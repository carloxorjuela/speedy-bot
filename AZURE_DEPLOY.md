# Azure Deployment — Estado y Pasos

**Objetivo:** Publicar el portal web (admin, preoperacional, consulta) en Azure App Service.  
**Restricción conocida:** RUNT y SIMIT bloquean IPs de datacenter → el scraper debe seguir corriendo en PC local Colombia. Azure solo sirve la UI.

---

## Recursos Azure creados

| Recurso | Nombre | Estado |
|---|---|---|
| Resource Group | `rg-speedy` | ✅ Creado |
| Container Registry | `acrspeedyvehicular` | ✅ Creado (Basic) |
| App Service Plan | `plan-speedy` | ✅ Creado (Linux B1) |
| Web App | `speedy-vehicular` | ✅ Creado |

**Suscripción ID:** `95fc091d-ef91-4f7a-8587-d8e81c70fa3c`  
**URL pública:** `https://speedy-vehicular.azurewebsites.net`

---

## Arquitectura de deploy

```
git push main
    ↓
GitHub Actions (.github/workflows/deploy.yml)
    ↓ build Docker image
    ↓ push → ghcr.io/carloxorjuela/speedy:latest
    ↓ az webapp config container set
Azure App Service
    ↓ pull image de ghcr.io
    ↓ run container
    ↓ /home/data/carplus.db (Azure Files persistente)
```

**¿Por qué ghcr.io y no ACR?**  
La suscripción tiene `TasksOperationsNotAllowed` en ACR — bloquea tanto `az acr build` como el push via CI. GitHub Container Registry (ghcr.io) es gratuito y no tiene esa restricción.

---

## Dockerfile

```dockerfile
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium
COPY api.py runt_scraper.py ./
COPY *.html *.js ./
RUN mkdir -p /home/data
EXPOSE 8080
CMD ["sh", "-c", \
  "[ ! -f /home/data/carplus.db ] && cp -n /app/carplus.db /home/data/carplus.db 2>/dev/null || true; \
   gunicorn --bind 0.0.0.0:8080 --workers 1 --timeout 120 api:app"]
```

**Notas:**
- Imagen base Playwright trae Chromium y todas las dependencias del sistema (~1.5 GB)
- 1 worker (Playwright/scraper no es thread-safe)
- Al arrancar: copia `carplus.db` a `/home/data/` solo si no existe (preserva datos en producción)

---

## Variables de entorno en App Service

```powershell
az webapp config appsettings set --resource-group rg-speedy --name speedy-vehicular --settings `
  DB_PATH=/home/data/carplus.db `
  ADMIN_KEY="speedy-admin-2026" `
  WEBSITES_PORT=8080 `
  WEBSITES_ENABLE_APP_SERVICE_STORAGE=true
```

`WEBSITES_ENABLE_APP_SERVICE_STORAGE=true` habilita el montaje de `/home` como Azure Files persistente.

---

## GitHub Actions workflow

Archivo: `.github/workflows/deploy.yml`

Requiere 4 secretos configurados en `github.com/carloxorjuela/carplus/settings/secrets/actions`:

| Secret | Cómo obtenerlo |
|---|---|
| `AZURE_CREDENTIALS` | `az ad sp create-for-rbac --name "github-speedy" --role contributor --scopes /subscriptions/95fc091d.../resourceGroups/rg-speedy --json-auth` |
| `AZURE_APP_NAME` | `speedy-vehicular` |
| `AZURE_RESOURCE_GROUP` | `rg-speedy` |
| ~~`AZURE_PUBLISH_PROFILE`~~ | Ya no se usa (reemplazado por AZURE_CREDENTIALS) |

El `GITHUB_TOKEN` para ghcr.io lo genera GitHub automáticamente — no requiere configuración.

---

## Errores encontrados y soluciones

### 1. `MissingSubscriptionRegistration` — Microsoft.ContainerRegistry
**Cuándo ocurre:** Al crear el ACR por primera vez.  
**Solución:**
```powershell
az provider register --namespace Microsoft.ContainerRegistry --wait
```

### 2. `TasksOperationsNotAllowed` — ACR Tasks
**Cuándo ocurre:** Al intentar `az acr build` o push desde CI hacia ACR.  
**Causa:** Restricción de política en la suscripción de Azure.  
**Solución:** Abandonar ACR. Usar **GitHub Container Registry (ghcr.io)** en su lugar. El workflow actualizado usa `docker/build-push-action` → ghcr.io + `azure/CLI` para actualizar el container en App Service.

### 3. `Failed to get app runtime OS {}` — webapps-deploy action
**Cuándo ocurre:** Al usar `azure/webapps-deploy@v3` con containers.  
**Causa:** Bug conocido del action v3 con App Service de contenedores Linux.  
**Solución:** Reemplazar el action por `azure/login` + `azure/CLI` que ejecuta directamente:
```bash
az webapp config container set --name ... --docker-custom-image-name ...
az webapp restart --name ...
```

---

## Pasos pendientes para completar el deploy

1. **Crear Service Principal** (si no existe):
```powershell
az ad sp create-for-rbac --name "github-speedy" --role contributor `
  --scopes "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/rg-speedy" `
  --json-auth
```
Copiar el JSON completo.

2. **Agregar secretos en GitHub** (`/settings/secrets/actions`):
   - `AZURE_CREDENTIALS` → JSON del paso anterior
   - `AZURE_APP_NAME` → `speedy-vehicular`
   - `AZURE_RESOURCE_GROUP` → `rg-speedy`

3. **Correr el workflow** desde la pestaña Actions del repo (o hacer cualquier push a `main`).

4. **Verificar** en `https://speedy-vehicular.azurewebsites.net`

---

## Costos estimados

| Recurso | Plan | Costo mensual |
|---|---|---|
| App Service Plan (Linux) | B1 | ~$13 USD |
| Container Registry | Basic | ~$5 USD |
| Azure Files (storage `/home`) | LRS | < $1 USD |
| **Total** | | **~$18-19 USD/mes** |

> Si el tráfico es bajo, considerar bajar a **F1 gratuito** para el portal (sin scraper). El F1 tiene solo 1 GB RAM — Playwright/Chromium NO arranca en F1.

---

## Comandos útiles post-deploy

```powershell
# Ver logs en tiempo real
az webapp log tail --name speedy-vehicular --resource-group rg-speedy

# Reiniciar
az webapp restart --name speedy-vehicular --resource-group rg-speedy

# Ver configuración del contenedor
az webapp config container show --name speedy-vehicular --resource-group rg-speedy

# Actualizar manualmente la imagen (sin CI)
az webapp config container set `
  --name speedy-vehicular --resource-group rg-speedy `
  --docker-custom-image-name ghcr.io/carloxorjuela/speedy:latest
```
