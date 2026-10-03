@echo off
rem TestLab - development setup (Windows). Safe to run again.
rem
rem   scripts\setup.bat
rem
rem Thin wrapper: finds a Python 3.12+ and runs scripts\devenv.py setup, which
rem holds the logic shared with Linux (setup.sh). Double-click or run from cmd.
rem An explicit interpreter wins: set TESTLAB_PYTHON=C:\path\to\python.exe
setlocal
for %%I in ("%~dp0..") do set "REPO_DIR=%%~fI"

set "PYCMD="
if defined TESTLAB_PYTHON set "PYCMD="%TESTLAB_PYTHON%""
if not defined PYCMD call :try_python "py -3.12"
if not defined PYCMD call :try_python "py -3.13"
if not defined PYCMD call :try_python "py -3"
if not defined PYCMD call :try_python "python"
if not defined PYCMD (
    echo TestLab: Python was not found.
    echo Install Python 3.12 from https://www.python.org/downloads/ ^(no administrator rights needed:
    echo choose "Install for me only"^) and run scripts\setup.bat again.
    goto end_fail
)

echo Using: %PYCMD%
%PYCMD% "%REPO_DIR%\scripts\devenv.py" setup %*
if errorlevel 1 goto end_fail
pause
exit /b 0

:end_fail
echo.
echo Setup did not finish - see the messages above.
pause
exit /b 1

:try_python
rem The Microsoft Store "python" alias fails this test, so it is skipped.
%~1 -c "import sys; sys.exit(sys.version_info < (3, 12))" >nul 2>&1
if not errorlevel 1 set "PYCMD=%~1"
exit /b 0
