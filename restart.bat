@echo off
title AlphaSwarm - Restart API
cd /d "%~dp0"

echo  Arret de l'API en cours...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5001 " ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo  Redemarrage du serveur API...
start /min "" cmd /c ".venv\Scripts\python api.py"
timeout /t 3 /nobreak >nul

echo  API relancee sur http://localhost:5001