# EDGE PLATFORM — DAILY RESULTS FETCH
# Use this prompt every race day after the card finishes.
# Fill in TRACK and DATE then paste into Cowork.

---

## DAILY FETCH PROMPT (copy and fill in below)

Fetch race results for [TRACK CODE] on [DATE].

Steps:
1. Build the Brisnet results URL using this pattern:
   https://www.brisnet.com/product/download/{YYYY-MM-DD}/INR/USA/TB/{TRACK}/D/0/

   Use TRACK_CODE_MAP from results_fetcher.py to convert
   DRF code to Brisnet code if needed:
   GPX → GP, all others match directly.

2. Open Chrome, navigate directly to that URL.
   Session should be live — kylerichey58 is logged in
   with Remember Me on the Brisnet bookmark.
   If login screen appears, stop and tell me.

3. Capture the full page HTML using:
   document.documentElement.outerHTML

4. Save to:
   C:\Users\kyler\Documents\SportsBetting\horse_racing_data\{TRACK}{MMDD}_results.html
   Example: GP0407_results.html

5. Run in SportsBetting terminal:
   python results_fetcher.py

6. Paste the full terminal output back to me.

---

## TRACK CODE REFERENCE

| I say | URL uses | Filename saved as |
|-------|----------|------------------|
| GP or GPX | GP | GP{MMDD}_results.html |
| MVR | MVR | MVR{MMDD}_results.html |
| KEE | KEE | KEE{MMDD}_results.html |
| SA | SA | SA{MMDD}_results.html |
| AQU | AQU | AQU{MMDD}_results.html |
| CD | CD | CD{MMDD}_results.html |
| OP | OP | OP{MMDD}_results.html |

---

## EXAMPLE — How to trigger this

Say to Cowork:
"Fetch results for GP April 7"
"Fetch results for KEE April 9"
"Fetch results for MVR April 7"

Cowork reads this file, builds the URL, fetches, saves, grades. Done.

---

## IMPORT RESULTS FILE (optional — for races you bet)

If you purchased the $0.75 Import Results File for a race:
1. Download the CSV from brisnet.com → Results → Import Results Files
2. Save to horse_racing_data/ folder
3. Run: python results_fetcher.py horse_racing_data/{filename}.csv

This captures closing odds in addition to finish positions.
