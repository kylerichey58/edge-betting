# EDGE Betting Intelligence Platform — Claude Instructions

## GIT IS ALREADY CONFIGURED — DO NOT REINITIALIZE
Git is fully set up in this folder. The repo is live at:
https://github.com/kylerichey58/edge-betting

To push any file change:
```
git add <filename>
git commit -m "your message"
git push origin master:main --force
```
DO NOT run git init. DO NOT ask for a PAT. DO NOT say git is not configured.
It is configured. Just run the commands above directly in the terminal.

---

## Core Files
- `bet_tracker.py` — bet logging (straight bets + parlays)
- `bet_analytics.py` — analytics dashboard
- `sports_betting.db` — SQLite database (tables: bets, parlays, parlay_legs, betting_stats)
- `ncaam_scout.py` — fetches today's NCAAM Power 4 games from The Odds API
- `ncaaw_scout.py` — fetches today's NCAAW Power 4 games, ESPN fallback if DK lines not posted
- `major_conference_analyzer.py` — upcoming game filter, countdown to tip, paste-ready Claude block
- `.env` — API keys (ODDS_API_KEY, ANTHROPIC_API_KEY) — **never modify**

## Standing Rules
- Always preserve existing data when editing Python files.
- No automated bet placement — human approval required before any wager, always.
- Never modify the .env file.
- Never bet ML legs in parlays — model shows 0% hit rate on ML parlay legs. SPREAD legs only.

---

## Metric Framework v2.0 (Updated March 27, 2026)

**9-metric framework. Applies to NCAAM and NCAAW equally.**
Live performance basis: 58 bets graded | 57.9% overall WR | 65.2% Totals WR | +2.82u net.

### The 9 Metrics

| # | Metric | Weight | Best For | Threshold |
|---|--------|--------|----------|-----------|
| 01 | **3-Point % (3PT%)** | HIGH | Spread + Total | Off >38% \| Def <28% \| Flag if gap >6% |
| 02 | **Win % Context** | HIGH | Spread | Road dog >60% = value \| Home fav <50% = fade \| Add SOS qualifier |
| 03 | **Off Reb % (OffReb%)** | HIGH | Totals | Threat: >35% \| Limited: <25% — primary totals anchor |
| 04 | **Def Efficiency (DefEff)** | HIGH | Totals | Elite: Top 30 \| Exploit: Rank 150+ — core under metric |
| 05 | **Pace & Tempo** | HIGH ↑ | Totals | Fast: >72 poss \| Slow: <65 poss \| Gap >5 = slower team controls pace |
| 06 | **Free Throw % (FT%)** | MEDIUM | Spread (close games only) | Reliable: >80% \| Fade: <65% — only activates when spread <5pts |
| 07 | **Bench Depth** | MEDIUM | Spread (context) | Deep: >20 PPG \| Vulnerable: <10 PPG — weight in B2Bs, rivalries, tournament |
| 08 | **Sharp Money / Public %** | HIGH ↑ | Both | 70%+ public = look other side \| RLM = sharp — required check before any bet |
| 09 | **Recent Form (Last 5)** | MED-HIGH | Both | Hot: 4-1 or 5-0 ATS \| Cold: 0-5 = fade — especially important in March |

### v2.0 Changes from v1.0
- Metric 05 (Pace/Tempo): **elevated to HIGH**, gap threshold dropped from >7 to **>5 possessions**
- Metric 06 (FT%): **narrowed** — close games only (spread <5pts); irrelevant in blowouts
- Metric 07 (Bench Depth): now a **context flag** — activate for B2Bs, rivalry games, tournament
- Metric 08 (Sharp Money): **elevated to HIGH** — required pre-bet check every time
- Metric 09 (Recent Form): **NEW** — added for tournament momentum edge

---

## Golden Rules

1. **5+ metrics aligned (v1) / 6+ metrics aligned (v2) = highest-confidence play.**
2. Metric 08 (Sharp Money) is most powerful when it **contradicts** the other 8 — that is where model edge and sharp money align perfectly.
3. Metric 05 (Pace/Tempo) is the **single strongest predictor for totals**. A gap of 5+ possessions means the slower team controls pace — bet accordingly.
4. Metric 06 (FT%) only activates when spread is **under 5 points**. Irrelevant in blowouts.
5. Metric 07 (Bench Depth) activates in **back-to-backs, rivalry games, and tournament play**.
6. Metric 09 (Recent Form) is especially important in **March Madness** — a 4-1 or 5-0 ATS run has momentum the line hasn't fully priced in.
7. **NCAAW edge**: thin public betting data = less efficient market. Metrics 01–07 carry more weight than 08 in women's analysis.
8. **Never bet ML legs in parlays.** 0% hit rate in model. SPREAD legs only.

---

## Confidence Rating & Unit Sizing

| Stars | Metrics Aligned | Unit Size | Parlay? | Notes |
|-------|----------------|-----------|---------|-------|
| ★★★★ 4-Star | 7–9 aligned | 1.5–2.0u | YES — SPREAD only | Gem tier. Size up. Best performing tier. |
| ★★★ 3-Star | 5–6 aligned | 1.0–1.5u | YES — SPREAD only | Solid. Standard sizing. 60%+ target WR. |
| ★★ 2-Star | 3–4 aligned | 0.5–1.0u | NO | Speculation only. Skip unless strong value. |
| ★ 1-Star | 1–2 aligned | 0–0.5u | NEVER | Lean only. Usually pass. |
| ML Parlay Legs | N/A | AVOID | NEVER | 0% hit rate. SPREAD legs only in parlays. |

---

## Daily Workflow

1. Run `ncaam_scout.py` / `ncaaw_scout.py` at ~6 PM EST — fetches games + DraftKings lines
2. Run `major_conference_analyzer.py` — filters upcoming games, generates Claude paste block
3. Paste 3–5 games into Claude: *"Analyze these games using all 9 metrics. Focus on totals edge."*
4. Check Action Network for Metric 08 (public %, RLM, sharp money) — required before any bet
5. Log approved bets: `python bet_tracker.py` (Option 1 straight / Option 2 parlay)
6. Place bets manually on DraftKings — never automated
7. Update results after games: Option 3 or 4 in tracker
8. Run `python bet_analytics.py` weekly for full dashboard refresh

---

## Sport Expansion Roadmap

| Sport | Status | Primary Edge |
|-------|--------|--------------|
| NCAAM Basketball | **ACTIVE** | Totals — 65%+ WR |
| NCAAW Basketball | **ACTIVE** | Totals — thin market inefficiency is the edge |
| MLB Baseball | PLANNED (summer 2026) | Totals + run lines |
| NFL / NCAAF | PLANNED (fall 2026) | ATS + totals |
| NBA | FUTURE | Totals + live betting |
| Horse Racing | FUTURE | ROI by race type |

---

*EDGE Betting Intelligence • Metric Framework v2.0 • March 27, 2026*
*You are not just betting. You are building a business.*
