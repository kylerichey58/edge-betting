# EDGE Intelligence Platform — Design Philosophy

*Established: April 25, 2026*
*Author: Kyle Richey, with Claude*
*Status: Governing reference document*

---

## What This Document Is

This is the **governing reference** for every architectural and analytical decision made in the EDGE Intelligence Platform. When a future decision is being made — adding a metric, retiring a metric, adjusting a weight, building a new sport wing, designing a new feature — this document is the source of truth for *why* the platform works the way it does.

If something proposed conflicts with the principles here, the proposal needs to be rejected, modified, or this document needs to be updated explicitly. No drift by accumulation.

This document overrides any conflicting guidance in CLAUDE.md, handoff docs, or session notes.

---

## What This Platform Is

EDGE Intelligence Platform is a **multi-sport edge-detection engine**. It analyzes events using sport-specific frameworks, finds situations where the books have mispriced probability, and surfaces those edges to a human bettor who decides what to act on.

The platform is **not** a bet-logger with analytics bolted on. It is an analytical engine with bet-logging bolted on. The center of gravity is in the analytical brain, not in the bet record. This distinction matters because it shapes every design decision: what gets stored, what gets displayed, what gets prioritized, what gets cleaned up.

---

## Core Principles

### 1. The engine is unbiased

The engine has no opinions about bet types. It does not refuse to surface moneyline edges. It does not declare totals "the primary edge." It does not blacklist parlays. It looks at math — probability vs. price — and surfaces mispricings wherever they exist.

Frozen rules from small samples (n=3, n=10, n=23) are not analytical conclusions. They are inherited bias. The platform actively rejects this pattern. If a bet type is unprofitable, it shows up as unprofitable in calibration data — at which point we have evidence, not a rule.

### 2. The engine is ruthless on the books

The engine's job is to be colder than the books are about specific situations. Books make money on volume and on bettors who chase narratives. The engine wins by being more disciplined about probability than the market is about price. When the math says a 28% chance and the book is selling 18% implied, that's the gap the engine exists to find.

The engine does not care about "value" in a vague sense. It cares about quantified edge.

### 3. The brain is per-sport

Each sport is an independent wing of the platform with its own metric framework, its own data tables, its own calibration record, its own versioned releases. Edges live in sport-specific structure — pace dynamics in basketball, situational trainer ROI in horse racing, weather and rest in football, bullpen fatigue in baseball. A unified "metrics across sports" model would dilute every sport's analytical sharpness.

Wings share infrastructure (database, safe-write utilities, UI shell, API integrations) but never share analytical logic.

### 4. The brain learns continuously, but versions are checkpointed

The brain is never "done." Every analyzed event with a known result feeds the relevant sport's data tables. Trainer stats, jockey stats, situational performance, calibration buckets — all grow with every graded event.

But versions are marked. "Horse Racing Car Wash v1.0," "Basketball Scout v2.0." A version represents a locked framework structure — the metrics, weights, and scoring logic are fixed at that point. Calibration data accumulates against that version. When the framework itself changes (new metric, retired metric, reweighted metric), a new version is declared, and calibration data is tracked separately so we can compare versions empirically.

### 5. The brain doesn't need bets to learn

Most retail betting platforms only learn from logged bets. This platform learns from every analyzed event, regardless of whether a bet was placed. Every horse scored and graded contributes to trainer/jockey databases. Every game projected and resolved contributes to calibration buckets.

This is the platform's structural advantage. Bets are a side stream, not the primary data flow.

### 6. The bettor is the judgment layer

The engine surfaces edges. The bettor decides what to act on. The engine never:

- Refuses to surface a bet type
- Enforces sizing rules (it suggests; the bettor decides)
- Auto-places bets (manual placement is permanent)
- Blocks the bettor from going against the model

The bettor's role is execution, judgment, and risk management. The engine's role is information.

### 7. Bets are tagged, tracked, and weighted minorly

When a bet is logged, it is tagged with its source: ENGINE (followed the model's recommendation) or OVERRIDE (went against the model on judgment, with optional reason).

This serves two purposes. First, it produces a separate calibration record over time: do gut overrides add edge or subtract it? Second, it keeps the data flow honest — the engine learns from event outcomes (large sample), and only minorly from bet outcomes (smaller sample). Bets do not drive the engine's evolution. Events do.

### 8. P&L is per-sport, with aggregate rollup

Each sport tracks its own P&L. There is also an aggregate "all sports" view. This matters because each sport's brain has its own development arc — horse racing might be at v2.0 while NFL is still at v0.5 — and mixing their P&L into a single number obscures whether each individual brain is actually performing.

### 9. The forbidden patterns

The platform actively rejects these patterns:

- Frozen rules derived from small samples
- "Permanent rules" that are actually inherited analytical bias
- Universal cross-sport metrics that ignore sport-specific structure
- Auto-placement of bets
- Conflating event analysis with bet logging
- Drift in CLAUDE.md or handoff docs that contradicts this document without explicit update

### 10. The kept rules (operational only)

Some rules are genuinely permanent. They are operational, infrastructure, or risk-management — never analytical:

- Human places all bets manually on DraftKings
- 1 unit = $100 (standardized for math and industry alignment)
- Sizing cap: 1u standard, up to 2u on highest-conviction situations
- Sport-specific sharp money treatment: heavy weight in basketball/football/baseball (where lines move on professional money), de-emphasized in horse racing (where pari-mutuel pools change constantly)
- Database safe-write protocol via db_utils.safe_write()
- Cowork never pushes to git; VS Code terminal handles all git operations
- All data hygiene rules around backups, locks, and validation

---

## What "Real Performance Tracking" Means

The platform's real performance record begins on a named date (target: ~May 1, 2026) when the architecture is reformed and clean. Everything before that date is build-phase data. Build-phase data is preserved as historical context where useful (event analysis tables) and discarded where it would distort the record (build-phase bets).

The first version of each sport's brain is declared explicitly. Performance against that version is tracked. Subsequent versions reset the calibration window for that sport, but historical event data is preserved.

If the platform is ever published or marketed externally, this is the date it can honestly point to as "track record begins here." Without an explicit declaration, every bet-logger has the same dishonest "lifetime performance" problem where build-phase data inflates or deflates the record. The platform avoids this by declaring its line clearly.

---

## Post-position semantics (added 2026-05-06, parser ship)

The platform persists two distinct fields for horse gate position:

- `program_number` (string, supports coupled-entry markers like '1A')
  — pre-scratch entry number, equals Brisnet's `post_position`,
  used as the canonical join key between Equibase and Brisnet data.

- `post_position` (integer)
  — post-scratch gate position the horse actually broke from on race day.

Both are real and useful; they measure different things. The engine should
query whichever is appropriate for the question being asked. Brisnet PPs
only know pre-scratch (so `program_number` is the canonical join for
Brisnet data). Equibase charts know post-scratch (so `post_position` for
actual-pace analysis on race day).

Verified empirically across all 14 races of the Churchill May 2 2026 card:
`Equibase.program_number == Brisnet.post_position` holds 140/140 horses
that appear in both sources, while `Equibase.post_position == Brisnet.post_position`
holds only 81/140 (the others differ by the count of scratched horses
positioned ahead in the gate). This is by design, not a defect — both
sources are correct in their domain.

---

## Pace scenario sourcing (added 2026-05-06, parser ship)

The chart parser leaves `pace_scenario = None` on chart-derived rows.
`pace_scenario` is populated by the scorer pre-race from BRIS run-style
data (E / E/P / P / S / NA) — see `horse_racing_scorer.py` lines 742-784
for the classification logic. That formulation consumes pre-race past-
performance running styles, not chart-side fractional times.

Chart-context pace classification (HOT / MIXED / SLOW based on actual
fractional times relative to par) is a separate concept that we may add
as a derived field later, but it is not the same thing as the BRIS-
derived `pace_scenario` the engine currently uses.

Until such time as a chart-context pace classifier is defined and
agreed upon, the chart parser's `pace_scenario` field is intentionally
None. The orchestrator (`parse_race`) sets it to None explicitly via a
documented stub (`classify_pace_scenario`) so consumers know there's no
chart-derived pace label to consult.

---

## What Changes Over Time

This document is not immutable. It can change. But changes are explicit:

- New sport wings get their own section
- New principles get added with date stamps
- Existing principles get amended only with explicit notation that they have been amended

What never changes without notation: the principle that the engine is unbiased, the principle that analysis precedes betting, the principle that frozen rules from small samples are forbidden.

---

## How to Use This Document

When making any future change to the platform, ask:

1. Does this proposal conflict with any principle in this document?
2. If yes, is the proposal correct and the principle outdated, or is the principle correct and the proposal flawed?
3. If the principle is outdated, update this document explicitly first. Then make the change.
4. If the principle is correct, reject or modify the proposal.

This is the governance loop. It exists because every architectural mistake we have made on this platform has come from drift — small decisions that quietly contradicted earlier intent and accumulated into something the original design never sanctioned. This document is the brake on that drift.

---

*EDGE Intelligence Platform | Built for Kyle Richey | Confidential*
