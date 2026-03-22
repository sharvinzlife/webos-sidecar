@echo off
setlocal

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  py -3 "%ROOT_DIR%launch.py" %*
  exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  python "%ROOT_DIR%launch.py" %*
  exit /b %ERRORLEVEL%
)

echo Python 3 is required.
exit /b 1
