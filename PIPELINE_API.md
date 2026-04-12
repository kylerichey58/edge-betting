# EDGE Intelligence Platform — Pipeline API Reference
**Last Updated:** April 10, 2026 | Read this at session start. Every function signature, return format, and gotcha is documented here. Never probe function names by trial and error — check here first.

---

## QUICK REFERENCE — IMPORT BLOCK

```python
from brisnet_fetcher import fetch_race_file, extract_zip, get_available_tracks
from horse_racing_parser import parse_race_file
from horse_racing_scorer import score_race
from horse_racing_simulator import run_simulation, generate_recommendation
from horse_racing_grader import grade_race, update_trainer_stats, get_leaderboard
from db_utils import safe_write, safe_read, verify_db, get_pending_stress_test_count, delete_stress_test_bets
from results_fetcher import build_results_url, scan_and_grade_all, fetch_import_results_file
```

---

## CRITICAL GOTCHAS — READ FIRST

| Gotcha | Detail |
|--------|--------|
| **`generate_recommendation`** | NOT `get_recommendation` — lives in `horse_racing_simulator`, NOT `horse_racing_scorer` |
| **`run_simulation`** | NOT `simulate_race` — this has caused trial-and-error every session |
| **`parse_race_file` return format** | Returns `{race_num: [horse_dicts]}` — a dict keyed by race number, NOT a flat list |
| **`score_race` signature** | NO `m05_override` param as of April 9 — M05 is fully automated, passing it will error |
| **`*k.zip` only** | `*n.zip` = entries format only, will NOT parse. Always `*k.zip` (PP Single) |
| **Never write directly to DB_PATH** | Always use `db_utils.safe_write()` — direct NTFS mount writes cause I/O errors and stranded journals |
| **M09 = 0 is absolute veto** | No exceptions. Do not log any bet where M09 = 0 regardless of composite score |
| **OPX → OP** | TRACK_CODE_MAP in results_fetcher.py — DRF code OPX maps to Brisnet code OP |
| **GPX → GP** | Same pattern — Gulfstream DRF code GPX maps to Brisnet code GP |

---

## brisnet_fetcher.py

### `get_available_tracks()`
```python
get_available_tracks() -> list[str]
```
Scans `horse_racing_data/` folder for `.DRF` files. Returns list of track codes currently loaded.
```python
# Example return
['AQU', 'KEE', 'GPX', 'OPX']
```

### `extract_zip(zip_path, dest_dir)`
```python
extract_zip(zip_path: str | Path, dest_dir: str | Path) -> list[Path]
```
Extracts ZIP contents to `dest_dir`. Returns list of extracted file paths.
- Auto-detects `*k.zip` vs `*n.zip` — will log a warning if `*n.zip` is passed but will still extract
- Does NOT move the ZIP — move manually after extraction if needed

### `fetch_race_file(track_code, date_str)`
```python
fetch_race_file(track_code: str, date_str: str) -> Path | None
```
Looks for a DRF file matching `{track_code}{MMDD}.DRF` in `horse_racing_data/`. Returns Path if found, None if not.
```python
fetch_race_file('KEE', '0411')  # looks for KEE0411.DRF
```

---

## horse_racing_parser.py

### `parse_race_file(drf_path)`
```python
parse_race_file(drf_path: str | Path) -> dict[int, list[dict]]
```
Parses a full `.DRF` file. Returns a dict keyed by race number (int), each value is a list of horse dicts.

**⚠️ Return format — this trips up every session:**
```python
races = parse_race_file('horse_racing_data/KEE0411.DRF')
# races = {1: [horse_dict, horse_dict, ...], 2: [...], ...}

# Correct iteration:
for race_num, horses in races.items():
    scored = score_race(horses)
```

### Horse Dict Keys (what each horse dict contains)
```python
{
    'name': str,
    'post_position': int,
    'morning_line_odds': float,
    'running_style': str,        # 'E', 'P', 'S', 'U' — auto-computed as of Apr 9
    'fc_beaten_pp1': float,      # first-call beaten lengths, most recent race
    'fc_beaten_pp2': float,      # first-call beaten lengths, 2nd most recent
    'fc_beaten_pp3': float,      # first-call beaten lengths, 3rd most recent
    'trainer': str,
    'jockey': str,
    'class_rating': float,
    'speed_figure': float,       # Beyer/pace figure
    'days_since_last_race': int,
    'track_condition_record': dict,
    'distance_record': dict,
}
```

---

## horse_racing_scorer.py

### `score_race(horses)`
```python
score_race(horses: list[dict]) -> list[dict]
```
Takes the list of horse dicts for ONE race. Returns list of scored dicts — one per horse.

**⚠️ No `m05_override` param** — removed April 9. M05 is fully automated from `running_style`.

```python
# Correct call:
scored_horses = score_race(horses)

# Wrong — will error:
scored_horses = score_race(horses, m05_override=2)
```

### Scored Dict Keys (what score_race adds to each horse)
```python
{
    # ... all original horse dict keys ...
    'm01': int,        # Class Level (0-3)
    'm02': int,        # Track Condition (0-3)
    'm03': int,        # Distance Fit (0-3)
    'm04': int,        # Jockey/Trainer % (0-3)
    'm05': int,        # Pace Scenario — AUTO (0-3)
    'm06': int,        # Speed Figure (0-3)
    'm07': int,        # Trainer Situational (0-3) — LIVE as of Apr 8
    'm08': int,        # Sharp Money / Odds Drift (0-3)
    'm09': int,        # Recent Form / Market (0 or 3) — 0 = absolute NO-PLAY
    'composite_score': int,    # sum of all metrics (0-27)
    'pace_scenario': str,      # 'HOT', 'SLOW', 'MIXED' — field-level
    'confidence': str,         # 'HIGH', 'MEDIUM', 'LOW'
    'flag': str,               # 'GEM', 'STRONG', 'NEUTRAL', 'WEAK', 'NO-PLAY'
}
```

---

## horse_racing_simulator.py

### `run_simulation(scored_horses, trials)`
```python
run_simulation(scored_horses: list[dict], trials: int = 10000) -> list[dict]
```
**⚠️ Function is `run_simulation` NOT `simulate_race`.**

Runs Monte Carlo simulation. Returns list of result dicts — one per horse — sorted by win probability descending.
```python
{
    'name': str,
    'post_position': int,
    'win_pct': float,      # e.g. 0.34 = 34%
    'place_pct': float,
    'show_pct': float,
    'composite_score': int,
    'morning_line_odds': float,
    'value': str,          # 'OVERLAY', 'FAIR', 'UNDERLAY'
    'flag': str,
}
```

### `generate_recommendation(sim_results)`
```python
generate_recommendation(sim_results: list[dict]) -> dict
```
**⚠️ Function is `generate_recommendation` NOT `get_recommendation`. Lives in `horse_racing_simulator`, NOT `horse_racing_scorer`.**

Takes the simulation result list for a race. Returns recommendation dict.
```python
{
    'top_pick': dict,           # highest win_pct horse
    'exacta': [dict, dict],     # top 2 by win_pct
    'trifecta': [dict, dict, dict],
    'superfecta': [dict, dict, dict, dict],  # only if field >= 7
    'pace_scenario': str,
    'gem_count': int,
    'recommendation_text': str,
    'play': bool,               # False if top pick has M09=0
}
```

---

## horse_racing_grader.py

### `grade_race(race_id, winner_name, place_name, show_name)`
```python
grade_race(
    race_id: int,
    winner_name: str,
    place_name: str,
    show_name: str
) -> dict
```
Grades all bets in DB matching `race_id`. Updates result and profit_loss. Returns summary dict.
```python
{
    'race_id': int,
    'bets_graded': int,
    'winners': list[str],
    'total_profit_loss': float,
}
```

### `update_trainer_stats(graded_race_data)`
```python
update_trainer_stats(graded_race_data: dict) -> int
```
Updates `trainer_situational_stats` table after grading. Returns number of rows updated.
Call this after every `grade_race()` call to keep M07 fed.

### `get_leaderboard(top_n, situation)`
```python
get_leaderboard(top_n: int = 20, situation: str = None) -> list[dict]
```
Returns top trainers by ROI. Optional `situation` filter (e.g. `'MCL_T'`, `'2nd_off_layoff'`).

---

## results_fetcher.py

### `build_results_url(track_code, date_str)`
```python
build_results_url(track_code: str, date_str: str) -> str
```
Converts DRF track code to Brisnet results URL.
```python
build_results_url('GPX', '2026-04-11')
# → 'https://www.brisnet.com/product/download/2026-04-11/INR/USA/TB/GP/D/0/'
```
TRACK_CODE_MAP handles all conversions — OPX→OP, GPX→GP, all others map directly.

### `scan_and_grade_all(results_dir)`
```python
scan_and_grade_all(results_dir: str | Path = 'horse_racing_data/') -> dict
```
Scans for `*_results.html` files, skips already-graded races, grades remaining. Returns summary.

### `fetch_import_results_file(track_code, date_str)`
```python
fetch_import_results_file(track_code: str, date_str: str) -> Path | None
```
Optional $0.75 paid path — fetches closing odds CSV from Brisnet Import Results. Stubbed for future use — not active yet.

---

## db_utils.py

### `safe_write()`
```python
# Context manager — use for ALL INSERT / UPDATE / DELETE
with safe_write() as conn:
    conn.execute("INSERT INTO bets (...) VALUES (...)")
    # commit is automatic on exit
```

### `safe_read()`
```python
# Context manager — use for SELECT only
with safe_read() as conn:
    rows = conn.execute("SELECT * FROM bets WHERE result='PENDING'").fetchall()
```

### `verify_db()`
```python
verify_db() -> dict
# Returns row counts for all tables + DB file size + status
# Call at session start to confirm clean state
```

### `get_pending_stress_test_count()`
```python
get_pending_stress_test_count() -> int
# Returns count of STRESS_TEST bets still in DB
```

### `delete_stress_test_bets()`
```python
delete_stress_test_bets() -> int
# Deletes all STRESS_TEST bets — ONLY after all are graded
# Will raise ValueError if any STRESS_TEST bets are still PENDING
```

---

## BRISNET CHROME WORKFLOW

### Download Flow (Cowork Chrome) — CONFIRMED APRIL 12
1. Navigate to `https://www.brisnet.com` (must be logged in as kylerichey58)
2. Click user account icon (top right) → click **"My Products"**
3. Find **"Brisnet Data Plan"** on the RIGHT side panel → click it
4. Click **"PP Data Files (single)"** → click **"View"**
5. AngularJS file table loads — find today's date column
6. Click the blue download icon for each available track
   Files land in `C:\Users\kyler\Downloads\` as `{track}{MMDD}k.zip`
7. Copy all `*k.zip` files to `horse_racing_data\`
8. Run `extract_zip()` on each — `.DRF` files extracted, ready to parse
9. **Never download `*n.zip`** — entries format only, will not parse

**NOTE:** Direct URL construction and Python requests are blocked by sandbox
proxy for authenticated Brisnet pages. Browser download is the only path.
The old `cgi-bin/static.cgi?page=datalist` URL is dead — redirects to home.

### Results Fetch Flow (Cowork Chrome)
1. Build URL: `build_results_url(track_code, date_str)`
2. Navigate Chrome to that URL
3. Capture full page HTML
4. Save as `{TRACK}{MMDD}_results.html` in `horse_racing_data/`
5. Run `scan_and_grade_all()` — auto-grades all ungraded races

### Track Code Map (DRF → Brisnet)
| DRF Code | Brisnet Code | Track |
|----------|-------------|-------|
| GPX | GP | Gulfstream Park |
| OPX | OP | Oaklawn Park |
| KEE | KEE | Keeneland |
| AQU | AQU | Aqueduct |
| CD | CD | Churchill Downs |
| SA | SA | Santa Anita |
| SAR | SAR | Saratoga |
| BEL | BEL | Belmont |
| DMR | DMR | Del Mar |
| FG | FG | Fair Grounds |
| TAM | TAM | Tampa Bay Downs |
| TP | TP | Turfway Park |
| LRL | LRL | Laurel |
| PIM | PIM | Pimlico |
| MVR | MVR | Mahoning Valley |
| CTX | CTX | Charles Town |
| EVD | EVD | Evangeline Downs |
| PEN | PEN | Penn National |

---

## SESSION START CHECKLIST

Run this at the top of every session before touching anything:

```python
from db_utils import verify_db, get_pending_stress_test_count

health = verify_db()
print(health)
# Expected: bets=53, status='healthy' (clean baseline April 10)

stress = get_pending_stress_test_count()
print(f"Stress test bets pending: {stress}")
# Expected: 0 on a clean session start
```

---

*EDGE Intelligence Platform | Pipeline API Reference | Updated April 10, 2026*
