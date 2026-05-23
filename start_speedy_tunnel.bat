@echo off
title Speedy Bot - Tunnel
echo.
echo  ==========================================
echo    SPEEDY BOT - TUNNEL CLOUDFLARE
echo    Puerto: 5001
echo  ==========================================
echo.
echo  Cuando veas la URL publica (https://xxxx.trycloudflare.com)
echo  copiala y ponla en Meta como webhook:
echo    URL: https://xxxx.trycloudflare.com/webhook
echo    Verify token: speedy_verify_2024
echo.
"C:\Users\jsgut\runt_analysis\cloudflared.exe" tunnel --url http://localhost:5001 --protocol http2
pause
