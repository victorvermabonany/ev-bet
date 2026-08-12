"""Flask app for the career astrology reader.

Deliberately stateless: the client holds the birth data and posts it with each
request. No database, no accounts, no stored birth records -- which is both the
simplest thing that works and the right default for data this personal.

Charts are cached in memory by birth data so the second call in a session is
free; the cache is a bounded dict rather than anything that outlives the process.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import threading
from collections import OrderedDict

from flask import Flask, Response, g, jsonify, render_template, request
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from astrology import career, dashboard, entitlements, places, ratelimit, reading, sky, whop_api
from astrology.chart import BirthData, build_chart

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)

# Render (and every other PaaS) terminates TLS at the edge and forwards plain
# HTTP. Without this, request.is_secure is False on an HTTPS site, which meant
# the session cookie -- the bearer token for paid access -- shipped without the
# Secure flag. Trust exactly one hop, the platform's own proxy.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_for=1)

# Cross-origin access is off by default. The API only ever serves this app's own
# page, and leaving it open let any site drive the (billable) reading endpoint.
# Set ASTRO_ALLOWED_ORIGINS to a comma-separated list to opt specific ones in.
_allowed_origins = [
    o.strip() for o in os.environ.get("ASTRO_ALLOWED_ORIGINS", "").split(",") if o.strip()
]
if _allowed_origins:
    CORS(app, origins=_allowed_origins, supports_credentials=True)

CACHE_LIMIT = 256
_chart_cache: OrderedDict[str, tuple] = OrderedDict()

# Generated readings, keyed by chart + tier. Without this every page refresh was
# a fresh Opus generation of up to 8k tokens -- the single largest cost in the
# product, paid again for output the user had already seen.
READING_CACHE_LIMIT = 512
_reading_cache: OrderedDict[str, dict] = OrderedDict()

# Per-hour ceilings. The reading and question endpoints cost real money on every
# miss, so they are the tight ones; charts are only CPU.
RATE_LIMITS = {
    "reading": int(os.environ.get("ASTRO_LIMIT_READING", "20")),
    "question": int(os.environ.get("ASTRO_LIMIT_QUESTION", "40")),
    "chart": int(os.environ.get("ASTRO_LIMIT_CHART", "120")),
    "checkout": int(os.environ.get("ASTRO_LIMIT_CHECKOUT", "20")),
    "claim": int(os.environ.get("ASTRO_LIMIT_CLAIM", "10")),
}
RATE_WINDOW = 3600


def _client_ip() -> str:
    """The caller's address, trusting exactly the one proxy hop ProxyFix does."""
    return request.remote_addr or "unknown"


def enforce_limit(bucket: str, identity: str | None = None):
    """Apply the bucket's ceiling. Returns a 429 response, or None to continue.

    Skipped under TESTING so the suite is not fighting a shared counter; the
    limiter itself is covered directly in tests/test_ratelimit.py.
    """
    if app.testing:
        return None
    decision = ratelimit.check(
        bucket, identity or _client_ip(), RATE_LIMITS[bucket], RATE_WINDOW
    )
    if decision.allowed:
        return None
    log.warning("rate limit hit: bucket=%s identity=%s", bucket, identity or _client_ip())
    response = jsonify({
        "error": "You've made a lot of requests in a short time. "
                 "Try again in a few minutes.",
        "retryAfter": decision.retry_after,
    })
    response.status_code = 429
    response.headers["Retry-After"] = str(decision.retry_after)
    return response

# Whop pricing. Plan IDs come from astro/scripts/setup_whop.sh; the labels live
# here so the paywall copy has one source of truth and can change without a
# deploy. If the plan IDs are unset the paywall still renders and simply says
# checkout is unconfigured -- it never grants access as a fallback.
WHOP_PLANS = [
    {
        "key": "weekly",
        "planId": os.environ.get("WHOP_WEEKLY_PLAN_ID", ""),
        "name": "Weekly",
        "price": os.environ.get("WHOP_WEEKLY_PRICE", "$7.99"),
        "cadence": "per week",
        "trialDays": int(os.environ.get("WHOP_TRIAL_DAYS", "3")),
        "note": "Cancel anytime.",
        "highlighted": True,
    },
    {
        "key": "annual",
        "planId": os.environ.get("WHOP_ANNUAL_PLAN_ID", ""),
        "name": "Annual",
        "price": os.environ.get("WHOP_ANNUAL_PRICE", "$89"),
        "cadence": "per year",
        "trialDays": 0,
        "note": "Billed once a year.",
        "highlighted": False,
    },
]


class BadRequest(Exception):
    """A client-side input problem, reported as 400 rather than 500."""


@app.errorhandler(BadRequest)
def _handle_bad_request(exc: BadRequest):
    return jsonify({"error": str(exc)}), 400


def _parse_birth(payload: dict):
    """Validate and resolve a birth-data payload into a computed chart."""
    if not isinstance(payload, dict):
        raise BadRequest("expected a JSON object")

    name = (payload.get("name") or "").strip()[:80]

    raw_date = (payload.get("date") or "").strip()
    try:
        birth_date = dt.date.fromisoformat(raw_date)
    except ValueError:
        raise BadRequest("birth date must be YYYY-MM-DD") from None

    if not dt.date(1900, 1, 1) <= birth_date <= dt.date.today():
        raise BadRequest("birth date must be between 1900 and today")

    time_known = bool(payload.get("timeKnown", True))
    raw_time = (payload.get("time") or "").strip()
    if time_known:
        try:
            hour, minute = raw_time.split(":")
            birth_time = dt.time(int(hour), int(minute))
        except (ValueError, AttributeError):
            raise BadRequest("birth time must be HH:MM") from None
    else:
        birth_time = dt.time(12, 0)

    latitude = payload.get("latitude")
    longitude = payload.get("longitude")
    timezone_name = (payload.get("timezone") or "").strip()
    place_label = (payload.get("place") or "").strip()

    if latitude is None or longitude is None:
        # The client normally sends coordinates from the picker; fall back to
        # resolving the typed string so the API is usable on its own.
        matches = places.search(place_label, 1)
        if not matches:
            raise BadRequest(
                f"We couldn't find a city matching \"{place_label}\". "
                f"Try the nearest large town, or check the spelling."
            )
        chosen = matches[0]
        latitude, longitude = chosen.latitude, chosen.longitude
        timezone_name = timezone_name or chosen.timezone
        place_label = chosen.label

    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        raise BadRequest("latitude and longitude must be numbers") from None

    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise BadRequest("coordinates out of range")

    if not timezone_name:
        timezone_name = places.timezone_for(latitude, longitude)

    key = hashlib.sha256(
        json.dumps(
            [name, birth_date.isoformat(), birth_time.isoformat(), time_known,
             round(latitude, 4), round(longitude, 4), timezone_name],
            sort_keys=True,
        ).encode()
    ).hexdigest()

    if key in _chart_cache:
        _chart_cache.move_to_end(key)
        return (key, *_chart_cache[key])

    try:
        moment = places.resolve_moment(birth_date, birth_time, timezone_name)
    except ValueError as exc:
        raise BadRequest(str(exc)) from None

    birth = BirthData(
        name=name,
        date=birth_date,
        time=birth_time,
        time_known=time_known,
        place_label=place_label or f"{latitude:.2f}, {longitude:.2f}",
        latitude=latitude,
        longitude=longitude,
        timezone=timezone_name,
    )

    chart = build_chart(birth, moment)
    profile = career.build_profile(chart)
    timing = career.timing_summary(chart)

    result = (chart, profile, timing)
    _chart_cache[key] = result
    _chart_cache.move_to_end(key)
    while len(_chart_cache) > CACHE_LIMIT:
        _chart_cache.popitem(last=False)
    return (key, *result)


def whop_config() -> dict:
    return {
        "productId": os.environ.get("WHOP_PRODUCT_ID", ""),
        "plans": WHOP_PLANS,
        # False until the plan IDs exist, which is what the front end keys off
        # to decide whether the CTA can open a real checkout at all.
        # Checkout needs both the plan IDs and a server-side API key: the
        # metadata that links a purchase to a session can only be attached by a
        # checkout configuration, which the server has to create.
        "configured": all(p["planId"] for p in WHOP_PLANS) and whop_api.configured(),
    }


def session_id() -> str:
    """The caller's session token, minted on first sight.

    Stashed on the request so a single request only ever mints one, and the
    after-request hook knows whether it needs to set the cookie.
    """
    existing = request.cookies.get(entitlements.COOKIE_NAME)
    if existing:
        return existing
    minted = getattr(g, "new_session_id", None)
    if minted is None:
        minted = entitlements.new_session_id()
        g.new_session_id = minted
    return minted


@app.after_request
def _persist_session(response):
    minted = getattr(g, "new_session_id", None)
    if minted:
        response.set_cookie(
            entitlements.COOKIE_NAME,
            minted,
            max_age=entitlements.COOKIE_MAX_AGE,
            httponly=True,        # never readable from JavaScript
            samesite="Lax",       # survives the return trip from Whop checkout
            # Secure unless this is genuinely a local plaintext session. With
            # ProxyFix in place is_secure reflects X-Forwarded-Proto, so a
            # deployed site always sets it; ASTRO_INSECURE_COOKIE is the escape
            # hatch for testing over plain HTTP on a LAN address.
            secure=request.is_secure or not os.environ.get("ASTRO_INSECURE_COOKIE"),
        )
    return response


@app.route("/")
def index():
    session_id()  # ensure a visitor has a token before they reach checkout
    # Rendered server-side rather than fetched: the live sky is the first proof
    # of the page's own claim, so it should be in the HTML on arrival rather
    # than popping in after a round trip. Cached for ten minutes upstream.
    return render_template("index.html", sky=sky.cached_snapshot())


# Render sets this on every deploy. Surfacing it makes "is my fix actually
# live?" answerable without guessing from behaviour.
BUILD = (os.environ.get("RENDER_GIT_COMMIT") or "dev")[:7]


@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "build": BUILD,
        # Whether the datasets a chart needs are loaded yet. A cold worker
        # answers this endpoint instantly while still warming in the background.
        "warm": places.is_warm(),
        "warmStage": places.warm_stage(),
        "aiConfigured": reading.api_configured(),
        "model": reading.MODEL,
        "voice": reading.VOICE,
        "whopConfigured": whop_config()["configured"],
        **(_warm_diagnosis() if request.args.get("deep") else {}),
    })


def _warm_diagnosis() -> dict:
    """Why the warm-up is where it is, for /health?deep=1.

    The deployed worker sat on one stage for ten minutes where it takes 1.4s
    locally, and there is no log access from here. Guessing at that from the
    outside costs a deploy per hypothesis; the thread's own stack answers it in
    one. Read-only and behind a query flag, so it costs a normal request
    nothing.
    """
    import sys
    import traceback

    frames = sys._current_frames()
    stacks = {}
    for thread in threading.enumerate():
        frame = frames.get(thread.ident)
        if frame is None:
            continue
        stacks[thread.name] = [
            f"{os.path.basename(f.filename)}:{f.lineno} {f.name}"
            for f in traceback.extract_stack(frame)[-6:]
        ]

    return {
        "diagnosis": {
            "indexPath": places.INDEX_PATH,
            "indexFileExists": os.path.exists(places.INDEX_PATH),
            "dbOpen": places._db is not None,
            "memoryIndexBuilt": places._index_cache is not None,
            "threads": stacks,
        }
    }


@app.route("/api/places")
def api_places():
    query = request.args.get("q", "")
    return jsonify({"results": [p.to_dict() for p in places.search(query, 8)]})


@app.route("/api/chart", methods=["POST"])
def api_chart():
    limited = enforce_limit("chart")
    if limited:
        return limited
    _key, chart, profile, timing = _parse_birth(request.get_json(silent=True) or {})
    return jsonify({
        "chart": chart.to_dict(),
        "profile": profile.to_dict(),
        "timing": timing,
    })


def _reading_for(key, chart, profile, timing, tier):
    """A reading for this chart and tier, from cache when we already have one.

    Returns (result, was_cached, limit_response). Same chart, same tier -> same
    reading, which is what stops a refresh (or a script) from billing another
    Opus generation. The cache is checked before the rate limit is spent, so
    repeat views never count against the caller.
    """
    cache_key = f"{key}:{tier}"
    cached = _reading_cache.get(cache_key)
    if cached is not None:
        _reading_cache.move_to_end(cache_key)
        return cached, True, None

    limited = enforce_limit("reading")
    if limited:
        return None, False, limited

    result = reading.generate(chart, profile, timing, tier).to_dict()
    _reading_cache[cache_key] = result
    _reading_cache.move_to_end(cache_key)
    while len(_reading_cache) > READING_CACHE_LIMIT:
        _reading_cache.popitem(last=False)
    return result, False, None


@app.route("/api/reading", methods=["POST"])
def api_reading():
    """Return a reading at whatever tier this session has actually paid for.

    The client no longer has any say in this. It used to pass `tier`, which
    meant the paywall was one crafted request away from being bypassed; the
    parameter is now ignored entirely and the tier is derived from a membership
    recorded by a signed Whop webhook.
    """
    payload = request.get_json(silent=True) or {}
    access = entitlements.entitlement(session_id())
    tier = "paid" if access["entitled"] else "free"

    key, chart, profile, timing = _parse_birth(payload)
    result, cached, limited = _reading_for(key, chart, profile, timing, tier)
    if limited:
        return limited
    return jsonify({**result, "entitlement": access, "cached": cached})


@app.route("/api/dashboard", methods=["POST"])
def api_dashboard():
    """Everything the post-signup dashboard renders, at this session's tier.

    Shares the reading cache with /api/reading, so landing on the dashboard and
    then opening the full chart costs one generation rather than two.
    """
    payload = request.get_json(silent=True) or {}
    access = entitlements.entitlement(session_id())
    tier = "paid" if access["entitled"] else "free"

    key, chart, profile, timing = _parse_birth(payload)
    result, cached, limited = _reading_for(key, chart, profile, timing, tier)
    if limited:
        return limited

    return jsonify({
        **dashboard.build(chart, profile, timing, result["content"], tier),
        "birth": chart.birth.to_dict() if hasattr(chart.birth, "to_dict") else None,
        "source": result.get("source"),
        "entitlement": access,
        "cached": cached,
    })


@app.route("/api/question", methods=["POST"])
def api_question():
    """Stream an answer to a specific career question (paid tier)."""
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()
    if not question:
        raise BadRequest("question is required")
    if len(question) > 500:
        raise BadRequest("question must be under 500 characters")

    if not entitlements.entitlement(session_id())["entitled"]:
        return jsonify({"error": "This needs an active subscription."}), 402

    # Keyed by session, not IP: a subscriber has paid for this, and several of
    # them can legitimately share an office address.
    limited = enforce_limit("question", session_id())
    if limited:
        return limited

    _key, chart, profile, timing = _parse_birth(payload)

    def stream():
        try:
            for chunk in reading.answer_question(chart, profile, timing, question):
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        except Exception as exc:  # noqa: BLE001
            log.exception("question stream failed")
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        yield "data: [DONE]\n\n"

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/entitlement")
def api_entitlement():
    """What this session is allowed to see. The UI's only source of truth."""
    return jsonify(entitlements.entitlement(session_id()))


@app.route("/api/checkout", methods=["POST"])
def api_checkout():
    """Hand the browser the metadata to attach to a Whop checkout.

    The session token travels into checkout as metadata so Whop's webhook can
    hand it back and tell us which visitor just paid. This is the whole of the
    identity mechanism: no password, no email, no account.
    """
    limited = enforce_limit("checkout")
    if limited:
        return limited

    payload = request.get_json(silent=True) or {}
    plan_key = payload.get("plan")
    plan = next((p for p in WHOP_PLANS if p["key"] == plan_key), None)
    if plan is None or not plan["planId"]:
        raise BadRequest("unknown or unconfigured plan")

    sid = session_id()
    try:
        checkout_id = whop_api.create_checkout_configuration(
            plan["planId"], {"sid": sid}
        )
    except whop_api.WhopError as exc:
        log.error("could not create checkout configuration: %s", exc)
        return jsonify({"error": "checkout is unavailable right now"}), 502

    return jsonify({"checkoutSessionId": checkout_id, "planId": plan["planId"]})


@app.route("/api/whop/webhook", methods=["POST"])
def api_whop_webhook():
    """Receive membership events from Whop.

    This endpoint is the only thing that can grant paid access, so it verifies
    an HMAC signature over the raw body and fails closed: with no secret
    configured it rejects everything. An unauthenticated endpoint that grants
    access would be a worse hole than the client-side flag it replaces, because
    nobody would ever see it happen.
    """
    raw = request.get_data()
    ok, reason = entitlements.verify_webhook(raw, request.headers)
    if not ok:
        log.warning("rejected whop webhook: %s", reason)
        return jsonify({"error": "invalid signature"}), 401

    try:
        payload = json.loads(raw.decode() or "{}")
    except ValueError:
        raise BadRequest("body must be JSON") from None

    result = entitlements.apply_event(payload)
    log.info(
        "whop webhook %s -> %s",
        result.get("event"),
        result.get("action") or result.get("reason"),
    )
    # Always 200 on a verified event: a non-2xx makes Whop retry, and retrying
    # will not fix a payload we could not match to anything.
    return jsonify({"received": True, "applied": result.get("applied", False)})


@app.route("/api/claim", methods=["POST"])
def api_claim():
    """Attach a purchase made outside our checkout to this browser.

    Needed because not every purchase starts at /api/checkout -- a Whop product
    page, the marketplace, an affiliate link or a forwarded checkout URL all
    arrive with no session metadata. Those are recorded but unowned; this is how
    the buyer takes ownership, using the membership id from their Whop receipt.
    """
    limited = enforce_limit("claim")
    if limited:
        return limited

    payload = request.get_json(silent=True) or {}
    result = entitlements.claim(session_id(), payload.get("membershipId"))

    if not result["claimed"]:
        messages = {
            "not found": "We couldn't find that membership. Check the ID on your "
                         "Whop receipt and try again.",
            "not active": "That subscription isn't active any more.",
            "expired": "That subscription has expired.",
            "no membership id": "Enter the membership ID from your Whop receipt.",
            "no session": "Your browser isn't accepting cookies, so we can't "
                          "remember this. Enable them and try again.",
        }
        reason = result.get("reason", "")
        return jsonify({"error": messages.get(reason, "That didn't work.")}), 404

    return jsonify({"claimed": True, "entitlement": entitlements.entitlement(session_id())})


@app.route("/api/sky")
def api_sky():
    """Today's sky. Same payload the landing page is rendered from."""
    return jsonify(sky.cached_snapshot())


@app.route("/api/config")
def api_config():
    return jsonify({
        "aiConfigured": reading.api_configured(),
        "voice": reading.VOICE,
        "whop": whop_config(),
    })


entitlements.init()


def _warm_datasets() -> None:
    """Build the city index and timezone dataset before a user needs them.

    This used to sit under `if __name__ == "__main__"`, which gunicorn never
    executes -- so in production the 34k-city index was built lazily inside
    whichever request happened to arrive first, taking ~8s and 130 MB while the
    visitor was mid-keystroke.

    Runs on a background thread so the worker binds its port immediately and
    Render's health check passes straight away. Any request that lands during
    the build simply waits on the same lock rather than starting a second one.
    """
    def build():
        try:
            started = dt.datetime.now()
            places.warm()
            log.info(
                "warmed city index and timezone data in %.1fs",
                (dt.datetime.now() - started).total_seconds(),
            )
        except Exception:  # noqa: BLE001 - never take the worker down for this
            log.exception("dataset warm-up failed; first request will build them")

    # Claim the warm-up on this thread first. A request that arrives before the
    # thread below reaches the compile would otherwise see no warm-up in
    # progress and start its own in-memory build.
    places.mark_warming()
    threading.Thread(target=build, name="warm-datasets", daemon=True).start()


_warm_datasets()


def _rewarm_after_fork() -> None:
    """Start the warm-up again in a worker forked from a preloaded master.

    `gunicorn --preload` imports this module once and forks the workers from
    it, and a fork does not carry threads across. Without this the worker holds
    inherited state claiming a compile is running, no thread running one, and
    -- if the master had not finished before the fork -- no index either.

    Cheap when the master did finish: the child's warm() finds the compiled
    file already on disk and is ready in a file open.
    """
    places.reset_after_fork()
    _warm_datasets()


if hasattr(os, "register_at_fork"):   # POSIX only; Render is Linux
    os.register_at_fork(after_in_child=_rewarm_after_fork)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=bool(os.environ.get("ASTRO_DEBUG")))
