"""
brisnet_fetcher.py — EDGE Intelligence Platform
Locates Brisnet PP Single Files (.drf) from horse_racing_data/ for use in
the Car Wash pipeline.

WORKFLOW (IMPORTANT — read this before running)
-----------------------------------------------
Brisnet requires an authenticated browser session to download files. The
automated login approach (below) may fail if Brisnet changes their login
form. The reliable workflow is:

  1. Log into brisnet.com manually in your browser.
  2. Download the PP Single File (.drf) for the race you want to analyze.
  3. Drop the file into horse_racing_data/ using the naming convention:
       {TRACK_CODE}_{YYYYMMDD}.drf   e.g.  KEE_20260407.drf
  4. Run the Car Wash:
       python edge_server.py   (then use Trainer Scout tab in the platform)

fetch_race_card() checks horse_racing_data/ first and returns the path to
the local file. It does NOT attempt any network request. If no file is
found it prints a clear download instruction and returns None.

HOW TO VERIFY BRISNET ENDPOINTS (if you want to attempt automated download):
  1. Open Chrome DevTools → Network tab
  2. Log into brisnet.com manually and download a PP file
  3. Find the POST request to the login form — check the action URL and field names
  4. Find the GET/POST that downloads the .drf — copy that URL
  5. Update LOGIN_URL, LOGIN_FIELDS, PP_DOWNLOAD_URL, ETD_DOWNLOAD_URL below
"""

import os
import sys
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
# HELPERS
# ---------------------------------------------------------------------------

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

    # Brisnet login failure typically returns the login page again with "Invalid" text
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
    ext = "drf" if file_type == "pp" else "etd"
    filename = f"{track_code.upper()}_{race_date}.{ext}"
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

    # Guard: if response is HTML it's probably an error page, not a data file
    content_type = resp.headers.get("Content-Type", "")
    if "text/html" in content_type:
        snippet = resp.text[:400].strip()
        raise BrisnetDownloadError(
            f"Expected a binary data file but received HTML. "
            f"The download URL may be wrong or authentication failed mid-session.\n"
            f"URL: {resp.url}\n"
            f"Response snippet: {snippet}"
        )

    # Stream to disk
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
# CUSTOM EXCEPTIONS
# ---------------------------------------------------------------------------

class BrisnetError(Exception):
    """Base class for all brisnet_fetcher errors."""

class BrisnetAuthError(BrisnetError):
    """Raised when login fails."""

class BrisnetDownloadError(BrisnetError):
    """Raised when a file download fails."""


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------

def fetch_race_card(track_code: str, race_date: str = None) -> "str | None":
    """
    Locate a local DRF file for the given track (and optionally date).

    WORKFLOW
    --------
    Brisnet requires an authenticated browser session to download files.
    Download the PP Single File (.drf) manually from brisnet.com, drop it
    in horse_racing_data/ using the naming convention:

        {TRACK_CODE}_{YYYYMMDD}.drf    e.g.  KEE_20260407.drf

    This function then finds it automatically before the Car Wash runs.

    FILE SEARCH PRIORITY
    --------------------
    1. horse_racing_data/{TRACK_CODE}_{YYYYMMDD}.drf  (exact date match)
    2. horse_racing_data/{TRACK_CODE}_*.drf           (any date, most recent first)
    3. horse_racing_data/*.drf                        (any track, most recent first)

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

    track_code = track_code.upper().strip()
    if race_date is None:
        race_date = _date.today().strftime("%Y%m%d")
    race_date = race_date.strip()

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # ── Priority 1: exact match — TRACK_YYYYMMDD.drf ─────────────────────
    exact = DATA_DIR / f"{track_code}_{race_date}.drf"
    if exact.exists():
        print(f"[fetcher] Using local DRF: {exact.name}")
        return str(exact)

    # ── Priority 2: any date for this track — TRACK_*.drf ────────────────
    track_matches = sorted(
        DATA_DIR.glob(f"{track_code}_*.drf"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if track_matches:
        chosen = track_matches[0]
        print(
            f"[fetcher] Using local DRF: {chosen.name}"
            f"  (no exact date match for {race_date} — using most recent file for {track_code})"
        )
        return str(chosen)

    # ── Priority 3: any .drf file (fallback) ─────────────────────────────
    any_drfs = sorted(
        DATA_DIR.glob("*.drf"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if any_drfs:
        chosen = any_drfs[0]
        print(
            f"[fetcher] Using local DRF: {chosen.name}"
            f"  (fallback — no {track_code} file found, using most recent available)"
        )
        return str(chosen)

    # ── No file found ─────────────────────────────────────────────────────
    print(
        f"[fetcher] No local DRF file found for {track_code} in horse_racing_data/. "
        f"Download today's DRF from brisnet.com and drop it in horse_racing_data/ then retry."
    )
    return None


# ---------------------------------------------------------------------------
# LIST HELPER
# ---------------------------------------------------------------------------

def list_available_drfs() -> None:
    """
    Print all .drf files currently in horse_racing_data/ with their
    track code, date (parsed from filename), and file size.

    Call this to verify which files are available before running the Car Wash.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    drfs = sorted(DATA_DIR.glob("*.drf"), key=lambda p: p.stat().st_mtime, reverse=True)

    print(f"\nAvailable DRF files in {DATA_DIR}:")
    print("-" * 60)
    if not drfs:
        print("  (none — download a .drf file from brisnet.com and drop it here)")
    else:
        for f in drfs:
            size     = f.stat().st_size
            stem     = f.stem                      # e.g. "KEE_20260407"
            parts    = stem.split("_", 1)
            track    = parts[0] if parts else "?"
            date_str = parts[1] if len(parts) > 1 else "?"
            print(f"  {f.name:<35}  track={track:<6}  date={date_str:<12}  {size:>10,} bytes")
    print("-" * 60)
    print()


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
# MAIN TEST BLOCK — prints TRACK_CODES and function signature, no login
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from datetime import date as _date

    print("=" * 60)
    print("BRISNET FETCHER — EDGE Intelligence Platform")
    print("=" * 60)
    print(f"Data directory : {DATA_DIR}")
    print()

    # ── Step 5: list all available DRF files ─────────────────────────────
    list_available_drfs()

    # ── Test fetch_race_card for today ────────────────────────────────────
    TODAY = _date.today().strftime("%Y%m%d")
    print(f"Testing fetch_race_card('KEE', '{TODAY}') ...")
    result = fetch_race_card("KEE", TODAY)
    if result:
        print(f"  → Found: {result}")
    else:
        print(f"  → None returned (no DRF file present — expected if none downloaded yet)")

    print()
    print("TRACK_CODES reference:")
    for name, code in sorted(TRACK_CODES.items(), key=lambda x: x[1]):
        print(f"  {code:<6}  {name}")

    print()
    print("Naming convention for manual downloads:")
    print("  {TRACK_CODE}_{YYYYMMDD}.drf   e.g.  KEE_20260407.drf")
    print(f"  Drop files in: {DATA_DIR}")
    print()
    print("Checkpoint 4 self-test: import check")
    print("  python -c \"import brisnet_fetcher; print('OK')\"")
