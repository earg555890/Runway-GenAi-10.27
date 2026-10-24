@echo off
rem Start Runway on http://localhost:8501 (local data, saved answers first) and open the browser.
rem If something is already serving 8501, just open the browser.
rem "Start Runway (Zetaris).bat" calls this with RUNWAY_BACKEND=zetaris.
setlocal
cd /d "%~dp0"
if not defined RUNWAY_BACKEND set "RUNWAY_BACKEND=local"

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if %errorlevel%==0 goto :open

if not exist ".venv\Scripts\python.exe" (
  echo Runway isn't installed yet. See README.md, "Try it in 2 minutes".
  pause
  exit /b 1
)
echo Starting Runway with %RUNWAY_BACKEND% data...
set "DATA_BACKEND=%RUNWAY_BACKEND%"
set "ANSWER_MODE=cached"
start "Runway" cmd /c ".venv\Scripts\python.exe -m streamlit run ui\app.py --server.port 8501 --server.headless true || pause"
powershell -NoProfile -Command "$end = (Get-Date).AddSeconds(120); while ((Get-Date) -lt $end) { try { if ((Invoke-WebRequest -UseBasicParsing http://localhost:8501/_stcore/health -TimeoutSec 2).Content -eq 'ok') { exit 0 } } catch {}; Start-Sleep -Milliseconds 500 }; exit 1"
if errorlevel 1 (
  echo Runway didn't start within 2 minutes. Look at the "Runway" window for the error.
  pause
  exit /b 1
)

:open
start "" http://localhost:8501
endlocal
