import os
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

API_KEY = "3e5b743ec48cf85d6598ddbe25267bfc"

SPORTS = ["basketball_nba", "baseball_mlb", "icehockey_nhl", "soccer_usa_mls"]
SHARP_BOOKS = ["pinnacle", "circa", "bookmaker", "betonlineag", "bovada", "betfair_ex_eu"]
SOFT_BOOKS = ["betmgm", "draftkings", "fanduel"]
BOOK_NAMES = {"betmgm": "BetMGM", "draftkings": "DraftKings", "fanduel": "FanDuel"}
MARKETS = ["h2h", "spreads", "totals"]
MARKET_LABELS = {"h2h": "ML", "spreads": "Spread", "totals": "Total"}

@app.route("/")
def index():
    from flask import render_template
    return render_template("index.html")
