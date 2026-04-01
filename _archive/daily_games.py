import requests
import os
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ODDS_API_KEY")
EST = timezone(timedelta(hours=-5))

def get_ncaam_games():
    url = "https://api.the-odds-api.com/v4/sports/basketball_ncaab/odds"
    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": "h2h,spreads,totals",
        "oddsFormat": "american",
        "bookmakers": "draftkings",
    }

    print("\n  Fetching today's NCAAM games from DraftKings...\n")

    try:
        response = requests.get(url, params=params)
        data = response.json()
    except Exception as e:
        print(f"  ❌ Error fetching data: {e}")
        return

    if isinstance(data, dict) and "message" in data:
        print(f"  ❌ API Error: {data['message']}")
        return

    if not data:
        print("  No games found.")
        return

    # Filter to today's games in EST
    now_est = datetime.now(EST)
    today_str = now_est.strftime("%Y-%m-%d")

    today_games = []
    for game in data:
        tip_utc = datetime.fromisoformat(game["commence_time"].replace("Z", "+00:00"))
        tip_est = tip_utc.astimezone(EST)
        if tip_est.strftime("%Y-%m-%d") == today_str:
            today_games.append((game, tip_est))

    if not today_games:
        print(f"  No NCAAM games found for {today_str} (EST).")
        print(f"  Total games in API response: {len(data)}")
        print("  (Games may not be posted yet — try again later in the day.)")
        return

    # Sort by tip time
    today_games.sort(key=lambda x: x[1])

    print("=" * 65)
    print(f"  🏀 NCAAM GAMES — {today_str} (All times EST)")
    print(f"  Odds: DraftKings  |  {len(today_games)} games found")
    print("=" * 65)

    for game, tip_est in today_games:
        away = game["away_team"]
        home = game["home_team"]
        tip  = tip_est.strftime("%I:%M %p")

        # Pull DraftKings odds
        spread_away = spread_home = total = ml_away = ml_home = "N/A"

        for bookmaker in game.get("bookmakers", []):
            if bookmaker["key"] != "draftkings":
                continue
            for market in bookmaker.get("markets", []):
                if market["key"] == "spreads":
                    for outcome in market["outcomes"]:
                        if outcome["name"] == away:
                            spread_away = f"{outcome['point']:+.1f} ({outcome['price']:+d})"
                        elif outcome["name"] == home:
                            spread_home = f"{outcome['point']:+.1f} ({outcome['price']:+d})"
                elif market["key"] == "totals":
                    for outcome in market["outcomes"]:
                        if outcome["name"] == "Over":
                            total = f"O/U {outcome['point']} | OVER ({outcome['price']:+d})"
                        elif outcome["name"] == "Under":
                            total += f" / UNDER ({outcome['price']:+d})"
                elif market["key"] == "h2h":
                    for outcome in market["outcomes"]:
                        if outcome["name"] == away:
                            ml_away = f"{outcome['price']:+d}"
                        elif outcome["name"] == home:
                            ml_home = f"{outcome['price']:+d}"

        print(f"\n  {tip} | {away} @ {home}")
        print(f"  {'─'*55}")
        print(f"  Spread : {away} {spread_away}")
        print(f"           {home} {spread_home}")
        print(f"  Total  : {total}")
        print(f"  ML     : {away} {ml_away} | {home} {ml_home}")

    print(f"\n  {'─'*65}")
    print(f"  {len(today_games)} games | Copy any matchup and paste to Claude for analysis")
    print(f"  {'─'*65}\n")

    # API usage
    remaining = response.headers.get("x-requests-remaining", "?")
    used      = response.headers.get("x-requests-used", "?")
    print(f"  API calls used: {used} | Remaining: {remaining}\n")

if __name__ == "__main__":
    get_ncaam_games()
