# homebrew-top-new

Local-first script to list recent Homebrew casks and popularity.

## Usage

Run:

```bash
source source_me.sh && /opt/homebrew/opt/python@3.12/bin/python3.12 homebrew_top_new.py
```

By default, this writes a flat sortable HTML report to
`homebrew_top_new_report.html` in the current working directory.

Optional flags:

- `--analytics-window {30d,90d,365d}`: choose popularity ranking window (default `30d`).
- `--offline`: use local cache only (no network requests).
- `--refresh-analytics`: refresh analytics cache even when not stale.
- `--refresh-bootstrap`: force recency bootstrap (local git first, GitHub fallback).
- `--bootstrap-max-pages N`: cap bootstrap commit pages scanned.

## Recency Sources

- Preferred: local Homebrew cask git history at `brew --repository homebrew/cask`.
- Fallback: bounded GitHub API scan when local git history is unavailable.

To enable local-git recency with minimal disk usage:

```bash
git clone --filter=blob:none --no-checkout https://github.com/Homebrew/homebrew-cask.git
cd homebrew-cask
git sparse-checkout init --cone
git sparse-checkout set Casks
git checkout master
```
