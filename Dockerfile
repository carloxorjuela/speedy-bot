# Playwright base image — trae Chromium + todas las dependencias del sistema
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium para Playwright (ya incluido en base image, este paso lo registra)
RUN playwright install chromium

# Código y assets
COPY api.py runt_scraper.py ./
COPY *.html ./
COPY *.js ./

# Directorio persistente para la base de datos
# En Azure App Service, /home es el volumen persistente montado automáticamente
RUN mkdir -p /home/data

EXPOSE 8080

# Al arrancar: si no existe la DB en /home/data, copiar la inicial incluida en la imagen
CMD ["sh", "-c", "\
  mkdir -p /home/data && [ ! -f /home/data/carplus.db ] && cp -n /app/carplus.db /home/data/carplus.db 2>/dev/null || true; \
  gunicorn --bind 0.0.0.0:8080 --workers 1 --timeout 120 api:app"]
