"""
results_fetcher.py — EDGE Intelligence Platform
Parses Brisnet Instant Results HTML files (and optional Import Results CSVs)
to auto-grade races by closing the loop into horse_racing_grader.grade_race().

Usage:
    python results_fetcher.py                          # scan horse_racing_data/ for all new *_results.html
    python results_fetcher.py path/to/FILE_results.html
    python results_fetcher.py path/to/FILE_results.csv
"""

import os
import re
import sys
import sqlite3
from datetime import datetime
from pathlib import Path
from db_utils import safe_write

# ---------------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------------

SCRIPT_DIR   = Path(__file__).parent
DATA_DIR     = SCRIPT_DIR / "horse_racing_data"
GRADE_LOG    = DATA_DIR / "graded_results.log"

# ---------------------------------------------------------------------------
# BRISNET RESULTS URL + TRACK CODE MAP
# ---------------------------------------------------------------------------

BRISNET_RESULTS_URL = "https://www.brisnet.com/product/download/{date}/INR/USA/TB/{track}/D/0/"

# Maps DRF filename track codes → Brisnet results page track codes
TRACK_CODE_MAP = {
    'GPX': 'GP',    # Gulfstream Park (GPX was old Calder code)
    'OPX': 'OP',    # Oaklawn Park (DRF alternate code)
    'GP':  'GP',    # Gulfstream Park direct
    'MVR': 'MVR',   # Mahoning Valley
    'KEE': 'KEE',   # Keeneland
    'CD':  'CD',    # Churchill Downs
    'SA':  'SA',    # Santa Anita
    'SAR': 'SAR',   # Saratoga
    'BEL': 'BEL',   # Belmont
    'AQU': 'AQU',   # Aqueduct
    'DMR': 'DMR',   # Del Mar
    'FG':  'FG',    # Fair Grounds
    'TAM': 'TAM',   # Tampa Bay Downs
    'TP':  'TP',    # Turfway Park
    'LRL': 'LRL',   # Laurel
    'PIM': 'PIM',   # Pimlico
    'OP':  'OP',    # Oaklawn
    'TTP': 'TP',    # Turfway Park alternate
}

# ---------------------------------------------------------------------------
# SAFE IMPORTS
# ---------------------------------------------------------------------------

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: beautifulsoup4 is not installed.")
    print("Fix: pip install beautifulsoup4")
    sys.exit(1)

try:
    from horse_racing_grader import grade_race
except ImportError as exc:
    print(f"ERROR: Could not import horse_racing_grader: {exc}")
    print("Ensure horse_racing_grader.py is in the same directory.")
    sys.exit(1)


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def build_results_url(track_code, race_date):
    """
    Build the direct Brisnet Instant Results URL for a given track and date.

    Args:
        track_code (str): DRF filename track code e.g. 'GPX', 'MVR', 'KEE'
        race_date (str): Date in YYYYMMDD format e.g. '20260405'

    Returns:
        tuple: (url, brisnet_track_code)
            url (str): Full Brisnet results URL ready to navigate
            brisnet_track_code (str): The mapped track code used in URL

    Example:
        url, code = build_results_url('GPX', '20260405')
        # url = 'https://www.brisnet.com/product/download/2026-04-05/INR/USA/TB/GP/D/0/'
        # code = 'GP'
    """
    brisnet_code   = TRACK_CODE_MAP.get(track_code.upper(), track_code.upper())
    date_formatted = f"{race_date[:4]}-{race_date[4:6]}-{race_date[6:8]}"
    url            = BRISNET_RESULTS_URL.format(date=date_formatted, track=brisnet_code)
    return url, brisnet_code


def _parse_track_and_date(filename: str):
    """
    Extract track code and race date (YYYYMMDD) from a filename like:
        GPX0407_results.html   → track='GPX', date='20260407'
        MVR0407_results.html   → track='MVR', date='20260407'
    Track code = leading uppercase letters before the first digit group.
    Date       = MMDD digits, prepended with current year.
    """
    stem = Path(filename).stem  # e.g. 'GPX0407_results'
    m = re.match(r'^([A-Za-z]+)(\d{4})', stem)
    if not m:
        return None, None
    track_code = m.group(1).upper()
    mmdd       = m.group(2)
    year       = datetime.now().year
    race_date  = f"{year}{mmdd}"
    return track_code, race_date


def _safe_float(text: str) -> float:
    """Strip $, commas, whitespace and convert to float. Returns 0.0 on failure."""
    if not text:
        return 0.0
    clean = re.sub(r'[$,\s]', '', text.strip())
    try:
        return float(clean)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# FUNCTION 1 — parse_results_file
# ---------------------------------------------------------------------------

def parse_results_file(filepath: str) -> dict:
    """
    Parse a saved Brisnet Instant Results HTML file.

    Supports two formats:
      A) Real Brisnet INR format — race headers like "1st Race - Track - Date",
         finish order in <table> rows (first data row = winner), Win/Place/Show
         as column headers with payoffs in the winner row cells.
      B) Test / legacy format — race headers like "Race 1", position markers
         "1. Horse Name" or "1." then name on next line.

    Returns a dict:
        {
            'track_code': str,
            'race_date':  str (YYYYMMDD),
            'races': [
                {
                    'race_number':  int,
                    'finish_order': [str, ...],   # horse names 1st → last
                    'win_payoff':   float,
                    'place_payoff': float,
                    'show_payoff':  float,
                    'scratches':    [str, ...],
                    'conditions':   str,
                },
                ...
            ]
        }
    """
    filepath = Path(filepath)
    track_code, race_date = _parse_track_and_date(filepath.name)
    if not track_code:
        print(f"WARNING: Could not parse track/date from filename: {filepath.name}")
        track_code = "UNK"
        race_date  = datetime.now().strftime("%Y%m%d")

    with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
        html = fh.read()

    soup = BeautifulSoup(html, 'html.parser')

    # -----------------------------------------------------------------------
    # Detect format: real Brisnet uses ordinal headers like "1st Race", "2nd Race"
    # -----------------------------------------------------------------------
    ordinal_re  = re.compile(r'^(\d+)(?:st|nd|rd|th)\s+Race\b', re.IGNORECASE)
    racenum_re  = re.compile(r'\brace\s+(\d+)\b', re.IGNORECASE)

    # Gather all anchor/link tags that match race header patterns
    race_header_tags = []
    for tag in soup.find_all('a'):
        text = tag.get_text(strip=True)
        m = ordinal_re.match(text)
        if m:
            race_header_tags.append((int(m.group(1)), tag, 'ordinal'))

    is_real_brisnet = len(race_header_tags) > 0

    if is_real_brisnet:
        races = _parse_brisnet_format(soup, race_header_tags)
    else:
        races = _parse_legacy_format(soup)

    return {
        'track_code': track_code,
        'race_date':  race_date,
        'races':      races,
    }


def _parse_brisnet_format(soup, race_header_tags: list) -> list:
    """
    Parse real Brisnet INR HTML format.
    Race headers are <a> links like "1st Race - Gulfstream Park - Sunday, April 5th, 2026".
    Finish order is in a <table> with columns: #, Horse, Jockey, Weight, Win, Place, Show.
    Rows after the header row are in finish order (row 1 = winner).
    """
    races = []

    # Deduplicate and sort by race number
    seen = set()
    unique_headers = []
    for race_num, tag, fmt in race_header_tags:
        if race_num not in seen:
            seen.add(race_num)
            unique_headers.append((race_num, tag))
    unique_headers.sort(key=lambda x: x[0])

    for idx, (race_num, header_tag) in enumerate(unique_headers):
        finish_order = []
        win_payoff   = 0.0
        place_payoff = 0.0
        show_payoff  = 0.0
        scratches    = []
        conditions   = ""

        # Determine the next race header tag to bound our search
        next_header_tag = unique_headers[idx + 1][1] if idx + 1 < len(unique_headers) else None

        # Collect all <table> elements between this header and the next
        section_tables = []
        el = header_tag.find_next_sibling()
        while el is not None:
            if next_header_tag and el == next_header_tag:
                break
            # Also stop if we hit a sibling that IS the next race anchor
            if el.name == 'a' and idx + 1 < len(unique_headers):
                m = re.match(r'^(\d+)(?:st|nd|rd|th)\s+Race\b', el.get_text(strip=True), re.IGNORECASE)
                if m and int(m.group(1)) != race_num:
                    break
            if el.name == 'table':
                section_tables.append(el)
            el = el.find_next_sibling()

        # Parse each table in this race section
        for table in section_tables:
            rows = table.find_all('tr')
            if not rows:
                continue

            # Identify column headers from first row
            header_cells = [td.get_text(strip=True) for td in rows[0].find_all(['th', 'td'])]

            # ----- Finish order table: has 'Horse' column -----
            if 'Horse' in header_cells:
                try:
                    horse_idx = header_cells.index('Horse')
                except ValueError:
                    continue

                win_idx   = header_cells.index('Win')   if 'Win'   in header_cells else -1
                place_idx = header_cells.index('Place') if 'Place' in header_cells else -1
                show_idx  = header_cells.index('Show')  if 'Show'  in header_cells else -1

                for row_i, row in enumerate(rows[1:]):  # skip header row
                    cells = row.find_all('td')
                    if len(cells) <= horse_idx:
                        continue
                    horse_name = cells[horse_idx].get_text(strip=True)
                    if not horse_name or horse_name in ('Horse', '#', 'Jockey', 'Weight'):
                        continue
                    finish_order.append(horse_name)

                    # Extract payoffs from winner row (row_i == 0)
                    if row_i == 0:
                        if win_idx >= 0 and win_idx < len(cells):
                            win_payoff   = _safe_float(cells[win_idx].get_text())
                        if place_idx >= 0 and place_idx < len(cells):
                            place_payoff = _safe_float(cells[place_idx].get_text())
                        if show_idx >= 0 and show_idx < len(cells):
                            show_payoff  = _safe_float(cells[show_idx].get_text())

            # ----- Conditions table -----
            elif not conditions:
                for row in rows:
                    cells = row.find_all('td')
                    for ci, cell in enumerate(cells):
                        if 'Conditions:' in cell.get_text():
                            if ci + 1 < len(cells):
                                conditions = cells[ci + 1].get_text(strip=True)
                            break

            # ----- Scratches table -----
            for row in rows:
                cells = row.find_all('td')
                for ci, cell in enumerate(cells):
                    txt = cell.get_text(strip=True)
                    if re.match(r'^Scratched?:?$', txt, re.IGNORECASE):
                        if ci + 1 < len(cells):
                            raw = re.split(r'[,;/]', cells[ci + 1].get_text(strip=True))
                            scratches.extend(s.strip() for s in raw if s.strip())

        races.append({
            'race_number':  race_num,
            'finish_order': finish_order,
            'win_payoff':   win_payoff,
            'place_payoff': place_payoff,
            'show_payoff':  show_payoff,
            'scratches':    scratches,
            'conditions':   conditions,
        })

    return races


def _parse_legacy_format(soup) -> list:
    """
    Parse test / legacy format with "Race N" headers and "1. Horse Name" position markers.
    Original text-based parsing logic preserved here for backward compatibility.
    """
    races = []
    race_header_pattern = re.compile(r'\brace\s+(\d+)\b', re.IGNORECASE)
    full_text = soup.get_text(separator='\n')
    lines     = full_text.splitlines()

    current_race_num = None
    current_lines    = []
    race_sections    = []

    for line in lines:
        m = race_header_pattern.match(line.strip())
        if m:
            if current_race_num is not None:
                race_sections.append((current_race_num, current_lines))
            current_race_num = int(m.group(1))
            current_lines    = [line]
        else:
            if current_race_num is not None:
                current_lines.append(line)

    if current_race_num is not None:
        race_sections.append((current_race_num, current_lines))

    for race_num, section_lines in race_sections:
        finish_order  = []
        win_payoff    = 0.0
        place_payoff  = 0.0
        show_payoff   = 0.0
        scratches     = []
        conditions    = ""

        try:
            for ln in section_lines[1:]:
                stripped = ln.strip()
                if stripped and not race_header_pattern.match(stripped):
                    conditions = stripped
                    break

            for ln in section_lines:
                sm = re.search(r'scratched?:?\s*(.+)', ln, re.IGNORECASE)
                if sm:
                    raw_scratches = re.split(r'[,;/]', sm.group(1))
                    scratches.extend(s.strip() for s in raw_scratches if s.strip())

            pos_pattern = re.compile(r'^(\d{1,2})[.):\s]*$')
            pos_inline  = re.compile(r'^(\d{1,2})[.):\s]\s*(.+)')
            pos_hits = {}
            clean_lines = [ln.strip() for ln in section_lines if ln.strip()]

            i = 0
            while i < len(clean_lines):
                ln = clean_lines[i]
                pm_inline = pos_inline.match(ln)
                if pm_inline:
                    pos  = int(pm_inline.group(1))
                    name = pm_inline.group(2).strip()
                    if not re.match(r'^\$?[\d,.]+$', name):
                        pos_hits[pos] = name
                    i += 1
                    continue
                pm_bare = pos_pattern.match(ln)
                if pm_bare and i + 1 < len(clean_lines):
                    pos     = int(pm_bare.group(1))
                    next_ln = clean_lines[i + 1]
                    if (not pos_pattern.match(next_ln)
                            and not pos_inline.match(next_ln)
                            and not re.match(r'^\$?[\d,.]+$', next_ln)
                            and not re.match(r'^(win|place|show|payoff|finish|horse|conditions|scratched)',
                                             next_ln, re.IGNORECASE)):
                        pos_hits[pos] = next_ln.strip()
                        i += 2
                        continue
                i += 1

            if pos_hits:
                for pos in sorted(pos_hits.keys()):
                    finish_order.append(pos_hits[pos])

            win_pat   = re.compile(r'\bwin\b.*?\$?([\d,.]+)', re.IGNORECASE)
            place_pat = re.compile(r'\bplace\b.*?\$?([\d,.]+)', re.IGNORECASE)
            show_pat  = re.compile(r'\bshow\b.*?\$?([\d,.]+)', re.IGNORECASE)

            for ln in section_lines:
                if win_payoff == 0.0:
                    wm = win_pat.search(ln)
                    if wm:
                        win_payoff = _safe_float(wm.group(1))
                if place_payoff == 0.0:
                    pm2 = place_pat.search(ln)
                    if pm2:
                        place_payoff = _safe_float(pm2.group(1))
                if show_payoff == 0.0:
                    sm2 = show_pat.search(ln)
                    if sm2:
                        show_payoff = _safe_float(sm2.group(1))

            dollar_lines = []
            for ln in section_lines:
                dm = re.match(r'^\s*\$?([\d]+\.[\d]{2})\s*$', ln.strip())
                if dm:
                    dollar_lines.append(_safe_float(dm.group(1)))
            if len(dollar_lines) >= 1 and win_payoff   == 0.0:
                win_payoff   = dollar_lines[0]
            if len(dollar_lines) >= 2 and place_payoff == 0.0:
                place_payoff = dollar_lines[1]
            if len(dollar_lines) >= 3 and show_payoff  == 0.0:
                show_payoff  = dollar_lines[2]

        except Exception as exc:
            print(f"WARNING: Could not fully parse Race {race_num} — {exc}. Skipping.")
            continue

        races.append({
            'race_number':  race_num,
            'finish_order': finish_order,
            'win_payoff':   win_payoff,
            'place_payoff': place_payoff,
            'show_payoff':  show_payoff,
            'scratches':    scratches,
            'conditions':   conditions,
        })

    return races


# ---------------------------------------------------------------------------
# FUNCTION 2 — auto_grade_from_file
# ---------------------------------------------------------------------------

def auto_grade_from_file(filepath: str) -> dict:
    """
    Parse a results HTML file and call grade_race() for each race found.
    Returns a summary dict: races_processed, races_with_bets, total_pl.
    """
    filepath = Path(filepath)
    print(f"\nParsing results file: {filepath.name}")
    print("-" * 50)

    parsed = parse_results_file(str(filepath))
    track  = parsed['track_code']
    date_  = parsed['race_date']

    races_processed  = 0
    races_with_bets  = 0
    total_pl         = 0.0

    for race in parsed['races']:
        rn           = race['race_number']
        finish_order = race['finish_order']
        win_p        = race['win_payoff']
        place_p      = race['place_payoff']
        show_p       = race['show_payoff']

        print(f"\nGrading Race {rn} — {track} {date_}")

        if not finish_order:
            print(f"  WARNING: No finish order found for Race {rn} — skipping")
            continue

        try:
            result = grade_race(
                track_code   = track,
                race_date    = date_,
                race_number  = rn,
                results_list = finish_order,
            )
        except Exception as exc:
            print(f"  ERROR calling grade_race() for Race {rn}: {exc}")
            races_processed += 1
            continue

        bets_logged  = result.get('bets_logged', 0)
        graded_count = result.get('graded_count', 0)
        race_pl      = result.get('total_pl', 0.0)

        print(f"  Winner paid: ${win_p:.2f} Win / ${place_p:.2f} Place / ${show_p:.2f} Show")

        if bets_logged > 0 or graded_count > 0:
            print(f"  ✓ Race {rn} graded — {bets_logged} bet(s) logged")
            races_with_bets += 1
            total_pl        += race_pl
        else:
            print(f"  — Race {rn}: no bets found in DB (skipped)")

        races_processed += 1

    print(f"\n{'=' * 50}")
    print(f"Scan complete — processed {races_processed} races, "
          f"{races_with_bets} had active bets, "
          f"total P/L: {total_pl:+.2f}u")

    return {
        'races_processed': races_processed,
        'races_with_bets': races_with_bets,
        'total_pl':        total_pl,
    }


# ---------------------------------------------------------------------------
# FUNCTION 3 — scan_and_grade_all
# ---------------------------------------------------------------------------

def scan_and_grade_all():
    """
    Scan horse_racing_data/ for all *_results.html files not yet processed.
    Tracks processed files in horse_racing_data/graded_results.log.
    """
    DATA_DIR.mkdir(exist_ok=True)

    # Load already-processed filenames
    processed = set()
    if GRADE_LOG.exists():
        with open(GRADE_LOG, 'r') as fh:
            for line in fh:
                processed.add(line.strip())

    # Find new result files
    all_files = sorted(DATA_DIR.glob('*_results.html'))
    new_files = [f for f in all_files if f.name not in processed]

    if not new_files:
        print("No new result files found.")
        return

    newly_processed = 0
    for result_file in new_files:
        auto_grade_from_file(str(result_file))
        # Log as processed
        with open(GRADE_LOG, 'a') as fh:
            fh.write(result_file.name + '\n')
        newly_processed += 1

    print(f"\nScan complete — {newly_processed} new result file(s) processed.")


# ---------------------------------------------------------------------------
# FUNCTION 4 — fetch_import_results_file (optional CSV enhancement)
# ---------------------------------------------------------------------------

def fetch_import_results_file(filepath: str):
    """
    Parse a Brisnet Import Results CSV file (the $0.75 paid results file).

    Expected CSV columns (1-indexed, comma-delimited):
        1: Track code
        2: Date (YYYYMMDD)
        3: Race number
        4: Post position
        5: Horse name
        6: Finish position
        7: Final odds (e.g. 4.5 = 9/2)
        8: Win payoff (if winner, else blank)
        9: Place payoff (if placed, else blank)
       10: Show payoff (if showed, else blank)

    Builds the same race structure as parse_results_file() and grades each race.
    Also attempts to update closing_odds in horse_race_analyses if the column exists.
    """
    filepath = Path(filepath)
    print(f"\nParsing Import Results CSV: {filepath.name}")
    print("-" * 50)

    import csv

    races_map = {}   # race_number → {'horses': [...], 'payoffs': {}}

    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
            reader = csv.reader(fh)
            for row in reader:
                if len(row) < 6:
                    continue
                try:
                    track_code  = row[0].strip().upper()
                    race_date   = row[1].strip()           # YYYYMMDD
                    race_number = int(row[2].strip())
                    # post_pos  = row[3] — not used
                    horse_name  = row[4].strip()
                    finish_pos  = int(row[5].strip()) if row[5].strip().isdigit() else 99
                    final_odds  = _safe_float(row[6]) if len(row) > 6 else 0.0
                    win_p       = _safe_float(row[7])  if len(row) > 7 else 0.0
                    place_p     = _safe_float(row[8])  if len(row) > 8 else 0.0
                    show_p      = _safe_float(row[9])  if len(row) > 9 else 0.0
                except (ValueError, IndexError):
                    continue

                if race_number not in races_map:
                    races_map[race_number] = {
                        'track_code':  track_code,
                        'race_date':   race_date,
                        'win_payoff':  0.0,
                        'place_payoff': 0.0,
                        'show_payoff': 0.0,
                        'horses': [],
                    }

                races_map[race_number]['horses'].append({
                    'name':       horse_name,
                    'finish_pos': finish_pos,
                    'final_odds': final_odds,
                })
                # Capture payoffs from the winner row
                if finish_pos == 1 and win_p > 0:
                    races_map[race_number]['win_payoff']   = win_p
                if finish_pos == 2 and place_p > 0:
                    races_map[race_number]['place_payoff'] = place_p
                if finish_pos == 3 and show_p > 0:
                    races_map[race_number]['show_payoff']  = show_p

    except FileNotFoundError:
        print(f"ERROR: File not found: {filepath}")
        return

    if not races_map:
        print("No race data found in CSV.")
        return

    # Determine track / date from first race entry
    first_race   = next(iter(races_map.values()))
    track_code   = first_race['track_code']
    race_date    = first_race['race_date']

    DB_PATH = SCRIPT_DIR / "sports_betting.db"

    races_processed = 0
    races_with_bets = 0
    total_pl        = 0.0

    for race_number in sorted(races_map.keys()):
        entry  = races_map[race_number]
        horses = sorted(entry['horses'], key=lambda h: h['finish_pos'])
        finish_order = [h['name'] for h in horses]

        win_p   = entry['win_payoff']
        place_p = entry['place_payoff']
        show_p  = entry['show_payoff']

        print(f"\nGrading Race {race_number} — {track_code} {race_date}")

        try:
            result = grade_race(
                track_code   = track_code,
                race_date    = race_date,
                race_number  = race_number,
                results_list = finish_order,
            )
        except Exception as exc:
            print(f"  ERROR calling grade_race() for Race {race_number}: {exc}")
            races_processed += 1
            continue

        bets_logged  = result.get('bets_logged', 0)
        graded_count = result.get('graded_count', 0)
        race_pl      = result.get('total_pl', 0.0)

        print(f"  Winner paid: ${win_p:.2f} Win / ${place_p:.2f} Place / ${show_p:.2f} Show")

        # Optional: update closing_odds in horse_race_analyses
        try:
            with safe_write() as conn:
                cur = conn.cursor()
                # Check column exists
                cur.execute("PRAGMA table_info(horse_race_analyses)")
                cols = [r[1] for r in cur.fetchall()]
                if 'closing_odds' in cols:
                    for h in horses:
                        cur.execute("""
                            UPDATE horse_race_analyses
                               SET closing_odds = ?
                             WHERE UPPER(horse_name) = UPPER(?)
                               AND track = ?
                               AND race_number = ?
                        """, (h['final_odds'], h['name'], track_code, race_number))
                # safe_write() handles commit + writeback on exit
        except Exception:
            pass  # Silently skip — never crash on optional update

        if bets_logged > 0 or graded_count > 0:
            print(f"  ✓ Race {race_number} graded — {bets_logged} bet(s) logged")
            races_with_bets += 1
            total_pl        += race_pl
        else:
            print(f"  — Race {race_number}: no bets found in DB (skipped)")

        races_processed += 1

    print(f"\n{'=' * 50}")
    print(f"Scan complete — processed {races_processed} races, "
          f"{races_with_bets} had active bets, "
          f"total P/L: {total_pl:+.2f}u")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    if len(sys.argv) == 1:
        scan_and_grade_all()
    elif len(sys.argv) == 2:
        fp = sys.argv[1]
        if fp.endswith('.html'):
            auto_grade_from_file(fp)
        elif fp.endswith('.csv') or fp.endswith('.txt'):
            fetch_import_results_file(fp)
        else:
            print(f"Unknown file type: {fp}")
            print("Usage: python results_fetcher.py [optional: path to results file]")
    else:
        print("Usage: python results_fetcher.py [optional: path to results file]")
