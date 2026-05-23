# Speedy — RUNT + SIMIT Scraper & Web Dashboard
**Proyecto:** Consulta de vehículos colombianos + chatbot WhatsApp + portal web  
**Repositorio:** https://github.com/carloxorjuela/carplus.git  
**Última actualización:** 2026-05-23

---

## ¿Qué hace este proyecto?

Un usuario envía su **placa** y **cédula** → el sistema consulta RUNT y SIMIT → responde con todos los datos del vehículo y multas.

Canales soportados:
- **WhatsApp** (vía n8n + bot)
- **Portal web** en `http://localhost:8080` — UI detallada con tarjetas por sección
- **Dashboard admin** en `http://localhost:8080/admin` — métricas, logs, gestión de flota, configuración (4 pestañas)
- **Preoperacional** en `http://localhost:8080/preoperacional` — formulario de revisión vehicular diaria

```
WhatsApp → n8n → API Flask → RUNT + SIMIT → respuesta
Browser  →      API Flask  → RUNT + SIMIT → JSON estructurado
```

---

## Arquitectura

| Componente | Tecnología | Ubicación |
|---|---|---|
| Chatbot | WhatsApp + n8n | Cloud (n8n $20/mes) |
| API REST | Flask + Python | PC local Colombia |
| Túnel público | Cloudflare Tunnel | PC local Colombia |
| Scraper RUNT | Python + ddddocr OCR | PC local Colombia |
| Scraper SIMIT | Python + Playwright (Chrome headless) | PC local Colombia |
| Base de datos | SQLite (`carplus.db`) | PC local Colombia |
| Portal usuario | HTML/CSS/JS (Tailwind + jsPDF) | Servido por Flask |
| Admin dashboard | HTML/CSS/JS (Chart.js + SheetJS + jsPDF) | Servido por Flask |
| Preoperacional | HTML/CSS/JS (Canvas signature pad + jsPDF) | Servido por Flask |

**¿Por qué en PC local?** El RUNT y SIMIT bloquean IPs de datacenters. Solo funcionan desde IPs colombianas residenciales.

---

## Estructura de archivos

```
runt_analysis/
├── api.py                    ← Flask API REST (todos los endpoints)
├── runt_scraper.py           ← Scrapers RUNT + SIMIT
├── index.html                ← Portal usuario (consulta detallada + PDF)
├── admin.html                ← Dashboard admin (4 tabs: Dashboard/Consultas/Placas/Configuración)
├── preoperacional.html       ← Formulario revisión preoperacional vehicular
├── placas.html               ← Dashboard de placas standalone (legacy, redirige a /admin)
├── requirements.txt          ← flask, gunicorn, requests, ddddocr, playwright
├── Dockerfile                ← Deploy Azure: base image Playwright + Chromium
├── .dockerignore
├── .github/workflows/deploy.yml  ← CI/CD: build en GitHub Actions → ghcr.io → Azure App Service
├── CONTEXTO.md               ← Este archivo
├── AZURE_DEPLOY.md           ← Estado y pasos del despliegue en Azure
├── capture_simit.py          ← Scripts auxiliares SIMIT
├── simit_core.js             ← JS reverseado del portal SIMIT (referencia)
└── carplus.db                ← SQLite local (en prod: /home/data/carplus.db)
```

---

## Cómo correr (local)

### Instalación (primera vez)
```powershell
pip install flask requests ddddocr playwright
python -m playwright install chromium
```

### Arranque (2 terminales)
```powershell
# Terminal 1 — API
cd C:\Users\danie\Downloads\runt_analysis\runt_analysis
python api.py

# Terminal 2 — Túnel público (opcional, para WhatsApp/n8n)
cloudflared.exe tunnel --url http://localhost:8080
```

### Acceso web
| URL | Descripción |
|---|---|
| `http://localhost:8080` | Portal de consulta para usuarios |
| `http://localhost:8080/admin` | Dashboard admin (4 pestañas) |
| `http://localhost:8080/preoperacional` | Formulario preoperacional |
| `http://localhost:8080/health` | Health check |

---

## Credenciales

| Qué | Valor |
|---|---|
| Password portal admin | `speedy2026` |
| API Key admin (header `X-Admin-Key`) | `speedy-admin-2026` |
| Variable de entorno para cambiar API Key | `ADMIN_KEY` |
| Variable de entorno para ruta DB | `DB_PATH` (default: junto a api.py) |

---

## API Endpoints

### Públicos
| Método | Ruta | Descripción |
|---|---|---|
| GET | `/` | Sirve `index.html` |
| GET | `/admin` | Sirve `admin.html` |
| GET | `/preoperacional` | Sirve `preoperacional.html` |
| GET | `/placas` | Redirige a `/admin` |
| GET | `/health` | `{"status": "ok"}` |
| POST | `/consultar` | Consulta completa RUNT + SIMIT |

**Request `/consultar`:**
```json
{ "placa": "IXX979", "cedula": "1010960147" }
```

**Response `/consultar`:**
```json
{
  "ok": true,
  "mensaje": "...",
  "datos": { "auth": {...}, "soat": [...], "solicitudes": [...], ... }
}
```

> `mensaje` = texto formateado para WhatsApp.  
> `datos` = JSON estructurado completo para la UI web.

### Admin (requieren `X-Admin-Key: speedy-admin-2026`)
| Método | Ruta | Descripción |
|---|---|---|
| GET | `/admin/metrics` | Métricas agregadas de uso |
| GET | `/admin/logs?page=1&per_page=50` | Logs paginados de consultas |
| GET | `/admin/placas` | Todas las placas cacheadas |
| GET | `/admin/placas/<placa>/datos` | JSON completo de una placa |

---

## Base de datos (`carplus.db`)

### Tabla `consultas` — log de cada request
```sql
id, timestamp, placa, cedula_masked, success, error_msg, response_time_ms, ip
```

### Tabla `placas_cache` — última consulta por placa
```sql
placa (PK), cedula_masked, ultima_consulta, datos_json,
marca, modelo, anio, color, clase, estado_vehiculo,
soat_vence, soat_aseguradora, soat_estado,
rtm_vence, rtm_cda, rtm_estado,
rc_vence, rc_estado,
tarjeta_op_vence, tarjeta_op_estado,
simit_paz_salvo, simit_total
```

> La caché se actualiza automáticamente en cada `/consultar` exitoso.

**En producción (Azure):** `DB_PATH=/home/data/carplus.db` — el directorio `/home` en App Service Linux es un volumen Azure Files persistente que sobrevive reinicios y redeployments.

---

## Clase `RuntScraper`

**API base:** `https://runtproapi.runt.gov.co/CYRConsultaVehiculoMS`

**Flujo de autenticación:**
1. GET `/captcha/libre-captcha/generar` → imagen PNG base64
2. OCR con `ddddocr(beta=True)` → texto del captcha
3. POST `/auth` con placa + cédula + captcha → JWT token
4. 19 endpoints con `Auth-Token: Bearer <jwt>`

**19 secciones consultadas:**
| Key en `datos` | Endpoint RUNT | Notas |
|---|---|---|
| `soat` | `/soat` | lista directa |
| `responsabilidad_civil` | `/responsabilidad-civil` | lista directa |
| `tecnomecanica` | `/rtms?tipo=<idClaseVehiculo>` | puede retornar null — ver nota RTM |
| `solicitudes` | `/solicitudes` | **fuente real de RTM** |
| `tarjeta_operacion` | `/tarjeta-operacion` | |
| `limitaciones` | `/limitaciones-propiedad` | lista directa |
| `garantias` | `/garantias` | |
| `garantias_prendas` | `/garantias/prendas` | |
| `blindaje` | `/datos-blindaje` | |
| `poliza_caucion` | `/poliza-caucion` | |
| `desintegracion` | `/desintegracion` | |
| `dijin` | `/certificado-dijin` | |
| `normalizacion` | `/normalizacion` | |
| `permisos_pcr` | `/permisos-pcr` | |
| `repotenciado` | `/informacion-repotenciado` | |

### ⚠️ Nota crítica sobre RTM

El endpoint `/rtms` retorna **vacío/null** para la mayoría de vehículos de la flota. Los datos reales de Revisión Técnico-Mecánica se encuentran en `/solicitudes`, filtrando por `tramitesRealizados` que contenga `"tecnico mecanica"`.

**Lógica en JS (index.html, placas.html, admin.html):**
```javascript
function extractRtmSol(solicitudes) {
  const kws = ['tecnico mecanica', 'tecnomecanica', 'rtm'];
  const cands = (Array.isArray(solicitudes) ? solicitudes : [])
    .filter(s => kws.some(k => (s.tramitesRealizados || '').toLowerCase().includes(k)));
  cands.sort((a, b) => (b.fechaSolicitud > a.fechaSolicitud ? 1 : -1));
  return cands[0] || null;
}
```

**Vencimiento RTM:** El campo `fechaVigencia` no existe en solicitudes. Se calcula como `fechaSolicitud + 1 año` (estimado).

---

## Clase `SimitScraper`

**Portal:** `https://www.fcm.org.co/simit/#/estado-cuenta`

**¿Por qué Playwright?** El SIMIT usa weHateCaptcha (proof-of-work) + FortiADC WAF que bloquean requests directos.

**Flujo:**
1. Playwright abre Chrome headless → navega al portal SIMIT
2. Browser resuelve el PoW automáticamente (~3-10s)
3. Llama la API via `fetch()` desde el contexto del browser (bypassa WAF)
4. Retorna JSON con multas, comparendos, totales

**Respuesta SIMIT:**
```json
{
  "multas": [...],
  "comparendos": [...],
  "acuerdosPago": [...],
  "pazSalvo": true/false,
  "totalGeneral": 0
}
```

**⚠️ Nota:** `pazSalvo` puede ser `false` aun cuando `totalGeneral = 0`. Tratar como paz y salvo si `pazSalvo || !totalGeneral`.

---

## Interfaces Web

### `index.html` — Portal de Usuario
- Formulario: Placa + Cédula → botón Consultar
- Carga animada en 3 pasos (captcha → RUNT → SIMIT)
- Tarjeta vehículo + fila de estado (SOAT / RTM / SIMIT) con badges
- Grid de secciones: SOAT, RTM, RC, Tarjeta Operación, Limitaciones, SIMIT multas
- Acordeón: Garantías, Solicitudes, Blindaje, DIJIN, Normalización, PCR, Repotenciado
- **Botón "Descargar PDF":** genera certificado formal con jsPDF+autotable (5 secciones: Datos, Documentos, SIMIT, Limitaciones, Garantías)
- Botón "Copiar para WhatsApp"

### `admin.html` — Dashboard Admin (4 pestañas)
- **Dashboard:** KPIs (total, hoy, éxito %, tiempo promedio) + gráficas Chart.js
- **Consultas:** tabla logs paginada con filtros
- **Placas:** dashboard completo de flota (antiguo `/placas`) — tabla con estados, filtros, modal detalle, exportar Excel/PDF, filtro "Con multas"
- **Configuración:** ajustes del sistema

### `preoperacional.html` — Formulario Preoperacional
- Basado en el formato oficial de revisión preoperacional vehicular
- Secciones: Información General, Requisitos Documentales (6 docs con fechas de vencimiento), Componentes Eléctricos (8 ítems), Componentes Mecánicos (17 ítems)
- Radios: Cumple / No Cumple / N/A; Sí / No / N/A
- Canvas signature pad (mouse + touch)
- Upload de fotos con preview
- localStorage para guardar borrador
- Genera PDF con jsPDF + autotable color-coded

---

## Integración n8n (WhatsApp)

Nodo **HTTP Request** en n8n:
| Campo | Valor |
|---|---|
| Method | POST |
| URL | `https://TU-URL.trycloudflare.com/consultar` |
| Body | `{"placa": "{{ $json.placa }}", "cedula": "{{ $json.cedula }}"}` |

---

## Bugs resueltos

| Bug | Causa | Solución |
|---|---|---|
| RTM vacío en todos los vehículos | `/rtms` retorna null para la flota | Usar `/solicitudes` filtrado por "tecnico mecanica" |
| SIMIT muestra "Con Deudas" con $0 | `pazSalvo=false` aunque `totalGeneral=0` | Condición: `pazSalvo \|\| !totalGeneral` |
| Filtro "Con multas" no funciona | Tailwind CDN no genera clases añadidas dinámicamente | Usar `el.style.*` en lugar de `classList.add()` |
| PDF SIMIT/Limitaciones cortadas | `autoTable` sin `margin.bottom` solapaba el footer | Añadir `margin: { bottom: 20 }` + `overflow: linebreak` |
| SOAT muestra año incorrecto | `soat_list[-1]` no considera fechas | `max(valid, key=lambda x: x['fechaVencimSoat'])` |
| 403 en RUNT desde nube | IP datacenter bloqueada | Correr en PC Colombia |
| OCR pierde mayúsculas | ddddocr modo default | Usar `beta=True` |
| SIMIT 401 directo | WAF + weHateCaptcha | Playwright headless |

---

## Tiempos por consulta

| Paso | Tiempo |
|---|---|
| RUNT captcha + auth | 5–15s |
| RUNT 19 endpoints | 10–20s |
| SIMIT Playwright + PoW | 5–15s |
| **Total** | **~30–50s** |

---

## Variables de entorno

```env
ADMIN_KEY=speedy-admin-2026       # API key para endpoints /admin/*
DB_PATH=/home/data/carplus.db     # Ruta DB (en producción Azure)
PORT=8080
```

---

## Opciones que se intentaron y no funcionaron

| Opción | Resultado |
|---|---|
| Azure East US VM | ❌ 403 — IP Microsoft bloqueada por RUNT |
| Railway (ASN 400940) | ❌ 403 — IP datacenter bloqueada por RUNT |
| Cualquier cloud (AWS, GCP) | ❌ Mismo problema — IPs datacenter |
| Proxy colombiano | ✅ Funcionaría pero cuesta $15-30/mes extra |
| Hostinger VPS Colombia | ✅ Funcionaría (~$7/mes) pero PC local es gratis |

> Ver `AZURE_DEPLOY.md` para el estado del despliegue en Azure App Service (portal admin/preoperacional que sí puede correr en nube, sin scraper).
