import sqlite3

DB_PATH = "sports_betting.db"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

c.execute("PRAGMA table_info(bets)")
cols = c.fetchall()
print("BETS TABLE COLUMNS:")
for col in cols:
    print(f"  {col[1]} ({col[2]})")

print()

c.execute("PRAGMA table_info(parlays)")
cols = c.fetchall()
print("PARLAYS TABLE COLUMNS:")
for col in cols:
    print(f"  {col[1]} ({col[2]})")

print()

c.execute("PRAGMA table_info(parlay_legs)")
cols = c.fetchall()
print("PARLAY_LEGS TABLE COLUMNS:")
for col in cols:
    print(f"  {col[1]} ({col[2]})")

conn.close()
