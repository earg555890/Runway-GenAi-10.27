@echo off
rem Stop whatever is serving http://localhost:8501, plus the python launcher and the "PocketMoney" console window
rem above it (found by walking up the process tree, never by window title).
setlocal
powershell -NoProfile -Command "$ids = Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; if (-not $ids) { Write-Host 'PocketMoney is not running.'; exit 0 }; foreach ($id in $ids) { $kill = @($id); $p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $id); for ($i = 0; $i -lt 2 -and $p; $i++) { $p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $p.ParentProcessId); if ($p -and ($p.Name -eq 'python.exe' -or ($p.Name -eq 'cmd.exe' -and $p.CommandLine -like '*streamlit run ui*'))) { $kill += $p.ProcessId } }; foreach ($k in $kill) { Stop-Process -Id $k -Force -ErrorAction SilentlyContinue } }; Write-Host 'PocketMoney stopped.'"
endlocal
