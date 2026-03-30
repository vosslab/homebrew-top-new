# Usage

## Running the script

```bash
source source_me.sh && python3 homebrew_top_new.py
```

This writes a sortable HTML report to `homebrew_top_new_report.html` in the
current working directory and prints a brief summary to stdout.

## CLI flags

| Flag | Default | Description |
| --- | --- | --- |
| `--analytics-window {30d,90d,365d}` | `30d` | Popularity ranking window |
| `--offline` | off | Use local cache only, no network requests |
| `--refresh-analytics` | off | Force refresh analytics cache even when not stale |
| `--refresh-bootstrap` | off | Force recency bootstrap (local git first, GitHub fallback) |
| `--bootstrap-max-pages N` | unlimited | Cap bootstrap commit pages scanned |

## Output

- `homebrew_top_new_report.html`: flat standalone HTML with two sortable tables:
  newest casks and top popular among newest.
- Stdout: concise completion summary with counts and timing.

## Recency sources

The script seeds first-seen timestamps in this order:

1. Local Homebrew cask git history at `brew --repository homebrew/cask`.
2. Nearby standalone `homebrew-cask` clone (for example `./homebrew-cask` or
   `../homebrew-cask`).
3. Bounded GitHub API scan as a fallback when local git history is unavailable.

See [docs/INSTALL.md](docs/INSTALL.md) for how to set up a local shallow clone
to reduce GitHub API usage.
