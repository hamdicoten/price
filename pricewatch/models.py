from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Product:
    store: str                 # "snr" | "waltermart" | "landmark"
    url: str                   # stable key for the product
    name: str
    price: float               # price we track (S&R: depends on membership)
    regular_price: float | None = None   # struck-through old price, if any
    member_price: float | None = None
    non_member_price: float | None = None
    promo: str | None = None   # "price-off", "buy1take1", ...

    @property
    def on_sale(self) -> bool:
        return self.regular_price is not None and self.regular_price > self.price

    @property
    def sale_pct(self) -> float | None:
        if not self.on_sale:
            return None
        return round(1 - self.price / self.regular_price, 3)


@dataclass
class WatchItem:
    id: str
    name: str
    category: str = "Other"
    brands: list[str] = field(default_factory=list)    # empty = any brand (fresh meat, generic items)
    keywords: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)   # search terms for stores that need a search
