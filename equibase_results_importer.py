"""
equibase_results_importer.py — EDGE Intelligence Platform
==========================================================
Bulk-imports 2023 Equibase Result Chart XML files.

Step 1 — Extracts 2023 Result Charts.zip to 2023 Result Charts/
Step 2 — For every *tch.xml result file:
          • Calls horse_racing_grader.grade_race() per race
            (matches any horse_race_analyses rows we placed bets on)
          • Calls horse_racing_grader.update_trainer_stats() for
            every horse in every result (the main M07 enrichment)

Performance notes:
  • lxml parser (4–5× faster than stdlib ET)
  • DB copied to /tmp for fast local writes; synced back at end
  • Trainer stats batched with ON CONFLICT upserts; grade_race()
    called live (it's lightweight – only hits rows we bet on)

Race type mapping (full English → DRF/Brisnet codes used in DB):
  Claiming                    → CLM
  Allowance                   → ALW
  Maiden Special Weight       → MSW
  Maiden Claiming             → MCL
  Stakes / Handicap Stakes    → STK
  Allowance Optional Claiming → AOC
  Optional Claiming           → OCL
  Starter Allowance           → STR
  Starter Optional Claiming   → SOC
  Maiden                      → MDN
  Handicap                    → HCP
  Maiden Optional Claiming    → MOC
  Waiver Claiming             → WCL
  Waiver Maiden Claiming      → WMC
"""

import os
import sys
import zipfile
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime, date

try:
    import lxml.etree as ET
    _LXML = True
except ImportError:
    import xml.etree.ElementTree as ET
    _LXML = False

# ─── PATHS ────────────────────────────────────────────────────────────────────

SCRIPT_DIR  = Path(__file__).parent
ZIP_SRC     = SCRIPT_DIR / "2023 Result Charts.zip"
EXTRACT_DIR = SCRIPT_DIR / "2023 Result Charts"
DB_PATH     = SCRIPT_DIR / "sports_betting.db"
TMP_DB      = Path("/tmp/results_import.db")

SEP = "=" * 68

# ─── RACE TYPE MAP (full text → code) ────────────────────────────────────────

RACE_TYPE_MAP = {
    "Claiming":                    "CLM",
    "Allowance":                   "ALW",
    "Maiden Special Weight":       "MSW",
    "Maiden Claiming":             "MCL",
    "Stakes":                      "STK",
    "Allowance Optional Claiming": "AOC",
    "Optional Claiming":           "OCL",
    "Starter Allowance":           "STR",
    "Starter Optional Claiming":   "SOC",
    "Maiden":                      "MDN",
    "Handicap":                    "HCP",
    "Handicap Stakes":             "STK",
    "Maiden Optional Claiming":    "MOC",
    "Waiver Claiming":             "WCL",
    "Waiver Maiden Claiming":      "WMC",
    # fallbacks
    "Maiden Optional":             "MOC",
    "Optional":                    "OCL",
}

# Layoff thresholds — must match horse_racing_grader.py exactly
_LAYOFF_1ST_MIN = 90
_LAYOFF_1ST_MAX = 180
_LAYOFF_2ND_MIN = 45
_LAYOFF_2ND_MAX = 89

# ─── STEP 1 — EXTRACT ZIP ────────────────────────────────────────────────────

def extract_zip() -> int:
    """
    Extract 2023 Result Charts.zip → 2023 Result Charts/ folder.
    Returns count of XML files extracted.
    Skips already-extracted files to allow re-runs.
    """
    print(f"\n{'─'*68}")
    print("STEP 1 — Extracting ZIP")
    print(f"{'─'*68}")
    print(f"  Source : {ZIP_SRC.name}  ({ZIP_SRC.stat().st_size/1024/1024:.0f} MB)")
    print(f"  Target : {EXTRACT_DIR}")

    if not ZIP_SRC.exists():
        print(f"  ERROR: ZIP not found: {ZIP_SRC}")
        sys.exit(1)

    EXTRACT_DIR.mkdir(exist_ok=True)
    extracted = 0
    skipped   = 0

    with zipfile.ZipFile(ZIP_SRC, "r") as z:
        members = [m for m in z.infolist() if m.filename.endswith("tch.xml")]
        total   = len(members)
        print(f"  XML files in ZIP: {total:,}")

        for info in members:
            # Strip the leading folder component so files land in EXTRACT_DIR
            fname    = Path(info.filename).name
            out_path = EXTRACT_DIR / fname

            if out_path.exists() and out_path.stat().st_size == info.file_size:
                skipped += 1
                continue

            data = z.read(info.filename)
            out_path.write_bytes(data)
            extracted += 1

            if (extracted + skipped) % 500 == 0:
                print(f"    {extracted + skipped:>5}/{total} extracted...", flush=True)

    xml_count = len(list(EXTRACT_DIR.glob("*tch.xml")))
    print(f"\n  ✅ Extraction complete")
    print(f"     Extracted new : {extracted:,}")
    print(f"     Already present: {skipped:,}")
    print(f"     Total XML files in folder: {xml_count:,}")
    return xml_count


# ─── DATE HELPERS ─────────────────────────────────────────────────────────────

def parse_ymd(s: str):
    """'2023-02-03' → date. Returns None on failure."""
    try:
        return datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


def days_between(earlier: date, later: date) -> int:
    return (later - earlier).days


# ─── RACE PARSING ─────────────────────────────────────────────────────────────

def parse_results_file(filepath: Path) -> list:
    """
    Parse one *tch.xml result chart.
    Returns list of race_dicts:
    {
        track_code    : str   e.g. 'GP'
        race_date_obj : date
        race_date_str : str   'YYYYMMDD'  (for grade_race)
        race_number   : int
        race_type     : str   DRF code e.g. 'CLM'
        surface       : str   'D' | 'T' | 'E'
        results_list  : [str] horse names in finish order (1st → last)
        horse_entries : [dict]  full entry data for update_trainer_stats
    }
    Each horse_entry dict:
    {
        trainer       : str   'First Last'
        trainer_last  : str   last name
        race_type     : str   DRF code
        surface       : str
        finish_pos    : int
        days_since    : int|None
        horse_name    : str
    }
    """
    try:
        data = filepath.read_bytes()
        root = ET.fromstring(data)
    except Exception:
        return []

    # Top-level date and track
    race_date_raw = (root.get("RACE_DATE") or "").strip()
    race_date_obj = parse_ymd(race_date_raw)
    if race_date_obj is None:
        return []
    race_date_str = race_date_obj.strftime("%Y%m%d")   # 'YYYYMMDD' for grade_race()

    track_code = (root.findtext("TRACK/CODE") or "").strip().upper()
    if not track_code:
        return []

    race_dicts = []

    for race_el in root.findall("RACE"):
        race_num_str = (race_el.get("NUMBER") or "").strip()
        try:
            race_number = int(race_num_str)
        except ValueError:
            continue

        # Race type → DRF code
        type_long  = (race_el.findtext("TYPE") or "").strip()
        race_type  = RACE_TYPE_MAP.get(type_long) or type_long[:3].upper() or "UNK"

        # Surface: SURFACE element (D/T/E); fall back to COURSE_ID
        surface_raw = (race_el.findtext("SURFACE")
                       or race_el.findtext("COURSE_ID") or "").strip().upper()
        # Normalise AW/A variants → E
        if surface_raw in ("A", "AW", "AT"):
            surface_raw = "E"
        surface = surface_raw or "D"

        # Build entry list, sort by OFFICIAL_FIN
        entries_raw = []
        for entry_el in race_el.findall("ENTRY"):
            horse_name = (entry_el.findtext("NAME") or "").strip()
            if not horse_name:
                continue

            # Official finish — skip DQ'd horses (OFFICIAL_FIN may be 0 or absent)
            fin_str = (entry_el.findtext("OFFICIAL_FIN") or "").strip()
            dq_flag = (entry_el.findtext("DH_DQ_FLAGS") or "").strip().upper()
            try:
                fin = int(fin_str)
            except ValueError:
                continue
            if fin < 1:
                continue
            if "DQ" in dq_flag:
                continue   # skip disqualified horses

            # Trainer
            t_first = (entry_el.findtext("TRAINER/FIRST_NAME") or "").strip()
            t_last  = (entry_el.findtext("TRAINER/LAST_NAME")  or "").strip()
            trainer_full = f"{t_first} {t_last}".strip()

            # days_since_last_race — from LAST_PP/RACE_DATE vs today's race date
            last_pp_str  = (entry_el.findtext("LAST_PP/RACE_DATE") or "").strip()
            last_pp_date = parse_ymd(last_pp_str)
            days_since   = (days_between(last_pp_date, race_date_obj)
                            if last_pp_date else None)

            entries_raw.append({
                "horse_name":  horse_name,
                "finish_pos":  fin,
                "trainer":     trainer_full,
                "trainer_last": t_last,
                "race_type":   race_type,
                "surface":     surface,
                "days_since":  days_since,
            })

        if not entries_raw:
            continue

        # Sort by official finish ascending → results_list for grade_race()
        entries_raw.sort(key=lambda e: e["finish_pos"])
        results_list = [e["horse_name"] for e in entries_raw]

        race_dicts.append({
            "track_code":    track_code,
            "race_date_obj": race_date_obj,
            "race_date_str": race_date_str,
            "race_number":   race_number,
            "race_type":     race_type,
            "surface":       surface,
            "results_list":  results_list,
            "horse_entries": entries_raw,
        })

    return race_dicts


# ─── DB HELPERS ───────────────────────────────────────────────────────────────

def open_local_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA cache_size=-32000")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def ensure_trainer_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trainer_situational_stats (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            trainer_name TEXT,
            situation    TEXT,
            starts       INTEGER DEFAULT 0,
            wins         INTEGER DEFAULT 0,
            places       INTEGER DEFAULT 0,
            shows        INTEGER DEFAULT 0,
            roi          REAL    DEFAULT 0.0,
            last_updated TEXT,
            UNIQUE(trainer_name, situation)
        )
    """)
    conn.commit()


_UPSERT_SQL = """
    INSERT INTO trainer_situational_stats
        (trainer_name, situation, starts, wins, places, shows, roi, last_updated)
    VALUES (?, ?, 1, ?, ?, ?, 0.0, ?)
    ON CONFLICT(trainer_name, situation) DO UPDATE SET
        starts       = trainer_situational_stats.starts  + 1,
        wins         = trainer_situational_stats.wins    + excluded.wins,
        places       = trainer_situational_stats.places  + excluded.places,
        shows        = trainer_situational_stats.shows   + excluded.shows,
        last_updated = excluded.last_updated
"""


def batch_update_trainer_stats(conn: sqlite3.Connection,
                                batch: list, now_str: str) -> None:
    """
    Batch upsert equivalent of calling update_trainer_stats() per horse.
    Each item: (trainer_full, situation, is_win, is_place, is_show)
    """
    rows = [
        (tf, sit, iw, ip, is_, now_str)
        for tf, sit, iw, ip, is_ in batch
    ]
    conn.executemany(_UPSERT_SQL, rows)
    conn.commit()


def recalculate_roi(conn: sqlite3.Connection) -> None:
    conn.execute("""
        UPDATE trainer_situational_stats
        SET roi = (wins * 5.0 - starts) / starts
        WHERE starts > 0
    """)
    conn.commit()


def build_situation_keys(trainer_last: str, race_type: str,
                          surface: str, days_since) -> list:
    """Exact replica of horse_racing_grader._situation_keys logic."""
    keys = []
    if trainer_last and race_type and surface:
        keys.append(f"{trainer_last}_{race_type}_{surface}")
    if days_since is not None:
        try:
            d = int(days_since)
            if _LAYOFF_1ST_MIN <= d <= _LAYOFF_1ST_MAX:
                keys.append(f"{trainer_last}_1st_off_layoff")
            elif _LAYOFF_2ND_MIN <= d <= _LAYOFF_2ND_MAX:
                keys.append(f"{trainer_last}_2nd_off_layoff")
        except (TypeError, ValueError):
            pass
    return keys


# ─── STEP 2 — PROCESS RESULTS ────────────────────────────────────────────────

def process_results(xml_dir: Path, db_conn: sqlite3.Connection) -> dict:
    """
    Walk all *tch.xml files in xml_dir:
      1. Parse each file → list of race_dicts
      2. Call grade_race() per race (updates horse_race_analyses / bets table)
      3. Batch update trainer_situational_stats for every horse entry

    Returns summary dict.
    """
    # Import grader (uses SCRIPT_DIR path by default — we override with db_path)
    sys.path.insert(0, str(SCRIPT_DIR))
    from horse_racing_grader import grade_race, print_trainer_leaderboard

    ensure_trainer_table(db_conn)

    xml_files = sorted(xml_dir.glob("*tch.xml"))
    total_files  = len(xml_files)

    print(f"\n{'─'*68}")
    print(f"STEP 2 — Processing {total_files:,} result chart files")
    print(f"  Parser: {'lxml (fast)' if _LXML else 'stdlib ET'}")
    print(f"{'─'*68}\n")

    files_done    = 0
    races_graded  = 0
    entries_total = 0
    grade_hits    = 0   # races where grade_race found matching horse_race_analyses rows
    trainer_batch = []
    BATCH_SIZE    = 2000
    now_str       = datetime.now().isoformat()

    for filepath in xml_files:
        race_dicts = parse_results_file(filepath)
        files_done += 1

        for rd in race_dicts:
            races_graded += 1

            # ── grade_race(): matches any horse_race_analyses bets ──────────
            grade_result = grade_race(
                track_code   = rd["track_code"],
                race_date    = rd["race_date_str"],
                race_number  = rd["race_number"],
                results_list = rd["results_list"],
                db_path      = TMP_DB,
            )
            if grade_result.get("graded_count", 0) > 0:
                grade_hits += 1
                print(f"  🏇 BET MATCH: {rd['track_code']} R{rd['race_number']} "
                      f"{rd['race_date_str']} — "
                      f"{grade_result['graded_count']} horse(s) graded",
                      flush=True)

            # ── update_trainer_stats() for EVERY horse in this race ─────────
            for entry in rd["horse_entries"]:
                entries_total += 1
                if not entry["trainer_last"]:
                    continue

                keys = build_situation_keys(
                    entry["trainer_last"],
                    entry["race_type"],
                    entry["surface"],
                    entry["days_since"],
                )
                fp       = entry["finish_pos"]
                is_win   = 1 if fp == 1 else 0
                is_place = 1 if fp <= 2 else 0
                is_show  = 1 if fp <= 3 else 0

                for situation in keys:
                    trainer_batch.append(
                        (entry["trainer"], situation, is_win, is_place, is_show)
                    )

        # Flush trainer batch periodically
        if len(trainer_batch) >= BATCH_SIZE:
            batch_update_trainer_stats(db_conn, trainer_batch, now_str)
            trainer_batch = []

        # Progress
        if files_done % 50 == 0:
            row_count = db_conn.execute(
                "SELECT COUNT(*) FROM trainer_situational_stats"
            ).fetchone()[0]
            print(
                f"  [{files_done:>5}/{total_files:,} files]  "
                f"races: {races_graded:>6,}  entries: {entries_total:>7,}  "
                f"trainer rows: {row_count:>7,}",
                flush=True
            )

    # Final flush
    if trainer_batch:
        batch_update_trainer_stats(db_conn, trainer_batch, now_str)

    return {
        "files_done":    files_done,
        "races_graded":  races_graded,
        "entries_total": entries_total,
        "grade_hits":    grade_hits,
    }


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print(SEP)
    print("equibase_results_importer.py — EDGE Intelligence Platform")
    print("2023 Result Charts → trainer_situational_stats")
    print(SEP)

    if not DB_PATH.exists():
        print(f"ERROR: DB not found: {DB_PATH}")
        sys.exit(1)

    # ── STEP 1: Extract ZIP ───────────────────────────────────────────────
    xml_count = extract_zip()

    # ── Copy DB to /tmp for fast writes ──────────────────────────────────
    print(f"\nCopying DB to /tmp for fast local writes...")
    shutil.copy2(str(DB_PATH), str(TMP_DB))
    print(f"  DB size: {TMP_DB.stat().st_size/1024:.0f} KB")

    conn = open_local_db(TMP_DB)

    # ── STEP 2: Process result files ─────────────────────────────────────
    t_start = datetime.now()
    summary = process_results(EXTRACT_DIR, conn)
    elapsed = (datetime.now() - t_start).total_seconds()

    # ── Recalculate ROI ───────────────────────────────────────────────────
    print(f"\nRecalculating ROI...", flush=True)
    recalculate_roi(conn)

    # ── Final DB stats ────────────────────────────────────────────────────
    total_rows      = conn.execute("SELECT COUNT(*) FROM trainer_situational_stats").fetchone()[0]
    unique_trainers = conn.execute("SELECT COUNT(DISTINCT trainer_name) FROM trainer_situational_stats").fetchone()[0]
    rows_10plus     = conn.execute("SELECT COUNT(*) FROM trainer_situational_stats WHERE starts >= 10").fetchone()[0]
    rows_25plus     = conn.execute("SELECT COUNT(*) FROM trainer_situational_stats WHERE starts >= 25").fetchone()[0]
    conn.close()

    # ── Copy DB back to mounted folder ────────────────────────────────────
    print(f"\nCopying updated DB back to SportsBetting folder...")
    shutil.copy2(str(TMP_DB), str(DB_PATH))
    size_mb = DB_PATH.stat().st_size / 1024 / 1024
    print(f"  ✅ sports_betting.db  ({size_mb:.1f} MB)")

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n{SEP}")
    print("IMPORT COMPLETE")
    print(f"{SEP}")
    print(f"  Result XML files processed: {summary['files_done']:>7,}")
    print(f"  Total races graded        : {summary['races_graded']:>7,}")
    print(f"  Total horse entries parsed: {summary['entries_total']:>7,}")
    print(f"  Races with bet matches    : {summary['grade_hits']:>7,}")
    print(f"  Elapsed time              : {elapsed:>7.1f}s")
    print()
    print(f"  trainer_situational_stats rows: {total_rows:,}")
    print(f"  Unique trainers               : {unique_trainers:,}")
    print(f"  Situations with 10+ starts    : {rows_10plus:,}")
    print(f"  Situations with 25+ starts    : {rows_25plus:,}")

    # ── Trainer leaderboard via official grader function ──────────────────
    print()
    # Re-open /tmp DB for leaderboard (avoid CIFS read issues)
    sys.path.insert(0, str(SCRIPT_DIR))
    from horse_racing_grader import print_trainer_leaderboard
    # Temporarily patch the DB path the grader uses
    import horse_racing_grader as _hgr
    _orig_db = _hgr.DB_PATH
    _hgr.DB_PATH = TMP_DB
    print_trainer_leaderboard(min_starts=10)
    _hgr.DB_PATH = _orig_db

    print(f"\n{SEP}\n")


if __name__ == "__main__":
    main()
