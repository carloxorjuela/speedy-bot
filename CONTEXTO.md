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
- **Dashboard admin** en `http://localhost:8080/admin` — métricas de uso
- **Dashboard de placas** en `http://localhost:8080/placas` — gestión de flota con exportación Excel y PDF

```
WhatsApp → n8n → API Flask (PC Colombia) → RUNT + SIMIT → respuesta
Browser  →        API Flask               → RUNT + SIMIT → JSON estructurado
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
| Portal usuario | HTML/CSS/JS (Tailwind) | Servido por Flask |
| Admin dashboard | HTML/CSS/JS (Chart.js) | Servido por Flask |
| Placas dashboard | HTML/CSS/JS (SheetJS + jsPDF) | Servido por Flask |

**¿Por qué en PC local?** El RUNT y SIMIT bloquean IPs de datacenters. Solo funcionan desde IPs colombianas residenciales.

---

## Estructura de archivos

```
runt_analysis/
├── api.py                    ← Flask API REST (todos los endpoints)
├── runt_scraper.py           ← Scrapers RUNT + SIMIT
├── index.html                ← Portal usuario (consulta detallada)
├── admin.html                ← Dashboard admin (métricas y logs)
├── placas.html               ← Dashboard de placas (flota, Excel, PDF)
├── requirements.txt          ← Dependencias Python
├── Dockerfile                ← Para futuros deploys
├── capture_simit.py          ← Scripts auxiliares SIMIT
├── capture_simit2.py
├── test_simit.py
├── test_simit_playwright.py
├── simit_core.js             ← JS reverseado del portal SIMIT (referencia)
├── simit_estado_cuenta.js
├── entry.js
└── CONTEXTO.md               ← Este archivo
```

---

## Cómo correr

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
| `http://localhost:8080/admin` | Dashboard admin |
| `http://localhost:8080/placas` | Dashboard de placas / flota |
| `http://localhost:8080/health` | Health check |

---

## Credenciales

| Qué | Valor |
|---|---|
| Password portal admin y placas | `speedy2026` |
| API Key admin (header `X-Admin-Key`) | `speedy-admin-2026` |
| Variable de entorno para cambiar API Key | `ADMIN_KEY` |

---

## API Endpoints

### Públicos
| Método | Ruta | Descripción |
|---|---|---|
| GET | `/` | Sirve `index.html` |
| GET | `/admin` | Sirve `admin.html` |
| GET | `/placas` | Sirve `placas.html` |
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
  "datos": { "auth": {...}, "soat": [...], "tecnomecanica": {...}, ... }
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
> Para refrescar una placa: hacer nueva consulta desde el portal o dashboard.

---

## Clase `RuntScraper`

**API base:** `https://runtproapi.runt.gov.co/CYRConsultaVehiculoMS`

**Flujo de autenticación:**
1. GET `/captcha/libre-captcha/generar` → imagen PNG base64
2. OCR con `ddddocr(beta=True)` → texto del captcha
3. POST `/auth` con placa + cédula + captcha → JWT token
4. 19 endpoints con `Auth-Token: Bearer <jwt>`

**Método principal:** `consulta_completa(placa, cedula)` → dict con todos los datos

**19 secciones consultadas:**
| Key en `datos` | Endpoint RUNT |
|---|---|
| `soat` | `/soat` → **lista directa** |
| `responsabilidad_civil` | `/responsabilidad-civil` → **lista directa** |
| `tecnomecanica` | `/rtms?tipo=<idClaseVehiculo>` → dict con `revisiones` (puede ser null) |
| `tarjeta_operacion` | `/tarjeta-operacion` |
| `limitaciones` | `/limitaciones-propiedad` → **lista directa** |
| `garantias` | `/garantias` |
| `garantias_prendas` | `/garantias/prendas` |
| `solicitudes` | `/solicitudes` |
| `blindaje` | `/datos-blindaje` |
| `poliza_caucion` | `/poliza-caucion` |
| `desintegracion` | `/desintegracion` |
| `certificado_desintegracion` | `/desintegracion/certificado` |
| `registro_inicial` | `/registro-inicial` |
| `registro_inicial_invc` | `/registro-inicial/invc` |
| `dijin` | `/certificado-dijin` |
| `normalizacion` | `/normalizacion` |
| `normalizacion_certificado` | `/normalizacion/certificado` |
| `permisos_pcr` | `/permisos-pcr` |
| `repotenciado` | `/informacion-repotenciado` |

**Nota importante sobre `/rtms`:** El endpoint puede retornar:
- `{"error": false, "descripcionRespuesta": null, "revisiones": [...]}` — con datos
- `{"error": false, "descripcionRespuesta": "NO APLICA", "revisiones": null}` — sin RTM registrado
- Una **lista directa** `[{...}]` — manejado en el código

---

## Clase `SimitScraper`

**Portal:** `https://www.fcm.org.co/simit/#/estado-cuenta`

**¿Por qué Playwright?** El SIMIT usa weHateCaptcha (proof-of-work) y FortiADC WAF que bloquea requests directos.

**Flujo:**
1. Playwright abre Chrome headless → navega al portal SIMIT
2. Browser auto-resuelve el PoW en background (~3-10s)
3. Lee token resuelto de `sessionStorage['whcQuestions']`
4. Llama la API via `fetch()` desde el contexto del browser (bypassa WAF)
5. Retorna JSON con multas, comparendos, totales

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

---

## Interfaces Web

### `index.html` — Portal de Usuario
- Formulario: Placa + Cédula → botón Consultar
- Carga animada en 3 pasos (captcha → RUNT → SIMIT)
- **Tarjeta de vehículo:** marca, modelo, año, motor, chasis, estado (badge verde/rojo)
- **Fila de estado:** SOAT, RTM, SIMIT con badge vigente/vencido
- **Grid de secciones:** SOAT detallado, RTM, Responsabilidad Civil, Tarjeta Operación
- **Card Limitaciones:** verde si limpio, roja si hay registros
- **Card SIMIT:** Paz y Salvo verde OR lista de multas con montos
- **Acordeón:** Garantías, Solicitudes, Blindaje, DIJIN, Normalización, PCR, Repotenciado, Desintegración
- **Botones:** Imprimir (CSS print) + Copiar para WhatsApp

### `admin.html` — Dashboard Admin
- Login con password (`speedy2026`)
- 4 KPI cards: Total consultas, Consultas hoy, Tasa de éxito %, Tiempo promedio
- Gráfica línea: Consultas por día (últimos 7 días)
- Gráfica donut: Éxito vs Error
- Tabla logs paginada: ID, Fecha, Placa, Cédula (masked), Estado, Tiempo, IP
- Navegación a dashboard de placas desde sidebar

### `placas.html` — Dashboard de Placas
- Login compartido con admin
- Tabla de placas con columnas: Placa, Vehículo, Estado, SOAT, RTM, RC, SIMIT, T.Op, Última consulta
- **Colores por vencimiento:** borde rojo (vencido), borde ámbar (≤30 días), blanco (al día)
- **Badges de fecha:** "Vence en 15d" / "Venció hace 5d" / "Sin datos"
- **Filtros:** búsqueda texto, estado general, filtro por documento vencido
- **Ordenamiento** por cualquier columna
- **"Nueva Consulta" modal:** agregar placa con loading state (~30-50s)
- **"Ver Detalles" modal:** datos completos del vehículo
- **Exportar Excel:** SheetJS → `Speedy_Placas_YYYY-MM-DD.xlsx` (2 hojas: Resumen + Leyenda)
- **Generar PDF:** jsPDF + autoTable → `Speedy_Certificado_PLACA_FECHA.pdf`

---

## Integración n8n (WhatsApp)

Nodo **HTTP Request** en n8n:
| Campo | Valor |
|---|---|
| Method | POST |
| URL | `https://TU-URL.trycloudflare.com/consultar` |
| Body | `{"placa": "{{ $json.placa }}", "cedula": "{{ $json.cedula }}"}` |

La respuesta llega en `{{ $json.mensaje }}` → enviar directo al WhatsApp.

---

## Bugs conocidos y soluciones aplicadas

| Bug | Causa | Solución |
|---|---|---|
| SOAT muestra 2022 en dashboard siendo vigente 2026 | `soat_list[-1]` tomaba el índice final sin importar la fecha | Cambiado a `max(valid, key=lambda x: x['fechaVencimSoat'])` |
| RTM nunca muestra datos en ningún cliente | Código asumía `{"revisiones": [...]}` pero la API puede retornar lista directa o `revisiones: null` | Normalización: `Array.isArray(tec) ? tec : (tec?.revisiones ?? [])` en JS y equivalente en Python |
| 403 en RUNT desde nube | IP datacenter bloqueada | Correr en PC Colombia |
| OCR pierde mayúsculas | ddddocr modo default | Usar `beta=True` |
| HTTP 400 en /auth | Captcha inválido | Reintentar hasta 3 veces |
| SIMIT 401 directo | WAF + weHateCaptcha | Usar Playwright |

---

## Tiempos por consulta

| Paso | Tiempo |
|---|---|
| RUNT captcha + auth | 5–15s (reintentos si falla) |
| RUNT 19 endpoints | 10–20s |
| SIMIT Playwright + PoW | 5–15s |
| **Total** | **~30–50s** |

---

## Pendiente / Mejoras futuras

- [ ] **Tunnel permanente:** cuenta Cloudflare + dominio → URL fija
- [ ] **Auto-inicio Windows:** Task Scheduler para arrancar API + tunnel al encender PC
- [ ] **2captcha backup:** Si OCR falla mucho → activar `twocaptcha_api_key` (~$1/1000 captchas)
- [ ] **Cola de consultas:** Celery o queue simple para concurrencia alta
- [ ] **Monitoreo:** UptimeRobot ping al `/health` con alerta si cae
- [ ] **Diagnóstico RTM:** Confirmar si `/rtms` retorna datos para placas con RTM vigente en portal RUNT (debug logs activos en `obtener_tecnomecanica`)
- [ ] **Refresh automático de caché:** Programar re-consulta periódica para flota

---

## Variables de entorno

```env
ADMIN_KEY=speedy-admin-2026   # API key para endpoints /admin/*
PORT=8080
TWOCAPTCHA_API_KEY=           # Opcional, backup para OCR captcha
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
