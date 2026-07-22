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

# Skip this tick if a previous run is still in flight (e.g. a slow git push),
# same protection the GitHub Actions concurrency group gave us.
exec 200>"$REPO_DIR/.run_local.lock"
if ! flock -n 200; then
    echo "$(date -Is) [skip] previous run still in progress"
    exit 0
fi

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
    echo "$(date -Is) [state] committed and pushed"
else
    echo "$(date -Is) [state] no change to commit"
fi
