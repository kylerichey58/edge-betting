# Sandbox Capability Reference

Last probed: 2026-04-30 12:15 UTC
Probed by: Cowork (read-only audit)
Sandbox identity: Linux workspace mounted to `C:\Users\kyler\Documents\Sportsbetting\`

> This file documents what Cowork's sandbox environment can and cannot do.
> It exists to prevent rediscovering blockers mid-task. Update on any new
> finding — capability changes, new tooling, new restrictions.

---

## Network Egress

Probe method: Python `requests.head(url, timeout=5, allow_redirects=False)`.

| Domain | Reachable | Status / Error | Notes |
|---|---|---|---|
| https://github.com | Yes | 200 | Only domain that returned a real HTTP response |
| https://api.github.com | No | `ProxyError` | Sandbox proxy refuses the connection |
| https://api.anthropic.com | No | `SSLError: SSLCertVerificationError` | TLS interception by the proxy; cert chain rejected |
| https://api.the-odds-api.com | No | `ProxyError` | Same proxy refusal pattern |
| https://www.brisnet.com | No | `ProxyError` | Brisnet unreachable from Python |
| https://www.brisnet.com/product/download/ | No | `ProxyError` | Same as parent host |

**Implication for Brisnet workflow (#15):** Python-level `requests.get()` against Brisnet is **not** a viable path from this sandbox. Daily PP fetches and result-page scrapes must go through Chrome browser tooling, or be performed outside the sandbox (Kyle's VS Code / browser session) and the files dropped into `horse_racing_data/`.

**Implication for Anthropic / Odds API:** Any code path that needs to call those APIs (e.g. live odds polling, AI-assisted analysis) cannot run from inside this sandbox. Those calls would have to be invoked by Kyle from his own machine, or routed through Cowork's first-class connectors.

---

## Implications for In-Flight Tasks

**For #15 (Brisnet workflow integration):**
- Python `requests`-based PP fetch is NOT viable. All Brisnet I/O must go through Chrome MCP.
- Chrome's download destination must be configured to a mounted path under `Sportsbetting/` — host Downloads is invisible.
- `auto_move_downloads()` post-extract zip cleanup will fail from inside the sandbox. Decision on how to handle deferred to #15.
- Results-page scrape from Brisnet has the same constraint — Chrome MCP only.

**For #14 (comprehensive platform audit):**
- Audit is read-only, so the file-delete limitation doesn't bite. But the audit may surface code paths (in `brisnet_fetcher.py`, `results_fetcher.py`) that assume Python network access or post-action file cleanup. Flag those as "sandbox-incompatible" in the inventory.
- `.git/config` repair is a prerequisite, not part of the audit.

**For all future Cowork tasks:**
- Prefer non-mutating probes over create-and-delete probes.
- Any task that ends with "and Cowork cleans up" needs a Kyle-side cleanup step or `allow_cowork_file_delete` invocation.
- Any task that needs to call an external API from Python is blocked at this sandbox. Either run from Kyle's machine or route via Chrome MCP.

---

## Browser Tooling

Tools available (Claude in Chrome MCP). **Names enumerated only — none invoked during this audit.**

Navigation / state:
- `mcp__Claude_in_Chrome__navigate` — load a URL in the active tab
- `mcp__Claude_in_Chrome__list_connected_browsers` — enumerate connected browser instances
- `mcp__Claude_in_Chrome__select_browser` / `switch_browser` — pick which connected browser to drive
- `mcp__Claude_in_Chrome__resize_window` — resize the browser window
- `mcp__Claude_in_Chrome__tabs_create_mcp` / `tabs_close_mcp` / `tabs_context_mcp` — tab lifecycle

Reading pages:
- `mcp__Claude_in_Chrome__read_page` — read structured page content
- `mcp__Claude_in_Chrome__get_page_text` — extract page text
- `mcp__Claude_in_Chrome__find` — find elements
- `mcp__Claude_in_Chrome__read_console_messages` — pull JS console output
- `mcp__Claude_in_Chrome__read_network_requests` — inspect network panel

Acting on pages:
- `mcp__Claude_in_Chrome__form_input` — type into form fields
- `mcp__Claude_in_Chrome__file_upload` — upload a local file via a file input
- `mcp__Claude_in_Chrome__upload_image` — upload an image to a page
- `mcp__Claude_in_Chrome__javascript_tool` — execute JS in the page context
- `mcp__Claude_in_Chrome__shortcuts_list` / `shortcuts_execute` — trigger Chrome shortcuts
- `mcp__Claude_in_Chrome__browser_batch` — batch multiple browser ops
- `mcp__Claude_in_Chrome__computer` — generic computer-control fallback
- `mcp__Claude_in_Chrome__gif_creator` — record interactions

Capability assessment for the Brisnet workflow (untested, inferred from tool names):

| Capability | Available? | Notes |
|---|---|---|
| (a) Navigate to URLs | Yes | `navigate` |
| (b) Read DOM | Yes | `read_page`, `get_page_text`, `find` |
| (c) Fill forms | Yes | `form_input`, plus `javascript_tool` as fallback |
| (d) Trigger downloads to a known location | Unknown | No explicit "download" tool. Likely requires `javascript_tool` + Chrome's default download dir. Where the file lands relative to the sandbox is a critical open question — Brisnet zips today land in `C:\Users\kyler\Downloads\`, which is **not mounted** into this sandbox (see File System below). |
| (e) Persist cookies across calls | Likely | The browser is a long-lived session driven via MCP, so cookies should survive across tool calls within one Cowork session. Unverified. |
| (f) Handle MFA prompts | Partial | SMS / TOTP codes that appear in a form field can be filled via `form_input` if Kyle relays the code. Push-notification or app-confirmation flows would require Kyle to confirm out-of-band. Brisnet does not appear to enforce MFA on the kylerichey58 account today. |

---

## File System

Probe method: create `_probe_<timestamp>.tmp` via shell redirection, then attempt `rm`. Verify with directory listing.

| Path | Read | Write (create) | Write (delete) | Notes |
|---|---|---|---|---|
| `C:\Users\kyler\Documents\Sportsbetting\` | Yes | Yes | **No** | `PermissionError: Operation not permitted` on `os.remove()` and `rm` |
| `C:\Users\kyler\Documents\Sportsbetting\horse_racing_data\` | Yes | Yes | **No** | Same |
| `C:\Users\kyler\Documents\Sportsbetting\_archive\` | Yes | Yes | **No** | Same |
| `C:\Users\kyler\Documents\Sportsbetting\.git\` | Yes | Yes | **No** | Same — including index.lock and HEAD.lock cannot be deleted from sandbox |
| `C:\Users\kyler\Downloads\` | **Not mounted** | n/a | n/a | The host Downloads folder is not visible in the sandbox at all |

### The asymmetric write — most important finding

The Windows mount is **write-create-only** from inside the sandbox. Files can be written and overwritten but not deleted. This has direct consequences:

- `auto_move_downloads()` (and any workflow that ends with `os.remove(zip)`) will fail at the cleanup step if invoked from inside the sandbox. The move and extract steps would succeed; the delete-after-extract step would not.
- `del .git\HEAD.lock` and `del .git\index.lock` — the permanent rule for git lock cleanup — **cannot be performed by Cowork.** Kyle must clear those locks from VS Code or PowerShell.
- Any sandbox-internal cleanup (probe files, scratch outputs, stale caches inside the project directory) requires either Kyle's manual intervention or the `mcp__cowork__allow_cowork_file_delete` permission flow (which prompts Kyle for approval per delete batch).

### The Downloads folder is not mounted

Brisnet's PP zips currently land in `C:\Users\kyler\Downloads\` (per CLAUDE.md step 7). That path is not mounted into the sandbox. Implications for #15:

- If Cowork drives Chrome to download a Brisnet zip, the file will land in the host Downloads folder — invisible to the sandbox.
- `auto_move_downloads()` cannot scan a folder it can't see.
- Workable adaptations: (a) configure Chrome's download dir to a path under `Sportsbetting/` for Brisnet sessions, (b) have Kyle manually copy zips from Downloads to `horse_racing_data/`, or (c) drive Chrome to download directly into a sandboxed-visible path.

---

## Database

Probe method: `sqlite3.connect('file:.../sports_betting.db?mode=ro', uri=True)`, list tables, count rows, close.

- Read access: **yes**
- Write access: not tested in this audit (out of scope; would require `safe_write()` invocation)

Tables visible (all 8 expected post-reform):

| Table | Row count | Notes |
|---|---:|---|
| `bets` | 0 | Empty per April 25 reform — real tracking begins ~May 1 |
| `parlays` | 0 | Empty per reform |
| `parlay_legs` | 0 | Empty per reform |
| `betting_stats` | 0 | Empty |
| `horse_race_analyses` | 508 | Brain memory — preserved |
| `trainer_situational_stats` | 82,197 | Preserved (matches CLAUDE.md) |
| `jockey_stats` | 1,135 | Preserved (matches CLAUDE.md) |
| `sqlite_sequence` | 6 | Internal SQLite metadata |

Confirms platform state matches CLAUDE.md exactly. No drift.

`db_utils.safe_write()` importable: **yes** — `db_utils` is on the import path; `safe_write`, `safe_read`, and `verify_db` all present as attributes. Not invoked.

---

## Git

- HEAD: **7c2223d** (matches expected post-reform commit)
- Remote URL: `https://github.com/kylerichey58/edge-betting.git`
- Remote URL safe: **yes** — no embedded `username:token@` credentials
- Branch: `main`

### Git CLI is currently broken

`git status`, `git remote -v`, `git log`, `git branch -vv` all fail with:

```
fatal: bad config line 20 in file .git/config
```

Cause: `.git/config` ends with a 56-byte block of null bytes (`\x00`) appended after the last valid line (`skippedCherryPicks = false`). The 19 lines above it parse correctly. Likely an artifact of an interrupted write during the security-incident cleanup or the post-push state.

Workaround used in this audit: read git state directly from `.git/HEAD`, `.git/refs/heads/main`, `.git/logs/HEAD`, and parse `.git/config` up to the first null byte. This works for read-only inspection but is not a substitute for the git CLI for any real operation.

Resolution required from Kyle (VS Code only — never from Cowork per permanent rule):
1. Open `.git\config` in VS Code
2. Delete everything after the final `\n` on line 19 (`	skippedCherryPicks = false`)
3. Save; re-run `git status` to confirm

Alternative one-liner from VS Code terminal: `git remote set-url origin https://github.com/kylerichey58/edge-betting.git` rewrites the file cleanly.

### Read-only commands

Out of scope until `.git/config` is repaired. Will retest after the fix.

### Write commands

Out of scope per permanent rule (Cowork never pushes). VS Code handles all git writes.

### Last 5 commits (from `.git/logs/HEAD`)

```
7c2223d refactor: April 25 platform reform - wipe build-phase data, remove exotic handling, introduce PHILOSOPHY.md
ab89481 fix: scan *k.zip (PP Single File) instead of *n.zip in Downloads auto-move
223b6e0 docs: refresh CLAUDE.md to Apr 13 baseline + add CTX→CT gotcha to PIPELINE_API.md
a3b17de ARM2026 April 12 stress test results + notes format fix + exotic delimiter bug documented
e27e734 Lock Brisnet download workflow + CTX→CT fix + exotic P&L cleanup order rule
```

---

## Known Limitations

1. **Network egress is heavily restricted.** Only `github.com` reachable from Python. `api.github.com`, `api.anthropic.com`, `api.the-odds-api.com`, and `brisnet.com` are blocked at the proxy. Any workflow that depends on Python `requests` calls to those hosts must run outside the sandbox.
2. **Cannot delete files on the Windows mount.** Symptom: `PermissionError: Operation not permitted`. Affects `Sportsbetting/` and every subdirectory including `.git/`. Workarounds: Kyle deletes manually, or Cowork uses `mcp__cowork__allow_cowork_file_delete` (prompts Kyle each batch).
3. **`.git/HEAD.lock` and `.git/index.lock` cannot be cleared from Cowork.** Per limitation #2. The permanent rule "del `.git\HEAD.lock` and `.git\index.lock` between stages" is a Kyle-only operation.
4. **`C:\Users\kyler\Downloads\` is not mounted.** Brisnet's default download path is invisible to the sandbox. Workflow #15 must route downloads into a mounted path.
5. **Git CLI fully blocked until `.git/config` is repaired.** Filesystem-level reads work as a partial substitute for read-only inspection.
6. **Browser-tool capabilities have not been exercised.** Capability claims in the Browser Tooling section are inferred from tool names. Verification is part of #15.
7. **No connector tooling probed.** This audit covered Python, sqlite, git, file system, and the Chrome MCP enumeration. MCP registry / connectors (Slack, Linear, Asana, etc.) were out of scope and may carry their own capabilities.
8. **Bash file reads can lag or truncate after Edit operations.** Symptom observed 2026-04-30: after editing `CLAUDE.md` (240 lines, ~12 KB), bash `cat`, `wc -c`, and Python `open().read()` from inside the sandbox all returned a truncated 11,735-byte view ending mid-word, while the Read tool and PowerShell `Get-Content` (Kyle, from outside the sandbox) both showed the file intact. Implication: do not use bash to verify writes on this mount. Use the Read tool or ask Kyle to confirm via VS Code / PowerShell. Do not "repair" a file based on bash output alone — the apparent damage may not exist on disk.
9. **Edit-tool modifications to existing files in `Sportsbetting/` are invisible to the bash sandbox.**
   Deeper characterization of the same root cause as Limitation #8 — the issue is not truncation, it is caching of the pre-edit file content.

   **Symptom (observed 2026-05-04):** after extending `horse_racing_grader.py` from 729 → 1043 lines via successive Edit tool calls, bash's view of the file remained a stale pre-edit snapshot capped at 715 lines and ending mid-word. The Read tool and host-side stat both confirmed the host filesystem had the full edited content; bash served stale virtiofs cache regardless of `sync`, `echo 3 > /proc/sys/vm/drop_caches`, or opening with `O_DIRECT`.

   **What works:** Write-tool creation of brand-new files syncs to bash immediately. Bash-side writes (`cp`, shell redirection, Python `open(..., 'w')`) propagate back to the host AND invalidate bash's own cache for the destination path, so bash sees its own writes correctly.

   **What fails:** Edit-tool partial modifications to existing files are never picked up by bash. Host writes do not invalidate the bash-side cache.

   **Workaround pattern — full overwrite (verified 2026-05-04 in Prompt 2.5):** for non-trivial edits to an existing file, write the desired final content to a brand-new staging file via the Write tool (e.g. `target_cleaned.py`), then `cp staging_file target_file` via bash. The bash-driven copy propagates to the host AND refreshes bash's view of the destination. Used this pattern to apply the grader cleanup (1043 → 838 lines) cleanly with all 28 self-test assertions passing on the post-cp file.

   **Workaround pattern — extract new logic (preferred when applicable):** instead of inline-editing the existing file, extract new logic into a brand-new module (which syncs cleanly), then re-export from the original module via `from new_module import …`. Used this pattern in Prompt 2 to ship `horse_profile_logic.py`.

   **Workaround pattern — bash heredoc → /tmp → cp (default for parser build, validated 2026-05-05/06 in Phases 4-7):** for any non-trivial edit to a pre-existing file, the highest-reliability pattern is to write the desired content to `/tmp` via a heredoc and `cp` it to the target — both in the same `bash` invocation:

   ```bash
   cat > /tmp/file <<'EOF'
   ...new content...
   EOF
   cp /tmp/file /sessions/.../mnt/Sportsbetting/file
   ```

   `/tmp` is pure Linux (no virtiofs translation) and the heredoc-then-cp happens inside one bash session, so there's no tool-boundary cache invalidation between the write and the copy. Used throughout the parser build (Phases 4 through 7B) on `horse_racing_pdf_parser_v2.py` (which grew from ~400 lines to ~1300 lines across many edits) without a single corruption recurrence. **The Edit tool also exhibits the cache issue, not just the Write tool** — observed in Phase 2 when an Edit-tool report-success was followed by a truncated/corrupted on-disk file. New files (paths that don't exist yet) generally Write cleanly, but pre-existing files should default to the heredoc-cp pattern.

   **When this matters:** any task that requires editing an existing file in `Sportsbetting/` and then verifying the change via bash (test runs, import sanity checks). Refactors, in-place schema migrations on existing modules, and any code changes more substantive than a one-line Edit are affected. Does not affect new-file workflows.

   **Alternative workaround:** close and reopen the Cowork session to flush the entire virtiofs cache — heavier-weight, loses session context, only worth it if many existing files need updating at once.

---

## Open Questions

- Where does a Chrome-driven download physically land? If we drive a Brisnet download via the Chrome MCP, does the file go to host Downloads (invisible to sandbox) or somewhere we can configure? Needs probe in #15.
- Does the Chrome MCP persist cookies across separate Cowork sessions, or only within one session? If only within, Brisnet auth has to be redone each session.
- Can the sandbox's network proxy be configured, or is the egress allowlist fixed? If fixed, the Brisnet/Odds-API/Anthropic blockers are permanent for Python and force everything onto Chrome.
- Is the file-delete restriction a property of the Cowork mount specifically, or of the underlying Linux→NTFS bridge? If the former, Anthropic may be able to relax it; if the latter, it is structural.
- Does `mcp__cowork__allow_cowork_file_delete` work for files inside `.git/`, or only inside the project root? Untested.

---

## Audit Trail

This audit created five probe files in `Sportsbetting/`, `Sportsbetting/horse_racing_data/`, `Sportsbetting/_archive/`, and `Sportsbetting/.git/`. Cowork attempted to delete them and failed (see Limitation #2). They remain on disk pending Kyle's manual cleanup or `allow_cowork_file_delete` approval:

- `_probe_test.tmp` (root)
- `_probe_1777551336412415244.tmp` (root)
- `horse_racing_data/_probe_1777551336432259846.tmp`
- `_archive/_probe_1777551336447198302.tmp`
- `.git/_probe_1777551336461712220.tmp`

This residue is itself a finding worth keeping in mind for future audits — probe before you commit to a probe-file pattern, since the cleanup is not free.
