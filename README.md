# Ingresso IMAX poller

Watches [Ingresso.com](https://www.ingresso.com) for **A Odisseia** IMAX
sessions at **Cinépolis JK Iguatemi (São Paulo)** and sends a **Telegram**
alert — with a direct buy link — the moment new sessions appear, so you can
grab good seats within minutes of a weekly batch dropping.

Runs entirely on **GitHub Actions** (free) on a time-aware cron. State is
committed back to the repo between runs, so there's no server or database.

## How it works

```
GitHub Actions cron (every 5 min)
   └─ main.py
        ├─ cadence gate   → poll only if enough time elapsed for today (SP time)
        ├─ fetcher.py     → Ingresso JSON API → filter to A Odisseia + IMAX
        ├─ diff vs state.json  → new sessions? sold-out session reopened?
        ├─ notify.py      → Telegram message per new/reopened session
        └─ save state.json → committed back to the repo
```

It uses Ingresso's **undocumented JSON content API** (the same one the website
and community projects use) — no HTML scraping, no headless browser. The
endpoint returning per-theater sessions is:

```
GET https://api-content.ingresso.com/v0/sessions/city/{cityId}/theater/{theaterId}?partnership={partnership}
```

Each session object carries its format labels (`type: ["Normal","IMAX",...]`),
room, price, availability (`enabled` / `blockMessage`), and a direct checkout
link (`siteURL`). Verified live against the API and cross-checked with the
[`ingresso`](https://pypi.org/project/ingresso/) PyPI package and the
[HA-ingresso.com](https://github.com/hudsonbrendon/HA-ingresso.com) integration.

## Files

| File | Purpose |
|------|---------|
| `config.py` | What to watch (city/theater/film IDs, IMAX keyword) + cadence. **Edit this to watch something else.** |
| `fetcher.py` | Calls the API, filters to the watched film + format, returns normalized sessions. |
| `notify.py` | Sends Telegram messages. |
| `main.py` | Orchestrates gate → fetch → diff → notify → save. |
| `discover_ids.py` | One-time helper to find city / theater / film IDs. |
| `state.json` | Seen sessions + last-checked timestamp (committed by CI). |
| `.github/workflows/poll.yml` | The cron schedule + runner. |

## Setup

### 1. Push this repo to GitHub

```bash
cd ingresso-imax-poller
git add .
git commit -m "Initial commit: Ingresso IMAX poller"
gh repo create ingresso-imax-poller --private --source=. --push
# (or create the repo in the GitHub UI and `git push`)
```

> **Public vs private:** scheduled Actions minutes are **free & unlimited on
> public repos**. On a private repo they count against your monthly quota
> (a `*/5` cron ≈ 8.6k short runs/month; each is a few seconds). This repo
> holds no secrets in code, so public is fine — but your choice.

### 2. Create a Telegram bot and get your chat ID

1. In Telegram, message **[@BotFather](https://t.me/BotFather)** → `/newbot` →
   follow the prompts. Copy the **bot token** it gives you
   (looks like `123456789:AA...`).
2. Send any message to your new bot (so it's allowed to message you back).
3. Get your **chat ID**: open
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser and read
   `result[].message.chat.id`. (Or message **@userinfobot**.)

### 3. Add GitHub repo secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|--------|-------|
| `TELEGRAM_BOT_TOKEN` | the token from BotFather |
| `TELEGRAM_CHAT_ID` | your chat ID |

### 4. (Optional) Verify / rediscover the IDs

The IDs for A Odisseia @ JK Iguatemi are already in `config.py`. To confirm
them, or to set up a different film/cinema:

```bash
pip install -r requirements.txt
python discover_ids.py
# other targets:
python discover_ids.py --uf RJ --city "Rio de Janeiro" --partnership cinemark --theater "Village" --film "Avatar"
```

Paste the printed IDs into the `WATCH` block in `config.py`.

### 5. Turn it on

The workflow runs automatically once pushed. To test immediately:

- Repo → **Actions → Poll Ingresso IMAX sessions → Run workflow**
  (with **force** checked). The first run seeds current sessions and sends a
  one-off summary; after that you're only alerted on **new** or **reopened**
  sessions.

## Polling cadence

Brazilian cinema weeks refresh **Thursday**, and new sessions often load
Mon–Wed. The cron fires every 5 minutes; `main.py` then decides whether to
actually poll based on the **São Paulo local weekday**:

| Days (SP local) | Interval |
|-----------------|----------|
| Mon–Wed | ~20 min |
| Thu | ~15 min |
| Fri–Sun | ~60 min |

Deciding cadence in code (not purely in cron) keeps it correct across the
UTC↔SP day boundary and absorbs GitHub's scheduling jitter. Change the
intervals in `config.py` (`POLL_INTERVAL_MINUTES`).

## Alerts

**You get exactly one alert the first time a session goes on sale.** That's the
moment that matters: a freshly on-sale session has *all* seats open, so it's
your best (and often only) shot at the specific seats you want — the API only
exposes session-level availability, not seat-level, so "just on sale" is the
reliable proxy for "the good seats are still there."

- Fires for **new weekly drops**, and also for a session that first appeared in
  pre-sale/blocked and has since opened (so a drop is never missed).
- **Never** fires when a session sells out — that's not actionable.
- **No re-alerts.** `state.json` lives in the repo and records which sessions
  have already been announced, so restarts and reruns stay quiet. The first run
  seeds silently and sends one summary instead of 40+ alerts.

## Local testing

```bash
pip install -r requirements.txt

python fetcher.py                 # print current watched sessions
python main.py --dry-run          # fetch + diff + print, no Telegram, no state write
TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python notify.py   # send a test message
python main.py --force            # real run, bypass the cadence gate
```

## Watching something else

Edit `config.py` → `WATCH`:

```python
WATCH = {
    "label": "Avatar — IMAX @ ...",
    "city_id": "1",
    "theater_id": "996",
    "partnership": "cinepolis",
    "film_id": "30413",          # or set None and rely on film_title
    "film_title": "A Odisseia",
    "format_keywords": ["IMAX"], # e.g. ["IMAX"], ["3D"], ["VIP"], ["Dublado"]
}
```

Use `discover_ids.py` to find new IDs. Nothing else needs to change.

## Notes & caveats

- **Unofficial API.** No auth, but Ingresso can change field names or rate-limit
  without notice. The fetcher sends a normal browser User-Agent and small random
  jitter to be polite. If sessions stop being found, re-run `discover_ids.py` —
  the film ID changes between runs/weeks.
- **Scheduled workflows can be delayed** by GitHub under load; the elapsed-time
  gate handles this gracefully (it polls whenever enough time has passed).
- GitHub disables cron on repos with 60 days of no activity — moot here since
  the poller commits `state.json` on every change.
