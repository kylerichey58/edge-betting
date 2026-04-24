# EDGE Intelligence Platform — Cowork Permanent Context
*Last updated: April 24, 2026 | Reflects state as of Apr 13 handoff (ARM2026 live, baseline locked)*

---

## PLATFORM OVERVIEW

EDGE is a personal sports betting analytics platform built by Kyle Richey. Single-source intelligence tool — games and races run through a metric framework and AI pipeline, structured bet recommendation comes out. Human always places bets manually on DraftKings. Automation is permanently off the table.

**Live URL:** https://kylerichey58.github.io/edge-betting/EDGE-Platform.html
**Local test:** `python -m http.server 8080` → localhost:8080/EDGE-Platform.html
**Backend:** `python edge_server.py` → port 5050
**Branch:** main — GitHub Pages auto-deploys on push
**Push command:** `git push origin main --force` (from VS Code terminal, never Cowork)
**Latest commit:** e27e734 — Brisnet workflow + CTX fix + exotic cleanup rule (Apr 13)

---

## CLEAN BASELINE (Locked April 10, 2026 — Permanent)

These numbers do not change unless a real graded bet is added. All stress test bets are excluded.

| Metric | Value |
|--------|-------|
| Overall Record (Straight) | 29W-23L-1P │ 55.8% WR │ -0.87u |
| **Totals Edge** | **+2.94u │ +11.4% ROI — PRIMARY EDGE (still intact)** |
| Spreads | 16W-11L │ -1.47u │ juice drag confirmed |
| Moneyline | 0W-3L — never bet ML, rule confirmed by data |
| Parlay Record | 1W-9L │ -6.54u — historically problematic |
| Real Bets in DB | 53 (5 fake placeholders deleted ids 59-63, id=12 date fixed to 2026-02-18) |

---

## FILE STRUCTURE

```
C:\Users\kyler\Documents\Sportsbetting\
  EDGE-Platform.html              — main platform, all tabs, full JS
  index.html                      — GitHub Pages entry point mirror
  edge_server.py                  — Flask backend on port 5050
  .env                            — API keys (NEVER commit)
  .gitignore                      — excludes .env, sports_betting.db, _archive/
  CLAUDE.md                       — this file — Cowork permanent context
  PIPELINE_API.md                 — function signature reference (read at session start)
  db_utils.py                     — safe_write() NTFS locking fix
  sports_betting.db               — SQLite, 53 real bets (clean baseline)
  bet_tracker.py                  — primary bet logging
  bet_analytics.py                — terminal analytics dashboard
  results_fetcher.py              — post-race result scraping + grading trigger
  stress_test_runner.py           — full-card DRF Car Wash pipeline
  major_conference_analyzer.py    — basketball module
  ncaam_scout.py / ncaaw_scout.py
  womens_basketball_analyzer.py
  horse_racing_data/              — Brisnet .drf/.zip files land here
  brisnet_fetcher.py              — downloads + extracts Brisnet PP files
  horse_racing_parser.py          — parses .drf CSV → horse dicts
  horse_racing_scorer.py          — 11-metric scoring engine
  horse_racing_simulator.py       — Monte Carlo simulation
  horse_racing_grader.py          — grades results + builds trainer DB
  equibase_xml_importer.py        — 2023 historical data loader (single-process only)
  _archive/                       — archived files
```

**API Keys in .env:**
- ANTHROPIC_API_KEY
- ODDS_API_KEY
- BRISNET_USERNAME (kylerichey58)
- BRISNET_PASSWORD

---

## TECH STACK

- EDGE-Platform.html — single-file HTML/JS dashboard, Chart.js visualizations
- Dark navy/teal design — Bebas Neue, JetBrains Mono, Outfit fonts
- Flask backend (edge_server.py) — port 5050
- sports_betting.db — SQLite with tables: `bets`, `parlays`, `parlay_legs`, `horse_race_analyses`, `trainer_situational_stats` (82,197 rows), `jockey_stats` (1,135 rows)

---

## COWORK WORKFLOW (PERMANENT RULES)

| Who | Does What | Never Does |
|-----|-----------|------------|
| Kyle | Decides track + race. Reviews output. Places bets manually on DraftKings. | Never lets automation place bets |
| Claude.ai | Strategy, architecture, all Cowork prompts written here first | Never writes directly to files |
| Cowork | All file creation and edits in SportsBetting folder. Confirms by pasting raw line content or test output. | Never pushes to GitHub — network sandbox blocks it |
| VS Code Terminal | All git operations: git add, git commit, git push origin main --force | Never edits files — git only |

**Git lock cleanup:** `del .git\HEAD.lock` and `del .git\index.lock` — mandatory after every stage
**Local test:** Always test at localhost:8080 before checking GitHub Pages — CDN caches stale versions
**CLAUDE.md:** Refresh when baseline, rules, or row counts change materially

---

## PERMANENT RULES (Never Change)

### Betting rules
- **Human places all bets manually on DraftKings Racing — automation permanently off the table**
- **M09 = 0 is absolute NO-PLAY** — no exceptions regardless of composite score
- **Never bet moneyline** — 0% hit rate confirmed (horse racing + basketball)
- **Totals are the primary edge** — +11.4% ROI confirmed; size up on totals
- **GEM threshold** — composite score ≥ 18 AND confidence = HIGH (both required)
- **Unit sizing** — 0.5-1.0u standard; up to 2.0u only for GEMs with HIGH confidence
- **Win/Place/Show on HIGH** — HIGH confidence + strong score = cover all three, never Win alone (calibration-confirmed Apr 10)
- **MED confidence = watchlist only** — 10.5% WR / -40.49u confirmed noise; do not bet, do not stress test

### Operational rules
- **db_utils.safe_write() for all writes** — never write directly to NTFS mount; copy-operate-writeback is automatic
- **Read PIPELINE_API.md at session start** — before touching any pipeline script
- **`*k.zip` only** — `*n.zip` is entries-format and will NOT parse
- **Git lock cleanup mandatory** — `del .git\index.lock` after every git stage
- **Cowork never pushes** — all `git push` from VS Code terminal
- **equibase_xml_importer.py must run single-process** — multiprocessing corrupted DB on April 8
- **Stress test cleanup order** — print full P&L by bet type → confirm with Kyle → THEN delete. Never delete first. Exotic data is unrecoverable after delete.
- **Brisnet download path is browser-only** — direct URL construction blocked by auth tokens. Use the locked workflow (see below).

### Track code mappings (DRF → Brisnet results)
- OPX → OP (Oaklawn)
- GPX → GP (Gulfstream)
- **CTX → CT (Charles Town)** — fixed April 12 after 18 voided bets on April 11

### Notes format (locked April 12 — stress_test_runner.py lines 263-265)
```
STRESS_TEST ARM2026 {track} R{rnum} | SCORE={score} | CONF={conf} | PACE={pace} | GEM={is_gem}
```
This captures full calibration signature. Old format lost all calibration data.

---

## BRISNET DOWNLOAD WORKFLOW (Confirmed April 12 — Only Working Path)

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

## CURRENT MODEL SPECS (Post-ARM2026, April 12)

| # | Metric | Status | Data Source |
|---|--------|--------|-------------|
| M01 | Speed Figure Trajectory | ✅ UPGRADED | Beyer Par by track/surface/class — 461 entries, 47 tracks |
| M02 | Class-Adjusted Figure | ✅ ENHANCED | NARC + Beyer Index — 150 stakes entries |
| M03 | Class Direction / Intent | ✅ ENHANCED | 2026 grade changes — 18 entries encoded |
| M04 | Surface & Distance Fit | ✅ ENHANCED | Track clockings — 692 benchmark entries |
| M05 | Pace Scenario | ✅ AUTOMATED | DRF first-call beaten lengths (indices 865/866/867) → HOT/SLOW/MIXED |
| M06 | Form Cycle / Raw Speed | ✅ SOLID | Unchanged — operating correctly |
| M07 | Trainer Situational ROI | ✅ UPGRADED | 82,197 rows — MEET fallback by last name active |
| M08 | Jockey Switch Signal | ✅ UPGRADED | 1,135 rows ARM meet win% — activates when DRF starts < 5 |
| M09 | Market Veto | ✅ SOLID | Absolute NO-PLAY veto — fired 24 times April 12 |

Composite max = 27. Gem threshold = 18+ AND confidence = HIGH.

---

## ARM2026 CALIBRATION FINDINGS (April 12 Grading — Most Important Numbers)

| Segment | Win Rate | WIN P&L | Implication |
|---------|----------|---------|-------------|
| Score 20-21 bucket | 66.7% | +18.90u | Top of GEM range = real signal (n=3, directionally correct) |
| **HIGH confidence** | **15.9%** | **+1.68u** | **Only profitable segment — ARM2026 upgrade proven** |
| MED confidence | 10.5% | -40.49u | Pure noise — watchlist only |
| GEM=YES | 12.4% | negative | Exotic drag pulls negative even with better WR |
| PACE=MIXED | 33.3% | positive | 6 bets — small sample, flag for future |
| PACE=SLOW | 11.9% | negative | 168 bets — full Sunday card was SLOW bias |
| PACE=HOT | — | — | **Not yet tested — next stress test priority** |

**Standout winners (model correctly flagged HIGH GEMs pre-race):**
- JUST TAKE NOTES (GPX R4) — $30 WIN, SCORE=20, HIGH
- R J'S ICE (LRL R6) — $16.40 WIN, SCORE=18, HIGH

---

## KNOWN BUGS (Outstanding)

| Bug | Location | Impact | Fix |
|-----|----------|--------|-----|
| Exotic delimiter mismatch | `_grade_exotic_bets()` in horse_racing_grader.py | Splits on `,` but CSV stores as `HORSE A / HORSE B` — 3 EXACTA hits missed Apr 12 | Handle both: split on `,` OR ` / ` |
| Exotic payout data missing | grader + results parser | Exotic P&L is placeholder stake, not real payout — ROI math wrong | Subscribe to Brisnet XRD plan ($25/mo) |

---

## DATABASE TABLES

**bets** — straight bets ledger (53 real + stress_test rows tagged STRESS_TEST)

**parlays / parlay_legs** — multi-leg tracking

**horse_race_analyses** — every horse analyzed: scores, probabilities, recommendation, result after grading
Fields: id, date, track, race_number, race_type, distance, surface, horse_name, post_position, jockey, trainer, morning_line_odds, m01-m11, composite_score, model_win_pct, model_place_pct, model_show_pct, recommendation, result, finish_position, profit_loss, notes, created_at

**trainer_situational_stats** (82,197 rows) — builds automatically after every graded race
Fields: id, trainer_name, situation, starts, wins, places, shows, roi, last_updated
UNIQUE on (trainer_name, situation). 2023 Equibase data is Bayesian prior; live races build on top.

**jockey_stats** (1,135 rows) — ARM2026 meet win% per jockey

---

## SCRIPT REFERENCE (see PIPELINE_API.md for full signatures)

| Script | Purpose |
|--------|---------|
| brisnet_fetcher.py | `fetch_race_file`, `extract_zip`, `get_available_tracks` |
| horse_racing_parser.py | `parse_race_file` → `{race_num: [horse_dicts]}` |
| horse_racing_scorer.py | `score_race`, `generate_recommendation` (NO m05_override as of Apr 9) |
| horse_racing_simulator.py | `simulate_race` (10,000 trials) |
| horse_racing_grader.py | `grade_race`, `update_trainer_stats`, `get_leaderboard` |
| results_fetcher.py | `build_results_url`, `scan_and_grade_all`, `fetch_import_results_file` |
| stress_test_runner.py | Full-card pipeline; notes format locked Apr 12 |
| db_utils.py | `safe_write`, `safe_read`, `verify_db`, `get_pending_stress_test_count`, `delete_stress_test_bets` |

---

## BASKETBALL METRIC FRAMEWORK v2.0 (Retained for Reference — 9 Metrics)

| # | Metric | Weight |
|---|--------|--------|
| M1 | 3-Point Percentage | Standard |
| M2 | Win % in Context | Standard |
| M3 | Offensive Rebound Rate | Standard |
| M4 | Defensive Efficiency | Standard |
| M5 | Pace/Tempo (gap threshold >5 poss) | HIGH |
| M6 | Free Throw % (close games only) | Standard |
| M7 | Bench Depth | Standard |
| M8 | Sharp Money (required pre-bet check) | HIGH |
| M9 | Recent Form (last 5 ATS + scoring trend) | Standard |

---

## ON THE HORIZON

### Immediate (next session)
- Fix `_grade_exotic_bets()` delimiter bug
- Run first HOT pace scenario stress test (all graded cards so far have been SLOW/MIXED)
- Weekend stress test marathon (Apr 25-27) for fresh calibration data

### Short term
- Workflow diagram — map automated / human-decision / optimization-opportunity layers
- Load Full Card UI build (track checkboxes, GEM jump button, race countdown timers, pace badges)
- Brisnet XRD subscription for real exotic payouts
- Request 2024 Equibase data to upgrade M07 from prior to current-cycle ground truth

### Longer term
- Cloud-hosting for multi-device access
- Expansion: MLB, NFL/NCAAF, NBA — sport-specific metric frameworks feeding unified platform
- Racing API + racing-mcp-server integration
- Action Network PRO as sharp money supplement for M09

---

*EDGE Intelligence Platform | Built for Kyle Richey | kylerichey58 | Confidential*
