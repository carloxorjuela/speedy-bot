@echo off
title Speedy Bot - CarPlus
echo.
echo  ==========================================
echo    SPEEDY BOT - CARPLUS
echo  ==========================================
echo.

echo  [0/2] Limpiando procesos anteriores en puerto 8080...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8080 " ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 /nobreak > nul

echo  [1/2] Iniciando API Flask en puerto 8080...
start "CarPlus - API Flask" cmd /k "cd /d C:\Users\jsgut\runt_analysis && python api.py"

echo  [2/2] Iniciando Cloudflare Tunnel (protocolo http2 para evitar errores QUIC)...
timeout /t 3 /nobreak > nul
start "CarPlus - Tunnel Cloudflare" cmd /k "C:\Users\jsgut\runt_analysis\cloudflared.exe tunnel --url http://localhost:8080 --protocol http2"

echo.
echo  ==========================================
echo   IMPORTANTE: Cuando veas la URL publica
echo   en la ventana del tunnel, copiala y
echo   actualiza en n8n:
echo     Nodo "Llamar API RUNT"  (URL /consultar)
echo     Nodo "Preparar Resultado RUNT" (TUNNEL=)
echo  ==========================================
echo.
pause
