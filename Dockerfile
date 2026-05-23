# Imagen base oficial de Playwright con Python — ya trae Chromium y dependencias del sistema
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instalar Chromium para Playwright
RUN playwright install chromium

# Copiar código
COPY runt_scraper.py .
COPY api.py .

EXPOSE 8080

# gunicorn: 1 worker (scraper no es thread-safe), timeout 120s para dar tiempo al scraper
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--timeout", "120", "api:app"]
