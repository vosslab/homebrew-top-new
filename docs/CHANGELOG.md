## 2026-03-29

### Additions and New Features
- Added `docs/USAGE.md` with CLI flags table, output description, and recency source details.
- Added `docs/INSTALL.md` with prerequisites, setup steps, and optional local cask clone instructions.

### Fixes and Maintenance
- Rewrote `README.md` to be short: one-paragraph description, quick start with correct
  `source source_me.sh && python3` command, and links to docs.
- Removed hardcoded interpreter path from `README.md` quick start.

## 2026-03-01

### Additions and New Features
- Added `homebrew_top_new.py`, an executable report script that fetches newest Homebrew casks, prints the newest 100 with descriptions, and prints the top 25 most-installed within the newest 250 based on 30-day analytics.
- Replaced `homebrew_top_new.py` with a local-first recency index implementation that keeps a persistent state file (`homebrew_top_new_state.json`), supports bounded GitHub bootstrap for missing recency data, and prints multi-window analytics (`30d`, `90d`, `365d`) including rank/percent for the selected window.
- Added local git recency bootstrap support (`brew --repository homebrew/cask`) so the script can seed first-seen timestamps from local cask history before any GitHub API fallback.
- Added focused tests in `tests/test_homebrew_top_new.py` for cask payload parsing, analytics schema normalization (`items` and `formulae` shapes), state diff updates, deterministic recency ordering, and cache freshness.
- Added focused tests for local git bootstrap parsing and GitHub bootstrap failure handling (rate-limit warning path).
- Added a flat standalone HTML report output (`homebrew_top_new_report.html`) with client-side sortable tables for newest casks and top popular among newest.

### Behavior or Interface Changes
- `homebrew_top_new.py` now prioritizes local cache/state and uses bounded network fallback; CLI controls were intentionally kept small (`--analytics-window`, `--offline`, `--refresh-analytics`, `--refresh-bootstrap`, `--bootstrap-max-pages`) instead of exposing every internal tuning parameter.
- `homebrew_top_new.py` now emits a concise CLI completion summary and writes full results to HTML instead of dumping full tabular content to stdout.

### Fixes and Maintenance
- Replaced equal-width `table-layout:fixed` in HTML report with `<colgroup>` percentage widths tuned per table, giving Description the most space and keeping numeric columns compact.
- Added clickable homepage links on the Name column in both HTML report tables; names link to the project homepage from the Homebrew cask metadata when available.
- Removed Rank and Percent columns from both HTML report tables; install counts are sufficient. Removed unused `format_percent`, `percent_value_or_default`, and `rank_value_or_default` helper functions. Rebalanced colgroup widths to give Description more space.
- Updated `README.md` with direct script usage and concise optional flags.
- Fixed state/cache path handling to use a writable fallback directory when Homebrew API cache dir is read-only in sandboxed environments.
- Fixed bootstrap failure behavior so GitHub rate-limit or request errors no longer crash the script; failures are reported as warnings and output still renders.
- Fixed newest-list ranking to exclude unknown first-seen tokens instead of padding with epoch-dated entries, preventing old casks from appearing as "newest" when recency index coverage is partial.
- Improved local git bootstrap discovery to detect nearby standalone `homebrew-cask` clones (for example `./homebrew-cask` or `../homebrew-cask`) and added explicit warning text when local git bootstrap is unavailable.

### Removals and Deprecations
- None.

### Decisions and Failures
- Kept network access in standard-library `urllib` code paths to avoid introducing a new third-party runtime dependency for this repository.
- Attempted to run repo hygiene pytest with `REPO_HYGIENE_SCOPE=changed`, but untracked-file collection and sandboxed `.git/index.lock` restrictions prevented the new file from entering tracked-file test parametrization.
- Chose local git history as the first recency bootstrap source to reduce GitHub API pressure and improve resilience when unauthenticated rate limits are tight.

### Developer Tests and Notes
- Ran `source source_me.sh && /opt/homebrew/opt/python@3.12/bin/python3.12 tests/fix_whitespace.py -i homebrew_top_new.py`.
- Ran `source source_me.sh && /opt/homebrew/opt/python@3.12/bin/python3.12 -m pyflakes homebrew_top_new.py`.
- Ran `source source_me.sh && /opt/homebrew/opt/python@3.12/bin/python3.12 -m py_compile homebrew_top_new.py`.
- Ran `source source_me.sh && /opt/homebrew/opt/python@3.12/bin/python3.12 tests/check_ascii_compliance.py -i homebrew_top_new.py`.
- Verified tab-only indentation in `homebrew_top_new.py` with an `awk` indentation scan.
- Verified shebang and executable bit for `homebrew_top_new.py` via `head -n 1` and `test -x`.
- Ran `source source_me.sh && /opt/homebrew/opt/python@3.12/bin/python3.12 -m pytest tests/test_homebrew_top_new.py`.
- Ran `source source_me.sh && export PYTHONPYCACHEPREFIX=/Users/vosslab/nsh/homebrew-top-new/.pycache && /opt/homebrew/opt/python@3.12/bin/python3.12 -m py_compile homebrew_top_new.py tests/test_homebrew_top_new.py`.
- Ran `source source_me.sh && export PYTHONPYCACHEPREFIX=/Users/vosslab/nsh/homebrew-top-new/.pycache && /opt/homebrew/opt/python@3.12/bin/python3.12 -m pyflakes homebrew_top_new.py tests/test_homebrew_top_new.py`.
- Ran `source source_me.sh && export PYTHONPYCACHEPREFIX=/Users/vosslab/nsh/homebrew-top-new/.pycache && /opt/homebrew/opt/python@3.12/bin/python3.12 -m pytest tests/test_homebrew_top_new.py`.
- Ran `source source_me.sh && export PYTHONPYCACHEPREFIX=/Users/vosslab/nsh/homebrew-top-new/.pycache && /opt/homebrew/opt/python@3.12/bin/python3.12 homebrew_top_new.py --offline`.
- Ran `source source_me.sh && export PYTHONPYCACHEPREFIX=/Users/vosslab/nsh/homebrew-top-new/.pycache && /opt/homebrew/opt/python@3.12/bin/python3.12 homebrew_top_new.py --bootstrap-max-pages 1`.
- Added regression test coverage for unknown-token exclusion in newest ranking.
- Added renderer test coverage for sortable HTML table output and HTML escaping behavior.
- Added repo-path discovery test coverage for local git bootstrap when a nearby standalone clone exists.
