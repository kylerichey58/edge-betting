"""
brisnet_fetcher.py — EDGE Intelligence Platform
Locates Brisnet PP Single Files (.DRF) from horse_racing_data/ for use in
the Car Wash pipeline.

WORKFLOW (IMPORTANT — read this before running)
-----------------------------------------------
Brisnet requires an authenticated browser session to download files. The
reliable workflow is:

  1. Log into brisnet.com manually in your browser.
  2. Download the PP Single File (.drf) for the race card you want.
     Brisnet delivers a ZIP file: {TRACK}{MMDD}n.zip  e.g.  GPX0409n.zip
  3. Drop the ZIP into horse_racing_data/   — OR —   leave it in Downloads/.
     This script auto-extracts *n.zip files from both locations.
  4. Run the Car Wash:
       python edge_server.py   (then use Trainer Scout tab in the platform)

BRISNET FILE NAMING CONVENTION
-------------------------------
  ZIP file:  {TRACK}{MMDD}n.zip      e.g.  GPX0409n.zip, KEE0407n.zip
  DRF inside: {TRACK}{MMDD}.DRF     e.g.  GPX0409.DRF, KEE0407.DRF
  No underscore. No year. All-caps track code and extension.

fetch_race_card() auto-extracts ZIPs from Downloads/ then searches
horse_racing_data/ for the matching DRF. Returns None (not a demo) if
no file found — the server then returns HTTP 400 with an actionable message.

HOW TO VERIFY BRISNET ENDPOINTS (if you want to attempt automated download):
  1. Open Chrome DevTools → Network tab
  2. Log into brisnet.com manually and download a PP file
  3. Find the POST request to the login form — check the action URL and field names
  4. Find the GET/POST that downloads the .drf — copy that URL
  5. Update LOGIN_URL, LOGIN_FIELDS, PP_DOWNLOAD_URL, ETD_DOWNLOAD_URL below
"""

import os
import sys
import zipfile
import shutil
from pathlib import Path
from dotenv import load_dotenv

# requests is imported lazily inside functions that use it so that
# 'import brisnet_fetcher' does not trigger network/SSL initialization.
# On Kyle's machine this works fine; in restricted sandboxes import requests
# can hang waiting for SSL certificate stores or proxy resolution.

# ---------------------------------------------------------------------------
# TRACK CODES — Brisnet 2-3 letter codes
# ---------------------------------------------------------------------------
TRACK_CODES = {
    "Churchill Downs":   "CD",
    "Keeneland":         "KEE",
    "Gulfstream":        "GP",
    "Santa Anita":       "SA",
    "Saratoga":          "SAR",
    "Belmont":           "BEL",
    "Aqueduct":          "AQU",
    "Del Mar":           "DMR",
    "Fair Grounds":      "FG",
    "Tampa Bay Downs":   "TAM",
    "Turfway Park":      "TP",
    "Laurel":            "LRL",
    "Pimlico":           "PIM",
    "Oaklawn":           "OP",
}

# Reverse lookup: code → display name
TRACK_NAMES = {v: k for k, v in TRACK_CODES.items()}

# ---------------------------------------------------------------------------
# BRISNET ENDPOINT CONFIGURATION
#
# These are based on Brisnet's standard cgi-bin URL patterns (active Data Plan).
# If any URL returns 404 or a redirect to the login page, open Chrome DevTools,
# log in manually, download a file, and inspect the Network tab to confirm
# the correct endpoint and parameter names — then update below.
# ---------------------------------------------------------------------------

BASE_URL        = "https://www.brisnet.com"

# Login endpoint — POST your credentials here
LOGIN_URL       = f"{BASE_URL}/cgi-bin/login.cgi"

# Form field names for the login POST (inspect the login form HTML if these fail)
LOGIN_FIELDS    = {
    "username_field": "id",       # <input name="id"> on brisnet.com login form
    "password_field": "pw",       # <input name="pw"> on brisnet.com login form
    "submit_field":   "submit",
    "submit_value":   "Log In",
}

# Download endpoints — track code and date (MMDDYY format for Brisnet) injected at runtime
# Brisnet date format for downloads is MMDDYY (e.g., 040426 for April 4, 2026)
PP_DOWNLOAD_URL  = f"{BASE_URL}/cgi-bin/getpp.cgi"
ETD_DOWNLOAD_URL = f"{BASE_URL}/cgi-bin/getetd.cgi"

# Query param names for the download requests
DOWNLOAD_PARAMS = {
    "track_param": "trk",    # e.g., trk=CD
    "date_param":  "dt",     # e.g., dt=040426  (MMDDYY)
    "bc_param":    "bc",     # billing code — always 1 for single-card purchases
}

# ---------------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------------
SCRIPT_DIR       = Path(__file__).parent
DATA_DIR         = SCRIPT_DIR / "horse_racing_data"
ENV_FILE         = SCRIPT_DIR / ".env"

# ---------------------------------------------------------------------------
# CUSTOM EXCEPTIONS
# ---------------------------------------------------------------------------

class BrisnetError(Exception):
    """Base class for all brisnet_fetcher errors."""

class BrisnetAuthError(BrisnetError):
    """Raised when login fails."""

class BrisnetDownloadError(BrisnetError):
    """Raised when a file download fails."""


# ---------------------------------------------------------------------------
# INTERNAL HELPERS
# ---------------------------------------------------------------------------

def _find_drfs() -> list:
    """
    Return all .DRF files in DATA_DIR (case-insensitive extension match),
    sorted most-recently-modified first.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    found = [
        p for p in DATA_DIR.iterdir()
        if p.is_file() and p.suffix.upper() == ".DRF"
    ]
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def _parse_drf_filename(path: Path) -> tuple:
    """
    Parse a Brisnet DRF filename: {TRACKCODE}{MMDD}.DRF
    Returns (track_code_upper, mmdd_str) or (stem_upper, '') if not parseable.

    Examples:
        GPX0409.DRF  →  ('GPX', '0409')
        KEE0408.DRF  →  ('KEE', '0408')
        CD0407.DRF   →  ('CD',  '0407')
    """
    stem = path.stem.upper()   # e.g. 'GPX0409'
    # Last 4 chars must be digits (MMDD)
    if len(stem) >= 5 and stem[-4:].isdigit():
        return stem[:-4], stem[-4:]
    return stem, ""


def extract_brisnet_zip(zip_path: "str | Path") -> list:
    """
    Extract all .DRF files from a Brisnet ZIP file into horse_racing_data/.

    Brisnet ZIP naming: {TRACK}{MMDD}n.zip   e.g.  GPX0409n.zip
    DRF inside:         {TRACK}{MMDD}.DRF    e.g.  GPX0409.DRF

    - Normalises extracted filenames to ALL-CAPS (e.g. gpx0409.drf → GPX0409.DRF)
    - Skips extraction if the .DRF already exists in DATA_DIR
    - Also extracts .DR2/.DR3/.DR4 companion files if present

    Returns list of Path objects for extracted .DRF files only.
    """
    zip_path = Path(zip_path)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    extracted = []

    if not zip_path.exists():
        print(f"[fetcher] ZIP not found: {zip_path}")
        return extracted

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.namelist():
                member_path = Path(member)
                upper_name  = member_path.name.upper()
                dest        = DATA_DIR / upper_name

                # Extract all data files (.DRF, .DR2, .DR3, .DR4)
                if member_path.suffix.upper() not in (".DRF", ".DR2", ".DR3", ".DR4"):
                    continue

                if dest.exists():
                    print(f"[fetcher] Already extracted: {upper_name} — skipping")
                    if member_path.suffix.upper() == ".DRF":
                        extracted.append(dest)
                    continue

                # Write to a temp path then move (handles cross-device rename)
                tmp = DATA_DIR / (upper_name + ".tmp")
                with zf.open(member) as src, open(tmp, "wb") as dst:
                    dst.write(src.read())
                shutil.move(str(tmp), str(dest))
                print(f"[fetcher] Extracted: {upper_name} ← {zip_path.name}")

                if member_path.suffix.upper() == ".DRF":
                    extracted.append(dest)

    except zipfile.BadZipFile as e:
        print(f"[fetcher] Bad ZIP file {zip_path.name}: {e}")
    except Exception as e:
        print(f"[fetcher] Error extracting {zip_path.name}: {e}")

    return extracted


def _auto_extract_downloads() -> None:
    """
    Scan the user's Downloads folder for Brisnet ZIP files (*n.zip) and
    auto-extract any .DRF files not already present in horse_racing_data/.

    Brisnet ZIP naming convention:  {TRACK}{MMDD}n.zip  e.g. GPX0409n.zip
    Only files ending in 'n.zip' (lowercase 'n' before .zip) are matched.
    Silent no-op if Downloads/ doesn't exist or contains no matching ZIPs.
    """
    downloads = Path.home() / "Downloads"
    if not downloads.exists():
        return

    # *n.zip pattern — the 'n' suffix is Brisnet's naming for their downloads
    zips = list(downloads.glob("*n.zip"))
    if not zips:
        return

    # Existing DRF uppercase names — avoid re-extraction
    existing_names = {p.name.upper() for p in _find_drfs()}

    for zip_path in zips:
        # Infer expected DRF name: GPX0409n.zip → GPX0409.DRF
        stem = zip_path.stem  # e.g. 'GPX0409n'
        if stem.endswith("n"):
            expected_drf = stem[:-1].upper() + ".DRF"
            if expected_drf in existing_names:
                continue  # already extracted
        # Extract — will skip individual files that already exist
        extract_brisnet_zip(zip_path)


def _load_credentials():
    """Load BRISNET_USERNAME and BRISNET_PASSWORD from .env."""
    load_dotenv(ENV_FILE)
    username = os.getenv("BRISNET_USERNAME")
    password = os.getenv("BRISNET_PASSWORD")
    if not username or not password:
        raise EnvironmentError(
            "BRISNET_USERNAME and/or BRISNET_PASSWORD not found in .env. "
            f"Looked in: {ENV_FILE}"
        )
    return username, password


def _yyyymmdd_to_brisnet(race_date: str) -> str:
    """
    Convert YYYYMMDD → MMDDYY (Brisnet's expected date format).
    Example: '20260404' → '040426'
    """
    if len(race_date) != 8 or not race_date.isdigit():
        raise ValueError(f"race_date must be YYYYMMDD, got: {race_date!r}")
    yyyy = race_date[0:4]
    mm   = race_date[4:6]
    dd   = race_date[6:8]
    yy   = yyyy[2:]          # last two digits of year
    return f"{mm}{dd}{yy}"


def _login(session, username: str, password: str) -> None:
    """
    POST credentials to Brisnet login endpoint and persist the session cookie.
    Raises BrisnetAuthError if login appears to have failed.
    """
    payload = {
        LOGIN_FIELDS["username_field"]: username,
        LOGIN_FIELDS["password_field"]: password,
        LOGIN_FIELDS["submit_field"]:   LOGIN_FIELDS["submit_value"],
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36",
        "Referer": BASE_URL,
    }

    resp = session.post(LOGIN_URL, data=payload, headers=headers, timeout=30, allow_redirects=True)

    if resp.status_code != 200:
        raise BrisnetAuthError(
            f"Login POST returned HTTP {resp.status_code}. "
            f"Check LOGIN_URL: {LOGIN_URL}"
        )

    lowered = resp.text.lower()
    failure_signals = ["invalid", "incorrect", "failed", "log in", "sign in"]
    success_signals = ["logout", "log out", "account", "my account", "welcome"]

    has_failure = any(sig in lowered for sig in failure_signals)
    has_success = any(sig in lowered for sig in success_signals)

    if has_failure and not has_success:
        raise BrisnetAuthError(
            "Login appeared to fail — response page looks like the login form. "
            "Check BRISNET_USERNAME / BRISNET_PASSWORD in .env, or verify "
            f"LOGIN_URL ({LOGIN_URL}) and form field names ({LOGIN_FIELDS}) "
            "using browser DevTools."
        )


def _build_output_path(track_code: str, race_date: str, file_type: str) -> Path:
    """Return the expected output path for a given track/date/type."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Use new naming convention: {TRACK}{MMDD}.DRF
    mmdd = race_date[4:6] + race_date[6:8]
    ext  = "DRF" if file_type == "pp" else "ETD"
    filename = f"{track_code.upper()}{mmdd}.{ext}"
    return DATA_DIR / filename


def _download_file(
    session,
    track_code: str,
    race_date: str,
    file_type: str,
    output_path: Path,
) -> None:
    """
    Download the data file from Brisnet using the authenticated session.
    Streams directly to disk to handle large files gracefully.
    """
    brisnet_date = _yyyymmdd_to_brisnet(race_date)
    track_upper  = track_code.upper()

    if file_type == "pp":
        url = PP_DOWNLOAD_URL
    elif file_type == "etd":
        url = ETD_DOWNLOAD_URL
    else:
        raise ValueError(f"file_type must be 'pp' or 'etd', got: {file_type!r}")

    params = {
        DOWNLOAD_PARAMS["track_param"]: track_upper,
        DOWNLOAD_PARAMS["date_param"]:  brisnet_date,
        DOWNLOAD_PARAMS["bc_param"]:    "1",
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/124.0.0.0 Safari/537.36",
        "Referer": BASE_URL,
    }

    print(f"  [fetcher] Requesting: {url} params={params}")
    resp = session.get(url, params=params, headers=headers, stream=True, timeout=60)

    if resp.status_code != 200:
        raise BrisnetDownloadError(
            f"Download returned HTTP {resp.status_code} for {track_upper} {race_date}. "
            f"URL attempted: {resp.url}\n"
            "If you get a redirect to the login page, the session cookie may have "
            "expired or the download URL pattern needs updating. Check DevTools."
        )

    content_type = resp.headers.get("Content-Type", "")
    if "text/html" in content_type:
        snippet = resp.text[:400].strip()
        raise BrisnetDownloadError(
            f"Expected a binary data file but received HTML. "
            f"The download URL may be wrong or authentication failed mid-session.\n"
            f"URL: {resp.url}\n"
            f"Response snippet: {snippet}"
        )

    bytes_written = 0
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
                bytes_written += len(chunk)

    if bytes_written == 0:
        output_path.unlink(missing_ok=True)
        raise BrisnetDownloadError(
            f"Download completed but file was empty. "
            f"URL: {resp.url} — verify the track code and date are available on Brisnet."
        )

    print(f"  [fetcher] Saved {bytes_written:,} bytes → {output_path}")


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------

def fetch_race_card(track_code: str, race_date: str = None) -> "str | None":
    """
    Locate a local DRF file for the given track (and optionally date).

    Automatically scans Downloads/ for Brisnet ZIPs (*n.zip) and extracts
    them into horse_racing_data/ before searching.

    FILE NAMING CONVENTION
    ----------------------
    Brisnet delivers ZIPs:   {TRACK}{MMDD}n.zip   e.g.  KEE0407n.zip
    Extracted DRF inside:    {TRACK}{MMDD}.DRF    e.g.  KEE0407.DRF

    FILE SEARCH PRIORITY
    --------------------
    1. horse_racing_data/{TRACK}{MMDD}.DRF   (exact track + today's date)
    2. horse_racing_data/{TRACK}*.DRF        (same track, any date — most recent)
    3. horse_racing_data/*.DRF               (any track — most recent)

    Parameters
    ----------
    track_code : str
        2-3 letter Brisnet track code (e.g., 'CD', 'KEE', 'GP').
    race_date : str, optional
        Date in YYYYMMDD format. Defaults to today's date.

    Returns
    -------
    str
        Absolute path to the local DRF file.
    None
        If no DRF file is found in horse_racing_data/.
        Caller should display a download instruction to the user.
    """
    from datetime import date as _date

    track_upper = track_code.upper().strip()
    if race_date is None:
        race_date = _date.today().strftime("%Y%m%d")
    race_date = race_date.strip()

    # Auto-extract any Brisnet ZIPs from Downloads/ before searching
    _auto_extract_downloads()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Today's MMDD for exact-date matching (e.g. '20260409' → '0409')
    mmdd_today  = race_date[4:6] + race_date[6:8]
    exact_upper = f"{track_upper}{mmdd_today}.DRF"

    all_drfs = _find_drfs()  # sorted most-recent-first

    # ── Priority 1: exact track+date match ───────────────────────────
    for f in all_drfs:
        if f.name.upper() == exact_upper:
            print(f"[fetcher] Using local DRF: {f.name}")
            return str(f)

    # ── Priority 2: any date for this track ──────────────────────────
    track_matches = [
        f for f in all_drfs
        if f.name.upper().startswith(track_upper) and f.name.upper().endswith(".DRF")
    ]
    if track_matches:
        chosen = track_matches[0]
        print(
            f"[fetcher] Using local DRF: {chosen.name}"
            f"  (no exact date {mmdd_today} — using most recent for {track_upper})"
        )
        return str(chosen)

    # ── Priority 3: any .DRF file (fallback) ─────────────────────────
    if all_drfs:
        chosen = all_drfs[0]
        print(
            f"[fetcher] Using local DRF: {chosen.name}"
            f"  (fallback — no {track_upper} file found, using most recent available)"
        )
        return str(chosen)

    # ── No file found ─────────────────────────────────────────────────
    print(
        f"[fetcher] No DRF file found for {track_upper} in horse_racing_data/.\n"
        f"  Download today's PP Single File from brisnet.com — Brisnet delivers a\n"
        f"  ZIP file named  {track_upper}MMDDn.zip  (e.g. {track_upper}0407n.zip).\n"
        f"  Drop the ZIP into horse_racing_data/  or  Downloads/  then retry."
    )
    return None


def list_available_drfs() -> list:
    """
    Return a list of dicts for all DRF files currently in horse_racing_data/.
    Also prints a summary table to stdout.

    Each dict:
        {
          'track_code':   'KEE',
          'mmdd':         '0407',
          'display_name': 'KEE — 04/07',
          'filepath':     '/path/to/horse_racing_data/KEE0407.DRF',
        }
    """
    drfs   = _find_drfs()
    result = []

    print(f"\nAvailable DRF files in {DATA_DIR}:")
    print("-" * 60)
    if not drfs:
        print("  (none — drop a Brisnet ZIP into horse_racing_data/ or Downloads/)")
    else:
        for f in drfs:
            track_code, mmdd = _parse_drf_filename(f)
            size = f.stat().st_size

            if len(mmdd) == 4:
                date_display = f"{mmdd[:2]}/{mmdd[2:]}"
            else:
                date_display = mmdd or "?"
            display_name = f"{track_code} — {date_display}"

            print(
                f"  {f.name:<30}  track={track_code:<6}  "
                f"date={date_display:<8}  {size:>10,} bytes"
            )
            result.append({
                "track_code":   track_code,
                "mmdd":         mmdd,
                "display_name": display_name,
                "filepath":     str(f),
            })

    print("-" * 60)
    print()
    return result


def get_available_tracks() -> list:
    """
    Return a list of track dicts for the UI dropdown, de-duplicated by
    track code (most-recently-modified DRF wins for each track).

    Runs auto-extract from Downloads/ first so freshly downloaded ZIPs
    appear without a manual refresh.

    Each dict:
        {
          'value': 'KEE',
          'label': 'KEE — 04/07',
          'mmdd':  '0407',
        }

    Returns empty list if no DRF files are present.
    """
    _auto_extract_downloads()
    drfs = _find_drfs()  # sorted most-recent-first

    seen   = set()
    tracks = []
    for f in drfs:
        track_code, mmdd = _parse_drf_filename(f)
        if track_code in seen or not track_code:
            continue
        seen.add(track_code)
        if len(mmdd) == 4:
            date_display = f"{mmdd[:2]}/{mmdd[2:]}"
        else:
            date_display = mmdd or "?"
        label = f"{track_code} — {date_display}"
        tracks.append({
            "value": track_code,
            "label": label,
            "mmdd":  mmdd,
        })

    return tracks


def verify_endpoints() -> None:
    """
    Utility: attempt to reach Brisnet login page (no credentials needed).
    Useful for confirming network connectivity and that the BASE_URL is reachable.
    Prints status without logging in.
    """
    import requests  # lazy import
    print(f"[verify] Checking base URL: {BASE_URL}")
    try:
        resp = requests.get(BASE_URL, timeout=10)
        print(f"[verify] Base URL reachable — HTTP {resp.status_code}")
    except requests.RequestException as e:
        print(f"[verify] Base URL NOT reachable: {e}")

    print(f"[verify] Login URL configured as: {LOGIN_URL}")
    print(f"[verify] Login fields: {LOGIN_FIELDS}")
    print(f"[verify] PP download URL: {PP_DOWNLOAD_URL}")
    print(f"[verify] ETD download URL: {ETD_DOWNLOAD_URL}")
    print(f"[verify] Download params: {DOWNLOAD_PARAMS}")
    print(f"[verify] Data directory: {DATA_DIR}")
    print()
    print("[verify] If downloads fail, open Chrome DevTools → Network tab,")
    print("[verify] log into brisnet.com, download a file manually, then")
    print("[verify] inspect the POST (login) and GET (download) requests")
    print("[verify] to confirm the correct URLs and parameter names.")


# ---------------------------------------------------------------------------
# MAIN TEST BLOCK
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from datetime import date as _date

    print("=" * 60)
    print("BRISNET FETCHER — EDGE Intelligence Platform")
    print("=" * 60)
    print(f"Data directory : {DATA_DIR}")
    print(f"Downloads scan : {Path.home() / 'Downloads'}")
    print()

    # ── Auto-extract any ZIPs from Downloads ─────────────────────────
    print("Scanning Downloads/ for Brisnet ZIPs (*n.zip)...")
    _auto_extract_downloads()

    # ── List all available DRF files ─────────────────────────────────
    drfs = list_available_drfs()

    # ── Test get_available_tracks ─────────────────────────────────────
    tracks = get_available_tracks()
    print(f"get_available_tracks() returned {len(tracks)} track(s):")
    for t in tracks:
        print(f"  value={t['value']:<6}  label={t['label']}")
    print()

    # ── Test fetch_race_card for today ────────────────────────────────
    TODAY = _date.today().strftime("%Y%m%d")
    print(f"Testing fetch_race_card('KEE', '{TODAY}') ...")
    result = fetch_race_card("KEE", TODAY)
    if result:
        print(f"  → Found: {result}")
    else:
        print("  → None returned (no DRF file present — expected if none downloaded yet)")

    print()
    print("TRACK_CODES reference:")
    for name, code in sorted(TRACK_CODES.items(), key=lambda x: x[1]):
        print(f"  {code:<6}  {name}")

    print()
    print("Brisnet file naming convention:")
    print("  ZIP:  {TRACK}{MMDD}n.zip   e.g.  KEE0407n.zip")
    print("  DRF:  {TRACK}{MMDD}.DRF    e.g.  KEE0407.DRF")
    print(f"  Drop ZIPs in: {DATA_DIR}  or  {Path.home() / 'Downloads'}")
    print()
    print("Checkpoint 4 self-test: import check")
    print("  python -c \"import brisnet_fetcher; print('OK')\"")
