"""Alert rules and the daily digest (Telegram text)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import median

from .db import DB
from .models import Product, WatchItem
from .units import parse_size, unit_price

STORE_NAMES = {"snr": "S&R", "waltermart": "WalterMart", "landmark": "Landmark", "robinsons": "Robinsons"}


@dataclass
class Alert:
    kind: str          # sale | promo | drop | low
    product: Product
    detail: str


def evaluate(p: Product, db: DB, settings: dict, day: date) -> list[Alert]:
    out: list[Alert] = []
    hist30 = db.history(p.url, before=day, days=settings.get("history_days", 30))
    hist_all = db.history(p.url, before=day)

    if p.on_sale:
        out.append(Alert("sale", p, f"Store discount {p.sale_pct * 100:.0f}% "
                                   f"(₱{p.regular_price:,.2f} → ₱{p.price:,.2f})"))
    elif p.promo in ("buy1take1",):
        out.append(Alert("promo", p, "Buy 1 Take 1 — effectively half price"))

    if hist30:
        med = median(hist30)
        drop = 1 - p.price / med
        if drop >= settings.get("drop_threshold", 0.15):
            out.append(Alert("drop", p, f"{drop * 100:.0f}% below its 30-day median (₱{med:,.2f})"))

    if (len(hist_all) >= settings.get("min_history_for_low", 7)
            and p.price <= min(hist_all) * (1 - settings.get("min_low_gap", 0.05))):
        out.append(Alert("low", p, f"Lowest since tracking started (previous low ₱{min(hist_all):,.2f})"))

    realert = settings.get("realert_days", 7)
    fresh = [a for a in out if not db.recently_alerted(p.url, a.kind, p.price, day, realert)]
    for a in fresh:
        db.log_alert(p.url, a.kind, p.price, day)
    return fresh


def _unit(p: Product):
    return unit_price(p.price, parse_size(p.name))


def format_alerts(alerts: list[Alert], groups_of: dict[str, list[str]], items: list[WatchItem]) -> str:
    if not alerts:
        return ""
    names = {it.id: it.name for it in items}
    by_product: dict[str, list[Alert]] = {}
    for a in alerts:
        by_product.setdefault(a.product.url, []).append(a)
    lines = ["🔔 *Price alerts*"]
    for url, al in by_product.items():
        p = al[0].product
        grp = ", ".join(names.get(g, g) for g in groups_of.get(url, []))
        up = _unit(p)
        unit = f" · {up[0]:,.0f} {up[1]}" if up else ""
        lines.append(f"\n*{p.name}* — {STORE_NAMES.get(p.store, p.store)} [{grp}]")
        lines.append(f"₱{p.price:,.2f}{unit}")
        lines += [f"• {a.detail}" for a in al]
        lines.append(url)
    return "\n".join(lines)


def best_in_group(products: list[Product], groups_of: dict[str, list[str]], item_id: str, n: int = 3):
    """Cheapest n products of a group by unit price, compared in the group's most common unit
    (₱/kg vs ₱/L vs ₱/pcs are never mixed)."""
    rows = [(_unit(p), p) for p in products if item_id in groups_of.get(p.url, [])]
    rows = [r for r in rows if r[0]]
    if not rows:
        return []
    units = [r[0][1] for r in rows]
    main = max(set(units), key=units.count)
    rows = sorted((r for r in rows if r[0][1] == main), key=lambda r: r[0][0])
    return rows[:n]


def daily_digest(products: list[Product], groups_of: dict[str, list[str]], items: list[WatchItem],
                 today: date | None = None) -> str:
    """Per category, per group: today's cheapest products by unit price."""
    today = today or date.today()
    lines = [f"☕ *Brew & Savour — daily price digest* ({today:%d %b %Y})"]
    categories: dict[str, list[WatchItem]] = {}
    for it in items:
        categories.setdefault(it.category, []).append(it)
    for cat, its in categories.items():
        block = [f"\n*{cat.upper()}*"]
        for it in its:
            rows = best_in_group(products, groups_of, it.id)
            if not rows:
                block.append(f"{it.name}: no matches today")
                continue
            block.append(f"*{it.name}*")
            for up, p in rows:
                tag = " 🏷️" if p.on_sale or p.promo else ""
                block.append(f"• {up[0]:,.0f} {up[1]} — {p.name} "
                             f"({STORE_NAMES.get(p.store, p.store)}, ₱{p.price:,.2f}){tag}")
        lines += block
    return "\n".join(lines)
