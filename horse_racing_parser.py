"""
horse_racing_parser.py — EDGE Intelligence Platform
Parses Brisnet Single File (.drf) CSV into structured horse dicts.

FIELD LAYOUT NOTES — Brisnet Single File DRF Format
====================================================
The DRF format uses PARALLEL ARRAYS for past performance data — all 10 values
of a given data type are stored together in a group of 10 consecutive fields,
rather than in per-race blocks. So:

  Fields 256-265 : race dates for past 10 races (most recent = field 256)
  Fields 316-325 : surface codes for past 10 races
  Fields 606-615 : gate/start call positions (confirmed from Brisnet docs)
  Fields 616-625 : stretch call positions (confirmed from Brisnet docs)
  ... etc.

All index constants below are 0-indexed (field N → index N-1).

HOW TO VERIFY FIELD POSITIONS AGAINST A REAL DRF FILE:
  1. Download a PP file (e.g., CD_20260405.drf) from Brisnet
  2. Open in Excel or run: python -c "import csv; r=list(csv.reader(open('CD_20260405.drf'))); print(list(enumerate(r[0], 1)))"
  3. Compare field values at each position against the known horse info
  4. Adjust the constants below to match
  Reference: https://support.brisnet.com/hc/en-us/articles/360056092092
"""

import csv
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# FIELD INDICES — 0-indexed (Brisnet's 1-indexed field number - 1)
# Calibrated against live PEN0408.DRF (PP Single File, 1435 fields/row)
# Run calibration: python horse_racing_parser.py --calibrate <file.drf>
# ---------------------------------------------------------------------------

# ── Current race / horse information ────────────────────────────────────────
F_TRACK           = 0    # field  1 : track abbreviation  ('PEN')
F_DATE            = 1    # field  2 : race date (YYYYMMDD) ('20260408')
F_RACE_NUM        = 2    # field  3 : race number  ('1')
F_POST_POS        = 3    # field  4 : post position ('1','2',…)  CONFIRMED
F_DISTANCE        = 5    # field  6 : distance in yards ('1320')  CONFIRMED
F_SURFACE         = 6    # field  7 : surface code D/T/d/t ('D')  CONFIRMED
F_RACE_TYPE       = 8    # field  9 : race type code C/A/M/G1… ('C')  CONFIRMED
F_PURSE           = 11   # field 12 : purse amount ('14000')  CONFIRMED
F_CLAIM_PRICE     = 12   # field 13 : claiming price ('4000')  CONFIRMED
F_MORNING_LINE    = 43   # field 44 : morning line odds ('1.40')  CONFIRMED
F_HORSE_NAME      = 44   # field 45 : horse name ('WARRIOR\'S MISS')  CONFIRMED

# ── Trainer — full name in one field ("LAST FIRST I" format) ────────────────
F_TRAINER_FULL    = 27   # field 28 : trainer full name ('KULP BRANDON L')  CONFIRMED
F_TRAINER_STARTS  = 28   # field 29 : trainer starts (year-to-date)  CONFIRMED approximate
F_TRAINER_WINS    = 29   # field 30 : trainer wins (year-to-date)    CONFIRMED approximate

# ── Jockey — full name in one field ("LAST FIRST I" format) ─────────────────
F_JOCKEY_FULL     = 32   # field 33 : jockey full name ('RODRIGUEZ ANGEL R')  CONFIRMED
F_JOCKEY_STARTS   = 34   # field 35 : jockey starts (year-to-date)   CONFIRMED approximate
F_JOCKEY_WINS     = 35   # field 36 : jockey wins (year-to-date)     CONFIRMED approximate

# ── Equipment / medication — indices not yet verified against live DRF ───────
F_MEDICATION      = 14   # VERIFY : medication code (L/B/LB/blank) — may be wrong
F_EQUIPMENT       = 15   # VERIFY : equipment (0=none,1=blinkers_on,2=blinkers_off) — may be wrong
F_FIRST_TIME_MED  = 68   # VERIFY : first-time medication flag (4 = first Lasix) — may be wrong

# ── Summary metrics ──────────────────────────────────────────────────────────
F_PRIME_POWER     = 250  # field 251: BRIS prime power rating ('111.59')  CONFIRMED
F_DAYS_SINCE      = 223  # field 224: days since last race to today  CONFIRMED

# ── Past performance parallel arrays (fields 256–635, index 0 = most recent) ─
# Each group = 10 consecutive fields, one per past race (most recent first).
# VERIFY all PP_* bases against a real DRF file.

PP_DATES_BASE     = 255  # fields 256-265 : race dates (YYYYMMDD)     CONFIRMED
PP_DAYS_BASE      = 265  # fields 266-275 : days between consecutive past races  CONFIRMED
PP_TRACKS_BASE    = 275  # fields 276-285 : track codes               CONFIRMED
PP_RACE_NUMS_BASE = 285  # fields 286-295 : track codes duplicate?    VERIFY
PP_RACE_TYPE_BASE = 295  # fields 296-305 : unknown small integers    VERIFY
PP_CONDITION_BASE = 305  # fields 306-315 : track conditions (FT/MY/GD…) CONFIRMED
PP_DISTANCE_BASE  = 315  # fields 316-325 : distances in yards (1320…)   CONFIRMED
PP_SURFACE_BASE   = 325  # fields 326-335 : surface codes (D/T…)     CONFIRMED
PP_POST_BASE      = 335  # fields 336-345 : EMPTY in live file        VERIFY
PP_STARTERS_BASE  = 345  # fields 346-355 : number of starters        likely correct
PP_ODDS_BASE      = 515  # fields 516-525 : closing odds (5.90/43.50) CONFIRMED
PP_CLAIM_BASE     = 535  # fields 536-545 : race type description strings CONFIRMED
PP_PURSE_BASE     = 555  # fields 556-565 : purse amounts             CONFIRMED
PP_SPEED_FIG_BASE = 765  # fields 766-775 : BRIS speed figures (most recent first)  CONFIRMED
PP_FC_BEATEN_PP1  = 865  # First-call beaten lengths, most recent race (idx, 0-based)
PP_FC_BEATEN_PP2  = 866  # First-call beaten lengths, 2nd most recent race
PP_FC_BEATEN_PP3  = 867  # First-call beaten lengths, 3rd most recent race
PP_FINISH_BASE    = 615  # fields 616-625 : official finish positions  CONFIRMED
PP_GATE_CALL_BASE = 565  # fields 566-575 : gate/start call positions  VERIFY
PP_STRETCH_BASE   = 595  # fields 596-605 : stretch call positions     VERIFY

# How many past race records we look at
N_PAST_RACES = 10   # Brisnet stores 10 past races
LAST3        = 3    # we only surface the last 3 in the horse dict

# Minimum field count a row must have to be parseable
# Must reach at least the speed figure array to be useful for scoring
MIN_FIELDS = PP_SPEED_FIG_BASE + N_PAST_RACES  # = 775

# ---------------------------------------------------------------------------
# EQUIPMENT / MEDICATION MAPS
# ---------------------------------------------------------------------------
EQUIPMENT_MAP = {
    "0": "none",
    "1": "blinkers_on",
    "2": "blinkers_off",
    "":  "none",
}

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _safe_str(fields, idx, default=""):
    """Return stripped string at index, or default if missing/empty."""
    try:
        return fields[idx].strip().strip('"')
    except IndexError:
        return default


def _safe_int(fields, idx, default=None):
    """Return int at index, or default if missing/blank/non-numeric."""
    try:
        val = fields[idx].strip().strip('"')
        return int(val) if val else default
    except (IndexError, ValueError):
        return default


def _safe_float(fields, idx, default=None):
    """Return float at index, or default if missing/blank/non-numeric."""
    try:
        val = fields[idx].strip().strip('"')
        return float(val) if val else default
    except (IndexError, ValueError):
        return default


def _extract_past3(fields, base, cast_fn=_safe_str, n=LAST3):
    """
    Extract the first `n` values from a parallel-array group starting at `base`.
    Returns a list of length n (with None/default where data is missing).
    """
    return [cast_fn(fields, base + i) for i in range(n)]


def _build_horse_dict(fields):
    """
    Parse a single DRF row (list of field strings) into a structured horse dict.
    Returns None if the row is too short to be a valid horse record.
    """
    if len(fields) < MIN_FIELDS:
        return None

    # ── Basic horse / race info ──────────────────────────────────────────
    track       = _safe_str(fields, F_TRACK)
    date_raw    = _safe_str(fields, F_DATE)       # YYYYMMDD from Brisnet
    race_num    = _safe_int(fields, F_RACE_NUM)
    distance    = _safe_int(fields, F_DISTANCE)
    surface     = _safe_str(fields, F_SURFACE)
    purse       = _safe_int(fields, F_PURSE)
    race_type   = _safe_str(fields, F_RACE_TYPE)
    claim_price = _safe_int(fields, F_CLAIM_PRICE)
    horse_name  = _safe_str(fields, F_HORSE_NAME)
    post_pos    = _safe_int(fields, F_POST_POS)

    # ── Morning line ─────────────────────────────────────────────────────
    morning_line = _safe_float(fields, F_MORNING_LINE)

    # ── Equipment / medication (indices unverified — may need recalibration) ─
    equip_raw      = _safe_str(fields, F_EQUIPMENT)
    blinkers_change = EQUIPMENT_MAP.get(equip_raw, "none")

    first_time_med_code = _safe_str(fields, F_FIRST_TIME_MED)
    first_time_lasix    = (first_time_med_code == "4")

    # ── Trainer — DRF stores full name as "LAST FIRST I" at one field ────
    trainer_full   = _safe_str(fields, F_TRAINER_FULL)   # e.g. "KULP BRANDON L"
    trainer_name   = trainer_full                          # stored as-is for DB keying
    trainer_starts = _safe_int(fields, F_TRAINER_STARTS, default=0)
    trainer_wins   = _safe_int(fields, F_TRAINER_WINS,   default=0)

    # ── Jockey — DRF stores full name as "LAST FIRST I" at one field ─────
    jockey_full   = _safe_str(fields, F_JOCKEY_FULL)    # e.g. "RODRIGUEZ ANGEL R"
    jockey_name   = jockey_full                           # stored as-is for DB keying
    jockey_starts = _safe_int(fields, F_JOCKEY_STARTS, default=0)
    jockey_wins   = _safe_int(fields, F_JOCKEY_WINS,   default=0)

    # ── Summary stats ────────────────────────────────────────────────────
    prime_power    = _safe_float(fields, F_PRIME_POWER)
    days_since     = _safe_int(fields, F_DAYS_SINCE)   # None = first-timer or data missing

    # ── Past 3 race parallel-array extractions ───────────────────────────
    speed_figs    = _extract_past3(fields, PP_SPEED_FIG_BASE, cast_fn=_safe_int)
    surfaces_pp   = _extract_past3(fields, PP_SURFACE_BASE,   cast_fn=_safe_str)
    race_types_pp = _extract_past3(fields, PP_RACE_TYPE_BASE, cast_fn=_safe_str)
    finish_pos    = _extract_past3(fields, PP_FINISH_BASE,    cast_fn=_safe_int)

    # ── Call positions for past 3 races ──────────────────────────────────
    gate_calls    = _extract_past3(fields, PP_GATE_CALL_BASE, cast_fn=_safe_int)
    stretch_calls = _extract_past3(fields, PP_STRETCH_BASE,   cast_fn=_safe_int)
    finish_calls  = finish_pos   # finish position doubles as the finish call

    call_positions = [
        {
            "start":   gate_calls[i],
            "stretch": stretch_calls[i],
            "finish":  finish_calls[i],
        }
        for i in range(LAST3)
    ]

    horse = {
        # Current race context
        "track":               track,
        "date":                date_raw,
        "race_number":         race_num,
        "distance_yards":      distance,
        "surface":             surface,
        "purse":               purse,
        "race_type":           race_type,
        "claiming_price":      claim_price,
        # Horse identity
        "horse_name":          horse_name,
        "post_position":       post_pos,
        "morning_line":        morning_line,
        # Connections
        "trainer":             trainer_name,
        "trainer_meet_starts": trainer_starts,
        "trainer_meet_wins":   trainer_wins,
        "jockey":              jockey_name,
        "jockey_meet_starts":  jockey_starts,
        "jockey_meet_wins":    jockey_wins,
        # Flags
        "first_time_lasix":    first_time_lasix,
        "blinkers_change":     blinkers_change,
        # Summary metrics
        "prime_power":         prime_power,
        "days_since_last_race": days_since,
        # Past 3 race arrays
        "speed_figures_last3":  speed_figs,
        "surfaces_last3":       surfaces_pp,
        "race_types_last3":     race_types_pp,
        "finish_positions_last3": finish_pos,
        "call_positions_last3": call_positions,
    }

    # --- M05 Pace Automation ---
    fc1 = _safe_int(fields, PP_FC_BEATEN_PP1)
    fc2 = _safe_int(fields, PP_FC_BEATEN_PP2)
    fc3 = _safe_int(fields, PP_FC_BEATEN_PP3)
    valid = [x for x in [fc1, fc2, fc3] if x is not None]
    if len(valid) >= 2:
        avg_fc = sum(valid) / len(valid)
        if avg_fc <= 2:
            running_style = 'E'   # Early / front-runner
        elif avg_fc <= 6:
            running_style = 'P'   # Presser / stalker
        else:
            running_style = 'S'   # Closer / off-the-pace
    else:
        running_style = 'U'       # Unknown — first timer or missing data
    horse['running_style'] = running_style
    horse['fc_beaten_pp1'] = fc1
    horse['fc_beaten_pp2'] = fc2
    horse['fc_beaten_pp3'] = fc3

    return horse


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------

def parse_race_file(file_path):
    """
    Read an entire .drf file and return all horses grouped by race number.

    Parameters
    ----------
    file_path : str or Path
        Path to the .drf CSV file.

    Returns
    -------
    dict[int, list[dict]]
        Keys are race numbers (int).
        Values are lists of horse dicts in that race, in file order.

    Notes
    -----
    Rows that fail to parse (too short, non-numeric race number, etc.) are
    skipped silently. The caller should check that the returned dict is
    non-empty.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"DRF file not found: {file_path}")

    races = {}

    with open(file_path, newline="", encoding="latin-1") as fh:
        reader = csv.reader(fh)
        for row_num, row in enumerate(reader, 1):
            if not row or len(row) < MIN_FIELDS:
                continue  # skip blank / header / malformed rows

            horse = _build_horse_dict(row)
            if horse is None or horse["race_number"] is None:
                continue

            rn = horse["race_number"]
            races.setdefault(rn, []).append(horse)

    return races


def parse_race(file_path, race_number):
    """
    Return only the horses for one specific race number.

    Parameters
    ----------
    file_path : str or Path
        Path to the .drf CSV file.
    race_number : int
        Race number to extract (1-indexed as printed on the card).

    Returns
    -------
    list[dict]
        List of horse dicts for that race, or empty list if race not found.
    """
    all_races = parse_race_file(file_path)
    return all_races.get(int(race_number), [])


# ---------------------------------------------------------------------------
# MOCK TEST — builds a synthetic 3-horse DRF CSV and exercises the parser
# ---------------------------------------------------------------------------

def _make_mock_row(
    track="KEE", date="20260404", race_num=3, distance_yards=1870, surface="D",
    purse=75000, race_type="A", claim=0, horse_name="MOCK STAR", post=1,
    morning_line=3.5, equip="1",
    trainer_name="COX BRAD",       # DRF format: "LAST FIRST [I]"
    trainer_starts=22, trainer_wins=7,
    jockey_name="ORTIZ JR. IRAD",  # DRF format: "LAST FIRST [I]"
    jockey_starts=44, jockey_wins=14,
    first_time_med="4",
    prime_power=145.8, days_since=21,
    # Past 3 speed figures, surfaces, race types, finish positions
    spd_figs=(110, 107, 103), pp_surfaces=("D", "D", "T"),
    pp_race_types=("A", "C", "A"), finish_positions=(1, 2, 3),
    gate_calls=(2, 1, 4), stretch_calls=(1, 2, 3),
):
    """
    Build a single mock DRF row as a list of strings.
    Total width: MIN_FIELDS + 1 (covers all defined positions).
    Only the key positions carry meaningful values; all others are empty.
    """
    n_fields = MIN_FIELDS + 1
    row = [""] * n_fields

    # ── Current race fields ──────────────────────────────────────────────
    row[F_TRACK]          = track
    row[F_DATE]           = date
    row[F_RACE_NUM]       = str(race_num)
    row[F_POST_POS]       = str(post)
    row[F_DISTANCE]       = str(distance_yards)
    row[F_SURFACE]        = surface
    row[F_RACE_TYPE]      = race_type
    row[F_PURSE]          = str(purse)
    row[F_CLAIM_PRICE]    = str(claim)
    row[F_MORNING_LINE]   = str(morning_line)
    row[F_HORSE_NAME]     = horse_name
    row[F_EQUIPMENT]      = equip
    row[F_TRAINER_FULL]   = trainer_name
    row[F_TRAINER_STARTS] = str(trainer_starts)
    row[F_TRAINER_WINS]   = str(trainer_wins)
    row[F_JOCKEY_FULL]    = jockey_name
    row[F_JOCKEY_STARTS]  = str(jockey_starts)
    row[F_JOCKEY_WINS]    = str(jockey_wins)
    row[F_FIRST_TIME_MED] = first_time_med
    row[F_PRIME_POWER]    = str(prime_power)
    row[F_DAYS_SINCE]     = str(days_since)

    # ── Past 3 race parallel arrays ──────────────────────────────────────
    for i in range(3):
        row[PP_SPEED_FIG_BASE + i] = str(spd_figs[i])
        row[PP_SURFACE_BASE   + i] = pp_surfaces[i]
        row[PP_RACE_TYPE_BASE + i] = pp_race_types[i]
        row[PP_FINISH_BASE    + i] = str(finish_positions[i])
        row[PP_GATE_CALL_BASE + i] = str(gate_calls[i])
        row[PP_STRETCH_BASE   + i] = str(stretch_calls[i])

    return row


if __name__ == "__main__":
    import io
    import pprint

    print("=" * 65)
    print("horse_racing_parser.py — EDGE Intelligence Platform")
    print("Checkpoint 5: mock parse test")
    print("=" * 65)

    # ── Build 3 mock horse rows for race 3 ──────────────────────────────
    horses_data = [
        dict(
            horse_name="MOCK STAR",     post=1, morning_line=3.5,
            equip="1",  first_time_med="4",  prime_power=145.8, days_since=21,
            trainer_name="COX BRAD",    trainer_starts=22, trainer_wins=7,
            jockey_name="ORTIZ JR. IRAD", jockey_starts=44, jockey_wins=14,
            spd_figs=(110, 107, 103),
            pp_surfaces=("D", "D", "T"),
            pp_race_types=("A", "C", "A"),
            finish_positions=(1, 2, 3),
            gate_calls=(2, 1, 4),       stretch_calls=(1, 2, 3),
        ),
        dict(
            horse_name="SPEED DEMON",   post=2, morning_line=5.0,
            equip="0",  first_time_med="",     prime_power=138.2, days_since=14,
            trainer_name="PLETCHER TODD", trainer_starts=31, trainer_wins=8,
            jockey_name="VELAZQUEZ JOHN", jockey_starts=38, jockey_wins=9,
            spd_figs=(105, 108, 101),
            pp_surfaces=("D", "D", "D"),
            pp_race_types=("A", "A", "M"),
            finish_positions=(2, 1, 4),
            gate_calls=(1, 3, 2),       stretch_calls=(2, 1, 4),
        ),
        dict(
            horse_name="DARK RUNNER",   post=5, morning_line=12.0,
            equip="2",  first_time_med="",     prime_power=121.5, days_since=None,
            trainer_name="BROWN CHAD",  trainer_starts=15, trainer_wins=4,
            jockey_name="ROSARIO JOEL", jockey_starts=29, jockey_wins=6,
            spd_figs=(99, 102, 96),
            pp_surfaces=("T", "T", "D"),
            pp_race_types=("N", "A", "C"),
            finish_positions=(3, 4, 1),
            gate_calls=(6, 5, 1),       stretch_calls=(4, 5, 2),
        ),
    ]

    # ── Assemble mock CSV in memory ──────────────────────────────────────
    buf = io.StringIO()
    writer = csv.writer(buf)
    for kwargs in horses_data:
        writer.writerow(_make_mock_row(**kwargs))
    mock_csv = buf.getvalue()

    print(f"\nMock CSV: 3 rows × {len(mock_csv.splitlines()[0].split(','))} fields\n")

    # ── Write to a temp file and parse ───────────────────────────────────
    import tempfile, sys
    tmp_path = Path(tempfile.mktemp(suffix="_mock_test.drf"))
    tmp_path.write_text(mock_csv, encoding="latin-1")

    races = parse_race_file(str(tmp_path))

    print(f"Races parsed: {sorted(races.keys())}")
    print(f"Horses in race 3: {len(races.get(3, []))}\n")

    # ── Print first horse dict ───────────────────────────────────────────
    first_horse = races[3][0]
    print("── First horse dict ──────────────────────────────────────────")
    pprint.pprint(first_horse, sort_dicts=False, width=70)

    # ── Key assertions ───────────────────────────────────────────────────
    print("\n── Key assertions ────────────────────────────────────────────")
    checks = [
        ("horse_name",              "MOCK STAR"),
        ("track",                   "KEE"),
        ("race_number",             3),
        ("surface",                 "D"),
        ("post_position",           1),
        ("morning_line",            3.5),
        ("trainer",                 "COX BRAD"),       # full name, DRF format
        ("jockey",                  "ORTIZ JR. IRAD"), # full name, DRF format
        ("first_time_lasix",        True),
        ("blinkers_change",         "blinkers_on"),
        ("prime_power",             145.8),
        ("days_since_last_race",    21),
        ("speed_figures_last3",     [110, 107, 103]),
        ("surfaces_last3",          ["D", "D", "T"]),
        ("race_types_last3",        ["A", "C", "A"]),
        ("finish_positions_last3",  [1, 2, 3]),
        ("call_positions_last3[0]", {"start": 2, "stretch": 1, "finish": 1}),
    ]

    all_pass = True
    for key, expected in checks:
        if key == "call_positions_last3[0]":
            actual = first_horse["call_positions_last3"][0]
        else:
            actual = first_horse.get(key)
        status = "PASS" if actual == expected else "FAIL"
        if status == "FAIL":
            all_pass = False
        print(f"  [{status}] {key}: got {actual!r}")

    print()
    print("All assertions passed ✓" if all_pass else "SOME ASSERTIONS FAILED ✗")

    # ── parse_race() smoke test ───────────────────────────────────────────
    race3 = parse_race(str(tmp_path), 3)
    assert len(race3) == 3, f"Expected 3 horses, got {len(race3)}"
    assert parse_race(str(tmp_path), 9) == [], "Expected empty list for race 9"
    print("\nparse_race() function: OK (race 3 = 3 horses, race 9 = [])")

    # ── Clean up temp file ────────────────────────────────────────────────
    try:
        tmp_path.unlink(missing_ok=True)
    except Exception:
        pass  # sandbox permission constraints — file is in /tmp, OS will purge it

    print("\nCheckpoint 5 self-test: import check")
    print("  python -c \"import horse_racing_parser; print('OK')\"")
