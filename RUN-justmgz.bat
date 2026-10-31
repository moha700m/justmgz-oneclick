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
powershell -NoProfile -Command "$i=0; while($i -lt 12){ try{ $c=New-Object Net.Sockets.TcpClient('127.0.0.1',8099); $c.Close(); exit 0 }catch{ Start-Sleep -Milliseconds 500; $i++ } }; exit 1" >nul 2>&1
start "" "http://127.0.0.1:8099"
echo   done - browser is opening.
exit /b

:NOT_SETUP
echo   Setup is not complete.
echo   Run START-justmgz.bat once, then come back to this file.
echo.
pause
exit /b
