#!/usr/bin/env bash
# One-shot setup for running the poller from this always-on machine.
# Run this once, from inside a clone of the repo:
#   ./scripts/bootstrap_local.sh
#
# It creates a venv, installs deps, prompts for Telegram credentials (written
# to a gitignored .env), verifies git push access, installs the */5 crontab
# entry (idempotent — safe to re-run), and does one dry smoke-test run.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
RUN_SCRIPT="$REPO_DIR/scripts/run_local.sh"

echo "== Repo: $REPO_DIR =="

# --- 1. Python venv ----------------------------------------------------------
if [[ ! -x "$REPO_DIR/.venv/bin/python3" ]]; then
    echo "== Creating venv =="
    python3 -m venv "$REPO_DIR/.venv"
fi
echo "== Installing dependencies =="
"$REPO_DIR/.venv/bin/pip" install -q -r requirements.txt

chmod +x "$RUN_SCRIPT" "$REPO_DIR/scripts/bootstrap_local.sh"

# --- 2. Telegram credentials --------------------------------------------------
if [[ -f "$REPO_DIR/.env" ]]; then
    echo "== .env already exists, leaving it alone =="
else
    echo "== Telegram credentials (from @BotFather / @userinfobot) =="
    read -r -p "TELEGRAM_BOT_TOKEN: " TG_TOKEN
    read -r -p "TELEGRAM_CHAT_ID: " TG_CHAT_ID
    if [[ -z "$TG_TOKEN" || -z "$TG_CHAT_ID" ]]; then
        echo "Both values are required; skipping .env creation. Create it manually later." >&2
    else
        printf 'TELEGRAM_BOT_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\n' "$TG_TOKEN" "$TG_CHAT_ID" > "$REPO_DIR/.env"
        chmod 600 "$REPO_DIR/.env"
        echo "Wrote .env (chmod 600)."
    fi
fi

# --- 3. Verify git push access -------------------------------------------------
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "== Checking push access to origin/$BRANCH (dry-run, no actual push) =="
if git push --dry-run origin "$BRANCH" >/dev/null 2>&1; then
    echo "Push access OK."
else
    echo "WARNING: 'git push --dry-run' failed. Cron won't be able to push state.json." >&2
    echo "Fix your git remote / SSH key / credential helper before relying on this." >&2
fi

# --- 4. Install crontab entry (idempotent) ------------------------------------
CRON_LINE="*/5 * * * * $RUN_SCRIPT >> $REPO_DIR/poll.log 2>&1"
EXISTING="$(crontab -l 2>/dev/null || true)"
if grep -qF "$RUN_SCRIPT" <<<"$EXISTING"; then
    echo "== Crontab entry already present, leaving it alone =="
else
    echo "== Installing crontab entry =="
    { printf '%s\n' "$EXISTING"; echo "$CRON_LINE"; } | grep -v '^$' | crontab -
    echo "Added: $CRON_LINE"
fi

# --- 5. Smoke test -------------------------------------------------------------
echo "== Smoke test: running scripts/run_local.sh once =="
"$RUN_SCRIPT"

echo
echo "== Done =="
echo "crontab -l           # confirm the schedule"
echo "tail -f poll.log     # watch it run"
