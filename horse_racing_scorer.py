"""
horse_racing_scorer.py — EDGE Intelligence Platform
11-metric scoring engine for thoroughbred horse racing.

Score range per metric: 0–3
Maximum composite:       33  (11 × 3)
Gem threshold:           18+
AUTO NO-PLAY:            M09 = 0 — veto, no exceptions

M10 and M11 are multiplier metrics — they amplify signal but cannot
override the M09 veto.

ARM2026 Integration (added April 11, 2026):
  - BEYER_PARS: par speed figures by (track, surface, race_type) from p.181
    Used in M01 to calibrate trajectory against class par.
  - STAKES_RATINGS: NARC + Beyer Index ratings from pp.90, 223 (reference lookup)
  - GRADE_CHANGES_2026: grade changes for 2026 from p.241 (reference lookup)
  - TRACK_CLOCKINGS: fastest times per distance/track from pp.1203-1215 (reference)
  - M07: MEET_{track} fallback using ARM-seeded trainer win% data
  - M08: jockey_stats DB fallback when DRF meet starts < 5

Usage:
    from horse_racing_scorer import score_horse, score_race
    result  = score_horse(horse_dict, field_horses, market_odds=4.5)
    results = score_race(horses_list)
"""

import csv
import sqlite3
import statistics
from pathlib import Path

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

SCRIPT_DIR    = Path(__file__).parent
DB_PATH       = SCRIPT_DIR / "sports_betting.db"
GEM_THRESHOLD = 18   # composite >= 18 → gem

# Class rank for M03  (higher number = higher class)
CLASS_RANK = {
    "MCL": 1,   # Maiden Claiming
    "MSW": 2,   # Maiden Special Weight
    "CLM": 3,   # Claiming
    "OC":  4,   # Optional Claiming
    "ALW": 5,   # Allowance
    "N":   5,   # Non-Graded Stakes (same tier as ALW)
    "STK": 6,   # Stakes
    "G3":  7,   # Grade 3
    "G2":  8,   # Grade 2
    "G1":  9,   # Grade 1
}


# ---------------------------------------------------------------------------
# ARM2026 DATA TABLES  (loaded at import, graceful fallback if files missing)
# ---------------------------------------------------------------------------

def _arm_class_to_edge(class_info: str) -> str:
    """Map ARM Beyer Par class_info string to EDGE race_type code."""
    ci = class_info.upper()
    if ci.startswith("MCL"):            return "MCL"
    if ci.startswith("MSW"):            return "MSW"
    if ci.startswith("GSTK-G1"):        return "G1"
    if ci.startswith("GSTK-G2"):        return "G2"
    if ci.startswith("GSTK-G3"):        return "G3"
    if ci.startswith("STK"):            return "STK"
    if ci.startswith("AN") or ci.startswith("ACN"):  return "ALW"
    # CLM, CN2, CN3, CN4, Cond CLM, SA (Santa Anita claiming notation), etc.
    return "CLM"


def _load_beyer_pars() -> dict:
    """
    Returns dict: {(track_code, surface, race_type): median_par}
    Built from arm_beyer_pars.csv.  Falls back to {} if file missing.
    """
    path = SCRIPT_DIR / "arm_beyer_pars.csv"
    if not path.exists():
        return {}
    raw: dict = {}   # {key: [par_values]}
    try:
        with open(path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                track  = row["track_code"].strip().upper()
                surf   = row["surface"].strip().upper()
                rtype  = _arm_class_to_edge(row["class_info"])
                try:
                    par = float(row["par"])
                except (ValueError, KeyError):
                    continue
                key = (track, surf, rtype)
                raw.setdefault(key, []).append(par)
        return {k: statistics.median(v) for k, v in raw.items()}
    except Exception:
        return {}


def _load_stakes_ratings() -> dict:
    """
    Returns dict: {race_name_upper: {grade, narc_rating, beyer_2025, beyer_10yr_avg}}
    Built from arm_stakes_ratings.csv.  Reference use only — no auto-scoring.
    """
    path = SCRIPT_DIR / "arm_stakes_ratings.csv"
    if not path.exists():
        return {}
    result = {}
    try:
        with open(path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                name = row.get("race_name", "").strip().upper()
                if not name:
                    continue
                result[name] = {
                    "grade":        row.get("grade", ""),
                    "narc_rating":  row.get("narc_rating", ""),
                    "beyer_2025":   row.get("beyer_2025", ""),
                    "beyer_10yr":   row.get("beyer_10yr_avg", ""),
                    "track_code":   row.get("track_code", ""),
                }
        return result
    except Exception:
        return {}


def _load_grade_changes() -> dict:
    """
    Returns dict: {race_name_upper: {old_grade, new_grade, direction, track_name}}
    direction = 'UPGRADED' (promoted) or 'DOWNGRADED' (demoted)
    Built from arm_grade_changes_2026.csv.  Reference use only — no auto-scoring.
    CSV columns: race_name, age_sex, track_name, grade_2025, grade_2026, direction
    """
    path = SCRIPT_DIR / "arm_grade_changes_2026.csv"
    if not path.exists():
        return {}
    result = {}
    try:
        with open(path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                name  = row.get("race_name", "").strip().upper()
                old_g = row.get("grade_2025", "").strip()
                new_g = row.get("grade_2026", "").strip()
                if not name or not old_g or not new_g:
                    continue
                # Filter out non-numeric grade entries (e.g. "Not run")
                if not old_g.isdigit() or not new_g.isdigit():
                    continue
                direction = row.get("direction", "").strip().upper()
                result[name] = {
                    "old_grade":  f"G{old_g}",
                    "new_grade":  f"G{new_g}",
                    "direction":  direction,
                    "track_name": row.get("track_name", ""),
                    "age_sex":    row.get("age_sex", ""),
                }
        return result
    except Exception:
        return {}


def _load_track_clockings() -> dict:
    """
    Returns dict: {(track_code, surface, distance_f): win_time_secs}
    Built from arm_track_clockings.csv.  Reference use only.
    """
    path = SCRIPT_DIR / "arm_track_clockings.csv"
    if not path.exists():
        return {}
    result = {}
    try:
        with open(path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                track = row.get("track_code", "").strip().upper()
                surf  = row.get("surface", "").strip().upper()
                dist  = row.get("distance_f", "").strip()
                secs  = row.get("win_time_secs", "").strip()
                if not track or not surf or not dist or not secs:
                    continue
                try:
                    result[(track, surf, dist)] = float(secs)
                except ValueError:
                    continue
        return result
    except Exception:
        return {}


# Load once at import — ~milliseconds, graceful on missing files
BEYER_PARS       = _load_beyer_pars()
STAKES_RATINGS   = _load_stakes_ratings()
GRADE_CHANGES_2026 = _load_grade_changes()
TRACK_CLOCKINGS  = _load_track_clockings()


# ---------------------------------------------------------------------------
# UTILITY FUNCTIONS
# ---------------------------------------------------------------------------

def _figs(horse):
    """Return non-None speed figures from speed_figures_last3 (most recent = [0])."""
    return [f for f in horse.get("speed_figures_last3") or [] if f is not None]


def _best_fig(horse):
    """Return the highest speed figure on record, or None."""
    vals = _figs(horse)
    return max(vals) if vals else None


def _field_avg_best(field_horses):
    """Average of each horse's best speed figure across the full field."""
    bests = [_best_fig(h) for h in field_horses]
    valid = [b for b in bests if b is not None]
    return sum(valid) / len(valid) if valid else None


def _safe_int(val, default=0):
    try:
        return int(val) if val is not None else default
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# M01  Speed Figure Trajectory
# ---------------------------------------------------------------------------

def _m01(horse):
    """
    Base trajectory score (0–3), then optionally calibrated against
    Beyer Par for today's class/track/surface (ARM2026 p.181).

    Trajectory:
      3 = all 3 figures improving (most recent > middle > oldest)
      2 = flat or one improvement
      1 = declining; also used when only 1 figure available
      0 = no figures at all (all None)
      First-timer (empty list) → 1 neutral per EDGE rules

    Par calibration (applied after trajectory, clamped to [0, 3]):
      best_fig >= par + 3  → score + 1  (running above par for this class)
      best_fig <= par - 5  → score - 1  (running below par for this class)
      Otherwise            → no adjustment
    """
    raw = horse.get("speed_figures_last3") or []
    figs = [f for f in raw if f is not None]

    if not raw:
        return 1                    # first timer — neutral
    if not figs:
        return 0                    # figures listed but all blank

    if len(figs) == 1:
        score = 1                   # single figure, can't assess trend
    elif len(figs) == 2:
        if figs[0] > figs[1]:   score = 2   # improving
        elif figs[0] == figs[1]: score = 2  # flat
        else:                    score = 1  # declining
    else:
        # len >= 3
        if figs[0] > figs[1] > figs[2]:
            score = 3                           # all improving
        elif figs[0] > figs[1] or figs[1] > figs[2]:
            score = 2                           # one step up
        elif figs[0] == figs[1] == figs[2]:
            score = 2                           # perfectly flat
        else:
            score = 1                           # declining

    # ── ARM2026 Beyer Par calibration ────────────────────────────────────
    track     = (horse.get("track") or "").upper()
    surface   = (horse.get("surface") or "").upper()
    race_type = (horse.get("race_type") or "").upper()
    best_fig  = max(figs) if figs else None

    if BEYER_PARS and track and surface and race_type and best_fig is not None:
        par = BEYER_PARS.get((track, surface, race_type))
        if par is not None:
            if best_fig >= par + 3:
                score = min(3, score + 1)   # running above par — bonus
            elif best_fig <= par - 5:
                score = max(0, score - 1)   # running below par — penalty

    return score


# ---------------------------------------------------------------------------
# M02  Class-Adjusted Figure
# ---------------------------------------------------------------------------

def _m02(horse, field_horses):
    """
    3 = horse's best figure is 5+ pts above field average
    2 = within ±5 pts of field average
    1 = 5–10 pts below field average
    0 = 10+ pts below field average
    """
    field_avg  = _field_avg_best(field_horses)
    horse_best = _best_fig(horse)

    if field_avg is None or horse_best is None:
        return 1    # no field data to compare — neutral

    gap = horse_best - field_avg
    if gap >  5:  return 3
    if gap >= -5:  return 2
    if gap >= -10: return 1
    return 0


# ---------------------------------------------------------------------------
# M03  Class Direction + Intent
# ---------------------------------------------------------------------------

def _m03(horse):
    """
    3 = drop in class (CLM→lower-CLM, ALW→CLM, STK→ALW, etc.)
    2 = same class level
    1 = step up (not massive)
    0 = massive step up — MCL or CLM into ALW, STK, or graded

    NOTE: CLM-vs-CLM claiming price comparison requires claiming_prices_last3,
    which is a future parser extension. For now, same CLM tier = 2.
    """
    today_type  = (horse.get("race_type") or "").upper()
    past_types  = horse.get("race_types_last3") or []
    last_type   = (past_types[0] or "").upper() if past_types else ""

    if not last_type or not today_type:
        return 2    # no history → assume same level

    today_rank = CLASS_RANK.get(today_type, 3)
    last_rank  = CLASS_RANK.get(last_type, 3)

    # Massive step up: MCL/CLM → ALW, STK, or graded
    massive_up_origin = {"MCL", "CLM"}
    massive_up_dest   = {"ALW", "N", "STK", "G3", "G2", "G1"}
    if last_type in massive_up_origin and today_type in massive_up_dest:
        return 0

    if today_rank < last_rank:
        return 3   # dropping in class
    if today_rank > last_rank:
        return 1   # stepping up (not massive)
    return 2       # same class tier


# ---------------------------------------------------------------------------
# M04  Surface & Distance Fit
# ---------------------------------------------------------------------------

def _m04(horse):
    """
    3 = won (finished 1st) on today's surface in last 3 races
    2 = ran on today's surface but no win
    1 = surface switch with no prior record on today's surface
    0 = surface AND distance switch simultaneously
        (requires distances_last3 — not yet in horse dict; defaults to 1)

    NOTE: Score 0 will activate once horse_racing_parser is extended to
    include distances_last3. Until then, pure surface switch = 1.
    """
    today_surf = (horse.get("surface") or "").upper()
    past_surfs = [(s or "").upper() for s in (horse.get("surfaces_last3") or [])]
    past_fins  = [(f if f is not None else 99) for f in (horse.get("finish_positions_last3") or [])]

    if not past_surfs:
        return 1    # first timer, no history

    won_on  = any(
        past_surfs[i] == today_surf and i < len(past_fins) and past_fins[i] == 1
        for i in range(len(past_surfs))
    )
    ran_on  = any(s == today_surf for s in past_surfs)

    if won_on: return 3
    if ran_on: return 2
    return 1   # surface switch — see NOTE above for score-0 path


# ---------------------------------------------------------------------------
# M05  Pace Scenario  (manual input, pass-through)
# ---------------------------------------------------------------------------

def _m05(override):
    """Clamp the manual pace override to [0, 3]."""
    return max(0, min(3, _safe_int(override, 1)))


# ---------------------------------------------------------------------------
# M06  Form Cycle Position
# ---------------------------------------------------------------------------

def _m06(horse):
    """
    Returns (score: int, _raw_bounce: bool).

    days since last race → score:
        None / 0       → 1  (first timer)
        1 – 30 days    → trend-based:
                         improving (fig[0] > fig[1])          → 3
                         stable    (|fig[0]-fig[1]| ≤ 5)      → 2
                         declining                             → 1
                         bounce risk (fig[0] > fig[1] + 10)   → 0
        31 – 89 days   → 1
        90 – 179 days  → 3  (sweet spot: second race back)
        180 + days     → 0

    is_bounce_risk (per spec) = True whenever score == 0.
    """
    days = horse.get("days_since_last_race")
    figs = _figs(horse)

    if days is None:
        return 1, False     # first timer

    days = _safe_int(days, 0)

    if days == 0:
        return 1, False     # treat as first timer

    if 1 <= days <= 30:
        if len(figs) < 2:
            return 2, False                         # insufficient data → stable
        recent, prev = figs[0], figs[1]
        if recent > prev + 10:
            return 0, True                          # bounce risk — big peak last out
        if recent > prev:
            return 3, False                         # improving
        if abs(recent - prev) <= 5:
            return 2, False                         # stable
        return 1, False                             # declining

    if 31 <= days <= 89:
        return 1, False

    if 90 <= days <= 179:
        return 3, False                             # sweet spot

    return 0, False                                 # 180+ days — first race off long layoff


# ---------------------------------------------------------------------------
# M07  Situational Trainer ROI  (queries sports_betting.db)
# ---------------------------------------------------------------------------

def _m07_score_from_row(starts, wins, roi):
    """Shared scoring logic for both primary and MEET fallback M07 lookup."""
    if starts < 10:
        return 2 if (roi or 0) > 0 else 1   # small sample — ROI-direction score
    win_rate = wins / starts if starts > 0 else 0
    if win_rate >= 0.20: return 3
    if win_rate >= 0.15: return 2
    if win_rate >= 0.10: return 1
    return 0


def _m07(horse, db_path=None):
    """
    Situation key: '{TrainerLastName}_{racetype}_{surface}'
    Matches trainer_situational_stats table (live race-graded rows).

    ARM2026 MEET fallback (April 11, 2026):
    When primary situation lookup returns no record, checks ARM-seeded
    MEET_{track} rows using trainer last name (parts[0] of DRF format,
    e.g. 'COX BRAD' → 'COX').  This activates M07 for known trainers
    at target tracks from day one of live operation.

    3 = win rate ≥ 20% with 10+ starts
    2 = win rate 15–20% OR < 10 starts with positive ROI
    1 = win rate 10–15%
    0 = win rate < 10%
    Default → 1 (neutral) if no DB record or DB unavailable — never blocks a bet on data error
    """
    if db_path is None:
        db_path = DB_PATH

    trainer_full = (horse.get("trainer") or "").strip()
    race_type    = (horse.get("race_type") or "").upper()
    surface      = (horse.get("surface") or "").upper()
    track        = (horse.get("track") or "").upper()

    parts        = trainer_full.split()
    trainer_last = parts[-1] if parts else ""
    if not trainer_last:
        return 1

    situation = f"{trainer_last}_{race_type}_{surface}"

    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        cur  = conn.cursor()

        # ── Primary lookup: live race-graded situational stats ────────────
        cur.execute(
            "SELECT starts, wins, roi "
            "FROM trainer_situational_stats "
            "WHERE trainer_name = ? AND situation = ?",
            (trainer_full, situation),
        )
        row = cur.fetchone()

        if row is not None:
            conn.close()
            return _m07_score_from_row(row[0], row[1], row[2])

        # ── MEET fallback: ARM2026-seeded meet win% by track ──────────────
        # ARM rows stored as trainer_name = last-name uppercase (e.g. 'COX')
        # DRF trainer_full = 'COX BRAD' → parts[0] = 'COX' (last name)
        if track:
            trainer_last_drf = parts[0].upper() if parts else ""
            meet_situation   = f"MEET_{track}"
            if trainer_last_drf:
                cur.execute(
                    "SELECT starts, wins, roi "
                    "FROM trainer_situational_stats "
                    "WHERE trainer_name = ? AND situation = ?",
                    (trainer_last_drf, meet_situation),
                )
                meet_row = cur.fetchone()
                if meet_row is not None:
                    conn.close()
                    return _m07_score_from_row(meet_row[0], meet_row[1], meet_row[2])

        conn.close()
        return 1    # no record — neutral per EDGE rules

    except Exception:
        return 1    # DB error → neutral, never block on data failure


# ---------------------------------------------------------------------------
# M08  Jockey Switch Signal
# ---------------------------------------------------------------------------

def _m08(horse, db_path=None):
    """
    Scores current jockey's meet win% as a proxy for upgrade/downgrade signal.
    Full switch detection (vs previous jockey) requires jockey_pp_names in the
    horse dict — a future parser extension.

    Primary source: DRF fields jockey_meet_starts / jockey_meet_wins.
    ARM2026 fallback (April 11, 2026): when DRF meet starts < 5,
    queries jockey_stats table using jockey last name + track code.
    Jockey last name = parts[0] of DRF format ('FRANCO MANUEL' → 'FRANCO').

    Current win% ≥ 20%   → 3 (elite jockey / upgrade signal)
    Current win% 15–19%  → 2 (quality jockey / same-jockey retained quality)
    Current win% 10–14%  → 1 (average)
    Current win% < 10%   → 0 (downgrade / weak jockey)
    Fewer than 5 starts  → 1 (insufficient sample — tries ARM fallback first)
    """
    if db_path is None:
        db_path = DB_PATH

    starts = _safe_int(horse.get("jockey_meet_starts"), 0)
    wins   = _safe_int(horse.get("jockey_meet_wins"),   0)

    # ── Use DRF live data if sample is adequate ───────────────────────────
    if starts >= 5:
        pct = wins / starts
        if pct >= 0.20: return 3
        if pct >= 0.15: return 2
        if pct >= 0.10: return 1
        return 0

    # ── ARM2026 jockey_stats fallback ─────────────────────────────────────
    # DRF jockey format: 'FRANCO MANUEL' (LAST FIRST [INIT])
    # ARM stored as last name uppercase: 'FRANCO'
    jockey_full = (horse.get("jockey") or "").strip()
    track       = (horse.get("track") or "").upper()

    if jockey_full and track:
        jockey_parts     = jockey_full.split()
        jockey_last_name = jockey_parts[0].upper() if jockey_parts else ""
        if jockey_last_name:
            try:
                conn = sqlite3.connect(str(db_path), timeout=5)
                cur  = conn.cursor()
                cur.execute(
                    "SELECT wins, win_pct, starts FROM jockey_stats "
                    "WHERE jockey_name = ? AND track_code = ?",
                    (jockey_last_name, track),
                )
                row = cur.fetchone()
                conn.close()
                if row is not None:
                    arm_wins, arm_pct, arm_starts = row
                    if arm_starts and arm_starts >= 5:
                        if arm_pct >= 0.20: return 3
                        if arm_pct >= 0.15: return 2
                        if arm_pct >= 0.10: return 1
                        return 0
            except Exception:
                pass    # DB error → fall through to neutral

    return 1    # insufficient sample — neutral


# ---------------------------------------------------------------------------
# M09  Odds Value Gap
# ---------------------------------------------------------------------------

def _quick_partial(horse, field_horses):
    """
    Fast M01–M08 sum for field normalization in M09.
    M07 defaults to 1 (no DB query in this fast path).
    """
    m06_score, _ = _m06(horse)
    return (
        _m01(horse)
        + _m02(horse, field_horses)
        + _m03(horse)
        + _m04(horse)
        + 1                   # m05 neutral in fast path
        + m06_score
        + 1                   # m07 neutral in fast path (no DB)
        + _m08(horse)
    )


def _m09(horse, field_horses, m01_m08_sum, market_odds):
    """
    model_win_pct  = this horse's M01–M08 sum / sum of all field horses' M01–M08
    market_implied = 1 / (market_odds + 1)
    gap            = model_win_pct − market_implied

    3 = gap ≥  0.08  (strong value)
    2 = gap ≥  0.03
    1 = gap ≥ −0.03  (approximately fair)
    0 = gap <  −0.03 (model below market → NO PLAY, no exceptions)

    Returns 1 (neutral) if market_odds is None or invalid.
    """
    if market_odds is None:
        return 1    # missing data — never block a bet on data error

    try:
        market_odds_f = float(market_odds)
        if market_odds_f <= 0:
            return 1
    except (TypeError, ValueError):
        return 1

    # Field normalization
    field_partials = [_quick_partial(h, field_horses) for h in field_horses]
    field_total    = sum(field_partials)
    if field_total == 0:
        return 1

    model_win_pct  = m01_m08_sum / field_total
    market_implied = 1.0 / (market_odds_f + 1.0)
    gap            = model_win_pct - market_implied

    if gap >=  0.08: return 3
    if gap >=  0.03: return 2
    if gap >= -0.03: return 1
    return 0    # AUTO NO-PLAY trigger


# ---------------------------------------------------------------------------
# M10  Equipment & Medication Flag  (multiplier metric)
# ---------------------------------------------------------------------------

def _m10(horse, m07_score):
    """
    3 = first Lasix + strong trainer (M07 ≥ 2)
    2 = blinkers change + strong trainer (M07 ≥ 2)
    1 = any equipment/medication change without strong trainer signal
    0 = no changes at all
    """
    first_lasix    = bool(horse.get("first_time_lasix", False))
    blinkers       = (horse.get("blinkers_change") or "none").lower()
    has_any_change = first_lasix or blinkers != "none"

    if first_lasix and m07_score >= 2:
        return 3
    if blinkers != "none" and m07_score >= 2:
        return 2
    if has_any_change:
        return 1
    return 0


# ---------------------------------------------------------------------------
# M11  Layoff Cycle Position  (multiplier metric)
# ---------------------------------------------------------------------------

def _m11(horse):
    """
    3 = 90–179 days  (second race back — sweet spot)
    2 = 45–89 days   (third race back zone)
    1 = 1–44 days    (actively racing) or first timer
    0 = 180+ days    (first race off extended layoff)
    """
    days = horse.get("days_since_last_race")
    if days is None:
        return 1    # first timer

    days = _safe_int(days, 0)
    if days == 0:
        return 1
    if 90 <= days <= 179:
        return 3
    if 45 <= days <= 89:
        return 2
    if 1 <= days <= 44:
        return 1
    return 0    # 180+


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------

def score_horse(horse_dict, field_horses, market_odds=None):
    """
    Score one horse on all 11 metrics.

    Parameters
    ----------
    horse_dict : dict
        Horse dict from horse_racing_parser.parse_race_file().
    field_horses : list[dict]
        Complete list of horses in the race (used for field comparisons in M02/M09).
    market_odds : float | None
        Current market odds for M09 value gap.
        Falls back to horse_dict['morning_line'] if not supplied.

    Returns
    -------
    dict with keys:
        horse_name, m01–m11, composite_score,
        is_bounce_risk, is_no_play, is_gem,
        model_win_pct  (float, from M09 calculation),
        pace_scenario, running_style
    """
    if market_odds is None:
        market_odds = horse_dict.get("morning_line")

    # --- M05 Auto Pace Scenario ---
    field_styles = [h.get('running_style', 'U') for h in field_horses]
    e_count = field_styles.count('E')
    p_count = field_styles.count('P')
    if e_count >= 3:
        pace_scenario = 'HOT'
    elif e_count == 0 and p_count <= 1:
        pace_scenario = 'SLOW'
    else:
        pace_scenario = 'MIXED'
    this_style = horse_dict.get('running_style', 'U')
    if pace_scenario == 'HOT':
        if this_style == 'E':
            m05 = 0   # Speed duel — front-runner gets crushed
        elif this_style == 'P':
            m05 = 2   # Presser benefits from hot pace
        else:
            m05 = 3   # Closer's dream — hot pace sets it up perfectly
    elif pace_scenario == 'SLOW':
        if this_style == 'E':
            m05 = 3   # Lone speed — unchallenged on the front end
        elif this_style == 'P':
            m05 = 2   # Presser still fine in slow pace
        else:
            m05 = 0   # Closer needs pace to close into — none here
    else:  # MIXED
        m05 = 1       # Neutral — no pace edge either way

    # ── Score M01–M08 ────────────────────────────────────────────────────
    m01 = _m01(horse_dict)
    m02 = _m02(horse_dict, field_horses)
    m03 = _m03(horse_dict)
    m04 = _m04(horse_dict)
    # m05 already computed above via auto pace scenario
    m06, _bounce = _m06(horse_dict)
    m07 = _m07(horse_dict)
    m08 = _m08(horse_dict)

    m01_m08_sum = m01 + m02 + m03 + m04 + m05 + m06 + m07 + m08

    # ── M09 — depends on full-field normalization ─────────────────────────
    m09 = _m09(horse_dict, field_horses, m01_m08_sum, market_odds)

    # ── M10 & M11 — multiplier metrics ───────────────────────────────────
    m10 = _m10(horse_dict, m07)
    m11 = _m11(horse_dict)

    composite = m01 + m02 + m03 + m04 + m05 + m06 + m07 + m08 + m09 + m10 + m11

    # ── Model win pct (for display) ───────────────────────────────────────
    field_partials = [_quick_partial(h, field_horses) for h in field_horses]
    field_total    = sum(field_partials) or 1
    model_win_pct  = round(m01_m08_sum / field_total, 4)

    return {
        "horse_name":      horse_dict.get("horse_name", ""),
        "post_position":   horse_dict.get("post_position"),
        "morning_line":    horse_dict.get("morning_line"),
        "m01": m01, "m02": m02, "m03": m03, "m04": m04,
        "m05": m05, "m06": m06, "m07": m07, "m08": m08,
        "m09": m09, "m10": m10, "m11": m11,
        "composite_score": composite,
        "model_win_pct":   model_win_pct,
        "is_bounce_risk":  m06 == 0,          # per spec: True when m06==0
        "is_no_play":      m09 == 0,           # AUTO NO-PLAY — M09 veto
        "is_gem":          composite >= GEM_THRESHOLD,
        "pace_scenario":   pace_scenario,
        "running_style":   this_style,
    }


def score_race(horses_list, market_odds_list=None):
    """
    Score all horses in a race and return sorted by composite_score descending.

    Parameters
    ----------
    horses_list : list[dict]
        All horse dicts for the race.
    market_odds_list : list[float] | None
        Market odds per horse, index-matched.  Falls back to morning_line.

    Returns
    -------
    list[dict]
        Scored dicts sorted descending by composite_score.
    """
    if market_odds_list is None:
        market_odds_list = [None] * len(horses_list)

    scored = []
    for i, horse in enumerate(horses_list):
        odds = market_odds_list[i] if i < len(market_odds_list) else None
        scored.append(score_horse(horse, horses_list, market_odds=odds))

    return sorted(scored, key=lambda s: s["composite_score"], reverse=True)


# ---------------------------------------------------------------------------
# SCORECARD PRINTER  (utility)
# ---------------------------------------------------------------------------

def print_scorecard(scored_list, title="EDGE Horse Racing Scorecard"):
    """Pretty-print a sorted scorecard table from score_race() output."""
    col_w = 20   # horse name column width
    hdr   = (
        f"{'Horse':<{col_w}} "
        f"{'PP':>2}  "
        f"{'ML':>5}  "
        f"M01 M02 M03 M04 M05 M06 M07 M08 M09 M10 M11  "
        f"{'CMP':>3}  {'Win%':>5}  Gem  NoPlay  Flags"
    )
    sep = "─" * len(hdr)

    print(f"\n{'═'*len(hdr)}")
    print(f"  {title}")
    print(f"{'═'*len(hdr)}")
    print(hdr)
    print(sep)

    for s in scored_list:
        name  = (s["horse_name"] or "?")[:col_w]
        pp    = s.get("post_position") or "?"
        ml    = f"{s.get('morning_line', '?')}"
        scores = " ".join(f"{s[f]:>3}" for f in ("m01","m02","m03","m04","m05","m06","m07","m08","m09","m10","m11"))
        comp  = s["composite_score"]
        wpct  = f"{s['model_win_pct']*100:5.1f}%"
        gem   = " GEM" if s["is_gem"]          else "    "
        nop   = "  NO-PLAY" if s["is_no_play"] else "         "
        flags = []
        if s["is_bounce_risk"]: flags.append("BOUNCE")
        flag_str = " ".join(flags)

        print(
            f"{name:<{col_w}} "
            f"{str(pp):>2}  "
            f"{ml:>5}  "
            f"{scores}  "
            f"{comp:>3}  "
            f"{wpct}  "
            f"{gem}{nop}  {flag_str}"
        )

    print(sep)
    gems    = [s for s in scored_list if s["is_gem"]]
    no_play = [s for s in scored_list if s["is_no_play"]]
    print(f"  Gems: {len(gems)}  |  No-Play: {len(no_play)}  |  "
          f"Gem threshold: {GEM_THRESHOLD}+")
    print(f"{'═'*len(hdr)}\n")


# ---------------------------------------------------------------------------
# MAIN TEST BLOCK — 5-horse dummy field
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    # ── Build 5-horse field covering all edge cases ───────────────────────
    # Each dict mirrors horse_racing_parser._build_horse_dict() output.
    # horses_list represents a single race field.

    field = [
        # ── Horse 1: GEM candidate ─────────────────────────────────────────
        # Improving figs, best in field, class drop, won on surface,
        # 120 days since last (M06=3, M11=3), first lasix, elite jockey
        {
            "horse_name":          "GEMSTONE GLORY",
            "post_position":       3,
            "morning_line":        4.0,       # generous odds → value gap likely
            "track":               "KEE",
            "race_type":           "CLM",
            "claiming_price":      25000,
            "surface":             "D",
            "distance_yards":      1760,
            "purse":               40000,
            "trainer":             "Brad Cox",
            "trainer_meet_starts": 24,
            "trainer_meet_wins":   7,
            "jockey":              "Irad Ortiz Jr.",
            "jockey_meet_starts":  55,
            "jockey_meet_wins":    14,        # 14/55 = 25.5% → M08=3
            "first_time_lasix":    True,
            "blinkers_change":     "none",
            "prime_power":         158.4,
            "days_since_last_race": 120,      # M06=3 (sweet spot), M11=3
            "speed_figures_last3":  [112, 108, 104],   # all improving → M01=3
            "surfaces_last3":       ["D", "D", "T"],
            "race_types_last3":     ["ALW", "ALW", "CLM"],  # class drop from ALW → M03=3
            "finish_positions_last3": [1, 2, 3],       # won on dirt → M04=3
            "call_positions_last3": [
                {"start": 2, "stretch": 1, "finish": 1},
                {"start": 3, "stretch": 2, "finish": 2},
                {"start": 4, "stretch": 3, "finish": 3},
            ],
        },
        # ── Horse 2: solid contender ───────────────────────────────────────
        # Stable figures, same class, ran on surface, 35 days → M06=1
        {
            "horse_name":          "STEADY PACER",
            "post_position":       6,
            "morning_line":        3.5,
            "track":               "KEE",
            "race_type":           "CLM",
            "claiming_price":      25000,
            "surface":             "D",
            "distance_yards":      1760,
            "purse":               40000,
            "trainer":             "Todd Pletcher",
            "trainer_meet_starts": 30,
            "trainer_meet_wins":   8,
            "jockey":              "John Velazquez",
            "jockey_meet_starts":  40,
            "jockey_meet_wins":    8,          # 8/40 = 20% → M08=3
            "first_time_lasix":    False,
            "blinkers_change":     "none",
            "prime_power":         142.1,
            "days_since_last_race": 35,        # M06=1 (31-89 days), M11=1
            "speed_figures_last3":  [105, 106, 104],   # one improvement → M01=2
            "surfaces_last3":       ["D", "T", "D"],
            "race_types_last3":     ["CLM", "CLM", "CLM"],
            "finish_positions_last3": [2, 4, 2],        # ran on dirt, no win → M04=2
            "call_positions_last3": [
                {"start": 1, "stretch": 2, "finish": 2},
                {"start": 5, "stretch": 4, "finish": 4},
                {"start": 2, "stretch": 3, "finish": 2},
            ],
        },
        # ── Horse 3: step-up, surface switch ──────────────────────────────
        # Declining figs, stepping up in class, switching surface, 20 days
        {
            "horse_name":          "DARK LONGSHOT",
            "post_position":       1,
            "morning_line":        15.0,      # long odds
            "track":               "KEE",
            "race_type":           "CLM",
            "claiming_price":      25000,
            "surface":             "D",
            "distance_yards":      1760,
            "purse":               40000,
            "trainer":             "Chad Brown",
            "trainer_meet_starts": 18,
            "trainer_meet_wins":   3,
            "jockey":              "Joel Rosario",
            "jockey_meet_starts":  28,
            "jockey_meet_wins":    4,          # 4/28 = 14.3% → M08=1
            "first_time_lasix":    False,
            "blinkers_change":     "none",
            "prime_power":         119.8,
            "days_since_last_race": 20,        # M06: check trend
            "speed_figures_last3":  [96, 100, 104],    # declining → M01=1
            "surfaces_last3":       ["T", "T", "T"],   # all turf, today dirt → M04=1
            "race_types_last3":     ["MCL", "MCL", "MCL"],  # MCL→CLM massive step → M03=0
            "finish_positions_last3": [3, 2, 4],
            "call_positions_last3": [
                {"start": 5, "stretch": 4, "finish": 3},
                {"start": 3, "stretch": 2, "finish": 2},
                {"start": 6, "stretch": 6, "finish": 4},
            ],
        },
        # ── Horse 4: bounce risk pattern ──────────────────────────────────
        # Big figure spike last out (potential bounce), 14 days since last
        {
            "horse_name":          "PEAK AND FADE",
            "post_position":       4,
            "morning_line":        2.5,       # bet-down favorite
            "track":               "KEE",
            "race_type":           "CLM",
            "claiming_price":      25000,
            "surface":             "D",
            "distance_yards":      1760,
            "purse":               40000,
            "trainer":             "Steve Asmussen",
            "trainer_meet_starts": 20,
            "trainer_meet_wins":   5,
            "jockey":              "Ricardo Santana",
            "jockey_meet_starts":  35,
            "jockey_meet_wins":    7,          # 7/35 = 20% → M08=3
            "first_time_lasix":    False,
            "blinkers_change":     "blinkers_on",
            "prime_power":         148.2,
            "days_since_last_race": 14,        # M06: figure check triggers bounce
            "speed_figures_last3":  [118, 102, 103],   # +16 spike → bounce risk, M06=0
            "surfaces_last3":       ["D", "D", "D"],
            "race_types_last3":     ["CLM", "CLM", "ALW"],
            "finish_positions_last3": [1, 3, 2],
            "call_positions_last3": [
                {"start": 1, "stretch": 1, "finish": 1},
                {"start": 4, "stretch": 3, "finish": 3},
                {"start": 2, "stretch": 2, "finish": 2},
            ],
        },
        # ── Horse 5: first timer, no figures ───────────────────────────────
        # Debut: no past race data, all metrics neutral/default
        {
            "horse_name":          "DEBUT DREAMER",
            "post_position":       7,
            "morning_line":        8.0,
            "track":               "KEE",
            "race_type":           "CLM",
            "claiming_price":      25000,
            "surface":             "D",
            "distance_yards":      1760,
            "purse":               40000,
            "trainer":             "Mark Casse",
            "trainer_meet_starts": 12,
            "trainer_meet_wins":   2,
            "jockey":              "Florent Geroux",
            "jockey_meet_starts":  20,
            "jockey_meet_wins":    3,          # 3/20 = 15% → M08=2
            "first_time_lasix":    False,
            "blinkers_change":     "none",
            "prime_power":         None,
            "days_since_last_race": None,      # first timer — M06=1, M11=1
            "speed_figures_last3":  [],        # no figures → M01=1 neutral
            "surfaces_last3":       [],
            "race_types_last3":     [],
            "finish_positions_last3": [],
            "call_positions_last3": [],
        },
    ]

    print("=" * 70)
    print("horse_racing_scorer.py — EDGE Intelligence Platform")
    print("Checkpoint 6: 5-horse mock field scorecard")
    print("=" * 70)

    # ── Score with auto M05 pace scenario (running_style from parser) ────
    results = score_race(field)
    print_scorecard(results, title="KEE Race 5 — $25k Claiming, 8f Dirt")

    # ── Per-horse detail for verification ────────────────────────────────
    print("── Per-horse metric detail ──────────────────────────────────────")
    for s in results:
        flags = []
        if s["is_gem"]:         flags.append("GEM")
        if s["is_no_play"]:     flags.append("NO-PLAY")
        if s["is_bounce_risk"]: flags.append("BOUNCE-RISK")
        print(
            f"  {s['horse_name']:<20} "
            f"composite={s['composite_score']:>2}  "
            f"model_win_pct={s['model_win_pct']*100:5.1f}%  "
            + (", ".join(flags) if flags else "clean")
        )

    print()
    print("Checkpoint 6 self-test: import check")
    print("  python -c \"import horse_racing_scorer; print('OK')\"")
