@echo off
cd /d "%~dp0"
rem Builds dist\FRUIT\FRUIT.exe. Run setup.bat once first.
.venv\Scripts\python.exe -m pip install -q pyinstaller || (pause & exit /b 1)
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --console --name FRUIT --icon images\icon_FRUIT.ico --paths . --hidden-import dashboard --collect-submodules TOOLS --collect-data googleapiclient --collect-data imageio_ffmpeg --copy-metadata imageio --copy-metadata imageio_ffmpeg --copy-metadata moviepy --copy-metadata proglog --copy-metadata tqdm --copy-metadata google-api-python-client FRUIT.py || (pause & exit /b 1)
rem files FRUIT opens relative to its own folder
xcopy /e /i /y /q images dist\FRUIT\images >nul
mkdir dist\FRUIT\input\temp 2>nul
copy /y input\temp\concatenate.txt dist\FRUIT\input\temp\ >nul
mkdir dist\FRUIT\TOOLS\recordings 2>nul
copy /y start.wav dist\FRUIT\ >nul
copy /y client_secret.example dist\FRUIT\ >nul
copy /y README.md dist\FRUIT\ >nul
copy /y LICENSE.txt dist\FRUIT\ >nul
echo.
echo Built dist\FRUIT - zip that folder to share it.
pause
