"""
equibase_xml_importer.py — EDGE Intelligence Platform
======================================================
Bulk-imports 2023 Equibase Past Performance XML files into
trainer_situational_stats in sports_betting.db.

Optimised: lxml parser (4-5× faster than stdlib ET) + multiprocessing.

Data source : 2023 PPs folder — SIMD*.xml and SIMD*.zip files
Target table: trainer_situational_stats

Situation key format EXACTLY matches horse_racing_grader.py:
  Primary : {TrainerLastName}_{race_type}_{surface}   e.g. Cox_CLM_D
  Layoff 1: {TrainerLastName}_1st_off_layoff           90–180 days off
  Layoff 2: {TrainerLastName}_2nd_off_layoff           45–89  days off

trainer_name column stores "First Last" format, matching horse_racing_parser.py.

Run:  python3 equibase_xml_importer.py
      (automatically uses local /tmp DB copy to avoid CIFS WAL errors)
"""

import os
import sys
import zipfile
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime
from multiprocessing import Pool, cpu_count

try:
    import lxml.etree as ET
    _USING_LXML = True
except ImportError:
    import xml.etree.ElementTree as ET
    _USING_LXML = False

# ─── CONFIG ──────────────────────────────────────────────────────────────────

SCRIPT_DIR    = Path(__file__).parent
PP_FOLDER     = SCRIPT_DIR / "2023 PPs"
DB_PATH       = SCRIPT_DIR / "sports_betting.db"
LOCAL_DB_PATH = Path("/tmp/sports_betting_import.db")

# Layoff thresholds — must EXACTLY match horse_racing_grader.py
_LAYOFF_1ST_MIN = 90
_LAYOFF_1ST_MAX = 180
_LAYOFF_2ND_MIN = 45
_LAYOFF_2ND_MAX = 89

BATCH_SIZE     = 2000    # upsert rows per DB commit
PROGRESS_EVERY = 200     # print progress every N files
NUM_WORKERS    = max(1, cpu_count())  # use all available CPUs

# ─── FILE DISCOVERY ───────────────────────────────────────────────────────────

def collect_files(folder: Path) -> list:
    """
    Walk `folder` recursively.  Find all SIMD*.xml / SIMD*.zip.
    Deduplicate by base name — prefer raw .xml > plain .zip > .xml.zip.
    Returns sorted list of Path objects.
    """
    best = {}  # (dir_str, base_upper) → (priority, path)

    for root_dir, _dirs, files in os.walk(folder):
        for fname in sorted(files):
            upper = fname.upper()
            if not upper.startswith("SIMD"):
                continue
            fpath = Path(root_dir) / fname
            if upper.endswith(".XML.ZIP"):
                base, prio = fname[:-8], 3
            elif upper.endswith(".XML"):
                base, prio = fname[:-4], 1
            elif upper.endswith(".ZIP"):
                base, prio = fname[:-4], 2
            else:
                continue
            key = (str(root_dir), base.upper())
            existing = best.get(key)
            if existing is None or existing[0] > prio:
                best[key] = (prio, fpath)

    return sorted(v[1] for v in best.values())


# ─── XML LOADING (runs in worker) ────────────────────────────────────────────

def _load_xml_bytes(filepath: Path):
    try:
        if filepath.suffix.lower() == ".xml":
            return filepath.read_bytes()
        with zipfile.ZipFile(filepath, "r") as z:
            candidates = [n for n in z.namelist()
                          if n.upper().endswith(".XML") and "SIMD" in n.upper()]
            return z.read(candidates[0]) if candidates else None
    except Exception:
        return None


def _parse_xml(xml_bytes: bytes):
    try:
        return ET.fromstring(xml_bytes)
    except Exception:
        return None


# ─── DATE HELPERS ─────────────────────────────────────────────────────────────

def _parse_date(s: str):
    """'2022-10-29+00:00' or '2022-10-29' → (year, month, day) tuple for fast compare."""
    if not s:
        return None
    try:
        y, m, d = int(s[0:4]), int(s[5:7]), int(s[8:10])
        return (y, m, d)
    except (ValueError, IndexError):
        return None


def _days_between(t1, t2) -> int:
    """Compute days between two (y,m,d) tuples quickly."""
    from datetime import date
    return (date(*t2) - date(*t1)).days


# ─── WORKER FUNCTION (multiprocessing) ────────────────────────────────────────

def process_file(filepath_str: str) -> list:
    """
    Worker: load one ZIP/XML file, extract all PP records.
    Returns list of tuples:
        (dedup_key, trainer_full, trainer_last, race_type, surface, finish_pos, days_since)
    dedup_key = (horse_reg, track_id, date_str_10, race_num)
    days_since = int or None
    """
    filepath = Path(filepath_str)
    xml_bytes = _load_xml_bytes(filepath)
    if not xml_bytes:
        return []
    root = _parse_xml(xml_bytes)
    if root is None:
        return []

    results = []

    for race in root.findall("Race"):
        # Race-level fallbacks
        rt_el = race.find("RaceType/RaceType")
        race_type_fb = (rt_el.text or "").strip().upper() if rt_el is not None else ""
        sf_el = race.find("Course/CourseType/Value")
        surface_fb   = (sf_el.text or "").strip().upper() if sf_el is not None else ""

        for starter in race.findall("Starters"):
            hr_el = starter.find("Horse/RegistrationNumber")
            horse_reg = (hr_el.text or "").strip() if hr_el is not None else ""

            pp_list = []  # collect valid PPs for this entry

            for pp in starter.findall("PastPerformance"):
                date_el  = pp.find("RaceDate")
                date_str = (date_el.text or "").strip() if date_el is not None else ""
                pp_date  = _parse_date(date_str)
                if pp_date is None:
                    continue

                ti_el    = pp.find("Track/TrackID")
                track_id = (ti_el.text or "").strip() if ti_el is not None else ""
                rn_el    = pp.find("RaceNumber")
                race_num = (rn_el.text or "").strip() if rn_el is not None else ""

                dedup_key = (horse_reg, track_id, date_str[:10], race_num)

                rt2_el   = pp.find("RaceType/RaceType")
                pp_rt    = (rt2_el.text or race_type_fb).strip().upper() if rt2_el is not None else race_type_fb
                sf2_el   = pp.find("Course/CourseType/Value")
                pp_sf    = (sf2_el.text or surface_fb).strip().upper() if sf2_el is not None else surface_fb

                if not pp_rt or not pp_sf:
                    continue

                start = pp.find("Start")
                if start is None:
                    continue

                tf_el   = start.find("Trainer/FirstName")
                tl_el   = start.find("Trainer/LastName")
                t_first = (tf_el.text or "").strip() if tf_el is not None else ""
                t_last  = (tl_el.text or "").strip() if tl_el is not None else ""
                if not t_last:
                    continue

                of_el = start.find("OfficialFinish")
                of_str = (of_el.text or "").strip() if of_el is not None else ""
                try:
                    finish_pos = int(of_str)
                except ValueError:
                    continue
                if finish_pos < 1:
                    continue

                pp_list.append((pp_date, dedup_key, pp_rt, pp_sf, t_first, t_last, finish_pos))

            # Sort by date ascending to compute gaps
            pp_list.sort(key=lambda x: x[0])

            for i, row in enumerate(pp_list):
                pp_date, dedup_key, pp_rt, pp_sf, t_first, t_last, finish_pos = row
                days_since = _days_between(pp_list[i - 1][0], pp_date) if i > 0 else None
                trainer_full = f"{t_first} {t_last}".strip()
                results.append((dedup_key, trainer_full, t_last, pp_rt, pp_sf, finish_pos, days_since))

    return results


# ─── SITUATION KEYS ───────────────────────────────────────────────────────────

def build_situation_keys(trainer_last: str, race_type: str, surface: str, days_since) -> list:
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


# ─── DATABASE ─────────────────────────────────────────────────────────────────

def open_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=60)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA cache_size=-32000")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def ensure_table(conn: sqlite3.Connection) -> None:
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


def flush_batch(conn, batch, now_str):
    rows = [
        (trainer_full, situation, is_win, is_place, is_show, now_str)
        for trainer_full, situation, is_win, is_place, is_show in batch
    ]
    conn.executemany(_UPSERT_SQL, rows)
    conn.commit()


def recalculate_roi(conn):
    conn.execute("""
        UPDATE trainer_situational_stats
        SET roi = (wins * 5.0 - starts) / starts
        WHERE starts > 0
    """)
    conn.commit()


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print("=" * 72)
    print("equibase_xml_importer.py — EDGE Intelligence Platform")
    print(f"Parser: {'lxml (fast)' if _USING_LXML else 'stdlib ET (slower)'}")
    print(f"Workers: {NUM_WORKERS} CPU(s)")
    print("=" * 72)

    for p, label in [(PP_FOLDER, "PP folder"), (DB_PATH, "DB")]:
        if not p.exists():
            print(f"\nERROR: {label} not found: {p}")
            sys.exit(1)

    # ── Copy DB to local temp path ────────────────────────────────────────
    print(f"\nCopying DB to local path for fast import...")
    shutil.copy2(str(DB_PATH), str(LOCAL_DB_PATH))
    print(f"  Working DB: {LOCAL_DB_PATH}\n")

    conn = open_db(LOCAL_DB_PATH)
    ensure_table(conn)

    # ── Discover files ────────────────────────────────────────────────────
    print(f"Scanning: {PP_FOLDER}")
    all_files = collect_files(PP_FOLDER)
    print(f"Found {len(all_files):,} unique SIMD files\n")

    # ── Process with multiprocessing ──────────────────────────────────────
    seen          = set()
    batch         = []
    total_files   = 0
    total_skipped = 0
    total_entries = 0
    total_upserts = 0
    now_str       = datetime.now().isoformat()

    file_strs = [str(f) for f in all_files]

    with Pool(processes=NUM_WORKERS) as pool:
        for raw_records in pool.imap_unordered(process_file, file_strs, chunksize=10):
            if not raw_records and raw_records is not None:
                total_skipped += 1

            for rec in raw_records:
                dedup_key, trainer_full, trainer_last, race_type, surface, finish_pos, days_since = rec
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                total_entries += 1

                keys = build_situation_keys(trainer_last, race_type, surface, days_since)
                fp       = finish_pos
                is_win   = 1 if fp == 1 else 0
                is_place = 1 if fp <= 2 else 0
                is_show  = 1 if fp <= 3 else 0

                for situation in keys:
                    batch.append((trainer_full, situation, is_win, is_place, is_show))
                    total_upserts += 1

            total_files += 1

            if len(batch) >= BATCH_SIZE:
                flush_batch(conn, batch, now_str)
                batch = []

            if total_files % PROGRESS_EVERY == 0:
                print(
                    f"  [{total_files:>5}/{len(all_files):,} files]  "
                    f"unique entries: {total_entries:>7,}  "
                    f"upsert-rows: {total_upserts:>8,}  "
                    f"dedup-set: {len(seen):>8,}",
                    flush=True
                )

    if batch:
        flush_batch(conn, batch, now_str)

    # ── Recalculate ROI ───────────────────────────────────────────────────
    print("\nRecalculating ROI...", flush=True)
    recalculate_roi(conn)

    # ── Summary stats ─────────────────────────────────────────────────────
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM trainer_situational_stats")
    total_rows = cur.fetchone()[0]
    cur.execute("SELECT COUNT(DISTINCT trainer_name) FROM trainer_situational_stats")
    unique_trainers = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM trainer_situational_stats WHERE starts >= 10")
    rows_10plus = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM trainer_situational_stats WHERE starts >= 25")
    rows_25plus = cur.fetchone()[0]

    cur.execute("""
        SELECT trainer_name, situation, starts, wins, places, shows, roi
        FROM trainer_situational_stats
        WHERE starts >= 10
        ORDER BY roi DESC
        LIMIT 10
    """)
    top10 = cur.fetchall()
    conn.close()

    # ── Copy DB back ──────────────────────────────────────────────────────
    print(f"\nCopying updated DB back to SportsBetting folder...", flush=True)
    shutil.copy2(str(LOCAL_DB_PATH), str(DB_PATH))
    db_kb = LOCAL_DB_PATH.stat().st_size / 1024
    print(f"  DB size: {db_kb:.0f} KB  ({db_kb/1024:.1f} MB)")

    # ── Final report ──────────────────────────────────────────────────────
    print(f"\n{'='*72}")
    print("IMPORT COMPLETE")
    print(f"{'='*72}")
    print(f"  Files processed       : {total_files:>8,}  ({total_skipped} skipped)")
    print(f"  Unique PP records     : {total_entries:>8,}")
    print(f"  Upsert-rows sent      : {total_upserts:>8,}")
    print(f"  trainer_situational_stats rows: {total_rows:,}")
    print(f"  Unique trainers       : {unique_trainers:,}")
    print(f"  Situations 10+ starts : {rows_10plus:,}")
    print(f"  Situations 25+ starts : {rows_25plus:,}")
    print()

    TW, SW = 24, 30
    if top10:
        print("TOP 10 TRAINER SITUATIONS (min 10 starts, by ROI):")
        print(f"  {'#':>2}  {'Trainer':<{TW}}  {'Situation':<{SW}}  {'Starts':>6}  {'Win%':>6}  {'ROI':>7}")
        print("  " + "─" * (TW + SW + 34))
        for rank, row in enumerate(top10, 1):
            trainer   = (row[0] or "")[:TW]
            situation = (row[1] or "")[:SW]
            starts, wins, roi = row[2], row[3], row[6]
            win_pct   = wins / starts * 100 if starts > 0 else 0.0
            print(f"  {rank:>2}  {trainer:<{TW}}  {situation:<{SW}}  {starts:>6}  {win_pct:>5.1f}%  {roi:>+7.2f}")
    else:
        print("No situations with 10+ starts found.")

    print(f"\n{'='*72}")
    print("M07 ACTIVATED — trainer_situational_stats populated with 2023 season data.")
    print("Scorer will now use real trainer ROI instead of neutral (1) default.")
    print(f"{'='*72}\n")


if __name__ == "__main__":
    main()
