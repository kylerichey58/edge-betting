"""
test_horse_profile_self.py — synthetic-data self-test for horse_profile_logic.

Inserts 5 fake horse_race_calls rows for 'TEST_HORSE_DELETE_ME', runs
update_horse_profiles(), reads the resulting horse_profile row, and asserts
each computed field matches expected. Cleans up via try/finally.

Run from Sportsbetting/ directory:
    python tests/test_horse_profile_self.py
"""

import json
import sys
from pathlib import Path

# Make project root importable regardless of cwd
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db_utils import safe_write, safe_read
import horse_profile_logic as hpl


TEST_HORSE = "TEST_HORSE_DELETE_ME"
TEST_TRACK = "TST"

# Synthetic 5-race history. Order: race_date DESC, race_number DESC = race 1 → 5.
# Race 1 is most recent.
TEST_RACES = [
    # race_date,    race_num, pos_q1, pos_q3, fin, BLq1, BLq3, BLfin, fs
    ("2026-04-30",  1,        8,      6,      1,   12.0, 8.0,  0.0,   10),  # CLOSE, electric (sustained=12 ≥ 8 + finish ≤ 2)
    ("2026-04-23",  1,        7,      4,      2,   10.0, 4.0,  1.0,   10),  # CLOSE, electric (sustained=9 ≥ 8 + finish ≤ 2)
    ("2026-04-15",  1,        2,      2,      1,    0.0, 0.0,  0.0,    8),  # WIRE, not electric
    ("2026-04-08",  1,        6,      5,      3,    8.0, 4.0,  2.0,    9),  # CLOSE, late=2/sus=6 not electric
    ("2026-04-01",  1,        5,      4,      6,    6.0, 3.0,  8.0,   10),  # FLAT (finish > 3, pos_q1 > 3 so not FADE)
]


def cleanup() -> None:
    with safe_write() as conn:
        conn.execute("DELETE FROM horse_race_calls WHERE horse_name = ?", (TEST_HORSE,))
        conn.execute("DELETE FROM horse_profile    WHERE horse_name = ?", (TEST_HORSE,))


def insert_test_rows() -> None:
    with safe_write() as conn:
        for rd, rn, pq1, pq3, fin, bl1, bl3, blf, fs in TEST_RACES:
            conn.execute(
                """
                INSERT OR REPLACE INTO horse_race_calls (
                    horse_name, track, race_date, race_number,
                    surface, pos_q1, beaten_lengths_q1,
                    pos_q3, beaten_lengths_q3,
                    finish_position, beaten_lengths_finish,
                    field_size, created_at
                ) VALUES (?, ?, ?, ?, 'D', ?, ?, ?, ?, ?, ?, ?, '2026-05-04T00:00:00')
                """,
                (TEST_HORSE, TEST_TRACK, rd, rn, pq1, bl1, pq3, bl3, fin, blf, fs),
            )


def assert_eq(label, actual, expected, *, tolerance=None):
    """Compare and print PASS/FAIL. Tolerance triggers float compare."""
    if tolerance is not None:
        passed = abs((actual or 0) - (expected or 0)) < tolerance
    else:
        passed = actual == expected
    icon = "PASS" if passed else "FAIL"
    print(f"  [{icon}] {label}")
    if not passed:
        print(f"          expected: {expected!r}")
        print(f"          actual:   {actual!r}")
    return passed


def main() -> int:
    print("=" * 65)
    print("horse_profile_logic self-test — synthetic horse data")
    print("=" * 65)

    cleanup()  # safety: clear any leftover state from prior runs

    failures = []
    try:
        # ── Step 1: insert synthetic rows ──────────────────────────────────
        insert_test_rows()
        with safe_read() as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM horse_race_calls WHERE horse_name = ?",
                (TEST_HORSE,),
            ).fetchone()[0]
        print(f"\n  inserted {n} synthetic rows for {TEST_HORSE}")

        # ── Step 2: pure-helper smoke checks (independent of DB) ──────────
        print("\n--- pure helper checks ---")
        # Build dict-shaped rows for pure helpers (most-recent-first ordering)
        rows = [
            {"pos_q1": pq1, "pos_q3": pq3, "finish_position": fin,
             "beaten_lengths_q1": bl1, "beaten_lengths_q3": bl3,
             "beaten_lengths_finish": blf, "field_size": fs}
            for (_, _, pq1, pq3, fin, bl1, bl3, blf, fs) in TEST_RACES
        ]
        # Per-race arc spot-checks
        if not assert_eq("race 1 arc",
                         hpl._classify_arc(8, 6, 1, 10), "CLOSE"):
            failures.append("race 1 arc")
        if not assert_eq("race 3 arc",
                         hpl._classify_arc(2, 2, 1, 8), "WIRE"):
            failures.append("race 3 arc")
        if not assert_eq("race 5 arc",
                         hpl._classify_arc(5, 4, 6, 10), "FLAT"):
            failures.append("race 5 arc")

        closer = hpl._compute_closer(rows)
        if not assert_eq("closer.signal ≈ 7.0",
                         closer["signal"], 7.0, tolerance=0.01):
            failures.append("closer.signal")
        if not assert_eq("closer.offpace_count (window=3)",
                         closer["offpace_count"], 2):
            failures.append("closer.offpace_count")
        if not assert_eq("closer.grade",
                         closer["grade"], "STRONG_CLOSER"):
            failures.append("closer.grade")

        electric = hpl._compute_electric_count(rows)
        if not assert_eq("electric_effort_count (last 5)",
                         electric, 2):
            failures.append("electric_effort_count")

        # ── Step 3: run update_horse_profiles + read back ──────────────────
        print("\n--- update_horse_profiles + horse_profile readback ---")
        result = hpl.update_horse_profiles([TEST_HORSE])
        if not assert_eq("update_horse_profiles.profiles_updated",
                         result["profiles_updated"], 1):
            failures.append("profiles_updated count")
        if not assert_eq("update_horse_profiles.horses_processed",
                         result["horses_processed"], [TEST_HORSE]):
            failures.append("horses_processed list")

        with safe_read() as conn:
            row = conn.execute(
                "SELECT * FROM horse_profile WHERE horse_name = ?",
                (TEST_HORSE,),
            ).fetchone()
        if row is None:
            print("  [FAIL] horse_profile row missing after update")
            failures.append("profile row exists")
            return len(failures)

        p = dict(row)
        if not assert_eq("total_starts",          p["total_starts"], 5):
            failures.append("total_starts")
        if not assert_eq("total_wins",            p["total_wins"], 2):
            failures.append("total_wins")
        if not assert_eq("total_itm",             p["total_itm"], 4):
            failures.append("total_itm")
        if not assert_eq("dirt_starts",           p["dirt_starts"], 5):
            failures.append("dirt_starts")
        if not assert_eq("dirt_wins",             p["dirt_wins"], 2):
            failures.append("dirt_wins")
        if not assert_eq("dirt_itm",              p["dirt_itm"], 4):
            failures.append("dirt_itm")
        if not assert_eq("turf_starts",           p["turf_starts"], 0):
            failures.append("turf_starts")
        if not assert_eq("synth_starts",          p["synth_starts"], 0):
            failures.append("synth_starts")
        if not assert_eq("running_style_observed",
                         p["running_style_observed"], "CLOSE"):
            failures.append("running_style_observed")
        if not assert_eq("closer_grade",          p["closer_grade"], "STRONG_CLOSER"):
            failures.append("closer_grade")
        if not assert_eq("electric_effort_count", p["electric_effort_count"], 2):
            failures.append("electric_effort_count (col)")
        if not assert_eq("avg_ground_gained_lifetime ≈ 5.0",
                         p["avg_ground_gained_lifetime"], 5.0, tolerance=0.001):
            failures.append("avg_ground_gained_lifetime")
        if not assert_eq("avg_ground_gained_last_3 ≈ 7.0",
                         p["avg_ground_gained_last_3"], 7.0, tolerance=0.001):
            failures.append("avg_ground_gained_last_3")
        if not assert_eq("last_seen_track",       p["last_seen_track"], TEST_TRACK):
            failures.append("last_seen_track")
        if not assert_eq("last_seen_date",        p["last_seen_date"], "2026-04-30"):
            failures.append("last_seen_date")
        if not assert_eq("analysis_count",        p["analysis_count"], 1):
            failures.append("analysis_count")

        arc_dist_actual = json.loads(p["arc_distribution_json"])
        arc_dist_expected = {"WIRE": 1, "PRESS": 0, "RALLY": 0,
                             "CLOSE": 2, "FADE": 0, "FLAT": 0}
        if not assert_eq("arc_distribution_json (last 3)",
                         arc_dist_actual, arc_dist_expected):
            failures.append("arc_distribution_json")

        # ── Step 4: get_horse_full_profile ─────────────────────────────────
        print("\n--- get_horse_full_profile ---")
        full = hpl.get_horse_full_profile(TEST_HORSE)
        if full is None:
            print("  [FAIL] get_horse_full_profile returned None")
            failures.append("get_horse_full_profile None")
        else:
            if not assert_eq("get_horse_full_profile keys",
                             sorted(full.keys()), ["profile", "recent_calls"]):
                failures.append("full_profile keys")
            if not assert_eq("recent_calls length",
                             len(full["recent_calls"]), 5):
                failures.append("recent_calls length")
            if not assert_eq("recent_calls[0].race_date (most recent)",
                             full["recent_calls"][0]["race_date"], "2026-04-30"):
                failures.append("recent_calls ordering")

        # ── Step 5: idempotency check — running again increments analysis_count
        print("\n--- idempotency ---")
        hpl.update_horse_profiles([TEST_HORSE])
        with safe_read() as conn:
            ac = conn.execute(
                "SELECT analysis_count FROM horse_profile WHERE horse_name = ?",
                (TEST_HORSE,),
            ).fetchone()[0]
        if not assert_eq("analysis_count after second call", ac, 2):
            failures.append("analysis_count idempotency")

    finally:
        cleanup()
        print("\n  cleanup: removed test rows from both tables")
        with safe_read() as conn:
            n_calls = conn.execute(
                "SELECT COUNT(*) FROM horse_race_calls WHERE horse_name = ?",
                (TEST_HORSE,),
            ).fetchone()[0]
            n_prof = conn.execute(
                "SELECT COUNT(*) FROM horse_profile WHERE horse_name = ?",
                (TEST_HORSE,),
            ).fetchone()[0]
        print(f"  post-cleanup: horse_race_calls={n_calls}, horse_profile={n_prof}")

    print("=" * 65)
    if failures:
        print(f"  RESULT: {len(failures)} FAILURE(S): {failures}")
        return 1
    print("  RESULT: ALL ASSERTIONS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
