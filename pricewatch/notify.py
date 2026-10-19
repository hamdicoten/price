"""Telegram delivery. Reads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from the environment.
Without them the message is printed to stdout (for local testing)."""
from __future__ import annotations

import html
import logging
import os
import re

import requests

log = logging.getLogger(__name__)
LIMIT = 4000  # Telegram limit is 4096


def _to_html(text: str) -> str:
    # *bold* → <b>bold</b>; escape the rest (so _ and & in URLs are safe)
    return re.sub(r"\*([^*\n]+)\*", r"<b>\1</b>", html.escape(text, quote=False))


def _chunks(text: str):
    buf = ""
    for block in text.split("\n\n"):
        if len(buf) + len(block) + 2 > LIMIT and buf:
            yield buf
            buf = ""
        buf += ("\n\n" if buf else "") + block
    if buf:
        yield buf


def send(text: str) -> None:
    if not text:
        return
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print(text)
        return
    for part in _chunks(text):
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30, json={
            "chat_id": chat, "text": _to_html(part), "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })
        if not r.ok:
            log.error("Telegram error %s: %s", r.status_code, r.text[:200])
