@echo off
setlocal
title justmgz
cd /d "%~dp0"
echo.
echo   justmgz - starting
echo   ============================================
echo.

wsl -u root -e test -x /opt/justmgz/eng/tr4mpass >nul 2>&1
if errorlevel 1 goto NOT_SETUP
if defined JUSTMGZ_NOELEV goto after_elev
net session >nul 2>&1
if errorlevel 1 (
  echo   Admin rights needed. Press "Yes" in the window.
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
:after_elev

set "USBIPD=usbipd"
if exist "%ProgramFiles%\usbipd-win\usbipd.exe" set "USBIPD=%ProgramFiles%\usbipd-win\usbipd.exe"

set "BUSID="
"%USBIPD%" list > "%TEMP%\justmgz-usb.txt" 2>nul
for /f "tokens=1" %%b in ('findstr /i "Apple" "%TEMP%\justmgz-usb.txt"') do if not defined BUSID set "BUSID=%%b"
if defined BUSID goto do_attach
echo   no iPhone detected.
echo   Plug the cable, wait for the screen to light up, run this file again.
echo.
pause
goto start_panel

:do_attach
"%USBIPD%" bind --busid %BUSID% >nul 2>&1
"%USBIPD%" attach --wsl --busid %BUSID% >nul 2>&1
echo   device attached (%BUSID%)

:start_panel
echo   starting panel...
wsl -u root -e bash -lc "fuser -k 8099/tcp 2>/dev/null; sleep 1; setsid nohup env TR4MPASS_DIR=/opt/justmgz/eng python3 /opt/justmgz/app/justmgz-engine.py > /tmp/justmgz.log 2>&1 < /dev/null &" >nul 2>&1
if defined JUSTMGZ_SKIP_HEALTH goto open_browser
set "HEALTH="
wsl -u root -e bash -lc "curl -s -o /dev/null -w %%{http_code} http://127.0.0.1:8099/ > /tmp/justmgz-health.txt 2>/dev/null" >nul 2>&1
for /f "usebackq delims=" %%h in (`wsl -u root -e cat /tmp/justmgz-health.txt 2^>nul`) do set "HEALTH=%%h"
if not "%HEALTH%"=="200" goto panel_dead
:open_browser
start "" "http://127.0.0.1:8099"
echo   done - browser is opening.
exit /b

:panel_dead
echo.
echo   The panel did not start. Last lines of the log:
echo   --------------------------------------------
wsl -u root -e tail -n 20 /tmp/justmgz.log
echo   --------------------------------------------
echo   Double click DO-CHECK.bat for a full diagnosis.
echo.
pause
exit /b

:NOT_SETUP
echo   Setup is not complete.
echo   Run START-justmgz.bat once, then come back to this file.
echo.
pause
exit /b
