from datetime import date, timedelta
from pathlib import Path

import pytest

from pricewatch import alerts
from pricewatch.db import DB
from pricewatch.matcher import load_watchlist, match
from pricewatch.models import Product
from pricewatch.stores import browser_capture, snr
from pricewatch.units import parse_size, unit_price

ROOT = Path(__file__).resolve().parents[1]
SETTINGS, ITEMS = load_watchlist(str(ROOT / "watchlist.yaml"))


# ---------- units ----------
@pytest.mark.parametrize("name,qty,unit", [
    ("McCormick Ground Cinnamon 454g", 0.454, "kg"),
    ("Samyang Ramen 4 x 130g", 0.52, "kg"),
    ("Nestlé All Purpose Cream 250mL x 6", 1.5, "L"),
    ("Bertolli Extra Virgin Olive Oil 2L", 2.0, "L"),
    ("Anchor Butter Salted 1kg", 1.0, "kg"),
    ("Century Tuna Chunks in Water 6 cans", 6, "pcs"),
])
def test_parse_size(name, qty, unit):
    s = parse_size(name)
    assert s is not None and s.unit == unit and s.qty == pytest.approx(qty)


def test_unit_price_unknown_size():
    assert unit_price(100, parse_size("Mystery Item")) is None
    assert unit_price(459, parse_size("x 454g")) == (1011.01, "₱/kg")


# ---------- matcher ----------
@pytest.mark.parametrize("name,expected", [
    ("McCormick Ground Cinnamon 454g", ["spices"]),
    ("McCormick Garlic Dip 300g", ["dips"]),
    ("Eden Cheese Original 430g", ["cheese"]),
    ("Magnolia Quickmelt Cheese 440g", ["cheese"]),
    ("Magnolia Fresh Chicken Whole", []),
    ("Nestlé All Purpose Cream 250mL", ["cream"]),
    ("Nestle Coffee-Mate Creamer 450g", []),
    ("Anchor Butter Salted 227g", ["butter"]),
    ("Dari Creme Classic 200g", ["butter"]),
    ("Del Monte Spaghetti 900g", ["pasta"]),
    ("Del Monte Spaghetti Sauce Filipino Style 1kg", []),
    ("Ideal Elbow Macaroni 400g", ["pasta"]),
    ("Wolf Blass Bilyara Shiraz 750mL", []),
])
def test_match(name, expected):
    assert match(name, ITEMS) == expected


# ---------- S&R parser ----------
def test_snr_parse_listing_non_member():
    html = (ROOT / "tests/fixtures/snr_listing.html").read_text(encoding="utf-8")
    prods = {p.name: p for p in snr.parse_listing(html, member=False)}
    assert len(prods) == 4
    cin = prods["McCormick Ground Cinnamon 454g"]
    assert cin.member_price == 459.0 and cin.non_member_price == 481.95
    assert cin.price == 481.95
    assert cin.on_sale and cin.regular_price == pytest.approx(565.95, abs=0.01)
    eden = prods["Eden Cheese Original 430g"]
    assert eden.price == 1307.25 and not eden.on_sale
    assert eden.url == "https://www.snrshopping.com/product/new-arrival/eden-cheese-original-430g"


def test_snr_parse_listing_member():
    html = (ROOT / "tests/fixtures/snr_listing.html").read_text(encoding="utf-8")
    cin = next(p for p in snr.parse_listing(html, member=True) if "Cinnamon" in p.name)
    assert cin.price == 459.0 and cin.regular_price == 539.0 and cin.sale_pct == pytest.approx(0.148, abs=0.001)


# ---------- browser JSON extractor ----------
def test_extract_products_from_json():
    body = {"data": {"items": [
        {"id": 11, "name": "McCormick Paprika 34g", "price": "₱ 89.75", "regular_price": "99.00"},
        {"id": 12, "name": "Banner", "type": "promo"},
        {"id": 13, "title": "Eden Cheese 165g", "sale_price": {"amount": 65.5}},
    ]}}
    prods = browser_capture.extract_products(body, "waltermart", "https://x.test/shop")
    assert [(p.name, p.price, p.regular_price) for p in prods] == [
        ("McCormick Paprika 34g", 89.75, 99.0), ("Eden Cheese 165g", 65.5, None)]


# ---------- alerts ----------
def _p(price, regular=None, promo=None):
    return Product(store="snr", url="u1", name="Eden Cheese Original 430g",
                   price=price, regular_price=regular, promo=promo)


def test_drop_and_low_alerts(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    today = date(2026, 10, 19)
    for i in range(10, 0, -1):
        db.record(_p(300.0), ["cheese"], today - timedelta(days=i))
    fired = alerts.evaluate(_p(240.0), db, SETTINGS, today)
    kinds = {a.kind for a in fired}
    assert kinds == {"drop", "low"}
    # the same price must not alert again the next day
    db.record(_p(240.0), ["cheese"], today)
    assert alerts.evaluate(_p(240.0), db, SETTINGS, today + timedelta(days=1)) == []


def test_small_change_no_alert(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    today = date(2026, 10, 19)
    for i in range(10, 0, -1):
        db.record(_p(300.0), ["cheese"], today - timedelta(days=i))
    assert alerts.evaluate(_p(290.0), db, SETTINGS, today) == []


def test_store_sale_and_promo(tmp_path):
    db = DB(str(tmp_path / "t.db"))
    today = date(2026, 10, 19)
    assert [a.kind for a in alerts.evaluate(_p(250.0, regular=300.0), db, SETTINGS, today)] == ["sale"]
    db2 = DB(str(tmp_path / "t2.db"))
    assert [a.kind for a in alerts.evaluate(_p(300.0, promo="buy1take1"), db2, SETTINGS, today)] == ["promo"]


def test_digest_orders_by_unit_price():
    a = Product("snr", "a", "Eden Cheese 430g", 300.0)       # ~698/kg
    b = Product("landmark", "b", "Magnolia Cheese 1kg", 600.0)  # 600/kg
    text = alerts.daily_digest([a, b], {"a": ["cheese"], "b": ["cheese"]}, ITEMS)
    sec = text.split("*Cheese*")[1]
    assert sec.index("Magnolia") < sec.index("Eden")


def test_snr_parse_survives_windows_mojibake():
    # Read as cp1252 on Windows, ₱ becomes "â‚±"; the parser must still find the price
    raw = (ROOT / "tests/fixtures/snr_listing.html").read_bytes().decode("cp1252", errors="replace")
    assert len(snr.parse_listing(raw)) == 4


# ---------- fixtures from live recon data ----------
import json
from pricewatch.stores import landmark, waltermart


def test_snr_live_members_value_page():
    html = (ROOT / "tests/fixtures/snr_members_value_live.html").read_text(encoding="utf-8")
    prods = snr.parse_listing(html)
    assert len(prods) == 24
    tur = next(p for p in prods if "Turmeric" in p.name)
    assert tur.member_price == 119.0 and tur.non_member_price == 124.95 and tur.price == 124.95


def test_snr_live_category_hidden_prices_detected():
    html = (ROOT / "tests/fixtures/snr_category_noprice_live.html").read_text(encoding="utf-8")
    assert snr.parse_listing(html) == []
    assert snr.product_link_count(html) == 30


def test_waltermart_parse_real_response():
    body = json.loads((ROOT / "tests/fixtures/waltermart_products.json").read_text(encoding="utf-8"))
    prods = waltermart.parse_products(body)
    assert len(prods) == 5                      # 2 bundles without a price skipped
    p = next(p for p in prods if "480g" in p.name)
    assert p.name == "Magnolia Cheezee Spread Pimiento 480g" and p.price == 202.0
    assert p.url.startswith("https://www.waltermartdelivery.com.ph/")
    assert match(p.name, ITEMS) == ["cheese"]


def test_waltermart_sale_price():
    body = {"items": [{"id": "1", "name": "McCormick Paprika | 34g", "unit_price": 89.0,
                       "sale_price": "75.50", "status": "available", "canonical_url": "u"}]}
    p = waltermart.parse_products(body)[0]
    assert p.price == 75.5 and p.regular_price == 89.0 and p.on_sale


def test_landmark_parse_real_response():
    body = json.loads((ROOT / "tests/fixtures/landmark_search.json").read_text(encoding="utf-8"))
    prods = {p.name: p for p in landmark.parse_search(body)}
    p = prods["Kraft Eden Cheddar Cheese 430g"]
    assert p.price == 245.0
    assert p.url.startswith("https://www.landmark.ph/products/")
    assert match("Eden Mayo with Creamy Cheese 80ml", ITEMS) == []
    assert unit_price(p.price, parse_size(p.name)) == (569.77, "₱/kg")


def test_units_gr_suffix():
    assert parse_size("Magnolia Cheese 185gr").qty == pytest.approx(0.185)


@pytest.mark.parametrize("name,qty,unit", [
    ("Nestle All Purpose Cream 250ml 24s", 6.0, "L"),
    ("Nestle All Purpose Cream 250ml x 4s", 1.0, "L"),
    ("Magnolia Dari Creme Classic 200g 2 for 99", 0.4, "kg"),
    ("Magnolia Cheezee Spread Milky White 220g Buy 2 Save 10 pesos", 0.44, "kg"),
    ("Dari Creme Classic 200g 2s Save P15", 0.4, "kg"),
    ("Nestle All Purpose Cream 2x250ml Save 15", 0.5, "L"),
    ("Ideal Gourmet Spaghetti 1kg", 1.0, "kg"),
])
def test_multipack_sizes(name, qty, unit):
    s = parse_size(name)
    assert s.unit == unit and s.qty == pytest.approx(qty)


class _Resp:
    def __init__(self, text, url):
        self.text, self.url = text, url


class _FakeSession:
    LOGIN_HTML = """<html><head><meta name="csrf-token" content="tok123"></head><body>
    <form method="POST" action="https://www.snrshopping.com/login">
      <input type="hidden" name="_token" value="tok123">
      <input type="email" name="email"><input type="password" name="password">
      <input type="checkbox" name="remember"><button>Submit</button>
    </form></body></html>"""

    def __init__(self):
        self.posted = None

    def get(self, url, **kw):
        return _Resp(self.LOGIN_HTML, url)

    def post(self, url, data=None, **kw):
        self.posted = (url, data)
        return _Resp("<a>Sign Out</a>", "https://www.snrshopping.com/")


def test_snr_login_reads_form_fields():
    s = _FakeSession()
    assert snr.login(s, "user@example.com", "pw-test") is True
    url, data = s.posted
    assert url == "https://www.snrshopping.com/login"
    assert data == {"_token": "tok123", "email": "user@example.com",
                    "password": "pw-test", "remember": "on"}


def test_snr_credentials_only_from_env(monkeypatch):
    from pricewatch import cli
    monkeypatch.delenv("SNR_EMAIL", raising=False)
    monkeypatch.delenv("SNR_PASSWORD", raising=False)
    assert cli.snr_credentials() is None
    monkeypatch.setenv("SNR_EMAIL", "a@b.c"); monkeypatch.setenv("SNR_PASSWORD", "x")
    assert cli.snr_credentials() == ("a@b.c", "x")


class _FailSession(_FakeSession):
    def post(self, url, data=None, **kw):
        self.posted = (url, data)
        body = ('<form><input type="email" name="email" value="%s"></form>'
                '<span class="invalid-feedback">These credentials do not match our records.</span>'
                % data["email"])
        return _Resp(body, "https://www.snrshopping.com/login")


def test_snr_login_failure_debug_scrubs_email(tmp_path, caplog):
    import logging
    caplog.set_level(logging.INFO)
    s = _FailSession()
    assert snr.login(s, "user@example.com", "pw-test", debug_dir=tmp_path) is False
    assert "credentials do not match" in caplog.text
    assert "pw-test" not in caplog.text and "user@example.com" not in caplog.text
    saved = (tmp_path / "login_response.html").read_text(encoding="utf-8")
    assert "user@example.com" not in saved and "<EMAIL>" in saved


def test_snr_loggedin_cards():
    html = (ROOT / "tests/fixtures/snr_loggedin_cards.html").read_text(encoding="utf-8")
    prods = {p.name: p for p in snr.parse_listing(html, promo="price-off", member=True)}
    assert len(prods) == 10
    fan = prods["Westinghouse 20-inch Stand Fan WH2715"]
    assert fan.price == 6495.0 and fan.regular_price == 7995.0 and fan.on_sale
    bbq = prods["CJ Foods Bulgogi Marinade Korean BBQ Sauce 840g"]
    assert bbq.price == 209.0 and bbq.regular_price is None and not bbq.on_sale
    assert snr.product_link_count(html) == 10


def test_units_count_word_before_x():
    s = parse_size("Heineken Pure Malt Lager Beer 6 cans x 330mL")
    assert s.unit == "L" and s.qty == pytest.approx(1.98)


def test_landmark_falls_back_to_browser(monkeypatch):
    import requests as rq

    class Blocked:
        headers = {}
        def get(self, *a, **k):
            raise rq.HTTPError("403 Forbidden")

    called = {}
    def fake_browser(queries, substore, delay):
        called["q"] = queries
        return {"u": Product("landmark", "u", "Ideal Gourmet Spaghetti 1kg", 104.75)}
    monkeypatch.setattr(landmark, "_fetch_browser", fake_browser)
    prods = landmark.fetch(["ideal spaghetti", "eden cheese"], delay=0, session=Blocked())
    assert called["q"] == ["ideal spaghetti", "eden cheese"] and prods[0].price == 104.75


def test_run_skips_stores_already_scanned_today(tmp_path, monkeypatch):
    from pricewatch import cli
    calls = []

    def fake_collect(stores, items, settings, recon_dir=None):
        calls.append(list(stores))
        out = []
        if "snr" in stores:
            out.append(Product("snr", "s1", "Eden Cheese Original 430g", 140.0))
        if "landmark" in stores:
            out.append(Product("landmark", "l1", "Kraft Eden Cheddar Cheese 430g", 245.0))
        return out

    monkeypatch.setattr(cli, "collect", fake_collect)
    monkeypatch.setattr(cli.notify, "send", lambda text: None)
    db = str(tmp_path / "p.db")
    wl = str(ROOT / "watchlist.yaml")
    cli.main(["run", "--stores", "snr", "--db", db, "--watchlist", wl])
    cli.main(["run", "--stores", "snr,landmark", "--db", db, "--watchlist", wl, "--report",
              "--report-out", str(tmp_path / "r.html")])
    assert calls == [["snr"], ["landmark"]]          # S&R not scanned a second time
    html = (tmp_path / "r.html").read_text(encoding="utf-8")
    assert "S&amp;R" in html and "Landmark" in html   # panelde ikisi de var
    cli.main(["run", "--stores", "snr", "--db", db, "--watchlist", wl, "--force"])
    assert calls[-1] == ["snr"]                       # --force re-scans


def test_digest_does_not_mix_units():
    a = Product("snr", "a", "Nestle All Purpose Cream 2pcs", 124.5)          # ₱/pcs
    b = Product("waltermart", "b", "Nestle All Purpose Cream 250ml x 2s", 126.5)
    c = Product("snr", "c", "Nestle All Purpose Cream 250mL", 69.75)
    g = {"a": ["cream"], "b": ["cream"], "c": ["cream"]}
    sec = alerts.daily_digest([a, b, c], g, ITEMS).split("*All-Purpose Cream*")[1].split("\n\n")[0]
    assert "pcs" not in sec and sec.index("250ml x 2s") < sec.index("250mL")


@pytest.mark.parametrize("name,expected", [
    ("Magnolia Chicken Breast Fillet 1kg", ["chicken"]),
    ("Bounty Fresh Whole Chicken approx 1.2kg", ["chicken"]),
    ("McCormick Chicken Gravy Seasoning Mix 28g", ["spices"]),   # not raw chicken
    ("Monterey Pork Belly Liempo per kg", ["pork"]),
    ("Purefoods Pork Luncheon Meat 340g", []),
    ("Ground Beef Approx. 1kg", ["beef"]),
    ("Purefoods Corned Beef 210g", []),
    ("Joy Dishwashing Liquid Lemon 1L", ["dishwashing"]),
    ("Zonrox Bleach Original 1L", ["bleach"]),
    ("Champion Garbage Bag Large 10pcs", ["trashbags"]),
    ("Tisyu Table Napkin 100 sheets", ["paper"]),
    ("Paper Cup 12oz with Lid 50pcs", ["cups"]),
    ("Nissin Cup Noodles Seafood 60g", []),
])
def test_new_categories(name, expected):
    assert match(name, ITEMS) == expected


def test_every_item_has_category():
    cats = {it.category for it in ITEMS}
    assert {"Dairy", "Chicken", "Pork", "Beef", "Cleaning", "Café Supplies"} <= cats


def test_panel_has_search_and_chips(tmp_path):
    from pricewatch import report
    db = DB(str(tmp_path / "p.db"))
    d = date(2026, 10, 19)
    db.record(Product("landmark", "l1", "Kraft Eden Cheddar Cheese 430g", 245.0), ["cheese"], d)
    db.record(Product("snr", "s1", "Zonrox Bleach Original 1L", 59.0, regular_price=69.0), ["bleach"], d)
    db.commit()
    html = report.render(report.load(str(tmp_path / "p.db")), ITEMS)
    assert 'id="q"' in html and 'data-c="cleaning"' in html and 'data-c="dairy"' in html
    assert 'data-q="zonrox bleach original 1l s&amp;r bleach cleaning"' in html
    assert "On sale today" in html and "Search a product or brand" in html


class _NetResp:
    def __init__(self, status, body=None):
        self.status_code, self._b, self.ok = status, body or {}, status < 400
    def json(self):
        return self._b
    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(self.status_code)


class _NetSession:
    def __init__(self):
        self.posts, self.puts = [], []
    def post(self, url, json=None, data=None, headers=None, timeout=None):
        self.posts.append((url, json, headers))
        if url.endswith("/sites"):
            return _NetResp(201, {"id": "site-123", "ssl_url": "https://bns-price-watch.netlify.app"})
        # Netlify answers with the digests it still needs (here: only index.html)
        return _NetResp(200, {"id": "dep-1", "name": "bns-price-watch",
                              "required": [json["files"]["/index.html"]]})
    def put(self, url, data=None, headers=None, timeout=None):
        self.puts.append((url, data, headers))
        return _NetResp(200)


def test_netlify_alias_deploy_never_production(tmp_path):
    import hashlib
    from pricewatch import netlify
    html = tmp_path / "p.html"; html.write_text("<h1>Price Watch</h1>", encoding="utf-8")
    s = _NetSession()
    url = netlify.deploy(str(html), "tok", "site-123", session=s)
    assert url == "https://panel--bns-price-watch.netlify.app"
    deploy_url, body, headers = s.posts[0]
    assert deploy_url.endswith("/sites/site-123/deploys") and headers["Authorization"] == "Bearer tok"
    assert body["draft"] is True and body["branch"] == "panel"          # alias deploy, not production
    assert set(body["files"]) == {"/index.html", "/robots.txt", "/_headers"}
    assert body["files"]["/index.html"] == hashlib.sha1(b"<h1>Price Watch</h1>").hexdigest()
    assert [u for u, _, _ in s.puts] == ["https://api.netlify.com/api/v1/deploys/dep-1/files/index.html"]


def test_publish_reuses_saved_site_id(tmp_path, monkeypatch):
    from pricewatch import cli, netlify
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NETLIFY_AUTH_TOKEN", "tok"); monkeypatch.delenv("NETLIFY_SITE_ID", raising=False)
    created, deployed = [], []
    monkeypatch.setattr(netlify, "create_site", lambda token, **k: created.append(1) or {"id": "site-9"})
    monkeypatch.setattr(netlify, "deploy", lambda path, token, sid, **k: deployed.append(sid) or "https://x.netlify.app")
    (tmp_path / "p.html").write_text("x")
    cli.publish_netlify("p.html"); cli.publish_netlify("p.html")
    assert created == [1] and deployed == ["site-9", "site-9"]   # site created once, reused after
