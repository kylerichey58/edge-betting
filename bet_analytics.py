import sqlite3
import os
from datetime import datetime
from collections import defaultdict

DB_PATH = os.path.join(os.path.dirname(__file__), "sports_betting.db")

def connect():
    return sqlite3.connect(DB_PATH)

def separator(char="═", width=57):
    print(char * width)

def thin_sep(width=57):
    print("─" * width)

def header(title):
    separator()
    print(f"  {title}")
    thin_sep()

# ─────────────────────────────────────────────
#  CORE DATA LOADERS
# ─────────────────────────────────────────────

def load_straight_bets(conn):
    cur = conn.cursor()
    # Exact column names from your sports_betting.db schema
    cur.execute("""
        SELECT id,
               away_team || ' @ ' || home_team  AS game,
               bet_type,
               bet_selection                     AS pick,
               NULL                              AS line,
               odds,
               units,
               confidence,
               result,
               profit_loss,
               reasoning                         AS notes,
               logged_date                       AS created_at
        FROM bets
        WHERE result IS NOT NULL AND result != 'PENDING'
        ORDER BY logged_date ASC
    """)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]

def load_parlays(conn):
    cur = conn.cursor()
    # Check parlays table exists
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='parlays'")
    if not cur.fetchone():
        return []

    cur.execute("PRAGMA table_info(parlays)")
    p_cols = [row[1] for row in cur.fetchall()]

    # Build flexible select for parlays
    name_col    = next((c for c in ["name","parlay_name","title"] if c in p_cols), None)
    odds_col    = next((c for c in ["combined_odds","odds","price"] if c in p_cols), None)
    units_col   = next((c for c in ["units","stake"] if c in p_cols), None)
    conf_col    = next((c for c in ["confidence","conf"] if c in p_cols), None)
    result_col  = next((c for c in ["result","outcome"] if c in p_cols), "result")
    pl_col      = next((c for c in ["profit_loss","pl","pnl"] if c in p_cols), None)
    notes_col   = next((c for c in ["notes","reasoning"] if c in p_cols), None)
    date_col    = next((c for c in ["created_at","logged_date","date","timestamp"] if c in p_cols), None)

    def alias(actual, name):
        return f"{actual} AS {name}" if actual else f"NULL AS {name}"

    cur.execute(f"""
        SELECT id,
               {alias(name_col,   'name')},
               {alias(odds_col,   'combined_odds')},
               {alias(units_col,  'units')},
               {alias(conf_col,   'confidence')},
               {alias(result_col, 'result')},
               {alias(pl_col,     'profit_loss')},
               {alias(notes_col,  'notes')},
               {alias(date_col,   'created_at')}
        FROM parlays
        WHERE {result_col} IS NOT NULL AND {result_col} != 'PENDING'
        ORDER BY {date_col or 'rowid'} ASC
    """)
    cols = [d[0] for d in cur.description]
    parlays = [dict(zip(cols, row)) for row in cur.fetchall()]

    # Load legs
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='parlay_legs'")
    has_legs = cur.fetchone() is not None

    for p in parlays:
        if not has_legs:
            p["legs"] = []
            continue
        cur.execute("PRAGMA table_info(parlay_legs)")
        lc = [row[1] for row in cur.fetchall()]
        game_col  = next((c for c in ["game","matchup","away_team"] if c in lc), None)
        pick_col  = next((c for c in ["pick","bet_selection","selection"] if c in lc), None)
        btype_col = next((c for c in ["bet_type","type"] if c in lc), None)
        line_col  = next((c for c in ["line","spread"] if c in lc), None)
        res_col   = next((c for c in ["result","outcome"] if c in lc), None)

        def la(actual, name):
            return f"{actual} AS {name}" if actual else f"NULL AS {name}"

        cur.execute(f"""
            SELECT {la(game_col,'game')}, {la(pick_col,'pick')},
                   {la(btype_col,'bet_type')}, {la(line_col,'line')},
                   {la(res_col,'result')}
            FROM parlay_legs WHERE parlay_id = ? ORDER BY id ASC
        """, (p["id"],))
        leg_cols = [d[0] for d in cur.description]
        p["legs"] = [dict(zip(leg_cols, row)) for row in cur.fetchall()]

    return parlays

def load_pending(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT id,
               away_team || ' @ ' || home_team AS game,
               bet_type,
               bet_selection AS pick,
               odds,
               units,
               confidence,
               logged_date AS created_at
        FROM bets WHERE result IS NULL OR result = 'PENDING'
    """)
    cols = [d[0] for d in cur.description]
    straight = [dict(zip(cols, row)) for row in cur.fetchall()]

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='parlays'")
    if not cur.fetchone():
        return straight, []

    cur.execute("PRAGMA table_info(parlays)")
    p_cols = [row[1] for row in cur.fetchall()]
    name_col   = next((c for c in ["name","title"] if c in p_cols), None)
    odds_col   = next((c for c in ["combined_odds","odds"] if c in p_cols), None)
    units_col  = next((c for c in ["units","stake"] if c in p_cols), None)
    conf_col   = next((c for c in ["confidence","conf"] if c in p_cols), None)
    result_col = next((c for c in ["result","outcome"] if c in p_cols), "result")
    date_col   = next((c for c in ["created_at","logged_date","date"] if c in p_cols), None)

    def alias(actual, name):
        return f"{actual} AS {name}" if actual else f"NULL AS {name}"

    cur.execute(f"""
        SELECT id, {alias(name_col,'name')}, {alias(odds_col,'combined_odds')},
               {alias(units_col,'units')}, {alias(conf_col,'confidence')},
               {alias(date_col,'created_at')}
        FROM parlays WHERE {result_col} IS NULL OR {result_col} = 'PENDING'
    """)
    cols = [d[0] for d in cur.description]
    parlays = [dict(zip(cols, row)) for row in cur.fetchall()]
    return straight, parlays

# ─────────────────────────────────────────────
#  CALCULATION HELPERS
# ─────────────────────────────────────────────

def calc_stats(bets, unit_key="units", pl_key="profit_loss", result_key="result"):
    wins = [b for b in bets if b[result_key] == "WIN"]
    losses = [b for b in bets if b[result_key] == "LOSS"]
    pushes = [b for b in bets if b[result_key] == "PUSH"]
    total = len(wins) + len(losses)
    win_rate = (len(wins) / total * 100) if total > 0 else 0
    total_pl = sum(b[pl_key] for b in bets if b[pl_key] is not None)
    total_risked = sum(b[unit_key] for b in bets if b[result_key] != "PUSH")
    roi = (total_pl / total_risked * 100) if total_risked > 0 else 0
    return {
        "wins": len(wins), "losses": len(losses), "pushes": len(pushes),
        "total": total, "win_rate": win_rate,
        "total_pl": total_pl, "total_risked": total_risked, "roi": roi
    }

def stars(confidence):
    try:
        n = int(confidence)
        return "⭐" * n
    except:
        return str(confidence)

def trend_arrow(values):
    if len(values) < 2:
        return "─"
    recent = sum(values[-3:]) / len(values[-3:])
    earlier = sum(values[:-3]) / len(values[:-3]) if len(values) > 3 else values[0]
    if recent > earlier + 0.05:
        return "↑"
    elif recent < earlier - 0.05:
        return "↓"
    return "─"

# ─────────────────────────────────────────────
#  SECTION 1 — OVERALL SUMMARY
# ─────────────────────────────────────────────

def section_overall(bets, parlays):
    header("📊  OVERALL PERFORMANCE SUMMARY")

    s = calc_stats(bets)
    p_stats = calc_stats(parlays)

    combined_pl = s["total_pl"] + p_stats["total_pl"]
    combined_risked = s["total_risked"] + p_stats["total_risked"]
    combined_roi = (combined_pl / combined_risked * 100) if combined_risked > 0 else 0

    print(f"  {'Metric':<28} {'Straight':>10}  {'Parlays':>10}  {'Combined':>10}")
    thin_sep()
    print(f"  {'Record':<28} {s['wins']}W-{s['losses']}L-{s['pushes']}P {'':>4} {p_stats['wins']}W-{p_stats['losses']}L")
    print(f"  {'Win Rate':<28} {s['win_rate']:>9.1f}%  {p_stats['win_rate']:>9.1f}%")
    print(f"  {'Net P/L (units)':<28} {s['total_pl']:>+10.2f}  {p_stats['total_pl']:>+10.2f}  {combined_pl:>+10.2f}")
    print(f"  {'ROI':<28} {s['roi']:>9.1f}%  {p_stats['roi']:>9.1f}%  {combined_roi:>9.1f}%")
    print(f"  {'Units Risked':<28} {s['total_risked']:>10.1f}  {p_stats['total_risked']:>10.1f}  {combined_risked:>10.1f}")
    separator()

# ─────────────────────────────────────────────
#  SECTION 2 — BREAKDOWN BY BET TYPE
# ─────────────────────────────────────────────

def section_by_type(bets):
    header("🎯  STRAIGHT BETS BY TYPE")
    types = defaultdict(list)
    for b in bets:
        types[b.get("bet_type", "UNKNOWN").upper()].append(b)

    print(f"  {'Type':<12} {'Record':>10} {'Win%':>7} {'P/L':>8} {'ROI':>8}")
    thin_sep()
    for t, tb in sorted(types.items()):
        s = calc_stats(tb)
        print(f"  {t:<12} {s['wins']}W-{s['losses']}L-{s['pushes']}P {s['win_rate']:>6.1f}% {s['total_pl']:>+7.2f}u {s['roi']:>7.1f}%")
    separator()

# ─────────────────────────────────────────────
#  SECTION 3 — BREAKDOWN BY CONFIDENCE
# ─────────────────────────────────────────────

def section_by_confidence(bets, parlays):
    header("⭐  PERFORMANCE BY CONFIDENCE LEVEL")
    levels = defaultdict(list)
    for b in bets:
        levels[b.get("confidence", "?")].append(b)

    print(f"  {'Level':<10} {'Record':>10} {'Win%':>7} {'P/L':>8} {'ROI':>8}  {'Type'}")
    thin_sep()
    for lvl in sorted(levels.keys(), reverse=True):
        lb = levels[lvl]
        s = calc_stats(lb)
        print(f"  {stars(lvl):<10} {s['wins']}W-{s['losses']}L-{s['pushes']}P {s['win_rate']:>6.1f}% {s['total_pl']:>+7.2f}u {s['roi']:>7.1f}%  Straight")

    p_levels = defaultdict(list)
    for p in parlays:
        p_levels[p.get("confidence", "?")].append(p)
    for lvl in sorted(p_levels.keys(), reverse=True):
        lb = p_levels[lvl]
        s = calc_stats(lb)
        print(f"  {stars(lvl):<10} {s['wins']}W-{s['losses']}L {'':>4} {s['win_rate']:>6.1f}% {s['total_pl']:>+7.2f}u {s['roi']:>7.1f}%  Parlay")
    separator()

# ─────────────────────────────────────────────
#  SECTION 4 — PARLAY LEG ANALYSIS
# ─────────────────────────────────────────────

def section_parlay_legs(parlays):
    header("🎰  PARLAY LEG HIT RATES")
    all_legs = []
    for p in parlays:
        all_legs.extend(p.get("legs", []))

    if not all_legs:
        print("  No parlay leg data available yet.")
        separator()
        return

    by_type = defaultdict(list)
    for leg in all_legs:
        if leg.get("result") and leg["result"] != "PENDING":
            by_type[leg.get("bet_type", "UNKNOWN").upper()].append(leg)

    print(f"  {'Leg Type':<12} {'Record':>8} {'Hit Rate':>10}  {'Verdict'}")
    thin_sep()
    for t, legs in sorted(by_type.items()):
        wins = sum(1 for l in legs if l["result"] == "WIN")
        total = len(legs)
        rate = wins / total * 100 if total > 0 else 0
        verdict = "✅ RELIABLE" if rate >= 60 else ("⚠️  MONITOR" if rate >= 45 else "❌ AVOID")
        print(f"  {t:<12} {wins}W-{total-wins}L {'':>3} {rate:>8.1f}%  {verdict}")

    print()
    print("  💡 KEY INSIGHT: Build parlays using your highest hit-rate leg types.")
    separator()

# ─────────────────────────────────────────────
#  SECTION 5 — ROLLING P/L TREND
# ─────────────────────────────────────────────

def section_rolling_trend(bets):
    header("📈  ROLLING P/L TREND (Straight Bets)")
    if not bets:
        print("  Not enough data.")
        separator()
        return

    running = 0
    print(f"  {'#':<4} {'Game':<28} {'Pick':<18} {'Result':>6} {'Bet P/L':>8} {'Running':>9}")
    thin_sep()
    for i, b in enumerate(bets, 1):
        pl = b.get("profit_loss") or 0
        running += pl
        game = (b.get("game") or "")[:27]
        pick = (b.get("pick") or "")[:17]
        result = b.get("result", "?")
        icon = "✅" if result == "WIN" else ("❌" if result == "LOSS" else "➡️")
        print(f"  {i:<4} {game:<28} {pick:<18} {icon} {pl:>+7.2f}u {running:>+8.2f}u")

    separator()

# ─────────────────────────────────────────────
#  SECTION 6 — BEST & WORST BETS
# ─────────────────────────────────────────────

def section_best_worst(bets, parlays):
    header("🏆  BEST & WORST BETS")
    all_bets = [(b.get("game","?"), b.get("pick","?"), b.get("profit_loss") or 0, "Straight") for b in bets]
    all_bets += [(p.get("name","Parlay"), "Parlay", p.get("profit_loss") or 0, "Parlay") for p in parlays]
    if not all_bets:
        print("  No graded bets yet.")
        separator()
        return

    sorted_bets = sorted(all_bets, key=lambda x: x[2], reverse=True)

    print("  TOP 3 WINNERS")
    for game, pick, pl, btype in sorted_bets[:3]:
        print(f"    ✅ {game[:30]:<30} {pick[:18]:<18} {pl:>+7.2f}u  ({btype})")
    print()
    print("  TOP 3 LOSERS")
    for game, pick, pl, btype in sorted_bets[-3:]:
        print(f"    ❌ {game[:30]:<30} {pick[:18]:<18} {pl:>+7.2f}u  ({btype})")
    separator()

# ─────────────────────────────────────────────
#  SECTION 7 — UNIT SIZING ANALYSIS
# ─────────────────────────────────────────────

def section_unit_sizing(bets):
    header("💰  UNIT SIZING ANALYSIS")
    if not bets:
        print("  No data yet.")
        separator()
        return

    buckets = {"0.5-1.0u": [], "1.1-2.0u": [], "2.1-3.0u": [], "3.0u+": []}
    for b in bets:
        u = b.get("units") or 0
        if u <= 1.0:
            buckets["0.5-1.0u"].append(b)
        elif u <= 2.0:
            buckets["1.1-2.0u"].append(b)
        elif u <= 3.0:
            buckets["2.1-3.0u"].append(b)
        else:
            buckets["3.0u+"].append(b)

    print(f"  {'Size':<12} {'Record':>10} {'Win%':>7} {'P/L':>8} {'ROI':>8}")
    thin_sep()
    for bucket, bb in buckets.items():
        if not bb:
            continue
        s = calc_stats(bb)
        print(f"  {bucket:<12} {s['wins']}W-{s['losses']}L-{s['pushes']}P {s['win_rate']:>6.1f}% {s['total_pl']:>+7.2f}u {s['roi']:>7.1f}%")
    separator()

# ─────────────────────────────────────────────
#  SECTION 8 — PENDING BETS
# ─────────────────────────────────────────────

def section_pending(conn):
    straight, parlays = load_pending(conn)
    if not straight and not parlays:
        return
    header("⏳  PENDING BETS")
    if straight:
        print("  STRAIGHT BETS")
        for b in straight:
            print(f"    ID {b['id']}: {b.get('game','?')[:35]} | {b.get('pick','?')} | {b.get('units',0)}u | {stars(b.get('confidence','?'))}")
    if parlays:
        print("  PARLAYS")
        for p in parlays:
            print(f"    ID {p['id']}: {p.get('name','Parlay')[:35]} | {p.get('units',0)}u | {stars(p.get('confidence','?'))}")
    separator()

# ─────────────────────────────────────────────
#  SECTION 9 — MODEL HEALTH & RECOMMENDATIONS
# ─────────────────────────────────────────────

def section_recommendations(bets, parlays):
    header("🧠  MODEL HEALTH & STRATEGIC INSIGHTS")
    all_bets = bets + parlays
    total_graded = len([b for b in bets if b.get("result") not in (None, "PENDING")]) + \
                   len([p for p in parlays if p.get("result") not in (None, "PENDING")])

    s = calc_stats(bets) if bets else {"win_rate": 0, "roi": 0, "total_pl": 0}

    insights = []

    # Sample size check
    if total_graded < 10:
        insights.append("⚠️  Sample size too small (<10 bets) — patterns are not yet reliable.")
    elif total_graded < 25:
        insights.append(f"📊 {total_graded} graded bets — early trends emerging. Target: 25 for deeper edge ID.")
    else:
        insights.append(f"✅ {total_graded} graded bets — statistically meaningful sample.")

    # Win rate check
    if s["win_rate"] >= 60:
        insights.append(f"✅ Win rate {s['win_rate']:.1f}% — above breakeven threshold. Model is performing.")
    elif s["win_rate"] >= 52:
        insights.append(f"📊 Win rate {s['win_rate']:.1f}% — near breakeven. Monitor closely.")
    else:
        insights.append(f"⚠️  Win rate {s['win_rate']:.1f}% — below breakeven. Review bet selection criteria.")

    # ROI check
    if s["roi"] > 15:
        insights.append(f"🔥 ROI {s['roi']:.1f}% — exceptional. Maintain discipline and don't chase.")
    elif s["roi"] > 0:
        insights.append(f"✅ ROI {s['roi']:.1f}% — profitable. Stay the course.")
    else:
        insights.append(f"⚠️  ROI {s['roi']:.1f}% — negative ROI. Review unit sizing and confidence thresholds.")

    # Parlay leg insight
    all_legs = []
    for p in parlays:
        all_legs.extend(p.get("legs", []))
    ml_legs = [l for l in all_legs if l.get("bet_type","").upper() == "ML" and l.get("result") not in (None,"PENDING")]
    if ml_legs:
        ml_wins = sum(1 for l in ml_legs if l["result"] == "WIN")
        ml_rate = ml_wins / len(ml_legs) * 100
        if ml_rate < 50:
            insights.append(f"⚠️  ML parlay legs hitting {ml_rate:.0f}% — consider avoiding ML legs in parlays.")

    # Milestone tracker
    print("  MILESTONE TRACKER")
    milestones = [
        (10,  "bet_analytics.py — first performance charts"),
        (25,  "Edge identification + parlay leg optimization"),
        (50,  "Full dashboard + predictive modeling"),
    ]
    for target, label in milestones:
        done = total_graded >= target
        icon = "✅" if done else "🔜"
        bar_filled = min(total_graded, target)
        bar = "█" * bar_filled + "░" * (target - bar_filled)
        # Keep bar short for display
        display_bar = "█" * min(bar_filled, 20) + "░" * (20 - min(bar_filled, 20))
        pct = min(total_graded / target * 100, 100)
        print(f"  {icon} {target} bets [{display_bar}] {pct:.0f}%  {label}")

    print()
    print("  STRATEGIC INSIGHTS")
    for insight in insights:
        print(f"  {insight}")

    separator()

# ─────────────────────────────────────────────
#  SECTION 10 — NEXT SESSION CHECKLIST
# ─────────────────────────────────────────────

def section_checklist():
    header("✅  NEXT SESSION CHECKLIST")
    items = [
        "Run major_conference_analyzer.py (~6 PM EST for evening games)",
        "Paste 3-5 games to Claude: 'Analyze these games using all 8 metrics'",
        "Check Action Network for public betting % (Metric 08)",
        "Log bets: python bet_tracker.py (Option 1 straight / Option 2 parlay)",
        "Update results after games: Option 3 or 4 in tracker",
        "Run python bet_analytics.py after updating to see fresh stats",
    ]
    for item in items:
        print(f"  □  {item}")
    separator()

# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def main():
    conn = connect()

    print()
    separator("═")
    print("  🏀  SPORTS BETTING MODEL — ANALYTICS DASHBOARD")
    print(f"  Generated: {datetime.now().strftime('%B %d, %Y  %I:%M %p')}")
    separator("═")
    print()

    bets = load_straight_bets(conn)
    parlays = load_parlays(conn)

    if not bets and not parlays:
        print("  No graded bets found in the database.")
        print("  Log and grade some bets using bet_tracker.py first!")
        return

    section_overall(bets, parlays)
    section_by_type(bets)
    section_by_confidence(bets, parlays)
    section_parlay_legs(parlays)
    section_rolling_trend(bets)
    section_best_worst(bets, parlays)
    section_unit_sizing(bets)
    section_pending(conn)
    section_recommendations(bets, parlays)
    section_checklist()

    conn.close()
    print()
    print("  You are not just betting. You are building a business.")
    print()
    separator("═")

if __name__ == "__main__":
    main()
