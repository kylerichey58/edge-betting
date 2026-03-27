"""
==============================================================================
WOMENS BASKETBALL ANALYZER — Women's D1 College Basketball
==============================================================================
Fetches ALL D1 women's games today with live DraftKings betting lines.
Filters and highlights major conference matchups for analysis.

HOW TO RUN:
    python womens_basketball_analyzer.py

WHAT IT DOES:
    1. Fetches today's NCAAW schedule from The Odds API (DraftKings lines)
    2. Fetches ALL D1 women's games from ESPN (even those without odds)
    3. Merges both sources into a unified view
    4. Highlights major conference games with full betting lines
    5. Lists remaining D1 games with game info only

REQUIREMENTS:
    pip install requests python-dotenv
    .env file with ODDS_API_KEY=your_key
==============================================================================
"""

import os
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# ── API KEYS ─────────────────────────────────────────────────────────────────
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

# ── CONSTANTS ─────────────────────────────────────────────────────────────────
ODDS_API_BASE    = "https://api.the-odds-api.com/v4"
ESPN_BASE        = "https://site.api.espn.com/apis/site/v2/sports/basketball/womens-college-basketball"
SPORT_KEY        = "basketball_ncaaw"
BOOKMAKER        = "draftkings"

MAJOR_CONFERENCES = {
    "SEC":       ["Alabama", "Arkansas", "Auburn", "Florida", "Georgia", "Kentucky",
                  "LSU", "Mississippi", "Mississippi State", "Missouri", "Ole Miss",
                  "South Carolina", "Tennessee", "Texas", "Texas A&M", "Vanderbilt"],
    "ACC":       ["Boston College", "California", "Clemson", "Duke", "Florida State",
                  "Georgia Tech", "Louisville", "Miami", "NC State", "North Carolina",
                  "Notre Dame", "Pittsburgh", "SMU", "Stanford", "Syracuse",
                  "Virginia", "Virginia Tech", "Wake Forest"],
    "Big Ten":   ["Illinois", "Indiana", "Iowa", "Maryland", "Michigan",
                  "Michigan State", "Minnesota", "Nebraska", "Northwestern", "Ohio State",
                  "Oregon", "Penn State", "Purdue", "Rutgers", "UCLA",
                  "USC", "Washington", "Wisconsin"],
    "Big 12":    ["Arizona", "Arizona State", "BYU", "Baylor", "Cincinnati",
                  "Colorado", "Houston", "Iowa State", "Kansas", "Kansas State",
                  "Oklahoma", "Oklahoma State", "TCU", "Texas Tech", "UCF",
                  "Utah", "West Virginia"],
    "Big East":  ["Butler", "Connecticut", "Creighton", "DePaul", "Georgetown",
                  "Marquette", "Providence", "St. John's", "Seton Hall",
                  "UConn", "Villanova", "Xavier"],
    "Pac-12":    ["Arizona", "Arizona State", "California", "Colorado", "Oregon",
                  "Oregon State", "Stanford", "UCLA", "USC", "Utah",
                  "Washington", "Washington State"],
}

ALL_MAJOR = set(t for teams in MAJOR_CONFERENCES.values() for t in teams)


# ── HELPERS ───────────────────────────────────────────────────────────────────

def is_major_conf_game(home: str, away: str) -> tuple[bool, str]:
    """Return (True, conference_name) if either team is in a major conference."""
    for conf, teams in MAJOR_CONFERENCES.items():
        if any(t.lower() in home.lower() or t.lower() in away.lower() for t in teams):
            return True, conf
    return False, ""


def fmt_odds(val) -> str:
    """Format American odds with + or - sign."""
    if val is None:
        return "N/A"
    return f"+{val}" if val > 0 else str(val)


def fmt_time(iso_str: str) -> str:
    """Convert ISO timestamp to readable ET time."""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        et_offset = -5  # EST (adjust to -4 for EDT in spring/summer)
        from datetime import timedelta
        et = dt + timedelta(hours=et_offset)
        return et.strftime("%-I:%M %p ET")
    except Exception:
        return iso_str


# ── DATA FETCHERS ─────────────────────────────────────────────────────────────

def fetch_odds_api_games() -> list[dict]:
    """Pull today's NCAAW games with DraftKings lines from The Odds API."""
    if not ODDS_API_KEY:
        print("⚠️  No ODDS_API_KEY found in .env — skipping odds data.")
        return []

    url = f"{ODDS_API_BASE}/sports/{SPORT_KEY}/odds"
    params = {
        "apiKey":      ODDS_API_KEY,
        "regions":     "us",
        "markets":     "spreads,totals,h2h",
        "bookmakers":  BOOKMAKER,
        "oddsFormat":  "american",
        "dateFormat":  "iso",
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        remaining = resp.headers.get("x-requests-remaining", "?")
        print(f"  ✅ Odds API — {len(data)} games found | Requests remaining: {remaining}")
        return data
    except Exception as e:
        print(f"  ❌ Odds API error: {e}")
        return []


def fetch_espn_games() -> list[dict]:
    """Pull today's full NCAAW schedule from ESPN (no odds, just game info)."""
    url = f"{ESPN_BASE}/scoreboard"
    params = {"limit": 200, "dates": datetime.now().strftime("%Y%m%d")}

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        events = resp.json().get("events", [])
        print(f"  ✅ ESPN — {len(events)} total D1 women's games today")
        return events
    except Exception as e:
        print(f"  ❌ ESPN error: {e}")
        return []


# ── PARSER ────────────────────────────────────────────────────────────────────

def parse_odds_game(game: dict) -> dict:
    """Extract spread, total, moneyline from a single Odds API game entry."""
    result = {
        "home":       game.get("home_team", ""),
        "away":       game.get("away_team", ""),
        "time":       fmt_time(game.get("commence_time", "")),
        "spread_home": None, "spread_away": None,
        "spread_line": None,
        "total":       None,
        "ml_home":     None, "ml_away":     None,
        "has_odds":    False,
    }

    for bm in game.get("bookmakers", []):
        if bm.get("key") != BOOKMAKER:
            continue
        result["has_odds"] = True
        for mkt in bm.get("markets", []):
            key = mkt.get("key")
            outcomes = {o["name"]: o for o in mkt.get("outcomes", [])}

            if key == "spreads":
                h = outcomes.get(result["home"])
                a = outcomes.get(result["away"])
                if h:
                    result["spread_home"] = h.get("point")
                    result["spread_line"] = fmt_odds(h.get("price"))
                if a:
                    result["spread_away"] = a.get("point")

            elif key == "totals":
                over = outcomes.get("Over")
                if over:
                    result["total"] = over.get("point")

            elif key == "h2h":
                h = outcomes.get(result["home"])
                a = outcomes.get(result["away"])
                if h:
                    result["ml_home"] = fmt_odds(h.get("price"))
                if a:
                    result["ml_away"] = fmt_odds(a.get("price"))

    return result


def parse_espn_game(event: dict) -> dict:
    """Extract basic game info from an ESPN event."""
    comp = event.get("competitions", [{}])[0]
    competitors = comp.get("competitors", [])
    home = next((c for c in competitors if c.get("homeAway") == "home"), {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), {})

    status = event.get("status", {}).get("type", {}).get("description", "Scheduled")
    start  = comp.get("startDate", "")

    return {
        "home":   home.get("team", {}).get("displayName", ""),
        "away":   away.get("team", {}).get("displayName", ""),
        "time":   fmt_time(start),
        "status": status,
        "venue":  comp.get("venue", {}).get("fullName", ""),
    }


# ── DISPLAY ───────────────────────────────────────────────────────────────────

def print_header():
    now = datetime.now().strftime("%A, %B %d, %Y")
    print("\n" + "=" * 70)
    print(f"  🏀  WOMEN'S D1 BASKETBALL ANALYZER  |  {now}")
    print("=" * 70)


def print_major_game(game: dict, conf: str, idx: int):
    home = game["home"]
    away = game["away"]
    time = game["time"]

    spread_info = "No line posted"
    total_info  = ""
    ml_info     = ""

    if game.get("has_odds"):
        sh = game.get("spread_home")
        sa = game.get("spread_away")
        sl = game.get("spread_line", "-110")
        tot = game.get("total")
        mlh = game.get("ml_home")
        mla = game.get("ml_away")

        if sh is not None:
            fav   = home if sh < 0 else away
            dog   = away if sh < 0 else home
            pts   = abs(sh)
            spread_info = f"{fav} -{pts} ({sl}) | {dog} +{pts}"
        if tot:
            total_info = f"  O/U: {tot}"
        if mlh and mla:
            ml_info = f"  ML: {home} {mlh} / {away} {mla}"

    print(f"\n  [{idx}] {away} @ {home}  —  {time}  [{conf}]")
    print(f"       📊 Spread: {spread_info}{total_info}")
    if ml_info:
        print(f"       💰{ml_info}")


def print_other_game(game: dict, idx: int):
    print(f"  [{idx:>3}] {game['away']:30} @ {game['home']:30}  {game['time']}")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print_header()
    print("\n🔄 Fetching data...")

    odds_games  = fetch_odds_api_games()
    espn_events = fetch_espn_games()

    # Parse all sources
    odds_parsed = [parse_odds_game(g) for g in odds_games]
    espn_parsed = [parse_espn_game(e) for e in espn_events]

    # Build lookup from odds data keyed by (home, away) normalized
    def norm(s):
        return s.lower().strip()

    odds_lookup = {
        (norm(g["home"]), norm(g["away"])): g
        for g in odds_parsed
    }

    # Merge ESPN into unified list, attach odds if available
    major_games = []
    other_games = []

    seen = set()

    for eg in espn_parsed:
        home = eg["home"]
        away = eg["away"]
        key  = (norm(home), norm(away))

        if key in seen:
            continue
        seen.add(key)

        # Attach odds if available
        odds = odds_lookup.get(key, {})
        merged = {**eg, **odds, "home": home, "away": away}
        if not odds:
            merged["has_odds"] = False

        is_major, conf = is_major_conf_game(home, away)
        if is_major:
            major_games.append((merged, conf))
        else:
            other_games.append(merged)

    # Also add any odds-only games not in ESPN (rare but possible)
    for og in odds_parsed:
        key = (norm(og["home"]), norm(og["away"]))
        if key not in seen:
            seen.add(key)
            is_major, conf = is_major_conf_game(og["home"], og["away"])
            if is_major:
                major_games.append((og, conf))
            else:
                other_games.append(og)

    # Sort major games by conference priority
    conf_order = {"SEC": 0, "ACC": 1, "Big Ten": 2, "Big 12": 3, "Big East": 4, "Pac-12": 5}
    major_games.sort(key=lambda x: (conf_order.get(x[1], 9), x[0].get("time", "")))

    # ── PRINT MAJOR CONFERENCE GAMES ──────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"  ⭐  MAJOR CONFERENCE GAMES  ({len(major_games)} matchups)")
    print(f"{'=' * 70}")

    if not major_games:
        print("  No major conference games found today.")
    else:
        current_conf = None
        idx = 1
        for game, conf in major_games:
            if conf != current_conf:
                print(f"\n  ── {conf} {'─' * (50 - len(conf))}")
                current_conf = conf
            print_major_game(game, conf, idx)
            idx += 1

    # ── PRINT ALL OTHER D1 GAMES ──────────────────────────────────────────────
    print(f"\n{'=' * 70}")
    print(f"  📋  ALL OTHER D1 WOMEN'S GAMES  ({len(other_games)} games)")
    print(f"{'=' * 70}\n")

    if not other_games:
        print("  No other D1 games found today.")
    else:
        other_games.sort(key=lambda x: x.get("time", ""))
        for i, game in enumerate(other_games, 1):
            print_other_game(game, i)

    # ── SUMMARY ───────────────────────────────────────────────────────────────
    with_odds = sum(1 for g, _ in major_games if g.get("has_odds"))
    print(f"\n{'=' * 70}")
    print(f"  📊 SUMMARY")
    print(f"  • Major conference games:  {len(major_games)}")
    print(f"  • Games with DK odds:      {with_odds}")
    print(f"  • Other D1 games:          {len(other_games)}")
    print(f"  • Total D1 games today:    {len(major_games) + len(other_games)}")
    print(f"{'=' * 70}")
    print(f"\n  ✅ Copy 3-5 major conference games and paste to Claude for")
    print(f"     full 8-metric analysis. Include the spread and total!\n")


if __name__ == "__main__":
    main()
