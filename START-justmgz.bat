@echo off
setlocal
title justmgz installer
cd /d "%~dp0"
set "LOG=%~dp0install-log.txt"
set "APTLOCAL=%TEMP%\justmgz-apt.log"
echo. > "%LOG%"

if defined JUSTMGZ_NOELEV goto after_elev
net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo   Admin rights needed. Press "Yes" in the window that appears.
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
:after_elev

call :line
echo   justmgz - automatic setup  ^(first run only^)
call :line
echo.

where wsl >nul 2>&1
if errorlevel 1 goto NO_WSL

wsl -u root -e true >nul 2>&1
if errorlevel 1 goto NO_DISTRO

echo Step 1/5 - locating files
set "WPATH="
for /f "usebackq delims=" %%p in (`wsl -u root wslpath -a "%CD%"`) do set "WPATH=%%p"
if not defined WPATH goto ERR_PATH
echo    ok
echo.

echo Step 2/5 - installing system libraries  ^(1-3 min^)
wsl -u root -e bash -lc "apt-get update > /tmp/justmgz-apt.log 2>&1; apt-get install -y build-essential git pkg-config python3 libimobiledevice-dev libirecovery-1.0-dev libusb-1.0-0-dev libplist-dev libcurl4-openssl-dev libssl-dev libssh2-1-dev libusbmuxd-dev psmisc >> /tmp/justmgz-apt.log 2>&1; echo $? > /tmp/justmgz-apt.rc" >nul 2>&1

set "APT_RC="
for /f "usebackq delims=" %%r in (`wsl -u root -e cat /tmp/justmgz-apt.rc 2^>nul`) do set "APT_RC=%%r"
if not defined APT_RC goto apt_unknown
if "%APT_RC%"=="0" goto apt_done
goto apt_fail

:apt_unknown
echo    could not read install result - continuing
goto do_build

:apt_done
echo    ok
goto do_build

:apt_fail
echo    install failed - checking the reason
wsl -u root -e cat /tmp/justmgz-apt.log > "%APTLOCAL%" 2>nul
if exist "%APTLOCAL%" type "%APTLOCAL%" >> "%LOG%"
findstr /i /c:"Could not get lock" "%APTLOCAL%" >nul 2>&1
if not errorlevel 1 goto diag_lock
findstr /i /c:"Temporary failure resolving" "%APTLOCAL%" >nul 2>&1
if not errorlevel 1 goto diag_net
findstr /i /c:"Unable to locate package" "%APTLOCAL%" >nul 2>&1
if not errorlevel 1 goto diag_universe

echo    unknown apt error - see install-log.txt
goto ERR_APT

:diag_lock
echo    REASON: another program is updating Ubuntu.
echo    Close any Ubuntu window, wait a minute, run this file again.
goto ERR_APT

:diag_net
echo    REASON: Ubuntu has no internet.
echo    Open Ubuntu and run: ping google.com
goto ERR_APT

:diag_universe
echo    REASON: package repo is missing. Enabling universe and retrying...
wsl -u root -e bash -lc "apt-get install -y software-properties-common >/dev/null 2>&1; add-apt-repository -y universe >>/tmp/justmgz-apt.log 2>&1; apt-get update >>/tmp/justmgz-apt.log 2>&1; apt-get install -y build-essential git pkg-config python3 libimobiledevice-dev libirecovery-1.0-dev libusb-1.0-0-dev libplist-dev libcurl4-openssl-dev libssl-dev libssh2-1-dev libusbmuxd-dev psmisc >>/tmp/justmgz-apt.log 2>&1; echo $? > /tmp/justmgz-apt.rc" >nul 2>&1
set "APT_RC2="
for /f "usebackq delims=" %%r in (`wsl -u root -e cat /tmp/justmgz-apt.rc 2^>nul`) do set "APT_RC2=%%r"
if "%APT_RC2%"=="0" goto apt_retry_ok
echo    retry failed - see install-log.txt
goto ERR_APT

:apt_retry_ok
echo    ok on second attempt
goto do_build

:do_build
echo.
echo Step 3/5 - downloading engine and building  ^(2-5 min^)
wsl -u root -e bash -lc "set -e; mkdir -p /opt/justmgz; if [ ! -d /opt/justmgz/eng/.git ]; then git clone --depth 1 https://github.com/tr4m0ryp/tr4mpass /opt/justmgz/eng; fi; cd /opt/justmgz/eng; if [ ! -f .patched ]; then patch -p1 < '%WPATH%/app/fix-build.patch'; touch .patched; fi; make -j4" >> "%LOG%" 2>&1
if errorlevel 1 goto ERR_BUILD
wsl -u root -e bash -lc "mkdir -p /opt/justmgz/app && cp -f '%WPATH%/app/'* /opt/justmgz/app/" >> "%LOG%" 2>&1
echo    engine ready
echo.

echo Step 4/5 - preparing iPhone USB passthrough
set "USBIPD=usbipd"
where usbipd >nul 2>&1
if not errorlevel 1 goto have_usbipd
echo    installing usbipd...
winget install --exact --silent --accept-package-agreements --accept-source-agreements dorssel.usbipd-win >> "%LOG%" 2>&1
if exist "%ProgramFiles%\usbipd-win\usbipd.exe" set "USBIPD=%ProgramFiles%\usbipd-win\usbipd.exe"
:have_usbipd
set "BUSID="
"%USBIPD%" list > "%TEMP%\justmgz-usb.txt" 2>nul
for /f "tokens=1" %%b in ('findstr /i "Apple" "%TEMP%\justmgz-usb.txt"') do if not defined BUSID set "BUSID=%%b"
if defined BUSID goto do_attach
echo    no iPhone detected - plug it in, then run RUN-justmgz.bat
goto start_panel

:do_attach
"%USBIPD%" bind --busid %BUSID% >nul 2>&1
"%USBIPD%" attach --wsl --busid %BUSID% >nul 2>&1
echo    device attached (%BUSID%)

:start_panel
echo.
echo Step 5/5 - starting the panel
wsl -u root -e bash -lc "fuser -k 8099/tcp 2>/dev/null; sleep 1; setsid nohup env TR4MPASS_DIR=/opt/justmgz/eng python3 /opt/justmgz/app/justmgz-engine.py > /tmp/justmgz.log 2>&1 < /dev/null &" >nul 2>&1
if defined JUSTMGZ_SKIP_HEALTH goto open_browser

set "HEALTH="
wsl -u root -e bash -lc "curl -s -o /dev/null -w %%{http_code} http://127.0.0.1:8099/ > /tmp/justmgz-health.txt 2>/dev/null" >nul 2>&1
for /f "usebackq delims=" %%h in (`wsl -u root -e cat /tmp/justmgz-health.txt 2^>nul`) do set "HEALTH=%%h"
if not "%HEALTH%"=="200" goto panel_dead

powershell -NoProfile -Command "$i=0; while($i -lt 12){ try{ $c=New-Object Net.Sockets.TcpClient('127.0.0.1',8099); $c.Close(); exit 0 }catch{ Start-Sleep -Milliseconds 500; $i++ } }; exit 1" >nul 2>&1
if errorlevel 1 goto panel_forward

:open_browser
start "" "http://127.0.0.1:8099"
goto banner_ok

:panel_dead
echo.
echo   The panel did not start inside Ubuntu. Last lines of the log:
echo   --------------------------------------------
wsl -u root -e tail -n 20 /tmp/justmgz.log
echo   --------------------------------------------
echo   Full log:  wsl -u root cat /tmp/justmgz.log
echo   Full check: double click DO-CHECK.bat
echo.
pause
exit /b

:panel_forward
echo.
echo   Panel runs inside Ubuntu, but Windows cannot reach port 8099.
echo   This is a WSL network issue, not an install issue.
echo     1. run: wsl --shutdown   then start again
echo     2. turn off VPN / proxy temporarily
echo     3. run: netsh winsock reset  then restart Windows
echo.
pause
exit /b

:banner_ok

echo.
call :line
echo   done - the panel is opening in your browser
echo   press the big button: start
call :line
echo.
echo Next time: double click RUN-justmgz.bat
echo.
pause
exit /b

:NO_WSL
echo.
echo WSL is not installed. Installing it now...
wsl --install -d Ubuntu
echo.
echo Restart Windows once, then run this file again.
pause
exit /b

:NO_DISTRO
echo.
echo WSL found but no Ubuntu distro. Installing Ubuntu...
wsl --install -d Ubuntu
echo.
echo After it finishes: open Ubuntu once, then run this file again.
pause
exit /b

:ERR_PATH
echo.
echo Could not resolve the folder path.
echo Move the files to a simple folder like C:\justmgz and try again.
pause
exit /b

:ERR_APT
echo.
echo Stopped at system libraries. Details: install-log.txt
pause
exit /b

:ERR_BUILD
echo.
echo Stopped at engine build.
echo Common causes: missing libraries, or no internet inside Ubuntu.
echo Details: install-log.txt
pause
exit /b

:line
echo ============================================
>>"%LOG%" echo ============================================
exit /b
