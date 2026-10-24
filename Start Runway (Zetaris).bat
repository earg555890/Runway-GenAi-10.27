@echo off
rem Start Runway on http://localhost:8501 with Maya's data read through Zetaris, and open the browser.
rem Needs Docker Desktop and the Zetaris containers running (JDBC port 10000). If Runway is already running,
rem just open the browser.
setlocal
cd /d "%~dp0"
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
if %errorlevel%==0 (
  start "" http://localhost:8501
  exit /b 0
)
powershell -NoProfile -Command "$c = New-Object Net.Sockets.TcpClient; try { $c.Connect('localhost', 10000); exit 0 } catch { exit 1 } finally { $c.Close() }"
if errorlevel 1 (
  echo Zetaris isn't reachable on port 10000.
  echo Start Docker Desktop and the Zetaris containers first.
  pause
  exit /b 1
)
set "RUNWAY_BACKEND=zetaris"
call "%~dp0Start Runway.bat"
endlocal
