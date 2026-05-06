# EDGE Intelligence Platform — Cowork Operational Reference

*Last updated: April 25, 2026 — Post-reform | Governed by PHILOSOPHY.md*

> This document is the operational reference. For the platform's design philosophy and governance principles, read **PHILOSOPHY.md** first.

---

## Platform Overview

EDGE is a multi-sport edge-detection engine. The platform analyzes events using sport-specific frameworks, surfaces probability-vs-price mispricings, and provides those edges to a human bettor who decides what to act on. **The engine is unbiased about bet types — it surfaces edge wherever it exists.** The bettor is the judgment layer.

**Live URL:** https://kylerichey58.github.io/edge-betting/EDGE-Platform.html
**Local test:** `python -m http.server 8080` → localhost:8080/EDGE-Platform.html
**Backend:** `python edge_server.py` → port 5050
**Branch:** main — GitHub Pages auto-deploys on push
**Push command:** `git push origin main --force` (from VS Code terminal, never Cowork)

---

## Platform State (Post-Reform — April 25, 2026)

The platform underwent a major reform on April 25, 2026. Prior bet records were build-phase data and have been wiped. The brain (event analysis tables) is preserved.

| Element | State |
|---------|-------|
| `bets` table | **Empty (0 rows)** — real performance tracking begins ~May 1, 2026 |
| `parlays` / `parlay_legs` tables | **Empty** — same reason |
| `horse_race_analyses` | **Preserved** — every horse ever analyzed, full history |
| `trainer_situational_stats` | **Preserved — 82,197 rows** |
| `jockey_stats` | **Preserved — 1,135 rows** |
| Exotic bet handling | **Removed from codebase** — exotics are bettor's discretion only |
| Biased "permanent rules" | **Removed** (no-ML, totals-priority, parlay-bad, M09-veto, GEM-as-gate) |

---

## Sport Wings (Each is independent)

| Sport | Engine Name | Status | Brain Version |
|-------|-------------|--------|---------------|
| Horse Racing | Car Wash | Active development | v1.0-pre (formalize before May 1) |
| Men's College Basketball | Scout | Frameworks exist; awaits re-scrutiny before 2026-27 season | TBD |
| Women's College Basketball | Scout | Frameworks exist; awaits re-scrutiny | TBD |
| NBA | Scout | Not yet built | — |
| NFL | TBD | Not yet built | — |
| NCAA Football | TBD | Not yet built | — |
| MLB | TBD | Not yet built | — |

Wings share infrastructure (DB, safe-write, UI shell, APIs) but never share analytical logic. See PHILOSOPHY.md principle #3.

---

## File Structure

```
C:\Users\kyler\Documents\Sportsbetting\
  EDGE-Platform.html              — main platform UI, all tabs, full JS
  index.html                      — GitHub Pages entry point mirror
  edge_server.py                  — Flask backend on port 5050
  .env                            — API keys (NEVER commit)
  .gitignore                      — excludes .env, sports_betting.db, _archive/, *_backup*.db
  CLAUDE.md                       — this file (operational reference)
  PHILOSOPHY.md                   — design philosophy (governing reference)
  PIPELINE_API.md                 — function signature reference
  SANDBOX_CAPABILITY.md           — Cowork sandbox env reference (network/FS/git/DB capabilities)
  db_utils.py                     — safe_write() NTFS locking fix
  sports_betting.db               — SQLite database
  bet_tracker.py                  — bet logging (will be updated for bet_source field)
  bet_analytics.py                — terminal analytics dashboard (will be updated for per-sport P&L)
  results_fetcher.py              — post-race result scraping + grading trigger
  major_conference_analyzer.py    — basketball module
  ncaam_scout.py / ncaaw_scout.py
  womens_basketball_analyzer.py
  horse_racing_data/              — Brisnet .drf/.zip files land here
  brisnet_fetcher.py
  horse_racing_parser.py
  horse_racing_scorer.py
  horse_racing_simulator.py
  horse_racing_grader.py          — exotic functions removed in April 25 reform
  equibase_xml_importer.py        — 2023 historical data loader (single-process only)
  _archive/                       — archived files
```

**API Keys in .env:**
- ANTHROPIC_API_KEY
- ODDS_API_KEY
- BRISNET_USERNAME (kylerichey58)
- BRISNET_PASSWORD

---

## Tech Stack

- EDGE-Platform.html — single-file HTML/JS dashboard, Chart.js visualizations
- Dark navy/teal design — Bebas Neue, JetBrains Mono, Outfit fonts
- Flask backend (edge_server.py) — port 5050
- sports_betting.db — SQLite

**Database tables:**
- `bets` — straight bets ledger (currently empty post-reform; will gain `bet_source` column)
- `parlays` / `parlay_legs` — multi-leg tracking (currently empty post-reform)
- `horse_race_analyses` — every horse analyzed: scores, probabilities, recommendation, finish position. **The brain's memory.**
- `trainer_situational_stats` — 82,197 rows. UNIQUE on (trainer_name, situation).
- `jockey_stats` — 1,135 rows.

---

## Cowork Workflow Rules

| Who | Does What | Never Does |
|-----|-----------|------------|
| Kyle | Decides what to bet, places bets manually on DraftKings, runs git commands | Never lets automation place bets |
| Claude.ai | Strategy, architecture, all Cowork prompts written here first | Never writes directly to files |
| Cowork | All file creation and edits in Sportsbetting folder. Confirms with raw output. | Never pushes to GitHub — sandbox blocks it |
| VS Code Terminal | All git operations: add, commit, push, force-push | Never edits files — git only |

**Permanent operational discipline:**
- One Cowork prompt per task. Confirm output before proceeding.
- Test on localhost:8080 before checking GitHub Pages.
- Git lock cleanup: `del .git\HEAD.lock` and `del .git\index.lock` between stages.
- All DB writes go through `db_utils.safe_write()`.
- Read PIPELINE_API.md at session start before touching pipeline scripts.
- `*k.zip` only — `*n.zip` is entries-format and will not parse.
- `equibase_xml_importer.py` runs single-process only (multiprocessing corrupted DB on April 8, 2026).

---

## Operational Rules (Permanent)

**These are infrastructure / risk / discipline rules. They are NOT analytical claims. See PHILOSOPHY.md principle #10.**

- **Human places all bets manually on DraftKings — automation off the table forever.**
- **1 unit = $100.** The platform speaks in standardized units.
- **Sizing cap: 1u standard, up to 2u on highest-conviction situations.** Bankroll discipline, not analytical opinion.
- **Sport-specific sharp money treatment:**
  - Heavy weight in basketball, baseball, football (lines move on professional money)
  - De-emphasized in horse racing (pari-mutuel pools change constantly; sharps are diluted)
- **Brain versioning:** Each sport's brain is versioned (v1.0, v1.1, v2.0, etc.). Calibration data is tracked per-version.
- **Bet source tagging:** When the `bet_source` column is added, every logged bet is tagged ENGINE or OVERRIDE.
- **Real performance tracking begins ~May 1, 2026** (date follows reform completion).
- **Stress test cleanup order:** Print full P&L by bet type → confirm → THEN delete. Never delete first.
- **Brisnet download path is browser-only.** Direct URL construction blocked by auth tokens.

---

## Track Code Mappings (DRF → Brisnet results)

- OPX → OP (Oaklawn)
- GPX → GP (Gulfstream)
- CTX → CT (Charles Town) — fixed April 12, 2026

---

## Brisnet Download Workflow

| Step | Action |
|------|--------|
| 1 | Navigate to brisnet.com (logged in as kylerichey58) |
| 2 | Click account icon (top right) → My Products |
| 3 | Find Brisnet Data Plan on the RIGHT side panel → click it |
| 4 | Click PP Data Files (single) → click View |
| 5 | AngularJS table loads — find today's date column |
| 6 | Click blue download icon for each available track |
| 7 | Files land in `C:\Users\kyler\Downloads\` as `{track}{MMDD}k.zip` |
| 8 | Copy all `*k.zip` to `horse_racing_data\` |
| 9 | Run `extract_zip()` on each — confirm .DRF files present before Car Wash |

---

## Horse Racing Car Wash — Current Metric Framework (v1.0-pre)

| # | Metric | Status | Data Source |
|---|--------|--------|-------------|
| M01 | Speed Figure Trajectory | ✅ Active | Beyer Par by track/surface/class |
| M02 | Class-Adjusted Figure | ✅ Active | NARC + Beyer Index |
| M03 | Class Direction / Intent | ✅ Active | 2026 grade changes |
| M04 | Surface & Distance Fit | ✅ Active | Track clockings |
| M05 | Pace Scenario | ✅ Active | DRF first-call beaten lengths |
| M06 | Form Cycle / Raw Speed | ✅ Active | DRF speed indices |
| M07 | Trainer Situational ROI | ✅ Active | trainer_situational_stats (82,197 rows) |
| M08 | Jockey Switch Signal | ✅ Active | jockey_stats (1,135 rows) |
| M09 | Market Signal | ✅ Active — **NOT a veto** | DRF morning line vs early odds |

**Composite range:** 0–27. **GEM label:** composite ≥ 18 with HIGH confidence.

**Important:** GEM is a **label**, not a gate. The engine surfaces edges across the full score range. GEM signals high-conviction situations but does not suppress lower-score plays where the math still shows edge. M09 is a **signal**, not a **veto** — it heavily informs but never blocks.

---

## Script Reference (see PIPELINE_API.md for full signatures)

| Script | Purpose |
|--------|---------|
| brisnet_fetcher.py | `fetch_race_file`, `extract_zip`, `get_available_tracks` |
| horse_racing_parser.py | `parse_race_file` → `{race_num: [horse_dicts]}` |
| horse_racing_scorer.py | `score_race`, `generate_recommendation` |
| horse_racing_simulator.py | `simulate_race` (10,000 trials) |
| horse_racing_grader.py | `grade_race`, `update_trainer_stats`, `get_leaderboard` |
| results_fetcher.py | `build_results_url`, `scan_and_grade_all`, `fetch_import_results_file` |
| db_utils.py | `safe_write`, `safe_read`, `verify_db` |

---

## Known Issues / On the Horizon

### Immediate (next sessions)
- Build `card_runner.py` — pre-computes a full slate via parser → scorer → simulator; replaces the retired `stress_test_runner.py` (tracked as Item 3 in `docs/EDGE_PlatformState_v1.md`)
- Add `bet_source` column population logic in `bet_tracker.py`
- Update `bet_analytics.py` for per-sport P&L views
- Formalize Horse Racing Car Wash v1.0 release (mark version, lock framework structure)

### Short term
- Re-scrutinize basketball Scout framework before 2026-27 season — same bias-rejection scrutiny applied to horse racing
- Build NBA Scout framework
- Verify pace data lives in `horse_race_analyses` properly (separate from old `bets.notes` hardcoding)
- Cloud-hosting for multi-device access

### Longer term
- NFL framework design
- NCAAF framework design
- MLB framework design
- Action Network PRO as supplementary sharp money source for major team sports
- Racing API + racing-mcp-server integration

---

## Reform History

- **April 25, 2026** — Major reform: bets/parlays tables wiped (build-phase data), exotic code removed, biased rules stripped from CLAUDE.md, PHILOSOPHY.md created, brain memory preserved. Real performance tracking begins ~May 1, 2026.
- **April 13, 2026** — ARM2026 calibration session, notes format fix in stress_test_runner.py.
- **April 12, 2026** — First full live stress test (174 bets, 6 tracks). Calibration data captured.
- **April 10, 2026** — Original "clean baseline" lock (now superseded by April 25 reform wipe).
- **April 8, 2026** — Equibase data import (2023 historical), `equibase_xml_importer.py` corruption incident.
- **February 14, 2026** — Platform launched as basketball analytics tool.

---

*EDGE Intelligence Platform | Built for Kyle Richey | kylerichey58 | Confidential*
