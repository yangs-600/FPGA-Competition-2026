@echo off
setlocal
cd /d "%~dp0"
"%~dp0runtime\python.exe" -I -S -X utf8 "%~dp0run_current_cases.py" --package "%~dp0." %*
set "case_exit=%errorlevel%"
echo.
echo Validation exit code: %case_exit%
if "%~1"=="" pause
exit /b %case_exit%
