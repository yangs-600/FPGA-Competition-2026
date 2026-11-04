@echo off
setlocal
"%~dp0runtime\python.exe" -I -S -B -X utf8 -u "%~dp0launch_demo.py" --mode measurements --package "%~dp0." %*
exit /b %errorlevel%
