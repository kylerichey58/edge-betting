# Chart Parser Technical Reference

**Source:** `kenthunt/chart-parser` (MIT license, GitHub) — Java + Apache PDFBox
**Purpose of this doc:** Document the spatial-extraction approach used in that project so a fresh Cowork session can build a Python equivalent (`pdfplumber`-based) for the EDGE Platform Horse Racing Wing.
**Created:** May 4, 2026 (post Prompt 3 BUG-1 / BUG-2 halt)

---

## TL;DR — the headline

**Equibase result chart PDFs use plain readable text for beaten lengths.** Words like "Head", "Neck", "Nose" and fractions like "1 1/2" or "3/4" are encoded as actual UTF-8 characters with regular fonts. There is no proprietary glyph encoding. The `¨ © ª «` symbols Cowork hit when parsing **Brisnet** PDFs are an artifact of Brisnet's proprietary typesetting font — Equibase doesn't use them.

**This means:** if we shift our source from Brisnet's free Instant Charts PDFs to Equibase's free Full Charts PDFs (same data, also free, available within 40 minutes of every race), the entire glyph-decoding problem disappears.

The `kenthunt/chart-parser` project is built around Equibase PDFs and parses them robustly with no glyph table needed.

---

## The core technique (in one paragraph)

Rather than reading the PDF as a stream of text, the parser reads it as a stream of **positioned characters**. Each character carries its `(unicode, x_position, y_position, font_size, width)`. Characters are then grouped into rows by y-position (same row = same y, ±4 units), and within each row, grouped into columns by x-position (each column has a known x-range from the header). Once you have "all characters between x=X1 and x=X2 on row Y", you concatenate them into the cell's text. Beaten lengths come out as readable strings: `"2 1/2"`, `"Head"`, `"3/4"`. From there, regex parses them to decimal lengths.

That's the entire approach. Everything else is engineering details.

---

## Equibase vs Brisnet — confirmed differences

| | Brisnet Instant Charts | Equibase Full Charts |
|---|---|---|
| Cost | Free | Free |
| Available within | minutes | 40 minutes |
| Format | PDF | PDF |
| Beaten lengths encoding | Proprietary glyphs (`¨ © ª «`) | Plain text (`"1 1/2"`, `"Head"`) |
| Open-source parser exists | No | Yes (this project) |
| Coverage | All North American tracks | All North American tracks (official source) |
| Layout-identical to source? | Derived from Equibase | Original Equibase |

**Recommendation:** switch ingestion source to Equibase. The 54 Brisnet PDFs already downloaded for May 1–2 should be re-fetched from Equibase to feed the backfill cleanly. Going forward, the daily flow pulls from Equibase, not Brisnet.

---

## The four key Java files (and what each does)

### 1. `ChartCharacter.java` — the primitive

A POJO with these fields per character:
- `unicode` (char) — the actual character
- `xDirAdj` (double) — x position on the page
- `yDirAdj` (double) — y position
- `fontSize` (double)
- `xScale` (double)
- `height` (double)
- `widthOfSpace` (double)
- `widthDirAdj` (double) — character width

These are produced by extending `PDFTextStripper` from Apache PDFBox. **The Python equivalent is `pdfplumber.Page.chars`** — a list of dicts with keys `text`, `x0`, `x1`, `top`, `bottom`, `size`, `fontname`, etc. Same primitive, different API.

### 2. `Chart.java` — the convertToText method

Takes a list of `ChartCharacter`s and turns them into a string by:
- Concatenating their `unicode` values in order
- Inserting a space when adjacent characters have horizontal spacing > 0 and < 3 units
- Inserting a `|` (CSV-like separator) when spacing > 3 units (column boundary)
- Inserting a newline when the y-difference exceeds 4 units (row boundary)

The algorithm in pseudocode:

```
def convert_to_text(chars):
    sb = []
    prev = None
    for curr in chars:
        if prev is not None:
            spacing = curr.x - (prev.x + prev.width)
            if 0.001 < spacing <= 3:
                sb.append(" ")
            elif spacing > 3:
                sb.append("|")
            if abs(curr.y - prev.y) > 4:
                sb.append("\n")
        sb.append(curr.unicode)
        prev = curr
    return "".join(sb)
```

The thresholds (`0.001`, `3`, `4`) are tuning constants derived from the Equibase chart layout. They may need slight adjustment for our use; the project README notes "0.001 from ZERO; found a few occurrences of when it appeared there was rounding up."

### 3. `RunningLine.groupRunningLineCharactersByColumn()` — the column assignment

For a single horse's row, given the column index map from the header (e.g., "PP" starts at x=120, "St" starts at x=145, "1/4" starts at x=170, ...), each character is assigned to the column whose header x-position is the floor of the character's x-position.

In Java: `runningLineColumnIndices.floor(columnIndex)` where `runningLineColumnIndices` is a TreeSet sorted by x-position.

The algorithm in pseudocode:

```
def group_chars_by_column(chars, column_x_starts):
    """
    column_x_starts: dict like {120: "PP", 145: "St", 170: "Q1", ...}
    """
    sorted_starts = sorted(column_x_starts.keys())
    result = {col_name: [] for col_name in column_x_starts.values()}
    
    for char in chars:
        # find largest x_start <= char.x
        col_x = max(x for x in sorted_starts if x <= char.x)
        col_name = column_x_starts[col_x]
        result[col_name].append(char)
    
    return result
```

Once you have characters grouped by column, you call `convert_to_text()` on each group and you have the cell's text.

### 4. `ChartLengthsAhead.java` — the lengths decoder

This is the answer to BUG-1. Once you have a column's text content, decoding beaten lengths is regex-based:

```
TEXT_LENGTHS_AHEAD_PATTERN     = "Head|Neck|Nose"
LENGTHS_AND_FRACTION_PATTERN   = "((\d+) )?((\d+)/(\d+))"
EVEN_LENGTHS_PATTERN           = "^(\d+)$"

Decoding:
  "Nose"  → 0.05 lengths
  "Head"  → 0.10 lengths
  "Neck"  → 0.25 lengths
  "1/4"   → 0.25
  "1/2"   → 0.50
  "3/4"   → 0.75
  "1 1/2" → 1.50
  "2 3/4" → 2.75
  "12"    → 12.00
  ""      → 0.00 (winner / no value)
```

Three patterns, summed. So `"1 1/2"` first matches `LENGTHS_AND_FRACTION` (1 + 0.5 = 1.5), and `"2"` matches `EVEN_LENGTHS` (2.0). They're additive in the original code.

**This is a complete decoding table.** Equibase only uses these representations in their PDFs. No glyphs, no proprietary encoding.

---

## The points-of-call config (`points-of-call.json`)

The repo includes a pre-built JSON file — **1,424 lines, 44 distinct race distances** — mapping each distance to its expected call structure. For example:

- 5 furlongs (sprint): `Start`, `1/4`, `Str`, `Fin` (4 calls)
- 1 mile (route): `Start`, `1/4`, `1/2`, `Str`, `Fin` (5 calls)
- 1 1/4 miles (Derby distance): `Start`, `1/4`, `1/2`, `3/4`, `1m`, `Str`, `Fin` (7 calls)
- 2 miles (marathon): more calls

**This file is MIT-licensed and can be copied verbatim into our Python project.** It eliminates the per-race column-detection logic Cowork was trying to build empirically.

The file lives at: `src/main/resources/points_of_call/points-of-call.json` in the repo. We should copy it into our Python project as a static resource.

---

## How the algorithm runs end-to-end

1. **Open PDF** with pdfplumber
2. **For each page:**
   a. Extract all characters: `page.chars` → list of dicts
   b. Group characters into **rows** by y-position (within ±4 units)
   c. Identify the **header row** (contains "PP", "St", "1/4", "1/2", etc.) and record each column's starting x-position
   d. Look up the race distance to confirm the expected call structure (using points-of-call.json)
   e. For each subsequent row (a horse's running line):
      - Group its characters by column using the x-position floor logic
      - Concatenate each column's characters into text
      - Parse text into typed values:
        - Position columns → integer
        - Beaten-length columns → decimal (using the regex decoder)
        - Other columns → as-is
3. **Repeat per race** (a single PDF often contains all races on a card, separated by page breaks or "RACE N" headers)
4. **Emit** structured output (dict per race, list of horse dicts inside)

This is the complete algorithm. No proprietary knowledge required, no font tables, no glyph lookups.

---

## Edge cases the project handles

These came up repeatedly in the test files. Worth implementing in our Python parser:

- **Dead heats** — two horses tied for the same finish position; handled by detecting "DH" markers
- **Disqualifications** — original finish vs official finish; both stored
- **Walkovers** — race with one entrant; minimal data
- **Cancellations** — race scheduled but didn't run
- **Scratched horses** — listed but no running line
- **Coupled entries** — multiple horses bet as one (e.g., "1 / 1A"); program number letter suffix
- **Late changes** — distance changes off-turf, surface changes
- **Run-up distance** — feet from gate to timing start, in parens after distance
- **Marathons** with extra calls (3/4-mile call + 1-mile call before stretch)
- **Sprints** with fewer calls (no 1/2 or 3/4 calls)

The points-of-call.json handles the call-count variations automatically. The other edge cases are explicit code paths.

---

## What our Python implementation should be

A new module `horse_racing_pdf_parser_v2.py` in the Sportsbetting folder. Public API:

```python
def parse_chart_pdf(pdf_path: str | Path) -> dict | None:
    """
    Parse an Equibase Full Chart PDF.
    
    Returns:
        {
            'track': str,
            'race_date': str (ISO YYYY-MM-DD),
            'races': [
                {
                    'race_number': int,
                    'distance_feet': int,
                    'distance_text': str,
                    'surface': str ('D'/'T'/'S'/'I'),
                    'track_condition': str,
                    'pace_scenario': str | None ('HOT'/'MIXED'/'SLOW'),
                    'field_size': int,
                    'fractional_times_seconds': [float, ...],
                    'horses': [
                        {
                            'horse_name': str,
                            'post_position': int,
                            'start_position': int,
                            'pos_q1': int,
                            'beaten_lengths_q1': float,
                            'pos_q2': int | None,
                            'beaten_lengths_q2': float | None,
                            'pos_q3': int | None,
                            'beaten_lengths_q3': float | None,
                            'pos_str': int,
                            'beaten_lengths_str': float,
                            'finish_position': int,
                            'beaten_lengths_finish': float,
                            'final_time_seconds': float | None,
                            'final_odds': float,
                            'medication_code': str | None,
                            'equipment_code': str | None,
                            'weight_carried': int,
                            'jockey': str,
                            'trainer': str,
                            'start_descriptor': str | None,
                            'winning_manner': str | None,
                        },
                        ...
                    ]
                },
                ...
            ]
        }
    
    Returns None if the PDF cannot be parsed.
    """
```

Internal structure:

```
horse_racing_pdf_parser_v2.py
├── extract_chars(pdf_path)             # uses pdfplumber.Page.chars
├── group_chars_by_row(chars)           # y-position clustering, ±4 units
├── identify_header_row(rows)           # finds row with "PP St 1/4..."
├── build_column_map(header_row)        # column name → x_start mapping
├── group_row_chars_by_column(row, map) # x-position floor logic
├── decode_beaten_lengths(text)         # regex decoder, all 3 patterns
├── decode_position_cell(text)          # position digit
├── parse_race(race_chars, distance_meta) # full race extraction
└── parse_chart_pdf(pdf_path)           # public entry point

tests/test_pdf_parser_v2.py
└── self-test against Derby PDF and 2-3 other races
```

Plus the static resource:

```
horse_racing_data/points_of_call.json   # copied verbatim from MIT-licensed repo
```

---

## What changes for our use case (vs the reference)

The reference parser is a generic chart parser. Ours has additional requirements specific to the EDGE Platform:

1. **Pace scenario classification** — port HOT/MIXED/SLOW thresholds from `horse_racing_scorer.py`. The reference parser doesn't classify pace; it just emits fractional times.
2. **Surface remap** — Equibase uses `D`/`T`/`d`/`t` (where lowercase = inner). Our schema uses `D`/`T`/`I`/`S`. Map at parser output, not in the database.
3. **Derived final_time_seconds for non-winners** — winner's time + (beaten_lengths_finish × 0.2). Reference parser doesn't do this; we want it.
4. **Field size as len(horses)** — our schema column. Reference doesn't expose it explicitly but it's trivial to compute.
5. **Output format is `dict`/JSON-like, not Java POJOs** — obviously.
6. **Logging** — INFO per race parsed, WARNING on partial-data, ERROR on unparseable. Reference uses Java logging; ours uses Python `logging`.

---

## Known limitations of the reference (we should inherit awareness, decide case-by-case)

From reading the codebase:

- **Font-size column detection isn't used.** The reference assumes font size is uniform across cells in a row. If Equibase ever shipped a chart where a beaten-length glyph was rendered at a smaller font size, the parser might mis-group it. Hasn't been a problem in practice.
- **The y-position threshold of 4 units** for row boundaries is a magic number. Works for current Equibase layout. May need adjustment if Equibase changes their PDF generator.
- **Race conditions text** is parsed via separate logic (not in the running line). Long conditions paragraphs with line wraps require special handling.
- **No support for Quarter Horse / Arabian / Mixed breed race specifics beyond basic.** Fine for our Thoroughbred-only use case.

---

## Licensing note

The `kenthunt/chart-parser` project is MIT-licensed. We are free to:
- Copy the `points-of-call.json` file verbatim
- Implement the same algorithms in Python
- Use the test PDF (`ARP_2016-07-24_race-charts.pdf`) for our own validation

We should:
- Include a comment in our parser pointing to the source: `"# Algorithm adapted from kenthunt/chart-parser (MIT, https://github.com/kenthunt/chart-parser)"`
- Include the MIT license text in our project's LICENSE file or NOTICE file if we have one

We are NOT making this redistributable software; this is internal infrastructure for the EDGE Platform.

---

## Recommended phased build plan

When we draft the Cowork prompt for the fresh session, the build should phase like this — each phase ending in a stop-and-validate before moving to the next.

**Phase 1 — Foundation**
- Set up the new file structure
- Copy `points_of_call.json` into the project
- Implement `extract_chars()` using `pdfplumber.Page.chars`
- Implement `convert_to_text()` (the Java port, in Python)
- Self-test: extract chars from Derby PDF, dump first 50 chars, confirm coordinates look reasonable

**Phase 2 — Row and column grouping**
- Implement `group_chars_by_row()`
- Implement `identify_header_row()` and `build_column_map()`
- Implement `group_row_chars_by_column()`
- Self-test: extract one horse's row from Derby, group by column, dump column → text mapping

**Phase 3 — Decoders**
- Implement `decode_beaten_lengths()` with all 3 regex patterns
- Implement `decode_position_cell()`
- Self-test: feed known strings, assert correct decimal output (Nose=0.05, Head=0.10, Neck=0.25, "1 1/2"=1.5, etc.)

**Phase 4 — Race assembly**
- Implement `parse_race()` — combine row+column logic into per-horse dicts
- Apply EDGE-specific transforms (surface remap, pace classification, derived times, field_size)
- Self-test: parse one race from Derby PDF (suggest Race 12, the Derby itself), dump every horse's full dict

**Phase 5 — Multi-race PDF**
- Implement `parse_chart_pdf()` — handle multi-page, multi-race PDFs
- Self-test: parse the full Derby card (14 races), assert race_count, total horses

**Phase 6 — The Sovereignty sanity check**
- For Race 12 (Derby), dump Sovereignty's full row alongside the actual chart
- Verify: pos_q1 through finish_position are correct, beaten lengths are decimal, jockey/trainer are right, pace scenario classified

**Phase 7 — Bug list closeout**
- Document every edge case encountered
- Document every threshold that needed tuning
- Note known limitations for v2 of the v2

Each phase ends in a stop point with explicit "approved, proceed" before the next phase starts.

---

## Open questions to resolve before/during the build

1. **Equibase URL pattern for chart download** — what's the exact URL format and do we need account credentials? (Equibase Full Charts are free per their FAQ, but the download URL convention isn't immediately obvious from the search results.)
2. **Brisnet→Equibase track code mapping** — does Equibase use the same 3-letter codes as Brisnet/DRF? Likely yes for major tracks, may differ on smaller ones.
3. **PDF format stability** — Equibase has used the same chart format for years per the GitHub project's age (commits go back several years), but worth confirming on a 2026 chart that the layout still matches.
4. **What to do with the 54 Brisnet PDFs already downloaded** — re-fetch from Equibase for backfill consistency, or attempt to parse Brisnet PDFs with the same algorithm and accept lower confidence on glyph cases?
