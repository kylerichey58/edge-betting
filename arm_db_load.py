"""
arm_db_load.py — EDGE Intelligence Platform
Loads ARM2026 staging CSVs into sports_betting.db.

Steps performed:
  1. Load arm_trainer_staging.csv → trainer_situational_stats
     - MEET_* rows: extract last name from natural format ("Brad H. Cox" → "COX")
     - OVERALL_ALL rows: extract last name from "Last, First" format ("Cox, Brad" → "COX")
     - INSERT OR IGNORE — never overwrites live race-graded rows
  2. Create jockey_stats table (if not exists)
     Load arm_jockey_staging.csv → jockey_stats
     - MEET rows: last name uppercase from natural format
     - INSERT OR REPLACE — ARM data is the baseline
  3. Print preview of loaded rows for Kyle review
  4. Print final verify_db() counts

NEVER called without Kyle reviewing the PREVIEW section first.
Always uses db_utils.safe_write() — no direct NTFS writes.
"""

import csv
import re
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

# ── Path setup ──────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
SPORT_DIR  = SCRIPT_DIR / "mnt" / "Sportsbetting"

sys.path.insert(0, str(SPORT_DIR))
from db_utils import safe_write, safe_read, verify_db

# ── CSV paths ────────────────────────────────────────────────────────────────
TRAINER_CSV = SPORT_DIR / "arm_trainer_staging.csv"
JOCKEY_CSV  = SPORT_DIR / "arm_jockey_staging.csv"

# ── Constants ────────────────────────────────────────────────────────────────
# Suffixes to strip before extracting last name from natural-format names
SUFFIXES = {"jr.", "sr.", "ii", "iii", "iv", "esq.", "jr", "sr"}
NOW = datetime.now(timezone.utc).isoformat()

# ─────────────────────────────────────────────────────────────────────────────
# Name normalization helpers
# ─────────────────────────────────────────────────────────────────────────────

def _natural_to_last(name: str) -> str:
    """
    Extract last name (uppercase) from natural-format ARM name.
    Examples:
      "Brad H. Cox"         → "COX"
      "Linda Rice"          → "RICE"
      "Richard E. Dutrow, Jr." → "DUTROW"
      "Todd A. Pletcher"    → "PLETCHER"
      "Rudy R. Rodriguez"   → "RODRIGUEZ"
    """
    # Strip trailing comma+suffix (e.g. ", Jr.")
    name = re.sub(r',?\s*(jr\.?|sr\.?|ii|iii|iv|esq\.?)$', '', name.strip(), flags=re.IGNORECASE).strip()
    # Strip trailing comma
    name = name.rstrip(',').strip()
    parts = name.split()
    # Remove single-letter initials and suffix tokens from the end
    while parts and (len(parts[-1]) <= 2 or parts[-1].lower().rstrip('.') in SUFFIXES):
        parts.pop()
    return parts[-1].upper() if parts else ""


def _lastname_first_to_last(name: str) -> str:
    """
    Extract last name (uppercase) from "Last, First" ARM format.
    Examples:
      "Cox, Brad"           → "COX"
      "Abney, Mike"         → "ABNEY"
      "Anderson, Carl Norman" → "ANDERSON"
      "Dutrow, Richard E."  → "DUTROW"
    """
    if ',' in name:
        last = name.split(',')[0].strip()
        return last.upper()
    # Fallback: treat as natural format
    return _natural_to_last(name)


# ─────────────────────────────────────────────────────────────────────────────
# Step 1 — Trainer staging → trainer_situational_stats
# ─────────────────────────────────────────────────────────────────────────────

def load_trainer_staging(preview_only: bool = False):
    """
    Load arm_trainer_staging.csv into trainer_situational_stats.
    Uses INSERT OR IGNORE — skips any existing (trainer_name, situation) pairs.
    """
    print("\n" + "="*60)
    print("STEP 1 — Load trainer staging → trainer_situational_stats")
    print("="*60)

    with open(TRAINER_CSV, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    insert_rows = []
    skipped_no_name = 0
    skipped_no_wins = 0

    for r in rows:
        raw_name  = r["trainer_name"].strip()
        situation = r["situation"].strip()
        wins_str  = r["wins"].strip()
        starts_str = r["starts"].strip()
        win_pct_str = r["win_pct"].strip()

        # Skip rows with no usable data
        if not raw_name:
            skipped_no_name += 1
            continue
        try:
            wins   = int(wins_str) if wins_str else 0
            starts = int(starts_str) if starts_str else 0
        except ValueError:
            skipped_no_wins += 1
            continue

        # Derive stored trainer_name = last name uppercase
        if situation == "OVERALL_ALL":
            stored_name = _lastname_first_to_last(raw_name)
        else:
            # MEET_* rows use natural format "Brad H. Cox"
            stored_name = _natural_to_last(raw_name)

        if not stored_name:
            skipped_no_name += 1
            continue

        # Calculate ROI proxy: wins / starts (no place/show data from ARM)
        roi = round(wins / starts, 4) if starts > 0 else 0.0
        # win_pct stored for reference
        try:
            win_pct = float(win_pct_str) / 100.0 if win_pct_str else roi
        except ValueError:
            win_pct = roi

        insert_rows.append({
            "trainer_name": stored_name,
            "situation":    situation,
            "starts":       starts,
            "wins":         wins,
            "places":       0,
            "shows":        0,
            "roi":          roi,
            "raw_name":     raw_name,   # for preview only
        })

    # --- PREVIEW ---
    print(f"\nPREVIEW — First 15 rows to be inserted:")
    print(f"{'raw_name':<35} {'stored_name':<15} {'situation':<20} {'wins':>5} {'starts':>6} {'roi':>6}")
    print("-" * 95)
    for r in insert_rows[:15]:
        print(f"{r['raw_name']:<35} {r['trainer_name']:<15} {r['situation']:<20} "
              f"{r['wins']:>5} {r['starts']:>6} {r['roi']:>6.3f}")

    print(f"\nStats:")
    print(f"  Total rows in CSV:         {len(rows)}")
    print(f"  Rows to insert:            {len(insert_rows)}")
    print(f"  Skipped (no name):         {skipped_no_name}")
    print(f"  Skipped (bad wins/starts): {skipped_no_wins}")

    # Situation breakdown
    from collections import Counter
    sit_counts = Counter(r["situation"].split("_")[0] + "_" + r["situation"].split("_")[1]
                         if r["situation"].startswith("MEET_") else r["situation"]
                         for r in insert_rows)
    print(f"\n  Situation breakdown (top 20):")
    for sit, cnt in sorted(sit_counts.most_common(20)):
        print(f"    {sit:<25} {cnt:>5}")

    if preview_only:
        print("\n[PREVIEW ONLY — no DB writes]")
        return 0

    # --- INSERT ---
    print(f"\nInserting {len(insert_rows)} rows via safe_write()...")
    inserted = 0
    ignored  = 0

    with safe_write() as conn:
        for r in insert_rows:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO trainer_situational_stats
                  (trainer_name, situation, starts, wins, places, shows, roi, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (r["trainer_name"], r["situation"],
                 r["starts"], r["wins"], r["places"], r["shows"],
                 r["roi"], NOW)
            )
            if cur.rowcount == 1:
                inserted += 1
            else:
                ignored += 1

    print(f"  Inserted: {inserted}")
    print(f"  Ignored (already exists): {ignored}")
    return inserted


# ─────────────────────────────────────────────────────────────────────────────
# Step 2 — Jockey staging → jockey_stats table
# ─────────────────────────────────────────────────────────────────────────────

CREATE_JOCKEY_STATS_SQL = """
CREATE TABLE IF NOT EXISTS jockey_stats (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    jockey_name  TEXT,
    track_code   TEXT,
    wins         INTEGER DEFAULT 0,
    win_pct      REAL    DEFAULT 0.0,
    starts       INTEGER DEFAULT 0,
    surface      TEXT    DEFAULT '',
    source       TEXT    DEFAULT 'ARM2026',
    year         INTEGER DEFAULT 2025,
    last_updated TEXT,
    UNIQUE(jockey_name, track_code)
)
"""


def load_jockey_staging(preview_only: bool = False):
    """
    Create jockey_stats table and load arm_jockey_staging.csv.
    Uses INSERT OR REPLACE — ARM data is the baseline (can refresh each year).
    """
    print("\n" + "="*60)
    print("STEP 2 — Load jockey staging → jockey_stats")
    print("="*60)

    with open(JOCKEY_CSV, newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    insert_rows = []
    skipped = 0

    for r in rows:
        raw_name   = r["jockey_name"].strip()
        track_code = r["track_code"].strip()
        wins_str   = r["wins"].strip()
        starts_str = r["starts"].strip()
        win_pct_str = r["win_pct"].strip()
        surface    = r.get("surface", "").strip()
        source_page = r.get("source_page", "").strip()
        year_str   = r.get("year", "2025").strip()

        if not raw_name or not track_code:
            skipped += 1
            continue

        try:
            wins   = int(wins_str) if wins_str else 0
            starts = int(starts_str) if starts_str else 0
            win_pct = float(win_pct_str) if win_pct_str else (wins / starts if starts > 0 else 0)
            year   = int(year_str) if year_str else 2025
        except ValueError:
            skipped += 1
            continue

        # Derive stored jockey_name = last name uppercase (same logic as trainer)
        # MEET rows: natural format "Luis A. Valenzuela" → "VALENZUELA"
        stored_name = _natural_to_last(raw_name)
        if not stored_name:
            # Fallback: try "Last, First" format
            stored_name = _lastname_first_to_last(raw_name)
        if not stored_name:
            skipped += 1
            continue

        source = f"ARM2026_p{source_page}" if source_page else "ARM2026"

        insert_rows.append({
            "jockey_name": stored_name,
            "track_code":  track_code,
            "wins":        wins,
            "win_pct":     win_pct / 100.0 if win_pct > 1.5 else win_pct,  # normalize if stored as percentage
            "starts":      starts,
            "surface":     surface,
            "source":      source,
            "year":        year,
            "raw_name":    raw_name,
        })

    # --- PREVIEW ---
    print(f"\nPREVIEW — First 15 rows to be inserted:")
    print(f"{'raw_name':<35} {'stored_name':<15} {'track':<8} {'wins':>5} {'starts':>6} {'win_pct':>8}")
    print("-" * 85)
    for r in insert_rows[:15]:
        print(f"{r['raw_name']:<35} {r['jockey_name']:<15} {r['track_code']:<8} "
              f"{r['wins']:>5} {r['starts']:>6} {r['win_pct']:>8.3f}")

    print(f"\nStats:")
    print(f"  Total rows in CSV:  {len(rows)}")
    print(f"  Rows to insert:     {len(insert_rows)}")
    print(f"  Skipped:            {skipped}")

    # Track breakdown
    from collections import Counter
    track_counts = Counter(r["track_code"] for r in insert_rows)
    edge_tracks = {'GPX','MVR','KEE','CD','SA','SAR','AQU','DMR','FG','TAM','TP','LRL','PIM','OP'}
    print(f"\n  Track breakdown (EDGE tracks only):")
    for track, cnt in sorted((t, c) for t, c in track_counts.items() if t in edge_tracks):
        print(f"    {track:<8} {cnt:>5}")

    if preview_only:
        print("\n[PREVIEW ONLY — no DB writes]")
        return 0

    # --- CREATE TABLE + INSERT ---
    print(f"\nCreating jockey_stats table (if not exists) and inserting {len(insert_rows)} rows...")

    inserted = 0
    replaced = 0

    with safe_write() as conn:
        conn.execute(CREATE_JOCKEY_STATS_SQL)

        for r in insert_rows:
            # Check if exists first to distinguish insert vs replace
            existing = conn.execute(
                "SELECT id FROM jockey_stats WHERE jockey_name = ? AND track_code = ?",
                (r["jockey_name"], r["track_code"])
            ).fetchone()

            conn.execute(
                """
                INSERT OR REPLACE INTO jockey_stats
                  (jockey_name, track_code, wins, win_pct, starts, surface, source, year, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (r["jockey_name"], r["track_code"],
                 r["wins"], r["win_pct"], r["starts"],
                 r["surface"], r["source"], r["year"], NOW)
            )
            if existing:
                replaced += 1
            else:
                inserted += 1

    print(f"  Inserted (new): {inserted}")
    print(f"  Replaced (updated): {replaced}")
    return inserted + replaced


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    preview = "--preview" in sys.argv

    print("\n" + "="*60)
    print("ARM DB LOAD — EDGE Intelligence Platform")
    print(f"Mode: {'PREVIEW ONLY' if preview else 'LIVE WRITE'}")
    print(f"Time: {NOW}")
    print("="*60)

    # Pre-load DB health check
    print("\nPre-load DB state:")
    health = verify_db()
    for k, v in health.items():
        print(f"  {k}: {v}")

    # Step 1 — Trainer staging
    t_inserted = load_trainer_staging(preview_only=preview)

    # Step 2 — Jockey staging
    j_loaded = load_jockey_staging(preview_only=preview)

    if not preview:
        # Post-load DB health check
        print("\n" + "="*60)
        print("Post-load DB state:")
        health = verify_db()
        for k, v in health.items():
            print(f"  {k}: {v}")

        print("\n" + "="*60)
        print("LOAD COMPLETE")
        print(f"  Trainer rows inserted: {t_inserted}")
        print(f"  Jockey rows loaded:    {j_loaded}")
        print("="*60)
    else:
        print("\n" + "="*60)
        print("PREVIEW COMPLETE — run without --preview to write to DB")
        print("="*60)
