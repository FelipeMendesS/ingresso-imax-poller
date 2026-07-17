"""Fetch and normalize Ingresso.com sessions for the watched film/format.

Uses the undocumented JSON content API (no scraping, no headless browser).
Endpoint shape verified against the live API and the reference projects
(PyPI `ingresso`, hudsonbrendon/HA-ingresso.com).

The sessions-by-theater endpoint returns:

    [ { "date": "2026-07-17", "movies": [
          { "id": "30413", "title": "A Odisseia", "siteURL": "...",
            "rooms": [ { "name": "Sala 1 - IMAX",
                         "sessions": [ { "id": "85403389", "price": 88.91,
                                         "room": "Sala 1 - IMAX", "time": "18:00",
                                         "type": ["Normal","IMAX","Legendado"],
                                         "date": {"localDate": "...", "hour": "18:00"},
                                         "siteURL": "https://checkout.ingresso.com/?sessionId=...",
                                         "enabled": true, "blockMessage": "" } ] } ] } ] } ]
"""

import random
import time

import requests

import config


def _http_get_json(url):
    """GET a URL with a browser UA + small random jitter; return parsed JSON."""
    lo, hi = config.REQUEST_JITTER_SECONDS
    time.sleep(random.uniform(lo, hi))
    resp = requests.get(
        url,
        headers={
            "User-Agent": config.USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        },
        timeout=config.HTTP_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.json()


def _matches_film(movie, watch):
    """True if this movie object is the film we're watching."""
    film_id = watch.get("film_id")
    if film_id:
        return str(movie.get("id")) == str(film_id)
    title = (watch.get("film_title") or "").strip().lower()
    return bool(title) and title in (movie.get("title") or "").strip().lower()


def _matches_format(session, watch):
    """True if the session's format labels or room name contain a keyword."""
    keywords = [k.lower() for k in watch.get("format_keywords", [])]
    if not keywords:
        return True
    # `type` is a list of plain strings, e.g. ["Normal", "IMAX", "Legendado"].
    labels = [str(t).lower() for t in (session.get("type") or [])]
    # `types` is a list of objects with name/alias; fold those in too.
    for t in session.get("types") or []:
        if isinstance(t, dict):
            labels.append(str(t.get("name", "")).lower())
            labels.append(str(t.get("alias", "")).lower())
    haystack = " ".join(labels + [str(session.get("room", "")).lower()])
    return any(k in haystack for k in keywords)


def _format_price(price):
    if price is None:
        return None
    try:
        return "R$ " + ("%.2f" % float(price)).replace(".", ",")
    except (TypeError, ValueError):
        return str(price)


def _is_available(session):
    """Whether tickets can currently be bought for this session.

    Ingresso marks unavailable sessions with enabled=false and/or a
    blockMessage. Used for the "sold-out session reopened" alert.
    """
    if session.get("enabled") is False:
        return False
    if (session.get("blockMessage") or "").strip():
        return False
    return True


def normalize_sessions(raw, watch):
    """Turn the raw API payload into a flat list of watched sessions.

    Returns a list of dicts, one per matching session:
        {session_id, date, time, room, format, price, price_tier,
         buy_url, available}
    Deduplicated by session_id (a session can appear under multiple format
    buckets in the same day).
    """
    out = {}
    for day in raw or []:
        day_date = day.get("date")  # "YYYY-MM-DD"
        for movie in day.get("movies") or []:
            if not _matches_film(movie, watch):
                continue
            for room in movie.get("rooms") or []:
                for session in room.get("sessions") or []:
                    if not _matches_format(session, watch):
                        continue
                    sid = str(session.get("id"))
                    if not sid or sid == "None":
                        continue
                    sdate = session.get("date") or {}
                    fmt = [
                        t for t in (session.get("type") or [])
                        if str(t).lower() not in ("normal",)
                    ] or session.get("type") or []
                    out[sid] = {
                        "session_id": sid,
                        "date": sdate.get("localDate", "")[:10] or day_date,
                        "time": session.get("time") or sdate.get("hour"),
                        "day_of_week": sdate.get("dayOfWeek"),
                        "room": session.get("room") or room.get("name"),
                        "format": ", ".join(str(f) for f in fmt),
                        "price": session.get("price"),
                        "price_tier": _format_price(session.get("price")),
                        "buy_url": session.get("siteURL"),
                        "available": _is_available(session),
                    }
    # Stable ordering: by date then time.
    return sorted(out.values(), key=lambda s: (s["date"] or "", s["time"] or ""))


def fetch_watched_sessions(watch=None):
    """Fetch + filter sessions for the watched film & format."""
    watch = watch or config.WATCH
    url = config.SESSIONS_BY_THEATER_URL.format(
        city_id=watch["city_id"],
        theater_id=watch["theater_id"],
        partnership=watch["partnership"],
    )
    raw = _http_get_json(url)
    return normalize_sessions(raw, watch)


if __name__ == "__main__":
    # Quick manual check: print current watched sessions.
    sessions = fetch_watched_sessions()
    print("Found %d matching session(s):\n" % len(sessions))
    for s in sessions:
        flag = "" if s["available"] else "  [SOLD OUT / BLOCKED]"
        print(
            "  {date} {time}  {room:24}  {price_tier:>11}  #{session_id}{flag}".format(
                flag=flag, **s
            )
        )
        print("      " + (s["buy_url"] or ""))
