"""Orchestrate: decide whether to poll -> fetch -> diff -> notify -> save state.

Run by GitHub Actions every 5 minutes. The cadence gate (based on São Paulo
local weekday) means most invocations exit early without touching the API.

Exit codes: always 0 on normal operation (including "skipped" and "no
changes") so the workflow's commit step runs cleanly. Non-zero only on an
unexpected error.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import config
import fetcher
import notify

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except ImportError:  # pragma: no cover
    ZoneInfo = None


def _now_utc():
    return datetime.now(timezone.utc)


def _local_now():
    if ZoneInfo is not None:
        try:
            return _now_utc().astimezone(ZoneInfo(config.LOCAL_TZ))
        except Exception:
            pass
    # Fallback: fixed UTC-3 (São Paulo has no DST since 2019).
    from datetime import timedelta

    return _now_utc().astimezone(timezone(timedelta(hours=-3)))


def _in_heartbeat_quiet_hours():
    """True if the current São Paulo hour falls in the heartbeat quiet window."""
    start = getattr(config, "HEARTBEAT_QUIET_START_HOUR", None)
    end = getattr(config, "HEARTBEAT_QUIET_END_HOUR", None)
    if start is None or end is None:
        return False
    hour = _local_now().hour
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # window wraps past midnight


def _elapsed_seconds(iso_ts):
    """Seconds since an ISO timestamp; a huge number if missing/unparseable."""
    if not iso_ts:
        return float("inf")
    try:
        dt = datetime.fromisoformat(iso_ts)
    except ValueError:
        return float("inf")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (_now_utc() - dt).total_seconds()


def load_state():
    path = config.STATE_FILE
    if not os.path.exists(path):
        return {"last_checked": None, "last_heartbeat": None, "sessions": {}}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (ValueError, OSError):
        return {"last_checked": None, "last_heartbeat": None, "sessions": {}}
    data.setdefault("last_checked", None)
    data.setdefault("last_heartbeat", None)
    data.setdefault("sessions", {})
    return data


def save_state(state):
    with open(config.STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")


def should_poll(state, force=False):
    """Cadence gate. Returns (bool, reason)."""
    if force:
        return True, "forced"
    last = state.get("last_checked")
    if not last:
        return True, "first run (no previous check)"
    try:
        last_dt = datetime.fromisoformat(last)
    except ValueError:
        return True, "unparseable last_checked"
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)
    elapsed = (_now_utc() - last_dt).total_seconds()

    weekday = _local_now().weekday()
    interval_min = config.POLL_INTERVAL_MINUTES.get(weekday, 20)
    threshold = interval_min * 60 - config.POLL_TOLERANCE_SECONDS
    if elapsed >= threshold:
        return True, "%.0fs since last check (>= %dmin cadence)" % (elapsed, interval_min)
    return False, "%.0fs since last check (< %dmin cadence)" % (elapsed, interval_min)


def sessions_to_alert(current, stored_sessions):
    """Sessions to alert on: on sale now, and not previously announced.

    Fires the first time a session can actually be bought — whether it's a
    brand-new session id, or one seen earlier while still in pre-sale / blocked
    that has since opened. Never fires on a session selling out.
    """
    out = []
    for s in current:
        if not s["available"]:
            continue
        prev = stored_sessions.get(s["session_id"])
        if prev is None or not prev.get("alerted", False):
            out.append(s)
    return out


def build_sessions_state(current, stored_sessions, alerted_ids, first_run):
    """Compact per-session state to persist, carrying the 'alerted' flag.

    On first run, sessions already on sale are seeded as alerted (so we don't
    spam an alert for every existing session); sold-out ones stay un-alerted so
    they'll fire if/when they open.
    """
    out = {}
    for s in current:
        sid = s["session_id"]
        if first_run:
            alerted = s["available"]
        else:
            prev = stored_sessions.get(sid)
            was_alerted = prev.get("alerted", False) if prev else False
            alerted = was_alerted or sid in alerted_ids
        out[sid] = {
            "date": s["date"],
            "time": s["time"],
            "room": s["room"],
            "available": s["available"],
            "alerted": alerted,
        }
    return out


def run(force=False, dry_run=False):
    state = load_state()

    do_poll, reason = should_poll(state, force=force)
    print("[gate] poll=%s (%s); SP local %s" % (
        do_poll, reason, _local_now().strftime("%a %Y-%m-%d %H:%M %Z")))
    if not do_poll:
        return 0  # not time yet; leave state untouched

    sessions = fetcher.fetch_watched_sessions()
    print("[fetch] %d matching session(s) for '%s'" % (
        len(sessions), config.WATCH["label"]))

    stored = state.get("sessions", {})
    first_run = not stored
    to_alert = [] if first_run else sessions_to_alert(sessions, stored)

    alerts_sent = False
    if first_run:
        on_sale = sum(1 for s in sessions if s["available"])
        print("[diff] first run -> seeding %d session(s) (%d on sale), no alerts"
              % (len(sessions), on_sale))
        if config.SEND_STARTUP_SUMMARY and not dry_run:
            notify.notify_startup_summary(sessions)
        # The summary is itself a proof-of-life; start the heartbeat clock now.
        state["last_heartbeat"] = _now_utc().isoformat()
    else:
        print("[diff] %d session(s) newly on sale" % len(to_alert))
        for s in to_alert:
            print("   ON SALE  %s %s %s" % (s["date"], s["time"], s["room"]))
        if to_alert and not dry_run:
            sent = notify.notify_new_sessions(to_alert)
            alerts_sent = True
            print("[notify] sent %d Telegram message(s)" % sent)

        # Heartbeat: hourly proof-of-life ping. Skips (but resets the clock) if a
        # real alert already went out this run.
        if config.SEND_HEARTBEAT and _in_heartbeat_quiet_hours() and not force:
            # Sleep window: don't ping, and don't reset the clock — that way the
            # first heartbeat right after the quiet window fires promptly.
            print("[heartbeat] quiet hours (22:00-08:00 SP) -> suppressed")
        elif config.SEND_HEARTBEAT:
            hb_elapsed = _elapsed_seconds(state.get("last_heartbeat"))
            hb_threshold = (config.HEARTBEAT_INTERVAL_MINUTES * 60
                            - config.POLL_TOLERANCE_SECONDS)
            if force or hb_elapsed >= hb_threshold:
                if alerts_sent:
                    print("[heartbeat] due, but alert already sent -> skip, reset clock")
                elif not dry_run:
                    notify.notify_heartbeat(sessions)
                    print("[heartbeat] sent proof-of-life ping")
                else:
                    print("[heartbeat] dry-run: would send ping")
                state["last_heartbeat"] = _now_utc().isoformat()

    # Persist snapshot + timestamp (even when nothing changed, to advance the
    # cadence clock).
    alerted_ids = {s["session_id"] for s in to_alert}
    state["sessions"] = build_sessions_state(sessions, stored, alerted_ids, first_run)
    state["last_checked"] = _now_utc().isoformat()
    if not dry_run:
        save_state(state)
        print("[state] saved (%d sessions tracked)" % len(state["sessions"]))
    else:
        print("[state] dry-run: not saved")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Ingresso IMAX session poller")
    parser.add_argument(
        "--force", action="store_true",
        help="ignore the cadence gate and poll now",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="fetch + diff + print, but do not send Telegram or write state",
    )
    args = parser.parse_args()
    # A manual workflow_dispatch run sets FORCE_POLL=1 to bypass the gate.
    force = args.force or os.environ.get("FORCE_POLL", "").lower() in ("1", "true", "yes")
    try:
        return run(force=force, dry_run=args.dry_run)
    except notify.TelegramConfigError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
