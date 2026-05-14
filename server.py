import os
import time

import requests
from flask import Flask, jsonify, render_template, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

API_KEY = (
    os.environ.get("ODDS_API_KEY")
    or os.environ.get("THE_ODDS_API_KEY")
    or os.environ.get("API_KEY")
    or ""
)
CACHE_TTL_SECONDS = int(os.environ.get("ODDS_CACHE_TTL_SECONDS", "300"))
REQUEST_TIMEOUT_SECONDS = int(os.environ.get("ODDS_REQUEST_TIMEOUT_SECONDS", "15"))

SPORTS = [
    "basketball_nba",
    "baseball_mlb",
    "icehockey_nhl",
    "soccer_usa_mls",
    "americanfootball_nfl",
]
SPORT_LABELS = {
    "basketball_nba": "NBA",
    "baseball_mlb": "MLB",
    "icehockey_nhl": "NHL",
    "soccer_usa_mls": "MLS",
    "americanfootball_nfl": "NFL",
}
SHARP_BOOKS = ["pinnacle", "circa", "bookmaker", "betonlineag", "bovada", "betfair_ex_eu"]
ALL_SOFT_BOOKS = [
    "betmgm",
    "draftkings",
    "fanduel",
    "caesars",
    "betrivers",
    "espnbet",
    "betparx",
    "ballybet",
    "hardrockbet",
    "pointsbet",
    "fliff",
    "mybookieag",
]
BOOK_NAMES = {
    "betmgm": "BetMGM",
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "caesars": "Caesars",
    "betrivers": "BetRivers",
    "espnbet": "ESPN Bet",
    "betparx": "betPARX",
    "ballybet": "Bally Bet",
    "hardrockbet": "Hard Rock",
    "pointsbet": "PointsBet",
    "fliff": "Fliff",
    "mybookieag": "MyBookie",
}
MARKETS = ["h2h", "spreads", "totals"]
MARKET_LABELS = {"h2h": "ML", "spreads": "Spread", "totals": "Total"}

odds_cache = {}
last_api_usage = {}


def api_configured():
    return bool(API_KEY)


def american_to_decimal(odds):
    return odds / 100 + 1 if odds > 0 else 100 / abs(odds) + 1


def implied_prob(decimal_odds):
    return 1 / decimal_odds


def calc_ev(true_prob, decimal_odds):
    return ((true_prob * (decimal_odds - 1)) - (1 - true_prob)) * 100


def outcome_key(outcome):
    name = str(outcome.get("name", "")).strip()
    point = outcome.get("point")
    return f"{name}|{point}" if point not in ("", None) else name


def outcome_label(outcome):
    name = str(outcome.get("name", "")).strip()
    point = outcome.get("point")
    return f"{name} {point}" if point not in ("", None) else name


def parse_float_param(name, default):
    try:
        return float(request.args.get(name, default))
    except (TypeError, ValueError):
        return default


def parse_csv_param(name, allowed_values, default_values):
    raw = request.args.get(name, "")
    if not raw:
        return default_values

    allowed = set(allowed_values)
    values = [value.strip() for value in raw.split(",") if value.strip()]
    filtered = [value for value in values if value in allowed]
    return filtered or default_values


def request_usage_from_headers(headers):
    usage = {}
    for key, value in headers.items():
        lower_key = key.lower()
        if lower_key.startswith("x-requests"):
            usage[lower_key] = value
    return usage


def get_sharp_probs(bookmakers, market_key):
    sharp_sources = []

    for book in bookmakers:
        if book.get("key") not in SHARP_BOOKS:
            continue

        for market in book.get("markets", []):
            if market.get("key") != market_key:
                continue

            outcomes = market.get("outcomes", [])
            priced_outcomes = [outcome for outcome in outcomes if outcome.get("price")]
            if not priced_outcomes:
                continue

            total = sum(
                implied_prob(american_to_decimal(outcome["price"]))
                for outcome in priced_outcomes
            )
            if total == 0:
                continue

            sharp_sources.append(
                {
                    outcome_key(outcome): implied_prob(american_to_decimal(outcome["price"])) / total
                    for outcome in priced_outcomes
                }
            )

    if not sharp_sources:
        return None

    combined = {}
    counts = {}
    for source in sharp_sources:
        for key, probability in source.items():
            combined[key] = combined.get(key, 0) + probability
            counts[key] = counts.get(key, 0) + 1

    return {key: combined[key] / counts[key] for key in combined}


def fetch_odds(sport, market_key, force_refresh=False):
    global last_api_usage

    cache_key = f"{sport}:{market_key}"
    now = time.time()
    cached = odds_cache.get(cache_key)

    if cached and not force_refresh and now - cached["fetched_at"] < CACHE_TTL_SECONDS:
        return {
            "data": cached["data"],
            "from_cache": True,
            "made_request": False,
            "usage": cached.get("usage", {}),
            "error": None,
        }

    if not api_configured():
        return {
            "data": None,
            "from_cache": False,
            "made_request": False,
            "usage": {},
            "error": "Missing Odds API key. Set ODDS_API_KEY in Render or your local environment.",
        }

    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"
    params = {
        "apiKey": API_KEY,
        "regions": "us,us2,eu,au",
        "markets": market_key,
        "oddsFormat": "american",
    }

    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        usage = request_usage_from_headers(response.headers)
        if usage:
            last_api_usage = usage

        try:
            data = response.json()
        except ValueError:
            return {
                "data": None,
                "from_cache": False,
                "made_request": True,
                "usage": usage,
                "error": f"{SPORT_LABELS.get(sport, sport)} {MARKET_LABELS.get(market_key, market_key)} returned invalid JSON.",
            }

        if response.status_code >= 400 or not isinstance(data, list):
            if isinstance(data, dict):
                message = data.get("message") or data.get("error") or str(data)
            else:
                message = str(data)
            return {
                "data": None,
                "from_cache": False,
                "made_request": True,
                "usage": usage,
                "error": f"{SPORT_LABELS.get(sport, sport)} {MARKET_LABELS.get(market_key, market_key)}: {message}",
            }

        odds_cache[cache_key] = {"data": data, "fetched_at": now, "usage": usage}
        return {
            "data": data,
            "from_cache": False,
            "made_request": True,
            "usage": usage,
            "error": None,
        }
    except requests.RequestException as exc:
        return {
            "data": None,
            "from_cache": False,
            "made_request": True,
            "usage": {},
            "error": f"{SPORT_LABELS.get(sport, sport)} {MARKET_LABELS.get(market_key, market_key)}: {exc}",
        }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/tracker")
def tracker():
    return render_template("tracker.html")


@app.route("/health")
def health():
    return jsonify({"ok": True, "apiConfigured": api_configured()})


@app.route("/config")
def config():
    return jsonify(
        {
            "apiConfigured": api_configured(),
            "cacheTtlSeconds": CACHE_TTL_SECONDS,
            "sports": [{"key": key, "label": SPORT_LABELS[key]} for key in SPORTS],
            "markets": [{"key": key, "label": MARKET_LABELS[key]} for key in MARKETS],
            "books": [{"key": key, "label": BOOK_NAMES.get(key, key)} for key in ALL_SOFT_BOOKS],
        }
    )


@app.route("/scan")
def scan():
    min_ev = parse_float_param("min_ev", 3.0)
    max_ev = parse_float_param("max_ev", 10.0)
    sports = parse_csv_param("sports", SPORTS, SPORTS)
    markets = parse_csv_param("markets", MARKETS, MARKETS)
    soft_books = parse_csv_param("books", ALL_SOFT_BOOKS, ALL_SOFT_BOOKS)
    force_refresh = request.args.get("refresh", "").lower() in {"1", "true", "yes"}

    all_bets = []
    scanned_games = set()
    errors = []
    request_count = 0
    cache_hits = 0
    cache_misses = 0

    for sport in sports:
        for market_key in markets:
            odds_response = fetch_odds(sport, market_key, force_refresh=force_refresh)

            if odds_response["made_request"]:
                request_count += 1
            if odds_response["from_cache"]:
                cache_hits += 1
            elif odds_response["data"] is not None:
                cache_misses += 1

            if odds_response["usage"]:
                last_api_usage.update(odds_response["usage"])
            if odds_response["error"]:
                errors.append(odds_response["error"])
                continue

            data = odds_response["data"] or []
            for game in data:
                home = game.get("home_team", "")
                away = game.get("away_team", "")
                game_id = game.get("id") or f"{sport}:{away}:{home}"
                scanned_games.add(game_id)

                bookmakers = game.get("bookmakers", [])
                sharp_probs = get_sharp_probs(bookmakers, market_key)
                if not sharp_probs:
                    continue

                for book in bookmakers:
                    book_key = book.get("key")
                    if book_key not in soft_books:
                        continue

                    for market in book.get("markets", []):
                        if market.get("key") != market_key:
                            continue

                        for outcome in market.get("outcomes", []):
                            odds = outcome.get("price")
                            if odds is None:
                                continue

                            true_prob = sharp_probs.get(outcome_key(outcome))
                            if not true_prob:
                                continue

                            decimal_odds = american_to_decimal(odds)
                            ev = calc_ev(true_prob, decimal_odds)
                            if not min_ev <= ev <= max_ev:
                                continue

                            label = outcome_label(outcome)
                            all_bets.append(
                                {
                                    "key": f"{game_id}:{market_key}:{book_key}:{label}:{odds}",
                                    "game": f"{away} @ {home}",
                                    "bet": label,
                                    "type": MARKET_LABELS[market_key],
                                    "market": market_key,
                                    "sport": SPORT_LABELS.get(sport, sport),
                                    "book": BOOK_NAMES.get(book_key, book_key),
                                    "bookKey": book_key,
                                    "odds": odds,
                                    "trueProb": round(true_prob * 100, 1),
                                    "ev": round(ev, 2),
                                    "commenceTime": game.get("commence_time"),
                                }
                            )

    seen = set()
    unique = []
    for bet in all_bets:
        dedupe_key = f"{bet['game']}|{bet['bet']}|{bet['type']}|{bet['book']}|{bet['odds']}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        unique.append(bet)

    unique.sort(key=lambda bet: bet["ev"], reverse=True)
    return jsonify(
        {
            "bets": unique,
            "games": len(scanned_games),
            "sports": sports,
            "markets": markets,
            "requestCount": request_count,
            "cacheHits": cache_hits,
            "cacheMisses": cache_misses,
            "cacheTtlSeconds": CACHE_TTL_SECONDS,
            "apiUsage": last_api_usage,
            "errors": errors,
            "apiConfigured": api_configured(),
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
