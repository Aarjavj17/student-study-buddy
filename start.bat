@echo off
cd /d "%~dp0"
echo ===============================================
echo Starting Student Buddy Flask Server...
echo.
echo Open this URL in your web browser:
echo http://127.0.0.1:5000
echo ===============================================
python -u app.py
if %errorlevel% neq 0 (
    echo.
    echo Press any key to exit...
    pause >nul
)
