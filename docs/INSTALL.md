# Installation

## Prerequisites

- macOS with Homebrew installed.
- Python 3.12 (via Homebrew: `brew install python@3.12`).
- No additional pip packages required; the script uses the standard library only.

## Setup

Clone this repo and run the bootstrap script once:

```bash
git clone https://github.com/vosslab/homebrew-top-new.git
cd homebrew-top-new
source source_me.sh
```

## Optional: local Homebrew cask git clone

Setting up a local shallow clone lets the recency bootstrap run without hitting
the GitHub API. This reduces rate-limit pressure and speeds up first runs.

```bash
git clone --filter=blob:none --no-checkout https://github.com/Homebrew/homebrew-cask.git
cd homebrew-cask
git sparse-checkout init --cone
git sparse-checkout set Casks
git checkout master
```

Place the clone at `./homebrew-cask` or `../homebrew-cask` relative to the repo
root, or let Homebrew manage it at `brew --repository homebrew/cask`.
