@echo off
rem Crea dist\ST_ESP32_flash_tool.exe e dist\ST_ESP32_manifest_creator.exe
rem (eseguibili unici, non richiedono Python).
rem PyInstaller si avvia con "python -m": i lanciatori .exe della .venv contengono il
rem percorso in cui e' stata creata e smettono di funzionare se la cartella viene spostata.
cd /d "%~dp0"
if not exist .venv python -m venv .venv
.venv\Scripts\python -m pip install -q -r requirements.txt pyinstaller || exit /b 1
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed --name ST_ESP32_flash_tool ^
    --collect-data esptool --collect-submodules esptool ^
    --add-binary "%~dp0tools\mklittlefs.exe;tools" --add-binary "%~dp0tools\mkspiffs.exe;tools" ^
    --workpath build --specpath build installer.py || exit /b 1
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed --name ST_ESP32_manifest_creator ^
    --collect-data esptool --collect-submodules esptool ^
    --workpath build --specpath build manifest_creator.py || exit /b 1
echo.
echo Creati dist\ST_ESP32_flash_tool.exe e dist\ST_ESP32_manifest_creator.exe
