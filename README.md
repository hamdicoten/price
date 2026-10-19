# Brew & Savour — Price Watch

Scans S&R, WalterMart and Landmark every day for the ingredients and supplies Brew & Savour buys,
keeps a price history in SQLite, sends Telegram alerts when something is genuinely cheap, and writes
a searchable HTML panel (`reports/price-watch.html`).

## Daily use (Windows)

```powershell
.\run.ps1            # scan → alerts → daily digest → panel (opens in the browser)
.\run.ps1 --force    # re-scan stores that were already scanned today
```

A store already scanned today is skipped and its stored prices are reused.
Logs go to `logs\`, prices to `data\prices.db`.

## Stores

| Store | How | Notes |
|---|---|---|
| S&R | Category pages, plain HTTP + HTML | Logged in → member prices in every category |
| WalterMart | Freshop API (token via Playwright) | Branch 7638 Mabalacat (closest online branch to Capas) |
| Landmark | Search page in a browser, captures the page's own API response | Direct API calls return 403 |
| Robinsons (GoRobinsons) | — | robots.txt forbids automated access; out of scope |

## Alerts

| Kind | Rule |
|---|---|
| Store discount | The store shows a struck-through old price |
| Buy 1 Take 1 | Product listed in S&R's Buy 1 Take 1 category |
| Below 30-day median | Price at least 15% under its 30-day median |
| Lowest price yet | New low after ≥ 7 days of history, at least 5% under the previous low |

The same alert at the same (or higher) price is not repeated within 7 days.
Thresholds live in `watchlist.yaml` → `settings`.

## Watchlist and categories

`watchlist.yaml` holds the ingredient groups. Each group has a `category` (Dairy, Pantry,
Spices & Sauces, Chicken, Pork, Beef, Cleaning, Café Supplies — add your own), and is matched by:

- `brands`: name must contain one of them (leave empty for unbranded items such as fresh meat)
- `keywords`: name must contain one of them
- `exclude`: name must not contain any of them
- `queries`: search terms for WalterMart and Landmark

Keep a group's `id` stable once prices are recorded — it links the price history.

## Panel

`reports/price-watch.html` is a single file that works offline:
search box (press `/` to focus) for product or brand names, category chips, alerts, today's sales,
the same product across stores, cheapest unit price per group, and every tracked product.

## Run it in the cloud (GitHub Actions + GitHub Pages) — free, nothing to maintain

`.github/workflows/pricewatch.yml` runs every day at 07:10 Manila time on GitHub's servers:
scan → alerts → digest → price history committed to `data/prices.db` → panel published on GitHub Pages.
In a **public** repository both Actions minutes and Pages hosting are free and unlimited.

1. Create a **public** repository on github.com (e.g. `bns-pricewatch`) and push this folder,
   including `data/prices.db` (the history collected so far).
2. Settings → Pages → Build and deployment → Source: **GitHub Actions**.
3. Settings → Secrets and variables → Actions → add `SNR_EMAIL`, `SNR_PASSWORD`
   (optional: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). Secrets are never visible in the public repo.
4. Actions tab → **Price Watch** → **Run workflow** once. After that it runs by itself.

The panel lives at `https://<github-user>.github.io/bns-pricewatch/` — anyone with the link can open it
(it only shows store prices; search engines are told not to index it).
The daily commit keeps the schedule alive (GitHub pauses schedules after 60 days without activity).
GitHub's runners sit in US data centres; if a store ever blocks them, the log will show it.

### Netlify (optional, not recommended)

`python -m pricewatch.cli publish` can deploy the panel to Netlify as an alias (branch) deploy.
On credit-based Netlify plans every *production* deploy costs 15 credits against a hard 300/month
limit that pauses every site on the account, so a daily production deploy is never used here.

## Credentials (local runs; the cloud uses GitHub secrets)

Never put credentials in `watchlist.yaml` or the code; they are read from environment variables.

```powershell
# one-time, while $env:SNR_EMAIL / $env:SNR_PASSWORD are set in the current window
[Environment]::SetEnvironmentVariable("SNR_EMAIL",    $env:SNR_EMAIL,    "User")
[Environment]::SetEnvironmentVariable("SNR_PASSWORD", $env:SNR_PASSWORD, "User")
[Environment]::SetEnvironmentVariable("TELEGRAM_BOT_TOKEN", "<token>", "User")
[Environment]::SetEnvironmentVariable("TELEGRAM_CHAT_ID",   "<chat id>", "User")
```

Without the Telegram variables, messages are printed to the console.

## Local schedule (not needed when GitHub Actions runs it)

Windows Task Scheduler, every morning at 08:00 (run from the project folder):

```powershell
$a = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PWD\run.ps1`""
$t = New-ScheduledTaskTrigger -Daily -At 8:00
Register-ScheduledTask -TaskName "BnS Price Watch" -Action $a -Trigger $t
```

For an always-on setup use the GitHub Actions workflow above. `Dockerfile` and `k8s/cronjob.yaml`
are there for a self-hosted cluster you own.

## Setup from scratch

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
python -m pytest -q
Get-ChildItem -Recurse | Unblock-File   # Windows blocks downloaded scripts
```

## Troubleshooting

`python -m pricewatch.cli recon --stores snr` saves raw S&R pages to `recon/` and logs the login
result, form field names and the site's error message (never your password).
