@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title justmgz — التثبيت والتشغيل
cd /d "%~dp0"
set "LOG=%~dp0install-log.txt"
set "APTLOCAL=%TEMP%\justmgz-apt.log"
echo. > "%LOG%"

if defined JUSTMGZ_NOELEV goto :after_elev
net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo   هذا الملف يحتاج صلاحيات مسؤول.
  echo   بتطلع لك نافذة — اضغط "نعم".
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
:after_elev

call :line
call :say "  justmgz — التثبيت التلقائي"
call :say "  (المرة الأولى فقط)"
call :line
call :say ""

where wsl >nul 2>&1
if errorlevel 1 goto :NO_WSL

wsl -u root -e true >nul 2>&1
if errorlevel 1 goto :NO_DISTRO

call :say "الخطوة ١ من ٥ — نحدد مكان الملفات"
set "WPATH="
for /f "usebackq delims=" %%p in (`wsl -u root wslpath -a "%CD%"`) do set "WPATH=%%p"
if not defined WPATH goto :ERR_PATH
call :say "   جاهز"
call :say ""

call :say "الخطوة ٢ من ٥ — نثبت مكتبات النظام"
call :say "   (تاخذ من دقيقة إلى ثلاث)"
wsl -u root -e bash -lc "apt-get update > /tmp/justmgz-apt.log 2>&1; apt-get install -y build-essential git pkg-config python3 libimobiledevice-dev libirecovery-1.0-dev libusb-1.0-0-dev libplist-dev libcurl4-openssl-dev libssl-dev libssh2-1-dev libusbmuxd-dev psmisc >> /tmp/justmgz-apt.log 2>&1; echo $? > /tmp/justmgz-apt.rc" >nul 2>&1

set "APT_RC="
for /f "usebackq delims=" %%r in (`wsl -u root -e cat /tmp/justmgz-apt.rc 2^>nul`) do set "APT_RC=%%r"

if not defined APT_RC (
  call :say "   ما قدرنا نقرأ نتيجة التثبيت — نكمل ونتأكد وقت البناء"
  goto :apt_done
)
if "!APT_RC!"=="0" (
  call :say "   تم"
  goto :apt_done
)

call :say "   تعذّر التثبيت — نشوف السبب"
wsl -u root -e cat /tmp/justmgz-apt.log > "%APTLOCAL%" 2>nul
if exist "%APTLOCAL%" type "%APTLOCAL%" >> "%LOG%"

findstr /i /c:"Could not get lock" "%APTLOCAL%" >nul 2>&1
if not errorlevel 1 (
  call :say "   السبب: برنامج ثاني يحدّث النظام داخل أوبنتو."
  call :say "   سكّر أي نافذة أوبنتو مفتوحة، واستنى دقيقة، وشغّل الملف مرة ثانية."
  goto :ERR_APT
)

findstr /i /c:"Temporary failure resolving" "%APTLOCAL%" >nul 2>&1
if not errorlevel 1 (
  call :say "   السبب: أوبنتو ما توصل للإنترنت."
  call :say "   افتح أوبنتو واكتب: ping google.com"
  call :say "   إذا ما رد، الإنترنت عندك محجوب عن WSL (VPN أو فلتر)."
  goto :ERR_APT
)

findstr /i /c:"Unable to locate package" "%APTLOCAL%" >nul 2>&1
if not errorlevel 1 (
  call :say "   السبب: نسخة أوبنتو عندك ما فيها المستودع المطلوب."
  call :say "   نحاول نفعّل المستودع ونعيد المحاولة..."
  wsl -u root -e bash -lc "apt-get install -y software-properties-common >/dev/null 2>&1; add-apt-repository -y universe >>/tmp/justmgz-apt.log 2>&1; apt-get update >>/tmp/justmgz-apt.log 2>&1; apt-get install -y build-essential git pkg-config python3 libimobiledevice-dev libirecovery-1.0-dev libusb-1.0-0-dev libplist-dev libcurl4-openssl-dev libssl-dev libssh2-1-dev libusbmuxd-dev psmisc >>/tmp/justmgz-apt.log 2>&1; echo $? > /tmp/justmgz-apt.rc" >nul 2>&1
  set "APT_RC2="
  for /f "usebackq delims=" %%r in (`wsl -u root -e cat /tmp/justmgz-apt.rc 2^>nul`) do set "APT_RC2=%%r"
  if "!APT_RC2!"=="0" (
    call :say "   نجحت المحاولة الثانية"
    goto :apt_done
  )
  call :say "   برضه فشلت — التفاصيل في ملف install-log.txt"
  goto :ERR_APT
)

call :say "   صار خطأ غير متوقع في التثبيت."
call :say "   التفاصيل في install-log.txt — أرسله لي وأصلحه."
goto :ERR_APT

:apt_done
call :say ""

call :say "الخطوة ٣ من ٥ — ننزل المحرك ونبنيه"
call :say "   (تاخذ من دقيقتين إلى خمس)"
wsl -u root -e bash -lc "set -e; mkdir -p /opt/justmgz; if [ ! -d /opt/justmgz/eng/.git ]; then git clone --depth 1 https://github.com/tr4m0ryp/tr4mpass /opt/justmgz/eng; fi; cd /opt/justmgz/eng; if [ ! -f .patched ]; then patch -p1 < '%WPATH%/app/fix-build.patch'; touch .patched; fi; make -j4" >> "%LOG%" 2>&1
if errorlevel 1 goto :ERR_BUILD
wsl -u root -e bash -lc "mkdir -p /opt/justmgz/app && cp -f '%WPATH%/app/'* /opt/justmgz/app/" >> "%LOG%" 2>&1
call :say "   تم — المحرك جاهز"
call :say ""

call :say "الخطوة ٤ من ٥ — نجهز توصيل الآيفون"
set "USBIPD=usbipd"
where usbipd >nul 2>&1
if errorlevel 1 (
  call :say "   نثبت أداة تمرير USB..."
  winget install --exact --silent --accept-package-agreements --accept-source-agreements dorssel.usbipd-win >> "%LOG%" 2>&1
  if exist "%ProgramFiles%\usbipd-win\usbipd.exe" set "USBIPD=%ProgramFiles%\usbipd-win\usbipd.exe"
)
set "BUSID="
"!USBIPD!" list > "%TEMP%\justmgz-usb.txt" 2>nul
for /f "tokens=1" %%b in ('findstr /i "Apple" "%TEMP%\justmgz-usb.txt"') do if not defined BUSID set "BUSID=%%b"
if not defined BUSID (
  call :say "   ما لقينا آيفون موصول — وصله بالكيبل بعدين شغّل RUN-justmgz.bat"
) else (
  "!USBIPD!" bind --busid !BUSID! >nul 2>&1
  "!USBIPD!" attach --wsl --busid !BUSID! >nul 2>&1
  call :say "   تم توصيل الجهاز"
)
call :say ""

call :say "الخطوة ٥ من ٥ — نشغل اللوحة"
wsl -u root -e bash -lc "fuser -k 8099/tcp 2>/dev/null; sleep 1; setsid nohup env TR4MPASS_DIR=/opt/justmgz/eng python3 /opt/justmgz/app/justmgz-engine.py > /tmp/justmgz.log 2>&1 < /dev/null &" >nul 2>&1
powershell -NoProfile -Command "$i=0; while($i -lt 12){ try{ $c=New-Object Net.Sockets.TcpClient('127.0.0.1',8099); $c.Close(); exit 0 }catch{ Start-Sleep -Milliseconds 500; $i++ } }; exit 1" >nul 2>&1
start "" "http://127.0.0.1:8099"

echo.
call :line
call :say "  خلص — المتصفح يفتح على اللوحة"
call :say "  اضغط الزر: ابدأ — وخله علينا"
call :line
echo.
call :say "المرة القادمة: دبل كلك على RUN-justmgz.bat"
echo.
pause
exit /b

:NO_WSL
call :say ""
call :say "ويندوز عندك ما فيه WSL."
call :say "بنثبته لك الآن — وبيطلب منك إعادة تشغيل الجهاز مرة وحدة."
call :say ""
wsl --install -d Ubuntu
call :say ""
call :say "بعد إعادة التشغيل: شغّل هذا الملف مرة ثانية."
pause
exit /b

:NO_DISTRO
call :say ""
call :say "WSL موجود، بس ما فيه أوبنتو مثبت."
call :say "بننزله لك الآن..."
wsl --install -d Ubuntu
call :say ""
call :say "بعد ما يخلص: افتح أوبنتو مرة وحدة، وبعدها شغّل هذا الملف."
pause
exit /b

:ERR_PATH
call :say ""
call :say "ما قدرنا نحدد مسار المجلد."
call :say "انقل الملفات لمجلد بسيط بدون مسافات، مثل: C:\justmgz"
pause
exit /b

:ERR_APT
call :say ""
call :say "توقفنا عند تثبيت المكتبات."
call :say "ملف install-log.txt فيه التفاصيل كاملة."
pause
exit /b

:ERR_BUILD
call :say ""
call :say "توقفنا عند بناء المحرك."
call :say "الأسباب الشائعة: المكتبات ناقصة، أو ما فيه إنترنت داخل أوبنتو."
call :say "التفاصيل في install-log.txt"
pause
exit /b

:line
echo ============================================
>>"%LOG%" echo ============================================
exit /b

:say
echo %~1
>>"%LOG%" echo %~1
exit /b
