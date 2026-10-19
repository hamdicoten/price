"""Reads the pack size from a product name and converts price to unit price (₱/kg, ₱/L, ₱/pcs)."""
from __future__ import annotations

import re
from dataclasses import dataclass

_UNIT_FACTORS = {
    # unit -> (base unit, factor)
    "kg": ("kg", 1.0),
    "g": ("kg", 0.001),
    "gm": ("kg", 0.001),
    "gr": ("kg", 0.001),
    "grams": ("kg", 0.001),
    "l": ("L", 1.0),
    "liter": ("L", 1.0),
    "litre": ("L", 1.0),
    "ml": ("L", 0.001),
}

# "4 x 130g", "4x130g", "130g x 4"
_MULTI_A = re.compile(r"(\d+)\s*(?:cans?|pcs|pieces|packs?|bottles?|sachets?)?\s*[x×]\s*(\d+(?:\.\d+)?)\s*(kg|gr|gm|grams|g|ml|l|liter|litre)\b", re.I)
_MULTI_B = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|gr|gm|grams|g|ml|l|liter|litre)\s*[x×]\s*(\d+)\b", re.I)
_SINGLE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|gr|gm|grams|g|ml|l|liter|litre)\b", re.I)
_PIECES = re.compile(r"(\d+)\s*(pcs|pieces|pc|cans|packs|sachets|bottles)\b", re.I)


# Pack count written AFTER the size: "250ml 24s", "250ml x 4s", "200g 2 for 99", "220g Buy 2 Save 10"
_PACK_PATTERNS = [
    re.compile(r"^\s*(?:x\s*)?(\d+)\s*s\b", re.I),       # 24s / x 4s / 2s
    re.compile(r"\b(\d+)\s*for\s+\d", re.I),              # 2 for 99
    re.compile(r"\bbuy\s*(\d+)\b", re.I),                 # Buy 2 Save 10 pesos
]


def _pack_count(rest: str) -> int:
    for pat in _PACK_PATTERNS:
        m = pat.search(rest)
        if m and 1 < int(m.group(1)) <= 100:
            return int(m.group(1))
    return 1


@dataclass(frozen=True)
class Size:
    qty: float      # taban birimde toplam miktar (kg, L veya adet)
    unit: str       # "kg" | "L" | "pcs"

    def label(self) -> str:
        return f"{self.qty:g} {self.unit}"


def parse_size(name: str) -> Size | None:
    text = name.replace(",", "")
    m = _MULTI_A.search(text)
    if m:
        count, amount, unit = int(m.group(1)), float(m.group(2)), m.group(3).lower()
        base, f = _UNIT_FACTORS[unit]
        return Size(count * amount * f, base)
    m = _MULTI_B.search(text)
    if m:
        amount, unit, count = float(m.group(1)), m.group(2).lower(), int(m.group(3))
        base, f = _UNIT_FACTORS[unit]
        return Size(count * amount * f, base)
    # If several sizes appear, use the first one
    m = _SINGLE.search(text)
    if m:
        amount, unit = float(m.group(1)), m.group(2).lower()
        base, f = _UNIT_FACTORS[unit]
        if amount > 0:
            return Size(amount * f * _pack_count(text[m.end():]), base)
    m = _PIECES.search(text)
    if m and int(m.group(1)) > 0:
        return Size(float(m.group(1)), "pcs")
    return None


def unit_price(price: float, size: Size | None) -> tuple[float, str] | None:
    """Returns (₱ per base unit, label), or None when the size is unknown."""
    if size is None or size.qty <= 0:
        return None
    return round(price / size.qty, 2), f"₱/{size.unit}"
