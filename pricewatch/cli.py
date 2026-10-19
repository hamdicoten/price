"""Usage:
  python -m pricewatch.cli run                 # scan, store prices, send alerts
  python -m pricewatch.cli run --digest        # + send the daily digest
  python -m pricewatch.cli run --report        # + write reports/price-watch.html
  python -m pricewatch.cli report              # rebuild the panel from stored prices
  python -m pricewatch.cli publish             # rebuild the panel and deploy it to Netlify
  python -m pricewatch.cli recon               # save raw pages/JSON to recon/ for debugging
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path

from . import __version__, alerts, notify
from .db import DB
from .matcher import load_watchlist, match
from .models import Product, WatchItem


def search_queries(items: list[WatchItem]) -> list[str]:
    qs: list[str] = []
    for it in items:
        if it.queries:
            qs += [q for q in it.queries if q not in qs]
            continue
        for b in it.brands:
            q = f"{b} {it.keywords[0]}" if it.keywords else b
            if q not in qs:
                qs.append(q)
    return qs


def snr_credentials() -> tuple[str, str] | None:
    """Credentials are read ONLY from environment variables (Secret/Vault on k3s)."""
    email, pw = os.getenv("SNR_EMAIL"), os.getenv("SNR_PASSWORD")
    return (email, pw) if email and pw else None


def publish_netlify(html_path: str) -> None:
    """Deploys the panel; a failure is logged but never breaks the scan."""
    token = os.getenv("NETLIFY_AUTH_TOKEN")
    if not token:
        logging.warning("Netlify: NETLIFY_AUTH_TOKEN not set, panel not published")
        return
    from . import netlify
    id_file = Path("data/netlify-site-id.txt")   # remembers the site so every run updates the same URL
    site_id = os.getenv("NETLIFY_SITE_ID") or (id_file.read_text().strip() if id_file.exists() else None)
    try:
        if not site_id:
            site_id = netlify.create_site(token)["id"]
            id_file.parent.mkdir(parents=True, exist_ok=True)
            id_file.write_text(site_id)
        url = netlify.deploy(html_path, token, site_id)
        logging.info("Panel online → %s", url)
    except Exception as e:  # noqa: BLE001
        logging.error("Netlify publish failed: %s", e)


def collect(stores: list[str], items: list[WatchItem], settings: dict,
            recon_dir: Path | None = None) -> list[Product]:
    products: list[Product] = []
    if "snr" in stores:
        from .stores import snr
        creds = snr_credentials()
        addr = settings.get("snr_address") or {}
        if recon_dir:
            import requests
            d = recon_dir / "snr"
            d.mkdir(parents=True, exist_ok=True)
            s = requests.Session()
            s.headers.update(snr.HEADERS)
            if creds:
                snr.ensure_login(s, *creds, debug_dir=d)
            else:
                logging.info("S&R: SNR_EMAIL/SNR_PASSWORD not set, trying without login")
            if any(addr.values()):
                snr.set_delivery_address(s, addr)
            for path in snr.CATEGORIES:
                name = path.rsplit("/", 1)[-1]
                try:
                    r = s.get(snr.BASE + path, timeout=30)
                except requests.RequestException as e:
                    logging.error("S&R recon %s: %s", name, e)
                    continue
                (d / f"{name}.html").write_text(r.text, encoding="utf-8")
                parsed = snr.parse_listing(r.text)
                logging.info("S&R recon %s: HTTP %s, %d products parsed (%d product links)",
                             name, r.status_code, len(parsed), snr.product_link_count(r.text))
        else:
            products += snr.fetch_all(member=settings.get("snr_member", False),
                                      address=addr if any(addr.values()) else None,
                                      credentials=creds)
    qs = search_queries(items)
    if recon_dir:
        from .stores import browser_capture
        for st in [s for s in stores if s in ("waltermart", "landmark")]:
            browser_capture.search(st, qs, recon_dir=recon_dir)
        return products
    # If one store fails, the others still run
    if "waltermart" in stores:
        from .stores import waltermart
        try:
            products += waltermart.fetch(qs, store_id=str(settings.get("waltermart_store_id",
                                                                       waltermart.DEFAULT_STORE_ID)))
        except Exception as e:
            logging.error("WalterMart scan failed: %s", e)
    if "landmark" in stores:
        from .stores import landmark
        try:
            products += landmark.fetch(qs, substore=settings.get("landmark_substore", "mkt"))
        except Exception as e:
            logging.error("Landmark scan failed: %s", e)
    return products


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="pricewatch")
    ap.add_argument("command", choices=["run", "recon", "report", "publish"])
    ap.add_argument("--stores", default="snr,waltermart,landmark")
    ap.add_argument("--watchlist", default="watchlist.yaml")
    ap.add_argument("--db", default="data/prices.db")
    ap.add_argument("--recon-dir", default="recon")
    ap.add_argument("--digest", action="store_true", help="also send the daily digest")
    ap.add_argument("--report", action="store_true", help="also write the HTML panel after the scan")
    ap.add_argument("--report-out", default="reports/price-watch.html")
    ap.add_argument("--force", action="store_true", help="re-scan stores already scanned today")
    ap.add_argument("--publish", action="store_true",
                    help="after --report, deploy the panel to Netlify (needs NETLIFY_AUTH_TOKEN)")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):  # keep ₱ and accents intact in the Windows console
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)
    logging.info("pricewatch v%s", __version__)
    settings, items = load_watchlist(args.watchlist)
    stores = [s.strip() for s in args.stores.split(",") if s.strip()]

    if args.command == "report":
        from . import report
        logging.info("Panel written → %s", report.write(args.db, items, args.report_out))
        return

    if args.command == "publish":
        from . import report
        report.write(args.db, items, args.report_out)
        publish_netlify(args.report_out)
        return

    if args.command == "recon":
        collect(stores, items, settings, recon_dir=Path(args.recon_dir))
        logging.info("Recon done → share the %s/ folder", args.recon_dir)
        return

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    db = DB(args.db)
    today = date.today()

    # Do not re-scan stores already scanned today; reuse their stored prices
    done = set() if args.force else db.stores_done(today) & set(stores)
    if done:
        logging.info("Already scanned today, using stored prices: %s "
                     "(use --force to re-scan)", ", ".join(sorted(done)))
    to_fetch = [s for s in stores if s not in done]
    found = collect(to_fetch, items, settings) if to_fetch else []

    tracked: list[Product] = []
    groups_of: dict[str, list[str]] = {}
    for p, g in db.products_on(today, done):
        tracked.append(p)
        groups_of[p.url] = g
    reused = len(tracked)
    for p in found:
        g = match(p.name, items)
        if g:
            tracked.append(p)
            groups_of[p.url] = g
    logging.info("%d products scanned, %d matched the watchlist (+%d stored)",
                 len(found), len(tracked) - reused, reused)

    fired: list[alerts.Alert] = []
    for p in tracked[reused:]:  # alerts for stored ones were raised on the first scan
        fired += alerts.evaluate(p, db, settings, today)  # check history first…
        db.record(p, groups_of[p.url], today)               # …then store today
    db.commit()

    notify.send(alerts.format_alerts(fired, groups_of, items))
    if args.digest:
        notify.send(alerts.daily_digest(tracked, groups_of, items))
    if args.report or args.publish:
        from . import report
        logging.info("Panel written → %s", report.write(args.db, items, args.report_out))
    if args.publish:
        publish_netlify(args.report_out)


if __name__ == "__main__":
    main()
