# Strumenti per le immagini filesystem

Usati da `fs_image.py` per aggiungere file all'immagine del filesystem prima del
caricamento, e inclusi in `ST_ESP32_flash_tool.exe` da `build_exe.bat`.
Sono gli stessi programmi con cui PlatformIO (platform espressif32 6.x, framework
Arduino) crea `littlefs.bin` e `spiffs.bin` con `pio run -t buildfs`.

| File | Origine | Versione | Licenza |
|------|---------|----------|---------|
| `mklittlefs.exe` | PlatformIO `tool-mklittlefs`, https://github.com/earlephilhower/mklittlefs | 1.203.210628 | MIT |
| `mkspiffs.exe` | PlatformIO `tool-mkspiffs` (`mkspiffs_espressif32_arduino.exe`), https://github.com/igrr/mkspiffs | 2.230.0 | MIT |

Parametri usati per ESP32: pagina 256 byte, blocco 4096 byte, dimensione pari
all'immagine scaricata (= partizione filesystem).
