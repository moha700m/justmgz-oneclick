@echo off
setlocal
title justmgz - diagnosis
cd /d "%~dp0"
echo.
echo ============================================
echo   justmgz diagnosis
echo ============================================
echo.

echo [1] WSL present?
where wsl >nul 2>&1
if errorlevel 1 (echo     NO - install WSL first) else (echo     yes)

echo [2] Ubuntu reachable?
wsl -u root -e true >nul 2>&1
if errorlevel 1 (echo     NO - open Ubuntu once) else (echo     yes)

echo [3] python3 inside Ubuntu?
wsl -u root -e bash -lc "command -v python3 >/dev/null && python3 -V || echo MISSING"

echo [4] engine binary?
wsl -u root -e bash -lc "test -x /opt/justmgz/eng/tr4mpass && echo present || echo MISSING"

echo [5] panel files?
wsl -u root -e bash -lc "test -f /opt/justmgz/app/ui.html && echo present || echo MISSING"

echo [6] libraries?
wsl -u root -e bash -lc "ldd /opt/justmgz/eng/tr4mpass 2>/dev/null | grep -c 'not found' | xargs -I{} echo {} missing"

echo [7] is port 8099 listening inside Ubuntu?
wsl -u root -e bash -lc "fuser 8099/tcp 2>/dev/null || echo nothing"

echo [7b] panel process running?
wsl -u root -e bash -lc "pgrep -af justmgz-engine.py || echo none"

echo [8] local HTTP response inside Ubuntu:
wsl -u root -e bash -lc "curl -s -o /dev/null -w '%%{http_code}\n' http://127.0.0.1:8099/ 2>/dev/null || echo failed"

echo [9] can Windows reach 127.0.0.1:8099?
powershell -NoProfile -Command "try{ $c=New-Object Net.Sockets.TcpClient('127.0.0.1',8099); $c.Close(); 'yes' }catch{ 'NO' }"

echo.
echo [10] last 15 lines of server log:
echo --------------------------------------------
wsl -u root -e tail -n 15 /tmp/justmgz.log 2>nul
echo --------------------------------------------
echo.
echo Copy this whole window if you need help.
pause
exit /b
