#!/usr/bin/env python3
"""
EDGE Betting Intelligence Platform
Bet Tracker v3.2 — Full Schema-Matched Edition
"""

import sqlite3
import os
from datetime import datetime
from db_utils import safe_write, safe_read

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sports_betting.db")

# ─────────────────────────────────────────────
#  SPORT DEFINITIONS
# ─────────────────────────────────────────────

ACTIVE_SPORTS = {
    "1": ("NCAAM", "NCAA Men's Basketball"),
    "2": ("NCAAW", "NCAA Women's Basketball"),
    "3": ("NBA",   "NBA Basketball"),
}

FUTURE_SPORTS = {
    "4": ("MLB",   "MLB Baseball          [FUTURE]"),
    "5": ("HORSE", "Horse Racing          [FUTURE]"),
    "6": ("NFL",   "NFL Football          [FUTURE]"),
    "7": ("NCAAF", "NCAA Football         [FUTURE]"),
}

ALL_SPORT_CODES = {**{k: v[0] for k, v in ACTIVE_SPORTS.items()},
                   **{k: v[0] for k, v in FUTURE_SPORTS.items()}}

# ─────────────────────────────────────────────
#  DATABASE SETUP
# ─────────────────────────────────────────────

def init_db():
    with safe_write() as conn:
        c = conn.cursor()

        # bets — matches your existing schema exactly
        c.execute("""
            CREATE TABLE IF NOT EXISTS bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_date TEXT,
                sport TEXT DEFAULT 'NCAAM',
                away_team TEXT,
                home_team TEXT,
                bet_type TEXT,
                bet_selection TEXT,
                odds TEXT,
                units REAL,
                confidence INTEGER,
                reasoning TEXT,
                game_id TEXT,
                logged_date TEXT,
                result TEXT DEFAULT 'PENDING',
                profit_loss REAL DEFAULT 0,
                final_score TEXT,
                notes TEXT
            )
        """)
        try:
            c.execute("ALTER TABLE bets ADD COLUMN sport TEXT DEFAULT 'NCAAM'")
        except sqlite3.OperationalError:
            pass

        # parlays — matches your existing schema exactly
        c.execute("""
            CREATE TABLE IF NOT EXISTS parlays (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                name TEXT,
                num_legs INTEGER,
                combined_odds INTEGER,
                units REAL,
                confidence INTEGER,
                reasoning TEXT,
                result TEXT DEFAULT 'PENDING',
                profit_loss REAL DEFAULT 0,
                notes TEXT,
                sport TEXT DEFAULT 'NCAAM'
            )
        """)
        try:
            c.execute("ALTER TABLE parlays ADD COLUMN sport TEXT DEFAULT 'NCAAM'")
        except sqlite3.OperationalError:
            pass

        # parlay_legs — matches your existing schema exactly
        c.execute("""
            CREATE TABLE IF NOT EXISTS parlay_legs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parlay_id INTEGER,
                leg_number INTEGER,
                sport TEXT,
                game TEXT,
                bet_type TEXT,
                selection TEXT,
                line TEXT,
                result TEXT DEFAULT 'PENDING',
                FOREIGN KEY (parlay_id) REFERENCES parlays(id)
            )
        """)
        # safe_write() context manager handles commit + writeback on exit


# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def calculate_pnl(units, odds_str, result):
    try:
        odds = int(str(odds_str).replace('+', ''))
    except (ValueError, TypeError):
        odds = -110
    if result == "WIN":
        if odds > 0:
            return round(units * (odds / 100), 2)
        else:
            return round(units * (100 / abs(odds)), 2)
    elif result == "LOSS":
        return round(-units, 2)
    return 0.0


def select_sport(label="Select sport"):
    print(f"\n  {label}:")
    print("  ─────────────────────────────────────")
    for key, (code, name) in ACTIVE_SPORTS.items():
        print(f"    [{key}] {code:<8} — {name}")
    print("  ─────────────────────────────────────")
    for key, (code, name) in FUTURE_SPORTS.items():
        print(f"    [{key}] {code:<8} — {name}")
    print()
    while True:
        choice = input("  Enter number (1-7): ").strip()
        if choice in ALL_SPORT_CODES:
            sport = ALL_SPORT_CODES[choice]
            if choice in FUTURE_SPORTS:
                confirm = input(f"  ⚠  '{sport}' is a future sport. Log anyway? (y/n): ").strip().lower()
                if confirm != "y":
                    continue
            return sport
        print("  Invalid selection. Try again.")


def stars(n):
    try:
        n = int(n)
    except:
        n = 2
    return "★" * n + "☆" * (4 - n)


# ─────────────────────────────────────────────
#  1. LOG STRAIGHT BET
# ─────────────────────────────────────────────

def log_straight_bet():
    print("\n" + "═" * 60)
    print("  LOG STRAIGHT BET")
    print("═" * 60)

    sport = select_sport("Sport")

    game_date = input("  Game date (YYYY-MM-DD) [today = Enter]: ").strip()
    if not game_date:
        game_date = datetime.now().strftime("%Y-%m-%d")

    away_team = input("  Away team: ").strip()
    home_team = input("  Home team: ").strip()

    print("\n  Bet Type:")
    print("    [1] Spread")
    print("    [2] Total (Over/Under)")
    print("    [3] Moneyline")
    bet_type = {"1": "SPREAD", "2": "TOTAL", "3": "MONEYLINE"}.get(
        input("  Select (1-3): ").strip(), "SPREAD")

    bet_selection = input("  Your pick (e.g. Duke -4.5 / UNDER 142.5): ").strip()
    odds = input("  Odds (e.g. -110 or +250): ").strip()

    try:
        units = float(input("  Units to bet (e.g. 1.5): ").strip())
    except ValueError:
        units = 1.0

    print("\n  Confidence:")
    for i in range(1, 5):
        print(f"    [{i}] {stars(i)} {i}-Star")
    try:
        confidence = int(input("  Select (1-4): ").strip())
        confidence = max(1, min(4, confidence))
    except ValueError:
        confidence = 3

    reasoning = input("  Reasoning: ").strip()
    notes = input("  Additional notes (Enter to skip): ").strip()

    print("\n" + "─" * 60)
    print(f"  PREVIEW")
    print("─" * 60)
    print(f"  Sport:      {sport}")
    print(f"  Date:       {game_date}")
    print(f"  Game:       {away_team} @ {home_team}")
    print(f"  Bet:        {bet_type} — {bet_selection} @ {odds}")
    print(f"  Units:      {units}u")
    print(f"  Confidence: {stars(confidence)} ({confidence}-Star)")
    print(f"  Reasoning:  {reasoning}")
    print("─" * 60)

    if input("  Log this bet? (y/n): ").strip().lower() != "y":
        print("  Cancelled.")
        return

    with safe_write() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO bets (game_date, sport, away_team, home_team, bet_type,
                              bet_selection, odds, units, confidence, reasoning,
                              logged_date, result, profit_loss, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, ?)
        """, (game_date, sport, away_team, home_team, bet_type,
              bet_selection, odds, units, confidence, reasoning,
              datetime.now().isoformat(), notes))
        bet_id = c.lastrowid
        # safe_write() context manager handles commit + writeback on exit
    print(f"\n  ✅ Bet #{bet_id} logged! ({sport} | {away_team} @ {home_team})")


# ─────────────────────────────────────────────
#  2. LOG PARLAY
# ─────────────────────────────────────────────

def log_parlay():
    print("\n" + "═" * 60)
    print("  LOG PARLAY")
    print("═" * 60)

    sport = select_sport("Sport (primary sport of this parlay)")

    date = input("  Date (YYYY-MM-DD) [today = Enter]: ").strip()
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    name = input("  Parlay name (e.g. Saturday 3-Legger): ").strip()

    try:
        combined_odds = int(input("  Combined odds (e.g. +425): ").strip().replace('+', ''))
    except ValueError:
        combined_odds = 0

    try:
        units = float(input("  Units to bet: ").strip())
    except ValueError:
        units = 1.0

    print("\n  Confidence:")
    for i in range(1, 5):
        print(f"    [{i}] {stars(i)} {i}-Star")
    try:
        confidence = int(input("  Select (1-4): ").strip())
        confidence = max(1, min(4, confidence))
    except ValueError:
        confidence = 3

    reasoning = input("  Reasoning: ").strip()
    notes = input("  Additional notes (Enter to skip): ").strip()

    try:
        num_legs = int(input("  How many legs? ").strip())
    except ValueError:
        num_legs = 2

    legs = []
    for i in range(1, num_legs + 1):
        print(f"\n  — LEG {i} —")
        leg_sport = sport
        leg_game = input("  Game (Away @ Home): ").strip()
        print("  Bet type: [1] Spread  [2] Total  [3] Moneyline")
        leg_type = {"1": "SPREAD", "2": "TOTAL", "3": "MONEYLINE"}.get(
            input("  Select: ").strip(), "SPREAD")
        leg_selection = input("  Pick: ").strip()
        leg_line = input("  Line (e.g. -4.5 or 142.5): ").strip()
        legs.append((i, leg_sport, leg_game, leg_type, leg_selection, leg_line))

    print("\n" + "─" * 60)
    print(f"  PARLAY PREVIEW — {name}")
    print("─" * 60)
    print(f"  Sport: {sport} | Date: {date} | Units: {units}u | Odds: +{combined_odds}")
    for i, ls, g, t, sel, ln in legs:
        print(f"  Leg {i}: [{t}] {sel}  ({g})")
    print("─" * 60)

    if input("  Log this parlay? (y/n): ").strip().lower() != "y":
        print("  Cancelled.")
        return

    with safe_write() as conn:
        c = conn.cursor()
        c.execute("""
            INSERT INTO parlays (date, sport, name, num_legs, combined_odds, units,
                                 confidence, reasoning, result, profit_loss, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, ?)
        """, (date, sport, name, num_legs, combined_odds, units,
              confidence, reasoning, notes))
        parlay_id = c.lastrowid

        for (leg_num, leg_sport, g, t, sel, ln) in legs:
            c.execute("""
                INSERT INTO parlay_legs
                    (parlay_id, leg_number, sport, game, bet_type, selection, line, result)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')
            """, (parlay_id, leg_num, leg_sport, g, t, sel, ln))
        # safe_write() context manager handles commit + writeback on exit
    print(f"\n  ✅ Parlay #{parlay_id} logged with {num_legs} legs! ({sport})")


# ─────────────────────────────────────────────
#  3. UPDATE STRAIGHT BET RESULT
# ─────────────────────────────────────────────

def update_straight_bet():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, game_date, sport, away_team, home_team, bet_selection, units, odds
        FROM bets WHERE result='PENDING' ORDER BY game_date
    """)
    pending = c.fetchall()
    conn.close()

    if not pending:
        print("\n  No pending straight bets.")
        return

    print("\n" + "═" * 60)
    print("  PENDING STRAIGHT BETS")
    print("═" * 60)
    for row in pending:
        bid, gdate, sport, away, home, sel, units, odds = row
        print(f"  [{bid}] {gdate} | {sport or '?':<6} | {away} @ {home} | {sel} | {units}u @ {odds}")

    try:
        bet_id = int(input("\n  Enter Bet ID to grade: ").strip())
    except ValueError:
        return

    print("  Result: [1] WIN  [2] LOSS  [3] PUSH")
    result = {"1": "WIN", "2": "LOSS", "3": "PUSH"}.get(
        input("  Select: ").strip(), "LOSS")

    final_score = input("  Final score (e.g. 78-71, Enter to skip): ").strip()

    # Read phase — use safe_read for the SELECT
    with safe_read() as rconn:
        rc = rconn.cursor()
        rc.execute("SELECT units, odds FROM bets WHERE id=?", (bet_id,))
        row = rc.fetchone()
    if not row:
        print("  Bet not found.")
        return

    units, odds = row[0], row[1]
    pnl = calculate_pnl(units, odds, result)

    # Write phase — use safe_write for the UPDATE
    with safe_write() as conn:
        c = conn.cursor()
        c.execute("""
            UPDATE bets SET result=?, profit_loss=?, final_score=? WHERE id=?
        """, (result, pnl, final_score if final_score else None, bet_id))
        # safe_write() context manager handles commit + writeback on exit

    emoji = "✅" if result == "WIN" else ("↩️" if result == "PUSH" else "❌")
    print(f"\n  {emoji} Bet #{bet_id}: {result} | P/L: {pnl:+.2f}u")


# ─────────────────────────────────────────────
#  4. UPDATE PARLAY RESULT
# ─────────────────────────────────────────────

def update_parlay():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, date, sport, name, units, combined_odds
        FROM parlays WHERE result='PENDING' ORDER BY date
    """)
    pending = c.fetchall()
    conn.close()

    if not pending:
        print("\n  No pending parlays.")
        return

    print("\n" + "═" * 60)
    print("  PENDING PARLAYS")
    print("═" * 60)
    for row in pending:
        pid, date, sport, name, units, odds = row
        print(f"  [{pid}] {date} | {sport or '?':<6} | {name} | {units}u @ +{odds}")

    try:
        parlay_id = int(input("\n  Enter Parlay ID to grade: ").strip())
    except ValueError:
        return

    # Read phase — fetch legs and parlay details before user input
    with safe_read() as rconn:
        rc = rconn.cursor()
        rc.execute("""
            SELECT id, leg_number, game, bet_type, selection
            FROM parlay_legs
            WHERE parlay_id=? AND result='PENDING'
            ORDER BY leg_number
        """, (parlay_id,))
        legs = rc.fetchall()
        if not legs:
            print("  No pending legs found for this parlay.")
            return
        rc.execute("SELECT units, combined_odds FROM parlays WHERE id=?", (parlay_id,))
        parlay_row = rc.fetchone()

    # Collect user input for each leg (outside any DB connection)
    leg_grades = []  # list of (leg_id, leg_result)
    all_results = []
    print(f"\n  Grade each leg:")
    for leg in legs:
        lid, leg_num, game, bet_type, selection = leg[0], leg[1], leg[2], leg[3], leg[4]
        print(f"\n    Leg {leg_num}: [{bet_type}] {selection} — {game}")
        print("    Result: [1] WIN  [2] LOSS  [3] PUSH")
        leg_result = {"1": "WIN", "2": "LOSS", "3": "PUSH"}.get(
            input("    Select: ").strip(), "LOSS")
        leg_grades.append((lid, leg_result))
        all_results.append(leg_result)

    if "LOSS" in all_results:
        parlay_result = "LOSS"
    elif all(r == "PUSH" for r in all_results):
        parlay_result = "PUSH"
    else:
        parlay_result = "WIN"

    units, combined_odds = parlay_row[0], parlay_row[1]
    pnl = calculate_pnl(units, str(combined_odds), parlay_result)

    # Write phase — update all rows in a single safe_write() transaction
    with safe_write() as conn:
        c = conn.cursor()
        for lid, leg_result in leg_grades:
            c.execute("UPDATE parlay_legs SET result=? WHERE id=?", (leg_result, lid))
        c.execute("UPDATE parlays SET result=?, profit_loss=? WHERE id=?",
                  (parlay_result, pnl, parlay_id))
        # safe_write() context manager handles commit + writeback on exit

    emoji = "✅" if parlay_result == "WIN" else "❌"
    print(f"\n  {emoji} Parlay #{parlay_id}: {parlay_result} | P/L: {pnl:+.2f}u")


# ─────────────────────────────────────────────
#  5. VIEW PENDING BETS
# ─────────────────────────────────────────────

def view_pending():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        SELECT id, game_date, sport, away_team, home_team, bet_type,
               bet_selection, units, odds, confidence
        FROM bets WHERE result='PENDING' ORDER BY game_date
    """)
    straight = c.fetchall()

    c.execute("""
        SELECT id, date, sport, name, units, combined_odds, confidence
        FROM parlays WHERE result='PENDING' ORDER BY date
    """)
    parlays = c.fetchall()

    print("\n" + "═" * 60)
    print("  PENDING BETS")
    print("═" * 60)

    if straight:
        print(f"\n  STRAIGHT BETS ({len(straight)})")
        print("  " + "─" * 56)
        for row in straight:
            bid, gdate, sport, away, home, bet_type, sel, units, odds, conf = row
            print(f"  #{bid:>3} | {gdate} | {sport or '?':<6} | {stars(conf)} | {bet_type:<9} | {sel} @ {odds}")
            print(f"       {away} @ {home} | {units}u")
    else:
        print("\n  No pending straight bets.")

    if parlays:
        print(f"\n  PARLAYS ({len(parlays)})")
        print("  " + "─" * 56)
        for row in parlays:
            pid, date, sport, name, units, odds, conf = row
            print(f"  #{pid:>3} | {date} | {sport or '?':<6} | {stars(conf)} | {name} | {units}u @ +{odds}")
            c.execute("""
                SELECT leg_number, bet_type, selection, game
                FROM parlay_legs WHERE parlay_id=? ORDER BY leg_number
            """, (pid,))
            for leg_num, bt, sel, gm in c.fetchall():
                print(f"        ↳ Leg {leg_num} [{bt}] {sel} — {gm}")
    else:
        print("\n  No pending parlays.")

    conn.close()


# ─────────────────────────────────────────────
#  6. STATISTICS
# ─────────────────────────────────────────────

def view_statistics():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    print("\n" + "═" * 60)
    print("  PERFORMANCE STATISTICS")
    print("═" * 60)

    # Overall
    c.execute("""
        SELECT result, COUNT(*), SUM(profit_loss), SUM(units)
        FROM bets WHERE result != 'PENDING' GROUP BY result
    """)
    wins = losses = pushes = 0
    total_pnl = total_units = 0.0
    for result, cnt, pnl, u in c.fetchall():
        if result == "WIN":    wins = cnt
        elif result == "LOSS": losses = cnt
        elif result == "PUSH": pushes = cnt
        total_pnl += (pnl or 0)
        total_units += (u or 0)

    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
    roi = (total_pnl / total_units * 100) if total_units > 0 else 0

    print(f"\n  OVERALL STRAIGHT BETS")
    print("  " + "─" * 40)
    print(f"  Record:    {wins}W-{losses}L-{pushes}P ({wins+losses+pushes} graded)")
    print(f"  Win Rate:  {win_rate:.1f}%")
    print(f"  Net Units: {total_pnl:+.2f}u")
    print(f"  ROI:       {roi:+.1f}%")

    # By sport
    c.execute("""
        SELECT COALESCE(sport,'UNKNOWN'), result, COUNT(*), SUM(profit_loss), SUM(units)
        FROM bets WHERE result != 'PENDING'
        GROUP BY sport, result ORDER BY sport
    """)
    sport_stats = {}
    for sport, result, cnt, pnl, u in c.fetchall():
        if sport not in sport_stats:
            sport_stats[sport] = {"W":0,"L":0,"P":0,"pnl":0.0,"units":0.0}
        if result == "WIN":    sport_stats[sport]["W"] = cnt
        elif result == "LOSS": sport_stats[sport]["L"] = cnt
        elif result == "PUSH": sport_stats[sport]["P"] = cnt
        sport_stats[sport]["pnl"] += (pnl or 0)
        sport_stats[sport]["units"] += (u or 0)

    if sport_stats:
        print(f"\n  BY SPORT")
        print("  " + "─" * 56)
        print(f"  {'SPORT':<8} {'RECORD':<14} {'WIN%':<8} {'NET':<10} {'ROI'}")
        print("  " + "─" * 56)
        for sport, s in sorted(sport_stats.items()):
            w, l, p = s["W"], s["L"], s["P"]
            wr = (w / (w + l) * 100) if (w + l) > 0 else 0
            r = (s["pnl"] / s["units"] * 100) if s["units"] > 0 else 0
            print(f"  {sport:<8} {w}W-{l}L-{p}P       {wr:>5.1f}%  {s['pnl']:>+7.2f}u  {r:>+.1f}%")

    # By bet type
    c.execute("""
        SELECT bet_type, COUNT(*),
               SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END),
               SUM(profit_loss), SUM(units)
        FROM bets WHERE result != 'PENDING' GROUP BY bet_type
    """)
    type_rows = c.fetchall()
    if type_rows:
        print(f"\n  BY BET TYPE")
        print("  " + "─" * 56)
        for bt, total, w, pnl, u in type_rows:
            l = total - w
            wr = (w / total * 100) if total > 0 else 0
            r = ((pnl or 0) / (u or 1) * 100)
            flag = "🔥 PRIMARY EDGE" if bt == "TOTAL" and wr >= 65 else ""
            print(f"  {bt:<12} {w}W-{l}L   {wr:>5.1f}%  {(pnl or 0):>+7.2f}u  {r:>+.1f}%  {flag}")

    # By confidence
    c.execute("""
        SELECT confidence, COUNT(*),
               SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END),
               SUM(profit_loss)
        FROM bets WHERE result != 'PENDING'
        GROUP BY confidence ORDER BY confidence DESC
    """)
    conf_rows = c.fetchall()
    if conf_rows:
        print(f"\n  BY CONFIDENCE")
        print("  " + "─" * 40)
        for conf, total, w, pnl in conf_rows:
            l = total - w
            wr = (w / total * 100) if total > 0 else 0
            print(f"  {stars(conf)} ({conf}★)   {w}W-{l}L   {wr:.1f}% WR   {(pnl or 0):+.2f}u")

    # Parlays
    c.execute("""
        SELECT result, COUNT(*), SUM(profit_loss)
        FROM parlays WHERE result != 'PENDING' GROUP BY result
    """)
    p_wins = p_losses = 0
    p_pnl = 0.0
    for result, cnt, pnl in c.fetchall():
        if result == "WIN":    p_wins = cnt
        elif result == "LOSS": p_losses = cnt
        p_pnl += (pnl or 0)

    print(f"\n  PARLAYS")
    print("  " + "─" * 40)
    if (p_wins + p_losses) > 0:
        print(f"  Record:    {p_wins}W-{p_losses}L")
        print(f"  Net Units: {p_pnl:+.2f}u")
        print(f"  ⚠  Parlay pause in effect — spread legs only when resuming")
    else:
        print("  No graded parlays yet.")

    # Parlay leg breakdown
    c.execute("""
        SELECT pl.bet_type,
               SUM(CASE WHEN pl.result='WIN' THEN 1 ELSE 0 END) as wins,
               COUNT(*) as total
        FROM parlay_legs pl
        JOIN parlays p ON pl.parlay_id = p.id
        WHERE p.result != 'PENDING'
        GROUP BY pl.bet_type
    """)
    leg_rows = c.fetchall()
    if leg_rows:
        print(f"\n  PARLAY LEG HIT RATES")
        print("  " + "─" * 40)
        for bt, w, total in leg_rows:
            l = total - w
            wr = (w / total * 100) if total > 0 else 0
            flag = "✅ USE" if bt == "SPREAD" and wr >= 55 else ("❌ AVOID" if bt == "MONEYLINE" else "")
            print(f"  {bt:<12} {w}W-{l}L   {wr:.1f}%   {flag}")

    conn.close()
    print()


# ─────────────────────────────────────────────
#  7. RECENT HISTORY
# ─────────────────────────────────────────────

def recent_history():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    print("\n" + "═" * 60)
    print("  RECENT HISTORY — LAST 15 BETS")
    print("═" * 60)

    c.execute("""
        SELECT game_date, sport, away_team, home_team, bet_type, bet_selection,
               units, odds, result, profit_loss, confidence
        FROM bets WHERE result != 'PENDING'
        ORDER BY game_date DESC, id DESC LIMIT 15
    """)
    rows = c.fetchall()

    if rows:
        for gdate, sport, away, home, bet_type, sel, units, odds, result, pnl, conf in rows:
            icon = "✅" if result == "WIN" else ("↩️" if result == "PUSH" else "❌")
            print(f"  {icon} {gdate} | {sport or '?':<6} | {stars(conf)} | {bet_type:<9} | {sel} @ {odds}")
            print(f"       {away} @ {home} | {units}u | {(pnl or 0):+.2f}u")
    else:
        print("\n  No graded bets yet.")

    conn.close()
    print()


# ─────────────────────────────────────────────
#  MAIN MENU
# ─────────────────────────────────────────────

def main_menu():
    init_db()
    while True:
        print("\n" + "═" * 60)
        print("  EDGE BETTING INTELLIGENCE — BET TRACKER v3.2")
        print("  Sports: NCAAM  •  NCAAW  •  NBA  •  [+ Future Sports]")
        print("═" * 60)
        print("  [1] Log Straight Bet")
        print("  [2] Log Parlay")
        print("  [3] Update Straight Bet Result")
        print("  [4] Update Parlay Result")
        print("  [5] View Pending Bets")
        print("  [6] Statistics")
        print("  [7] Recent History")
        print("  [8] Exit")
        print("─" * 60)

        choice = input("  Select option: ").strip()
        if choice == "1":        log_straight_bet()
        elif choice == "2":      log_parlay()
        elif choice == "3":      update_straight_bet()
        elif choice == "4":      update_parlay()
        elif choice == "5":      view_pending()
        elif choice == "6":      view_statistics()
        elif choice == "7":      recent_history()
        elif choice == "8":
            print("\n  EDGE Tracker closed.\n")
            break
        else:
            print("  Invalid option.")

if __name__ == "__main__":
    main_menu()
