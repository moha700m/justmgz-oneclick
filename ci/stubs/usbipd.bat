@echo off
if "%~1"=="list" (
  echo BUSID  VID:PID    DEVICE                        STATE
  echo 3-1    05ac:12a8  Apple Inc. iPhone             Not shared
  exit /b 0
)
echo [stub] usbipd %*
exit /b 0
