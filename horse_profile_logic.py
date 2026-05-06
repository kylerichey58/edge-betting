"""
horse_profile_logic.py — EDGE Intelligence Platform
Running-arc profile system for horse_race_calls + horse_profile tables.

Two-layer architecture:
  - horse_race_calls   : raw per-race-per-horse rows. Append-only. Sacred.
  - horse_profile      : derived lifetime aggregates. Recomputable cache.

Public API:
  update_horse_profiles(horse_names=None) -> dict
      Recompute aggregates for given horses (or ALL horses if None).
  get_horse_full_profile(horse_name) -> dict | None
      Unified-query helper: returns {'profile': {...}, 'recent_calls': [...]}.

This module is the single source of truth for running-arc logic.
horse_racing_grader.grade_race() calls update_horse_profiles() after writing
horse_race_calls rows, completing the C1 trigger pattern.

NOTE (May 4, 2026): horse_racing_grader.py also contains a copy of these
constants and helpers — added inline before this module was extracted.
The duplication should be cleaned up by a follow-up refactor (grader imports
from this module). Tracked as observation OBS-2 in Prompt-2 bug list.
"""

import json
import math
from datetime import datetime
from db_utils import safe_write, safe_read


# ============================================================
# RUNNING ARC PROFILE THRESHOLDS — May 4, 2026
# Reasoned starting parameters. Watch 30 days of forward data
# before retuning. Do NOT tune from historical re-runs.
# ============================================================

# --- Closer-grade computation ---
CLOSER_RECENT_RACES_WINDOW    = 3      # how many recent races to evaluate
CLOSER_OFFPACE_Q1_THRESHOLD   = 4      # pos_q1 >= this means horse ran off the pace
CLOSER_LATE_MOVE_WEIGHT       = 0.7    # weight of q3-to-finish closing move
CLOSER_SUSTAINED_RUN_WEIGHT   = 0.3    # weight of q1-to-finish sustained run
CLOSER_NONCONVERSION_PENALTY  = 0.5    # multiplier when finish_position > field_size/2
CLOSER_STRONG_THRESHOLD       = 3.0    # signal >= this AND consistency check → STRONG
CLOSER_STRONG_CONSISTENCY_MIN = 2      # of last N races, this many must be off-pace
CLOSER_MILD_THRESHOLD         = 1.5    # signal between this and STRONG → MILD
CLOSER_MIN_GRADED_RACES       = 3      # below this → INSUFFICIENT_DATA

# --- Arc classification ---
ARC_LEAD_POSITION_MAX      = 2         # WIRE: pos_q1, pos_q3, finish all <= 2
ARC_NEAR_LEAD_POSITION_MAX = 3         # PRESS: all positions <= 3 (and not WIRE)
ARC_OFFPACE_POSITION_MIN   = 4         # RALLY/CLOSE: pos_q1 >= 4
# FADE: pos_q1 <= ARC_NEAR_LEAD_POSITION_MAX AND finish_position >= ceil(field_size/2)
# FLAT: catch-all
# Order: WIRE → PRESS → RALLY → CLOSE → FADE → FLAT (first match wins)

# --- Electric-effort flag ---
ELECTRIC_RECENT_RACES_WINDOW = 5       # wider window than closer (rare events)
ELECTRIC_LATE_MOVE_LENGTHS   = 6       # gained >= this many lengths q3 → finish
ELECTRIC_SUSTAINED_LENGTHS   = 8       # OR gained >= this many lengths q1 → finish
ELECTRIC_FINISH_POSITION_MAX = 2       # AND finished in top 2

# --- Running style observed ---
STYLE_RECENT_RACES_WINDOW = 3          # match closer window for consistency
STYLE_DOMINANT_THRESHOLD  = 2          # this many of N must share an arc → that style
                                       # else → 'MIXED'

# Arc names — single source of truth for arc_distribution_json keys
ARC_NAMES = ("WIRE", "PRESS", "RALLY", "CLOSE", "FADE", "FLAT")


# ---------------------------------------------------------------------------
# PURE HELPERS (testable in isolation)
# ---------------------------------------------------------------------------

def _classify_arc(pos_q1, pos_q3, finish_position, field_size) -> str:
    """Classify a single race into WIRE/PRESS/RALLY/CLOSE/FADE/FLAT.

    First-match-wins. Defensive: returns 'FLAT' if any required field is None.
    """
    if pos_q1 is None or pos_q3 is None or finish_position is None:
        return "FLAT"

    if (pos_q1 <= ARC_LEAD_POSITION_MAX
        and pos_q3 <= ARC_LEAD_POSITION_MAX
        and finish_position <= ARC_LEAD_POSITION_MAX):
        return "WIRE"

    if (pos_q1 <= ARC_NEAR_LEAD_POSITION_MAX
        and pos_q3 <= ARC_NEAR_LEAD_POSITION_MAX
        and finish_position <= ARC_NEAR_LEAD_POSITION_MAX):
        return "PRESS"

    if (pos_q1 >= ARC_OFFPACE_POSITION_MIN
        and pos_q3 <= ARC_NEAR_LEAD_POSITION_MAX
        and finish_position <= ARC_NEAR_LEAD_POSITION_MAX):
        return "RALLY"

    if (pos_q1 >= ARC_OFFPACE_POSITION_MIN
        and pos_q3 >= ARC_OFFPACE_POSITION_MIN
        and finish_position <= ARC_NEAR_LEAD_POSITION_MAX):
        return "CLOSE"

    if (pos_q1 <= ARC_NEAR_LEAD_POSITION_MAX
        and field_size is not None
        and finish_position >= math.ceil(field_size / 2)):
        return "FADE"

    return "FLAT"


def _compute_closer(rows: list) -> dict:
    """Compute closer signal, off-pace count, and grade.

    `rows` is the horse's race history ordered most-recent-first.
    The CLOSER_RECENT_RACES_WINDOW window applies to BOTH the signal
    iteration AND the offpace_count consistency check (strict-spec
    interpretation; see Prompt-2 bug list OBS-1).

    Returns: {'signal': float, 'offpace_count': int, 'grade': str}
    """
    total_starts = len(rows)
    window = rows[:CLOSER_RECENT_RACES_WINDOW]

    contributing = []
    offpace_count = 0
    for r in window:
        pq1   = r.get("pos_q1")
        bl_q1 = r.get("beaten_lengths_q1")
        bl_q3 = r.get("beaten_lengths_q3")
        bl_fn = r.get("beaten_lengths_finish")
        fin   = r.get("finish_position")
        fs    = r.get("field_size")

        if pq1 is None or pq1 < CLOSER_OFFPACE_Q1_THRESHOLD:
            continue
        offpace_count += 1

        if None in (bl_q1, bl_q3, bl_fn, fin):
            continue

        closing_move  = bl_q3 - bl_fn
        sustained_run = bl_q1 - bl_fn
        weighted = (closing_move  * CLOSER_LATE_MOVE_WEIGHT
                    + sustained_run * CLOSER_SUSTAINED_RUN_WEIGHT)

        if fs is not None and fin > (fs / 2):
            weighted *= CLOSER_NONCONVERSION_PENALTY

        contributing.append(weighted)

    signal = (sum(contributing) / len(contributing)) if contributing else 0.0

    if total_starts < CLOSER_MIN_GRADED_RACES:
        grade = "INSUFFICIENT_DATA"
    elif signal >= CLOSER_STRONG_THRESHOLD and offpace_count >= CLOSER_STRONG_CONSISTENCY_MIN:
        grade = "STRONG_CLOSER"
    elif signal >= CLOSER_MILD_THRESHOLD:
        grade = "MILD_CLOSER"
    else:
        grade = "NOT_A_CLOSER"

    return {"signal": signal, "offpace_count": offpace_count, "grade": grade}


def _compute_arc_distribution(rows: list) -> dict:
    """Distribution of arcs over last STYLE_RECENT_RACES_WINDOW races.

    Always emits all 6 keys with explicit zero counts.
    """
    dist = {name: 0 for name in ARC_NAMES}
    for r in rows[:STYLE_RECENT_RACES_WINDOW]:
        arc = _classify_arc(
            r.get("pos_q1"), r.get("pos_q3"),
            r.get("finish_position"), r.get("field_size"),
        )
        dist[arc] = dist.get(arc, 0) + 1
    return dist


def _compute_running_style(arc_dist: dict, total_starts: int) -> str:
    """If any arc has count >= STYLE_DOMINANT_THRESHOLD → that arc; else MIXED.

    Special case: total_starts < STYLE_RECENT_RACES_WINDOW → 'MIXED'.
    """
    if total_starts < STYLE_RECENT_RACES_WINDOW:
        return "MIXED"
    for arc, count in arc_dist.items():
        if count >= STYLE_DOMINANT_THRESHOLD:
            return arc
    return "MIXED"


def _compute_electric_count(rows: list) -> int:
    """Count qualifying electric efforts in last ELECTRIC_RECENT_RACES_WINDOW races."""
    count = 0
    for r in rows[:ELECTRIC_RECENT_RACES_WINDOW]:
        bl_q1 = r.get("beaten_lengths_q1")
        bl_q3 = r.get("beaten_lengths_q3")
        bl_fn = r.get("beaten_lengths_finish")
        fin   = r.get("finish_position")
        if None in (bl_q1, bl_q3, bl_fn, fin):
            continue
        late_gain      = bl_q3 - bl_fn
        sustained_gain = bl_q1 - bl_fn
        if (fin <= ELECTRIC_FINISH_POSITION_MAX
            and (late_gain >= ELECTRIC_LATE_MOVE_LENGTHS
                 or sustained_gain >= ELECTRIC_SUSTAINED_LENGTHS)):
            count += 1
    return count


def _avg_ground_gained(rows: list):
    """Mean of (beaten_lengths_q1 - beaten_lengths_finish). NULL-safe.

    Returns None if no valid samples.
    """
    gains = []
    for r in rows:
        bl_q1 = r.get("beaten_lengths_q1")
        bl_fn = r.get("beaten_lengths_finish")
        if bl_q1 is None or bl_fn is None:
            continue
        gains.append(bl_q1 - bl_fn)
    if not gains:
        return None
    return sum(gains) / len(gains)


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------

def update_horse_profiles(horse_names=None, db_path=None) -> dict:
    """Recompute horse_profile aggregates from horse_race_calls.

    Args:
        horse_names: list of names to recompute. If None, rebuild ALL profiles
                     from scratch (used for threshold retuning).
        db_path: ignored — included for API consistency with other grader fns.

    Returns:
        {'profiles_updated': int, 'horses_processed': list[str]}
    """
    # 1. Resolve target horse list
    if horse_names is None:
        with safe_read() as conn:
            cur = conn.execute(
                "SELECT DISTINCT horse_name FROM horse_race_calls "
                "WHERE horse_name IS NOT NULL AND horse_name <> ''"
            )
            horse_names = [r[0] for r in cur.fetchall()]
    else:
        # Dedupe, preserve order, drop empties
        seen = set()
        cleaned = []
        for h in horse_names:
            if not h or h in seen:
                continue
            seen.add(h)
            cleaned.append(h)
        horse_names = cleaned

    if not horse_names:
        return {"profiles_updated": 0, "horses_processed": []}

    # 2. Read existing analysis_counts (single batch read)
    placeholders = ",".join("?" * len(horse_names))
    existing_counts = {}
    with safe_read() as conn:
        cur = conn.execute(
            f"SELECT horse_name, analysis_count FROM horse_profile "
            f"WHERE horse_name IN ({placeholders})",
            horse_names,
        )
        for r in cur.fetchall():
            existing_counts[r[0]] = r[1] or 0

    # 3. Per-horse: read calls history, compute aggregates
    profile_rows = []
    for hname in horse_names:
        with safe_read() as conn:
            cur = conn.execute(
                """
                SELECT * FROM horse_race_calls
                WHERE horse_name = ?
                ORDER BY race_date DESC, race_number DESC
                """,
                (hname,),
            )
            rows = [dict(r) for r in cur.fetchall()]

        if not rows:
            continue   # nothing to recompute

        total_starts = len(rows)
        total_wins   = sum(1 for r in rows if r.get("finish_position") == 1)
        total_itm    = sum(1 for r in rows
                           if r.get("finish_position") is not None
                           and r["finish_position"] <= 3)

        # Surface buckets
        dirt   = [r for r in rows if r.get("surface") == "D"]
        turf   = [r for r in rows if r.get("surface") in ("T", "I")]
        synth  = [r for r in rows if r.get("surface") == "S"]

        def _wins(rs):
            return sum(1 for r in rs if r.get("finish_position") == 1)

        def _itm(rs):
            return sum(1 for r in rs
                       if r.get("finish_position") is not None
                       and r["finish_position"] <= 3)

        # Wet track / pace
        wet_conds = ("Sloppy", "Muddy", "Yielding", "Soft", "Heavy")
        wet   = [r for r in rows if r.get("track_condition") in wet_conds]
        hot   = [r for r in rows if r.get("pace_scenario") == "HOT"]
        slow  = [r for r in rows if r.get("pace_scenario") == "SLOW"]
        mixed = [r for r in rows if r.get("pace_scenario") == "MIXED"]

        most_recent      = rows[0]
        last_seen_track  = most_recent.get("track")
        last_seen_date   = most_recent.get("race_date")

        # Derived
        closer       = _compute_closer(rows)
        arc_dist     = _compute_arc_distribution(rows)
        running_style = _compute_running_style(arc_dist, total_starts)
        electric     = _compute_electric_count(rows)
        avg_lifetime = _avg_ground_gained(rows)
        avg_last_3   = _avg_ground_gained(rows[:CLOSER_RECENT_RACES_WINDOW])

        analysis_count = existing_counts.get(hname, 0) + 1
        last_updated   = datetime.now().isoformat()

        profile_rows.append({
            "horse_name":                 hname,
            "last_seen_track":            last_seen_track,
            "last_seen_date":             last_seen_date,
            "total_starts":               total_starts,
            "total_wins":                 total_wins,
            "total_itm":                  total_itm,
            "running_style_observed":     running_style,
            "avg_ground_gained_lifetime": avg_lifetime,
            "avg_ground_gained_last_3":   avg_last_3,
            "closer_grade":               closer["grade"],
            "dirt_starts":                len(dirt),
            "dirt_wins":                  _wins(dirt),
            "dirt_itm":                   _itm(dirt),
            "turf_starts":                len(turf),
            "turf_wins":                  _wins(turf),
            "turf_itm":                   _itm(turf),
            "synth_starts":               len(synth),
            "synth_wins":                 _wins(synth),
            "synth_itm":                  _itm(synth),
            "wet_track_starts":           len(wet),
            "wet_track_wins":             _wins(wet),
            "hot_pace_starts":            len(hot),
            "hot_pace_wins":              _wins(hot),
            "slow_pace_starts":           len(slow),
            "slow_pace_wins":             _wins(slow),
            "mixed_pace_starts":          len(mixed),
            "mixed_pace_wins":            _wins(mixed),
            "analysis_count":             analysis_count,
            "last_updated":               last_updated,
            "electric_effort_count":      electric,
            "arc_distribution_json":      json.dumps(arc_dist),
        })

    # 4. Single safe_write for all UPSERTs (atomic per call)
    if profile_rows:
        with safe_write() as conn:
            cur = conn.cursor()
            for p in profile_rows:
                cur.execute(
                    """
                    INSERT OR REPLACE INTO horse_profile (
                        horse_name, last_seen_track, last_seen_date,
                        total_starts, total_wins, total_itm,
                        running_style_observed,
                        avg_ground_gained_lifetime, avg_ground_gained_last_3,
                        closer_grade,
                        dirt_starts, dirt_wins, dirt_itm,
                        turf_starts, turf_wins, turf_itm,
                        synth_starts, synth_wins, synth_itm,
                        wet_track_starts, wet_track_wins,
                        hot_pace_starts, hot_pace_wins,
                        slow_pace_starts, slow_pace_wins,
                        mixed_pace_starts, mixed_pace_wins,
                        analysis_count, last_updated,
                        electric_effort_count, arc_distribution_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        p["horse_name"], p["last_seen_track"], p["last_seen_date"],
                        p["total_starts"], p["total_wins"], p["total_itm"],
                        p["running_style_observed"],
                        p["avg_ground_gained_lifetime"], p["avg_ground_gained_last_3"],
                        p["closer_grade"],
                        p["dirt_starts"], p["dirt_wins"], p["dirt_itm"],
                        p["turf_starts"], p["turf_wins"], p["turf_itm"],
                        p["synth_starts"], p["synth_wins"], p["synth_itm"],
                        p["wet_track_starts"], p["wet_track_wins"],
                        p["hot_pace_starts"], p["hot_pace_wins"],
                        p["slow_pace_starts"], p["slow_pace_wins"],
                        p["mixed_pace_starts"], p["mixed_pace_wins"],
                        p["analysis_count"], p["last_updated"],
                        p["electric_effort_count"], p["arc_distribution_json"],
                    ),
                )

    processed = [p["horse_name"] for p in profile_rows]
    return {"profiles_updated": len(profile_rows), "horses_processed": processed}


def get_horse_full_profile(horse_name: str, db_path=None) -> dict | None:
    """Unified-query helper: returns profile + last 5 race calls for one horse.

    Returns None if horse not found in horse_profile.
    """
    with safe_read() as conn:
        cur = conn.execute(
            "SELECT * FROM horse_profile WHERE horse_name = ?",
            (horse_name,),
        )
        prow = cur.fetchone()
        if prow is None:
            return None
        profile = dict(prow)

        cur = conn.execute(
            """
            SELECT * FROM horse_race_calls
            WHERE horse_name = ?
            ORDER BY race_date DESC, race_number DESC
            LIMIT 5
            """,
            (horse_name,),
        )
        recent_calls = [dict(r) for r in cur.fetchall()]

    return {"profile": profile, "recent_calls": recent_calls}
