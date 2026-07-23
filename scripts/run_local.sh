#!/usr/bin/env bash
# Cron entrypoint for running the poller from an always-on local machine
# instead of GitHub Actions. GitHub's scheduled cron is best-effort and can be
# delayed or dropped for many minutes under load, which is why the hourly
# heartbeat sometimes arrived 70+ minutes apart. A real cron on a machine you
# control fires on time, every time.
#
# Mirrors the commit-and-push step that used to live in
# .github/workflows/poll.yml, so state.json history keeps accumulating the
# same way it did on GitHub Actions.
#
# Install (see README.md "Running on your own machine" for the full walkthrough):
#   crontab -e
#   */5 * * * * /path/to/ingresso-imax-poller/scripts/run_local.sh >> /path/to/ingresso-imax-poller/poll.log 2>&1

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# Portable ISO-8601 timestamp. BSD/macOS `date` has no `-Is`, so build it
# explicitly; this format works identically on macOS and GNU/Linux.
ts() { date +%Y-%m-%dT%H:%M:%S%z; }

# Skip this tick if a previous run is still in flight (e.g. a slow git push),
# same protection the GitHub Actions concurrency group gave us. Uses an atomic
# `mkdir` lock rather than `flock`, which isn't available on stock macOS.
LOCK_DIR="$REPO_DIR/.run_local.lock.d"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    # `mkdir` locks don't auto-release on crash like `flock` does. If the lock
    # is stale (left by a run that died more than 15 minutes ago), remove it and
    # retry; otherwise a previous run really is still in flight, so skip.
    if [[ -n "$(find "$LOCK_DIR" -maxdepth 0 -mmin +15 2>/dev/null)" ]]; then
        rmdir "$LOCK_DIR" 2>/dev/null || true
    fi
    if ! mkdir "$LOCK_DIR" 2>/dev/null; then
        echo "$(ts) [skip] previous run still in progress"
        exit 0
    fi
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

if [[ -x "$REPO_DIR/.venv/bin/python3" ]]; then
    PYTHON="$REPO_DIR/.venv/bin/python3"
else
    PYTHON="python3"
fi

# cron runs with a near-empty environment, so TELEGRAM_BOT_TOKEN /
# TELEGRAM_CHAT_ID won't be set unless loaded explicitly. Put them in a
# gitignored .env file (KEY=value per line) next to this script's repo root.
if [[ -f "$REPO_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_DIR/.env"
    set +a
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"

# Pick up any state committed from elsewhere (e.g. a manual workflow_dispatch
# run on GitHub) before polling, so we diff against the latest known state.
git pull --rebase --autostash origin "$BRANCH" >/dev/null 2>&1 || true

"$PYTHON" main.py

if [[ -n "$(git status --porcelain state.json)" ]]; then
    git add state.json
    git commit -m "chore: update session state [skip ci]" >/dev/null
    git pull --rebase --autostash origin "$BRANCH" || true
    git push origin "$BRANCH"
    echo "$(ts) [state] committed and pushed"
else
    echo "$(ts) [state] no change to commit"
fi
