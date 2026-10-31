@echo off
if defined JUSTMGZ_DEBUG @echo on
chcp 65001 >nul
setlocal EnableDelayedExpansion
title justmgz - تشغيل
cd /d "%~dp0"

wsl -u root -e test -x /opt/justmgz/eng/tr4mpass >nul 2>&1
if errorlevel 1 (
  echo [!] التثبيت غير مكتمل - شغل START-justmgz.bat اول مرة.
  pause
  exit /b
)

if defined JUSTMGZ_NOELEV goto :after_elev
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

:after_elev
set "USBIPD=usbipd"
if exist "%ProgramFiles%\usbipd-win\usbipd.exe" set "USBIPD=%ProgramFiles%\usbipd-win\usbipd.exe"
set "BUSID="
"!USBIPD!" list > "%TEMP%\usbipd-scan.txt" 2>nul
for /f "tokens=1" %%b in ('findstr /i "Apple" "%TEMP%\usbipd-scan.txt"') do if not defined BUSID set "BUSID=%%b"
if defined BUSID (
  "!USBIPD!" bind --busid !BUSID! >nul 2>&1
  "!USBIPD!" attach --wsl --busid !BUSID! >nul 2>&1
  echo [OK] الجهاز موصول: !BUSID!
) else (
  echo [!] ما لقينا آيفون. وصله بالكيبل وافتح الملف مرة ثانية.
  pause
)

wsl -u root -e bash -lc "fuser -k 8099/tcp 2>/dev/null; sleep 1; setsid nohup env TR4MPASS_DIR=/opt/justmgz/eng python3 /opt/justmgz/app/justmgz-engine.py > /tmp/justmgz.log 2>&1 < /dev/null &" >nul 2>&1
powershell -NoProfile -Command "$i=0; while($i -lt 24){ try{ $c=New-Object Net.Sockets.TcpClient('127.0.0.1',8099); $c.Close(); exit 0 }catch{ Start-Sleep -Milliseconds 500; $i++ } }; exit 1" >nul 2>&1
start "" "http://127.0.0.1:8099"
exit /b
