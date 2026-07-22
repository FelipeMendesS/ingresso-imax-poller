"""Telegram notifications for new / reopened IMAX sessions."""

import os

import requests

import config

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramConfigError(RuntimeError):
    pass


def _credentials():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise TelegramConfigError(
            "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set "
            "(as env vars locally, or as GitHub repo secrets in CI)."
        )
    return token, chat_id


def _escape(text):
    """Escape HTML special chars for Telegram parse_mode=HTML."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _send(text, disable_preview=True):
    token, chat_id = _credentials()
    resp = requests.post(
        TELEGRAM_API.format(token=token),
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_preview,
        },
        timeout=config.HTTP_TIMEOUT_SECONDS,
    )
    # Surface Telegram's error body (bad token / chat id) instead of a bare 4xx.
    if not resp.ok:
        raise RuntimeError(
            "Telegram sendMessage failed (%s): %s" % (resp.status_code, resp.text)
        )
    return resp.json()


def _session_block(s):
    dow = (" (%s)" % s["day_of_week"]) if s.get("day_of_week") else ""
    lines = [
        "🎬 <b>Sessão IMAX à venda</b>",
        "📅 %s%s  ⏰ <b>%s</b>" % (_escape(s.get("date")), _escape(dow), _escape(s.get("time"))),
        "🏛 %s" % _escape(s.get("room")),
    ]
    if s.get("format"):
        lines.append("🎞 %s" % _escape(s["format"]))
    if s.get("price_tier"):
        lines.append("💵 %s" % _escape(s["price_tier"]))
    if s.get("buy_url"):
        lines.append('🎟 <a href="%s">Comprar ingresso</a>' % _escape(s["buy_url"]))
    return "\n".join(lines)


def notify_new_sessions(sessions, watch=None):
    """Send one Telegram message per session that just went on sale.

    Returns the number of messages sent.
    """
    watch = watch or config.WATCH
    header = _escape(watch.get("label", "IMAX watch"))
    sent = 0
    for s in sessions:
        _send("<b>%s</b>\n\n%s" % (header, _session_block(s)))
        sent += 1
    return sent


def notify_startup_summary(sessions, watch=None):
    """One-off summary sent on the first run so we don't spam per-session."""
    watch = watch or config.WATCH
    header = _escape(watch.get("label", "IMAX watch"))
    if not sessions:
        body = "Nenhuma sessão IMAX listada no momento. Vou avisar assim que aparecer. 👀"
    else:
        on_sale = sum(1 for s in sessions if s.get("available"))
        lines = [
            "Monitorando. Só te aviso quando uma sessão IMAX entrar à venda.",
            "Agora: %d sessão(ões) listada(s), %d à venda." % (len(sessions), on_sale),
        ]
        for s in sessions:
            status = "à venda" if s.get("available") else "esgotada"
            lines.append(
                "• %s %s — %s (%s) — %s"
                % (
                    _escape(s.get("date")),
                    _escape(s.get("time")),
                    _escape(s.get("room")),
                    _escape(s.get("price_tier") or "?"),
                    status,
                )
            )
        body = "\n".join(lines)
    _send("✅ <b>%s</b>\n\n%s" % (header, body))


def notify_heartbeat(sessions, watch=None):
    """Proof-of-life ping: bot is running, no new sessions on sale right now."""
    watch = watch or config.WATCH
    header = _escape(watch.get("label", "IMAX watch"))
    total = len(sessions)
    on_sale = sum(1 for s in sessions if s.get("available"))
    body = (
        "💓 Bot no ar — sem novas sessões IMAX à venda por enquanto.\n"
        "Monitorando %d sessão(ões), %d à venda agora.\n"
        "Te aviso na hora que abrir uma nova. 🎬" % (total, on_sale)
    )
    _send("💓 <b>%s</b>\n\n%s" % (header, body))


def send_raw(text):
    """Escape-hatch for ad-hoc messages (used by --test)."""
    return _send(_escape(text))


if __name__ == "__main__":
    # `python notify.py` sends a test message to verify credentials.
    print(send_raw("✅ Ingresso IMAX poller: test message. Credentials OK."))
