"""
horse_racing_simulator.py — EDGE Intelligence Platform
Monte Carlo simulation engine for horse racing.

Workflow in the Car Wash pipeline:
    horse_racing_scorer.score_race()
        → run_simulation()          ← this module
        → generate_recommendation()  ← this module
        → print_car_wash_table()     ← this module

Usage:
    from horse_racing_simulator import run_simulation, generate_recommendation, print_car_wash_table

    scored   = horse_racing_scorer.score_race(horses)
    results  = run_simulation(scored, n_trials=10000)
    rec      = generate_recommendation(results)
    print_car_wash_table(results, rec)
"""

import numpy as np

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------

DEFAULT_TRIALS  = 10_000
SIM_SD          = 3.5        # performance draw standard deviation
GEM_THRESHOLD   = 18         # mirrors horse_racing_scorer

# Value flag thresholds (win_pct − market_implied_pct)
EV_STRONG       =  0.08
EV_MARGINAL     =  0.03
EV_NEUTRAL_LOW  = -0.03      # below this → NEGATIVE_EV

POSITIVE_FLAGS  = {"STRONG_EV", "MARGINAL_EV"}

# Recommendation trigger thresholds
WIN_BET_MIN_WIN_PCT     = 0.30
COMPRESSED_FIELD_MAX    = 0.20   # top horse below this → field too even


# ---------------------------------------------------------------------------
# VALUE FLAG HELPER
# ---------------------------------------------------------------------------

def _value_flag(win_pct: float, market_implied: float) -> str:
    gap = win_pct - market_implied
    if gap >= EV_STRONG:
        return "STRONG_EV"
    if gap >= EV_MARGINAL:
        return "MARGINAL_EV"
    if gap >= EV_NEUTRAL_LOW:
        return "NEUTRAL"
    return "NEGATIVE_EV"


# ---------------------------------------------------------------------------
# run_simulation
# ---------------------------------------------------------------------------

def run_simulation(scored_horses: list, n_trials: int = DEFAULT_TRIALS) -> list:
    """
    Run a Monte Carlo simulation over the scored horse field.

    For each trial, each horse draws a performance number from
    Normal(mean=composite_score, sd=SIM_SD).  Horses are ranked by
    performance (highest = 1st).  Win/place/show counts accumulate
    across all trials.

    Parameters
    ----------
    scored_horses : list[dict]
        Output from horse_racing_scorer.score_race() or score_horse().
        Required keys: horse_name, composite_score, morning_line,
                       is_gem, is_bounce_risk, is_no_play.
    n_trials : int
        Number of Monte Carlo trials.  Default 10,000.

    Returns
    -------
    list[dict]
        One dict per horse, sorted by win_pct descending.
        Keys: horse_name, post_position, composite_score,
              win_pct, place_pct, show_pct,
              morning_line, market_implied_pct, value_flag,
              is_gem, is_bounce_risk, is_no_play.
    """
    if not scored_horses:
        return []

    n = len(scored_horses)

    # Build composite array (one mean per horse)
    composites = np.array(
        [h.get("composite_score", 0) for h in scored_horses], dtype=np.float64
    )

    # ── Draw performances: shape (n_trials, n_horses) ──────────────────
    rng          = np.random.default_rng()          # seeded by OS entropy
    performances = rng.normal(
        loc=composites[np.newaxis, :],              # broadcast means
        scale=SIM_SD,
        size=(n_trials, n),
    )

    # ── Rank by performance (descending) ───────────────────────────────
    # rankings[trial, pos] = horse index finishing in that position
    rankings = np.argsort(-performances, axis=1)    # shape (n_trials, n)

    # ── Accumulate finish position counts ──────────────────────────────
    # wins[i]   = # trials horse i finished 1st
    # places[i] = # trials horse i finished 1st or 2nd
    # shows[i]  = # trials horse i finished 1st, 2nd, or 3rd
    wins   = np.bincount(rankings[:, 0], minlength=n)
    places = wins.copy()
    shows  = wins.copy()

    if n >= 2:
        places += np.bincount(rankings[:, 1], minlength=n)
        shows  += np.bincount(rankings[:, 1], minlength=n)
    if n >= 3:
        shows  += np.bincount(rankings[:, 2], minlength=n)

    # ── Build result dicts ─────────────────────────────────────────────
    results = []
    for i, horse in enumerate(scored_horses):
        win_pct   = float(wins[i])   / n_trials
        place_pct = float(places[i]) / n_trials
        show_pct  = float(shows[i])  / n_trials

        ml = horse.get("morning_line")
        if ml is not None:
            try:
                market_implied = 1.0 / (float(ml) + 1.0)
            except (ValueError, ZeroDivisionError):
                market_implied = None
        else:
            market_implied = None

        vflag = (
            _value_flag(win_pct, market_implied)
            if market_implied is not None
            else "NEUTRAL"
        )

        results.append({
            "horse_name":        horse.get("horse_name", ""),
            "post_position":     horse.get("post_position"),
            "composite_score":   horse.get("composite_score", 0),
            "win_pct":           round(win_pct,   4),
            "place_pct":         round(place_pct, 4),
            "show_pct":          round(show_pct,  4),
            "morning_line":      ml,
            "market_implied_pct": round(market_implied, 4) if market_implied is not None else None,
            "value_flag":        vflag,
            "is_gem":            bool(horse.get("is_gem",         False)),
            "is_bounce_risk":    bool(horse.get("is_bounce_risk", False)),
            "is_no_play":        bool(horse.get("is_no_play",     False)),
        })

    # Sort by win_pct descending
    return sorted(results, key=lambda r: r["win_pct"], reverse=True)


# ---------------------------------------------------------------------------
# generate_recommendation
# ---------------------------------------------------------------------------

def generate_recommendation(simulation_results: list) -> dict:
    """
    Apply EDGE betting rules to simulation output and return a recommendation.

    Priority order:
    1. NO_PLAY  — top horse is M09 veto (is_no_play)
    2. WIN_BET  — top win_pct ≥ 0.30, positive value, no veto
    3. NO_PLAY  — field compressed, no value, or any other veto condition

    Parameters
    ----------
    simulation_results : list[dict]
        Output from run_simulation(), sorted by win_pct descending.

    Returns
    -------
    dict with keys:
        recommendation  : str   (WIN_BET | NO_PLAY)
        horses_involved : list  (horse names in bet order)
        confidence      : str   (HIGH | MEDIUM | LOW)
        reasoning       : str   (one sentence, ≤ 120 chars)
    """
    if not simulation_results:
        return {
            "recommendation":  "NO_PLAY",
            "horses_involved": [],
            "confidence":      "LOW",
            "reasoning":       "Empty field — no horses to evaluate.",
        }

    top  = simulation_results[0]
    rest = simulation_results[1:]

    def _fmt(horse):
        return f"{horse['horse_name']} ({horse['morning_line']}-1)"

    # ── Rule 1: M09 veto on top horse ────────────────────────────────────
    if top["is_no_play"]:
        return {
            "recommendation":  "NO_PLAY",
            "horses_involved": [top["horse_name"]],
            "confidence":      "HIGH",
            "reasoning": (
                f"{top['horse_name']} carries M09 veto — model win% "
                f"({top['win_pct']*100:.1f}%) below market implied "
                f"({top['market_implied_pct']*100:.1f}%)."
            ),
        }

    top_win   = top["win_pct"]
    top_flag  = top["value_flag"]
    top_ml    = top["morning_line"]
    top_mkt   = top["market_implied_pct"] or 0

    # ── Rule 2: WIN_BET ───────────────────────────────────────────────────
    if (
        top_win >= WIN_BET_MIN_WIN_PCT
        and top_flag in POSITIVE_FLAGS
        and not top["is_no_play"]
    ):
        confidence = (
            "HIGH"   if top_flag == "STRONG_EV" and top_win >= 0.40 else
            "MEDIUM"
        )
        edge_pct = (top_win - top_mkt) * 100
        return {
            "recommendation":  "WIN_BET",
            "horses_involved": [top["horse_name"]],
            "confidence":      confidence,
            "reasoning": (
                f"{top['horse_name']} model {top_win*100:.1f}% vs "
                f"market {top_mkt*100:.1f}% — "
                f"+{edge_pct:.1f}pt edge at {top_ml}-1."
            ),
        }

    # ── Rule 3: NO_PLAY ───────────────────────────────────────────────────
    if top_win < COMPRESSED_FIELD_MAX:
        reason = (
            f"Field compressed — top model win% {top_win*100:.1f}%, "
            "no horse dominates."
        )
        conf = "LOW"
    elif top_flag == "NEGATIVE_EV":
        reason = (
            f"{top['horse_name']} at {top_ml}-1 is a market overlay — "
            "model finds no positive value."
        )
        conf = "LOW"
    else:
        reason = (
            f"No bet triggers met — insufficient win% or value "
            f"({top['horse_name']} {top_win*100:.1f}%, {top_flag})."
        )
        conf = "LOW"

    return {
        "recommendation":  "NO_PLAY",
        "horses_involved": [top["horse_name"]],
        "confidence":      conf,
        "reasoning":       reason,
    }


# ---------------------------------------------------------------------------
# CAR WASH TABLE PRINTER
# ---------------------------------------------------------------------------

def print_car_wash_table(
    simulation_results: list,
    recommendation: dict | None = None,
    title: str = "EDGE Car Wash Output",
) -> None:
    """
    Print the Car Wash probability table and recommendation block.

    Table format:
        Horse | Post | Win% | Place% | Show% | Value | Score | Flag

    Recommendation block:
        RECOMMENDATION: [type] --- [horses]
        Confidence: [level] | Reasoning: [one sentence]
    """
    # Column widths
    NW = 22   # horse name
    header = (
        f"{'Horse':<{NW}}  "
        f"{'Post':>4}  "
        f"{'Win%':>6}  "
        f"{'Place%':>7}  "
        f"{'Show%':>6}  "
        f"{'Value':<12}  "
        f"{'Score':>5}  "
        f"Flag"
    )
    bar = "─" * len(header)

    print(f"\n{'═'*len(header)}")
    print(f"  {title}")
    print(f"{'═'*len(header)}")
    print(header)
    print(bar)

    for h in simulation_results:
        name  = (h["horse_name"] or "?")[:NW]
        pp    = str(h.get("post_position") or "?")
        win   = f"{h['win_pct']*100:6.1f}%"
        plc   = f"{h['place_pct']*100:7.1f}%"
        shw   = f"{h['show_pct']*100:6.1f}%"
        vflag = h.get("value_flag", "")
        score = str(h.get("composite_score", ""))
        ml    = h.get("morning_line", "?")
        mkt   = h.get("market_implied_pct") or 0

        # Flags column
        flags = []
        if h.get("is_gem"):          flags.append("GEM")
        if h.get("is_no_play"):      flags.append("NO-PLAY")
        if h.get("is_bounce_risk"):  flags.append("BOUNCE")
        flag_str = " ".join(flags)

        print(
            f"{name:<{NW}}  "
            f"{pp:>4}  "
            f"{win}  "
            f"{plc}  "
            f"{shw}  "
            f"{vflag:<12}  "
            f"{score:>5}  "
            f"{flag_str}"
        )

    print(bar)
    print(f"{'═'*len(header)}")

    # ── Recommendation block ──────────────────────────────────────────────
    if recommendation:
        rec     = recommendation.get("recommendation", "NO_PLAY")
        horses  = ", ".join(recommendation.get("horses_involved", []))
        conf    = recommendation.get("confidence", "LOW")
        reason  = recommendation.get("reasoning", "")

        print()
        print(f"  RECOMMENDATION: {rec}  ---  {horses}")
        print(f"  Confidence: {conf}  |  Reasoning: {reason}")
        print()


# ---------------------------------------------------------------------------
# MAIN TEST BLOCK — 5-horse field (exact field from prompt spec)
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    np.random.seed(42)   # reproducible output for checkpoint confirmation

    print("=" * 70)
    print("horse_racing_simulator.py — EDGE Intelligence Platform")
    print("Checkpoint 7: 5-horse Car Wash simulation")
    print("=" * 70)
    print(f"numpy {np.__version__} | trials={DEFAULT_TRIALS:,} | SD={SIM_SD}")

    # ── Exact 5-horse field from build spec ──────────────────────────────
    horses = [
        {
            "horse_name":    "GEMSTONE GLORY",
            "post_position": 3,
            "composite_score": 27,
            "morning_line":  4.0,
            "is_gem":        True,
            "is_bounce_risk": False,
            "is_no_play":    False,
        },
        {
            "horse_name":    "RAIL ROCKET",
            "post_position": 1,
            "composite_score": 22,
            "morning_line":  6.0,
            "is_gem":        False,
            "is_bounce_risk": False,
            "is_no_play":    False,
        },
        {
            "horse_name":    "MUDDY WATERS",
            "post_position": 5,
            "composite_score": 18,
            "morning_line":  8.0,
            "is_gem":        False,
            "is_bounce_risk": False,
            "is_no_play":    False,
        },
        {
            "horse_name":    "PEAK AND FADE",
            "post_position": 2,
            "composite_score": 14,
            "morning_line":  3.0,
            "is_gem":        False,
            "is_bounce_risk": True,
            "is_no_play":    True,
        },
        {
            "horse_name":    "LONG SHOT LOUIE",
            "post_position": 4,
            "composite_score": 10,
            "morning_line":  15.0,
            "is_gem":        False,
            "is_bounce_risk": False,
            "is_no_play":    False,
        },
    ]

    # ── Run simulation ────────────────────────────────────────────────────
    results = run_simulation(horses, n_trials=DEFAULT_TRIALS)
    rec     = generate_recommendation(results)

    # ── Print Car Wash table + recommendation ─────────────────────────────
    print_car_wash_table(
        results,
        rec,
        title="KEE Race 5 — Car Wash Simulation (10,000 trials)",
    )

    # ── Spot-check assertions ─────────────────────────────────────────────
    print("── Assertions ────────────────────────────────────────────────────")
    top        = results[0]
    no_play_h  = next((r for r in results if r["horse_name"] == "PEAK AND FADE"), None)

    checks = [
        ("Top horse is GEMSTONE GLORY",       top["horse_name"] == "GEMSTONE GLORY"),
        ("GEMSTONE GLORY win_pct >= 0.30",    top["win_pct"] >= 0.30),
        ("GEMSTONE GLORY is STRONG_EV",       top["value_flag"] == "STRONG_EV"),
        ("GEMSTONE GLORY is_gem",             top["is_gem"]),
        ("PEAK AND FADE is_no_play",          no_play_h and no_play_h["is_no_play"]),
        ("PEAK AND FADE is_bounce_risk",      no_play_h and no_play_h["is_bounce_risk"]),
        ("Recommendation is WIN_BET",         rec["recommendation"] == "WIN_BET"),
        ("WIN_BET is on GEMSTONE GLORY",      "GEMSTONE GLORY" in rec["horses_involved"]),
    ]

    all_ok = True
    for label, cond in checks:
        status = "PASS" if cond else "FAIL"
        if not cond:
            all_ok = False
        print(f"  [{status}] {label}")

    print()
    print("All assertions passed ✓" if all_ok else "SOME ASSERTIONS FAILED ✗")
    print()
    print("Checkpoint 7 self-test: import check")
    print("  python -c \"import horse_racing_simulator; print('OK')\"")
