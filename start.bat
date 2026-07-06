@echo off
title AlphaSwarm — API Server
cd /d "%~dp0"

echo.
echo  ============================================
echo   AlphaSwarm v2.1 — Multi-Agent Portfolio Mgmt
echo  ============================================
echo.
echo  Arret des instances precedentes...

REM Kill any existing process on port 5001
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5001 " ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo  Demarrage du serveur API...
echo  Interface : http://localhost:5001
echo.

start /min "" cmd /c ".venv\Scripts\python api.py"
timeout /t 3 /nobreak >nul
start http://localhost:5001

echo  Serveur lance. Fermez cette fenetre pour arreter.
pause
