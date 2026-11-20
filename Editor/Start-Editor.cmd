@echo off
setlocal
"%~dp0runtime\python.exe" -B "%~dp0editor.py" %*
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)
