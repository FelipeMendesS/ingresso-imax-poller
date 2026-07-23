"""Configuration for the Ingresso.com IMAX session poller.

All the IDs below were discovered once with ``discover_ids.py`` and hardcoded
here. To watch a different film / cinema / city, run ``discover_ids.py`` again
and edit the WATCH block. The rest of the pipeline is driven entirely by this
file, so no other code needs to change.
"""

# --- What to watch -----------------------------------------------------------
# Discovered via discover_ids.py (verified against the live API 2026-07-17):
#   São Paulo (capital) ...... city id 1
#   Cinépolis JK Iguatemi .... theater id 996  (partnership "cinepolis")
#   A Odisseia ............... film/event id 30413
WATCH = {
    "label": "A Odisseia — IMAX @ Cinépolis JK Iguatemi",
    "city_id": "1",
    "theater_id": "996",
    "partnership": "cinepolis",
    # Match the film by its event id (most reliable). If you'd rather match by
    # title (e.g. the id changes between weeks), set film_id to None and the
    # fetcher falls back to a case-insensitive substring match on film_title.
    "film_id": "30413",
    "film_title": "A Odisseia",
    # A session qualifies when ANY of these keywords appears (case-insensitive)
    # in its format labels (the session "type" array) or in the room name.
    "format_keywords": ["IMAX"],
}

# --- Ingresso.com JSON API ---------------------------------------------------
# Undocumented but stable content API used by ingresso.com itself and by
# community projects (PyPI `ingresso`, HA-ingresso.com). No auth required.
API_BASE = "https://api-content.ingresso.com/v0"

# Sessions grouped by date -> movies -> rooms -> sessions, for one theater.
SESSIONS_BY_THEATER_URL = (
    API_BASE + "/sessions/city/{city_id}/theater/{theater_id}?partnership={partnership}"
)
# Discovery helpers (used by discover_ids.py).
CITIES_BY_STATE_URL = API_BASE + "/states/{uf}"
THEATERS_BY_CITY_URL = API_BASE + "/theaters/city/{city_id}?partnership={partnership}"

# A normal-looking desktop browser UA — the API rejects some default UAs.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HTTP_TIMEOUT_SECONDS = 30
# Small random delay before the request so runs don't hit the API at the exact
# same offset every time.
REQUEST_JITTER_SECONDS = (0.5, 3.0)

# --- Polling cadence ---------------------------------------------------------
# Brazilian cinema weeks refresh Thursday; new sessions often load Mon-Wed.
# A local cron job fires every 5 minutes (see scripts/run_local.sh); main.py
# then decides whether enough time has elapsed to actually poll, based on the
# *São Paulo local* weekday. This keeps the cadence correct regardless of
# UTC/timezone day boundaries.
#
# Python weekday(): Monday=0 ... Sunday=6.
POLL_INTERVAL_MINUTES = {
    0: 20,   # Monday
    1: 20,   # Tuesday
    2: 20,   # Wednesday
    3: 5,    # Thursday  (new week drops — poll as fast as the 5-min cron allows)
    4: 60,   # Friday
    5: 60,   # Saturday
    6: 60,   # Sunday
}
# Timezone the cadence is reckoned in.
LOCAL_TZ = "America/Sao_Paulo"
# A poll fires when (now - last_checked) >= interval - tolerance. The tolerance
# absorbs the 5-minute cron granularity and GitHub's scheduling jitter so we
# reliably hit the target cadence instead of drifting to the next tick.
POLL_TOLERANCE_SECONDS = 120

# --- State -------------------------------------------------------------------
STATE_FILE = "state.json"
# On the very first run (empty state) we seed all currently-listed sessions as
# "seen" and send ONE summary instead of spamming an alert per existing session.
SEND_STARTUP_SUMMARY = True

# --- Heartbeat ---------------------------------------------------------------
# Proof-of-life: send a Telegram ping on a fixed interval even when nothing
# changed, so that if the pings ever stop you know the bot died (silence = alarm).
# It piggybacks on the regular poll (which fires at least hourly on every day),
# so it costs no extra API calls. If a real "on sale" alert already went out in
# the same run, the heartbeat is skipped for that hour (the alert proves life).
SEND_HEARTBEAT = True
HEARTBEAT_INTERVAL_MINUTES = 60
# Quiet hours (São Paulo local, LOCAL_TZ): no heartbeat between these hours so
# it doesn't ping you while you sleep. Window wraps past midnight when start >
# end. 23 -> 8 means silent from 11 PM to 8 AM: nothing fires once the local
# hour hits 23, so the latest a heartbeat can arrive is 10:59 PM. (The gate is
# hour-granular, so it can't allow 11:00 but block 11:57 — hence the cutoff is
# the top of the 11 PM hour.) Real on-sale alerts are NOT affected — those
# always fire. Set HEARTBEAT_QUIET_START_HOUR = None to disable.
HEARTBEAT_QUIET_START_HOUR = 23
HEARTBEAT_QUIET_END_HOUR = 8
