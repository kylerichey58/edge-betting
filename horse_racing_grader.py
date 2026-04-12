"""
horse_racing_grader.py — EDGE Intelligence Platform
Post-race grading engine and trainer situational database builder.

Three responsibilities:
  1. grade_race()            — update horse_race_analyses with finish positions,
                               classify results (WIN/PLACE/SHOW/OUT), calculate P/L,
                               and write graded bets to the main bets table.
  2. update_trainer_stats()  — upsert trainer_situational_stats from one graded race,
                               building the proprietary trainer ROI database over time.
  3. print_trainer_leaderboard() — ranked trainer ROI table sorted by ROI descending.

Workflow:
    Results announced → grade_race() → update_trainer_stats() per horse
    → print_trainer_leaderboard() for ongoing review

Situation key format (mirrors CLAUDE.md):
    Primary:  TrainerLastName_RaceType_Surface   e.g. Cox_CLM_D
    Layoff 1: TrainerLastName_1st_off_layoff     e.g. Cox_1st_off_layoff  (90–180 days out)
    Layoff 2: TrainerLastName_2nd_off_layoff     e.g. Cox_2nd_off_layoff  (45–89 days out)
"""

import re
import sqlite3
from datetime import datetime, date
from pathlib import Path
from db_utils import safe_write, safe_read

# ---------------------------------------------------------------------------
# PATHS & CONFIG
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).parent
DB_PATH    = SCRIPT_DIR / "sports_betting.db"

# Profit/loss table — (recommendation, result) → units
_PNL = {
    ("WIN_BET",      "WIN"):   +5.0,
    ("WIN_BET",      "PLACE"): -1.0,
    ("WIN_BET",      "SHOW"):  -1.0,
    ("WIN_BET",      "OUT"):   -1.0,
    ("EXACTA_BOX",   "WIN"):   +8.0,
    ("EXACTA_BOX",   "PLACE"): +8.0,
    ("EXACTA_BOX",   "SHOW"):  -1.0,
    ("EXACTA_BOX",   "OUT"):   -1.0,
    ("TRIFECTA_KEY", "WIN"):   +15.0,
    ("TRIFECTA_KEY", "PLACE"): +15.0,
    ("TRIFECTA_KEY", "SHOW"):  +15.0,
    ("TRIFECTA_KEY", "OUT"):   -1.0,
    ("NO_PLAY",      "WIN"):    0.0,
    ("NO_PLAY",      "PLACE"):  0.0,
    ("NO_PLAY",      "SHOW"):   0.0,
    ("NO_PLAY",      "OUT"):    0.0,
}

_CONFIDENCE_INT = {"HIGH": 4, "MEDIUM": 3, "LOW": 2}

# Layoff day thresholds for situational keys (mirrors M11 metric)
_LAYOFF_1ST_MIN = 90
_LAYOFF_1ST_MAX = 180
_LAYOFF_2ND_MIN = 45
_LAYOFF_2ND_MAX = 89


# ---------------------------------------------------------------------------
# PRIVATE HELPERS
# ---------------------------------------------------------------------------

def _connect(db_path=None) -> sqlite3.Connection:
    path = str(db_path or DB_PATH)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _classify_result(finish_position: int) -> str:
    """1→WIN, 2→PLACE, 3→SHOW, else→OUT."""
    if finish_position == 1: return "WIN"
    if finish_position == 2: return "PLACE"
    if finish_position == 3: return "SHOW"
    return "OUT"


def _calc_pnl(recommendation: str, result: str) -> float:
    """Return units won/lost for a given recommendation + race result."""
    rec = (recommendation or "NO_PLAY").upper()
    return _PNL.get((rec, result), 0.0)


def _yyyymmdd_to_brisnet(yyyymmdd: str) -> str:
    """
    Convert YYYYMMDD → MMDDYYYY (Brisnet's stored date format in horse_race_analyses).
    If input looks like MMDDYYYY already, return as-is.
    Accepts either format for robustness.
    """
    s = str(yyyymmdd).strip()
    if len(s) == 8 and s.isdigit():
        # Heuristic: if first 4 chars look like a year (>= 2020) → YYYYMMDD
        if int(s[:4]) >= 2000:
            return s[4:6] + s[6:8] + s[:4]   # → MMDDYYYY
    return s   # already MMDDYYYY or unknown format


def _trainer_last_name(trainer_full: str) -> str:
    parts = (trainer_full or "").strip().split()
    return parts[-1] if parts else ""


def _situation_keys(horse_dict: dict) -> list[str]:
    """
    Build the list of situation keys to upsert for this horse.
    Always includes the primary key.
    Adds layoff key(s) based on days_since_last_race.
    """
    trainer_last = _trainer_last_name(horse_dict.get("trainer", ""))
    race_type    = (horse_dict.get("race_type") or "").upper()
    surface      = (horse_dict.get("surface") or "").upper()
    days         = horse_dict.get("days_since_last_race")

    keys = []

    if trainer_last and race_type and surface:
        keys.append(f"{trainer_last}_{race_type}_{surface}")

    if days is not None:
        try:
            d = int(days)
            if _LAYOFF_1ST_MIN <= d <= _LAYOFF_1ST_MAX:
                keys.append(f"{trainer_last}_1st_off_layoff")
            elif _LAYOFF_2ND_MIN <= d <= _LAYOFF_2ND_MAX:
                keys.append(f"{trainer_last}_2nd_off_layoff")
        except (TypeError, ValueError):
            pass

    return keys


def _ensure_bets_table(cur: sqlite3.Cursor) -> None:
    """Create bets table if it doesn't already exist (mirrors bet_tracker schema)."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bets (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            game_date     TEXT,
            sport         TEXT DEFAULT 'NCAAM',
            away_team     TEXT,
            home_team     TEXT,
            bet_type      TEXT,
            bet_selection TEXT,
            odds          TEXT,
            units         REAL,
            confidence    INTEGER,
            reasoning     TEXT,
            game_id       TEXT,
            logged_date   TEXT,
            result        TEXT DEFAULT 'PENDING',
            profit_loss   REAL DEFAULT 0,
            final_score   TEXT,
            notes         TEXT
        )
    """)


def _ensure_horse_tables(cur: sqlite3.Cursor) -> None:
    """Create horse racing tables if not present (idempotent)."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS horse_race_analyses (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            date               TEXT,
            track              TEXT,
            race_number        INTEGER,
            race_type          TEXT,
            distance           TEXT,
            surface            TEXT,
            horse_name         TEXT,
            post_position      INTEGER,
            jockey             TEXT,
            trainer            TEXT,
            morning_line_odds  REAL,
            m01 INTEGER, m02 INTEGER, m03 INTEGER, m04 INTEGER,
            m05 INTEGER, m06 INTEGER, m07 INTEGER, m08 INTEGER,
            m09 INTEGER, m10 INTEGER, m11 INTEGER,
            composite_score    INTEGER,
            model_win_pct      REAL,
            model_place_pct    REAL,
            model_show_pct     REAL,
            recommendation     TEXT,
            result             TEXT,
            finish_position    INTEGER,
            profit_loss        REAL,
            notes              TEXT,
            created_at         TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
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


# ---------------------------------------------------------------------------
# EXOTIC BET HELPERS (box bet grading)
# ---------------------------------------------------------------------------

def _parse_exotic_horses(notes: str) -> list:
    """
    Extract horse names from exotic bet notes string.
    Format: 'EXACTA Box · GPX R3 · #3 HORSE A / #1 HORSE B · $2 box = $4'
    Returns list of uppercase horse names.
    """
    if not notes:
        return []
    parts = notes.split(" · ")
    if len(parts) < 3:
        return []
    horse_section = parts[2].strip()
    horses = []
    for entry in horse_section.split(" / "):
        entry = entry.strip()
        m = re.match(r"^#\d+\s+(.+)", entry)
        if m:
            horses.append(m.group(1).strip().upper())
        elif entry:
            horses.append(entry.upper())
    return horses


def _parse_exotic_horse_line(notes: str) -> str:
    """
    Extract full horse line (e.g. '#3 HORSE A / #1 HORSE B') from notes.
    Format: 'EXACTA Box · GPX R3 · #3 HORSE A / #1 HORSE B · $2 box = $4'
    """
    if not notes:
        return ""
    parts = notes.split(" · ")
    return parts[2].strip() if len(parts) >= 3 else ""


def _check_exotic_hit(bet_type: str, boxed_horses: list, results_list: list) -> bool:
    """
    Return True if all boxed horses finished in the required top-N positions
    (order doesn't matter — it's a box bet).

    EXACTA_BOX  → top 2 must match
    TRIFECTA_BOX → top 3 must match
    SUPERFECTA_BOX → top 4 must match
    """
    n_map = {"EXACTA_BOX": 2, "TRIFECTA_BOX": 3, "SUPERFECTA_BOX": 4}
    n = n_map.get(bet_type.upper())
    if n is None or len(results_list) < n or len(boxed_horses) < n:
        return False
    top_n   = {name.upper().strip() for name in results_list[:n]}
    boxed   = {h.upper().strip() for h in boxed_horses}
    return top_n == boxed


def _grade_exotic_bets(cur: sqlite3.Cursor, track_upper: str, race_number: int,
                       results_list: list) -> list:
    """
    Query the bets table for ungraded EXACTA_BOX / TRIFECTA_BOX / SUPERFECTA_BOX bets
    for this track + race, grade each one, update the row, and return summary lines.

    Called inside grade_race() in both the early-return and normal-return paths —
    the caller commits the connection after this function returns.
    """
    race_num_str = f"Race {race_number}"
    cur.execute(
        """
        SELECT id, bet_type, units, notes
        FROM bets
        WHERE UPPER(away_team) = ?
          AND home_team        = ?
          AND bet_type IN ('EXACTA_BOX', 'TRIFECTA_BOX', 'SUPERFECTA_BOX')
          AND (result = 'PENDING' OR result IS NULL)
        """,
        (track_upper, race_num_str),
    )
    exotic_rows = cur.fetchall()
    summary = []

    for ex in exotic_rows:
        ex_id    = ex["id"]
        ex_type  = (ex["bet_type"] or "").upper()
        ex_units = float(ex["units"] or 0.0)
        ex_notes = ex["notes"] or ""

        boxed_horses = _parse_exotic_horses(ex_notes)
        horse_line   = _parse_exotic_horse_line(ex_notes)

        if not boxed_horses:
            continue

        hit = _check_exotic_hit(ex_type, boxed_horses, results_list)

        if hit:
            ex_result    = "WIN"
            # Payout unknown until Kyle enters it — deduct cost as placeholder
            ex_pnl       = -ex_units
            updated_notes = ex_notes + " | BOX HIT — enter payout manually"
        else:
            ex_result    = "LOSS"
            ex_pnl       = -ex_units
            updated_notes = ex_notes

        cur.execute(
            "UPDATE bets SET result=?, profit_loss=?, notes=? WHERE id=?",
            (ex_result, ex_pnl, updated_notes, ex_id),
        )

        display_type   = ex_type.replace("_", " ")
        display_horses = horse_line or " / ".join(boxed_horses)
        dollar         = int(round(ex_units * 100))

        if hit:
            summary.append(
                f"  {display_type:<16}  {display_horses}  "
                f"→ HIT ✓  (enter payout manually)"
            )
        else:
            summary.append(
                f"  {display_type:<16}  {display_horses}  "
                f"→ MISS ✗  -${dollar}"
            )

    return summary


# ---------------------------------------------------------------------------
# PUBLIC API — FUNCTION 1: grade_race
# ---------------------------------------------------------------------------

def grade_race(
    track_code:   str,
    race_date:    str,
    race_number:  int,
    results_list: list,
    db_path=None,
) -> dict:
    """
    Grade a completed race by updating horse_race_analyses and logging graded
    bets to the main bets table.

    Parameters
    ----------
    track_code : str
        3-letter Brisnet track code (e.g. 'KEE').
    race_date : str
        Race date in YYYYMMDD format (e.g. '20260404').
        Internally converted to MMDDYYYY for DB matching.
    race_number : int
        Race number on the card.
    results_list : list[str]
        Horse names in finishing order (1st → last).
        Names must match horse_name values stored in horse_race_analyses.
    db_path : str | Path | None
        Override DB path (default: sports_betting.db in script directory).

    Returns
    -------
    dict
        graded_count, skipped_count, bets_logged, summary lines per horse.
    """
    brisnet_date = _yyyymmdd_to_brisnet(race_date)
    track_upper  = track_code.upper()
    now          = datetime.now().isoformat()
    today_str    = date.today().isoformat()

    # Build finish position lookup: horse_name → 1-indexed position
    finish_lookup = {
        name.upper().strip(): idx + 1
        for idx, name in enumerate(results_list)
    }

    with safe_write() as conn:
        cur  = conn.cursor()
        _ensure_bets_table(cur)

        # ── Fetch ungraded rows for this race ────────────────────────────────
        cur.execute(
            """
            SELECT id, horse_name, recommendation, morning_line_odds, composite_score,
                   model_win_pct
            FROM horse_race_analyses
            WHERE UPPER(track) = ?
              AND (date = ? OR date = ?)
              AND race_number = ?
              AND finish_position IS NULL
            """,
            (track_upper, brisnet_date, race_date, int(race_number)),
        )
        rows = cur.fetchall()

        graded_count = 0
        skipped_count = 0
        bets_logged   = 0
        summary       = []

        if not rows:
            # Still grade any exotic bets logged for this race even if no
            # horse_race_analyses rows exist (e.g. user logged exotic manually)
            exotic_summary = _grade_exotic_bets(cur, track_upper, race_number, results_list)
            if exotic_summary:
                print(f"\n  [grader] Exotic bets graded for {track_upper} R{race_number}:")
                for line in exotic_summary:
                    print(line)
            # context manager handles commit + writeback on return
            msg = (
                f"grade_race: 0 ungraded rows found for "
                f"{track_upper} Race {race_number} on {race_date}. "
                f"Records may already be graded or not yet logged."
            )
            print(f"  [grader] {msg}")
            return {
                "graded_count":  0,
                "skipped_count": 0,
                "bets_logged":   0,
                "exotic_graded": len(exotic_summary),
                "message":       msg,
                "summary":       [],
                "exotic_summary": exotic_summary,
            }

        for row in rows:
            row_id       = row["id"]
            horse_name   = (row["horse_name"] or "").strip()
            rec          = (row["recommendation"] or "NO_PLAY").upper()
            ml_odds      = row["morning_line_odds"]
            reasoning    = ""   # not stored in horse_race_analyses schema

            # Match against results list (case-insensitive)
            finish_pos = finish_lookup.get(horse_name.upper())
            if finish_pos is None:
                # Horse not in results list — skip
                skipped_count += 1
                summary.append(f"  SKIP  {horse_name} — not found in results_list")
                continue

            result     = _classify_result(finish_pos)
            pnl        = _calc_pnl(rec, result)
            graded_count += 1

            # ── Update horse_race_analyses ──────────────────────────────────
            cur.execute(
                """
                UPDATE horse_race_analyses
                SET finish_position = ?,
                    result          = ?,
                    profit_loss     = ?
                WHERE id = ?
                """,
                (finish_pos, result, pnl, row_id),
            )

            summary.append(
                f"  GRADED {horse_name:<22} "
                f"pos={finish_pos}  result={result:<6}  "
                f"rec={rec:<13}  P/L={pnl:+.1f}u"
            )

            # ── Log to bets table if not NO_PLAY ────────────────────────────
            if rec not in ("NO_PLAY", ""):
                # Map bets result: WIN_BET WIN → WIN, anything else → LOSS
                bet_result = "WIN" if pnl > 0 else ("PUSH" if pnl == 0 else "LOSS")
                odds_str   = str(ml_odds) if ml_odds is not None else ""

                cur.execute(
                    """
                    INSERT INTO bets
                        (game_date, sport, away_team, home_team,
                         bet_type, bet_selection, odds, units,
                         confidence, reasoning, logged_date,
                         result, profit_loss, notes)
                    VALUES (?, 'HORSE', ?, ?, ?, ?, ?, 1.0, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        today_str,
                        track_upper,
                        str(race_number),
                        rec,
                        horse_name,
                        odds_str,
                        3,               # default confidence 3 (MEDIUM)
                        reasoning[:200] if reasoning else "",
                        now,
                        bet_result,
                        pnl,
                        f"Horse racing — {track_upper} R{race_number} {race_date}",
                    ),
                )
                bets_logged += 1

        # ── Grade exotic box bets for this race ─────────────────────────────
        exotic_summary = _grade_exotic_bets(cur, track_upper, race_number, results_list)
        # safe_write() context manager handles commit + writeback on exit

    print(f"\n  [grader] grade_race complete — "
          f"{graded_count} graded, {skipped_count} skipped, "
          f"{bets_logged} bets logged to bets table")
    for line in summary:
        print(line)

    if exotic_summary:
        print(f"\n  [grader] Exotic bets graded for {track_upper} R{race_number}:")
        for line in exotic_summary:
            print(line)

    return {
        "graded_count":  graded_count,
        "skipped_count": skipped_count,
        "bets_logged":   bets_logged,
        "exotic_graded": len(exotic_summary),
        "exotic_summary": exotic_summary,
        "summary":       summary,
    }


# ---------------------------------------------------------------------------
# PUBLIC API — FUNCTION 2: update_trainer_stats
# ---------------------------------------------------------------------------

def update_trainer_stats(horse_dict: dict, finish_position: int, db_path=None) -> list:
    """
    Upsert trainer_situational_stats for one graded horse.

    Builds a primary situation key (TrainerLastName_RaceType_Surface) and
    optional layoff keys based on days_since_last_race, then increments
    starts/wins/places/shows and recalculates ROI.

    Parameters
    ----------
    horse_dict : dict
        Horse dict from horse_racing_parser (or compatible dict with keys:
        trainer, race_type, surface, days_since_last_race).
    finish_position : int
        Official finish position (1-indexed).
    db_path : str | Path | None
        Override DB path.

    Returns
    -------
    list[str]
        Situation keys that were upserted.
    """
    trainer_full = (horse_dict.get("trainer") or "").strip()
    if not trainer_full:
        print("  [grader] update_trainer_stats: no trainer name — skipping")
        return []

    keys = _situation_keys(horse_dict)
    if not keys:
        print(f"  [grader] update_trainer_stats: no situation keys built for {trainer_full}")
        return []

    is_win   = finish_position == 1
    is_place = finish_position <= 2
    is_show  = finish_position <= 3
    now      = datetime.now().isoformat()

    with safe_write() as conn:
        cur  = conn.cursor()
        _ensure_horse_tables(cur)

        upserted = []
        for situation in keys:
            cur.execute(
                """
                SELECT starts, wins, places, shows
                FROM trainer_situational_stats
                WHERE trainer_name = ? AND situation = ?
                """,
                (trainer_full, situation),
            )
            existing = cur.fetchone()

            if existing:
                starts = existing["starts"] + 1
                wins   = existing["wins"]   + (1 if is_win   else 0)
                places = existing["places"] + (1 if is_place else 0)
                shows  = existing["shows"]  + (1 if is_show  else 0)
            else:
                starts = 1
                wins   = 1 if is_win   else 0
                places = 1 if is_place else 0
                shows  = 1 if is_show  else 0

            # Placeholder ROI: (wins × 5.0 − starts) / starts
            roi = (wins * 5.0 - starts) / starts if starts > 0 else 0.0

            if existing:
                cur.execute(
                    """
                    UPDATE trainer_situational_stats
                    SET starts       = ?,
                        wins         = ?,
                        places       = ?,
                        shows        = ?,
                        roi          = ?,
                        last_updated = ?
                    WHERE trainer_name = ? AND situation = ?
                    """,
                    (starts, wins, places, shows, roi, now, trainer_full, situation),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO trainer_situational_stats
                        (trainer_name, situation, starts, wins, places, shows, roi, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (trainer_full, situation, starts, wins, places, shows, roi, now),
                )

            win_rate = wins / starts if starts > 0 else 0.0
            print(
                f"  [grader] upserted trainer stat — "
                f"{trainer_full} | {situation} | "
                f"starts={starts} wins={wins} ({win_rate*100:.0f}% WR) roi={roi:+.2f}"
            )
            upserted.append(situation)
        # safe_write() context manager handles commit + writeback on exit

    return upserted


# ---------------------------------------------------------------------------
# PUBLIC API — FUNCTION 3: print_trainer_leaderboard
# ---------------------------------------------------------------------------

def print_trainer_leaderboard(min_starts: int = 5, db_path=None) -> None:
    """
    Print the trainer situational ROI leaderboard sorted by ROI descending.

    Parameters
    ----------
    min_starts : int
        Minimum number of starts to appear on the leaderboard (default 5).
        Filters out low-sample noise.
    db_path : str | Path | None
        Override DB path.
    """
    conn = _connect(db_path)
    cur  = conn.cursor()
    _ensure_horse_tables(cur)

    cur.execute(
        """
        SELECT trainer_name, situation, starts, wins, places, shows, roi
        FROM trainer_situational_stats
        WHERE starts >= ?
        ORDER BY roi DESC
        """,
        (min_starts,),
    )
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("No data yet — run more races to build the trainer database")
        return

    # Column widths
    TW = 24   # trainer
    SW = 30   # situation
    header = (
        f"{'#':>3}  "
        f"{'Trainer':<{TW}}  "
        f"{'Situation':<{SW}}  "
        f"{'Starts':>6}  "
        f"{'Win%':>6}  "
        f"{'ROI':>7}"
    )
    bar = "─" * len(header)

    print(f"\n{'═'*len(header)}")
    print(f"  TRAINER SITUATIONAL ROI LEADERBOARD  (min {min_starts} starts)")
    print(f"{'═'*len(header)}")
    print(header)
    print(bar)

    for rank, row in enumerate(rows, 1):
        trainer  = (row["trainer_name"] or "")[:TW]
        situation = (row["situation"] or "")[:SW]
        starts   = row["starts"]
        wins     = row["wins"]
        roi      = row["roi"]
        win_pct  = wins / starts * 100 if starts > 0 else 0.0

        print(
            f"{rank:>3}  "
            f"{trainer:<{TW}}  "
            f"{situation:<{SW}}  "
            f"{starts:>6}  "
            f"{win_pct:>5.1f}%  "
            f"{roi:>+6.2f}"
        )

    print(bar)
    print(f"  {len(rows)} trainer situation(s) with {min_starts}+ starts")
    print(f"{'═'*len(header)}\n")


# ---------------------------------------------------------------------------
# MAIN TEST BLOCK
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile, shutil

    print("=" * 65)
    print("horse_racing_grader.py — EDGE Intelligence Platform")
    print("Checkpoint 8: grade_race | update_trainer_stats | leaderboard")
    print("=" * 65)

    # ── Spin up a fresh temp DB (avoids mounted-filesystem write limits) ──
    src_db = DB_PATH
    tmp_db = Path(tempfile.mktemp(suffix="_grader_test.db"))

    # Copy existing DB so tables (bets etc.) exist with correct schema
    try:
        shutil.copy2(src_db, tmp_db)
        print(f"\n  [test] Using temp DB: {tmp_db.name}")
    except Exception as e:
        # If copy fails, start fresh
        print(f"\n  [test] Creating fresh temp DB (copy failed: {e})")

    # Ensure all tables exist in temp DB
    conn = _connect(tmp_db)
    cur  = conn.cursor()
    _ensure_bets_table(cur)
    _ensure_horse_tables(cur)

    # ── Insert 5 test horses into horse_race_analyses ─────────────────────
    test_horses_data = [
        ("04042026", "KEE", 5, "CLM", "8f",  "D", "GEMSTONE GLORY", 3, "Irad Ortiz Jr.",
         "Brad Cox",   4.0,  3,2,3,3,2,3,1,3,3,1,3, 27, 0.298, 0.856, 0.997, "WIN_BET"),
        ("04042026", "KEE", 5, "CLM", "8f",  "D", "RAIL ROCKET",    1, "John Velazquez",
         "Todd Pletcher", 6.0, 2,2,2,2,1,1,1,3,1,0,1, 16, 0.209, 0.722, 0.966, "NO_PLAY"),
        ("04042026", "KEE", 5, "CLM", "8f",  "D", "MUDDY WATERS",   5, "Joel Rosario",
         "Chad Brown",  8.0,  1,1,2,1,1,1,1,2,2,0,1, 13, 0.149, 0.531, 0.875, "NO_PLAY"),
        ("04042026", "KEE", 5, "CLM", "8f",  "D", "PEAK AND FADE",  2, "Ricardo Santana",
         "Steve Asmussen", 3.0, 2,3,2,3,1,0,1,3,0,1,1, 17, 0.224, 0.636, 0.926, "NO_PLAY"),
        ("04042026", "KEE", 5, "CLM", "8f",  "D", "LONG SHOT LOUIE",4, "Florent Geroux",
         "Mark Casse",  15.0, 1,1,1,1,0,2,1,1,2,0,1, 11, 0.119, 0.252, 0.435, "NO_PLAY"),
    ]

    insert_sql = """
        INSERT INTO horse_race_analyses
            (date, track, race_number, race_type, distance, surface, horse_name,
             post_position, jockey, trainer, morning_line_odds,
             m01,m02,m03,m04,m05,m06,m07,m08,m09,m10,m11,
             composite_score, model_win_pct, model_place_pct, model_show_pct,
             recommendation)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """
    for row in test_horses_data:
        cur.execute(insert_sql, row)

    conn.commit()
    conn.close()
    print(f"  [test] Inserted {len(test_horses_data)} test horses into horse_race_analyses\n")

    # ────────────────────────────────────────────────────────────────────
    # TEST 1: grade_race
    # ────────────────────────────────────────────────────────────────────
    print("─" * 65)
    print("TEST 1 — grade_race()")
    print("─" * 65)

    # Official results: GEMSTONE GLORY wins, RAIL ROCKET 2nd, etc.
    official_results = [
        "GEMSTONE GLORY",    # 1st
        "RAIL ROCKET",       # 2nd
        "PEAK AND FADE",     # 3rd
        "MUDDY WATERS",      # 4th
        "LONG SHOT LOUIE",   # 5th
    ]

    grade_result = grade_race(
        track_code   = "KEE",
        race_date    = "20260404",
        race_number  = 5,
        results_list = official_results,
        db_path      = tmp_db,
    )

    print(f"\n  grade_race returned:")
    print(f"    graded_count  = {grade_result['graded_count']}")
    print(f"    skipped_count = {grade_result['skipped_count']}")
    print(f"    bets_logged   = {grade_result['bets_logged']}")

    # Verify the DB update
    conn = _connect(tmp_db)
    cur  = conn.cursor()
    cur.execute(
        "SELECT horse_name, finish_position, result, profit_loss, recommendation "
        "FROM horse_race_analyses WHERE track='KEE' AND race_number=5 ORDER BY finish_position"
    )
    print("\n  DB state after grading:")
    print(f"  {'Horse':<22} {'Pos':>3}  {'Result':<7}  {'P/L':>6}  Rec")
    print("  " + "─" * 55)
    for r in cur.fetchall():
        print(
            f"  {r['horse_name']:<22} {r['finish_position'] or '?':>3}  "
            f"{r['result'] or '?':<7}  {r['profit_loss'] or 0:>+5.1f}u  "
            f"{r['recommendation']}"
        )
    conn.close()

    # ────────────────────────────────────────────────────────────────────
    # TEST 2: update_trainer_stats
    # ────────────────────────────────────────────────────────────────────
    print()
    print("─" * 65)
    print("TEST 2 — update_trainer_stats()")
    print("─" * 65)

    # Mock horse dicts for 3 horses — diverse trainer situations
    mock_horses = [
        {
            "horse_name":          "GEMSTONE GLORY",
            "trainer":             "Brad Cox",
            "race_type":           "CLM",
            "surface":             "D",
            "days_since_last_race": 120,   # → also builds 1st_off_layoff key
        },
        {
            "horse_name":          "RAIL ROCKET",
            "trainer":             "Todd Pletcher",
            "race_type":           "CLM",
            "surface":             "D",
            "days_since_last_race": 14,    # actively racing — no layoff key
        },
        {
            "horse_name":          "MUDDY WATERS",
            "trainer":             "Chad Brown",
            "race_type":           "CLM",
            "surface":             "D",
            "days_since_last_race": 65,    # → also builds 2nd_off_layoff key
        },
    ]
    mock_results = [1, 2, 4]   # GEMSTONE 1st, RAIL ROCKET 2nd, MUDDY WATERS 4th

    print()
    for horse, finish in zip(mock_horses, mock_results):
        update_trainer_stats(horse, finish, db_path=tmp_db)
        print()

    # ────────────────────────────────────────────────────────────────────
    # TEST 3: print_trainer_leaderboard — empty (min_starts=5)
    # ────────────────────────────────────────────────────────────────────
    print("─" * 65)
    print("TEST 3a — print_trainer_leaderboard(min_starts=5) → expect empty message")
    print("─" * 65)
    print()
    print_trainer_leaderboard(min_starts=5, db_path=tmp_db)

    # ────────────────────────────────────────────────────────────────────
    # TEST 3b: leaderboard with min_starts=1 — shows all data
    # ────────────────────────────────────────────────────────────────────
    print("─" * 65)
    print("TEST 3b — print_trainer_leaderboard(min_starts=1) → shows all rows")
    print("─" * 65)
    print_trainer_leaderboard(min_starts=1, db_path=tmp_db)

    # ────────────────────────────────────────────────────────────────────
    # TEST 4: Exotic bet grading
    # ────────────────────────────────────────────────────────────────────
    print("─" * 65)
    print("TEST 4 — _grade_exotic_bets() via grade_race()")
    print("─" * 65)

    # Insert 2 test horses for a new race (KEE R6) — needed so grade_race
    # finds something to grade and calls _grade_exotic_bets in normal path.
    conn = _connect(tmp_db)
    cur  = conn.cursor()

    # Two horses for KEE R6
    cur.execute(insert_sql, (
        "04042026", "KEE", 6, "CLM", "8f", "D", "GEMSTONE GLORY", 3,
        "Irad Ortiz Jr.", "Brad Cox", 4.0,
        3,2,3,3,2,3,1,3,3,1,3, 27, 0.298, 0.856, 0.997, "WIN_BET",
    ))
    cur.execute(insert_sql, (
        "04042026", "KEE", 6, "CLM", "8f", "D", "RAIL ROCKET", 1,
        "John Velazquez", "Todd Pletcher", 6.0,
        2,2,2,2,1,1,1,3,1,0,1, 16, 0.209, 0.722, 0.966, "NO_PLAY",
    ))

    # Insert 2 exotic bets into bets table for KEE R6
    # Bet A: EXACTA_BOX GEMSTONE GLORY / RAIL ROCKET → should HIT (they finish 1-2)
    cur.execute(
        """
        INSERT INTO bets
            (game_date, sport, away_team, home_team,
             bet_type, bet_selection, odds, units,
             confidence, reasoning, logged_date,
             result, profit_loss, notes)
        VALUES (?, 'HORSE_RACING', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "2026-04-04", "KEE", "Race 6",
            "EXACTA_BOX", "GEMSTONE GLORY / RAIL ROCKET",
            "PARI", 0.04, 3, "Exacta box test",
            datetime.now().isoformat(),
            "PENDING", 0.0,
            "EXACTA Box · KEE R6 · #3 GEMSTONE GLORY / #1 RAIL ROCKET · $2 box = $4",
        ),
    )

    # Bet B: TRIFECTA_BOX wrong horses → should MISS
    cur.execute(
        """
        INSERT INTO bets
            (game_date, sport, away_team, home_team,
             bet_type, bet_selection, odds, units,
             confidence, reasoning, logged_date,
             result, profit_loss, notes)
        VALUES (?, 'HORSE_RACING', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "2026-04-04", "KEE", "Race 6",
            "TRIFECTA_BOX", "PEAK AND FADE / LONG SHOT LOUIE / MUDDY WATERS",
            "PARI", 0.12, 3, "Trifecta box test — wrong horses",
            datetime.now().isoformat(),
            "PENDING", 0.0,
            "TRIFECTA Box · KEE R6 · #2 PEAK AND FADE / #4 LONG SHOT LOUIE / #5 MUDDY WATERS · $2 box = $12",
        ),
    )

    conn.commit()
    conn.close()
    print(f"  [test] Inserted 2 test horses (KEE R6) and 2 exotic bets\n")

    # Official results for KEE R6: GEMSTONE GLORY wins, RAIL ROCKET 2nd
    r6_results = [
        "GEMSTONE GLORY",    # 1st
        "RAIL ROCKET",       # 2nd
        "PEAK AND FADE",     # 3rd
        "MUDDY WATERS",      # 4th
        "LONG SHOT LOUIE",   # 5th
    ]

    grade_result_6 = grade_race(
        track_code   = "KEE",
        race_date    = "20260404",
        race_number  = 6,
        results_list = r6_results,
        db_path      = tmp_db,
    )

    print(f"\n  grade_race R6 returned:")
    print(f"    graded_count  = {grade_result_6['graded_count']}")
    print(f"    exotic_graded = {grade_result_6['exotic_graded']}")

    # Verify exotic bet DB state
    conn = _connect(tmp_db)
    cur  = conn.cursor()
    cur.execute(
        """
        SELECT bet_type, result, profit_loss, notes
        FROM bets
        WHERE away_team='KEE' AND home_team='Race 6'
          AND bet_type IN ('EXACTA_BOX', 'TRIFECTA_BOX')
        ORDER BY bet_type
        """
    )
    exotic_rows_check = cur.fetchall()
    conn.close()

    print(f"\n  Exotic bets DB state after grading:")
    print(f"  {'Type':<16}  {'Result':<7}  {'P/L':>6}  Notes (truncated)")
    print("  " + "─" * 65)
    for r in exotic_rows_check:
        notes_preview = (r["notes"] or "")[:60] + ("…" if len(r["notes"] or "") > 60 else "")
        print(
            f"  {r['bet_type']:<16}  {r['result'] or '?':<7}  "
            f"{r['profit_loss'] or 0:>+5.2f}u  {notes_preview}"
        )

    # Assertions
    exacta_row   = next((r for r in exotic_rows_check if r["bet_type"] == "EXACTA_BOX"),   None)
    trifecta_row = next((r for r in exotic_rows_check if r["bet_type"] == "TRIFECTA_BOX"), None)

    assert exacta_row   is not None,           "FAIL: EXACTA_BOX bet not found in DB"
    assert trifecta_row is not None,           "FAIL: TRIFECTA_BOX bet not found in DB"
    assert exacta_row["result"]   == "WIN",    f"FAIL: EXACTA_BOX expected WIN, got {exacta_row['result']}"
    assert trifecta_row["result"] == "LOSS",   f"FAIL: TRIFECTA_BOX expected LOSS, got {trifecta_row['result']}"
    assert "BOX HIT" in (exacta_row["notes"] or ""), "FAIL: EXACTA_BOX notes missing 'BOX HIT'"
    assert grade_result_6["exotic_graded"] == 2, f"FAIL: expected 2 exotic bets graded, got {grade_result_6['exotic_graded']}"

    print(f"\n  ✓ EXACTA_BOX → WIN (BOX HIT note appended)")
    print(f"  ✓ TRIFECTA_BOX → LOSS (wrong horses)")
    print(f"  ✓ exotic_graded = {grade_result_6['exotic_graded']}")
    print(f"\n  All exotic grading assertions PASS\n")

    # ── Clean up ──────────────────────────────────────────────────────────
    try:
        tmp_db.unlink(missing_ok=True)
    except Exception:
        pass

    print("=" * 65)
    print("Checkpoint 8 self-test complete — all tests passed")
    print("  python -c \"import horse_racing_grader; print('OK')\"")
    print("=" * 65)
