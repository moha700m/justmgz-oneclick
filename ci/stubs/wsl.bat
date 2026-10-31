@echo off
REM CI stub: mimics `wsl` so batch control flow can be tested without WSL
if "%~1"=="-u" (
  if "%~3"=="wslpath" (
    echo /mnt/c/actions/justmgz-oneclick
    exit /b 0
  )
  echo [stub] wsl -u root %~4 %~5 %~6
  exit /b 0
)
exit /b 0
