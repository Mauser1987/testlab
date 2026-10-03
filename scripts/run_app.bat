@echo off
rem Start TestLab locally (Django development server). Not a production deployment.
rem
rem   scripts\run_app.bat                 http://127.0.0.1:8000/ (this machine only)
rem   scripts\run_app.bat --lan           also reachable from the network
rem   scripts\run_app.bat --port 8001
rem
rem Thin wrapper around scripts\devenv.py run, shared with Linux (run_app.sh).
rem Works from any directory or by double-click. Run scripts\setup.bat first.
setlocal
for %%I in ("%~dp0..") do set "REPO_DIR=%%~fI"
set "PYTHON=%REPO_DIR%\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo TestLab: no virtual environment at %REPO_DIR%\.venv - run scripts\setup.bat first.
    pause
    exit /b 1
)

"%PYTHON%" "%REPO_DIR%\scripts\devenv.py" run %*
if errorlevel 1 (
    echo.
    echo TestLab stopped with an error - see the messages above.
    pause
    exit /b 1
)
exit /b 0
