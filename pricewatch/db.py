"""SQLite price history. One observation per product per day (a re-run the same day overwrites it)."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from .models import Product

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    url        TEXT PRIMARY KEY,
    store      TEXT NOT NULL,
    name       TEXT NOT NULL,
    groups     TEXT NOT NULL,           -- comma-separated group ids
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS prices (
    url           TEXT NOT NULL REFERENCES products(url),
    day           TEXT NOT NULL,
    price         REAL NOT NULL,
    regular_price REAL,
    promo         TEXT,
    PRIMARY KEY (url, day)
);
CREATE TABLE IF NOT EXISTS alerts (
    url   TEXT NOT NULL,
    day   TEXT NOT NULL,
    kind  TEXT NOT NULL,
    price REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts_url ON alerts(url, day);
CREATE TABLE IF NOT EXISTS search_hits (   -- what each store search returned that day
    day    TEXT NOT NULL,
    store  TEXT NOT NULL,
    query  TEXT NOT NULL,
    pos    INTEGER NOT NULL,                -- position in the store's results (relevance)
    url    TEXT,
    name   TEXT,
    price  REAL,
    PRIMARY KEY (day, store, query, pos)
);
"""


class DB:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    def record(self, p: Product, groups: list[str], day: date) -> None:
        d = day.isoformat()
        self.conn.execute(
            """INSERT INTO products(url, store, name, groups, first_seen, last_seen)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(url) DO UPDATE SET name=excluded.name, groups=excluded.groups,
                                              last_seen=excluded.last_seen""",
            (p.url, p.store, p.name, ",".join(groups), d, d))
        self.conn.execute(
            """INSERT INTO prices(url, day, price, regular_price, promo) VALUES (?,?,?,?,?)
               ON CONFLICT(url, day) DO UPDATE SET price=excluded.price,
                   regular_price=excluded.regular_price, promo=excluded.promo""",
            (p.url, d, p.price, p.regular_price, p.promo))

    def history(self, url: str, before: date, days: int | None = None) -> list[float]:
        """Prices BEFORE `before` (today excluded)."""
        if days is None:
            rows = self.conn.execute(
                "SELECT price FROM prices WHERE url=? AND day<? ORDER BY day", (url, before.isoformat()))
        else:
            start = (before - timedelta(days=days)).isoformat()
            rows = self.conn.execute(
                "SELECT price FROM prices WHERE url=? AND day<? AND day>=? ORDER BY day",
                (url, before.isoformat(), start))
        return [r[0] for r in rows]

    def recently_alerted(self, url: str, kind: str, price: float, day: date, within_days: int) -> bool:
        start = (day - timedelta(days=within_days)).isoformat()
        row = self.conn.execute(
            "SELECT 1 FROM alerts WHERE url=? AND kind=? AND price<=? AND day>=? LIMIT 1",
            (url, kind, price, start)).fetchone()
        return row is not None

    def log_alert(self, url: str, kind: str, price: float, day: date) -> None:
        self.conn.execute("INSERT INTO alerts(url, day, kind, price) VALUES (?,?,?,?)",
                          (url, day.isoformat(), kind, price))

    def stores_done(self, day: date) -> set[str]:
        """Stores with prices recorded on that day."""
        rows = self.conn.execute(
            "SELECT DISTINCT p.store FROM prices pr JOIN products p USING(url) WHERE pr.day=?",
            (day.isoformat(),))
        return {r[0] for r in rows}

    def products_on(self, day: date, stores: set[str]) -> list[tuple[Product, list[str]]]:
        """Returns stored prices as Products (to reuse without re-scanning)."""
        if not stores:
            return []
        marks = ",".join("?" * len(stores))
        rows = self.conn.execute(
            f"""SELECT p.store, p.url, p.name, p.groups, pr.price, pr.regular_price, pr.promo
                FROM prices pr JOIN products p USING(url)
                WHERE pr.day=? AND p.store IN ({marks})""", (day.isoformat(), *sorted(stores)))
        return [(Product(store=r[0], url=r[1], name=r[2], price=r[4], regular_price=r[5], promo=r[6]),
                 [g for g in (r[3] or "").split(",") if g]) for r in rows]

    def save_searches(self, day: date, hits: dict) -> None:
        """hits: {(store, query): [Product, ...]}. Replaces that day's rows for the stores given;
        a query with no results is kept as a row with pos -1 so empty searches stay visible."""
        d = day.isoformat()
        for store in {s for s, _ in hits}:
            self.conn.execute("DELETE FROM search_hits WHERE day=? AND store=?", (d, store))
        for (store, query), prods in hits.items():
            if not prods:
                self.conn.execute("INSERT OR REPLACE INTO search_hits VALUES (?,?,?,?,?,?,?)",
                                  (d, store, query, -1, None, None, None))
            for i, p in enumerate(prods):
                self.conn.execute("INSERT OR REPLACE INTO search_hits VALUES (?,?,?,?,?,?,?)",
                                  (d, store, query, i, p.url, p.name, p.price))

    def commit(self) -> None:
        self.conn.commit()
