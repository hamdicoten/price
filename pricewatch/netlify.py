"""Publishes the panel to Netlify through its deploy API (no Netlify CLI or Node needed).

CREDITS: on Netlify's credit-based plans every PRODUCTION deploy costs 15 credits and the Free
plan has a hard 300-credit monthly limit — when it runs out, ALL sites on the account are paused.
A daily production deploy (~450 credits/month) would do exactly that. So the panel is deployed as
a branch/alias deploy (same method as `netlify deploy --alias`), which does not consume deploy
credits, and is served at https://<alias>--<site>.netlify.app. Production is left untouched.

Needs NETLIFY_AUTH_TOKEN (Netlify → User settings → Applications → Personal access tokens) and
NETLIFY_SITE_ID (otherwise the first run creates a site and stores its id in data/netlify-site-id.txt).
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from pathlib import Path

import requests

log = logging.getLogger(__name__)
API = "https://api.netlify.com/api/v1"
DEFAULT_ALIAS = "panel"

# Keep the page out of search engines; access itself is controlled by the site's protection.
ROBOTS = "User-agent: *\nDisallow: /\n"
HEADERS_FILE = "/*\n  X-Robots-Tag: noindex, nofollow\n  Referrer-Policy: no-referrer\n"


def site_files(html_path: str) -> dict[str, bytes]:
    return {
        "/index.html": Path(html_path).read_bytes(),
        "/robots.txt": ROBOTS.encode(),
        "/_headers": HEADERS_FILE.encode(),
    }


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "User-Agent": "BrewAndSavour-PriceWatch"}


def _check(r, site_id: str):
    if r.status_code == 401:
        raise RuntimeError("Netlify rejected the token (401). Create a new personal access token.")
    if r.status_code == 404:
        raise RuntimeError(f"Netlify site {site_id} not found (404). Check NETLIFY_SITE_ID.")
    r.raise_for_status()


def create_site(token: str, name: str | None = None, session=None) -> dict:
    s = session or requests
    name = name or f"bns-price-watch-{secrets.token_hex(3)}"
    r = s.post(f"{API}/sites", json={"name": name}, headers=_auth(token), timeout=60)
    r.raise_for_status()
    site = r.json()
    log.info("Netlify site created: %s (%s)", site.get("ssl_url") or site.get("url"), site["id"])
    return site


def deploy(html_path: str, token: str, site_id: str | None = None, session=None,
           alias: str = DEFAULT_ALIAS) -> str:
    """Uploads the panel as an alias (branch) deploy — no production-deploy credits.
    Returns the alias URL."""
    s = session or requests
    if not site_id:
        site_id = create_site(token, session=session)["id"]
    files = site_files(html_path)
    digests = {path: hashlib.sha1(body).hexdigest() for path, body in files.items()}

    # 1) announce the files; Netlify answers with the digests it does not have yet
    r = s.post(f"{API}/sites/{site_id}/deploys", headers=_auth(token), timeout=60,
               json={"files": digests, "draft": True, "branch": alias, "title": "Price Watch panel"})
    _check(r, site_id)
    d = r.json()
    required = set(d.get("required") or [])

    # 2) upload only what is missing
    for path, body in files.items():
        if digests[path] in required:
            u = s.put(f"{API}/deploys/{d['id']}/files{path}", data=body, timeout=120,
                      headers={**_auth(token), "Content-Type": "application/octet-stream"})
            _check(u, site_id)

    url = ((d.get("links") or {}).get("alias")
           or (f"https://{alias}--{d['name']}.netlify.app" if d.get("name") else d.get("deploy_ssl_url", "")))
    log.info("Netlify alias deploy (no production credits): %s", url)
    return url
