# Algorithm adapted from kenthunt/chart-parser (MIT, https://github.com/kenthunt/chart-parser)
"""
horse_racing_pdf_parser_v2 — Equibase Full Chart PDF parser for the EDGE Platform.

Build phase
-----------
Phase 4 — Race Assembly. Per-horse dicts populated against the EDGE schema.

Phase 1 primitives:
    extract_chars(pdf_path)
    convert_to_text(chars)

Phase 2 spatial structure:
    group_chars_by_row(chars)
    identify_header_row(rows)
    build_column_map(header_row)
    group_row_chars_by_column(row, column_map)

Phase 3 decoders:
    decode_beaten_lengths(text)
    decode_position_cell(text)
    decode_horse_jockey_cell(text)

Phase 4 race assembly:
    recalibrate_column_map(rows, header_row, header_column_map)
    extract_running_line_rows(rows, header_row)
    decode_running_line_cell(col_name, cell_text)
    classify_pace_scenario(fractional_times_seconds, distance_feet)
    extract_race_metadata(rows)
    parse_race(rows, race_metadata=None)

Phase 5 entry point (parse_chart_pdf) lands next.

References
----------
- Chart_Parser_Technical_Reference.md (project root)
- EDGE_HorseRacing_Handoff_May5.docx (project root)
- horse_racing_data/points_of_call.json (Phase 4 still-pending dependency)
"""

from __future__ import annotations

import bisect
import json  # noqa: F401  — used by Phase 4 distance lookups when JSON is in place
import logging
import re
from pathlib import Path

import pdfplumber

# ---------------------------------------------------------------------------
# Tuning constants (Phase 1/2)
# ---------------------------------------------------------------------------
MIN_SPACE_THRESHOLD = 0.001
MAX_SPACE_THRESHOLD = 3
ROW_BOUNDARY_THRESHOLD = 4
ROW_CLUSTERING_TOLERANCE = 5
HEADER_TOKENS = ("PP", "Str", "Fin", "Horse", "Jockey", "1/4", "1/2", "3/4", "Wt")
HEADER_MIN_MATCHES = 4

# Phase 4 calibration constants
CALIBRATION_SAMPLE_ROWS = 5            # how many data rows to sample for x_start measurement
CALIBRATION_WINDOW_BUFFER = 5.0        # units LEFT of header x_start that the search window extends
RUNNING_LINE_X_TOLERANCE = 3.0         # leftmost-char x0 must be within ±this of header's first column
COLUMN_FLOOR_TOLERANCE = 0.1           # FP-roundoff absorption in group_row_chars_by_column floor lookup

# ---------------------------------------------------------------------------
# EDGE-specific transforms (Phase 4D)
# ---------------------------------------------------------------------------
# Surface remap. Equibase emits 'D'/'T'/'d'/'t' (lowercase = inner turf
# / inner dirt). EDGE schema uses 'D'/'T'/'I'/'S' where 'I' = inner turf,
# 'S' = synthetic / all-weather.
SURFACE_MAP = {
    "D": "D",
    "T": "T",
    "d": "D",
    "t": "I",
    "A": "S",
}

# Distance text → distance in feet. Hardcoded common distances; the
# authoritative source will be horse_racing_data/points_of_call.json once
# Kyle drops it. If that JSON is present and disagrees with this table,
# the JSON wins.
DISTANCE_TEXT_TO_FEET = {
    "Five Furlongs": 3300,
    "Five And One Half Furlongs": 3630,
    "Six Furlongs": 3960,
    "Six And One Half Furlongs": 4290,
    "Seven Furlongs": 4620,
    "One Mile": 5280,
    "One And One Sixteenth Miles": 5610,
    "One And One Eighth Miles": 5940,
    "One And Three Sixteenths Miles": 6270,
    "One And One Quarter Miles": 6600,    # 1.25 mi, formal phrasing
    "One And One Fourth Miles": 6600,      # Derby — Equibase's actual phrasing as of 2026
    "One And Three Eighths Miles": 7260,
    "One And One Half Miles": 7920,
}

# Surface phrase → SURFACE_MAP key, in order of specificity (Inner Turf must
# match before plain Turf; Inner Dirt before plain Dirt).
SURFACE_PHRASES = (
    ("On The Inner Turf", "t"),
    ("On The Inner Dirt", "d"),
    ("On The All Weather", "A"),
    ("On The Synthetic", "A"),
    ("On The Tapeta", "A"),
    ("On The Polytrack", "A"),
    ("On The Turf", "T"),
    ("On The Dirt", "D"),
)

# Track-name aliases (P5-NEW-OBS-5 / P7B.4). The stray-glyph artifact in
# Equibase chart titles introduces extra whitespace into the matched track
# name (different glyphs on different pages — a "<" on page 1, a "*" on
# page 21 of the May 2 Churchill PDF). The whitespace-collapse step in
# parse_chart_pdf can't recover the joined word, so we keep an explicit
# alias table. Add observed aliases here as new charts surface them.
TRACK_NAME_ALIASES = {
    "CHUR CHILL DOWNS":  "CHURCHILL DOWNS",
    "CHURCHIL L DOWNS":  "CHURCHILL DOWNS",
}


def _normalize_track_name(name):
    """Apply TRACK_NAME_ALIASES to a (whitespace-collapsed) track string."""
    if not name:
        return name
    return TRACK_NAME_ALIASES.get(name, name)

log = logging.getLogger(__name__)


# ===========================================================================
# Primitive 1 — extract_chars
# ===========================================================================
def extract_chars(pdf_path):
    """Extract every character from every page of a PDF as positioned dicts."""
    path = Path(pdf_path)
    chars = []
    try:
        with pdfplumber.open(path) as pdf:
            for page_index, page in enumerate(pdf.pages, start=1):
                for c in page.chars:
                    char = dict(c)
                    char["page_number"] = page_index
                    chars.append(char)
    except Exception as exc:
        log.error("extract_chars failed for %s: %s", path, exc)
        return []
    return chars


# ===========================================================================
# Primitive 2 — convert_to_text
# ===========================================================================
def convert_to_text(chars):
    """Concatenate chars into text with spaces, pipes, and newlines per spacing rules."""
    if not chars:
        return ""
    out = []
    prev = None
    for curr in chars:
        if prev is not None:
            spacing = curr["x0"] - prev["x1"]
            if MIN_SPACE_THRESHOLD < spacing <= MAX_SPACE_THRESHOLD:
                out.append(" ")
            elif spacing > MAX_SPACE_THRESHOLD:
                out.append("|")
            if abs(curr["top"] - prev["top"]) > ROW_BOUNDARY_THRESHOLD:
                out.append("\n")
        out.append(curr["text"])
        prev = curr
    return "".join(out)


# ===========================================================================
# Phase 2.1 — group_chars_by_row
# ===========================================================================
def group_chars_by_row(chars, *, apply_noise_filter=True):
    """Cluster chars into rows by y-position, sort each row left-to-right.

    Page-aware (P4-NEW-OBS-2): chars from different pages never merge into
    the same row, even if their y-coordinates happen to coincide. We sort
    by (page_number, top, x0) and trigger a new row on either a page
    change or a top-delta exceeding ROW_CLUSTERING_TOLERANCE.
    """
    if not chars:
        return []
    sorted_chars = sorted(
        chars, key=lambda c: (c.get("page_number", 1), c["top"], c["x0"])
    )
    rows = []
    current_row = []
    anchor_top = None
    anchor_page = None
    for c in sorted_chars:
        page = c.get("page_number", 1)
        if anchor_top is None:
            anchor_top = c["top"]
            anchor_page = page
            current_row = [c]
            continue
        if page != anchor_page or c["top"] - anchor_top > ROW_CLUSTERING_TOLERANCE:
            rows.append(current_row)
            current_row = [c]
            anchor_top = c["top"]
            anchor_page = page
        else:
            current_row.append(c)
    if current_row:
        rows.append(current_row)
    for row in rows:
        row.sort(key=lambda c: c["x0"])
    if not apply_noise_filter:
        return rows
    filtered = []
    for row in rows:
        if len(row) == 1:
            ch = row[0]
            text = ch["text"]
            width = ch["x1"] - ch["x0"]
            if not text.isalnum() and width < 3:
                continue
        filtered.append(row)
    return filtered


# ===========================================================================
# Phase 2.2 — identify_header_row
# ===========================================================================
def identify_header_row(rows):
    """First row whose text contains >= HEADER_MIN_MATCHES of HEADER_TOKENS."""
    for row in rows:
        text = convert_to_text(row)
        matches = sum(1 for tok in HEADER_TOKENS if tok in text)
        if matches >= HEADER_MIN_MATCHES:
            return row
    log.warning(
        "identify_header_row found no header in %d rows (need %d of %s)",
        len(rows), HEADER_MIN_MATCHES, list(HEADER_TOKENS),
    )
    return None


# ===========================================================================
# Phase 2.3 — build_column_map
# ===========================================================================
def build_column_map(header_row):
    """Tokenize a header row into {column_name: x_start} pairs."""
    if not header_row:
        return {}
    tokens = []
    current_chars = []
    current_x_start = None
    prev = None
    for c in header_row:
        if prev is not None:
            spacing = c["x0"] - prev["x1"]
            if spacing > MAX_SPACE_THRESHOLD:
                if current_chars and current_x_start is not None:
                    tokens.append(("".join(current_chars), current_x_start))
                current_chars = []
                current_x_start = None
            elif spacing > MIN_SPACE_THRESHOLD:
                if current_chars:
                    current_chars.append(" ")
        if not current_chars:
            current_x_start = c["x0"]
        current_chars.append(c["text"])
        prev = c
    if current_chars and current_x_start is not None:
        tokens.append(("".join(current_chars), current_x_start))
    column_map = {}
    for raw_name, x_start in tokens:
        name = raw_name.strip()
        if not name:
            continue
        if name in column_map:
            i = 2
            while f"{name}_{i}" in column_map:
                i += 1
            column_map[f"{name}_{i}"] = x_start
        else:
            column_map[name] = x_start
    return column_map


# ===========================================================================
# Phase 2.4 — group_row_chars_by_column
# ===========================================================================
def group_row_chars_by_column(row, column_map):
    """Floor-by-x_start char-to-column assignment (Java TreeSet#floor port)."""
    if not column_map:
        return {}
    sorted_items = sorted(column_map.items(), key=lambda kv: kv[1])
    sorted_x_starts = [x for _, x in sorted_items]
    sorted_names = [name for name, _ in sorted_items]
    result = {name: [] for name in column_map}
    dropped = 0
    for c in row:
        x = c["x0"]
        # Add COLUMN_FLOOR_TOLERANCE to absorb floating-point roundoff and
        # minor positioning jitter — without this, a char whose x0 sits
        # ~1e-7 below the calibrated x_start (genuinely the SAME visual
        # column position, just FP noise from PDF transforms) lands in
        # the prior column. Discovered debugging Get Them Roses' Fin "8"
        # at 454.95199920000005 vs Fin x_start 454.952. P4-NEW-OBS-3.
        idx = bisect.bisect_right(sorted_x_starts, x + COLUMN_FLOOR_TOLERANCE) - 1
        if idx < 0:
            dropped += 1
            continue
        result[sorted_names[idx]].append(c)
    if dropped:
        log.debug("group_row_chars_by_column: dropped %d chars left of first column", dropped)
    for cell in result.values():
        cell.sort(key=lambda c: c["x0"])
    return result


# ===========================================================================
# Phase 3 — decoders
# ===========================================================================
TEXT_LENGTHS_AHEAD_PATTERN = re.compile(r"Head|Neck|Nose")
LENGTHS_AND_FRACTION_PATTERN = re.compile(r"((\d+)\s+)?((\d+)/(\d+))")
EVEN_LENGTHS_PATTERN = re.compile(r"^(\d+)$")    # see P3-NEW-OBS-1 — upstream-faithful

TEXT_LENGTHS_VALUES = {"Nose": 0.05, "Head": 0.10, "Neck": 0.25}

POSITION_PATTERN = re.compile(r"^\s*(\d+)")
HORSE_JOCKEY_PATTERN = re.compile(
    r"^\s*(?P<horse>.+?)\s*\((?P<jockey>[^)]+)\)\s*"
)


def decode_beaten_lengths(text):
    """Decode a beaten-lengths cell to a decimal lengths value."""
    if not text:
        return 0.0
    cleaned = text.replace("|", " ").strip()
    if not cleaned:
        return 0.0
    total = 0.0
    for m in TEXT_LENGTHS_AHEAD_PATTERN.finditer(cleaned):
        total += TEXT_LENGTHS_VALUES.get(m.group(0), 0.0)
    for m in LENGTHS_AND_FRACTION_PATTERN.finditer(cleaned):
        whole = int(m.group(2)) if m.group(2) else 0
        num = int(m.group(4))
        den = int(m.group(5))
        total += whole + (num / den if den else 0.0)
    m = EVEN_LENGTHS_PATTERN.match(cleaned)
    if m:
        total += int(m.group(1))
    return total


def decode_position_cell(text):
    """Extract leading integer position. Returns None if no leading digit."""
    if not text:
        return None
    m = POSITION_PATTERN.match(text)
    if not m:
        return None
    return int(m.group(1))


def decode_horse_jockey_cell(text):
    """Split combined 'Horse Name (Jockey)' cell into (horse, jockey)."""
    if not text or not text.strip():
        return (None, None)
    m = HORSE_JOCKEY_PATTERN.match(text)
    if m:
        return (m.group("horse").strip(), m.group("jockey").strip())
    fallback = text.strip()
    return (fallback or None, None)


# ===========================================================================
# Phase 4A — recalibrate_column_map
# ===========================================================================
def recalibrate_column_map(rows, header_row, header_column_map):
    """
    Replace header-derived column x_starts with data-derived x_starts.

    Algorithm: take the first CALIBRATION_SAMPLE_ROWS data rows after the
    header (a "data row" is one whose leftmost char is a digit, matching
    the Equibase 'Last Raced' format like '7Mar26 11TAM6'). For each
    column, define a search window from `header_x_start - CALIBRATION_WINDOW_BUFFER`
    to the next column's header x_start (exclusive). The calibrated
    x_start is the minimum leftmost-x0 of any char inside that window
    across the sampled rows. Columns with no chars in any sampled row's
    window fall back to their header x_start.

    See P3-NEW-OBS-2 for why this is needed: Equibase header glyphs sit
    slightly left of where the data values actually start, so the
    floor-by-header-x_start logic in group_row_chars_by_column leaks
    primary data (leading digits, leading horse-name letters) into the
    prior column.
    """
    if not header_row or not header_column_map:
        return dict(header_column_map)

    try:
        header_idx = rows.index(header_row)
    except ValueError:
        log.warning("recalibrate_column_map: header_row not in rows")
        return dict(header_column_map)

    # Walk forward and collect ALL data rows (rows whose leftmost char is a
    # digit) until the running-line block ends. Using all data rows — not just
    # the first CALIBRATION_SAMPLE_ROWS — catches 2-digit program numbers that
    # may not appear early in the field. P5-NEW-OBS-3.
    data_rows = []
    for row in rows[header_idx + 1:]:
        if not row:
            continue
        first_char = row[0]
        if not first_char.get("text") or not first_char["text"][0].isdigit():
            # Stop at first non-data row — we don't want to walk past the
            # running-line block into payouts/comments where row layout differs.
            break
        data_rows.append(row)

    if not data_rows:
        log.warning("recalibrate_column_map: no data rows; returning header map")
        return dict(header_column_map)

    sorted_cols = sorted(header_column_map.items(), key=lambda kv: kv[1])
    calibrated = {}
    for i, (col_name, header_x) in enumerate(sorted_cols):
        next_x = sorted_cols[i + 1][1] if i + 1 < len(sorted_cols) else float("inf")
        win_lo = header_x - CALIBRATION_WINDOW_BUFFER
        win_hi = next_x

        per_row_lefts = []
        for row in data_rows:
            in_win = [c["x0"] for c in row if win_lo <= c["x0"] < win_hi]
            if in_win:
                per_row_lefts.append(min(in_win))

        if per_row_lefts:
            calibrated[col_name] = min(per_row_lefts)
        else:
            log.debug(
                "recalibrate_column_map: %r has no data-window chars; falling back to header x_start",
                col_name,
            )
            calibrated[col_name] = header_x

    return calibrated


# ===========================================================================
# Phase 4B — extract_running_line_rows
# ===========================================================================
def extract_running_line_rows(rows, header_row):
    """
    Walking forward from header+1, return the contiguous block of running-line
    rows. A row qualifies if its leftmost char is a digit AND its leftmost
    char's x0 is within ±RUNNING_LINE_X_TOLERANCE of the header's leftmost
    char x0. Stop at the first row that fails either condition.
    """
    if not header_row:
        return []
    try:
        header_idx = rows.index(header_row)
    except ValueError:
        return []

    anchor_x = header_row[0]["x0"]
    out = []
    for row in rows[header_idx + 1:]:
        if not row:
            break
        first = row[0]
        if not first.get("text"):
            break
        if not first["text"][0].isdigit():
            break
        if abs(first["x0"] - anchor_x) > RUNNING_LINE_X_TOLERANCE:
            break
        out.append(row)
    return out


# ===========================================================================
# Phase 4C — decode_running_line_cell  (column-aware decoder)
# ===========================================================================
# Equibase column name → (pos_field, beaten_field) for fractional-position
# columns. The 1m alias maps to pos_q3 only when 3/4 isn't already present;
# the orchestrator (parse_race) handles that disambiguation.
# P7A correction: removed the "1m" alias to pos_q3. The Phase 4 spec said:
# "accept 1m as an alias and map to pos_q3 if no 3/4 column was present, or
#  to a separate pos_one_mile if both are present." My initial implementation
# aliased unconditionally, so for marathons (Derby has BOTH "3/4" and "1m"),
# the 1m cell overwrote pos_q3 with the 1m data, dropping 3/4 entirely.
# This made late_gain measure "1m to finish" instead of "3/4 to finish",
# and broke Phase 7A criterion #1 for Renegade.
#
# For now: 3/4 keeps pos_q3, 1m data is dropped (the unknown-column passthrough
# in decode_running_line_cell stores it as raw_1m). Phase 7B will add a proper
# pos_one_mile / beaten_lengths_one_mile schema field for marathon races.
FRACTIONAL_POSITION_FIELDS = {
    "1/4": ("pos_q1", "beaten_lengths_q1"),
    "1/2": ("pos_q2", "beaten_lengths_q2"),
    "3/4": ("pos_q3", "beaten_lengths_q3"),
    # 1m has its own pair (P7B.1). Marathons (>=1 1/8 mi) carry both 3/4
    # and 1m calls; sprints/short routes have neither or just 3/4. The
    # separate field preserves both rather than aliasing one to the other.
    "1m":  ("pos_one_mile", "beaten_lengths_one_mile"),
    "Str": ("pos_str", "beaten_lengths_str"),
    "Fin": ("finish_position", "beaten_lengths_finish"),
}


def _split_position_and_lengths(cell_text, field_size=9):
    """
    Split a fractional-position cell into (pos:int|None, lengths_text:str).

    Algorithm depends on field_size (P4-NEW-OBS-6 fix):
        field_size <= 9  -> position is always the single first digit
        field_size >= 10 -> position may be 1 or 2 digits; prefer 2-digit
                            iff first 2 chars are digits AND the 2-digit
                            value is in [10, field_size]. Otherwise fall
                            back to single-digit.

    Examples:
        '21 1/2', fs=8  -> (2, '1 1/2')
        '101/2',  fs=20 -> (10, '1/2')      # 2-digit pos because 10 <= 20
        '21 1/2', fs=20 -> (2, '1 1/2')     # 21 > 20, fall back to 1-digit
        '12',     fs=15 -> (12, '')         # 12 <= 15 AND tail empty
        '12',     fs=8  -> (1, '2')         # fs=8, single-digit only
        '8',      fs=8  -> (8, '')
        '1Head',  fs=any -> (1, 'Head')
        '',       fs=any -> (None, '')
    """
    if not cell_text:
        return None, ""
    cleaned = cell_text.replace("|", " ").strip()
    if not cleaned or not cleaned[0].isdigit():
        return None, cleaned

    if field_size <= 9:
        return int(cleaned[0]), cleaned[1:].strip()

    # field_size >= 10: try 2-digit position first, but only if the rest of
    # the cell is consistent with that interpretation. The disambiguator:
    # if cleaned[2] is '/', the second digit is the numerator of a fraction
    # (e.g. cell "11/2" means pos=1 lengths="1/2", NOT pos=11 lengths="/2").
    # P5-NEW-OBS-1.
    if len(cleaned) >= 2 and cleaned[0:2].isdigit():
        candidate = int(cleaned[0:2])
        if 10 <= candidate <= field_size:
            third = cleaned[2:3]
            if third != "/":
                return candidate, cleaned[2:].strip()
    return int(cleaned[0]), cleaned[1:].strip()


def decode_running_line_cell(col_name, cell_text, field_size=9):
    """
    Column-aware decoder. Returns a dict of EDGE schema fields for one cell.

    Mapping table (Equibase column -> EDGE fields):
        'Last Raced'           -> last_raced_text
        'Pgm'                  -> program_number (str — preserves 1A, 2B coupled markers)
        'Horse Name (Jockey)'  -> horse_name, jockey
        'Wgt M/E'              -> weight_carried, medication_code, equipment_code
        'PP'                   -> post_position
        'Start'                -> start_position
        '1/4', '1/2', '3/4', '1m' -> pos_q{1,2,3}, beaten_lengths_q{1,2,3}
        'Str'                  -> pos_str, beaten_lengths_str
        'Fin'                  -> finish_position, beaten_lengths_finish
        'Odds'                 -> final_odds, was_favorite
        'Comments'             -> comment

    Unknown columns fall through to a `raw_<col_name>` passthrough.
    """
    cleaned = (cell_text or "").strip()

    if col_name == "Last Raced":
        return {"last_raced_text": cleaned or None}

    if col_name == "Pgm":
        # Pgm may contain bleed (e.g. "11|P" — the "|P" is the start of the
        # next horse name). Anchored extraction of leading word characters
        # preserves '1A', '2B' coupled-entry markers.
        m = re.match(r"^\s*(\w+)", cleaned)
        return {"program_number": m.group(1) if m else None}

    if col_name == "Horse Name (Jockey)":
        horse, jockey = decode_horse_jockey_cell(cleaned)
        return {"horse_name": horse, "jockey": jockey}

    if col_name == "Wgt M/E":
        # Leading numeric is weight; trailing is M/E codes. Per upstream
        # WgtMedEquip.java, the first letter of the tail is medication
        # (M, e.g. 'L' = Lasix) and any remaining chars are equipment
        # (E, e.g. 'b' = blinkers, 'f' = front bandages).
        cl = cleaned.replace("|", " ").strip()
        wm = re.match(r"^\s*(\d+)\s*([A-Za-z]*)", cl)
        if wm:
            wt = int(wm.group(1))
            tail = wm.group(2)
            med = tail[0] if tail else None
            eq = tail[1:] if len(tail) > 1 else None
            return {
                "weight_carried": wt,
                "medication_code": med,
                "equipment_code": eq,
            }
        return {
            "weight_carried": None,
            "medication_code": None,
            "equipment_code": None,
        }

    if col_name == "PP":
        return {"post_position": decode_position_cell(cleaned)}

    if col_name == "Start":
        return {"start_position": decode_position_cell(cleaned)}

    if col_name in FRACTIONAL_POSITION_FIELDS:
        pos_field, beaten_field = FRACTIONAL_POSITION_FIELDS[col_name]
        pos, lengths_text = _split_position_and_lengths(cleaned, field_size)
        bl = decode_beaten_lengths(lengths_text) if pos is not None else None
        return {pos_field: pos, beaten_field: bl}

    if col_name == "Odds":
        cl = cleaned.replace("|", " ").strip()
        was_fav = "*" in cl
        # take first whitespace-separated token, sans '*'
        token = cl.replace("*", "").strip().split()
        try:
            odds = float(token[0]) if token else None
        except ValueError:
            odds = None
        return {"final_odds": odds, "was_favorite": was_fav}

    if col_name == "Comments":
        return {"comment": cleaned or None}

    # Unknown column — passthrough so we can see what we missed.
    return {f"raw_{col_name}": cleaned}


# ===========================================================================
# Phase 4D — pace classifier (STUB — see P4-NEW-OBS-1)
# ===========================================================================
def classify_pace_scenario(fractional_times_seconds, distance_feet):
    """
    Classify a race's pace as 'HOT' / 'MIXED' / 'SLOW' based on chart-side
    fractional times. PLACEHOLDER — currently returns None.

    Why a stub: horse_racing_scorer.py's pace classifier (which the Phase 4
    spec asks to port) takes a list of BRIS Run Style codes from past-
    performances PPs (E / E/P / P / S / NA) and counts them to label the
    field's pre-race pace shape. It does not consume fractional times.

    A fractional-time-based classifier needs different inputs (par times
    by distance/surface, baseline thresholds, possibly a simple "opening
    quarter delta vs par" rule) and a definition that's coherent with the
    rest of the engine. That definition is not yet captured anywhere.

    Until that's resolved (see P4-NEW-OBS-1), parse_race emits
    pace_scenario=None and the bettor or downstream scorer has to fill it
    in from a separate pre-race pace input.
    """
    _ = (fractional_times_seconds, distance_feet)  # silence unused-arg lint
    return None


# ===========================================================================
# Phase 4E — extract_race_metadata
# ===========================================================================
# Race-header pattern used by parse_chart_pdf to find race boundaries.
# Allows < and > in the track-name capture so the stray Equibase decoration
# glyph (P1-NEW-OBSERVATION) doesn't terminate the match. The track name
# is normalized (whitespace collapsed) before being stored at the top level.
RACE_HEADER_PATTERN = re.compile(
    r"(?P<track>[A-Z][A-Z\s<>]+?)\s*-\s*"
    r"(?P<date>[A-Z][a-z]+\s+\d+,\s+\d{4})\s*-\s*"
    r"Race\s+(?P<race_num>\d+)"
)


TRACK_DATE_RACENO_PATTERN = re.compile(
    # The track-name capture allows < and > so a stray Equibase decoration
    # glyph in the title (P1-NEW-OBSERVATION) doesn't prematurely terminate
    # the match. The post-processor in extract_race_metadata strips them.
    r"([A-Z][A-Z\s<>]+?)\s*-\s*([A-Za-z]+\s+\d+,\s*\d{4})\s*-\s*Race\s+(\d+)"
)
DISTANCE_LINE_PATTERN = re.compile(r"Distance:\s*([^\n|]+)", re.IGNORECASE)
TRACK_CONDITION_PATTERN = re.compile(r"Track:\s*([A-Za-z]+)")
FRACTIONAL_TIMES_PATTERN = re.compile(
    # Allow pipes inside the captured run — convert_to_text emits them
    # between adjacent fractional times because the column-spacing exceeds
    # MAX_SPACE_THRESHOLD. The TIME_TOKEN_PATTERN below tokenizes around them.
    r"Fractional Times[:\s]*([\d:.\s|]+)", re.IGNORECASE
)
FINAL_TIME_PATTERN = re.compile(
    r"Final Time[:\s]*(\d+:\d+\.\d+|\d+\.\d+)", re.IGNORECASE
)
TIME_TOKEN_PATTERN = re.compile(r"\d+:\d+\.\d+|\d+\.\d+")


def _time_token_to_seconds(token):
    if ":" in token:
        mm, ss = token.split(":", 1)
        return int(mm) * 60 + float(ss)
    return float(token)


def extract_race_metadata(rows):
    """
    Scan the row list for race metadata. Tolerates the convert_to_text
    artifacts (pipes from internal spacing, extra newlines from stray
    glyphs).

    Returns a dict with the following keys (any of which may be None or []
    if not detected):
        track, race_date, race_number, distance_text, distance_feet,
        surface, track_condition, fractional_times_seconds.

    race_type is intentionally not extracted at this phase — it's a
    multi-line field with substantial variation; Phase 5 can add it.
    """
    # Per-row convert_to_text may emit internal \n when a stray glyph
    # exceeds the pairwise newline threshold (4) but row clustering kept
    # it in the row at tolerance 5. Collapse those internal newlines to
    # spaces so regexes that expect single-line headers (e.g. the title
    # "CHURCHILL DOWNS - May 2, 2026 - Race 1") still match.
    def _line(r):
        return convert_to_text(r).replace("\n", " ").strip()
    full_text = "\n".join(_line(r) for r in rows if r)

    metadata = {
        "track": None,
        "race_date": None,
        "race_number": None,
        "distance_text": None,
        "distance_feet": None,
        "surface": None,
        "track_condition": None,
        "fractional_times_seconds": [],
        "final_time_seconds": None,
    }

    m = TRACK_DATE_RACENO_PATTERN.search(full_text)
    if m:
        # P4-NEW-OBS-4: stray decoration glyphs in title (the < at top=30.04
        # in the Churchill chart) introduce extra whitespace into the matched
        # group. Strip non-alphanumeric tokens and collapse whitespace so the
        # track name reads cleanly. Best-effort — won't perfectly recover
        # words split by overlapping glyphs, but produces "CHURCHILL DOWNS"
        # close enough for downstream identification.
        track_raw = m.group(1)
        track_clean = re.sub(r"[^A-Za-z\s]", " ", track_raw)
        track_clean = re.sub(r"\s+", " ", track_clean).strip()
        metadata["track"] = _normalize_track_name(track_clean)
        metadata["race_date"] = m.group(2).strip()
        try:
            metadata["race_number"] = int(m.group(3))
        except ValueError:
            pass

    dm = DISTANCE_LINE_PATTERN.search(full_text)
    if dm:
        dist_full = dm.group(1)
        # Distance text — find longest matching key in DISTANCE_TEXT_TO_FEET.
        # Sort keys by length descending so "One And One Sixteenth Miles"
        # matches before "One Mile".
        for k in sorted(DISTANCE_TEXT_TO_FEET.keys(), key=len, reverse=True):
            if k in dist_full:
                metadata["distance_text"] = k
                metadata["distance_feet"] = DISTANCE_TEXT_TO_FEET[k]
                break
        # Surface — first matching phrase wins (phrases ordered most-specific-first).
        for phrase, equibase_key in SURFACE_PHRASES:
            if phrase in dist_full:
                metadata["surface"] = SURFACE_MAP.get(equibase_key, equibase_key)
                break

    tc = TRACK_CONDITION_PATTERN.search(full_text)
    if tc:
        metadata["track_condition"] = tc.group(1).strip()

    ft = FRACTIONAL_TIMES_PATTERN.search(full_text)
    if ft:
        ft_text = ft.group(1)
        metadata["fractional_times_seconds"] = [
            _time_token_to_seconds(t) for t in TIME_TOKEN_PATTERN.findall(ft_text)
        ]

    fnt = FINAL_TIME_PATTERN.search(full_text)
    if fnt:
        metadata["final_time_seconds"] = _time_token_to_seconds(fnt.group(1))

    return metadata


# ===========================================================================
# Phase 7B.3 — Trainer / winning-manner extraction
# ===========================================================================
TRAINERS_SECTION_START_PATTERN = re.compile(r"^Trainers\s*:", re.IGNORECASE)
TRAINER_ENTRY_PATTERN = re.compile(r"^\s*([A-Za-z0-9]+)\s*-\s*(.+?)\s*$")
TRAINERS_SECTION_END_PATTERNS = re.compile(
    r"^(Owners|Footnotes|Breeder|Scratched|Total|Pgm\b|Copyright|Denotes)",
    re.IGNORECASE,
)

# Winning-manner descriptors — case-insensitive, matched against the
# footnotes / narrative block. First match wins.
WINNING_MANNER_PATTERNS = re.compile(
    r"\b("
    r"drew\s+(?:away|clear|off|out|in front)|"
    r"prevailed|"
    r"ridden out|"
    r"hard ridden|"
    r"all out|"
    r"under a (?:brisk )?drive|"
    r"driving|"
    r"easily|"
    r"handily|"
    r"in hand|"
    r"comfortably|"
    r"rallied (?:wide|widest)?\s*(?:to (?:win|prevail))?"
    r")\b",
    re.IGNORECASE,
)


def _extract_trainer_block(rows):
    """
    Return {program_number: trainer_name} parsed from the chart's
    multi-line "Trainers:" section.

    Equibase format (across one or more lines):
        Trainers: 19 - DeVaux, Cherie; 1 - Pletcher, Todd; 22 - Beckman, ...

    The block starts at a row whose text begins with "Trainers:" and
    continues across continuation rows (no leading section keyword) until
    the next section (Owners:, Footnotes, Breeder:, etc.) begins.

    Trainer names contain commas (suffixes like "Jr.", initials like "D. Whitworth").
    Splitting on ";" preserves the "Last, First" format intact.
    """
    out = {}
    in_block = False
    block_parts = []
    for row in rows:
        text = convert_to_text(row).replace("\n", " ")
        if not in_block:
            if TRAINERS_SECTION_START_PATTERN.match(text):
                in_block = True
                # strip the "Trainers:" prefix
                stripped = TRAINERS_SECTION_START_PATTERN.sub("", text, count=1)
                block_parts.append(stripped)
            continue
        # in block — stop at next section
        if TRAINERS_SECTION_END_PATTERNS.match(text):
            break
        block_parts.append(text)
    if not block_parts:
        return out

    # Pipes inside the convert_to_text rendering are convert_to_text
    # column-spacing artifacts — collapse to spaces.
    full = " ".join(block_parts).replace("|", " ")
    full = re.sub(r"\s+", " ", full).strip()
    for entry in full.split(";"):
        m = TRAINER_ENTRY_PATTERN.match(entry.strip())
        if m:
            pgm = m.group(1).strip()
            name = m.group(2).strip()
            if pgm and name:
                out[pgm] = name
    return out


def _extract_winning_manner(rows):
    """
    Scan the footnotes/narrative block for a winning-manner descriptor.
    Returns the first match (lowercased) or None.

    Equibase footnotes always begin with the winner's name in ALL CAPS
    followed by a verb-laden recap. Examples observed:
        "POWERSHIFT stalked the pace ... drew away late under a brisk drive."
        "GOLDEN TEMPO bumped with ... prevailed."
    """
    for row in rows:
        text = convert_to_text(row).replace("\n", " ")
        m = WINNING_MANNER_PATTERNS.search(text)
        if m:
            return m.group(1).lower()
    return None


# ===========================================================================
# Phase 7A — call-point beaten-lengths transformation
# ===========================================================================
def _convert_call_lengths_to_from_leader(horses):
    """
    Convert beaten_lengths_q1/q2/q3/str from cell-format (gap-from-prior-horse)
    to lengths-from-leader at each call point. Mirrors what already happens
    for beaten_lengths_finish (P4-NEW-OBS-5), so all beaten-lengths fields
    on a horse_race_calls row share consistent semantics ("how far behind
    the leader was this horse at this point").

    Cell-format raw values are preserved as bl_q1_raw, bl_q2_raw, bl_q3_raw,
    bl_str_raw before the conversion overwrites the main fields.

    P6-NEW-OBS-1 motivated this fix: the classifier's late-gain formula
    (closing_move = bl_q3 - bl_fn) needs both fields in lengths-from-leader
    semantics to produce a meaningful magnitude.

    Mutates `horses` in place.
    """
    call_field_pairs = (
        ("pos_q1",       "beaten_lengths_q1",       "bl_q1_raw"),
        ("pos_q2",       "beaten_lengths_q2",       "bl_q2_raw"),
        ("pos_q3",       "beaten_lengths_q3",       "bl_q3_raw"),
        ("pos_one_mile", "beaten_lengths_one_mile", "bl_one_mile_raw"),
        ("pos_str",      "beaten_lengths_str",      "bl_str_raw"),
    )
    for pos_field, bl_field, raw_field in call_field_pairs:
        # Preserve raw cell-format value on every horse before conversion.
        for h in horses:
            h[raw_field] = h.get(bl_field)

        sorted_h = sorted(
            [h for h in horses if h.get(pos_field) is not None],
            key=lambda h: h[pos_field],
        )
        if not sorted_h:
            continue

        cumulative = 0.0
        for i, h in enumerate(sorted_h):
            raw = h.get(bl_field) or 0.0
            if i == 0:
                # Leader at this call point: 0 lengths from leader by definition.
                h[bl_field] = 0.0
            else:
                cumulative += raw
                h[bl_field] = cumulative


# ===========================================================================
# Phase 4F — parse_race orchestration
# ===========================================================================
def parse_race(rows, race_metadata=None):
    """
    Assemble one race's structured dict from its rows.

    Inputs
    ------
    rows : list of grouped-and-sorted rows (output of group_chars_by_row)
           that contain the race's running line plus metadata. Typically
           one or two pages' worth of rows passed by the Phase 5 caller.
    race_metadata : optional pre-extracted metadata dict; if None, this
           function calls extract_race_metadata(rows) itself.

    Returns
    -------
    dict matching the schema in Chart_Parser_Technical_Reference.md, or
    None if the race header / running-line block could not be located.
    """
    header = identify_header_row(rows)
    if header is None:
        log.warning("parse_race: no header row found")
        return None

    header_map = build_column_map(header)
    column_map = recalibrate_column_map(rows, header, header_map)
    running_line_rows = extract_running_line_rows(rows, header)

    if not running_line_rows:
        log.warning("parse_race: no running-line rows after header")

    field_size = len(running_line_rows)
    horses = []
    for row in running_line_rows:
        cell_groups = group_row_chars_by_column(row, column_map)
        horse = {}
        for col_name, cell_chars in cell_groups.items():
            cell_text = convert_to_text(cell_chars) if cell_chars else ""
            horse.update(decode_running_line_cell(col_name, cell_text, field_size))
        horses.append(horse)

    # Row-index override for finish_position. The Equibase running line is
    # ordered by official finish, so the i-th row's finish_position is i+1.
    # Cell-parsed finish_position is preserved as finish_position_from_cell
    # for audit. Fixes ambiguity in cells like "11/2" (pos=1 lengths=1.5
    # vs pos=11 lengths=incomplete) and DNF/scratched markers like "---"
    # that produce None. P5-NEW-OBS-2.
    for i, h in enumerate(horses):
        cell_pos = h.get("finish_position")
        canonical = i + 1
        h["finish_position_from_cell"] = cell_pos
        if cell_pos != canonical:
            log.debug(
                "parse_race: finish_position override row=%d cell=%r row_order=%d",
                i, cell_pos, canonical,
            )
        h["finish_position"] = canonical

    if race_metadata is None:
        race_metadata = extract_race_metadata(rows)

    race = dict(race_metadata)
    race["horses"] = horses
    race["field_size"] = len(horses)
    race["pace_scenario"] = classify_pace_scenario(
        race_metadata.get("fractional_times_seconds") or [],
        race_metadata.get("distance_feet"),
    )

    # Convert beaten_lengths_q1/q2/q3/str from cell-format to lengths-from-leader
    # at each call point (P7A — see _convert_call_lengths_to_from_leader docstring).
    # This must happen BEFORE the from-winner conversion below; the two work on
    # disjoint fields but reading the function call order top-down is clearer
    # if call-points come first.
    _convert_call_lengths_to_from_leader(horses)

    # Convert beaten_lengths_finish from cell-format to "lengths-behind-winner"
    # semantics. Equibase's Fin column stores the lead margin for the winner
    # and the gap-from-the-prior-horse for non-winners. Downstream EDGE
    # logic wants a single normalized "lengths behind winner" number where
    # the winner is 0.0. P4-NEW-OBS-5.
    horses_by_finish = sorted(
        [h for h in horses if h.get("finish_position") is not None],
        key=lambda h: h["finish_position"],
    )
    cumulative = 0.0
    for i, h in enumerate(horses_by_finish):
        raw = h.get("beaten_lengths_finish") or 0.0
        if i == 0:
            # Winner: preserve the winning margin in a separate field, set
            # beaten_lengths_finish = 0 (canonical "winner has zero behind").
            h["winning_margin_lengths"] = raw
            h["beaten_lengths_finish"] = 0.0
        else:
            cumulative += raw
            h["beaten_lengths_finish"] = cumulative

    # Derived final_time_seconds for non-winners. Winner's time comes
    # from the chart's "Final Time:" line (P4-NEW-OBS-8). Each non-winner's
    # time = winner_time + (lengths-behind * 0.2).
    winner_time = race_metadata.get("final_time_seconds")
    race["final_time_seconds"] = winner_time
    if winner_time is None:
        # Fallback to last fractional if Final Time not detected (rare).
        fts = race_metadata.get("fractional_times_seconds") or []
        winner_time = fts[-1] if fts else None
    if winner_time is not None:
        for h in horses:
            bl = h.get("beaten_lengths_finish")
            if bl is None:
                h["final_time_seconds"] = None
            else:
                h["final_time_seconds"] = winner_time + bl * 0.2
    else:
        for h in horses:
            h["final_time_seconds"] = None

    # Phase 7B.3 — trainer per horse, winning_manner at race level.
    trainers_by_pgm = _extract_trainer_block(rows)
    if trainers_by_pgm:
        for h in horses:
            pgm = h.get("program_number")
            if pgm is not None and str(pgm) in trainers_by_pgm:
                h["trainer"] = trainers_by_pgm[str(pgm)]
    race["winning_manner"] = _extract_winning_manner(rows)

    return race


# ===========================================================================
# Phase 5A — parse_chart_pdf (multi-race orchestrator)
# ===========================================================================
def _find_race_header_indices(rows):
    """Return list of (row_index, race_number) for each row that matches the
    race-header pattern "<TRACK> - <Month Day, Year> - Race N"."""
    out = []
    for i, row in enumerate(rows):
        line = convert_to_text(row).replace("\n", " ")
        m = RACE_HEADER_PATTERN.search(line)
        if m:
            try:
                out.append((i, int(m.group("race_num"))))
            except ValueError:
                continue
    return out


def parse_chart_pdf(pdf_path):
    """
    Public API entry point. Parse a multi-race Equibase Full Chart PDF.

    Algorithm:
      1. Extract chars across all pages, page-aware row clustering.
      2. Find race-header rows via RACE_HEADER_PATTERN.
      3. Slice rows for each race (header_idx[k] .. header_idx[k+1]).
      4. Run parse_race(slice) per race; ERRORS in one race do not
         block others.
      5. Aggregate to {track, race_date (ISO), races}.

    Track-name normalization (P4-NEW-OBS-4): the stray-glyph artifact in
    title rows can leave internal multi-space residue ("CHUR CHILL DOWNS").
    The race-level metadata strips non-alpha chars and collapses whitespace;
    the top-level `track` field uses the cleaned value from the first race
    that produced one.

    Date normalization: extract_race_metadata captures the date in human
    form ("May 2, 2026"); this function converts to ISO ("2026-05-02").

    Returns None if the PDF can't be opened or no race headers are found.
    """
    chars = extract_chars(pdf_path)
    if not chars:
        log.error("parse_chart_pdf: extract_chars returned empty for %s", pdf_path)
        return None

    rows = group_chars_by_row(chars)
    if not rows:
        log.error("parse_chart_pdf: no rows after grouping")
        return None

    race_starts = _find_race_header_indices(rows)
    if not race_starts:
        log.error("parse_chart_pdf: no race headers found in %s", pdf_path)
        return None

    log.info("parse_chart_pdf: found %d race headers", len(race_starts))

    races = []
    track_name = None
    race_date_iso = None

    from datetime import datetime as _dt

    for k, (start_idx, race_num) in enumerate(race_starts):
        end_idx = race_starts[k + 1][0] if k + 1 < len(race_starts) else len(rows)
        race_rows = rows[start_idx:end_idx]
        try:
            race_dict = parse_race(race_rows)
        except Exception as exc:  # noqa: BLE001
            log.error("parse_chart_pdf: parse_race(race %d) raised: %s", race_num, exc)
            continue
        if race_dict is None:
            log.error("parse_chart_pdf: parse_race(race %d) returned None", race_num)
            continue

        # Authoritative race_number from the header pattern.
        race_dict["race_number"] = race_num

        # Capture top-level metadata once, normalized + alias-applied.
        if track_name is None and race_dict.get("track"):
            collapsed = re.sub(r"\s+", " ", race_dict["track"]).strip()
            track_name = _normalize_track_name(collapsed)
        if race_date_iso is None and race_dict.get("race_date"):
            try:
                dt = _dt.strptime(race_dict["race_date"], "%B %d, %Y")
                race_date_iso = dt.strftime("%Y-%m-%d")
            except ValueError:
                log.warning(
                    "parse_chart_pdf: race_date %r doesn't match %%B %%d, %%Y",
                    race_dict["race_date"],
                )

        races.append(race_dict)

    # P7B.4 — every race in a chart is at the same track. Override per-race
    # `track` with the canonical top-level value so stray-glyph artifacts on
    # individual page titles don't leave each race with a different mangled
    # track string.
    if track_name:
        for race in races:
            race["track"] = track_name

    return {
        "track": track_name,
        "race_date": race_date_iso,
        "races": races,
    }


# ===========================================================================
# Self-test (Phases 1 + 2 + 3 + 4 + 5)
# ===========================================================================
if __name__ == "__main__":
    import sys
    from collections import Counter

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    DEFAULT_SAMPLE_PDF = (
        Path(__file__).parent / "horse_racing_data" / "ARP_2016-07-24_race-charts.pdf"
    )
    SAMPLE_PDF_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE_PDF

    if not SAMPLE_PDF_PATH.exists():
        print(f"[Phase 1 self-test] Sample PDF not found at {SAMPLE_PDF_PATH}.", file=sys.stderr)
        sys.exit(2)

    print(f"[Phase 1 self-test] Sample: {SAMPLE_PDF_PATH}")

    chars = extract_chars(SAMPLE_PDF_PATH)
    page_count = max((c["page_number"] for c in chars), default=0)
    print(f"[Phase 1 self-test] Total chars: {len(chars):,}")
    print(f"[Phase 1 self-test] Pages:       {page_count}")
    text_p1 = convert_to_text(chars[:200])
    print("\n[Phase 1 self-test] convert_to_text(chars[:200]) ->")
    print("-" * 72)
    print(text_p1)
    print("-" * 72)
    coords_ok = (
        all(0 <= c["x0"] <= 800 for c in chars[:200])
        and all(0 <= c["top"] <= 1100 for c in chars[:200])
    )
    text_ok = "\n" in text_p1 and any(ch.isalpha() for ch in text_p1)
    print(f"[Phase 1 self-test] coords_ok={coords_ok}  text_ok={text_ok}")
    if not (coords_ok and text_ok):
        print("[Phase 1 self-test] FAILED.", file=sys.stderr)
        sys.exit(1)
    print("[Phase 1 self-test] PASSED.")

    # Phase 2
    chars_p1 = [c for c in chars if c["page_number"] == 1]
    rows_p1 = group_chars_by_row(chars_p1)
    print(f"\n[Phase 2 self-test] Page 1 rows: {len(rows_p1)}")
    header_p1 = identify_header_row(rows_p1)
    header_map_p1 = build_column_map(header_p1) if header_p1 else {}
    print(f"[Phase 2 self-test] Header columns: {len(header_map_p1)}")
    print("[Phase 2 self-test] PASSED.")

    # Phase 3 — pure decoder spot checks (full battery already validated last phase)
    assert decode_beaten_lengths("1 1/2") == 1.5
    assert decode_position_cell("11|P") == 11
    assert decode_horse_jockey_cell("Powershift (Ortiz, Jr., Irad)") == ("Powershift", "Ortiz, Jr., Irad")
    print("\n[Phase 3 self-test] Spot checks PASSED.")

    # ------------------------------------------------------------------
    # Phase 4 self-test — Race 1 assembly
    # ------------------------------------------------------------------
    print("\n[Phase 4 self-test] Race 1 assembly")

    race_1_chars = [c for c in chars if c["page_number"] in (1, 2)]
    race_1_rows = group_chars_by_row(race_1_chars)
    print(f"[Phase 4 self-test] Race 1 char count (pages 1-2): {len(race_1_chars)}")
    print(f"[Phase 4 self-test] Race 1 row count: {len(race_1_rows)}")

    header = identify_header_row(race_1_rows)
    if header is None:
        print("[Phase 4 self-test] FAIL: no header detected")
        sys.exit(1)

    header_map = build_column_map(header)
    column_map = recalibrate_column_map(race_1_rows, header, header_map)

    print("\n[Phase 4 self-test] Header column map vs calibrated:")
    for col_name in sorted(header_map.keys(), key=lambda c: header_map[c]):
        delta = column_map[col_name] - header_map[col_name]
        print(
            f"    {col_name!r:>22}  header={header_map[col_name]:7.2f}  "
            f"calibrated={column_map[col_name]:7.2f}  delta={delta:+6.2f}"
        )

    running_line_rows = extract_running_line_rows(race_1_rows, header)
    print(f"\n[Phase 4 self-test] Running-line rows: {len(running_line_rows)}")

    metadata = extract_race_metadata(race_1_rows)
    print("\n[Phase 4 self-test] Race metadata:")
    for k, v in metadata.items():
        print(f"    {k!r:>22} = {v!r}")

    # Decode every horse using the calibrated map
    field_size = len(running_line_rows)
    horses = []
    for row in running_line_rows:
        cell_groups = group_row_chars_by_column(row, column_map)
        horse = {}
        for col_name, cell_chars in cell_groups.items():
            cell_text = convert_to_text(cell_chars) if cell_chars else ""
            horse.update(decode_running_line_cell(col_name, cell_text, field_size))
        horses.append(horse)

    # Row-index override for finish_position. The Equibase running line is
    # ordered by official finish, so the i-th row's finish_position is i+1.
    # Cell-parsed finish_position is preserved as finish_position_from_cell
    # for audit. Fixes ambiguity in cells like "11/2" (pos=1 lengths=1.5
    # vs pos=11 lengths=incomplete) and DNF/scratched markers like "---"
    # that produce None. P5-NEW-OBS-2.
    for i, h in enumerate(horses):
        cell_pos = h.get("finish_position")
        canonical = i + 1
        h["finish_position_from_cell"] = cell_pos
        if cell_pos != canonical:
            log.debug(
                "parse_race: finish_position override row=%d cell=%r row_order=%d",
                i, cell_pos, canonical,
            )
        h["finish_position"] = canonical

    print(f"\n[Phase 4 self-test] Decoded {len(horses)} horses. First horse:")
    for k, v in horses[0].items():
        print(f"    {k!r:>22} = {v!r}")

    print(
        f"\n[Phase 4 self-test] All horses summary "
        f"(finish_position, horse_name, beaten_lengths_finish, jockey):"
    )
    for h in horses:
        print(
            f"    {h.get('finish_position', '?')!s:>3}  "
            f"{(h.get('horse_name') or '?'):<30}  "
            f"beaten={h.get('beaten_lengths_finish')!s:<5}  "
            f"jockey={h.get('jockey') or '?'}"
        )

    # Now exercise the orchestrator end-to-end to confirm parse_race
    # produces the schema-shaped dict with horses + derived final_time_seconds.
    print("\n[Phase 4 self-test] parse_race(race_1_rows) result skeleton:")
    race = parse_race(race_1_rows)
    if race is None:
        print("    parse_race returned None — see warnings above")
    else:
        scalars = {k: v for k, v in race.items() if k != "horses"}
        for k, v in scalars.items():
            print(f"    {k!r:>22} = {v!r}")
        print(f"    {'horses[0]':>22} = (showing field_size={race['field_size']} horses)")
        if race["horses"]:
            print(
                f"\n[Phase 4 self-test] parse_race output (post-conversion) per horse:"
            )
            for h in race["horses"]:
                print(
                    f"    finish={h.get('finish_position'):>2}  "
                    f"{(h.get('horse_name') or '?'):<30}  "
                    f"beaten_from_winner={h.get('beaten_lengths_finish'):<6}  "
                    f"final_time_s={h.get('final_time_seconds')!s:<6}"
                )

    # ------------------------------------------------------------------
    # Phase 4 self-validation — uses parse_race output so the
    # cell-format -> lengths-from-winner conversion has been applied.
    # ------------------------------------------------------------------
    failures = []
    race_horses = (race or {}).get("horses") or []
    if not race_horses:
        failures.append("no horses in parse_race output")
    else:
        first = race_horses[0]
        if not first.get("horse_name"):
            failures.append("first horse has no horse_name")
        elif first["horse_name"] == "owershift":
            failures.append("first horse name is 'owershift' — calibration did NOT eliminate bleed")
        if first.get("finish_position") is None:
            failures.append("first horse has no finish_position")
        # Winner check: the horse with finish_position == 1 should have
        # beaten_lengths_finish == 0.0 (post-conversion semantics).
        winners = [h for h in race_horses if h.get("finish_position") == 1]
        if not winners:
            failures.append("no horse with finish_position == 1 in race output")
        elif winners[0].get("beaten_lengths_finish") != 0.0:
            failures.append(
                f"winner has beaten_lengths_finish={winners[0].get('beaten_lengths_finish')!r} (expected 0.0)"
            )
        # Every horse should have horse_name and finish_position
        for i, h in enumerate(race_horses):
            if not h.get("horse_name"):
                failures.append(f"horse[{i}] missing horse_name")
            if h.get("finish_position") is None:
                failures.append(f"horse[{i}] missing finish_position")
        # Finish positions should be unique 1..N (no duplicate winners).
        finishes = [h.get("finish_position") for h in race_horses]
        if len(set(finishes)) != len(finishes):
            dups = [f for f in set(finishes) if finishes.count(f) > 1]
            failures.append(f"duplicate finish_position values: {dups}")

    if failures:
        print("\n[Phase 4 self-test] FAILURES:")
        for f in failures:
            print(f"    - {f}")
        sys.exit(1)
    else:
        print("\n[Phase 4 self-test] PASSED.")

    # ------------------------------------------------------------------
    # Phase 5A self-test — full multi-race parse
    # ------------------------------------------------------------------
    print("\n[Phase 5A self-test] Full multi-race parse")
    result = parse_chart_pdf(SAMPLE_PDF_PATH)
    if result is None:
        print("[Phase 5A self-test] FAIL: parse_chart_pdf returned None")
        sys.exit(1)

    print(f"[Phase 5A self-test] Track:      {result['track']!r}")
    print(f"[Phase 5A self-test] Date:       {result['race_date']!r}")
    print(f"[Phase 5A self-test] Race count: {len(result['races'])}")

    print(f"\n[Phase 5A self-test] Per-race summary:")
    print(
        f"  {'#':>3}  {'distance':>8}  {'surf':>4}  {'cond':>8}  "
        f"{'horses':>6}  {'winner':<25}  {'time':>7}"
    )
    for race in result["races"]:
        winner = next(
            (h for h in race["horses"] if h.get("finish_position") == 1), None
        )
        winner_name = (winner or {}).get("horse_name") or "?"
        ft = race.get("final_time_seconds")
        ft_str = f"{ft:.2f}" if isinstance(ft, (int, float)) else "?"
        print(
            f"  {race['race_number']:>3}  "
            f"{race.get('distance_feet','?')!s:>8}  "
            f"{race.get('surface','?')!s:>4}  "
            f"{race.get('track_condition','?')!s:>8}  "
            f"{race.get('field_size','?')!s:>6}  "
            f"{winner_name:<25}  "
            f"{ft_str:>7}"
        )

    # Validate
    print(f"\n[Phase 5A self-test] Position sequence validation:")
    p5_failures = []
    for race in result["races"]:
        positions = sorted(
            (h.get("finish_position") or 0) for h in race["horses"]
        )
        expected = list(range(1, len(positions) + 1))
        is_contiguous = positions == expected
        flag = "" if is_contiguous else "  <-- NON-CONTIGUOUS"
        print(f"  Race {race['race_number']:>2}: positions {positions} {flag}")
        if not is_contiguous:
            p5_failures.append(
                f"Race {race['race_number']} positions {positions} not contiguous 1..{len(positions)}"
            )

    field_size_oddities = []
    for race in result["races"]:
        fs = race.get("field_size", 0)
        # Equibase records the actual starter count. 2-horse races are rare
        # but legal (heavy scratches). Cap is the historical Derby max of 20.
        if fs < 2 or fs > 20:
            field_size_oddities.append(f"Race {race['race_number']} field_size={fs}")

    missing_final_time = [
        r["race_number"] for r in result["races"]
        if r.get("final_time_seconds") is None
    ]

    print(
        f"\n[Phase 5A self-test] Total races: {len(result['races'])}, "
        f"races missing final_time_seconds: {missing_final_time}, "
        f"field-size oddities: {field_size_oddities}"
    )

    derby_race = next((r for r in result["races"] if r["race_number"] == 12), None)
    if derby_race:
        print(
            f"[Phase 5A self-test] Race 12 (Derby) field_size = "
            f"{derby_race.get('field_size')}"
        )

    if len(result["races"]) != 14:
        p5_failures.append(f"expected 14 races, got {len(result['races'])}")
    if missing_final_time:
        p5_failures.append(f"missing final_time_seconds: {missing_final_time}")
    if field_size_oddities:
        p5_failures.append(f"field-size oddities: {field_size_oddities}")

    if p5_failures:
        print("\n[Phase 5A self-test] FAILURES:")
        for f in p5_failures:
            print(f"    - {f}")
        sys.exit(1)
    print("[Phase 5A self-test] PASSED.")
