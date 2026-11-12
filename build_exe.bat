@echo off
rem Crea dist\ST_ESP32_flash_tool.exe, dist\ST_ESP32_manifest_creator.exe e dist\ST_ESP32_license_tool.exe
rem (eseguibili unici, non richiedono Python).
rem PyInstaller si avvia con "python -m": i lanciatori .exe della .venv contengono il
rem percorso in cui e' stata creata e smettono di funzionare se la cartella viene spostata.
cd /d "%~dp0"
if not exist .venv python -m venv .venv
.venv\Scripts\python -m pip install -q -r requirements.txt pyinstaller || exit /b 1
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed --name ST_ESP32_flash_tool ^
    --collect-data esptool --collect-submodules esptool ^
    --add-binary "%~dp0tools\mklittlefs.exe;tools" --add-binary "%~dp0tools\mkspiffs.exe;tools" ^
    --add-data "%~dp0logo-200x40-1.png;." ^
    --workpath build --specpath build installer.py || exit /b 1
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed --name ST_ESP32_manifest_creator ^
    --collect-data esptool --collect-submodules esptool ^
    --add-data "%~dp0logo-200x40-1.png;." ^
    --workpath build --specpath build manifest_creator.py || exit /b 1
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --windowed --name ST_ESP32_license_tool ^
    --add-data "%~dp0logo-200x40-1.png;." ^
    --workpath build --specpath build license_tool.py || exit /b 1
rem aggiornamento automatico: copia con la versione nel nome e manifest (versione = VERSION in installer.py)
.venv\Scripts\python updater.py dist\ST_ESP32_flash_tool.exe || exit /b 1
echo.
echo Creati dist\ST_ESP32_flash_tool.exe, dist\ST_ESP32_manifest_creator.exe e dist\ST_ESP32_license_tool.exe
echo Per pubblicare l'aggiornamento copiare in https://drive.steplab.net/esp32/
echo   prima dist\ST_ESP32_flash_tool_^<versione^>.exe, poi dist\ST_ESP32_flash_tool.json
