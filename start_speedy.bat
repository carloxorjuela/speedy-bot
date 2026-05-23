@echo off
title Speedy Bot - Verificacion Vehicular
echo.
echo  ================================================
echo    Speedy Bot - Verificacion Vehicular Colombia
echo  ================================================
echo.

cd /d "%~dp0"

REM Activar entorno virtual si existe
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
    echo [OK] Entorno virtual activado
)

REM Verificar .env
if not exist ".env" (
    echo [ERROR] No existe el archivo .env
    echo         Copia .env.example a .env y rellena los valores.
    pause
    exit /b 1
)

REM Verificar credentials.json de Google
if not exist "credentials.json" (
    echo [WARN] No existe credentials.json para Google Sheets.
    echo        El logging a Sheets estara desactivado.
    echo.
)

echo [OK] Iniciando bot Speedy en puerto 5001...
echo [OK] Webhook URL: http://localhost:5001/webhook
echo.
echo      Recuerda tener Cloudflare corriendo en otra ventana:
echo      cloudflared.exe tunnel --url http://localhost:5001
echo.

start "Speedy - Alertas" cmd /k "python alerts_scheduler.py"

python speedy_api.py

pause
