@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Run setup.bat first. & pause & exit /b 1)
rem use ffmpeg installed by "winget install Gyan.FFmpeg" if it isn't already on PATH
where ffmpeg >nul 2>nul || for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*") do for /d %%B in ("%%D\ffmpeg-*") do set "PATH=%%B\bin;%PATH%"
".venv\Scripts\python.exe" FRUIT.py
pause
