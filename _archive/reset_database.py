"""
Complete Database Reset for Bet Tracker
This will delete the old database and create a fresh one
"""

import sqlite3
import os

DB_FILE = 'sports_betting.db'

def reset_database():
    """Delete old database and create fresh one"""
    
    # Delete the old database file completely
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        print("🗑️  Deleted old database")
    
    # Create brand new database
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    print("\n📦 Creating new database...")
    
    # Create the bets table with correct structure
    cursor.execute('''
        CREATE TABLE bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_date TEXT NOT NULL,
            sport TEXT NOT NULL,
            away_team TEXT NOT NULL,
            home_team TEXT NOT NULL,
            bet_type TEXT NOT NULL,
            bet_selection TEXT NOT NULL,
            odds TEXT,
            units REAL NOT NULL,
            confidence INTEGER,
            reasoning TEXT,
            game_id TEXT,
            logged_date TEXT NOT NULL,
            result TEXT DEFAULT 'PENDING',
            profit_loss REAL DEFAULT 0.0,
            final_score TEXT,
            notes TEXT
        )
    ''')
    
    conn.commit()
    conn.close()
    
    print("✅ New database created!")
    print("✅ Ready to log your first bet!")
    print("\n🎯 Now run: python bet_tracker.py")

if __name__ == "__main__":
    reset_database()
