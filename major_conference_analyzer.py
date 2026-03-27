"""
major_conference_analyzer.py — EDGE Betting Intelligence Platform
Fetches today's NCAAM Power 4 conference games from The Odds API,
displays DraftKings lines, highlights upcoming games, flags
same-conference matchups, and prints a paste-ready Claude
analysis block for 8-metric evaluation.

Usage: python major_conference_analyzer.py
Recommended: Run ~6 PM EST to catch full evening slate with posted lines.
"""

import os
import json
import requests
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")
EST     = timezone(timedelta(hours=-5))

# ─── Power 4 Conference Team Keywords ────────────────────────────────────────
# Substrings matched against team name strings returned by The Odds API.

POWER4_KEYWORDS = {
    "Big Ten": [
        "Illinois", "Indiana", "Iowa", "Maryland", "Michigan State", "Michigan",
        "Minnesota", "Nebraska", "Northwestern", "Ohio State", "Penn State",
        "Purdue", "Rutgers", "Wisconsin", "UCLA", "USC Trojans", "Washington",
        "Oregon Ducks",
    ],
    "Big 12": [
        "Baylor", "BYU", "Cincinnati", "Houston", "Iowa State", "Kansas State",
        "Kansas Jayhawks", "Kansas ", "Oklahoma State", "TCU", "Texas Tech",
        "UCF", "West Virginia", "Colorado Buffaloes", "Arizona State",
        "Arizona Wildcats", "Utah Utes",
    ],
    "SEC": [
        "Alabama", "Arkansas", "Auburn", "Florida Gators", "Georgia Bulldogs",
        "Kentucky", "LSU", "Mississippi State", "Missouri", "Ole Miss",
        "South Carolina", "Tennessee", "Texas Longhorns", "Texas A&M",
        "Vanderbilt", "Oklahoma Sooners",
    ],
    "ACC": [
        "Boston College", "Clemson", "Duke", "Florida State", "Georgia Tech",
        "Louisville", "Miami Hurricanes", "NC State", "Notre Dame",
        "North Carolina", "Pittsburgh", "Syracuse", "Virginia Tech",
        "Virginia Cavaliers", "Wake Forest", "California Golden Seals",
        "SMU Mustangs", "Stanford Cardinal",
    ],
    "Big East": [
        "Butler", "Creighton", "DePaul", "Georgetown", "Marquette",
        "Providence", "Seton Hall", "St. John's", "UConn", "Villanova",
        "Xavier",
    ],
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_conference(team_name: str) -> str | None:
    """Return conference name if team belongs to a Power 4 conference."""
    for conf, keywords in POWER4_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in team_name.lower():
                return conf
    return None

def is_power4_game(away: str, home: str) -> bool:
    """Return True if at least one team is in a Power 4 conference."""
    return get_conference(away) is not None or get_conference(home) is not None

def is_conf_matchup(away: str, home: str) -> bool:
    """Return True if both teams are in the same conference."""
    ca = get_conference(away)
    ch = get_conference(home)
    return ca is not None and ca == ch

def time_until_tip(tip_est: datetime, now_est: datetime) -> str:
    """Return a human-readable string for how far away tip-off is."""
    delta = tip_est - now_est
    total_minutes = int(delta.total_seconds() / 60)
    if total_minutes < 0:
        return "In progress / final"
    if total_minutes < 60:
        return f"{total_minutes}m until tip"
    hours   = total_minutes // 60
    minutes = total_minutes % 60
    if minutes == 0:
        return f"{hours}h until tip"
    return f"{hours}h {minutes}m until tip"

def extract_draftkings(game: dict) -> dict:
    """Pull spread, total, and moneyline from DraftKings bookmaker entry."""
    lines = {
        "spread_away": "N/A", "spread_home": "N/A",
        "total_line":  "N/A", "over_price":  "N/A", "under_price": "N/A",
        "ml_away":     "N/A", "ml_home":     "N/A",
    }
    for bk in game.get("bookmakers", []):
        if bk["key"] != "draftkings":
            continue
        for market in bk.get("markets", []):
            key = market["key"]
            for outcome in market.get("outcomes", []):
                name  = outcome["name"]
                price = outcome.get("price", 0)
                point = outcome.get("point", None)
                away  = game["away_team"]
                home  = game["home_team"]
                if key == "spreads":
                    if name == away:
                        lines["spread_away"] = f"{point:+.1f} ({price:+d})"
                    elif name == home:
                        lines["spread_home"] = f"{point:+.1f} ({price:+d})"
                elif key == "totals":
                    if name == "Over":
                        lines["total_line"] = str(point)
                        lines["over_price"] = f"{price:+d}"
                    elif name == "Under":
                        lines["under_price"] = f"{price:+d}"
                elif key == "h2h":
                    if name == away:
                        lines["ml_away"] = f"{price:+d}"
                    elif name == home:
                        lines["ml_home"] = f"{price:+d}"
    return lines

def build_game_block(record: dict) -> str:
    """Format a single game into a display block."""
    ln         = record["lines"]
    tip        = record["tip_est"]
    countdown  = record["countdown"]
    conf_away  = record.get("conf_away") or "—"
    conf_home  = record.get("conf_home") or "—"
    conf_label = f"  🔥 CONF GAME: {conf_away}" if record["conf_matchup"] else f"  {conf_away} vs {conf_home}"

    total_display = "N/A"
    if ln["total_line"] != "N/A":
        total_display = (
            f"O/U {ln['total_line']}  |  "
            f"OVER {ln['over_price']}  /  UNDER {ln['under_price']}"
        )

    lines = [
        f"  {tip}  ({countdown})",
        f"  {record['away_team']} ({conf_away})  @  {record['home_team']} ({conf_home})",
        conf_label,
        f"  {'─' * 65}",
        f"  Spread : {record['away_team']:<35} {ln['spread_away']}",
        f"           {record['home_team']:<35} {ln['spread_home']}",
        f"  Total  : {total_display}",
        f"  ML     : {record['away_team']} {ln['ml_away']}  |  {record['home_team']} {ln['ml_home']}",
    ]
    return "\n".join(lines)

def build_claude_paste_block(records: list[dict]) -> str:
    """
    Build a paste-ready text block for Claude 8-metric analysis.
    Format mirrors what the checklist recommends sending to Claude.
    """
    lines = [
        "Analyze these games using all 8 metrics. Focus on totals edge.",
        "",
    ]
    for r in records:
        ln = r["lines"]
        spread_str = "N/A"
        if ln["spread_away"] != "N/A":
            spread_str = (
                f"{r['away_team']} {ln['spread_away']}  /  "
                f"{r['home_team']} {ln['spread_home']}"
            )
        total_str = "N/A"
        if ln["total_line"] != "N/A":
            total_str = (
                f"O/U {ln['total_line']}  "
                f"(OVER {ln['over_price']} / UNDER {ln['under_price']})"
            )
        ml_str = f"{r['away_team']} {ln['ml_away']}  /  {r['home_team']} {ln['ml_home']}"

        conf_note = ""
        if r["conf_matchup"]:
            conf_note = f"  [CONF GAME — {r['conf_away']}]"

        lines += [
            f"Game: {r['away_team']} @ {r['home_team']}  —  {r['tip_est']}{conf_note}",
            f"  Spread : {spread_str}",
            f"  Total  : {total_str}",
            f"  ML     : {ml_str}",
            "",
        ]
    return "\n".join(lines)


# ─── Main ─────────────────────────────────────────────────────────────────────

def run():
    if not API_KEY:
        print("  ❌  ODDS_API_KEY not found in .env file.")
        return

    url = "https://api.the-odds-api.com/v4/sports/basketball_ncaab/odds"
    params = {
        "apiKey":     API_KEY,
        "regions":    "us",
        "markets":    "h2h,spreads,totals",
        "oddsFormat": "american",
        "bookmakers": "draftkings",
    }

    print("\n  Fetching NCAAM games from The Odds API (DraftKings) …\n")

    try:
        response = requests.get(url, params=params, timeout=15)
        data     = response.json()
    except Exception as e:
        print(f"  ❌  Request failed: {e}")
        return

    if isinstance(data, dict) and "message" in data:
        print(f"  ❌  API error: {data['message']}")
        return

    if not data:
        print("  No NCAAM games currently available in the API.")
        return

    # ── Filter to today (EST) ─────────────────────────────────────────────────
    now_est   = datetime.now(EST)
    today_str = now_est.strftime("%Y-%m-%d")

    today_games = []
    for game in data:
        tip_utc = datetime.fromisoformat(game["commence_time"].replace("Z", "+00:00"))
        tip_est = tip_utc.astimezone(EST)
        if tip_est.strftime("%Y-%m-%d") == today_str:
            today_games.append((game, tip_est))

    if not today_games:
        print(f"  No NCAAM games found for today ({today_str} EST).")
        print(f"  Total games in feed: {len(data)}  (may be future dates or no lines posted yet)\n")
        return

    today_games.sort(key=lambda x: x[1])

    # ── Filter to Power 4 ─────────────────────────────────────────────────────
    p4_games = [
        (g, t) for g, t in today_games
        if is_power4_game(g["away_team"], g["home_team"])
    ]

    # ── Split into upcoming vs already started ────────────────────────────────
    upcoming = [(g, t) for g, t in p4_games if t > now_est]
    started  = [(g, t) for g, t in p4_games if t <= now_est]

    remaining = response.headers.get("x-requests-remaining", "?")
    used      = response.headers.get("x-requests-used", "?")

    # ── Header ────────────────────────────────────────────────────────────────
    print("=" * 70)
    print(f"  🏀  MAJOR CONFERENCE ANALYZER — {today_str}  (EST)")
    print(f"  Power 4 Games Today: {len(p4_games)}  "
          f"|  Upcoming: {len(upcoming)}  |  Started/Final: {len(started)}")
    print(f"  Odds: DraftKings  |  Run time: {now_est.strftime('%I:%M %p EST')}")
    print("=" * 70)

    if not p4_games:
        print("\n  No Power 4 conference games found for today.\n")
        return

    # ── Build records ─────────────────────────────────────────────────────────
    records    = []
    txt_blocks = []

    # Show upcoming games first, then started
    for game, tip_est in (upcoming + started):
        away        = game["away_team"]
        home        = game["home_team"]
        lines       = extract_draftkings(game)
        conf_match  = is_conf_matchup(away, home)
        countdown   = time_until_tip(tip_est, now_est)

        record = {
            "game_id":      game.get("id"),
            "sport":        "NCAAM",
            "date":         today_str,
            "tip_est":      tip_est.strftime("%I:%M %p"),
            "away_team":    away,
            "home_team":    home,
            "conf_away":    get_conference(away),
            "conf_home":    get_conference(home),
            "conf_matchup": conf_match,
            "countdown":    countdown,
            "lines":        lines,
            "fetched_at":   now_est.strftime("%Y-%m-%d %H:%M:%S EST"),
        }
        records.append(record)

        block = build_game_block(record)
        txt_blocks.append(block)

    # ── Print upcoming ────────────────────────────────────────────────────────
    if upcoming:
        print(f"\n  ── UPCOMING GAMES ({len(upcoming)}) " + "─" * 48)
        for rec in records[:len(upcoming)]:
            print(f"\n{build_game_block(rec)}")

    # ── Print started/final ───────────────────────────────────────────────────
    if started:
        print(f"\n  ── STARTED / FINAL ({len(started)}) " + "─" * 47)
        for rec in records[len(upcoming):]:
            print(f"\n{build_game_block(rec)}")

    # ── Summary footer ────────────────────────────────────────────────────────
    conf_game_count = sum(1 for r in records if r["conf_matchup"])
    print(f"\n  {'─' * 70}")
    print(f"  {len(p4_games)} Power 4 games  |  {conf_game_count} conference matchups  "
          f"|  {len(upcoming)} upcoming")
    print(f"  API calls used: {used}  |  Remaining: {remaining}")
    print(f"  {'─' * 70}\n")

    # ── Paste-ready Claude block ──────────────────────────────────────────────
    if upcoming:
        paste_records = [r for r in records if r["countdown"] != "In progress / final"]
        print("  ┌" + "─" * 68 + "┐")
        print("  │  📋  COPY TO CLAUDE — paste below for 8-metric analysis" + " " * 12 + "│")
        print("  └" + "─" * 68 + "┘")
        print()
        print(build_claude_paste_block(paste_records))
        print("  " + "─" * 68)
        print("  Paste the block above into Claude:")
        print("  'Analyze these games using all 8 metrics. Focus on totals edge.'")
        print("  " + "─" * 68 + "\n")

    # ── Save JSON ─────────────────────────────────────────────────────────────
    json_path = os.path.join(os.path.dirname(__file__), "major_conference_output.json")
    with open(json_path, "w") as f:
        json.dump(records, f, indent=2)
    print(f"  ✅  JSON saved  →  major_conference_output.json  ({len(records)} games)")

    # ── Save TXT ──────────────────────────────────────────────────────────────
    txt_path = os.path.join(os.path.dirname(__file__), "major_conference_readable.txt")
    header = (
        f"MAJOR CONFERENCE ANALYZER — {today_str}\n"
        f"Odds: DraftKings  |  Power 4 Games: {len(p4_games)}  "
        f"|  Conference Matchups: {conf_game_count}\n"
        f"{'=' * 70}\n"
    )
    with open(txt_path, "w") as f:
        f.write(header + "\n")
        f.write("\n\n".join(txt_blocks))
        f.write(f"\n\n{'─' * 70}\n")
        f.write(f"Fetched: {now_est.strftime('%Y-%m-%d %H:%M:%S EST')}\n")
        f.write(f"API calls used: {used}  |  Remaining: {remaining}\n")
        if upcoming:
            f.write(f"\n{'─' * 70}\nCLAUDE PASTE BLOCK\n{'─' * 70}\n")
            paste_records = [r for r in records if r["countdown"] != "In progress / final"]
            f.write(build_claude_paste_block(paste_records))
    print(f"  ✅  TXT saved   →  major_conference_readable.txt\n")


if __name__ == "__main__":
    run()
