@echo off
rem Start TestLab locally for development and testing (Django development server).
rem Developer convenience only - not for production deployment.
rem
rem Uses the existing virtual environment in <repo>\.venv; installs nothing.
rem Applies pending migrations to the configured development database (never
rem deletes or recreates it), then serves on http://127.0.0.1:8000/.
setlocal

rem Repository root = parent of this script's directory, wherever it is launched from.
for %%I in ("%~dp0..") do set "REPO_DIR=%%~fI"
set "VENV_DIR=%REPO_DIR%\.venv"
set "URL=http://127.0.0.1:8000/"

if not exist "%VENV_DIR%\Scripts\python.exe" goto no_venv

call "%VENV_DIR%\Scripts\activate.bat"

python -c "import django, dj_database_url, docxtpl" >nul 2>&1
if errorlevel 1 goto missing_packages

cd /d "%REPO_DIR%\app"

echo TestLab: applying pending database migrations (if any)...
python manage.py migrate --noinput
if errorlevel 1 goto migrate_failed

echo.
echo   TestLab is starting at:  %URL%
echo   (stop the server with Ctrl+C)
echo.
python manage.py runserver 127.0.0.1:8000
exit /b %errorlevel%

:no_venv
echo TestLab: no Python virtual environment found at %VENV_DIR%
goto setup_help

:missing_packages
echo TestLab: the virtual environment at %VENV_DIR% is missing required packages.
goto setup_help

:setup_help
echo.
echo Create the development environment once, in %REPO_DIR%:
echo.
echo     py -3.12 -m venv .venv
echo     .venv\Scripts\pip install -e ".[dev]"
echo     .venv\Scripts\python app\manage.py createsuperuser
echo.
echo Requires Python 3.12+. See README.md, "Development setup".
pause
exit /b 1

:migrate_failed
echo TestLab: applying migrations failed - see the error above. The server was not started.
pause
exit /b 1
