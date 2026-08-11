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
from collections import OrderedDict

from flask import Flask, Response, g, jsonify, render_template, request
from flask_cors import CORS

from astrology import career, entitlements, places, reading, whop_api
from astrology.chart import BirthData, build_chart

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

CACHE_LIMIT = 256
_chart_cache: OrderedDict[str, tuple] = OrderedDict()

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
            raise BadRequest("could not resolve birth place -- pick one from the list")
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
        return _chart_cache[key]

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
    return result


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
            secure=not app.debug and request.is_secure,
        )
    return response


@app.route("/")
def index():
    session_id()  # ensure a visitor has a token before they reach checkout
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "aiConfigured": reading.api_configured(),
        "model": reading.MODEL,
        "voice": reading.VOICE,
        "whopConfigured": whop_config()["configured"],
    })


@app.route("/api/places")
def api_places():
    query = request.args.get("q", "")
    return jsonify({"results": [p.to_dict() for p in places.search(query, 8)]})


@app.route("/api/chart", methods=["POST"])
def api_chart():
    chart, profile, timing = _parse_birth(request.get_json(silent=True) or {})
    return jsonify({
        "chart": chart.to_dict(),
        "profile": profile.to_dict(),
        "timing": timing,
    })


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

    chart, profile, timing = _parse_birth(payload)
    result = reading.generate(chart, profile, timing, tier)
    return jsonify({**result.to_dict(), "entitlement": access})


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

    chart, profile, timing = _parse_birth(payload)

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


@app.route("/api/config")
def api_config():
    return jsonify({
        "aiConfigured": reading.api_configured(),
        "voice": reading.VOICE,
        "whop": whop_config(),
    })


entitlements.init()


if __name__ == "__main__":
    # Warm the city index at boot so the first search isn't slow.
    places.search("London", 1)
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=bool(os.environ.get("ASTRO_DEBUG")))
