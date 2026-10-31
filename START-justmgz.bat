@echo off
if defined JUSTMGZ_DEBUG @echo on
chcp 65001 >nul
setlocal EnableDelayedExpansion
title justmgz - التثبيت والتشغيل
cd /d "%~dp0"
set "LOG=%~dp0install-log.txt"
echo. > "%LOG%"

if defined JUSTMGZ_NOELEV goto :after_elev
net session >nul 2>&1
if errorlevel 1 (
  echo [!] يحتاج صلاحيات مسؤول - اضغط نعم في النافذة اللي تطلع
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

:after_elev
call :say "============================================"
call :say "  justmgz - تثبيت تلقائي (اول مرة بس)"
call :say "============================================"
call :say ""

where wsl >nul 2>&1
if errorlevel 1 goto :NO_WSL

wsl -u root -e true >nul 2>&1
if errorlevel 1 goto :NO_DISTRO

set "WPATH="
call :say "[1/5] نجهز مسار المشروع..."
for /f "usebackq delims=" %%p in (`wsl -u root wslpath -a "%CD%"`) do set "WPATH=%%p"
if not defined WPATH goto :ERR_PATH
call :say "      %WPATH%"

call :say "[2/5] نثبت المكتبات (قد تاخذ دقيقتين)..."
wsl -u root -e bash -lc "export DEBIAN_FRONTEND=noninteractive; apt-get update -qq && apt-get install -y -qq build-essential git pkg-config python3 libimobiledevice-dev libirecovery-dev libusb-1.0-0-dev libplist-dev libcurl4-openssl-dev libssl-dev libssh2-1-dev libusbmuxd-dev psmisc" >> "%LOG%" 2>&1
if errorlevel 1 goto :ERR_APT
call :say "      تم"

call :say "[3/5] ننزل المحرك ونبنيه..."
wsl -u root -e bash -lc "set -e; mkdir -p /opt/justmgz; if [ ! -d /opt/justmgz/eng/.git ]; then git clone --depth 1 https://github.com/tr4m0ryp/tr4mpass /opt/justmgz/eng; fi; cd /opt/justmgz/eng; if [ ! -f .patched ]; then patch -p1 < '%WPATH%/app/fix-build.patch'; touch .patched; fi; make -j4" >> "%LOG%" 2>&1
if errorlevel 1 goto :ERR_BUILD
wsl -u root -e bash -lc "mkdir -p /opt/justmgz/app && cp -f '%WPATH%/app/'* /opt/justmgz/app/" >> "%LOG%" 2>&1
call :say "      تم - المحرك جاهز"

call :say "[4/5] نجهز تمرير USB..."
set "USBIPD=usbipd"
where usbipd >nul 2>&1
if errorlevel 1 (
  winget install --exact --silent --accept-package-agreements --accept-source-agreements dorssel.usbipd-win >> "%LOG%" 2>&1
  if exist "%ProgramFiles%\usbipd-win\usbipd.exe" set "USBIPD=%ProgramFiles%\usbipd-win\usbipd.exe"
)
set "BUSID="
"!USBIPD!" list > "%TEMP%\usbipd-scan.txt" 2>nul
for /f "tokens=1" %%b in ('findstr /i "Apple" "%TEMP%\usbipd-scan.txt"') do if not defined BUSID set "BUSID=%%b"
if not defined BUSID (
  call :say "      ما لقينا آيفون موصول - وصله بالكيبل بعدين شغل RUN-justmgz.bat"
) else (
  "!USBIPD!" bind --busid !BUSID! >nul 2>&1
  "!USBIPD!" attach --wsl --busid !BUSID! >nul 2>&1
  call :say "      تم ربط الجهاز (!BUSID!)"
)

call :say "[5/5] نشغل اللوحة..."
wsl -u root -e bash -lc "fuser -k 8099/tcp 2>/dev/null; sleep 1; setsid nohup env TR4MPASS_DIR=/opt/justmgz/eng python3 /opt/justmgz/app/justmgz-engine.py > /tmp/justmgz.log 2>&1 < /dev/null &" >nul 2>&1
powershell -NoProfile -Command "$i=0; while($i -lt 24){ try{ $c=New-Object Net.Sockets.TcpClient('127.0.0.1',8099); $c.Close(); exit 0 }catch{ Start-Sleep -Milliseconds 500; $i++ } }; exit 1" >nul 2>&1
start "" "http://127.0.0.1:8099"

call :say ""
call :say "============================================"
call :say "  خلص - المتصفح يفتح لك على اللوحة"
call :say "  اضغط الزر: ابدأ"
call :say "============================================"
call :say ""
call :say "مرة ثانية: دبل كلك على RUN-justmgz.bat فقط"
pause
exit /b

:NO_WSL
call :say ""
call :say "[!] WSL مو مثبت على جهازك."
call :say "    بنثبته لك الآن... قد يطلب إعادة تشغيل الجهاز."
call :say ""
wsl --install -d Ubuntu
call :say ""
call :say "بعد ما يخلص: أعد تشغيل الجهاز، وبعدها شغل هذا الملف مرة ثانية."
pause
exit /b

:NO_DISTRO
call :say ""
call :say "[!] WSL موجود بس ما فيه Ubuntu."
call :say "    بننزله الآن..."
wsl --install -d Ubuntu
call :say "بعد التنزيل: افتح Ubuntu مرة وحدة عشان يكمل التجهيز، وبعدها أعد تشغيل هذا الملف."
pause
exit /b

:ERR_PATH
call :say "[X] ما قدرنا نحدد مسار المجلد. انقل الملفات لمجلد بسيط مثل C:\justmgz وجرب."
pause
exit /b

:ERR_APT
call :say "[X] فشل تثبيت المكتبات. التفاصيل في install-log.txt"
pause
exit /b

:ERR_BUILD
call :say "[X] فشل بناء المحرك. التفاصيل في install-log.txt"
pause
exit /b

:say
echo %~1
>>"%LOG%" echo %~1
exit /b
