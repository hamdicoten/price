"""Recon helper for WalterMart and Landmark — prices load with JavaScript.

Opens a search page with Playwright, captures the JSON responses the page fetches and saves them
under recon/ so the store parsers can be written against real data.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from urllib.parse import quote_plus

from ..models import Product

log = logging.getLogger(__name__)

STORES = {
    "waltermart": {
        "search_url": "https://www.waltermartdelivery.com.ph/shop#!/?q={q}",
        "verified": False,
    },
    "landmark": {
        "search_url": "https://www.landmark.ph/search?q={q}",              
        "verified": False,
    },
}

NAME_KEYS = ("name", "title", "product_name", "productName", "display_name")
PRICE_KEYS = ("price", "sale_price", "salePrice", "final_price", "finalPrice", "price_value")
REGULAR_KEYS = ("regular_price", "regularPrice", "original_price", "originalPrice",
                "compare_at_price", "base_price", "list_price")
URL_KEYS = ("url", "canonical_url", "permalink", "slug", "href", "id")


def _to_float(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace("₱", "").replace(",", "").strip())
        except ValueError:
            return None
    if isinstance(v, dict):  # {"amount": 123.0} gibi
        for k in ("amount", "value", "raw"):
            if k in v:
                return _to_float(v[k])
    return None


def extract_products(obj, store: str, base_url: str) -> list[Product]:
    """Finds objects carrying a name + price anywhere in a JSON tree (heuristic)."""
    out: list[Product] = []

    def walk(node):
        if isinstance(node, dict):
            name = next((node[k] for k in NAME_KEYS if isinstance(node.get(k), str)), None)
            price = next((p for k in PRICE_KEYS if (p := _to_float(node.get(k))) is not None), None)
            if name and price and price > 0:
                regular = next((r for k in REGULAR_KEYS if (r := _to_float(node.get(k))) is not None), None)
                key = next((str(node[k]) for k in URL_KEYS if node.get(k)), name)
                url = key if key.startswith("http") else f"{base_url}#{key}"
                out.append(Product(store=store, url=url, name=name.strip(), price=price,
                                   regular_price=regular if regular and regular > price else None))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(obj)
    return out


def search(store: str, queries: list[str], recon_dir: Path | None = None,
           delay: float = 4.0) -> list[Product]:
    from playwright.sync_api import sync_playwright  # heavy dependency, imported only here

    cfg = STORES[store]
    results: dict[str, Product] = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(locale="en-PH")
        for q in queries:
            # New tab per query: on hash-routed sites (WalterMart #!/?q=) a hash-only change
            # does not reload the page or fire new requests.
            page = context.new_page()
            captured: list[tuple[str, object]] = []

            def on_response(resp):
                if "json" not in (resp.headers.get("content-type") or ""):
                    return
                try:
                    captured.append((resp.url, resp.json()))
                except Exception:
                    pass

            page.on("response", on_response)
            url = cfg["search_url"].format(q=quote_plus(q))
            try:
                page.goto(url, wait_until="networkidle", timeout=60_000)
            except Exception as e:
                log.warning("%s '%s': %s", store, q, e)
            page.remove_listener("response", on_response)

            if recon_dir:
                d = recon_dir / store / q.replace(" ", "_")
                d.mkdir(parents=True, exist_ok=True)
                (d / "page.html").write_text(page.content(), encoding="utf-8")
                for i, (u, body) in enumerate(captured):
                    (d / f"{i:02d}.json").write_text(
                        json.dumps({"url": u, "body": body}, ensure_ascii=False, indent=1),
                        encoding="utf-8")
                log.info("%s '%s': saved %d JSON responses → %s", store, q, len(captured), d)

            for _, body in captured:
                for p in extract_products(body, store, url):
                    results.setdefault(p.url, p)
            page.close()
            time.sleep(delay)
        context.close()
        browser.close()
    return list(results.values())
