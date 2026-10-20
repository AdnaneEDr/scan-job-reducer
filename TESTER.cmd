@echo off
setlocal
cd /d "%~dp0"
set "SCAN_PYTHON="
py -3 -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
if not errorlevel 1 set "SCAN_PYTHON=py -3"
if defined SCAN_PYTHON goto ready
python -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
if not errorlevel 1 set "SCAN_PYTHON=python"
if defined SCAN_PYTHON goto ready
set "SCAN_BUNDLED=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%SCAN_BUNDLED%" goto bundled
echo Python 3.10 or later is required to run this project.
pause
exit /b 2
:bundled
set SCAN_PYTHON="%SCAN_BUNDLED%"
:ready
echo === Primary scenario ===
%SCAN_PYTHON% app.py --input inputs/primary.json
if errorlevel 1 goto failed
echo.
echo === Secondary scenario ===
%SCAN_PYTHON% app.py --input inputs/secondary.json
if errorlevel 1 goto failed
echo.
echo === Automated tests ===
%SCAN_PYTHON% -m unittest discover -s tests -p "*_test.py" -v
if errorlevel 1 goto failed
echo.
echo Both scenarios and all tests passed.
pause
exit /b 0
:failed
echo.
echo An error occurred. See the message above.
pause
exit /b 1

