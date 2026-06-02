@echo off
cd /d "%~dp0"
echo ===============================================
echo Starting Student Buddy Flask Server...
echo Please keep this command prompt open while using the app.
echo ===============================================
python app.py
if %errorlevel% neq 0 (
    echo.
    echo Press any key to exit...
    pause >nul
)
