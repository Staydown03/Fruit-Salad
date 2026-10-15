@echo off
cd /d "%~dp0"
echo === FRUIT setup ===
where python >nul 2>nul || (echo Python 3.12 or newer is required: https://www.python.org/downloads/ & pause & exit /b 1)
if not exist .venv\Scripts\python.exe (
  echo Creating the Python environment in .venv ...
  python -m venv .venv || (pause & exit /b 1)
)
echo Installing Python packages ...
.venv\Scripts\python.exe -m pip install -r requirements.txt || (pause & exit /b 1)
where ffmpeg >nul 2>nul
if errorlevel 1 if not exist "%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*" (
  echo Installing ffmpeg with winget ...
  winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
)
if not exist client_secret.json echo NOTE: save your Google OAuth "Desktop app" client file in this folder as client_secret.json
echo.
echo Done. Start FRUIT with "Start FRUIT.bat".
pause
