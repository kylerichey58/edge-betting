import sqlite3
from datetime import datetime

DB_PATH = 'sports_betting.db'

def get_bet(bet_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM bets WHERE id=?", (bet_id,))
    row = c.fetchone()
    conn.close()
    return row

def get_parlay(parlay_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM parlays WHERE id=?", (parlay_id,))
    parlay = c.fetchone()
    c.execute("SELECT * FROM parlay_legs WHERE parlay_id=?", (parlay_id,))
    legs = c.fetchall()
    conn.close()
    return parlay, legs

def display_bet(row):
    if not row:
        print("  ❌ Bet not found.")
        return
    print(f"""
  ┌─────────────────────────────────────────────┐
  │ BET #{row[0]}
  │ Date:       {row[1]}
  │ Sport:      {row[2]}
  │ Matchup:    {row[3]} @ {row[4]}
  │ Type:       {row[5]}
  │ Selection:  {row[6]}
  │ Odds:       {row[7]}
  │ Units:      {row[8]}u
  │ Confidence: {'⭐' * row[9]}
  │ Result:     {row[13]}
  │ Score:      {row[15]}
  │ P/L:        {row[14]}u
  │ Notes:      {row[16]}
  └─────────────────────────────────────────────┘""")

def display_parlay(parlay, legs):
    if not parlay:
        print("  ❌ Parlay not found.")
        return
    print(f"""
  ┌─────────────────────────────────────────────┐
  │ PARLAY #{parlay[0]} — {parlay[2]}
  │ Date:       {parlay[1]}
  │ Legs:       {parlay[3]}
  │ Odds:       +{parlay[4]}
  │ Units:      {parlay[5]}u
  │ Confidence: {'⭐' * parlay[6]}
  │ Result:     {parlay[8]}
  │ P/L:        {parlay[9]}u
  └─────────────────────────────────────────────┘""")
    print("  LEGS:")
    for leg in legs:
        print(f"    Leg {leg[2]}: {leg[4]} | {leg[5]} {leg[6]} {leg[7]} | Result: {leg[8]}")

def calc_profit(units, odds_str, result):
    """Calculate correct P/L from units, odds string, and result."""
    try:
        odds = int(odds_str.replace('+','').replace(' ',''))
        if result == 'WIN':
            if odds > 0:
                return round(units * odds / 100, 2)
            else:
                return round(units * 100 / abs(odds), 2)
        elif result == 'LOSS':
            return round(-units, 2)
        else:  # PUSH
            return 0.0
    except:
        return None

def repair_straight_bet():
    bet_id = input("\n  Enter Bet ID to repair: ").strip()
    row = get_bet(int(bet_id))
    if not row:
        print("  ❌ Bet not found.")
        return

    print("\n  Current record:")
    display_bet(row)

    print("""
  What do you want to fix?
    1 — Result (WIN/LOSS/PUSH)
    2 — Final Score
    3 — Units risked
    4 — Odds
    5 — Profit/Loss (manual override)
    6 — Notes
    7 — Fix result + recalculate P/L automatically
    8 — Cancel
    """)

    choice = input("  Choice: ").strip()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if choice == '1':
        new_val = input("  New result (WIN/LOSS/PUSH): ").strip().upper()
        c.execute("UPDATE bets SET result=? WHERE id=?", (new_val, bet_id))
        print(f"  ✅ Result updated to {new_val}")

    elif choice == '2':
        new_val = input("  New final score (e.g. 78-72): ").strip()
        c.execute("UPDATE bets SET final_score=? WHERE id=?", (new_val, bet_id))
        print(f"  ✅ Score updated to {new_val}")

    elif choice == '3':
        new_val = float(input("  New units risked: ").strip())
        c.execute("UPDATE bets SET units=? WHERE id=?", (new_val, bet_id))
        print(f"  ✅ Units updated to {new_val}u")

    elif choice == '4':
        new_val = input("  New odds (e.g. -110 or +135): ").strip()
        c.execute("UPDATE bets SET odds=? WHERE id=?", (new_val, bet_id))
        print(f"  ✅ Odds updated to {new_val}")

    elif choice == '5':
        new_val = float(input("  New P/L (use negative for loss, e.g. -1.5): ").strip())
        c.execute("UPDATE bets SET profit_loss=? WHERE id=?", (new_val, bet_id))
        print(f"  ✅ P/L manually set to {new_val}u")

    elif choice == '6':
        new_val = input("  New notes: ").strip()
        c.execute("UPDATE bets SET notes=? WHERE id=?", (new_val, bet_id))
        print(f"  ✅ Notes updated")

    elif choice == '7':
        new_result = input("  Correct result (WIN/LOSS/PUSH): ").strip().upper()
        new_score = input("  Final score (e.g. 78-72): ").strip()
        pl = calc_profit(row[8], row[7], new_result)
        if pl is None:
            pl = float(input("  Could not auto-calculate P/L. Enter manually: ").strip())
        c.execute(
            "UPDATE bets SET result=?, final_score=?, profit_loss=? WHERE id=?",
            (new_result, new_score, pl, bet_id)
        )
        print(f"  ✅ Bet #{bet_id} → {new_result} | Score: {new_score} | P/L: {pl:+.2f}u")

    elif choice == '8':
        print("  Cancelled.")
        conn.close()
        return

    conn.commit()

    # Show updated record
    c.execute("SELECT * FROM bets WHERE id=?", (bet_id,))
    updated = c.fetchone()
    conn.close()
    print("\n  Updated record:")
    display_bet(updated)

def repair_parlay():
    parlay_id = input("\n  Enter Parlay ID to repair: ").strip()
    parlay, legs = get_parlay(int(parlay_id))
    if not parlay:
        print("  ❌ Parlay not found.")
        return

    print("\n  Current record:")
    display_parlay(parlay, legs)

    print("""
  What do you want to fix?
    1 — Parlay result (WIN/LOSS)
    2 — Parlay P/L (manual override)
    3 — Individual leg result
    4 — Cancel
    """)

    choice = input("  Choice: ").strip()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    if choice == '1':
        new_val = input("  New result (WIN/LOSS): ").strip().upper()
        c.execute("UPDATE parlays SET result=? WHERE id=?", (new_val, parlay_id))
        print(f"  ✅ Parlay result updated to {new_val}")

    elif choice == '2':
        new_val = float(input("  New P/L: ").strip())
        c.execute("UPDATE parlays SET profit_loss=? WHERE id=?", (new_val, parlay_id))
        print(f"  ✅ Parlay P/L set to {new_val}u")

    elif choice == '3':
        leg_num = input("  Which leg number to fix? ").strip()
        new_val = input("  New result (WIN/LOSS/PUSH): ").strip().upper()
        c.execute(
            "UPDATE parlay_legs SET result=? WHERE parlay_id=? AND leg_number=?",
            (new_val, parlay_id, leg_num)
        )
        print(f"  ✅ Leg {leg_num} updated to {new_val}")

    elif choice == '4':
        print("  Cancelled.")
        conn.close()
        return

    conn.commit()
    conn.close()
    print("\n  Repair complete. Run bet_analytics.py to refresh your dashboard.")

def view_recent():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, game_date, away_team, home_team, bet_selection, result, profit_loss
        FROM bets ORDER BY id DESC LIMIT 10
    """)
    rows = c.fetchall()
    conn.close()
    print("\n  === LAST 10 STRAIGHT BETS ===")
    print(f"  {'ID':<5} {'Date':<12} {'Matchup':<30} {'Selection':<20} {'Result':<8} {'P/L'}")
    print("  " + "-"*90)
    for r in rows:
        matchup = f"{r[2]} @ {r[3]}"
        pl_str = f"{r[6]:+.2f}u" if r[6] is not None else "PENDING"
        print(f"  {r[0]:<5} {r[1]:<12} {matchup:<30} {r[4]:<20} {str(r[5]):<8} {pl_str}")

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, date, name, result, profit_loss FROM parlays ORDER BY id DESC LIMIT 5")
    rows = c.fetchall()
    conn.close()
    if rows:
        print("\n  === LAST 5 PARLAYS ===")
        print(f"  {'ID':<5} {'Date':<12} {'Name':<30} {'Result':<8} {'P/L'}")
        print("  " + "-"*65)
        for r in rows:
            pl_str = f"{r[4]:+.2f}u" if r[4] is not None else "PENDING"
            print(f"  {r[0]:<5} {r[1]:<12} {r[2]:<30} {str(r[3]):<8} {pl_str}")

def main():
    print("""
╔══════════════════════════════════════╗
║         BET REPAIR TOOL             ║
║   Fix any entry error, any time     ║
╚══════════════════════════════════════╝

  1 — View recent bets (find the ID you need)
  2 — Repair a straight bet
  3 — Repair a parlay
  4 — Exit
    """)

    while True:
        choice = input("  Choice: ").strip()

        if choice == '1':
            view_recent()
        elif choice == '2':
            repair_straight_bet()
        elif choice == '3':
            repair_parlay()
        elif choice == '4':
            print("  Exiting repair tool.")
            break
        else:
            print("  Invalid choice.")

        print("\n  --- Main Menu ---")
        print("  1 — View recent bets")
        print("  2 — Repair a straight bet")
        print("  3 — Repair a parlay")
        print("  4 — Exit")

if __name__ == "__main__":
    main()
