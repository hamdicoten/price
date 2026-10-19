"""Builds a single-file HTML panel from the price database (reports/price-watch.html)."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from html import escape
from statistics import median

from .compare import cross_store_pairs
from .models import WatchItem
from .units import parse_size, unit_price

STORE_NAMES = {"snr": "S&R", "waltermart": "WalterMart", "landmark": "Landmark"}
STORE_DETAIL = {"snr": "member account", "waltermart": "Mabalacat branch", "landmark": "Makati"}
STORE_URLS = {"snr": "https://www.snrshopping.com", "waltermart": "https://www.waltermartdelivery.com.ph",
              "landmark": "https://www.landmark.ph"}
KIND_LABEL = {"sale": "Store discount", "promo": "Buy 1 Take 1", "drop": "Below 30-day median",
              "low": "Lowest price yet"}


def _peso(v: float) -> str:
    return f"₱{v:,.2f}"


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _unit(price: float, name: str):
    return unit_price(price, parse_size(name))


def _unit_label(up) -> str:
    if not up:
        return "—"
    v, lbl = up
    return (f"₱{v:,.0f}" if v >= 10 else f"₱{v:,.2f}") + lbl[1:]


def load(db_path: str) -> dict:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    last = con.execute("SELECT max(day) FROM prices").fetchone()[0]
    if not last:
        return {"empty": True}
    days = con.execute("SELECT count(DISTINCT day) FROM prices").fetchone()[0]
    rows = [dict(r) for r in con.execute(
        """SELECT p.url, p.store, p.name, p.groups, pr.price, pr.regular_price, pr.promo
           FROM prices pr JOIN products p USING(url) WHERE pr.day = ?""", (last,))]
    for r in rows:
        r["groups"] = [g for g in (r["groups"] or "").split(",") if g]
        hist = [x[0] for x in con.execute(
            "SELECT price FROM prices WHERE url=? AND day<? ORDER BY day DESC LIMIT 30", (r["url"], last))]
        r["median30"] = median(hist) if hist else None
    alerts = [dict(r) for r in con.execute(
        """SELECT a.kind, a.price, p.name, p.store, p.url, p.groups FROM alerts a JOIN products p USING(url)
           WHERE a.day = ? ORDER BY a.kind""", (last,))]
    for a in alerts:
        a["groups"] = [g for g in (a["groups"] or "").split(",") if g]
    searches: dict[tuple[str, str], list[dict]] = {}
    try:
        for r in con.execute("""SELECT store, query, pos, url, name, price FROM search_hits
                                WHERE day=? ORDER BY store, query, pos""", (last,)):
            lst = searches.setdefault((r["store"], r["query"]), [])
            if r["pos"] >= 0:
                lst.append({"url": r["url"], "name": r["name"], "price": r["price"]})
    except sqlite3.OperationalError:
        pass  # database from before search logging
    return {"empty": False, "day": date.fromisoformat(last), "days": days, "rows": rows, "alerts": alerts,
            "searches": searches}


CSS = """
/* Layout: one column, summary before detail. Stores → numbers → search & filters (sticky)
   → alerts → on sale → same product, different price → cheapest per group → all products */
:root{
  --bg:#F5EEE3; --surface:#FBF7F0; --line:#E3D7C5; --ink:#2A1C14; --muted:#6B5A4C;
  --accent:#A24A26; --accent-soft:#F3DCCB; --accent-ink:#5C2A13; --good:#2F6B45; --good-soft:#DCEBDF;
  --display:"Fraunces", Georgia, "Times New Roman", serif;
  --body:"Inter", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono:"IBM Plex Mono", ui-monospace, "Cascadia Mono", Consolas, monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#1C140F; --surface:#271D16; --line:#3C2E24; --ink:#F2E8DA; --muted:#BCA994;
  --accent:#E58C61; --accent-soft:#4A2A1C; --accent-ink:#F7D3BF; --good:#8FCB9F; --good-soft:#1F3627;
  color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#1C140F; --surface:#271D16; --line:#3C2E24; --ink:#F2E8DA; --muted:#BCA994;
  --accent:#E58C61; --accent-soft:#4A2A1C; --accent-ink:#F7D3BF; --good:#8FCB9F; --good-soft:#1F3627;
  color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:400 15px/1.55 var(--body)}
body::before{content:"";position:fixed;inset:0 0 auto;height:env(safe-area-inset-top,0px);z-index:10;background:var(--bg)}
.wrap{max-width:1180px;margin:0 auto;padding-block:36px 64px;
  padding-left:max(16px, env(safe-area-inset-left, 0px));padding-right:max(16px, env(safe-area-inset-right, 0px));
  display:flex;flex-direction:column;gap:32px}
header{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:12px 24px;
  padding-bottom:22px;border-bottom:1px solid var(--line)}
.eyebrow{margin:0;font:500 12px/1.4 var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
h1{margin:4px 0 0;font:600 clamp(34px,6vw,48px)/1.05 var(--display);letter-spacing:-.01em}
h2{margin:0;font:600 24px/1.2 var(--display);text-wrap:balance}
.meta{margin:0;color:var(--muted);font-size:14px}
.section{display:flex;flex-direction:column;gap:14px;min-width:0}
.section-head{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:6px 16px}
.hint{color:var(--muted);font-size:14px}
.stores{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.store{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px;
  display:flex;flex-direction:column;gap:4px}
.store b{font-weight:600}
.store span{color:var(--muted);font-size:14px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}
.stat{padding:16px 18px;border-radius:12px;border:1px solid var(--line);display:flex;flex-direction:column;gap:2px;min-width:0}
.stat .n{font:600 34px/1.1 var(--display);font-variant-numeric:tabular-nums}
.stat .l{font-size:13px;color:var(--muted)}
.stat.lead{background:var(--ink);border-color:var(--ink);color:var(--bg)}
.stat.lead .l{color:var(--bg);opacity:.8}
.toolbar{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;background:var(--bg);
  padding-block:12px;margin-block:-12px;display:flex;flex-direction:column;gap:10px;border-bottom:1px solid var(--line)}
.search{display:flex;align-items:center;gap:10px;background:var(--surface);border:1px solid var(--line);
  border-radius:999px;padding:0 16px;min-height:48px}
.search:focus-within{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
.search svg{flex:none;color:var(--muted)}
.search input{flex:1;min-width:0;border:0;background:transparent;color:var(--ink);font:400 16px/1.4 var(--body);outline:0;padding:12px 0}
.search input::placeholder{color:var(--muted)}
.search button{border:0;background:transparent;color:var(--muted);font:500 13px var(--body);cursor:pointer;
  min-height:44px;padding:0 4px}
.chips{display:flex;gap:8px;overflow-x:auto;padding-bottom:2px;scrollbar-width:thin}
.chip-btn{flex:none;min-height:36px;padding:0 14px;border-radius:999px;border:1px solid var(--line);
  background:var(--surface);color:var(--ink);font:500 13px/1 var(--body);cursor:pointer;white-space:nowrap}
.chip-btn small{font:400 12px var(--mono);color:var(--muted);margin-left:6px}
.chip-btn[aria-pressed="true"]{background:var(--ink);border-color:var(--ink);color:var(--bg)}
.chip-btn[aria-pressed="true"] small{color:var(--bg);opacity:.75}
.chip-btn:focus-visible,.search button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.result{font-size:13px;color:var(--muted);min-height:1.2em}
.box{background:var(--surface);border:1px solid var(--line);border-radius:12px;overflow-x:auto}
table{width:100%;border-collapse:collapse;min-width:640px}
th{font:500 11.5px/1.3 var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--muted);
  text-align:left;padding:12px 16px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:11px 16px;border-bottom:1px solid var(--line);vertical-align:top}
tbody tr:last-child td{border-bottom:0}
.num{text-align:right;font-family:var(--mono);font-variant-numeric:tabular-nums;white-space:nowrap}
.old{color:var(--muted);text-decoration:line-through}
.win{background:var(--good-soft);color:var(--good);font-weight:600}
.chip{display:inline-block;font:500 12px/1.4 var(--mono);padding:2px 9px;border-radius:999px;
  background:var(--accent-soft);color:var(--accent-ink);white-space:nowrap}
.chip.store{background:transparent;border:1px solid var(--line);color:var(--muted)}
.cat{color:var(--muted);font-size:13px;white-space:nowrap}
.gap{color:var(--accent);font-weight:600}
a{color:var(--accent)} a:hover{text-decoration-thickness:2px}
a:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:3px}
.groups{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
.group{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:16px 18px;
  display:flex;flex-direction:column;gap:10px;min-width:0}
.group h3{margin:0;font:600 16px/1.3 var(--body);display:flex;justify-content:space-between;gap:8px}
.group h3 small{font:400 12px/1.6 var(--mono);color:var(--muted);white-space:nowrap}
.group .gcat{font:500 11px/1.3 var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.group ol{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:8px}
.group li{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;align-items:baseline}
.group .u{font:600 15px/1.3 var(--mono);font-variant-numeric:tabular-nums;white-space:nowrap}
.group li:first-child .u{color:var(--accent);font-size:18px;font-family:var(--display)}
.group .p{min-width:0;font-size:14px}
.group .w{grid-column:2;color:var(--muted);font-size:13px}
.group .none{margin:0;color:var(--muted);font-size:14px}
.empty{background:var(--surface);border:1px dashed var(--line);border-radius:12px;padding:18px 20px;
  display:flex;flex-direction:column;gap:6px}
.empty p{margin:0;max-width:68ch}
.empty p+p{color:var(--muted)}
.no-hits{margin:0;padding:16px;color:var(--muted)}
.section.lifted .section-head h2::after{content:" · search results";font:500 14px var(--body);color:var(--muted)}
footer{border-top:1px solid var(--line);padding-top:14px;color:var(--muted);font-size:13px}
@media (prefers-reduced-motion: no-preference){.search,.chip-btn{transition:background .15s,border-color .15s,box-shadow .15s}}
"""

JS = """
(function(){
  var input=document.getElementById('q'), clear=document.getElementById('q-clear');
  var chips=[].slice.call(document.querySelectorAll('.chip-btn')), result=document.getElementById('result');
  var items=[].slice.call(document.querySelectorAll('[data-cat]'));
  var sections=[].slice.call(document.querySelectorAll('[data-filterable]'));
  var cat='all';
  try{ var saved=localStorage.getItem('pw-cat'); if(saved && document.querySelector('.chip-btn[data-c="'+saved+'"]')) cat=saved; }catch(e){}
  // lower-case, drop accents, and ignore apostrophes/quotes so "Member's" finds "Member’s"
  function norm(s){return (s||'').toLowerCase().normalize('NFKD').replace(/[\\u0300-\\u036f]/g,'')
    .replace(/[\\u2018\\u2019\\u201a\\u201b\\u2032\\u00b4`'"\\u201c\\u201d]/g,'');}
  // While a search is typed, the product list moves right under the search box; it goes back when cleared.
  var allSec=document.getElementById('all-products'), toolbar=document.querySelector('.toolbar');
  var home=allSec?{parent:allSec.parentNode, next:allSec.nextSibling}:null, lifted=false;
  function place(searching){
    if(!allSec||!toolbar||searching===lifted) return;
    if(searching){ toolbar.parentNode.insertBefore(allSec, toolbar.nextSibling); }
    else { home.parent.insertBefore(allSec, home.next); }
    allSec.classList.toggle('lifted', searching); lifted=searching;
  }
  function apply(){
    var q=norm(input.value).trim(), terms=q?q.split(/\\s+/):[], shown=0, products=0;
    items.forEach(function(el){
      var okCat = cat==='all' || el.getAttribute('data-cat').split('|').indexOf(cat)>-1;
      var hay = el._hay || (el._hay = norm(el.getAttribute('data-q')));
      var okQ = terms.every(function(t){return hay.indexOf(t)>-1;});
      el.hidden = !(okCat && okQ);
      if(!el.hidden && el.hasAttribute('data-product')) products++;
    });
    sections.forEach(function(sec){
      var any=[].some.call(sec.querySelectorAll('[data-cat]'),function(el){return !el.hidden;});
      var msg=sec.querySelector('.no-hits'); if(msg) msg.hidden=any;
      var box=sec.querySelector('.box'); if(box) box.hidden=!any;
    });
    chips.forEach(function(c){c.setAttribute('aria-pressed', c.getAttribute('data-c')===cat?'true':'false');});
    clear.hidden=!input.value;
    place(!!q);
    result.textContent = (q||cat!=='all') ? products+' tracked product'+(products===1?'':'s')+' match' : '';
  }
  chips.forEach(function(c){c.addEventListener('click',function(){cat=c.getAttribute('data-c');
    try{localStorage.setItem('pw-cat',cat);}catch(e){} apply();});});
  input.addEventListener('input',apply);
  clear.addEventListener('click',function(){input.value='';input.focus();apply();});
  document.addEventListener('keydown',function(e){
    if(e.key==='/' && document.activeElement!==input){e.preventDefault();input.focus();}
    if(e.key==='Escape' && document.activeElement===input){input.value='';apply();}
  });
  apply();
})();
"""

SEARCH_ICON = ('<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
               'stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/>'
               '<path d="m20 20-3.5-3.5"/></svg>')


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-")


def render(data: dict, items: list[WatchItem], generated: datetime | None = None) -> str:
    generated = generated or datetime.now()
    head = ('<title>Price Watch</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n'
            '<meta name="robots" content="noindex, nofollow">\n'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600'
            '&amp;family=Inter:wght@400;500;600&amp;family=IBM+Plex+Mono:wght@400;500&amp;display=swap">\n'
            f"<style>{CSS}</style>\n")
    if data.get("empty"):
        return head + ('<div class="wrap"><header><div><p class="eyebrow">Brew &amp; Savour · Capas, Tarlac</p>'
                       '<h1>Price Watch</h1></div></header><div class="empty"><p>No scans yet.</p>'
                       '<p>Run the first scan with <code>.\\run.ps1</code>; this page fills in afterwards.</p></div></div>')

    rows, day = data["rows"], data["day"]
    item_by_id = {it.id: it for it in items}
    categories = list(dict.fromkeys(it.category for it in items))

    def cats_of(groups):
        return sorted({item_by_id[g].category for g in groups if g in item_by_id}, key=categories.index)

    def attrs(name, store, groups, product=False):
        cs = cats_of(groups)
        q = " ".join([name, STORE_NAMES.get(store, store)] + [item_by_id[g].name for g in groups if g in item_by_id] + cs)
        return (f' data-cat="{escape("|".join(_slug(c) for c in cs) or "other")}"'
                f' data-q="{escape(q.lower())}"' + (' data-product' if product else ""))

    def store_chip(s):
        return f'<span class="chip store">{escape(STORE_NAMES.get(s, s))}</span>'

    def link(url, name):
        return f'<a href="{escape(url)}" target="_blank" rel="noopener">{escape(name)}</a>'

    stores_seen = sorted({r["store"] for r in rows}, key=lambda s: list(STORE_NAMES).index(s) if s in STORE_NAMES else 9)
    on_sale = sorted([r for r in rows if r["regular_price"] and r["regular_price"] > r["price"]],
                     key=lambda r: -(1 - r["price"] / r["regular_price"]))
    b1t1 = [r for r in rows if r["promo"] == "buy1take1" and r not in on_sale]
    pairs = [p for p in cross_store_pairs(rows) if p["gap"] > 0.005]
    biggest = pairs[0] if pairs else None

    out = [head, '<div class="wrap">']
    out.append('<header><div><p class="eyebrow">Brew &amp; Savour · Capas, Tarlac</p><h1>Price Watch</h1></div>'
               f'<p class="meta">Last scan {day:%d %B %Y} · {data["days"]} day{"s" if data["days"] != 1 else ""} of price history</p></header>')

    # Stores
    out.append('<section class="stores" aria-label="Stores">')
    for s in stores_seen:
        n = sum(r["store"] == s for r in rows)
        ns = sum(r["store"] == s for r in on_sale)
        out.append(f'<div class="store"><b>{escape(STORE_NAMES.get(s, s))}</b>'
                   f'<span>{escape(STORE_DETAIL.get(s, ""))} · {n} tracked product{"s" if n != 1 else ""}'
                   f'{f" · {ns} on sale" if ns else ""}</span></div>')
    out.append('</section>')

    # Numbers
    out.append('<section class="stats" aria-label="Summary">')
    if biggest:
        out.append(f'<div class="stat lead"><span class="l">Biggest gap between stores</span>'
                   f'<span class="n">{_pct(biggest["gap"])}</span>'
                   f'<span class="l">{escape(biggest["cheap"]["name"])}</span></div>')
    out.append(f'<div class="stat"><span class="l">Tracked products</span><span class="n">{len(rows)}</span>'
               f'<span class="l">{len(categories)} categories · {len(stores_seen)} stores</span></div>')
    out.append(f'<div class="stat"><span class="l">On sale today</span><span class="n">{len(on_sale) + len(b1t1)}</span>'
               f'<span class="l">store discounts and Buy 1 Take 1</span></div>')
    hist_note = (f"history building · day {data['days']} of 7" if data["days"] < 7 else "all alert rules active")
    out.append(f'<div class="stat"><span class="l">Alerts today</span><span class="n">{len(data["alerts"])}</span>'
               f'<span class="l">{hist_note}</span></div>')
    out.append('</section>')

    # Search + category filters
    counts = {c: 0 for c in categories}
    for r in rows:
        for c in cats_of(r["groups"]):
            counts[c] += 1
    out.append('<section class="toolbar" aria-label="Search and filter">'
               f'<label class="search" for="q">{SEARCH_ICON}'
               '<input id="q" type="search" placeholder="Search a product or brand — e.g. eden, chicken breast, zonrox" '
               'autocomplete="off" spellcheck="false">'
               '<button type="button" id="q-clear" hidden>Clear</button></label>'
               '<div class="chips" role="group" aria-label="Category">'
               f'<button type="button" class="chip-btn" data-c="all" aria-pressed="true">All<small>{len(rows)}</small></button>')
    for c in categories:
        out.append(f'<button type="button" class="chip-btn" data-c="{_slug(c)}" aria-pressed="false">'
                   f'{escape(c)}<small>{counts[c]}</small></button>')
    out.append('</div><p class="result" id="result" aria-live="polite"></p></section>')

    # Coverage: group x store, so missing items are visible
    cov = {it.id: {s: 0 for s in stores_seen} for it in items}
    for r in rows:
        for g in r["groups"]:
            if g in cov and r["store"] in cov[g]:
                cov[g][r["store"]] += 1
    gaps = sum(1 for g in cov.values() for n in g.values() if n == 0)
    out.append('<section class="section" aria-labelledby="h-cov" data-filterable><div class="section-head">'
               '<h2 id="h-cov">Coverage check</h2>'
               f'<span class="hint">Products found per group and store · {gaps} gap{"s" if gaps != 1 else ""} — '
               'a gap means the store may not sell it, or the scan missed it</span></div>'
               '<div class="box"><table><thead><tr><th>Group</th><th>Category</th>'
               + "".join(f'<th class="num">{escape(STORE_NAMES.get(s, s))}</th>' for s in stores_seen)
               + '</tr></thead><tbody>')
    for it in items:
        cells = "".join(
            f'<td class="num">{cov[it.id][s]}</td>' if cov[it.id][s]
            else '<td class="num"><span class="chip">missing</span></td>' for s in stores_seen)
        q = f"{it.name} {it.category} " + " ".join(STORE_NAMES.get(s, s) for s in stores_seen if not cov[it.id][s])
        out.append(f'<tr data-cat="{_slug(it.category)}" data-q="{escape(q.lower())}">'
                   f'<td>{escape(it.name)}</td><td class="cat">{escape(it.category)}</td>{cells}</tr>')
    out.append('</tbody></table></div><p class="no-hits" hidden>No groups match this filter.</p></section>')

    # Alerts
    out.append('<section class="section" aria-labelledby="h-al" data-filterable><div class="section-head">'
               '<h2 id="h-al">Alerts</h2><span class="hint">What went to Telegram this morning</span></div>')
    if data["alerts"]:
        out.append('<div class="box"><table><thead><tr><th>Product</th><th>Store</th><th>Reason</th>'
                   '<th class="num">Price</th></tr></thead><tbody>')
        for a in data["alerts"]:
            out.append(f'<tr{attrs(a["name"], a["store"], a["groups"])}><td>{link(a["url"], a["name"])}</td>'
                       f'<td>{store_chip(a["store"])}</td><td><span class="chip">{escape(KIND_LABEL.get(a["kind"], a["kind"]))}</span></td>'
                       f'<td class="num">{_peso(a["price"])}</td></tr>')
        out.append('</tbody></table></div><p class="no-hits" hidden>No alerts match this filter.</p>')
    else:
        out.append('<div class="empty"><p>No alerts on your watchlist today.</p>'
                   '<p>Store discounts and Buy 1 Take 1 are caught from day one. "Below 30-day median" and '
                   '"lowest price yet" alerts start once a product has 7 days of history.</p></div>')
    out.append('</section>')

    # On sale today
    if on_sale or b1t1:
        out.append('<section class="section" aria-labelledby="h-sale" data-filterable><div class="section-head">'
                   '<h2 id="h-sale">On sale today</h2><span class="hint">The store\'s own discount, on your watchlist</span></div>'
                   '<div class="box"><table><thead><tr><th>Product</th><th>Store</th><th class="num">Was</th>'
                   '<th class="num">Now</th><th class="num">Off</th></tr></thead><tbody>')
        for r in on_sale:
            out.append(f'<tr{attrs(r["name"], r["store"], r["groups"])}><td>{link(r["url"], r["name"])}</td>'
                       f'<td>{store_chip(r["store"])}</td><td class="num old">{_peso(r["regular_price"])}</td>'
                       f'<td class="num">{_peso(r["price"])}</td>'
                       f'<td class="num gap">{_pct(1 - r["price"] / r["regular_price"])}</td></tr>')
        for r in b1t1:
            out.append(f'<tr{attrs(r["name"], r["store"], r["groups"])}><td>{link(r["url"], r["name"])}</td>'
                       f'<td>{store_chip(r["store"])}</td><td class="num">—</td><td class="num">{_peso(r["price"])}</td>'
                       f'<td class="num"><span class="chip">Buy 1 Take 1</span></td></tr>')
        out.append('</tbody></table></div><p class="no-hits" hidden>Nothing on sale matches this filter.</p></section>')

    # Same product, different price
    out.append('<section class="section" aria-labelledby="h-pair" data-filterable><div class="section-head">'
               '<h2 id="h-pair">Same product, different price</h2>'
               '<span class="hint">Same item and size in two stores · green is cheaper</span></div>')
    if pairs:
        out.append('<div class="box"><table><thead><tr><th>Product</th><th>Cheaper at</th><th class="num">Price</th>'
                   '<th>Dearer at</th><th class="num">Price</th><th class="num">Gap</th></tr></thead><tbody>')
        for p in pairs[:25]:
            c, d = p["cheap"], p["dear"]
            out.append(f'<tr{attrs(c["name"] + " " + d["name"] + " " + STORE_NAMES.get(d["store"], d["store"]), c["store"], c["groups"])}>'
                       f'<td>{link(c["url"], c["name"])}</td><td>{store_chip(c["store"])}</td>'
                       f'<td class="num win">{_peso(c["price"])}</td><td>{store_chip(d["store"])}</td>'
                       f'<td class="num">{_peso(d["price"])}</td><td class="num gap">{_pct(p["gap"])}</td></tr>')
        out.append('</tbody></table></div><p class="no-hits" hidden>No cross-store matches for this filter.</p>')
    else:
        out.append('<div class="empty"><p>No product was found in two stores today.</p></div>')
    out.append('</section>')

    # Cheapest per group
    out.append('<section class="section" aria-labelledby="h-grp" data-filterable><div class="section-head">'
               '<h2 id="h-grp">Cheapest per group</h2>'
               '<span class="hint">Unit price (₱/kg, ₱/L) · a fair comparison across brands and sizes</span></div>'
               '<div class="groups">')
    for it in items:
        cand = [(_unit(r["price"], r["name"]), r) for r in rows if it.id in r["groups"]]
        cand = [c for c in cand if c[0]]
        names = " ".join(r["name"] for _, r in cand)
        q = f"{it.name} {it.category} {names}".lower()
        out.append(f'<article class="group" data-cat="{_slug(it.category)}" data-q="{escape(q)}">'
                   f'<span class="gcat">{escape(it.category)}</span>'
                   f'<h3>{escape(it.name)}<small>{len(cand)} item{"s" if len(cand) != 1 else ""}</small></h3>')
        if not cand:
            out.append('<p class="none">No matches today.</p></article>')
            continue
        units = [u[1] for u, _ in cand]
        main = max(set(units), key=units.count)
        cand = sorted([c for c in cand if c[0][1] == main], key=lambda c: c[0][0])[:3]
        out.append('<ol>')
        for up, r in cand:
            out.append(f'<li><span class="u">{_unit_label(up)}</span><span class="p">{escape(r["name"])}</span>'
                       f'<span class="w">{escape(STORE_NAMES.get(r["store"], r["store"]))} · {_peso(r["price"])}</span></li>')
        out.append('</ol></article>')
    out.append('</div><p class="no-hits" hidden>No groups match this filter.</p></section>')

    # Store searches: what each search returned and what the watchlist filtered out
    searches = data.get("searches") or {}
    if searches:
        tracked_urls = {r["url"] for r in rows}
        q_items = {}
        for it in items:
            for q in (it.queries or []):
                q_items.setdefault(q.lower(), it)
        out.append('<section class="section" aria-labelledby="h-srch" data-filterable><div class="section-head">'
                   '<h2 id="h-srch">Store searches</h2>'
                   '<span class="hint">What each store returned · "not on watchlist" lists products the store '
                   'found but the watchlist rules left out — tell me if one belongs</span></div>'
                   '<div class="box"><table><thead><tr><th>Store</th><th>Search</th><th class="num">Results</th>'
                   '<th class="num">Kept</th><th>Not on watchlist (first 8)</th></tr></thead><tbody>')
        order = list(STORE_NAMES)
        for (store, query), hits in sorted(searches.items(),
                                           key=lambda kv: (order.index(kv[0][0]) if kv[0][0] in order else 9, kv[0][1])):
            kept = sum(h["url"] in tracked_urls for h in hits)
            left = [h for h in hits if h["url"] not in tracked_urls]
            it = q_items.get(query.lower())
            cat = _slug(it.category) if it else "other"
            names = "; ".join(f'{h["name"]} ({_peso(h["price"]) if h["price"] else "price not read"})'
                              for h in left[:8]) if left else "—"
            res = (f'<span class="chip">no results</span>' if not hits else str(len(hits)))
            q = f"{STORE_NAMES.get(store, store)} {query} " + " ".join(h["name"] for h in hits)
            out.append(f'<tr data-cat="{cat}" data-q="{escape(q.lower())}">'
                       f'<td>{store_chip(store)}</td><td>{escape(query)}</td><td class="num">{res}</td>'
                       f'<td class="num">{kept}</td><td class="cat">{escape(names)}</td></tr>')
        out.append('</tbody></table></div><p class="no-hits" hidden>No searches match this filter.</p></section>')

    # All tracked products
    def sort_key(r):
        cs = cats_of(r["groups"])
        up = _unit(r["price"], r["name"])
        return (categories.index(cs[0]) if cs else 99, up[0] if up else float("inf"), r["name"].lower())

    out.append('<section class="section" id="all-products" aria-labelledby="h-all" data-filterable><div class="section-head">'
               '<h2 id="h-all">All tracked products</h2>'
               '<span class="hint">Every product matched today · cheapest unit price first within a category</span></div>'
               '<div class="box"><table><thead><tr><th>Product</th><th>Category</th><th>Store</th>'
               '<th class="num">Price</th><th class="num">Unit price</th></tr></thead><tbody>')
    for r in sorted(rows, key=sort_key):
        cs = ", ".join(cats_of(r["groups"]))
        was = (f' <span class="old">{_peso(r["regular_price"])}</span>'
               if r["regular_price"] and r["regular_price"] > r["price"] else "")
        out.append(f'<tr{attrs(r["name"], r["store"], r["groups"], product=True)}><td>{link(r["url"], r["name"])}</td>'
                   f'<td class="cat">{escape(cs)}</td><td>{store_chip(r["store"])}</td>'
                   f'<td class="num">{_peso(r["price"])}{was}</td>'
                   f'<td class="num">{_unit_label(_unit(r["price"], r["name"]))}</td></tr>')
    out.append('</tbody></table></div><p class="no-hits" hidden>No products match. Try a brand name or clear the filter.</p></section>')

    src = " · ".join(link(STORE_URLS[s], STORE_NAMES[s]) for s in stores_seen if s in STORE_URLS)
    out.append(f'<footer>Sources: {src} · generated {generated:%d %b %Y %H:%M}</footer>')
    out.append(f'</div>\n<script>{JS}</script>')
    return "\n".join(out)


def write(db_path: str, items: list[WatchItem], out_path: str) -> str:
    from pathlib import Path
    html = render(load(db_path), items)
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("<!doctype html>\n<html lang=\"en\">\n<head>\n" + html.replace("</style>\n", "</style>\n</head>\n<body>\n", 1)
                 + "\n</body>\n</html>\n", encoding="utf-8")
    return str(p)
