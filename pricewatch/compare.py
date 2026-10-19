"""Finds the same product in different stores (similar name + identical size)."""
from __future__ import annotations

import re

from .matcher import normalize
from .units import parse_size

_STOP = {"g", "gr", "gm", "kg", "ml", "l", "pc", "pcs", "the", "with", "and", "of", "x", "s"}


def _key(name: str):
    n = normalize(name)
    toks = set(re.findall(r"[a-z]+", n)) - _STOP
    size = parse_size(name)
    return toks, ((round(size.qty, 4), size.unit) if size else None)


def cross_store_pairs(rows: list[dict], min_similarity: float = 0.6) -> list[dict]:
    """rows: {store, name, price, url}. Returns cross-store pairs with the same size and a similar
    name (each product in at most one pair), largest price gap first."""
    keyed = [(r, *_key(r["name"])) for r in rows]
    keyed = [k for k in keyed if k[2] is not None and k[1]]
    cands = []
    for i, (a, ta, sa) in enumerate(keyed):
        for b, tb, sb in keyed[i + 1:]:
            if a["store"] == b["store"] or sa != sb:
                continue
            sim = len(ta & tb) / len(ta | tb)
            if sim >= min_similarity:
                cands.append((sim, a, b))
    cands.sort(key=lambda c: -c[0])
    used, pairs = set(), []
    for sim, a, b in cands:
        if a["url"] in used or b["url"] in used:
            continue
        used.update((a["url"], b["url"]))
        lo, hi = sorted((a, b), key=lambda r: r["price"])
        if lo["price"] <= 0:
            continue
        pairs.append({"cheap": lo, "dear": hi, "gap": hi["price"] / lo["price"] - 1, "similarity": sim})
    pairs.sort(key=lambda p: -p["gap"])
    return pairs
