"""S&R (snrshopping.com) — pages are server-rendered; plain HTTP + HTML parsing is enough.

Scans category pages (no dependency on a search URL) and matches product names against the
watchlist afterwards. "On Sale" categories are scanned separately so the promo type
(price-off / buy1take1) bilinsin.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Callable
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup, Tag

from .. import searchlog
from ..models import Product

log = logging.getLogger(__name__)

BASE = "https://www.snrshopping.com"

# kategori yolu -> promosyon etiketi (None = normal kategori)
CATEGORIES: dict[str, str | None] = {
    "/category/shop-all-categories/groceries-1/pantry-items-1/condiments-seasonings-1": None,
    "/category/shop-all-categories/groceries-1/pantry-items-1/baking-toppings-1": None,
    "/category/shop-all-categories/groceries-1/pantry-items-1/rice-pasta-noodles-and-soup": None,
    "/category/shop-all-categories/groceries-1/eggs-chilled-products-1/fresh-milk-yogurts-chilled-products-1": None,
    "/category/shop-all-categories/groceries-1/beverages-1/milk-products-1": None,
    "/category/shop-all-categories/groceries-1/snacks-sweets-dips-1/dips-spreads-1": None,
    # Member's Value pages show prices even without login (verified in recon)
    # Meat
    "/category/shop-all-categories/groceries-1/fresh-meat-produce-seafood-1/chicken-1": None,
    "/category/shop-all-categories/groceries-1/fresh-meat-produce-seafood-1/pork": None,
    "/category/shop-all-categories/groceries-1/fresh-meat-produce-seafood-1/beef": None,
    # Cleaning & café supplies
    "/category/shop-all-categories/household-cleaning-essentials/cleaning-products-1": None,
    "/category/shop-all-categories/household-cleaning-essentials/paper-products-1": None,
    "/category/shop-all-categories/household-cleaning-essentials/disposables-1": None,
    "/category/members-value/household-cleaning": None,
    "/category/members-value/home-essentials": None,
    "/category/members-value/fresh-meat-seafoods": None,
    "/category/members-value/dry-goods-condiments": None,
    "/category/members-value/spreads-dressings": None,
    "/category/members-value/pantry-staples": None,
    "/category/members-value/kitchen-essentials": None,
    "/category/on-sale/price-off": "price-off",
    "/category/on-sale/buy-x-take-x": "buy1take1",
    "/category/on-sale/item-of-the-week": "item-of-the-week",
}

# A few non-digit characters between the currency sign and the number (₱, spaces, broken encoding)
_MONEY = r"[^\d]{0,8}?([\d,]+(?:\.\d{1,2})?)"
_MEMBER_RE = re.compile(r"(?<![-A-Za-z])Member Price\s*" + _MONEY)
_NONMEMBER_RE = re.compile(r"Non-member Price:?\s*" + _MONEY, re.I)

HEADERS = {
    "User-Agent": "BrewAndSavour-PriceWatch/0.1 (+personal price tracker; 1 req/3s)",
    "Accept-Language": "en-PH,en;q=0.8",
}


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def canonical_url(href: str) -> str:
    """The same product is linked as /product/<category path>/<slug> on category pages and as
    /product/<slug> in search results; key it by the slug so it is counted once."""
    path = urljoin(BASE, href.strip()).split("?")[0].split("#")[0].strip().rstrip("/")
    return f"{BASE}/product/{path.rsplit('/', 1)[-1]}" if "/product/" in path else path


def _card_for(anchor: Tag) -> Tag | None:
    """Walks up from the product title link to the smallest container that also holds the price."""
    node = anchor
    for _ in range(6):
        node = node.parent
        if node is None:
            return None
        if node.select_one(".oc-price") or "Member Price" in node.get_text(" "):
            # A container holding several products means we went too far up
            titles = {a["href"] for a in node.find_all("a", href=True)
                      if "/product/" in a["href"] and a.get_text(strip=True)}
            return node if len(titles) == 1 else None
    return None


def parse_listing(html: str, promo: str | None = None, member: bool = False) -> list[Product]:
    soup = BeautifulSoup(html, "html.parser")
    products: dict[str, Product] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        name = a.get_text(" ", strip=True)
        if "/product/" not in href or not name:
            continue  # image links have no text; skip them
        url = canonical_url(href)
        if url in products:
            continue
        card = _card_for(a)
        if card is None:
            continue
        # Logged-in view: .oc-price = what the account pays, .og-price = price before the discount
        oc = card.select_one(".oc-price")
        if oc is not None:
            cur = re.search(r"[\d,]+(?:\.\d{1,2})?", oc.get_text())
            if not cur:
                continue
            price = _num(cur.group(0))
            og = card.select_one(".og-price")
            reg = re.search(r"[\d,]+(?:\.\d{1,2})?", og.get_text()) if og else None
            products[url] = Product(
                store="snr", url=url, name=name, price=price,
                regular_price=_num(reg.group(0)) if reg else None,
                member_price=price if member else None, promo=promo,
            )
            continue

        # Guest view: "Member Price ₱ x" + "Non-member Price: ₱ y"
        text = card.get_text(" ", strip=True)
        m = _MEMBER_RE.search(text)
        if not m:
            continue
        member_price = _num(m.group(1))
        nm = _NONMEMBER_RE.search(text)
        non_member = _num(nm.group(1)) if nm else None

        regular = None
        old = card.find(["del", "s", "strike"])
        if old:
            digits = re.search(r"[\d,]+(?:\.\d{1,2})?", old.get_text())
            if digits:
                regular = _num(digits.group(0))

        price = member_price if member or non_member is None else non_member
        # Old price is member-based; for non-members apply the same ratio
        if regular and not member and non_member:
            regular = round(regular * non_member / member_price, 2)

        products[url] = Product(
            store="snr", url=url, name=name, price=price, regular_price=regular,
            member_price=member_price, non_member_price=non_member, promo=promo,
        )
    return list(products.values())


def _unpriced_links(html: str) -> list[Product]:
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, Product] = {}
    for a in soup.find_all("a", href=True):
        name = a.get_text(" ", strip=True)
        # "Rice, Pasta, Noodles, and Soup (3)" is a category filter link, not a product
        if "/product/" in a["href"] and name and not re.search(r"\(\d+\)$", name):
            url = canonical_url(a["href"])
            out.setdefault(url, Product(store="snr", url=url, name=name, price=0.0))
    return list(out.values())


def product_link_count(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    return len({a["href"] for a in soup.find_all("a", href=True)
                if "/product/" in a["href"] and a.get_text(strip=True)})


def login(s: requests.Session, email: str, password: str, debug_dir=None) -> bool:
    """Reads the login form from the page (action, hidden fields, field names) and submits it.
    Credentials come only from the caller; they are never stored or logged here."""
    page = s.get(BASE + "/login", timeout=30)
    soup = BeautifulSoup(page.text, "html.parser")
    pw_input = soup.find("input", attrs={"type": "password"})
    form = pw_input.find_parent("form") if pw_input else None
    if form is None:
        log.error("S&R: login form not found")
        return False
    data = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        typ = (inp.get("type") or "text").lower()
        if typ == "password":
            data[name] = password
        elif typ in ("email", "text") and ("mail" in name.lower() or "user" in name.lower()):
            data[name] = email
        elif typ == "checkbox":
            data[name] = inp.get("value") or "on"   # Remember Me
        elif typ == "hidden":
            data[name] = inp.get("value", "")
    if email not in data.values():
        log.error("S&R: email field not found (form fields: %s)", list(data))
        return False
    action = urljoin(BASE + "/login", form.get("action") or "/login")
    r = s.post(action, data=data, timeout=30, headers={"Referer": BASE + "/login"})
    logged_in = "/login" not in r.url and not re.search(r">\s*Sign In\s*/", r.text)
    log.info("S&R login: %s (final URL: %s)", "OK" if logged_in else "FAILED", r.url)
    if not logged_in:
        # Diagnostics: field NAMES (not values), captcha traces and the site's error message
        log.info("S&R login form: action=%s method=%s fields=%s",
                 action, form.get("method"), sorted(data))
        form_html = str(form).lower()
        for hint in ("recaptcha", "g-recaptcha", "hcaptcha", "turnstile", "captcha"):
            if hint in form_html or hint in page.text.lower():
                log.warning("S&R login page mentions '%s' — possibly a captcha", hint)
                break
        err = BeautifulSoup(r.text, "html.parser").select(
            ".alert, .invalid-feedback, .help-block, .text-danger, .error")
        msgs = {e.get_text(" ", strip=True) for e in err if e.get_text(strip=True)}
        log.info("S&R error messages: %s", list(msgs)[:5] or "none found")
        if debug_dir:
            debug_dir.mkdir(parents=True, exist_ok=True)
            scrub = lambda t: t.replace(email, "<EMAIL>")  # noqa: E731
            (debug_dir / "login_page.html").write_text(scrub(page.text), encoding="utf-8")
            (debug_dir / "login_response.html").write_text(scrub(r.text), encoding="utf-8")
    return logged_in


def login_with_browser(s: requests.Session, email: str, password: str,
                       timeout_ms: int = 60_000) -> bool:
    """If the plain HTTP login fails: fill the form in a real browser and copy its cookies.
    (Works when the site adds fields or tokens with JavaScript.)"""
    from playwright.sync_api import sync_playwright

    ok = False
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(locale="en-PH", user_agent=s.headers.get("User-Agent"))
        page = ctx.new_page()
        try:
            page.goto(BASE + "/login", wait_until="domcontentloaded", timeout=timeout_ms)
            form = page.locator("form:has(input[type=password])").first
            form.locator("input[type=email], input[name*=mail i]").first.fill(email)
            form.locator("input[type=password]").first.fill(password)
            with page.expect_navigation(timeout=timeout_ms):
                form.locator("button[type=submit], input[type=submit], button").first.click()
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
            ok = "/login" not in page.url
            if not ok:
                errs = page.locator(".alert, .invalid-feedback, .help-block, .text-danger").all_inner_texts()
                log.info("S&R browser login error messages: %s",
                         [e.strip() for e in errs if e.strip()][:5] or "none found")
            for c in ctx.cookies():
                s.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/"))
        finally:
            browser.close()
    log.info("S&R browser login: %s (final URL: %s)", "OK" if ok else "FAILED", page.url)
    return ok


def ensure_login(s: requests.Session, email: str, password: str, debug_dir=None) -> bool:
    if login(s, email, password, debug_dir=debug_dir):
        return True
    log.info("S&R: plain HTTP login failed, trying with the browser…")
    try:
        return login_with_browser(s, email, password)
    except Exception as e:
        log.error("S&R browser login error: %s", e)
        return False


def set_delivery_address(s: requests.Session, address: dict) -> dict | None:
    """Mimics the site's 'Set Delivery Address' form (POST /calculateDistance)."""
    home = s.get(BASE + "/", timeout=30)
    m = re.search(r'<meta name="csrf-token" content="([^"]+)"', home.text)
    if not m:
        log.warning("S&R: csrf token not found, address not set")
        return None
    destination = "+".join(str(address.get(k, "")) for k in
                           ("company_name", "building_no", "street", "barangay", "city")) + "+PH"
    data = {**{k: address.get(k, "") for k in
               ("company_name", "building_no", "street", "barangay", "city")},
            "destination": destination, "_token": m.group(1)}
    r = s.post(BASE + "/calculateDistance", data=data, timeout=30,
               headers={"X-Requested-With": "XMLHttpRequest", "Referer": BASE + "/"})
    try:
        info = r.json()
    except ValueError:
        info = {"http": r.status_code, "text": r.text[:200]}
    log.info("S&R adres sonucu: %s", info)
    return info


SEARCH = BASE + "/product/search/results"

# "₱ 199.00" (also the broken-encoding forms of ₱ and "PHP 199.00")
_PESO_RE = re.compile(r"(?:₱|â‚±|PHP|Php)\s*([\d,]+(?:\.\d{1,2})?)")


def _first_num(text: str) -> float | None:
    m = re.search(r"[\d,]*\d(?:\.\d{1,2})?", text)
    return _num(m.group(0)) if m else None


def parse_product_page(html: str, url: str, member: bool = False) -> Product | None:
    """Reads name and price from a single product page (used for search results whose listing
    shows no price). The price is the first one after the product title, so prices of
    "related products" further down the page are ignored."""
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1 is None or not h1.get_text(strip=True):
        return None
    name = h1.get_text(" ", strip=True)
    oc = h1.find_next(class_="oc-price")
    if oc is not None:
        price = _first_num(oc.get_text())
        reg = None
        box = oc
        for _ in range(3):  # old price sits next to the current one
            box = box.parent
            if box is None:
                break
            og = box.select_one(".og-price")
            if og is not None:
                reg = _first_num(og.get_text())
                break
        if price:
            return Product(store="snr", url=url, name=name, price=price,
                           regular_price=reg if reg and reg > price else None,
                           member_price=price if member else None)
    # Plain text after the title: "Member Price ₱ x / Non-member Price ₱ y" or just "₱ x"
    after = " ".join(t.strip() for t in h1.find_all_next(string=True, limit=80) if t.strip())[:600]
    m = _MEMBER_RE.search(after)
    if m:
        mp = _num(m.group(1))
        nm = _NONMEMBER_RE.search(after)
        nmp = _num(nm.group(1)) if nm else None
        return Product(store="snr", url=url, name=name, price=mp if member or nmp is None else nmp,
                       member_price=mp, non_member_price=nmp)
    m = _PESO_RE.search(after)
    if m and _num(m.group(1)) > 0:
        price = _num(m.group(1))
        return Product(store="snr", url=url, name=name, price=price,
                       member_price=price if member else None)
    return None


def _price_from_product_pages(s, unpriced: list[Product], member: bool, seen: dict,
                              delay: float, limit: int) -> int:
    """Opens product pages for search results that showed no price. Returns how many got a price."""
    done = 0
    for p in unpriced[:limit]:
        try:
            r = s.get(p.url, timeout=30)
            r.raise_for_status()
        except requests.RequestException as e:
            log.warning("S&R product page %s: %s", p.url, e)
            continue
        got = parse_product_page(r.text, p.url, member=member)
        if got is None:
            log.warning("S&R product page: no price read for %s", p.name)
        else:
            got.name = p.name  # keep the listing name so matching stays the same
            seen[p.url] = got
            p.price, p.regular_price, p.member_price = got.price, got.regular_price, got.member_price
            done += 1
        time.sleep(delay)
    if len(unpriced) > limit:
        log.warning("S&R product pages: %d unpriced search results left (limit %d)", len(unpriced) - limit, limit)
    log.info("S&R product pages: %d of %d priced", done, min(len(unpriced), limit))
    return done


def _scan_pages(s, label: str, page_url, promo, member, seen, max_pages, delay, collect=None) -> int:
    """Walks one listing (category or search) page by page. Stops when a page brings nothing new
    for THIS listing — products already seen in another listing do not end it early."""
    here: set[str] = set()
    for page in range(1, max_pages + 1):
        url = page_url(page)
        try:
            r = s.get(url, timeout=30)
            r.raise_for_status()
        except requests.RequestException as e:
            log.warning("S&R %s: %s", url, e)
            break
        items = parse_listing(r.text, promo=promo, member=member)
        if not items and product_link_count(r.text):
            if collect is not None and page == 1:
                # Products are listed but no price could be read (different page layout or hidden
                # prices). Keep their names with price 0 so the panel shows them instead of nothing.
                collect.extend(_unpriced_links(r.text))
            log.warning("S&R %s page %d: %d product links but no prices read", label, page,
                        product_link_count(r.text))
            break
        fresh = [p for p in items if p.url not in here]
        if collect is not None:
            collect.extend(fresh)
        for p in items:
            here.add(p.url)
            # Keep the promo info when a product shows up in a normal and a promo listing
            if p.url in seen and seen[p.url].promo and not p.promo:
                continue
            seen[p.url] = p
        log.info("S&R %s page %d: %d products", label, page, len(items))
        time.sleep(delay)
        if not fresh:
            break  # end of the listing
    return len(here)


def fetch_all(member: bool = False, max_pages: int = 15, delay: float = 3.0,
              address: dict | None = None, credentials: tuple[str, str] | None = None,
              queries: list[str] | None = None, search_pages: int = 2,
              session: requests.Session | None = None,
              wanted: Callable[[str], bool] | None = None, product_pages: int = 150) -> list[Product]:
    """Category pages first, then the site's own search for every watchlist query, so products
    filed under a category we do not scan (e.g. onion powder) are still found. Search results
    that show no price and that `wanted` (the watchlist) asks for are priced from their own page."""
    s = session or requests.Session()
    s.headers.update(HEADERS)
    if credentials:
        ensure_login(s, *credentials)
    if address:
        set_delivery_address(s, address)
    seen: dict[str, Product] = {}
    for path, promo in CATEGORIES.items():
        _scan_pages(s, path.rsplit("/", 1)[-1],
                    lambda pg, path=path: f"{BASE}{path}" + (f"?page={pg}" if pg > 1 else ""),
                    promo, member, seen, max_pages, delay)
    for q in queries or []:
        before = len(seen)
        got: list[Product] = []
        n = _scan_pages(s, f"search '{q}'",
                        lambda pg, q=q: f"{SEARCH}?key={quote_plus(q)}" + (f"&page={pg}" if pg > 1 else ""),
                        None, member, seen, search_pages, delay, collect=got)
        searchlog.record("snr", q, got)
        log.info("S&R search '%s': %d results, %d not seen in categories", q, n, len(seen) - before)
    if wanted is not None:
        # Same unpriced product may come back from several searches: one object per URL,
        # so pricing it once updates every search that listed it.
        unpriced: dict[str, Product] = {}
        for (store, _q), hits in searchlog.HITS.items():
            if store != "snr":
                continue
            for i, h in enumerate(hits):
                if h.price:
                    continue
                if h.url in seen:  # priced by a category page
                    hits[i] = seen[h.url]
                elif wanted(h.name):
                    hits[i] = unpriced.setdefault(h.url, h)
        _price_from_product_pages(s, list(unpriced.values()), member, seen, delay, product_pages)
    return list(seen.values())
