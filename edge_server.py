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

The Trainer Scout JS calls http://localhost:5050/horse/grade. CORS is
enabled so the static file server on port 8080 can call this server
on port 5050.

ROUTES
------
  GET  /health           — health check, returns {"status": "ok"}
  GET  /horse/tracks     — list available tracks from local DRF files
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
# ROUTE 0b: GET /horse/tracks
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/horse/tracks", methods=["GET"])
def horse_tracks():
    """
    Return available tracks from local DRF files.

    Called every time the Trainer Scout Refresh (↺) button is clicked.
    Calls auto_move_downloads() FIRST — moves any *k.zip PP Single File ZIPs
    from Downloads/ to horse_racing_data/, extracts them, and deletes the ZIP.
    (*k.zip = PP Single File format. *n.zip = entries format — ignored.)

    Response JSON:
        {
          "ok": true,
          "tracks": [
            { "value": "PEN", "label": "PEN — 04/08", "mmdd": "0408" },
            { "value": "MVR", "label": "MVR — 04/08", "mmdd": "0408" },
            ...
          ]
        }

    Returns empty tracks list if no DRF files are present.
    """
    try:
        from brisnet_fetcher import get_available_tracks, auto_move_downloads
        auto_move_downloads()   # move + extract + delete any *k.zip in Downloads/
        tracks = get_available_tracks()
        return jsonify({"ok": True, "tracks": tracks})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e), "tracks": []}), 500


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
    print(f"                 GET  /horse/tracks")
    print(f"                 POST /horse/grade")
    print()
    print("  Pair with static server:")
    print("    python -m http.server 8080")
    print("    → localhost:8080/EDGE-Platform.html → Trainer Scout tab")
    print("=" * 58)
    app.run(host="0.0.0.0", port=port, debug=False)
