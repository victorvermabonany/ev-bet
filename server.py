import os
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

API_KEY = os.environ.get("ODDS_API_KEY", "9ce39f64955e8bb570296ec801076b2a")

SPORTS = ["basketball_nba", "baseball_mlb", "icehockey_nhl", "soccer_usa_mls", "americanfootball_nfl"]
SHARP_BOOKS = ["pinnacle", "circa", "bookmaker", "betonlineag", "bovada", "betfair_ex_eu"]
SOFT_BOOKS = ["betmgm", "draftkings", "fanduel"]
BOOK_NAMES = {"betmgm": "BetMGM", "draftkings": "DraftKings", "fanduel": "FanDuel"}
MARKETS = ["h2h", "spreads", "totals"]
MARKET_LABELS = {"h2h": "ML", "spreads": "Spread", "totals": "Total"}

def american_to_decimal(o):
    return o / 100 + 1 if o > 0 else 100 / abs(o) + 1

def implied_prob(d):
    return 1 / d

def calc_ev(p, d):
    return ((p * (d - 1)) - (1 - p)) * 100

def get_sharp_prob(bookmakers, market_key):
    for sharp in SHARP_BOOKS:
        for book in bookmakers:
            if book["key"] != sharp:
                continue
            for market in book.get("markets", []):
                if market["key"] != market_key:
                    continue
                outcomes = market.get("outcomes", [])
                if not outcomes:
                    continue
                total = sum(implied_prob(american_to_decimal(o["price"])) for o in outcomes)
                if total == 0:
                    continue
                return {
                    (o.get("name", "") + str(o.get("point", ""))): implied_prob(american_to_decimal(o["price"])) / total
                    for o in outcomes
                }
    return None

@app.route("/scan")
def scan():
    min_ev = float(request.args.get("min_ev", 3.0))
    max_ev = float(request.args.get("max_ev", 10.0))
    all_bets = []
    total_games = 0

    for sport in SPORTS:
        for market_key in MARKETS:
            try:
                url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"
                params = {
                    "apiKey": API_KEY,
                    "regions": "us,us2,eu,au",
                    "markets": market_key,
                    "oddsFormat": "american",
                }
                res = requests.get(url, params=params, timeout=15)
                data = res.json()
                if not isinstance(data, list):
                    continue
                total_games += len(data)
                for game in data:
                    home = game.get("home_team", "")
                    away = game.get("away_team", "")
                    bookmakers = game.get("bookmakers", [])
                    sharp_probs = get_sharp_prob(bookmakers, market_key)
                    if not sharp_probs:
                        continue
                    for book in bookmakers:
                        if book["key"] not in SOFT_BOOKS:
                            continue
                        for market in book.get("markets", []):
                            if market["key"] != market_key:
                                continue
                            for outcome in market.get("outcomes", []):
                                team = outcome.get("name", "")
                                point = outcome.get("point", "")
                                odds = outcome["price"]
                                decimal = american_to_decimal(odds)
                                key = team + str(point)
                                true_prob = sharp_probs.get(key)
                                if not true_prob:
                                    continue
                                ev = calc_ev(true_prob, decimal)
                                if min_ev <= ev <= max_ev:
                                    label = f"{team} {point}" if point != "" else team
                                    all_bets.append({
                                        "game": f"{away} @ {home}",
                                        "bet": label,
                                        "type": MARKET_LABELS[market_key],
                                        "book": BOOK_NAMES.get(book["key"], book["key"]),
                                        "odds": odds,
                                        "trueProb": round(true_prob * 100, 1),
                                        "ev": round(ev, 2),
                                    })
            except Exception as e:
                print(f"Error {sport} {market_key}: {e}")

    seen = set()
    unique = []
    for b in all_bets:
        k = b["game"] + b["bet"] + b["book"]
        if k not in seen:
            seen.add(k)
            unique.append(b)

    unique.sort(key=lambda x: x["ev"], reverse=True)
    return jsonify({"bets": unique, "games": total_games})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
