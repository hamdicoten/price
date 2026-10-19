"""Landmark (landmark.ph) — the site's own search API returns plain JSON.

GET https://www.landmark.ph/api/products/search-page/v4?substoreAlias=mkt&searchKeywords=eden+cheese
→ [ {id, handle, title, availableForSale, priceRange:{minVariantPrice:{amount}}}, ... ]

Note: the API has no separate sale-price field; Landmark discounts are caught from the price
history (drop / low rules). Direct calls get HTTP 403, so the browser path below is the main one.
"""
from __future__ import annotations

import logging
import time

import requests

from ..models import Product

log = logging.getLogger(__name__)

API = "https://www.landmark.ph/api/products/search-page/v4"
BASE = "https://www.landmark.ph"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (BrewAndSavour-PriceWatch/0.2; personal price tracker)",
    "Accept": "application/json",
    "Referer": f"{BASE}/search",
}


def parse_search(body: list) -> list[Product]:
    out = []
    for it in body or []:
        if not it.get("availableForSale", True):
            continue
        try:
            price = float(it["priceRange"]["minVariantPrice"]["amount"])
        except (KeyError, TypeError, ValueError):
            continue
        if price <= 0:
            continue
        out.append(Product(
            store="landmark",
            url=f"{BASE}/products/{it.get('handle')}/{it.get('id')}",
            name=str(it.get("title", "")).strip(),
            price=price,
        ))
    return out


def _fetch_http(queries, substore, delay, session):
    s = session or requests.Session()
    s.headers.update(HEADERS)
    found: dict[str, Product] = {}
    failures = 0
    for q in queries:
        try:
            r = s.get(API, params={"substoreAlias": substore, "searchKeywords": q}, timeout=30)
            r.raise_for_status()
            items = parse_search(r.json())
        except (requests.RequestException, ValueError) as e:
            log.warning("Landmark '%s' (HTTP): %s", q, e)
            failures += 1
            if failures >= 2 and not found:
                raise RuntimeError("Landmark rejects direct API calls") from e
            continue
        for p in items:
            found.setdefault(p.url, p)
        log.info("Landmark '%s': %d products", q, len(items))
        time.sleep(delay)
    return found


def _fetch_browser(queries, substore, delay):
    """Opens the search page in a real browser and captures the API response the page itself requests.
    (Calling the API directly returns 403, even from a browser session.)"""
    from urllib.parse import quote_plus

    from playwright.sync_api import sync_playwright

    found: dict[str, Product] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(locale="en-PH")
        for q in queries:
            page = ctx.new_page()   # new tab per query so client-side routing does not reuse a cached result
            try:
                with page.expect_response(lambda r: "/api/products/search-page" in r.url,
                                          timeout=45_000) as resp_info:
                    page.goto(f"{BASE}/search?q={quote_plus(q)}", wait_until="domcontentloaded",
                              timeout=60_000)
                r = resp_info.value
                if not r.ok:
                    log.warning("Landmark '%s' (browser): HTTP %s", q, r.status)
                    continue
                items = parse_search(r.json())
            except Exception as e:  # noqa: BLE001
                log.warning("Landmark '%s' (browser): %s", q, e)
                continue
            finally:
                page.close()
            for p in items:
                found.setdefault(p.url, p)
            log.info("Landmark '%s' (browser): %d products", q, len(items))
            time.sleep(delay)
        browser.close()
    return found


def fetch(queries: list[str], substore: str = "mkt", delay: float = 2.0,
          session: requests.Session | None = None) -> list[Product]:
    try:
        found = _fetch_http(queries, substore, delay, session)
    except RuntimeError as e:
        log.info("%s — trying with the browser…", e)
        found = _fetch_browser(queries, substore, delay)
    if not found:
        log.error("Landmark: no products received")
    return list(found.values())
