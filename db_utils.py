"""
db_utils.py — EDGE Intelligence Platform
Safe SQLite write utility for NTFS mount compatibility.

WHY THIS EXISTS:
SQLite uses file-level locking for commit operations. When the DB lives on an
NTFS-mounted path (C:\\Users\\kyler\\Documents\\SportsBetting\\sports_betting.db),
the cross-filesystem write causes disk I/O errors on conn.commit() and leaves
stranded journal files that force a rollback. This has caused data loss on every
multi-track stress test session.

THE FIX:
All DB write operations go through this module. It copies the DB to a local
scratch path, performs the operation there, then writes back to the mount
using Python's explicit byte-by-byte method (shutil.copyfileobj) which bypasses
the NTFS locking issue. Read-only operations (SELECT) can still connect directly.

USAGE:
    from db_utils import safe_write, safe_read, get_db_path

    # For any INSERT / UPDATE / DELETE:
    with safe_write() as conn:
        conn.execute("INSERT INTO bets ...")
        # commit happens automatically on context exit

    # For SELECT only:
    with safe_read() as conn:
        rows = conn.execute("SELECT ...").fetchall()

NEVER do this:
    conn = sqlite3.connect(DB_PATH)   # direct mount write — will I/O error
    conn.commit()                      # stranded journal, rollback
"""

import sqlite3
import shutil
import os
import tempfile
import logging
from contextlib import contextmanager
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
DB_PATH = Path(__file__).parent / "sports_betting.db"
SCRATCH_DIR = Path(tempfile.gettempdir()) / "edge_scratch"

logging.basicConfig(level=logging.INFO, format="[db_utils] %(message)s")
log = logging.getLogger(__name__)


def _ensure_scratch():
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)


def _scratch_path() -> Path:
    return SCRATCH_DIR / "sports_betting_work.db"


def _copy_to_scratch() -> Path:
    """Copy production DB to local scratch. Returns scratch path."""
    _ensure_scratch()
    src = DB_PATH
    dst = _scratch_path()
    if not src.exists():
        raise FileNotFoundError(f"Production DB not found at {src}")
    shutil.copy2(str(src), str(dst))
    log.info(f"Copied DB to scratch: {dst} ({dst.stat().st_size} bytes)")
    return dst


def _writeback_to_mount(scratch: Path):
    """Write scratch DB back to NTFS mount using explicit byte copy."""
    dst = DB_PATH
    src = scratch
    src_size = src.stat().st_size
    with open(str(src), "rb") as fsrc, open(str(dst), "wb") as fdst:
        shutil.copyfileobj(fsrc, fdst)
    dst_size = dst.stat().st_size
    if src_size != dst_size:
        raise IOError(
            f"Writeback size mismatch — scratch={src_size}, mount={dst_size}. "
            f"Scratch copy preserved at {scratch}"
        )
    log.info(f"Writeback confirmed: {dst} ({dst_size} bytes)")


@contextmanager
def safe_write():
    """
    Context manager for any DB write operation.
    Copies DB to scratch, yields connection, commits, writes back to mount.
    On any error, rolls back and preserves scratch for inspection.

    Usage:
        with safe_write() as conn:
            conn.execute("INSERT INTO bets ...")
    """
    scratch = _copy_to_scratch()
    conn = sqlite3.connect(str(scratch))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
        log.info("Commit to scratch successful.")
    except Exception as e:
        conn.rollback()
        log.error(f"Write failed, rolled back: {e}")
        raise
    finally:
        conn.close()

    # Write back only if no exception
    _writeback_to_mount(scratch)
    log.info("safe_write complete — production DB updated.")


@contextmanager
def safe_read():
    """
    Context manager for read-only DB operations.
    Connects directly to mount in read-only mode — no copy needed.

    Usage:
        with safe_read() as conn:
            rows = conn.execute("SELECT * FROM bets").fetchall()
    """
    uri = DB_PATH.as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def get_db_path() -> Path:
    """Return the production DB path. Use for reference only — never write directly."""
    return DB_PATH


def verify_db() -> dict:
    """
    Quick health check — returns row counts for key tables.
    Safe to call at session start to confirm DB state before any operations.

    Returns:
        dict with table row counts and DB file size
    """
    result = {}
    try:
        with safe_read() as conn:
            for table in ["bets", "parlays", "parlay_legs", "horse_race_analyses", "trainer_situational_stats"]:
                try:
                    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    result[table] = count
                except sqlite3.OperationalError:
                    result[table] = "table not found"
        result["db_size_bytes"] = DB_PATH.stat().st_size
        result["status"] = "healthy"
    except Exception as e:
        result["status"] = f"error: {e}"
    return result


def get_pending_stress_test_count() -> int:
    """Returns count of STRESS_TEST bets currently in DB — useful pre-session check."""
    with safe_read() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM bets WHERE notes LIKE '%STRESS_TEST%'"
        ).fetchone()
        return row[0] if row else 0


def delete_stress_test_bets() -> int:
    """
    Deletes all STRESS_TEST tagged bets after grading is confirmed.
    Returns count of deleted rows.
    ALWAYS grade first — this is irreversible.
    """
    with safe_read() as check_conn:
        pending = check_conn.execute(
            "SELECT COUNT(*) FROM bets WHERE notes LIKE '%STRESS_TEST%' AND result = 'PENDING'"
        ).fetchone()[0]
        if pending > 0:
            raise ValueError(
                f"{pending} STRESS_TEST bets are still PENDING. Grade all bets before deleting."
            )

    with safe_write() as conn:
        cursor = conn.execute("DELETE FROM bets WHERE notes LIKE '%STRESS_TEST%'")
        deleted = cursor.rowcount
        log.info(f"Deleted {deleted} STRESS_TEST bets.")
    return deleted


if __name__ == "__main__":
    print("Running DB health check...")
    health = verify_db()
    for k, v in health.items():
        print(f"  {k}: {v}")
    stress_count = get_pending_stress_test_count()
    print(f"  stress_test_pending: {stress_count}")
