"""
edge_server.py — EDGE Intelligence Platform Horse Racing Backend
================================================================
Local Flask API server for the Trainer Scout tab.

HOW TO RUN
----------
  cd C:\\Users\\kyler\\Documents\\Sportsbetting
  python edge_server.py

Then open EDGE-Platform.html via:
  python -m http.server 8080
  → navigate to localhost:8080/EDGE-Platform.html → Trainer Scout tab

The Trainer Scout JS calls http://localhost:5050/horse/simulate and
http://localhost:5050/horse/grade. CORS is enabled so the static file
server on port 8080 can call this server on port 5050.

ROUTES
------
  GET  /health           — health check, returns {"status": "ok"}
  POST /horse/simulate   — run the Car Wash pipeline
  POST /horse/grade      — grade a completed race

WHY A SEPARATE SERVER
---------------------
EDGE-Platform.html is a static file — Game Scout calls the Anthropic
API directly from the browser (see runScout()). Horse racing requires
running Python scripts (brisnet_fetcher, scorer, simulator) which
cannot be called from the browser directly. This server bridges the gap.
"""

import os
import sys
import sqlite3
from pathlib import Path
from datetime import date, datetime

from flask import Flask, request, jsonify
from flask_cors import CORS

# ── PATH SETUP ───────────────────────────────────────────────────────────────
SPORTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SPORTS_DIR))

DB_PATH = SPORTS_DIR / "sports_betting.db"

app = Flask(__name__)
CORS(app)   # allow requests from localhost:8080


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE 0: GET /health
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    """Simple health check — used by browser console to confirm server is live."""
    return jsonify({"status": "ok"})


# ─────────────────────────────────────────────────────────────────────────────
# DEMO HORSE DATA (fallback when Brisnet file is unavailable)
# Used for local testing when .drf has not been downloaded yet.
# ─────────────────────────────────────────────────────────────────────────────

def _demo_horses(track_code: str, race_number: int) -> list:
    """Return 5 realistic demo horse dicts. Used as fallback when no DRF file."""
    return [
        {
            "horse_name": "MORNING GLORY",
            "post_position": 1, "surface": "D", "race_type": "CLM",
            "distance_yards": 1320, "morning_line": 3.0,
            "jockey": "J. Velazquez", "trainer": "Todd Pletcher",
            "trainer_meet_starts": 8, "trainer_meet_wins": 3,
            "jockey_meet_starts": 85, "jockey_meet_wins": 19,
            "first_time_lasix": False, "blinkers_change": "",
            "prime_power": 130, "days_since_last_race": 21,
            "speed_figures_last3": [98, 95, 97],
            "surfaces_last3": ["D", "D", "D"],
            "race_types_last3": ["CLM", "CLM", "CLM"],
            "finish_positions_last3": [1, 2, 1],
            "call_positions_last3": [1, 1, 2, 1, 1, 2],
        },
        {
            "horse_name": "FAST AND LOOSE",
            "post_position": 2, "surface": "D", "race_type": "CLM",
            "distance_yards": 1320, "morning_line": 5.0,
            "jockey": "I. Ortiz Jr", "trainer": "Brad Cox",
            "trainer_meet_starts": 12, "trainer_meet_wins": 4,
            "jockey_meet_starts": 92, "jockey_meet_wins": 23,
            "first_time_lasix": True, "blinkers_change": "",
            "prime_power": 125, "days_since_last_race": 65,
            "speed_figures_last3": [92, 96, 91],
            "surfaces_last3": ["D", "D", "D"],
            "race_types_last3": ["CLM", "CLM", "CLM"],
            "finish_positions_last3": [2, 1, 3],
            "call_positions_last3": [2, 2, 1, 2, 2, 1],
        },
        {
            "horse_name": "DARK STAR RISING",
            "post_position": 3, "surface": "D", "race_type": "CLM",
            "distance_yards": 1320, "morning_line": 6.0,
            "jockey": "L. Saez", "trainer": "Chad Brown",
            "trainer_meet_starts": 6, "trainer_meet_wins": 1,
            "jockey_meet_starts": 78, "jockey_meet_wins": 14,
            "first_time_lasix": False, "blinkers_change": "",
            "prime_power": 119, "days_since_last_race": 35,
            "speed_figures_last3": [88, 91, 86],
            "surfaces_last3": ["D", "T", "D"],
            "race_types_last3": ["CLM", "ALW", "CLM"],
            "finish_positions_last3": [3, 4, 2],
            "call_positions_last3": [3, 3, 4, 3, 4, 3],
        },
        {
            "horse_name": "RIVER RUNNER",
            "post_position": 4, "surface": "D", "race_type": "CLM",
            "distance_yards": 1320, "morning_line": 9.0,
            "jockey": "J. Rosario", "trainer": "Steve Asmussen",
            "trainer_meet_starts": 15, "trainer_meet_wins": 3,
            "jockey_meet_starts": 80, "jockey_meet_wins": 15,
            "first_time_lasix": False, "blinkers_change": "",
            "prime_power": 112, "days_since_last_race": 14,
            "speed_figures_last3": [85, 82, 87],
            "surfaces_last3": ["D", "D", "D"],
            "race_types_last3": ["CLM", "CLM", "CLM"],
            "finish_positions_last3": [4, 3, 5],
            "call_positions_last3": [4, 4, 3, 4, 3, 4],
        },
        {
            "horse_name": "LONGSHOT LARRY",
            "post_position": 5, "surface": "D", "race_type": "CLM",
            "distance_yards": 1320, "morning_line": 20.0,
            "jockey": "F. Geroux", "trainer": "Mark Casse",
            "trainer_meet_starts": 5, "trainer_meet_wins": 1,
            "jockey_meet_starts": 60, "jockey_meet_wins": 10,
            "first_time_lasix": False, "blinkers_change": "",
            "prime_power": 98, "days_since_last_race": 120,
            "speed_figures_last3": [75, 72, 78],
            "surfaces_last3": ["D", "D", "T"],
            "race_types_last3": ["CLM", "CLM", "CLM"],
            "finish_positions_last3": [6, 5, 7],
            "call_positions_last3": [5, 5, 5, 5, 5, 6],
        },
    ]


# ─────────────────────────────────────────────────────────────────────────────
# DB HELPER
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_horse_tables(cur: sqlite3.Cursor) -> None:
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


def _log_analyses(
    track_code: str,
    race_date: str,     # YYYYMMDD
    race_number: int,
    horses: list,
    scored: list,
    sim_results: list,
    rec: dict,
) -> None:
    """Insert ungraded rows into horse_race_analyses (skip if already present)."""
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        _ensure_horse_tables(cur)

        sim_by_name = {r["horse_name"]: r for r in sim_results}
        # Brisnet DB date format is MMDDYYYY
        mm, dd, yyyy = race_date[4:6], race_date[6:8], race_date[:4]
        db_date = f"{mm}{dd}{yyyy}"

        for s in scored:
            name  = s.get("horse_name", "")
            sim   = sim_by_name.get(name, {})
            horse = next((h for h in horses if h.get("horse_name") == name), {})

            # Skip if already logged for this exact race+horse
            cur.execute(
                """SELECT id FROM horse_race_analyses
                   WHERE UPPER(track)=? AND date=? AND race_number=? AND horse_name=?""",
                (track_code.upper(), db_date, race_number, name),
            )
            if cur.fetchone():
                continue

            cur.execute(
                """
                INSERT INTO horse_race_analyses
                    (date, track, race_number, race_type, distance, surface,
                     horse_name, post_position, jockey, trainer, morning_line_odds,
                     m01,m02,m03,m04,m05,m06,m07,m08,m09,m10,m11,
                     composite_score, model_win_pct, model_place_pct, model_show_pct,
                     recommendation)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    db_date, track_code.upper(), race_number,
                    horse.get("race_type", "CLM"),
                    str(horse.get("distance_yards", "")),
                    horse.get("surface", "D"),
                    name,
                    s.get("post_position"),
                    horse.get("jockey"),
                    horse.get("trainer"),
                    s.get("morning_line"),
                    s.get("m01", 0), s.get("m02", 0), s.get("m03", 0), s.get("m04", 0),
                    s.get("m05", 0), s.get("m06", 0), s.get("m07", 0), s.get("m08", 0),
                    s.get("m09", 0), s.get("m10", 0), s.get("m11", 0),
                    s.get("composite_score", 0),
                    sim.get("win_pct"),
                    sim.get("place_pct"),
                    sim.get("show_pct"),
                    rec.get("recommendation", "NO_PLAY"),
                ),
            )

        conn.commit()
        conn.close()
        print(f"  [db] Logged {len(scored)} horses for {track_code} R{race_number} {db_date}")
    except Exception as e:
        print(f"  [db][warn] _log_analyses failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE 1: POST /horse/simulate
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/horse/simulate", methods=["POST"])
def horse_simulate():
    """
    Run the Car Wash pipeline for a race.

    Request JSON:
        { "track_code": "KEE", "race_number": 5, "pace_scenario": 0 }

    Response JSON:
        {
          "ok": true,
          "track_code": "KEE",
          "race_number": 5,
          "race_date": "20260404",
          "data_source": "brisnet" | "demo",
          "simulation_results": [...],   # list of horse dicts sorted by win_pct desc
          "recommendation": { ... }
        }

    Pipeline:
        1. brisnet_fetcher.fetch_race_card() → .drf file path
        2. horse_racing_parser.parse_race()  → horse dicts
        3. horse_racing_scorer.score_race()  → scored dicts
        4. horse_racing_simulator.run_simulation() → Win%/Place%/Show%
        5. horse_racing_simulator.generate_recommendation() → recommendation
        6. Insert ungraded rows into horse_race_analyses
    """
    data = request.get_json(force=True) or {}
    track_code    = (data.get("track_code") or "KEE").upper().strip()
    race_number   = int(data.get("race_number", 1))
    pace_scenario = int(data.get("pace_scenario", 1))
    today_str     = date.today().strftime("%Y%m%d")

    try:
        from horse_racing_scorer    import score_race
        from horse_racing_simulator import run_simulation, generate_recommendation

        data_source = "demo"
        horses = []

        # ── Step 1–2: Load local DRF + parse ─────────────────────────────
        try:
            from brisnet_fetcher     import fetch_race_card
            from horse_racing_parser import parse_race

            file_path = fetch_race_card(track_code, today_str)

            if file_path is None:
                # No local DRF file — tell the user to download it manually.
                # Return 400 so the UI can display a clear, actionable message.
                print(f"  [sim] No DRF file for {track_code} — returning 400 to UI")
                return jsonify({
                    "ok":    False,
                    "error": (
                        f"No DRF file found for {track_code}. "
                        "Download today's PP Single File (.drf) from brisnet.com "
                        "and drop it in horse_racing_data/ then retry."
                    ),
                    "no_drf": True,
                }), 400

            horses = parse_race(file_path, race_number)

            if not horses:
                raise ValueError(f"No horses parsed for race {race_number} in {file_path}")

            data_source = "brisnet"
            print(f"  [sim] DRF loaded: {len(horses)} horses for {track_code} R{race_number}")

        except Exception as fetch_err:
            # Unexpected parse/import error — fall back to demo data so the
            # UI remains usable for testing even when something else breaks.
            print(f"  [sim] Parse error ({fetch_err}) — falling back to demo horses")
            horses = _demo_horses(track_code, race_number)

        # ── Step 3: Score ─────────────────────────────────────────────────
        m05_overrides = [pace_scenario] * len(horses)
        scored        = score_race(horses, m05_overrides=m05_overrides)

        # ── Step 4–5: Simulate + Recommend ───────────────────────────────
        sim_results = run_simulation(scored)
        rec         = generate_recommendation(sim_results)

        # ── Step 6: Log to DB ─────────────────────────────────────────────
        _log_analyses(track_code, today_str, race_number, horses, scored, sim_results, rec)

        return jsonify({
            "ok":                True,
            "track_code":        track_code,
            "race_number":       race_number,
            "race_date":         today_str,
            "data_source":       data_source,
            "simulation_results": sim_results,
            "recommendation":    rec,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE 2: POST /horse/grade
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/horse/grade", methods=["POST"])
def horse_grade():
    """
    Grade a completed race and log to bets table.

    Request JSON:
        {
          "track_code":   "KEE",
          "race_date":    "20260404",   # YYYYMMDD
          "race_number":  5,
          "results_list": ["MORNING GLORY", "FAST AND LOOSE", "DARK STAR RISING", ...]
        }

    Response JSON:
        {
          "ok": true,
          "graded_count": 3,
          "skipped_count": 2,
          "bets_logged": 1,
          "summary": ["  GRADED MORNING GLORY  pos=1 ..."],
          "rows": [
              { "horse_name": "...", "finish_position": 1, "result": "WIN",
                "profit_loss": 5.0, "recommendation": "WIN_BET" },
              ...
          ]
        }
    """
    data = request.get_json(force=True) or {}
    try:
        from horse_racing_grader import grade_race

        track_code   = (data.get("track_code") or "").upper().strip()
        race_date    = data.get("race_date", "")
        race_number  = int(data.get("race_number", 1))
        results_list = data.get("results_list", [])

        result = grade_race(
            track_code   = track_code,
            race_date    = race_date,
            race_number  = race_number,
            results_list = results_list,
            db_path      = DB_PATH,
        )

        # Fetch updated rows for the response table
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        cur  = conn.cursor()
        mm, dd, yyyy = race_date[4:6], race_date[6:8], race_date[:4]
        db_date = f"{mm}{dd}{yyyy}"
        cur.execute(
            """SELECT horse_name, finish_position, result, profit_loss, recommendation
               FROM horse_race_analyses
               WHERE UPPER(track)=? AND date=? AND race_number=?
               ORDER BY finish_position""",
            (track_code, db_date, race_number),
        )
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()

        return jsonify({
            "ok":            True,
            "graded_count":  result.get("graded_count", 0),
            "skipped_count": result.get("skipped_count", 0),
            "bets_logged":   result.get("bets_logged", 0),
            "summary":       result.get("summary", []),
            "rows":          rows,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print("=" * 58)
    print("  EDGE Server — Horse Racing Backend")
    print("=" * 58)
    print(f"  Listening on : http://localhost:{port}")
    print(f"  Sports dir   : {SPORTS_DIR}")
    print(f"  Database     : {DB_PATH}")
    print(f"  Endpoints    : GET  /health")
    print(f"                 POST /horse/simulate")
    print(f"                 POST /horse/grade")
    print()
    print("  Pair with static server:")
    print("    python -m http.server 8080")
    print("    → localhost:8080/EDGE-Platform.html → Trainer Scout tab")
    print("=" * 58)
    app.run(host="0.0.0.0", port=port, debug=False)
