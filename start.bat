@echo off
cd /d "%~dp0"
echo ===============================================
echo Cleaning up port 5000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :5000 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>nul
)
echo Starting Student Buddy Flask Server...
echo.
echo Open this URL in your web browser:
echo https://127.0.0.1:5000
echo ===============================================
python -u app.py
if %errorlevel% neq 0 (
    echo.
    echo Press any key to exit...
    pause >nul
)
