"""
Cross-check Equibase Full Chart parse vs Brisnet PP file for the same card.

Goal: surface naming or post-position discrepancies between the two sources
*before* the May 1-2 backfill, while we have a clean test case (Churchill
May 2 2026 — the Derby card).

What the script does
--------------------
  1. Run horse_racing_pdf_parser_v2.parse_chart_pdf on the Equibase PDF.
  2. Run horse_racing_parser.parse_race_file on the Brisnet DRF.
  3. Per race:
     - Build {normalized_name: {post_position, program_number, raw_name}} maps
       from each source.
     - Compute set deltas (in_both / equibase_only / brisnet_only).
     - For names that appear in both, check post_position agreement.
     - Run a fuzzy-match pass over (equibase_only x brisnet_only) — pairs
       with edit distance <= 3 OR substring containment are flagged as
       PROBABLE NAMING MISMATCH (the architectural concern).
  4. Print a summary table + per-race detail for races with flags.

Running
-------
    python tests/cross_check_equibase_brisnet.py

Inputs are hardcoded for the Churchill May 2, 2026 card. Future calls can
pass alternate paths via argv[1]/argv[2].
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Project root on sys.path so we can import the parser modules.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import horse_racing_pdf_parser_v2 as eq_parser  # noqa: E402
import horse_racing_parser as br_parser          # noqa: E402

DEFAULT_EQUIBASE_PDF = PROJECT_ROOT / "horse_racing_data" / "CD050226USA.pdf"
DEFAULT_BRISNET_DRF = PROJECT_ROOT / "horse_racing_data" / "cards" / "CDX0502.DRF"


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------
# Brisnet uses ALL CAPS ("BHATIA"), Equibase uses Title Case ("Powershift").
# Apostrophes appear differently between sources ("D' Rapper" vs "DRAPPER").
# Normalize: uppercase, strip non-alphanumeric except space, collapse runs of
# whitespace. This is intentionally aggressive — it loses (a) case info and
# (b) hyphenation/apostrophe distinctions, but those are exactly the sources
# of false-positive mismatches we're trying to filter out.
_NORMALIZE_RE = re.compile(r"[^A-Z0-9 ]")


def normalize_name(s):
    if not s:
        return ""
    upped = s.upper()
    cleaned = _NORMALIZE_RE.sub(" ", upped)
    return re.sub(r"\s+", " ", cleaned).strip()


# ---------------------------------------------------------------------------
# Edit distance (iterative Levenshtein, no external deps)
# ---------------------------------------------------------------------------
def levenshtein(a, b):
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(
                min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + (0 if ca == cb else 1))
            )
        prev = curr
    return prev[-1]


def is_fuzzy_match(eq_name, br_name):
    """True if these probably refer to the same horse despite differing strings."""
    if not eq_name or not br_name:
        return False
    if eq_name == br_name:
        return True
    # substring containment (one is a prefix/suffix of the other)
    if eq_name in br_name or br_name in eq_name:
        return True
    # edit distance <= 3 for short names; <= 5 for longer
    threshold = 3 if max(len(eq_name), len(br_name)) <= 12 else 5
    return levenshtein(eq_name, br_name) <= threshold


# ---------------------------------------------------------------------------
# Per-source race builders
# ---------------------------------------------------------------------------
def equibase_horses_by_race(pdf_path):
    """Return {race_number: [{name_norm, name_raw, post_position, program_number}, ...]}."""
    result = eq_parser.parse_chart_pdf(pdf_path)
    if result is None:
        raise RuntimeError(f"parse_chart_pdf failed on {pdf_path}")
    out = {}
    for race in result["races"]:
        rn = race["race_number"]
        out[rn] = []
        for h in race["horses"]:
            raw = h.get("horse_name") or ""
            out[rn].append({
                "name_norm": normalize_name(raw),
                "name_raw": raw,
                "post_position": h.get("post_position"),
                "program_number": h.get("program_number"),
            })
    return out, result


def brisnet_horses_by_race(drf_path):
    """Return {race_number: [{name_norm, name_raw, post_position, program_number}, ...]}."""
    races = br_parser.parse_race_file(drf_path)
    out = {}
    for rn, horses in races.items():
        out[rn] = []
        for h in horses:
            raw = h.get("horse_name") or ""
            out[rn].append({
                "name_norm": normalize_name(raw),
                "name_raw": raw,
                "post_position": h.get("post_position"),
                "program_number": h.get("program_number"),
            })
    return out


# ---------------------------------------------------------------------------
# Cross-check
# ---------------------------------------------------------------------------
def cross_check_one_race(eq_horses, br_horses):
    """Compare one race's horse lists. Returns a dict of findings."""
    eq_by_norm = {h["name_norm"]: h for h in eq_horses}
    br_by_norm = {h["name_norm"]: h for h in br_horses}
    eq_names = set(eq_by_norm)
    br_names = set(br_by_norm)

    in_both = eq_names & br_names
    eq_only = eq_names - br_names
    br_only = br_names - eq_names

    # Equibase and Brisnet use DIFFERENT post-position semantics:
    #   - Equibase.post_position    = post-scratch gate position (1..N contiguous)
    #   - Equibase.program_number   = pre-scratch ENTRY position (matches Brisnet)
    #   - Brisnet.post_position     = pre-scratch entry position
    # The canonical join is Equibase.program_number == Brisnet.post_position.
    # We report both comparisons so the divergence is visible.
    pp_matches = []         # Equibase.program_number == Brisnet.post_position
    pp_mismatches = []
    gate_shifts = []        # Equibase.post_position != Brisnet.post_position (informational)
    for n in sorted(in_both):
        eq_pgm_raw = eq_by_norm[n]["program_number"]
        try:
            eq_pgm = int(re.sub(r"[^0-9]", "", str(eq_pgm_raw))) if eq_pgm_raw else None
        except (TypeError, ValueError):
            eq_pgm = None
        eq_pp = eq_by_norm[n]["post_position"]
        br_pp = br_by_norm[n]["post_position"]

        # Authoritative check: program_number vs Brisnet PP
        if eq_pgm is not None and eq_pgm == br_pp:
            pp_matches.append(n)
        else:
            pp_mismatches.append({
                "name": n,
                "eq_program_number": eq_pgm_raw,
                "eq_pp": eq_pp,
                "br_pp": br_pp,
                "eq_raw": eq_by_norm[n]["name_raw"],
                "br_raw": br_by_norm[n]["name_raw"],
            })

        # Informational: gate-position shift (post-scratch vs pre-scratch)
        if eq_pp != br_pp:
            gate_shifts.append({
                "name": n,
                "eq_pp": eq_pp,
                "br_pp": br_pp,
                "shift": (br_pp or 0) - (eq_pp or 0),
            })

    # Fuzzy matches between eq_only and br_only — probable naming mismatches.
    naming_mismatches = []
    for eqn in sorted(eq_only):
        for brn in sorted(br_only):
            if is_fuzzy_match(eqn, brn):
                naming_mismatches.append({
                    "eq_name": eqn,
                    "br_name": brn,
                    "eq_raw": eq_by_norm[eqn]["name_raw"],
                    "br_raw": br_by_norm[brn]["name_raw"],
                    "edit_distance": levenshtein(eqn, brn),
                    "eq_pp": eq_by_norm[eqn]["post_position"],
                    "br_pp": br_by_norm[brn]["post_position"],
                })

    return {
        "eq_count": len(eq_horses),
        "br_count": len(br_horses),
        "in_both": sorted(in_both),
        "eq_only": sorted(eq_only),
        "br_only": sorted(br_only),
        "pp_matches": pp_matches,
        "pp_mismatches": pp_mismatches,
        "gate_shifts": gate_shifts,
        "naming_mismatches": naming_mismatches,
    }


def main(eq_pdf, br_drf):
    print("=" * 60)
    print("EQUIBASE x BRISNET CROSS-CHECK")
    print("=" * 60)
    print(f"Source A (Equibase): {eq_pdf}")
    print(f"Source B (Brisnet):  {br_drf}")

    eq_by_race, eq_meta = equibase_horses_by_race(eq_pdf)
    print(f"Equibase: track={eq_meta['track']!r}  date={eq_meta['race_date']!r}")
    br_by_race = brisnet_horses_by_race(br_drf)
    print(f"Brisnet: {len(br_by_race)} race(s)")

    all_race_nums = sorted(set(eq_by_race) | set(br_by_race))

    # Per-race results
    per_race = {}
    for rn in all_race_nums:
        eq = eq_by_race.get(rn, [])
        br = br_by_race.get(rn, [])
        per_race[rn] = cross_check_one_race(eq, br)

    # Summary table
    print()
    print("SUMMARY")
    print("-" * 60)
    print(
        "Note: PgmOk = Equibase.program_number matches Brisnet.post_position\n"
        "      (Brisnet PP and Equibase PP differ by design — Equibase PP is\n"
        "      the post-scratch gate, Equibase program_number is the pre-scratch\n"
        "      entry. Pre-scratch entry == Brisnet PP. Use program_number for joins.)"
    )
    print()
    print(
        f"{'Race':>4}  {'Eq':>3}  {'Br':>3}  {'Match':>5}  "
        f"{'EqOnly':>6}  {'BrOnly':>6}  {'PgmOk':>5}  {'Naming':>6}  Status"
    )
    total_eq = total_br = total_match = total_pp_ok = total_naming = 0
    for rn in all_race_nums:
        r = per_race[rn]
        match = len(r["in_both"])
        eq_only = len(r["eq_only"])
        br_only = len(r["br_only"])
        pp_ok = len(r["pp_matches"])
        pp_mis = len(r["pp_mismatches"])
        naming = len(r["naming_mismatches"])

        total_eq += r["eq_count"]
        total_br += r["br_count"]
        total_match += match
        total_pp_ok += pp_ok
        total_naming += naming

        status = "OK" if (eq_only == 0 and br_only == 0 and pp_mis == 0 and naming == 0) else ""
        if br_only > 0 and naming == 0 and pp_mis == 0:
            status = f"{br_only} scratch(es)"
        if pp_mis > 0:
            status = f"PP MISMATCH x{pp_mis}"
        if naming > 0:
            status = f"NAMING x{naming}"

        print(
            f"{rn:>4}  {r['eq_count']:>3}  {r['br_count']:>3}  {match:>5}  "
            f"{eq_only:>6}  {br_only:>6}  {pp_ok:>4}  {naming:>6}  {status}"
        )

    print(
        f"\nOVERALL: {total_match}/{total_br} matched, "
        f"{total_pp_ok}/{total_match} PP-correct, "
        f"{total_br - total_match} Brisnet-only (scratches), "
        f"{total_naming} probable naming mismatches"
    )

    # Per-race detail for races with flags
    print()
    print("PER-RACE DETAIL (races with flags only)")
    print("-" * 60)
    any_detail = False
    for rn in all_race_nums:
        r = per_race[rn]
        flags = (
            len(r["eq_only"]) > 0
            or len(r["pp_mismatches"]) > 0
            or len(r["naming_mismatches"]) > 0
        )
        # Always show races with naming or pp issues; show br_only just if also other flags
        if not flags and not r["br_only"]:
            continue
        any_detail = True
        print(f"\nRACE {rn}:")
        print(f"  Equibase ({r['eq_count']}): {[eq_parser.normalize_name if False else h for h in []]}")  # placeholder
        eq_names_raw = [
            f"{name} (PP={info['post_position']})"
            for name, info in sorted(
                {h["name_norm"]: h for h in [hh for hh in br_by_race.get(rn, [])]}.items()
            )
        ]
        # Cleaner: show raw name lists from each source
        eq_list = sorted(
            (h["name_raw"], h["post_position"]) for h in eq_by_race.get(rn, [])
        )
        br_list = sorted(
            (h["name_raw"], h["post_position"]) for h in br_by_race.get(rn, [])
        )
        print(f"  Equibase ({len(eq_list)}): " + ", ".join(f"{n}@PP{p}" for n, p in eq_list))
        print(f"  Brisnet ({len(br_list)}):  " + ", ".join(f"{n}@PP{p}" for n, p in br_list))
        if r["br_only"]:
            print(f"  Brisnet-only (likely scratches): {r['br_only']}")
        if r["eq_only"]:
            print(f"  Equibase-only: {r['eq_only']}")
        if r["pp_mismatches"]:
            print(f"  PP MISMATCHES (Equibase.program_number vs Brisnet.post_position):")
            for pm in r["pp_mismatches"]:
                print(
                    f"    - {pm['name']}: Equibase pgm={pm['eq_program_number']!r}  Brisnet PP={pm['br_pp']}"
                )
        if r["gate_shifts"]:
            print(f"  Gate-position shifts (informational — post-scratch vs pre-scratch):")
            for gs in r["gate_shifts"][:5]:
                print(
                    f"    - {gs['name']}: Eq.post_position={gs['eq_pp']}  Br.post_position={gs['br_pp']}  shift={gs['shift']:+d}"
                )
            if len(r["gate_shifts"]) > 5:
                print(f"    ... and {len(r['gate_shifts']) - 5} more")
        if r["naming_mismatches"]:
            print(f"  PROBABLE NAMING MISMATCHES:")
            for nm in r["naming_mismatches"]:
                print(
                    f"    - {nm['eq_name']!r} (Equibase, raw={nm['eq_raw']!r}, "
                    f"PP={nm['eq_pp']})  ~~  "
                    f"{nm['br_name']!r} (Brisnet, raw={nm['br_raw']!r}, "
                    f"PP={nm['br_pp']})  edit_dist={nm['edit_distance']}"
                )
    if not any_detail:
        print("(All races clean.)")

    return per_race


if __name__ == "__main__":
    eq = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_EQUIBASE_PDF
    br = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_BRISNET_DRF
    main(eq, br)
