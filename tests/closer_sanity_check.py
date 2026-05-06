"""
Phase 7A — Two-horse end-to-end pipeline validation.

Re-validates the closer pipeline after applying P6-NEW-OBS-1's fix
(beaten_lengths_q1/q2/q3/str now in lengths-from-leader semantics).

Validates:
  - Renegade (Race 12 Derby, finished 2nd, 15-15-12-7-2 progression)
  - Golden Tempo (Race 12 Derby, won, 18-?-14-11-1 progression)

For each horse:
  - dominant_arc in {CLOSE, RALLY}
  - electric_effort_count == 1 (Q3 -> Finish ground gained should now be >= 6
    after the from-leader transformation)
  - late_gain >= 6
  - Comparative: Golden Tempo's late_gain >= Renegade's late_gain

Plus a Race-12-wide before/after table to visually sanity-check the
transformation across all 18 horses.

Scratch DB: /tmp/sports_betting_phase6_validation.db (carried forward from
Phase 6 — script wipes & recreates on each run). Production DB never touched.
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import horse_racing_pdf_parser_v2 as eq_parser  # noqa: E402

DEFAULT_PDF = PROJECT_ROOT / "horse_racing_data" / "CD050226USA.pdf"
PRODUCTION_DB = PROJECT_ROOT / "sports_betting.db"
SCRATCH_DB = Path("/tmp/sports_betting_phase6_validation.db")

# Schema mapping (Phase 7A — extended with 4 _raw cell-format columns)
SCHEMA_COLUMNS = (
    "horse_name", "track", "race_date", "race_number",
    "surface", "distance", "track_condition", "pace_scenario",
    "post_position", "start_position",
    "pos_q1", "beaten_lengths_q1",
    "pos_q2", "beaten_lengths_q2",
    "pos_q3", "beaten_lengths_q3",
    "pos_str", "beaten_lengths_str",
    "finish_position", "beaten_lengths_finish",
    "final_time_seconds", "final_odds",
    "medication_code", "equipment_code",
    "weight_carried", "jockey", "trainer",
    "start_descriptor", "winning_manner",
    "created_at", "field_size",
    # Phase 7A additions:
    "bl_q1_raw", "bl_q2_raw", "bl_q3_raw", "bl_str_raw",
    # Phase 7B.1 additions:
    "pos_one_mile", "beaten_lengths_one_mile", "bl_one_mile_raw",
)
NEW_RAW_COLUMNS = (
    "bl_q1_raw", "bl_q2_raw", "bl_q3_raw", "bl_str_raw",
    "bl_one_mile_raw",
)
NEW_INT_REAL_COLUMNS = (
    ("pos_one_mile", "INTEGER"),
    ("beaten_lengths_one_mile", "REAL"),
)


def build_calls_row(horse, race, track_name_normalized, race_date_iso):
    """horse_race_calls row from a parsed Equibase horse + race (Phase 7A schema)."""
    return {
        "horse_name": horse.get("horse_name"),
        "track": track_name_normalized,
        "race_date": race_date_iso,
        "race_number": race.get("race_number"),
        "surface": race.get("surface"),
        "distance": race.get("distance_text"),
        "track_condition": race.get("track_condition"),
        "pace_scenario": race.get("pace_scenario"),
        "post_position": horse.get("post_position"),
        "start_position": horse.get("start_position"),
        "pos_q1": horse.get("pos_q1"),
        "beaten_lengths_q1": horse.get("beaten_lengths_q1"),
        "pos_q2": horse.get("pos_q2"),
        "beaten_lengths_q2": horse.get("beaten_lengths_q2"),
        "pos_q3": horse.get("pos_q3"),
        "beaten_lengths_q3": horse.get("beaten_lengths_q3"),
        "pos_str": horse.get("pos_str"),
        "beaten_lengths_str": horse.get("beaten_lengths_str"),
        "finish_position": horse.get("finish_position"),
        "beaten_lengths_finish": horse.get("beaten_lengths_finish"),
        "final_time_seconds": horse.get("final_time_seconds"),
        "final_odds": horse.get("final_odds"),
        "medication_code": horse.get("medication_code"),
        "equipment_code": horse.get("equipment_code"),
        "weight_carried": horse.get("weight_carried"),
        "jockey": horse.get("jockey"),
        "trainer": horse.get("trainer"),
        "start_descriptor": horse.get("start_descriptor"),
        "winning_manner": horse.get("winning_manner"),
        "created_at": datetime.now().isoformat(),
        "field_size": race.get("field_size"),
        "bl_q1_raw": horse.get("bl_q1_raw"),
        "bl_q2_raw": horse.get("bl_q2_raw"),
        "bl_q3_raw": horse.get("bl_q3_raw"),
        "bl_str_raw": horse.get("bl_str_raw"),
        "pos_one_mile": horse.get("pos_one_mile"),
        "beaten_lengths_one_mile": horse.get("beaten_lengths_one_mile"),
        "bl_one_mile_raw": horse.get("bl_one_mile_raw"),
    }


def setup_scratch_db():
    """Copy production DB to scratch path. Add 4 _raw columns. Patch DB_PATH."""
    if not PRODUCTION_DB.exists():
        raise FileNotFoundError(f"Production DB not found at {PRODUCTION_DB}")
    if SCRATCH_DB.exists():
        SCRATCH_DB.unlink()
    shutil.copy(PRODUCTION_DB, SCRATCH_DB)
    print(f"[Phase 7A] Copied {PRODUCTION_DB} -> {SCRATCH_DB} ({SCRATCH_DB.stat().st_size:,} bytes)")

    # Add _raw columns to scratch DB (production schema migration is a separate task).
    conn = sqlite3.connect(str(SCRATCH_DB))
    try:
        cur = conn.cursor()
        existing = {row[1] for row in cur.execute("PRAGMA table_info(horse_race_calls)")}
        for col in NEW_RAW_COLUMNS:
            if col not in existing:
                cur.execute(f"ALTER TABLE horse_race_calls ADD COLUMN {col} REAL")
                print(f"[Phase 7A] ALTER TABLE horse_race_calls ADD COLUMN {col} REAL")
        for col, type_ in NEW_INT_REAL_COLUMNS:
            if col not in existing:
                cur.execute(f"ALTER TABLE horse_race_calls ADD COLUMN {col} {type_}")
                print(f"[Phase 7B.1] ALTER TABLE horse_race_calls ADD COLUMN {col} {type_}")
        conn.commit()
    finally:
        conn.close()

    import db_utils
    db_utils.DB_PATH = SCRATCH_DB
    print(f"[Phase 7A] db_utils.DB_PATH = {db_utils.DB_PATH}")


def insert_calls_row(row):
    """Direct SQL INSERT OR REPLACE into scratch DB's horse_race_calls."""
    placeholders = ",".join("?" * len(SCHEMA_COLUMNS))
    values = tuple(row.get(c) for c in SCHEMA_COLUMNS)
    conn = sqlite3.connect(str(SCRATCH_DB))
    try:
        cur = conn.cursor()
        cur.execute(
            f"INSERT OR REPLACE INTO horse_race_calls ({','.join(SCHEMA_COLUMNS)}) "
            f"VALUES ({placeholders})",
            values,
        )
        conn.commit()
    finally:
        conn.close()


def fmt_num(v, prec=2):
    if v is None:
        return "None"
    if isinstance(v, float):
        return f"{v:.{prec}f}"
    return str(v)


def print_race12_table(parsed):
    """Show all 18 Derby horses with raw cell-format vs from-leader values."""
    race12 = next((r for r in parsed["races"] if r["race_number"] == 12), None)
    if race12 is None:
        print("[Phase 7A] WARN: Race 12 not in parsed result")
        return
    print(f"\n[Phase 7A] Race 12 (Derby) before/after — beaten_lengths transformation")
    print(f"          (raw = cell-format gap-from-prior; from_leader = cumulative)")
    print()
    header = (
        f"{'Pos':>3}  {'Horse':<28}  "
        f"{'Q1: raw -> from_leader':<26}  "
        f"{'Q3: raw -> from_leader':<26}  "
        f"{'Str: raw -> from_leader':<27}  "
        f"{'Fin (from_winner)':>17}"
    )
    print(header)
    print("-" * len(header))
    horses_sorted = sorted(race12["horses"], key=lambda h: h.get("finish_position") or 999)
    for h in horses_sorted:
        fin = h.get("finish_position")
        name = (h.get("horse_name") or "?")[:28]
        q1 = f"{fmt_num(h.get('bl_q1_raw'))} -> {fmt_num(h.get('beaten_lengths_q1'))}"
        q3 = f"{fmt_num(h.get('bl_q3_raw'))} -> {fmt_num(h.get('beaten_lengths_q3'))}"
        st = f"{fmt_num(h.get('bl_str_raw'))} -> {fmt_num(h.get('beaten_lengths_str'))}"
        fn = fmt_num(h.get("beaten_lengths_finish"))
        print(f"{fin!s:>3}  {name:<28}  {q1:<26}  {q3:<26}  {st:<27}  {fn:>17}")


def sanity_check_race12_table(parsed):
    """Validate: leader at each call has from_leader=0, monotonic increase."""
    race12 = next((r for r in parsed["races"] if r["race_number"] == 12), None)
    if race12 is None:
        return ["Race 12 missing"]
    horses = race12["horses"]
    failures = []
    for pos_field, bl_field, label in (
        ("pos_q1",  "beaten_lengths_q1",  "Q1"),
        ("pos_q2",  "beaten_lengths_q2",  "Q2"),
        ("pos_q3",  "beaten_lengths_q3",  "Q3"),
        ("pos_str", "beaten_lengths_str", "Str"),
    ):
        sorted_by_pos = sorted(
            [h for h in horses if h.get(pos_field) is not None],
            key=lambda h: h[pos_field],
        )
        if not sorted_by_pos:
            continue
        # Leader from_leader should be 0
        leader = sorted_by_pos[0]
        if leader.get(bl_field) != 0.0:
            failures.append(
                f"{label}: leader {leader.get('horse_name')!r} bl={leader.get(bl_field)!r} (expected 0.0)"
            )
        # Monotonic non-decreasing
        prev_bl = None
        for h in sorted_by_pos:
            bl = h.get(bl_field)
            if bl is None:
                continue
            if bl < 0:
                failures.append(f"{label}: {h.get('horse_name')!r} negative bl={bl}")
            if prev_bl is not None and bl < prev_bl:
                failures.append(
                    f"{label}: monotonicity broken at {h.get('horse_name')!r} pos={h.get(pos_field)} "
                    f"bl={bl} (prev {prev_bl})"
                )
            prev_bl = bl
    return failures


def run_classifier_for(horse_name, hpl):
    """Update profile + fetch via get_horse_full_profile."""
    print(f"\n[Phase 7A] update_horse_profiles({horse_name!r})...")
    res = hpl.update_horse_profiles(horse_names=[horse_name])
    print(f"[Phase 7A]   result: {res}")
    profile = hpl.get_horse_full_profile(horse_name)
    return profile


def print_profile(name, profile):
    print(f"\n[Phase 7A] get_horse_full_profile({name!r}):")
    print(f"  profile:")
    for k, v in profile.get("profile", {}).items():
        print(f"    {k}: {v!r}")
    print(f"  recent_calls ({len(profile.get('recent_calls', []))} row):")
    for call in profile.get("recent_calls", []):
        print(f"    {{")
        for k, v in call.items():
            print(f"      {k}: {v!r}")
        print(f"    }}")


def print_comparison(renegade_h, gt_h, renegade_profile, gt_profile):
    """Side-by-side comparative cross-check."""
    import json as _json

    def dom_arc(prof):
        adj = (prof.get("profile") or {}).get("arc_distribution_json") or "{}"
        try:
            d = _json.loads(adj)
        except (TypeError, ValueError):
            return None
        if not d:
            return None
        return max(d.items(), key=lambda kv: kv[1])[0]

    def fld(prof, key):
        return (prof.get("profile") or {}).get(key)

    def lg(h):
        bl_q3 = h.get("beaten_lengths_q3")
        bl_fn = h.get("beaten_lengths_finish")
        if bl_q3 is None or bl_fn is None:
            return None
        return bl_q3 - bl_fn

    rows = [
        ("finish_position", renegade_h.get("finish_position"), gt_h.get("finish_position")),
        ("pos_q1",          renegade_h.get("pos_q1"),          gt_h.get("pos_q1")),
        ("pos_q3",          renegade_h.get("pos_q3"),          gt_h.get("pos_q3")),
        ("pos_str",         renegade_h.get("pos_str"),         gt_h.get("pos_str")),
        ("bl_q1 (from_leader)", renegade_h.get("beaten_lengths_q1"), gt_h.get("beaten_lengths_q1")),
        ("bl_q3 (from_leader)", renegade_h.get("beaten_lengths_q3"), gt_h.get("beaten_lengths_q3")),
        ("bl_str (from_leader)", renegade_h.get("beaten_lengths_str"), gt_h.get("beaten_lengths_str")),
        ("bl_finish (from_winner)", renegade_h.get("beaten_lengths_finish"), gt_h.get("beaten_lengths_finish")),
        ("late_gain (bl_q3 - bl_finish)", lg(renegade_h), lg(gt_h)),
        ("classifier dominant_arc", dom_arc(renegade_profile), dom_arc(gt_profile)),
        ("classifier electric_effort_count",
         fld(renegade_profile, "electric_effort_count"),
         fld(gt_profile, "electric_effort_count")),
        ("classifier closer_grade",
         fld(renegade_profile, "closer_grade"),
         fld(gt_profile, "closer_grade")),
    ]

    print(f"\n[Phase 7A] Renegade vs Golden Tempo — comparative late-move analysis")
    print()
    print(f"  {'Field':<35}  {'Renegade':>14}  {'Golden Tempo':>14}")
    print("  " + "-" * 35 + "  " + "-" * 14 + "  " + "-" * 14)
    for label, r, g in rows:
        print(f"  {label:<35}  {fmt_num(r):>14}  {fmt_num(g):>14}")


def main():
    pdf_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PDF

    print(f"[Phase 7A] Parsing {pdf_path}")
    parsed = eq_parser.parse_chart_pdf(pdf_path)
    if parsed is None:
        print("FATAL: parse_chart_pdf returned None")
        sys.exit(1)
    print(f"[Phase 7A] Track: {parsed['track']!r}  Date: {parsed['race_date']!r}  Races: {len(parsed['races'])}")

    # ---- Race 12 before/after table ----
    print_race12_table(parsed)
    table_failures = sanity_check_race12_table(parsed)
    if table_failures:
        print(f"\n[Phase 7A] Race 12 table sanity FAILURES:")
        for f in table_failures:
            print(f"    - {f}")
        sys.exit(1)
    print(f"\n[Phase 7A] Race 12 table sanity: PASS (leaders all 0.0, monotonic increase)")

    # ---- Pull Renegade and Golden Tempo from Race 12 ----
    race12 = next(r for r in parsed["races"] if r["race_number"] == 12)
    renegade = next((h for h in race12["horses"] if h.get("horse_name") == "Renegade"), None)
    gt = next((h for h in race12["horses"] if h.get("horse_name") == "Golden Tempo"), None)
    if renegade is None or gt is None:
        print(f"[Phase 7A] FATAL: missing Renegade or Golden Tempo in Race 12 horses")
        sys.exit(1)

    # ---- Setup scratch DB + insert both rows ----
    setup_scratch_db()
    for horse in (renegade, gt):
        row = build_calls_row(horse, race12, parsed["track"], parsed["race_date"])
        insert_calls_row(row)
        print(f"[Phase 7A] Inserted {horse['horse_name']!r} into horse_race_calls")

    import horse_profile_logic as hpl

    renegade_profile = run_classifier_for("Renegade", hpl)
    gt_profile = run_classifier_for("Golden Tempo", hpl)

    print_profile("Renegade", renegade_profile)
    print_profile("Golden Tempo", gt_profile)

    print_comparison(renegade, gt, renegade_profile, gt_profile)

    # ---- 8 pass criteria ----
    import json as _json
    def _arc(prof):
        adj = (prof.get("profile") or {}).get("arc_distribution_json") or "{}"
        try:
            d = _json.loads(adj)
        except Exception:
            return None
        return max(d.items(), key=lambda kv: kv[1])[0] if d else None
    def _ec(prof):
        return (prof.get("profile") or {}).get("electric_effort_count") or 0
    def _lg(h):
        return (h.get("beaten_lengths_q3") or 0.0) - (h.get("beaten_lengths_finish") or 0.0)

    r_arc = _arc(renegade_profile)
    g_arc = _arc(gt_profile)
    r_ec = _ec(renegade_profile)
    g_ec = _ec(gt_profile)
    r_lg = _lg(renegade)
    g_lg = _lg(gt)

    print(f"\n[Phase 7A] PASS CRITERIA")
    criteria = [
        ("1. Renegade late_gain >= 6", r_lg >= 6, f"actual {r_lg:.2f}"),
        ("2. Renegade electric_effort_count == 1", r_ec == 1, f"actual {r_ec}"),
        ("3. Renegade dominant_arc == CLOSE", r_arc == "CLOSE", f"actual {r_arc!r}"),
        ("4. Golden Tempo late_gain >= 6", g_lg >= 6, f"actual {g_lg:.2f}"),
        ("5. Golden Tempo electric_effort_count == 1", g_ec == 1, f"actual {g_ec}"),
        ("6. Golden Tempo dominant_arc in {CLOSE, RALLY}",
         g_arc in ("CLOSE", "RALLY"), f"actual {g_arc!r}"),
        ("7. Golden Tempo late_gain >= Renegade late_gain",
         g_lg >= r_lg, f"GT {g_lg:.2f} vs Ren {r_lg:.2f}"),
        ("8. Race 12 table sanity (leaders=0, monotonic)",
         len(table_failures) == 0, "see above" if table_failures else "all clean"),
    ]
    for label, ok, detail in criteria:
        print(f"  [{('PASS' if ok else 'FAIL'):>4}]  {label}  ({detail})")

    overall = all(ok for _, ok, _ in criteria)
    print(f"\n[Phase 7A] Overall: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
