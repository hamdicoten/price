"""Collects what each store search returned, so the panel can show what was found, what was
filtered out by the watchlist, and which searches came back empty.

Store fetchers call `record()` once per query; the CLI stores the result for the day.
"""
from __future__ import annotations

from .models import Product

# (store, query) -> products in the order the store returned them
HITS: dict[tuple[str, str], list[Product]] = {}


def reset() -> None:
    HITS.clear()


def record(store: str, query: str, products: list[Product]) -> None:
    HITS[(store, query)] = list(products)
