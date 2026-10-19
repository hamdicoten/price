"""Matches product names against the watchlist groups."""
from __future__ import annotations

import re
import unicodedata

import yaml

from .models import WatchItem


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))  # Nestlé -> Nestle
    text = text.lower().replace("’", "'").replace("'", "")           # McCormick's -> mccormicks
    return re.sub(r"\s+", " ", text).strip()


def _has(term: str, text: str) -> bool:
    term = normalize(term)
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}", text) is not None


def load_watchlist(path: str) -> tuple[dict, list[WatchItem]]:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    items = [WatchItem(**it) for it in data["items"]]
    for it in items:
        if not it.brands and not it.keywords:
            raise ValueError(f"watchlist item '{it.id}' needs brands or keywords")
    return data.get("settings", {}), items


def match(name: str, items: list[WatchItem]) -> list[str]:
    """Returns the group ids a product belongs to (a product may sit in several groups)."""
    text = normalize(name)
    hits = []
    for it in items:
        if it.brands and not any(_has(b, text) for b in it.brands):
            continue
        if it.keywords and not any(_has(k, text) for k in it.keywords):
            continue
        if any(_has(x, text) for x in it.exclude):
            continue
        hits.append(it.id)
    return hits
