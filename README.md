# homebrew-top-new

A local-first script that reports recent Homebrew casks ranked by popularity.
It seeds first-seen timestamps from local git history (or a GitHub fallback),
fetches Homebrew analytics, and writes a sortable HTML report.

## Quick start

```bash
source source_me.sh && python3 homebrew_top_new.py
```

Opens `homebrew_top_new_report.html` in the current directory with newest casks
and top popular among newest, sorted by install count.

## Documentation

- [docs/INSTALL.md](docs/INSTALL.md): prerequisites and optional local cask clone setup.
- [docs/USAGE.md](docs/USAGE.md): CLI flags, output files, and recency source details.
- [docs/CHANGELOG.md](docs/CHANGELOG.md): history of changes.
