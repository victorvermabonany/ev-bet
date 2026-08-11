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

from flask import Flask, Response, jsonify, render_template, request
from flask_cors import CORS

from astrology import career, places, reading
from astrology.chart import BirthData, build_chart

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

CACHE_LIMIT = 256
_chart_cache: OrderedDict[str, tuple] = OrderedDict()

# PRD open question 3 (pricing). Kept as config so it can be changed without a
# deploy, and so the paywall copy has a single source of truth.
PRICE_LABEL = os.environ.get("ASTRO_PRICE_LABEL", "$5.99/mo")


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


@app.route("/")
def index():
    return render_template("index.html", price_label=PRICE_LABEL)


@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "aiConfigured": reading.api_configured(),
        "model": reading.MODEL,
        "voice": reading.VOICE,
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
    payload = request.get_json(silent=True) or {}
    tier = "paid" if payload.get("tier") == "paid" else "free"
    chart, profile, timing = _parse_birth(payload)
    result = reading.generate(chart, profile, timing, tier)
    return jsonify(result.to_dict())


@app.route("/api/question", methods=["POST"])
def api_question():
    """Stream an answer to a specific career question (paid tier)."""
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()
    if not question:
        raise BadRequest("question is required")
    if len(question) > 500:
        raise BadRequest("question must be under 500 characters")

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


@app.route("/api/config")
def api_config():
    return jsonify({
        "aiConfigured": reading.api_configured(),
        "priceLabel": PRICE_LABEL,
        "voice": reading.VOICE,
    })


if __name__ == "__main__":
    # Warm the city index at boot so the first search isn't slow.
    places.search("London", 1)
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=bool(os.environ.get("ASTRO_DEBUG")))
