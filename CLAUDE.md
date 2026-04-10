# EDGE Intelligence Platform — Cowork Permanent Context
*Last updated: April 10, 2026 | Horse Racing Wing: Production Ready*

---

## PLATFORM OVERVIEW

EDGE is a personal sports betting analytics platform built by Kyle Richey. Single-source intelligence tool — games and races are run through a metric framework and AI pipeline, structured bet recommendation comes out. Human always places bets manually on DraftKings. Automation is permanently off the table.

**Live URL:** https://kylerichey58.github.io/edge-betting/EDGE-Platform.html
**Local test:** `python -m http.server 8080` → localhost:8080/EDGE-Platform.html
**Branch:** main — GitHub Pages auto-deploys on push
**Push command:** `git push origin main --force` (from VS Code terminal, never Cowork)
**Latest commit:** f360889

---

## CURRENT PLATFORM STATS (as of April 10, 2026)

| Metric | Value |
|--------|-------|
| Overall Record | 29W-23L-1P (55.8% WR, -0.87u straight bets) |
| Totals | 12W-8L, 60.0% WR, +2.94u, +11.4% ROI — PRIMARY EDGE |
| Spreads | 16W-11L, -1.47u, -6.1% ROI (juice drag) |
| Parlays | 1W-9L, -6.54u — ACTIVE but spread legs only |
| Best Unit Tier | 0.5-1.0u at 57.1% WR / +5.86u |
| Graded Bets in DB | 53 total in sports_betting.db |

---

## FILE STRUCTURE

```
C:\Users\kyler\Documents\Sportsbetting\
  EDGE-Platform.html         — main platform, all tabs, full JS
  index.html                 — GitHub Pages entry point mirror
  .env                       — API keys (NEVER commit this)
  .gitignore                 — excludes .env, sports_betting.db, _archive/
  CLAUDE.md                  — this file — Cowork permanent context
  BETTING_MODEL_GUIDE.md     — reference doc
  sports_betting.db          — SQLite database, 53 graded bets
  bet_tracker.py             — primary bet logging (8-option menu)
  bet_analytics.py           — terminal analytics dashboard
  bet_repair.py              — database repair utility
  major_conference_analyzer.py
  ncaam_scout.py / ncaaw_scout.py
  womens_basketball_analyzer.py
  horse_racing_data/         — NEW: Brisnet data files folder
    README.txt               — naming conventions
  brisnet_fetcher.py         — NEW: downloads Brisnet PP files
  horse_racing_parser.py     — NEW: parses .drf CSV to horse dicts
  horse_racing_scorer.py     — NEW: 11-metric scoring engine
  horse_racing_simulator.py  — NEW: Monte Carlo simulation
  horse_racing_grader.py     — NEW: grades results + builds trainer DB
  _archive/                  — 19 archived files
```

**API Keys in .env:**
- ANTHROPIC_API_KEY
- ODDS_API_KEY
- BRISNET_USERNAME (kylerichey58)
- BRISNET_PASSWORD

---

## TECH STACK

- EDGE-Platform.html — single-file HTML/JS dashboard
- Chart.js for visualizations
- Dark navy/teal design — Bebas Neue, JetBrains Mono, Outfit fonts
- sports_betting.db — SQLite with tables: bets, parlays, parlay_legs, horse_race_analyses, trainer_situational_stats

---

## COWORK WORKFLOW (PERMANENT RULES)

| Who | Does What | Never Does |
|-----|-----------|------------|
| Kyle | Decides track + race. Reviews output. Places bets manually on DraftKings. | Never lets automation place bets |
| Claude.ai | Strategy, architecture, all Cowork prompts written here first | Never writes directly to files |
| Cowork | All file creation and edits in SportsBetting folder. Confirms by pasting raw line content or test output. | Never pushes to GitHub — network sandbox blocks it |
| VS Code Terminal | All git operations: git add, git commit, git push origin main --force | Never edits files — git only |

**Git lock fix:** `del .git\HEAD.lock` and `del .git\index.lock`
**Local test:** Always test at localhost:8080 before checking GitHub Pages — CDN caches stale versions.
**CLAUDE.md:** Only update when model rules fundamentally change.

---

## MODEL RULES — NEVER CHANGES

- **Totals are the primary edge** — 65.2% WR, +22.3% ROI. Size up on totals.
- **Never bet moneyline** — 0% hit rate established across model history
- **Parlays: spread legs only** — moneyline legs prohibited by historical data
- **Optimal unit sizing is 0.5–1.0u** — highest ROI tier; up to 2.0u for gems with HIGH confidence
- **4-star gem threshold (basketball)** = 6+ of 9 metrics aligned
- **Sharp money is a required pre-bet check** — HIGH weight in v2.0
- **Human always places the bet** — no automated placement ever
- **The engine is the product** — metric framework is the edge

---

## BASKETBALL METRIC FRAMEWORK v2.0 (9 Metrics)

| # | Metric | Weight |
|---|--------|--------|
| M1 | 3-Point Percentage | Standard |
| M2 | Win % in Context | Standard |
| M3 | Offensive Rebound Rate | Standard |
| M4 | Defensive Efficiency | Standard |
| M5 | Pace/Tempo — gap threshold >5 possessions | HIGH |
| M6 | Free Throw % — close games only (spread <5) | Standard |
| M7 | Bench Depth — context flag | Standard |
| M8 | Sharp Money — required pre-bet check | HIGH |
| M9 | Recent Form — last 5 games ATS + scoring trend | Standard |

---

---

# HORSE RACING WING — PRODUCTION STATUS
*Last updated: April 7, 2026 | Status: PRODUCTION READY — All 9 checkpoints green*

---

## THE CAR WASH PIPELINE — 5 SCRIPTS

- **brisnet_fetcher.py** — Downloads/extracts Brisnet ZIPs, detects DRF files, feeds parser. Auto-scans Downloads folder for new ZIPs on every call.
- **horse_racing_parser.py** — Parses DRF comma-delimited format into horse dicts. 17 metrics per horse. 17/17 assertions pass.
- **horse_racing_scorer.py** — Scores horses on 11 metrics (M01-M11). Returns composite score, GEM flag (>=18 HIGH), NO-PLAY flag (M09=0 absolute veto).
- **horse_racing_simulator.py** — Monte Carlo 10,000 trials. Returns win/place/show%, value flags, recommendation (WIN_BET/EXACTA_BOX/TRIFECTA_KEY/NO_PLAY).
- **horse_racing_grader.py** — Post-race grading. Updates horse_race_analyses, logs to bets table, upserts trainer_situational_stats.
- **results_fetcher.py** — Fetches + parses Brisnet Instant Results HTML, auto-grades all DB rows for that card, updates P&L. Supports real Brisnet format and legacy test format.

---

## THE BACKEND SERVER

- **File:** edge_server.py
- **Port:** 5050
- **Routes:**
  - `GET /health` → `{"status":"ok"}`
  - `GET /horse/tracks` → dynamic list of available DRF files
  - `POST /horse/simulate` → runs full Car Wash pipeline, returns simulation_results + recommendation
  - `POST /horse/grade` → calls grade_race(), returns graded results

---

## THE DATABASE — sports_betting.db

- **horse_race_analyses** — stores every simulation run, updated after grading
- **trainer_situational_stats** — builds over time with every graded race. M07 scorer reads this. Currently empty — activates after first real graded races.
- **bets table** — horse racing bets logged with sport=HORSE_RACING

---

## BRISNET FILE FORMAT

- ZIP naming: `{TRACK}{MMDD}n.zip` (ex: GPX0409n.zip, MVR0407n.zip)
- DRF naming inside ZIP: `{TRACK}{MMDD}.DRF` (ex: GPX0409.DRF)
- Drop ZIP in Downloads/ or horse_racing_data/ — auto-extracted on next call
- Track code is parsed from filename — no hardcoded lookup table needed

---

## 11-METRIC FRAMEWORK v1.0

Each metric scores 0-3. Maximum composite = 27. Gem threshold = 18+.

| # | Metric | Type | Score 3 | Score 0 |
|---|--------|------|---------|---------|
| M01 | Speed Figure Trajectory | VALIDATOR | All 3 figures improving | No figures (first timer = 1 neutral) |
| M02 | Class-Adjusted Figure | VALIDATOR | Best figure 5+ pts above field avg | 10+ pts below field avg |
| M03 | Class Direction + Intent | VALIDATOR | Tactical drop in class | Massive step up MCL/CLM to ALW or STK |
| M04 | Surface & Distance Fit | VALIDATOR | Won on today's surface + similar distance in last 3 | Surface AND distance switch simultaneously |
| M05 | Pace Scenario | ENGINE | Perfect pace setup — lone speed or ideal stalker | No pace advantage — caught in speed duel |
| M06 | Form Cycle Position | ENGINE | Peaking — consistent improving form, no peak effort yet | Bounce risk — career peak last out |
| M07 | Situational Trainer ROI | ENGINE | 20%+ win rate in this exact situation, 10+ starts | Under 10% win rate |
| M08 | Jockey Switch Signal | ENGINE | Clear upgrade — top jockey (20%+ meet win rate) first time | Downgrade — previous jockey had higher meet win% |
| M09 | Odds Value Gap | VALIDATOR | Model win% exceeds market implied% by 8+ pts | Model win% BELOW market — NO PLAY |
| M10 | Equipment & Medication Flag | MULTIPLIER | First Lasix + strong trainer ROI (M07 >= 2) | No changes |
| M11 | Layoff Cycle Position | MULTIPLIER | 2nd race back after 45-180 day layoff — sweet spot | 180+ day layoff first race back |

**Key Scoring Rules:**
- Gem threshold: composite score >= 18 out of 27
- **AUTO NO-PLAY: M09 = 0 regardless of all other scores — no exceptions**
- Auto-fade signal: M06 = bounce risk AND M09 = 0 simultaneously
- M05 is the ONLY manual input — requires 60-second human read of running lines
- M07 defaults to 1 (neutral) until trainer_situational_stats has 10+ starts in situation
- M09 defaults to 1 (neutral) if Odds API call fails — never blocks a bet on a data error
- M10 and M11 are multipliers — amplify signal but do NOT override M09 veto

---

## THE UI TAB

- **Tab:** Trainer Scout in EDGE-Platform.html
- **Tab id:** `tab-trainerscout`
- **Position:** after Game Scout, before Parlay Builder
- **Accent color:** `#7B3FBE` purple
- Dynamic track dropdown — loads from `GET /horse/tracks`
- Car Wash table with color-coded Value and Flag columns
- Log This Bet pre-fills bet tracker
- Grade This Race calls `POST /horse/grade`

---

## TO START THE PLATFORM

| Step | Command |
|------|---------|
| Terminal 1 | python edge_server.py |
| Terminal 2 | python -m http.server 8080 |
| Browser | localhost:8080/EDGE-Platform.html |
| Tab | Trainer Scout → hit ↺ Refresh |

## DAILY RACE DAY WORKFLOW

### PRE-RACE (45 min before post)
1. Download Brisnet ZIP for target track from brisnet.com
2. Drop ZIP in Downloads folder — auto-extracted on Refresh
3. Open Trainer Scout tab → select track → enter race number
4. Run Car Wash → review recommendation → place bet on DraftKings

### POST-RACE (after card finishes)
Tell Cowork: "Fetch results for {TRACK} {DATE}"
Cowork navigates to:
https://www.brisnet.com/product/download/{YYYY-MM-DD}/INR/USA/TB/{TRACK}/D/0/
Saves HTML to horse_racing_data/{TRACK}{MMDD}_results.html
Runs: python results_fetcher.py
All bets auto-graded, P&L updated, trainer stats built

## BRISNET URL PATTERNS

| File Type | URL Pattern |
|-----------|-------------|
| Instant Results (free) | https://www.brisnet.com/product/download/{YYYY-MM-DD}/INR/USA/TB/{TRACK}/D/0/ |
| PP Download (your $125 plan) | brisnet.com → Data Files → PP Multi → select track/date |
| Import Results ($0.75) | brisnet.com → Results → Import Results Files → select track/date |

## TRACK CODE MAP (DRF filename → Brisnet results URL)

| DRF Code | Brisnet Code | Track |
|----------|-------------|-------|
| GPX | GP | Gulfstream Park |
| MVR | MVR | Mahoning Valley |
| KEE | KEE | Keeneland |
| CD | CD | Churchill Downs |
| SA | SA | Santa Anita |
| SAR | SAR | Saratoga |
| BEL | BEL | Belmont |
| AQU | AQU | Aqueduct |
| DMR | DMR | Del Mar |
| FG | FG | Fair Grounds |
| TAM | TAM | Tampa Bay Downs |
| TP | TP | Turfway Park |
| LRL | LRL | Laurel |
| PIM | PIM | Pimlico |
| OP | OP | Oaklawn |

---

## NEXT SESSION FOCUS

- First live race card test with real Brisnet DRF data
- Kyle has ideas and enhancement questions to discuss
- Trainer stats database will start building after first graded races
- M07 metric activates with real data — model gets sharper over time

---

## HORSE RACING BETTING RULES (PERMANENT)

- **Human places all bets manually on DraftKings Racing — automation permanently off the table**
- **M09 = 0 → absolute NO-PLAY, no exceptions, no override**
- **Never bet moneyline**
- Unit sizing: 0.5-1.0u standard, 2.0u max for GEM + HIGH confidence only
- Always localhost:8080 before GitHub Pages — CDN caches stale versions
- Cowork never pushes to GitHub — all git ops in VS Code terminal only

---

## DATA SOURCES

**Primary: Brisnet** (account: kylerichey58, Data Plan active $125/month)
- PP Single File (.drf) — $1.50/card — powers all 11 metric inputs — use for every race analyzed
- Early Track Data (ETD) — $0.75/card — optional morning preview
- Comprehensive Chart Files — $74.95/month plan — post-race results, builds trainer DB
- Exotic Results (XRD) — $25/month plan — exacta/trifecta payouts for ROI grading

**Supporting:**
- The Odds API — already integrated, key in .env — live win/place/show odds for M09
- Horse Racing USA (RapidAPI) — free tier, coverage gaps — backup only
- Equibase.com — DO NOT SCRAPE — ToS explicitly prohibits automated access

---

## FUTURE ROADMAP (Do Not Build Yet)

- The Racing API + racing-mcp-server (github.com/mohsinm-dev/racing-mcp-server) — when Racing API subscription added
- Action Network PRO — sharp money supplement for M09
- Betfair Exchange API — lay betting as sharp money proxy
- Model calibration sprint after 25 graded races
- Data monetization: trainer situational ROI DB, track bias reports

---

*EDGE Intelligence Platform | Built for Kyle Richey | kylerichey58 | Confidential*
