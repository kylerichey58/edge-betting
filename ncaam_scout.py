"""
ncaam_scout.py — EDGE Betting Intelligence Platform
NCAA Men's Basketball Game Scout
------------------------------------------------------------
Fetches today's NCAAM games from The Odds API (DraftKings lines),
filters to major conferences + March Madness bracket teams,
formats output for Cowork to feed into the Scouting Report tab.

Usage:
    python ncaam_scout.py              # Today's games
    python ncaam_scout.py --date 2026-03-27  # Specific date
    python ncaam_scout.py --mode mm   # March Madness bracket only
    python ncaam_scout.py --all       # All games (no conference filter)

Output:
    - Console: formatted game list for quick review
    - ncaam_games_output.json: structured data for Cowork → Scouting Report
    - ncaam_games_readable.txt: clean paste-ready format for Claude analysis
"""

import os
import sys
import json
import argparse
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# ─── CONFIG ──────────────────────────────────────────────────────────────────

ODDS_API_KEY  = os.getenv("ODDS_API_KEY")
SPORT_KEY     = "basketball_ncaab"
REGIONS       = "us"
MARKETS       = "spreads,totals,h2h"
ODDS_FORMAT   = "american"
DATE_FORMAT   = "%Y-%m-%dT%H:%M:%SZ"

# Major conferences filter (regular season mode)
MAJOR_CONFERENCES = [
    # Power 4
    "Big Ten", "Big 12", "SEC", "ACC",
    # High-major additions
    "Big East", "Pac-12", "American Athletic",
    # Common abbreviations that may appear in team names / API data
    "Big Ten Conference", "Southeastern Conference",
    "Atlantic Coast Conference", "Big 12 Conference",
]

# Power 4 teams — used for filtering when conference data isn't available from API
POWER4_TEAMS = {
    # ACC
    "Duke", "North Carolina", "NC State", "Wake Forest", "Virginia",
    "Virginia Tech", "Notre Dame", "Clemson", "Syracuse", "Louisville",
    "Georgia Tech", "Boston College", "Miami", "Pittsburgh", "Florida State",
    # Big Ten
    "Michigan", "Michigan State", "Ohio State", "Penn State", "Indiana",
    "Purdue", "Illinois", "Iowa", "Minnesota", "Nebraska", "Northwestern",
    "Wisconsin", "Maryland", "Rutgers", "UCLA", "USC", "Washington",
    "Oregon", "Oregon State",
    # Big 12
    "Kansas", "Baylor", "Texas", "Texas Tech", "Oklahoma", "Oklahoma State",
    "TCU", "Iowa State", "West Virginia", "Kansas State", "BYU",
    "Cincinnati", "UCF", "Houston", "Arizona", "Arizona State", "Utah",
    "Colorado",
    # SEC
    "Kentucky", "Tennessee", "Alabama", "Auburn", "Florida", "Georgia",
    "LSU", "Mississippi State", "Ole Miss", "South Carolina", "Vanderbilt",
    "Missouri", "Texas A&M", "Arkansas",
    # Big East
    "UConn", "Villanova", "Marquette", "St. John's", "Seton Hall",
    "Providence", "Georgetown", "Xavier", "Butler", "DePaul", "Creighton",
}

# March Madness bracket — update after Selection Sunday each year
# Set MARCH_MADNESS_MODE = True after bracket is set
MARCH_MADNESS_MODE = False  # Flip to True on Selection Sunday

MM_BRACKET_FILE = "mm_bracket_2026.json"  # External file, updated on Selection Sunday

def load_mm_bracket():
    """Load March Madness bracket teams from external JSON file."""
    if os.path.exists(MM_BRACKET_FILE):
        with open(MM_BRACKET_FILE, "r") as f:
            data = json.load(f)
            return set(data.get("teams", []))
    # Fallback: current Sweet 16 teams (March 27, 2026)
    return {
        # NCAAM Sweet 16 - 2026
        "Duke", "Alabama", "Houston", "UConn",
        "Auburn", "Michigan State", "Florida", "Maryland",
        "Texas Tech", "Purdue", "Marquette", "Kansas",
        "Tennessee", "Kentucky", "Arizona", "Wisconsin",
    }

# ─── ODDS API ────────────────────────────────────────────────────────────────

def fetch_games():
    """Fetch today's NCAAM games with DraftKings lines from The Odds API."""
    if not ODDS_API_KEY:
        print("❌  ERROR: ODDS_API_KEY not found in .env file.")
        print("    Add: ODDS_API_KEY=your_key_here")
        sys.exit(1)

    url = f"https://api.the-odds-api.com/v4/sports/{SPORT_KEY}/odds/"
    params = {
        "apiKey":      ODDS_API_KEY,
        "regions":     REGIONS,
        "markets":     MARKETS,
        "oddsFormat":  ODDS_FORMAT,
        "bookmakers":  "draftkings",
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        remaining = resp.headers.get("x-requests-remaining", "?")
        used      = resp.headers.get("x-requests-used", "?")
        print(f"✅  API connected — {remaining} requests remaining ({used} used)")
        return data
    except requests.exceptions.HTTPError as e:
        print(f"❌  API error: {e}")
        if resp.status_code == 401:
            print("    Check your ODDS_API_KEY in .env")
        elif resp.status_code == 422:
            print("    Sport key may be invalid or off-season")
        sys.exit(1)
    except requests.exceptions.ConnectionError:
        print("❌  No internet connection. Check your network.")
        sys.exit(1)

# ─── GAME PARSING ────────────────────────────────────────────────────────────

def parse_game(raw):
    """Extract structured data from a raw Odds API game object."""
    game = {
        "id":         raw.get("id", ""),
        "away":       raw.get("away_team", "Away"),
        "home":       raw.get("home_team", "Home"),
        "start_time": raw.get("commence_time", ""),
        "spread":     "N/A",
        "spread_away_juice": "N/A",
        "spread_home_juice": "N/A",
        "total":      "N/A",
        "over_juice":  "N/A",
        "under_juice": "N/A",
        "ml_away":    "N/A",
        "ml_home":    "N/A",
        "bookmaker":  "DraftKings",
    }

    # Format game time to EST display
    try:
        dt_utc = datetime.strptime(game["start_time"], DATE_FORMAT).replace(tzinfo=timezone.utc)
        from datetime import timedelta
        dt_est = dt_utc - timedelta(hours=4)  # UTC → EDT
        game["display_time"] = dt_est.strftime("%-I:%M %p ET")
        game["date"] = dt_est.strftime("%a %b %-d")
    except Exception:
        game["display_time"] = "TBD"
        game["date"] = "Today"

    # Parse bookmaker odds
    for bookmaker in raw.get("bookmakers", []):
        if bookmaker.get("key") != "draftkings":
            continue
        for market in bookmaker.get("markets", []):
            mkey = market.get("key")
            outcomes = market.get("outcomes", [])

            if mkey == "spreads":
                for o in outcomes:
                    if o["name"] == game["away"]:
                        game["spread"] = f"{game['away']} {o['point']:+.1f}"
                        game["spread_away_juice"] = str(o["price"])
                    elif o["name"] == game["home"]:
                        game["spread_home_juice"] = str(o["price"])

            elif mkey == "totals":
                for o in outcomes:
                    if o["name"] == "Over":
                        game["total"] = str(o["point"])
                        game["over_juice"] = str(o["price"])
                    elif o["name"] == "Under":
                        game["under_juice"] = str(o["price"])

            elif mkey == "h2h":
                for o in outcomes:
                    if o["name"] == game["away"]:
                        game["ml_away"] = str(o["price"])
                    elif o["name"] == game["home"]:
                        game["ml_home"] = str(o["price"])

    return game

# ─── FILTERING ───────────────────────────────────────────────────────────────

def is_major_conference_team(team_name):
    """Check if a team is in the Power 4 / major conference list."""
    for team in POWER4_TEAMS:
        if team.lower() in team_name.lower() or team_name.lower() in team.lower():
            return True
    return False

def is_mm_team(team_name, mm_teams):
    """Check if a team is in the March Madness bracket."""
    for team in mm_teams:
        if team.lower() in team_name.lower() or team_name.lower() in team.lower():
            return True
    return False

def filter_games(games, mode, mm_teams=None, show_all=False):
    """
    Filter games based on current mode:
    - 'regular': Power 4 + major conference teams only
    - 'mm': March Madness bracket teams only
    - show_all: bypass filter, return everything
    """
    if show_all:
        return games

    filtered = []
    for g in games:
        away, home = g["away"], g["home"]

        if mode == "mm" and mm_teams:
            if is_mm_team(away, mm_teams) or is_mm_team(home, mm_teams):
                filtered.append(g)
        else:
            # Regular season: at least one team is major conference
            if is_major_conference_team(away) or is_major_conference_team(home):
                filtered.append(g)

    return filtered

# ─── OUTPUT FORMATTING ───────────────────────────────────────────────────────

def format_console_output(games, mode):
    """Print formatted game list to console."""
    mode_label = "🏆 MARCH MADNESS" if mode == "mm" else "🏀 NCAAM MAJOR CONFERENCE"
    print(f"\n{'═'*62}")
    print(f"  EDGE BETTING INTELLIGENCE — {mode_label} GAMES")
    print(f"  {datetime.now().strftime('%A, %B %-d, %Y')}  |  {len(games)} games found")
    print(f"{'═'*62}\n")

    if not games:
        print("  No games found for today's slate.")
        print("  Check back later or run with --all to see all games.\n")
        return

    for i, g in enumerate(games, 1):
        spread_display = g["spread"] if g["spread"] != "N/A" else "Line TBD"
        total_display  = f"O/U {g['total']}" if g["total"] != "N/A" else "Total TBD"
        ml_display     = f"ML: {g['ml_away']} / {g['ml_home']}" if g["ml_away"] != "N/A" else ""

        print(f"  [{i}] {g['away']} @ {g['home']}")
        print(f"      📅 {g['date']}  ⏰ {g['display_time']}")
        print(f"      📊 Spread: {spread_display}  |  {total_display}")
        if ml_display:
            print(f"      💰 {ml_display}")
        if g["over_juice"] != "N/A":
            print(f"      🎯 Juice: Over {g['over_juice']} / Under {g['under_juice']}")
        print()

    print(f"{'─'*62}")
    print(f"  NEXT STEP: Paste 3-5 games into Claude → 'Analyze using all 8 metrics'")
    print(f"  OR: Let Cowork auto-scout and populate the Scouting Report tab.")
    print(f"{'─'*62}\n")

def build_readable_output(games, mode):
    """Build a clean paste-ready text block for Claude analysis."""
    lines = []
    mode_label = "MARCH MADNESS" if mode == "mm" else "NCAAM MAJOR CONFERENCE"
    lines.append(f"=== EDGE {mode_label} SLATE — {datetime.now().strftime('%B %-d, %Y')} ===\n")

    for i, g in enumerate(games, 1):
        spread = g["spread"] if g["spread"] != "N/A" else "Spread TBD"
        total  = f"O/U {g['total']}" if g["total"] != "N/A" else "Total TBD"
        ml     = f"ML {g['ml_away']} / {g['ml_home']}" if g["ml_away"] != "N/A" else ""

        lines.append(f"{i}. {g['away']} @ {g['home']}")
        lines.append(f"   Time: {g['display_time']}")
        lines.append(f"   Lines: {spread} | {total}" + (f" | {ml}" if ml else ""))
        lines.append("")

    lines.append("---")
    lines.append("Analyze these games using all 8 metrics (3PT%, Win% Context,")
    lines.append("OffReb%, Def Efficiency, Pace/Tempo, FT%, Bench Depth, Sharp Money).")
    lines.append("Provide star rating, confidence score, recommended bet, and unit size.")

    return "\n".join(lines)

def build_json_output(games, mode):
    """Build structured JSON for Cowork → Scouting Report tab."""
    output = {
        "generated_at": datetime.now().isoformat(),
        "sport": "NCAAM",
        "mode": mode,
        "game_count": len(games),
        "games": []
    }

    for g in games:
        output["games"].append({
            "id": f"ncaam_{g['id'][:8]}",
            "away": g["away"],
            "home": g["home"],
            "sport": "NCAAM",
            "time": g["display_time"],
            "date": g["date"],
            "spread": g["spread"],
            "total": g["total"],
            "ml_away": g["ml_away"],
            "ml_home": g["ml_home"],
            "over_juice": g["over_juice"],
            "under_juice": g["under_juice"],
            "status": "pending",
            "stars": 0,
            "confidence": 0,
            "betType": "spread",
            "recommendation": "RUN ANALYSIS",
            "units": "—",
            "metrics": [
                {"num": "01", "name": "3PT%",          "v": "neutral", "text": "Awaiting analysis"},
                {"num": "02", "name": "Win% Context",  "v": "neutral", "text": "Awaiting analysis"},
                {"num": "03", "name": "Off Reb%",      "v": "neutral", "text": "Awaiting analysis"},
                {"num": "04", "name": "Def Efficiency","v": "neutral", "text": "Awaiting analysis"},
                {"num": "05", "name": "Pace/Tempo",    "v": "neutral", "text": "Awaiting analysis"},
                {"num": "06", "name": "FT%",           "v": "neutral", "text": "Awaiting analysis"},
                {"num": "07", "name": "Bench Depth",   "v": "neutral", "text": "Awaiting analysis"},
                {"num": "08", "name": "Sharp Money",   "v": "neutral", "text": "Check Action Network"}
            ],
            "sharpAlert": "Check Action Network for public betting % before finalizing.",
            "summary": f"Run 8-metric analysis on {g['away']} @ {g['home']} in Game Scout tab.",
            "monteCarlo": {"winProb": 50, "projTotal": "—", "edge": "—"}
        })

    return output

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="EDGE NCAAM Game Scout")
    parser.add_argument("--mode", choices=["regular", "mm"], default="regular",
                        help="regular = Power 4 filter | mm = March Madness bracket only")
    parser.add_argument("--all", action="store_true",
                        help="Show all NCAAM games (no conference filter)")
    parser.add_argument("--output-json", default="ncaam_games_output.json",
                        help="Path for JSON output file (for Cowork)")
    parser.add_argument("--output-txt", default="ncaam_games_readable.txt",
                        help="Path for readable text output (for Claude paste)")
    args = parser.parse_args()

    # Auto-detect March Madness mode
    mode = args.mode
    if MARCH_MADNESS_MODE and mode == "regular":
        mode = "mm"
        print("📌  March Madness mode active (MARCH_MADNESS_MODE = True)")

    mm_teams = load_mm_bracket() if mode == "mm" else None

    print(f"\n🔍  Fetching NCAAM games from The Odds API...")
    raw_games = fetch_games()
    print(f"    Found {len(raw_games)} total NCAAM games in API response")

    parsed = [parse_game(g) for g in raw_games]
    filtered = filter_games(parsed, mode, mm_teams, show_all=args.all)

    print(f"    After filter ({mode} mode): {len(filtered)} games")

    # Console output
    format_console_output(filtered, mode)

    # Save JSON for Cowork
    json_data = build_json_output(filtered, mode)
    with open(args.output_json, "w") as f:
        json.dump(json_data, f, indent=2)
    print(f"✅  JSON saved → {args.output_json}  ({len(filtered)} games)")

    # Save readable text for Claude paste
    readable = build_readable_output(filtered, mode)
    with open(args.output_txt, "w") as f:
        f.write(readable)
    print(f"✅  Readable output → {args.output_txt}")
    print(f"\n💡  TIP: Open {args.output_txt} and paste into Claude Game Scout tab.")
    print(f"    Or let Cowork auto-scout → populate Scouting Report tab.\n")

if __name__ == "__main__":
    main()
