# Speedy Bot — Setup completo

## 1. Variables de entorno (`.env`)

Crea el archivo `.env` en esta carpeta con estos valores:

```
WHATSAPP_TOKEN=EAAxxxxxx          ← tu token de Meta
WHATSAPP_PHONE_ID=123456789       ← ID del número en Meta
WHATSAPP_VERIFY_TOKEN=speedy_verify_2024
GOOGLE_SHEETS_ID=1vTSCljUl3ycIE4B72o4-jeZn7iuJG9WxVX0jbTxJpPg
GOOGLE_CREDENTIALS_FILE=credentials.json
PORT=5001
```

---

## 2. Google Sheets — credentials.json (5 minutos)

Como ya tienes GCP, la opción más rápida es **Service Account**:

1. Ve a: https://console.cloud.google.com/
2. Selecciona tu proyecto (o crea uno nuevo gratis)
3. Menú izquierdo → **APIs y Servicios** → **Biblioteca**
   - Busca **Google Sheets API** → Habilitar
4. Menú izquierdo → **APIs y Servicios** → **Credenciales**
   - Clic en **+ CREAR CREDENCIALES** → **Cuenta de servicio**
   - Nombre: `speedy-bot` → Crear
   - Rol: **Editor** → Continuar → Listo
5. Clic en la cuenta recién creada → pestaña **Claves**
   - **Agregar clave** → **Crear clave nueva** → JSON → Descargar
   - Renombra el archivo descargado a `credentials.json` y ponlo en esta carpeta

6. **Comparte tu Google Sheet** con el email de la service account:
   - El email está dentro del `credentials.json` como `"client_email"`
   - Abre el sheet → Compartir → pega ese email → Editor

✅ Listo. El bot ya puede leer y escribir en tu sheet.

---

## 3. Instalar dependencias

```powershell
pip install -r requirements_speedy.txt
python -m playwright install chromium
```

Para OCR en PDFs escaneados (opcional):
- Descarga Tesseract: https://github.com/UB-Mannheim/tesseract/wiki
- Instálalo y agrega la ruta a PATH

---

## 4. Configurar webhook en Meta

1. Ve a: https://developers.facebook.com/
2. Tu App → WhatsApp → Configuración → Webhooks
3. URL del webhook: `https://TU_TUNNEL.trycloudflare.com/webhook`
4. Token de verificación: `speedy_verify_2024`
5. Suscribir a: `messages`

---

## 5. Correr el bot

```powershell
# Abrir Cloudflare tunnel (ventana 1):
.\cloudflared.exe tunnel --url http://localhost:5001

# Correr el bot (ventana 2, o doble clic en start_speedy.bat):
python speedy_api.py

# El scheduler de alertas corre automáticamente desde start_speedy.bat
# O manualmente:
python alerts_scheduler.py
```

---

## Estructura de archivos

```
runt_analysis/
├── speedy_api.py          ← Servidor principal (Flask + webhook Meta)
├── conversation.py        ← Máquina de estados del bot
├── runt_scraper.py        ← Consulta RUNT y SIMIT
├── pdf_parser.py          ← Extrae campos de PDFs vehiculares
├── extractor_texto.py     ← Motor de extracción de texto (pypdf + OCR)
├── cross_reference.py     ← Compara PDF vs RUNT
├── whatsapp_client.py     ← Envía mensajes a Meta API
├── sheets_logger.py       ← Lee/escribe en Google Sheets
├── alerts_scheduler.py    ← Alertas de vencimiento automáticas
├── config.py              ← Variables de entorno
├── .env                   ← TUS credenciales (no subir a git)
├── credentials.json       ← Service account Google (no subir a git)
└── start_speedy.bat       ← Arranque con doble clic
```
