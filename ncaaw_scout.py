"""
ncaaw_scout.py — EDGE Betting Intelligence Platform
NCAA Women's Basketball Game Scout
------------------------------------------------------------
Fetches today's NCAAW games from The Odds API (DraftKings lines)
+ ESPN for games not yet on the odds board.
Filters to major conferences + March Madness bracket teams.
Formats output for Cowork to feed into the Scouting Report tab.

KEY EDGE: NCAAW public betting data is THIN. That's your edge.
Markets are inefficient — especially on totals. Exploit it.

Usage:
    python ncaaw_scout.py              # Today's games
    python ncaaw_scout.py --mode mm   # March Madness bracket only
    python ncaaw_scout.py --all       # All D1 women's games

Output:
    - Console: formatted game list
    - ncaaw_games_output.json: structured data for Cowork -> Scouting Report
    - ncaaw_games_readable.txt: paste-ready format for Claude analysis
"""

import os
import sys
import json
import argparse
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# --- CONFIG ---

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
SPORT_KEY    = "basketball_ncaaw"
REGIONS      = "us"
MARKETS      = "spreads,totals,h2h"
ODDS_FORMAT  = "american"
DATE_FORMAT  = "%Y-%m-%dT%H:%M:%SZ"

ESPN_NCAAW_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/womens-college-basketball/scoreboard"

POWER4_TEAMS_W = {
    "Duke", "North Carolina", "NC State", "Virginia", "Virginia Tech",
    "Notre Dame", "Clemson", "Syracuse", "Louisville", "Georgia Tech",
    "Boston College", "Miami", "Pittsburgh", "Florida State", "Stanford",
    "California", "Wake Forest",
    "Michigan", "Michigan State", "Ohio State", "Penn State", "Indiana",
    "Purdue", "Illinois", "Iowa", "Minnesota", "Nebraska", "Northwestern",
    "Wisconsin", "Maryland", "Rutgers", "UCLA", "USC", "Washington",
    "Oregon", "Oregon State",
    "Kansas", "Baylor", "Texas", "Texas Tech", "Oklahoma", "Oklahoma State",
    "TCU", "Iowa State", "West Virginia", "Kansas State", "BYU",
    "Cincinnati", "UCF", "Houston", "Arizona", "Arizona State", "Utah",
    "Colorado",
    "Kentucky", "Tennessee", "Alabama", "Auburn", "Florida", "Georgia",
    "LSU", "Mississippi State", "Ole Miss", "South Carolina", "Vanderbilt",
    "Missouri", "Texas A&M", "Arkansas",
    "UConn", "Villanova", "Marquette", "Seton Hall",
    "Providence", "Georgetown", "Xavier", "Butler", "DePaul", "Creighton",
}

MARCH_MADNESS_MODE = False
MM_BRACKET_FILE_W  = "mm_bracket_w_2026.json"

def load_mm_bracket_w():
    if os.path.exists(MM_BRACKET_FILE_W):
        with open(MM_BRACKET_FILE_W, "r") as f:
            data = json.load(f)
            return set(data.get("teams", []))
    return {
        "UConn", "South Carolina", "UCLA", "LSU",
        "Notre Dame", "Tennessee", "Oregon", "Duke",
        "Iowa", "Texas", "Indiana", "NC State",
        "Kansas State", "Baylor", "Stanford", "Oklahoma",
    }

def fetch_odds_games():
    if not ODDS_API_KEY:
        print("WARNING: ODDS_API_KEY not found - will use ESPN data only.")
        return []
    url = f"https://api.the-odds-api.com/v4/sports/{SPORT_KEY}/odds/"
    params = {
        "apiKey":     ODDS_API_KEY,
        "regions":    REGIONS,
        "markets":    MARKETS,
        "oddsFormat": ODDS_FORMAT,
        "bookmakers": "draftkings",
    }
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        remaining = resp.headers.get("x-requests-remaining", "?")
        used = resp.headers.get("x-requests-used", "?")
        print(f"OK  Odds API connected - {remaining} requests remaining ({used} used)")
        return data
    except requests.exceptions.HTTPError as e:
        code = getattr(e.response, "status_code", 0)
        if code == 422:
            print("WARNING: NCAAW odds not available from API today")
        else:
            print(f"WARNING: Odds API error ({code}): {e}")
        return []
    except requests.exceptions.ConnectionError:
        print("ERROR: No internet connection.")
        sys.exit(1)

def fetch_espn_games():
    try:
        resp = requests.get(ESPN_NCAAW_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        events = data.get("events", [])
        games = []
        for event in events:
            comps = event.get("competitions", [{}])[0]
            competitors = comps.get("competitors", [])
            if len(competitors) < 2:
                continue
            home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
            away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
            home_name = home.get("team", {}).get("displayName", "Home")
            away_name = away.get("team", {}).get("displayName", "Away")
            start_raw = event.get("date", "")
            display_time = "TBD"
            date_str = "Today"
            try:
                dt_utc = datetime.strptime(start_raw, DATE_FORMAT).replace(tzinfo=timezone.utc)
                dt_est = dt_utc - timedelta(hours=4)
                display_time = dt_est.strftime("%I:%M %p ET").lstrip("0")
                date_str = dt_est.strftime("%a %b %d").replace(" 0", " ")
            except Exception:
                pass
            games.append({
                "id": event.get("id", ""),
                "away": away_name,
                "home": home_name,
                "display_time": display_time,
                "date": date_str,
                "spread": "Check DraftKings",
                "spread_away_juice": "N/A",
                "spread_home_juice": "N/A",
                "total": "Check DraftKings",
                "over_juice": "N/A",
                "under_juice": "N/A",
                "ml_away": "N/A",
                "ml_home": "N/A",
                "source": "ESPN",
            })
        print(f"OK  ESPN fallback: found {len(games)} NCAAW games")
        return games
    except Exception as e:
        print(f"WARNING: ESPN fetch failed: {e}")
        return []

def parse_odds_game(raw):
    game = {
        "id": raw.get("id", ""),
        "away": raw.get("away_team", "Away"),
        "home": raw.get("home_team", "Home"),
        "start_time": raw.get("commence_time", ""),
        "spread": "N/A",
        "spread_away_juice": "N/A",
        "spread_home_juice": "N/A",
        "total": "N/A",
        "over_juice": "N/A",
        "under_juice": "N/A",
        "ml_away": "N/A",
        "ml_home": "N/A",
        "source": "DraftKings",
    }
    try:
        dt_utc = datetime.strptime(game["start_time"], DATE_FORMAT).replace(tzinfo=timezone.utc)
        dt_est = dt_utc - timedelta(hours=4)
        game["display_time"] = dt_est.strftime("%I:%M %p ET").lstrip("0")
        game["date"] = dt_est.strftime("%a %b %d").replace(" 0", " ")
    except Exception:
        game["display_time"] = "TBD"
        game["date"] = "Today"

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

def is_power4_team(name):
    for team in POWER4_TEAMS_W:
        if team.lower() in name.lower() or name.lower() in team.lower():
            return True
    return False

def is_mm_team(name, mm_teams):
    for team in mm_teams:
        if team.lower() in name.lower() or name.lower() in team.lower():
            return True
    return False

def filter_games(games, mode, mm_teams=None, show_all=False):
    if show_all:
        return games
    filtered = []
    for g in games:
        away, home = g["away"], g["home"]
        if mode == "mm" and mm_teams:
            if is_mm_team(away, mm_teams) or is_mm_team(home, mm_teams):
                filtered.append(g)
        else:
            if is_power4_team(away) or is_power4_team(home):
                filtered.append(g)
    return filtered

def dedupe_games(odds_games, espn_games):
    seen = set()
    merged = []
    for g in odds_games:
        key = f"{g['away'].lower()}_{g['home'].lower()}"
        seen.add(key)
        merged.append(g)
    for g in espn_games:
        key = f"{g['away'].lower()}_{g['home'].lower()}"
        if key not in seen:
            seen.add(key)
            merged.append(g)
    return merged

def format_console_output(games, mode):
    mode_label = "MARCH MADNESS WOMENS" if mode == "mm" else "NCAAW MAJOR CONFERENCE"
    print("\n" + "="*62)
    print(f"  EDGE BETTING INTELLIGENCE -- {mode_label}")
    print(f"  {datetime.now().strftime('%A, %B %d, %Y')}  |  {len(games)} games")
    print("  NCAAW EDGE: Thin public data = exploitable totals market")
    print("="*62 + "\n")
    if not games:
        print("  No NCAAW games found for today's slate.\n")
        return
    for i, g in enumerate(games, 1):
        has_lines = g["total"] not in ("N/A", "Check DraftKings")
        spread_disp = g["spread"] if g["spread"] not in ("N/A", "Check DraftKings") else "Check DraftKings"
        total_disp = f"O/U {g['total']}" if has_lines else "Check DraftKings"
        source_tag = f"[{g.get('source', 'DK')}]"
        print(f"  [{i}] {g['away']} @ {g['home']}  {source_tag}")
        print(f"      Date: {g['date']}  Time: {g['display_time']}")
        print(f"      Spread: {spread_disp}  |  {total_disp}")
        if g["ml_away"] != "N/A":
            print(f"      ML: {g['ml_away']} / {g['ml_home']}")
        if g["over_juice"] != "N/A":
            print(f"      Juice: Over {g['over_juice']} / Under {g['under_juice']}")
        if not has_lines:
            print("      NOTE: Lines not yet posted - check DraftKings app")
        print()
    print("-"*62)
    print("  NCAAW: Thin markets = your edge. Hunt totals, especially unders.")
    print("  NEXT: Paste 3-5 games into Claude OR let Cowork auto-scout.")
    print("-"*62 + "\n")

def build_readable_output(games, mode):
    lines = []
    mode_label = "MARCH MADNESS WOMENS" if mode == "mm" else "NCAAW MAJOR CONFERENCE"
    lines.append(f"=== EDGE {mode_label} SLATE -- {datetime.now().strftime('%B %d, %Y')} ===")
    lines.append("NOTE: NCAAW markets are thin -- totals are the primary edge.\n")
    for i, g in enumerate(games, 1):
        spread = g["spread"] if g["spread"] not in ("N/A", "Check DraftKings") else "Check DK"
        total = f"O/U {g['total']}" if g["total"] not in ("N/A", "Check DraftKings") else "Check DK"
        ml = f"ML {g['ml_away']} / {g['ml_home']}" if g["ml_away"] != "N/A" else ""
        lines.append(f"{i}. {g['away']} @ {g['home']}")
        lines.append(f"   Time: {g['display_time']}")
        lines.append(f"   Lines: {spread} | {total}" + (f" | {ml}" if ml else ""))
        lines.append("")
    lines.append("---")
    lines.append("Analyze these NCAAW games using all 8 metrics.")
    lines.append("Note: NCAAW public betting data is thin. Weight metrics 1-7 heavily.")
    lines.append("Provide star rating, confidence score, recommended bet, and unit size.")
    return "\n".join(lines)

def build_json_output(games, mode):
    output = {
        "generated_at": datetime.now().isoformat(),
        "sport": "NCAAW",
        "mode": mode,
        "game_count": len(games),
        "edge_note": "NCAAW markets thin -- totals are primary edge.",
        "games": []
    }
    for g in games:
        has_lines = g["total"] not in ("N/A", "Check DraftKings")
        output["games"].append({
            "id": f"ncaaw_{g['id'][:8]}",
            "away": g["away"],
            "home": g["home"],
            "sport": "NCAAW",
            "time": g["display_time"],
            "date": g["date"],
            "spread": g["spread"],
            "total": g["total"] if has_lines else "TBD",
            "ml_away": g["ml_away"],
            "ml_home": g["ml_home"],
            "over_juice": g["over_juice"],
            "under_juice": g["under_juice"],
            "lines_available": has_lines,
            "source": g.get("source", "DraftKings"),
            "status": "pending",
            "stars": 0,
            "confidence": 0,
            "betType": "under",
            "recommendation": "RUN ANALYSIS",
            "units": "--",
            "metrics": [
                {"num": "01", "name": "3PT%", "v": "neutral", "text": "Awaiting analysis"},
                {"num": "02", "name": "Win% Context", "v": "neutral", "text": "Awaiting analysis"},
                {"num": "03", "name": "Off Reb%", "v": "neutral", "text": "Awaiting analysis"},
                {"num": "04", "name": "Def Efficiency", "v": "neutral", "text": "Awaiting analysis"},
                {"num": "05", "name": "Pace/Tempo", "v": "neutral", "text": "Awaiting analysis"},
                {"num": "06", "name": "FT%", "v": "neutral", "text": "Awaiting analysis"},
                {"num": "07", "name": "Bench Depth", "v": "neutral", "text": "Awaiting analysis"},
                {"num": "08", "name": "Sharp Money", "v": "neutral",
                 "text": "NCAAW market thin -- limited public data. Metrics 1-7 carry more weight."}
            ],
            "sharpAlert": "NCAAW public betting data is thin. Pure model edge on totals.",
            "summary": f"Run 8-metric analysis on {g['away']} @ {g['home']}. Focus on totals.",
            "monteCarlo": {"winProb": 50, "projTotal": "--", "edge": "--"}
        })
    return output

def main():
    parser = argparse.ArgumentParser(description="EDGE NCAAW Game Scout")
    parser.add_argument("--mode", choices=["regular", "mm"], default="regular")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--output-json", default="ncaaw_games_output.json")
    parser.add_argument("--output-txt", default="ncaaw_games_readable.txt")
    args = parser.parse_args()

    mode = args.mode
    if MARCH_MADNESS_MODE and mode == "regular":
        mode = "mm"
        print("March Madness mode active (MARCH_MADNESS_MODE = True)")

    mm_teams = load_mm_bracket_w() if mode == "mm" else None

    print("\nFetching NCAAW games...")

    raw_odds = fetch_odds_games()
    odds_games = [parse_odds_game(g) for g in raw_odds]
    espn_games = fetch_espn_games()
    all_games = dedupe_games(odds_games, espn_games)
    print(f"    Total merged: {len(all_games)} games ({len(odds_games)} with DK lines, {len(espn_games)} from ESPN)")

    filtered = filter_games(all_games, mode, mm_teams, show_all=args.all)
    print(f"    After filter ({mode} mode): {len(filtered)} games")

    format_console_output(filtered, mode)

    json_data = build_json_output(filtered, mode)
    with open(args.output_json, "w") as f:
        json.dump(json_data, f, indent=2)
    print(f"OK  JSON saved -> {args.output_json}  ({len(filtered)} games)")

    readable = build_readable_output(filtered, mode)
    with open(args.output_txt, "w") as f:
        f.write(readable)
    print(f"OK  Readable output -> {args.output_txt}")
    print(f"\nTIP: Open {args.output_txt} and paste into Claude Game Scout.")
    print("     Or let Cowork auto-scout -> populate Scouting Report tab.\n")

if __name__ == "__main__":
    main()
