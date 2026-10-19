# Brew & Savour Price Watch — daily scan
# Usage:  .\run.ps1                              (scan + alerts + daily digest + panel)
#         .\run.ps1 --stores landmark,waltermart (extra arguments go to the CLI)
#         .\run.ps1 --force                       (re-scan stores already scanned today)
#
# S&R login reads SNR_EMAIL / SNR_PASSWORD from Windows USER environment variables.
# One-time setup (while the values are set in that window):
#   [Environment]::SetEnvironmentVariable("SNR_EMAIL",    $env:SNR_EMAIL,    "User")
#   [Environment]::SetEnvironmentVariable("SNR_PASSWORD", $env:SNR_PASSWORD, "User")

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# Python writes UTF-8; make PowerShell read UTF-8 too (otherwise ₱ shows up garbled)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

foreach ($name in "SNR_EMAIL", "SNR_PASSWORD", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID") {
    if (-not [Environment]::GetEnvironmentVariable($name, "Process")) {
        $v = [Environment]::GetEnvironmentVariable($name, "User")
        if ($v) { [Environment]::SetEnvironmentVariable($name, $v, "Process") }
    }
}
if (-not $env:SNR_EMAIL -or -not $env:SNR_PASSWORD) {
    Write-Warning "SNR_EMAIL / SNR_PASSWORD not set — S&R will be scanned without login (Member's Value only)."
}

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw ".venv not found. First run: python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt" }

New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot "logs") | Out-Null
$log = Join-Path $PSScriptRoot ("logs\run-{0:yyyy-MM-dd_HHmm}.log" -f (Get-Date))

# Local runs are for testing; the daily scan and the online panel run on GitHub Actions.
& $python -m pricewatch.cli run --digest --report @args 2>&1 | Tee-Object -FilePath $log
$panel = Join-Path $PSScriptRoot "reports\price-watch.html"
Write-Host "`nLog:   $log"
Write-Host "Panel: $panel"
# Open the panel in the browser after a manual run
if ([Environment]::UserInteractive -and $Host.Name -eq 'ConsoleHost' -and (Test-Path $panel)) { Invoke-Item $panel }
