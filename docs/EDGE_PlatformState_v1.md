# EDGE_PlatformState_v1.md

**Living brain doc for the EDGE Intelligence Platform — horse-racing wing.**

This doc is the persistent memory for the build. It replaces snapshot handoffs going forward. Three rules:

1. **The doc is truth, the code is verification.** If they disagree, stop and reconcile before moving on.
2. **Don't bloat it.** Living reference, not a journal. Session Log entries are 2–3 sentences. Backlog is items, not narrative.
3. **One doc, not two.** Both Claude and Cowork read this same file. Audience-specific content gets a tagged subsection, never a separate doc.

End-of-session ritual: *"Update the brain doc with: what we accomplished, what changed in locked decisions or open issues, what's next."*
Start-of-session ritual: *"Read EDGE_PlatformState_v1.md and confirm context."*

---

## 1. Current state

### What's working
- Forward-scoring engine: `brisnet_fetcher.py → horse_racing_parser.py → horse_racing_scorer.py → horse_racing_simulator.py` runs end-to-end (commit `bc2b19e`).
- M05 fix in production: parser reads Brisnet field 209 directly with full vocab `{E, E/P, P, S, NA}`; scorer has E/P-aware pace classifier and NA-omit logic.
- Brain tables populated: `horse_race_analyses` (3,992 rows from May 1–2), `trainer_situational_stats` (82,197), `jockey_stats` (1,135).
- May 1 live run: 20 tracks, 187 races, 1,655 horses, 53 GEMs at 3.2% rate. Two-gate GEM definition validated.
- Trainer Scout tab UI structure correct, fires the right `/horse/simulate` POST, renders the right response shape.

### Actively being worked on
- **First task this session:** synthesize the May 6 handoffs into this brain doc, commit to `docs/EDGE_PlatformState_v1.md`. Then move to Phase 1.
- After the brain doc lands, Phase 1.1 begins. First implementation step is **P1 fix (Item 1)** — but only after deciding whether `/horse/simulate` retires under the new vision (card_runner pre-computation + GET endpoints).

### What's broken
- **P1** — `score_race(m05_overrides=...)` kwarg orphaned. Two callers crash on every request: `edge_server.py:389` and `stress_test_runner.py:99`. This is what makes Trainer Scout's Run Car Wash button return 500.
- **P5** — Result-ingestion pipeline never run end-to-end. `parse_chart_pdf`, grader's `horses_data` branch, `horse_profile_logic` all exist; no production caller passes `horses_data` to `grade_race()`. `horse_race_calls = 0`, `horse_profile = 0`. Resolves with `card_grader.py`.
- **Top half of dashboard is fictional.** Topbar live-stats, ticker, four stat cards, Recent Bets list, both charts — all read from a hardcoded 58-row basketball BETS array at `EDGE-Platform.html` L1245–1304. Nothing reads from `sports_betting.db`. Resolves with GET `/bets` + dashboard rewire (Item 17).
- See full P-item ledger in Section 5.

### Last session's accomplishments (May 6 audit + vision lock)
- Completed Platform Audit Phases A–D.1 plus UI Audit (Phase E pre-work). Mapped every gap between current state and target state.
- Locked all major architecture decisions with Kyle (folder structure, two-gate GEM location, WPS_ALL representation, `bet_source` auto-derive, Equibase as result source, `PIPELINE_API.md` retires).
- Generated two bridge handoff docs (Claude-side and Cowork-side) — last snapshots before brain doc takes over.

---

## 2. Locked decisions

These do not get re-litigated. If a decision is locked here, it gets followed.

### Vision & architecture
- **Folder structure** — `horse_racing_data/data/MMDDYY/` for Brisnet PPs, `horse_racing_data/results/MMDDYY/` for Equibase chart PDFs. Two roots, dated subfolders. No code change when adding a new day; Kyle just creates the folder and drops files.
- **UI shell** — Modify existing `EDGE-Platform.html`. Don't rebuild. Trainer Scout tab becomes the daily slate view. Other tabs extend to handle horse-racing data.
- **Track-code bridge** — Single shared dict `TRACK_CODE_BRIDGE` mapping Brisnet ↔ Equibase track codes. Identity for most tracks (`KEE→KEE`); explicit bridges for X-suffix family (`GPX→GP`, `OPX→OP`, `CTX→CT`). Both `card_runner.py` and `card_grader.py` reference it. ~20 entries to start.
- **Two-gate GEM location** — Set in the simulator AFTER confidence is computed. Scorer stays composite-aware; simulator finalizes `is_gem`.
- **WPS_ALL representation** — ONE row in `bets` table with `bet_type='WPS_ALL'`. Grader settles as combined W+P+S P&L. UI shows four-button bar `[Win] [Place] [Show] [All]` per horse.
- **bet_source** — Required column. Auto-derived as `ENGINE` if bet matches engine recommendation tier (GEM or STRONG); otherwise `OVERRIDE`. UI shows simple Engine/Override toggle that engine pre-selects, Kyle flips with one click.
- **Brain enrichment** — Wired from day one. `update_trainer_stats` fires per horse; `update_horse_profiles` fires per race. Every graded card makes tomorrow's Car Wash smarter.
- **Result source** — Equibase chart PDF only. Kyle handles downloads. `results_fetcher.py` retires. Brisnet $0.75 paid CSV path retires.
- **Bankroll/stock view** — Deferred. Existing Unit Portfolio chart inherits horse-racing data once bets flow.
- **Pick sheets** — Phase 3. Matures from `_scratch/build_carwash_report_05_02.py` into a checked-in `reports/` module.
- **Two-product split (basketball)** — Deferred. Basketball stays dormant in same shell. Decision revisits before 2026–27.

### Doctrine (mirrors PHILOSOPHY.md, source of truth is code)
- **P1 — Engine surfaces edges, bettor decides.** No hard engine vetoes based on a single metric.
- **P2 — M09=0 is a flag (`M09!`), not a veto.** Bettor's rule, not engine logic. Shipped commit `5c01240`, April 30, 2026.
- **P3 — Per-sport architecture.** Each sport: own tab, own schema, own tracker.
- **P4 — Calibrate forward only.** No leaky calibration. Brain versions checkpointed (mechanism not yet built).
- **P5 — Brain learns continuously.** Each graded race contributes.
- **P6 — Manual placement is permanent.** No automated bet placement, ever.
- **P7 — Bets tagged ENGINE or OVERRIDE.** Auto-derived; one-click flip in UI.
- **P8 — Per-sport P&L with aggregate rollup.**
- **P9 — No frozen rules from small samples.** (Current ticker violates this with "ML LEGS — AVOID" and "FINAL FOUR — TOTALS FIRST" from N=3 pre-reform losses. Stale; cleanup in Item 18.)

### Documentation
- **`PIPELINE_API.md`** retires. This brain doc replaces it as canonical state reference.
- **`CLAUDE.md`** keeps existing scope (operational reference for Cowork patterns: HOW Cowork works). This brain doc is WHAT we're building. Distinct, cross-reference.
- **`PHILOSOPHY.md`** keeps existing. Brain doc references rather than duplicates.
- **`SANDBOX_CAPABILITY.md`** — folded into Section 7 of this doc. Standalone doc retires.

---

## 3. Active backlog

Phase 1 = daily loop end-to-end. Phase 2 = visibility. Phase 3 = calibration & roadmap.

### Phase 1.1 — Daily loop infrastructure
- [ ] **Item 1** — Fix `score_race(m05_overrides=)` callers (P1). Three lines at `edge_server.py:389` and `stress_test_runner.py:99`. **Decide first:** does `/horse/simulate` retire under the new vision (card_runner pre-computation)?
- [ ] **Item 2** — Build `TRACK_CODE_BRIDGE` dict. Single source of truth. ~20 entries. Both `card_runner.py` and `card_grader.py` reference it.
- [ ] **Item 3** — Build `card_runner.py`. Walks `horse_racing_data/data/MMDDYY/`, runs parser → scorer → simulator per race, writes `horse_race_analyses` via `safe_write`. Replaces `stress_test_runner.py`.
- [ ] **Item 4** — Add `CREATE TABLE` for `horse_race_calls` and `horse_profile` to `_ensure_horse_tables()` and `_scratch/db_recovery.py` (P6).
- [ ] **Item 5** — Build `card_grader.py`. Walks `horse_racing_data/results/MMDDYY/`, calls `parse_chart_pdf`, `grade_race(horses_data=...)`, fires `update_trainer_stats` per horse and `update_horse_profiles` per race. Resolves P5.
- [ ] **Item 6** — Make `edge_server._log_analyses` populate `confidence_tier` and `value_flag` (P2) and route through `safe_write` (P7).

### Phase 1.2 — Backend endpoints
- [ ] **Item 7** — `GET /horse/cards` — list of dates with parsed data ready.
- [ ] **Item 8** — `GET /horse/cards/<date>` — tracks + races for that date.
- [ ] **Item 9** — `GET /horse/race/<date>/<track>/<n>` — per-race detail (read from `horse_race_analyses`, NOT recomputed).
- [ ] **Item 10** — `POST /bets/log` — log W/P/S/WPS_ALL bet; auto-derives `bet_source`.
- [ ] **Item 11** — `GET /bets` — list bets with sport filter.
- [ ] **Item 12** — `GET /stats/summary` — aggregated dashboard numbers per sport.

### Phase 1.3 — UI rewiring
- [ ] **Item 13** — Promote purple ladder to CSS variables `--purple`, `--purple-light`, `--purple-fade`.
- [ ] **Item 14** — Trainer Scout redesign: Date → Track → Race # → race view with horses + W/P/S/All bar + Engine/Override toggle. Replace per-race "Run Car Wash" form.
- [ ] **Item 15** — LOG BET tab: replace EXACTA/TRIFECTA pills with W/P/S/WPS_ALL. Add `bet_source` toggle.
- [ ] **Item 16** — BET TRACKER tab: add HORSE filter. Branch render mode for horse rows.
- [ ] **Item 17** — DASHBOARD rewire: `buildDashboard`, `buildTopbarStats`, `buildTicker`, `renderTracker`, `initCharts` pull from `GET /bets` instead of hardcoded `BETS` array. Drop the 58-row fixture.
- [ ] **Item 18** — Stale cleanup: M05 manual dropdown, ZIP hint text, ML AVOID slogans, $20-vs-$100 unit-size discrepancy, basketball-coded checklist, EXACTA/TRIFECTA pills, Sizing Guidelines warning.

### Phase 2 — Visibility
- [ ] **Item 19** — Bankroll / stock view wired to horse-racing data.
- [ ] **Item 20** — End-of-day P&L report endpoint.
- [ ] **Item 21** — UI auto-refresh after results land.

### Phase 3 — Calibration & roadmap
- [ ] **Item 22** — Calibration loop: compare `model_win_pct` vs actual `finish_position` across rolling windows.
- [ ] **Item 23** — Brain versioning checkpoint mechanism (PHILOSOPHY P4).
- [ ] **Item 24** — Pick sheets module: promote `_scratch/build_carwash_report_05_02.py` to `reports/`.
- [ ] **Item 25** — Future M-metrics consuming `horse_profile` (M12, M13, M14).
- [ ] **Item 26** — Cloud hosting (Railway / Render / DigitalOcean) when local build is solid.

### Pre-anything
Before starting Phase 1, Kyle cleans the working tree from VS Code terminal:
```
git reset --mixed HEAD && git add .
```

---

## 4. Key reference

### Constants

| Item | Value |
|---|---|
| Unit size | 1u = $100 |
| Standard sizing | 0.5–1.0u, up to 2.0u for high-confidence GEMs |
| GEM threshold | composite ≥ 18 AND HIGH confidence (two-gate) |
| Composite max | **33** (NOT 27 as stale docs claim) |
| Metrics | **M01–M11** (NOT M01–M09 as stale docs claim) |
| Monte Carlo trials | 10,000 per race |
| Brisnet field for run style | `F_RUN_STYLE = 209` with vocab `{E, E/P, P, S, NA}` |
| Pre-reform baseline | 53 bets · 29W-23L-1P · 55.8% WR · +2.94u Totals · +11.4% ROI |
| May 1–2 slate | 3,992 horses · 461 races · 49 (date,track) pairs · 271 GEMs |
| Brisnet account | kylerichey58 · $125/month Data Plan |
| Backend port | 5050 (Flask) |
| Frontend port (local) | 8080 |
| Live URL | https://kylerichey58.github.io/edge-betting/EDGE-Platform.html |
| Repo | github.com/kylerichey58/edge-betting |
| Bookmakers | TwinSpires, FanDuel (manual placement only) |
| Fonts | Rajdhani (display) / IBM Plex Sans (body) / IBM Plex Mono (data) |
| Purple ladder | `#7B3FBE` / `#a78bfa` / `#6b46c1` / `#1a0e22` |

### File structure (target)

```
C:\Users\kyler\Documents\Sportsbetting\
├── edge_server.py               # Flask backend, port 5050
├── EDGE-Platform.html           # 3,641-line single-file SPA
├── sports_betting.db            # SQLite, 10 tables
├── brisnet_fetcher.py           # Forward chain
├── horse_racing_parser.py
├── horse_racing_scorer.py
├── horse_racing_simulator.py
├── horse_racing_pdf_parser_v2.py  # Result chain
├── horse_racing_grader.py
├── horse_profile_logic.py
├── card_runner.py               # TO BUILD (Item 3)
├── card_grader.py               # TO BUILD (Item 5)
├── horse_racing_data/
│   ├── data/MMDDYY/             # Brisnet PPs
│   └── results/MMDDYY/          # Equibase chart PDFs
├── docs/
│   └── EDGE_PlatformState_v1.md # this doc
├── _archive/                    # 19 files, basketball-era, zero deps
└── _scratch/                    # 46 entries, zero deps
```

Retiring: `index.html` (33-day-old GitHub Pages mirror), `results_fetcher.py`, `stress_test_runner.py`, `PIPELINE_API.md`.

### Schema (SQLite, 10 tables)

| Table | Status | Rows | Notes |
|---|---|---|---|
| `horse_race_analyses` | Active | 3,992 | All May 1–2; all `finish_position=NULL` (never graded) |
| `trainer_situational_stats` | Active | 82,197 | ARM 2026 historical seed; brain memory for M07 |
| `jockey_stats` | Active | 1,135 | Brain memory for M08 |
| `bets` | Empty | 0 | Post-reform; awaits new `POST /bets/log` |
| `horse_race_calls` | Empty | 0 | No DDL in production code (P6) |
| `horse_profile` | Empty | 0 | No DDL in production code (P6); per-horse aggregates |
| `betting_stats` | Orphan | — | D-ledger flagged; not referenced |

### Pipelines

```
Forward:  brisnet_fetcher → horse_racing_parser → horse_racing_scorer
                          → horse_racing_simulator (Monte Carlo, permanent Step 2.5)
                          → horse_race_analyses

Result:   Equibase PDF → horse_racing_pdf_parser_v2.parse_chart_pdf
                       → horse_racing_grader.grade_race(horses_data=...)
                       → horse_race_analyses (finish_position) + bets (settlement)
                                + horse_race_calls + horse_profile
                                + trainer_situational_stats
```

### Key file paths and line numbers

| Reference | Location |
|---|---|
| Hardcoded BETS array (to drop) | `EDGE-Platform.html` L1245–1304 |
| CSS variables block | `EDGE-Platform.html` L23–35 |
| M05 manual dropdown (stale) | `EDGE-Platform.html` L1138–1146 |
| Stale ZIP hint text | `EDGE-Platform.html` L1129 |
| Bankroll $20 default (wrong) | `EDGE-Platform.html` L1312 |
| Bet Tracker filter row (add HORSE) | `EDGE-Platform.html` L997–1000 |
| EXACTA/TRIFECTA pills (stale) | `EDGE-Platform.html` L911–912 |
| Pre-Bet Checklist (basketball) | `EDGE-Platform.html` L984–989 |
| Sizing Guidelines table (stale) | `EDGE-Platform.html` L972–983 |
| `score_race` crash site #1 | `edge_server.py:389` |
| `score_race` crash site #2 | `stress_test_runner.py:99` |

### Endpoint contract (current + target)

Current routes in `edge_server.py`: `/health`, `/horse/tracks`, `/horse/simulate` (broken P1, may retire), `/horse/grade`.

New endpoints to build:
- `GET /horse/cards` → `[{date, n_tracks, n_races}]`
- `GET /horse/cards/<date>` → `[{track, races: [n, ...]}]`
- `GET /horse/race/<date>/<track>/<n>` → `{race_meta, horses: [{name, m01..m11, composite, win_pct, place_pct, show_pct, confidence, is_gem, recommendation}]}` — read-only from `horse_race_analyses`
- `POST /bets/log` → body `{sport, date, track, race_number, horse_name, bet_type ∈ {W,P,S,WPS_ALL}, units, bet_source}`; auto-derive `bet_source`
- `GET /bets?sport=horse` → list with filtering
- `GET /stats/summary?sport=horse` → aggregated W/L/units for dashboard

---

## 5. Open issues ledger

### P-items (production)

| ID | Severity | Description | Status |
|---|---|---|---|
| **P1** | Tier 0 | `score_race(m05_overrides=)` kwarg orphaned; two callers crash | **OPEN** — Item 1 |
| **P2** | Tier 1 | `_log_analyses` doesn't write `confidence_tier` or `value_flag` | **OPEN** — Item 6 |
| **P3** | Tier 1 | `is_gem` single-gate in production scorer (two-gate only in scratch) | **OPEN** — superseded by locked decision (gate moves to simulator) |
| **P4** | Tier 1 | M09 doctrine inconsistency: scorer says veto, simulator says flag | **OPEN** — simulator wins per PHILOSOPHY P2; reconcile in code |
| **P5** | Tier 0 | Result-ingestion pipeline never run end-to-end | **OPEN** — Item 5 |
| **P6** | Tier 1 | Missing DDL for `horse_race_calls` and `horse_profile` | **OPEN** — Item 4 |
| **P7** | Tier 1 | `edge_server` bypasses `safe_write` (race condition) | **OPEN** — Item 6 |
| **P8** | Tier 2 | No UNIQUE constraint on `(track, date, race_number, horse_name)` | **OPEN** — duplicate risk on re-runs |
| **P9** | Tier 1 | `PIPELINE_API.md` ~25% accurate | **SUPERSEDED** by locked decision (doc retires) |

### D-items
The audit produced ~60 D-items numbered D1–D61 covering schema drift, dead code, and doctrine inconsistencies. Tier 0/1 surfaced as P-items above. Tier 2–3 items deferred until Phase 1 ships. Full ledger lives in the May 6 transcript; surface here only as we encounter or close them.

Notable D-items already surfaced:
- **D16** — Five different date conventions across DB. Working toward consolidation.
- **D-archive** — `_archive/` (19 files) and `_scratch/` (46 entries) have zero code dependencies. Confirmed orphans.

---

## 6. Session log

### 2026-05-06
Audit complete (Phases A through D.1). UI audit (Phase E pre-work) complete. Vision locked across all major decisions. Two bridge handoff docs generated (Claude-side, Cowork-side) — last snapshots before brain doc takes over.

### 2026-05-01
First live run on May 1 slate: 20 tracks, 187 races, 1,655 horses, 53 GEMs at 3.2%. Monte Carlo confirmed as permanent Step 2.5. Sandbox Limitation #8 documented; NTFS DB latency workaround standardized. Commit `bc2b19e`.

### 2026-04-30
M05 fix shipped (commit `bc2b19e`). Parser reads Brisnet field 209 directly with full vocab `{E, E/P, P, S, NA}`; scorer gets E/P-aware pace classifier, new M05 matrix, NA-omit logic. Process rule locked: work one step at a time.

---

## 7. Sandbox & workflow notes

### Cowork sandbox limitations
- **Limitation #8 — NTFS truncation.** File edits on `Sportsbetting/` and `outputs/` paths can show stale or truncated content via bash `cat` after writes. **Workaround:** heredoc to `/tmp/`, then PowerShell copy back. Self-contained PowerShell scripts that Kyle runs and pastes output back is the primary verification pattern.
- **DB latency.** NTFS read latency on `sports_betting.db` exceeds 45 seconds. **Workaround:** stage `sports_betting.db` to `/tmp/sports_betting.db` with a monkey-patch on `DB_PATH`, run operations, copy back.
- **No `~/Downloads` access** from Cowork sandbox. Anything calling `auto_move_downloads` fails in sandbox; works on Kyle's local Windows shell.
- **No git push.** All git operations are Kyle's responsibility. Cowork can read git state and stage edits; Kyle commits and pushes.
- **Chrome MCP first-touch.** Any new domain navigation requires Kyle watching the Chrome window for the approval prompt.
- **Network egress (Python `requests`).** Working: Anthropic API, Brisnet authenticated session, Odds API. No general internet egress beyond what's been used; assume new domains need testing first. Brisnet results page in particular has been flaky — that's the current motivator for moving to Equibase PDFs.
- **Classifier hazards.** Cowork's classifier triggers on language like "bypass", "chunked reads", "evade filter". Avoid those phrasings in prompts even when describing legitimate workarounds. Describe what to do, not what to circumvent.

### Process rules
- **One step at a time.** No batching multi-step plans. Each step gets discussed, executed, verified, then we move on. Don't restate the whole sequence at every step.
- **Claude drafts every Cowork prompt.** Kyle never writes prompts to Cowork directly — he relays Claude's prompts.
- **Cowork output goes back to Claude.** Kyle pastes Cowork's output for the next planning step.
- **Surface ambiguity, don't guess.** When Cowork is unsure about scope or whether something violates a locked decision, present 2–3 options and ask. No architectural guesses.

### Cowork prompt envelope
```
Goal: <one-line objective>
Context: <current state, what just happened>
What to do: <numbered or sub-pointed steps>
Deliverable: <exact format expected back>
Guardrails: <what NOT to do, sandbox limitations to honor>
```

### Cross-reference docs
- **`PHILOSOPHY.md`** — operating principles. ~80% accurate. Code is truth where they disagree.
- **`CLAUDE.md`** — operational reference for Cowork patterns. ~70% accurate; M01–M09 / 0–27 framing is wrong (should be M01–M11 / 0–33).
- **`Chart_Parser_Technical_Reference.md`** — ~85% accurate.
- **`PIPELINE_API.md`** — RETIRING. Don't reference.
- **`SANDBOX_CAPABILITY.md`** — RETIRING. Folded into this section.

---

*End of EDGE_PlatformState_v1.md.*
