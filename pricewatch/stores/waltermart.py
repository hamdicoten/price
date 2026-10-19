"""WalterMart (waltermartdelivery.com.ph) — runs on NCR Freshop.

1. Playwright opens the home page once and captures the session token the site creates.
2. Product searches then go straight to the API over plain HTTP:
   GET https://api.freshop.ncrcloud.com/1/products?app_key=walter_mart&q=...&store_id=...&token=...

Price field: `unit_price` = shelf price per piece (size="pc"). Records without `unit_price` are
usually bundle definitions and are skipped. A returned `sale_price` is treated as a discount.

Branch: no Tarlac branch online; the closest to Capas is WalterMart Mabalacat (7638).
"""
from __future__ import annotations

import logging
import re
import time

import requests

from ..models import Product

log = logging.getLogger(__name__)

API = "https://api.freshop.ncrcloud.com/1/products"
HOME = "https://www.waltermartdelivery.com.ph/"
APP_KEY = "walter_mart"
DEFAULT_STORE_ID = "7638"   # WalterMart Mabalacat
FIELDS = "id,name,size,unit_price,price,sale_price,sale_start_date,sale_finish_date,status,canonical_url,promotion_text"
_TOKEN_RE = re.compile(r"[?&/]token=([0-9a-f]{32})|/sessions/([0-9a-f]{32})")


def get_token(timeout_ms: int = 60_000) -> str:
    from playwright.sync_api import sync_playwright

    token: str | None = None

    def sniff(req):
        nonlocal token
        if token is None and "freshop" in req.url:
            m = _TOKEN_RE.search(req.url)
            if m:
                token = m.group(1) or m.group(2)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(locale="en-PH")
        page.on("request", sniff)
        try:
            page.goto(HOME, wait_until="networkidle", timeout=timeout_ms)
        finally:
            browser.close()
    if not token:
        raise RuntimeError("Could not capture the WalterMart session token")
    return token


def _num(v) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse_products(body: dict) -> list[Product]:
    out = []
    for it in body.get("items") or []:
        if it.get("status") not in (None, "available"):
            continue
        shelf = _num(it.get("unit_price")) or _num(it.get("price"))
        if not shelf or shelf <= 0:
            continue  # bundle / record without a price
        sale = _num(it.get("sale_price"))
        price, regular = (sale, shelf) if sale and 0 < sale < shelf else (shelf, None)
        name = re.sub(r"\s*\|\s*", " ", str(it.get("name", ""))).strip()  # "Eden Cheese | 430g"
        url = it.get("canonical_url") or f"{HOME}shop#!/?product={it.get('id')}"
        out.append(Product(store="waltermart", url=url, name=name, price=price,
                           regular_price=regular,
                           promo="sale" if regular else None))
    return out


def fetch(queries: list[str], store_id: str = DEFAULT_STORE_ID, delay: float = 2.0,
          token: str | None = None, session: requests.Session | None = None) -> list[Product]:
    token = token or get_token()
    s = session or requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (BrewAndSavour-PriceWatch/0.2)",
                      "Origin": "https://www.waltermartdelivery.com.ph",
                      "Referer": HOME})
    found: dict[str, Product] = {}
    for q in queries:
        params = {"app_key": APP_KEY, "q": q, "store_id": store_id, "token": token,
                  "limit": 100, "fields": FIELDS, "sort": "relevance"}
        try:
            r = s.get(API, params=params, timeout=30)
            r.raise_for_status()
            items = parse_products(r.json())
        except (requests.RequestException, ValueError) as e:
            log.warning("WalterMart '%s': %s", q, e)
            continue
        for p in items:
            found.setdefault(p.url, p)
        log.info("WalterMart '%s' (branch %s): %d products", q, store_id, len(items))
        time.sleep(delay)
    return list(found.values())
