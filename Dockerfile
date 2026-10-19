# Playwright'ın resmi imajı Chromium + sistem bağımlılıklarıyla gelir
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pricewatch/ pricewatch/
COPY watchlist.yaml .

# Varsayılan: tara + uyar. Özet için CronJob args'ında --digest ekle.
ENTRYPOINT ["python", "-m", "pricewatch.cli"]
CMD ["run", "--db", "/data/prices.db"]
