# ST ESP32 Flash Tool

Applicazione Python (Tkinter) per caricare il firmware su ESP32:
**Centrale Light** (`Solaria_centrale_light_ms`) e **Modulo Pompa** (`ModuloPompe2022`).

## Setup

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

## 1. Preparare i pacchetti firmware

```
.venv\Scripts\python prepare_firmware.py            # copia i binari già compilati
.venv\Scripts\python prepare_firmware.py --build    # compila prima con PlatformIO
.venv\Scripts\python prepare_firmware.py moduloPompa
```

Per ogni prodotto crea `firmware/<cartella>/` con bootloader, partizioni, boot_app0,
firmware e immagine filesystem (LittleFS / SPIFFS da `data/`), più `manifest.json`
(offset, dimensione e sha256 di ogni file, chip e scheda di compilazione).
Il chip di ogni prodotto è la voce `"chip"` in `PRODUCTS` (`esp32`, `esp32s3`, ...).

## 2. Definire chip e schede supportati

```
.venv\Scripts\python manifest_creator.py
```

Il catalogo `index.json` elenca i prodotti; per ognuno, le combinazioni
**chip ESP32 + tipo di scheda** supportate, ciascuna con la sua cartella remota
(relativa all'URL base, es. `moduloPompa_s3`, oppure un URL completo).
Nella finestra di una scheda, **Da cartella locale…** prende cartella, chip e scheda
da una cartella creata da `prepare_firmware.py`. **Verifica cartelle** legge il
`manifest.json` di ogni cartella dal server e segnala cartelle mancanti o firmware
compilato per un altro chip. Il catalogo si salva di default in `firmware/index.json`.

Con una scheda collegata al PC, **Rileva** (riquadro *ESP32 collegato*) legge il
chip, la flash e le caratteristiche e li aggiunge all'elenco **Chip rilevati**;
**Nuova scheda** crea una scheda del prodotto selezionato con il chip scelto
nell'elenco. Il tipo di scheda va sempre indicato a mano: dal chip non si ricava.

## 3. Pubblicare sul server

Copiare `index.json` e le sottocartelle di `firmware/` sotto l'URL base del server:

```
https://server/base/index.json
https://server/base/ModuloCentrale/manifest.json
https://server/base/ModuloCentrale/firmware.bin ...
https://server/base/moduloPompa/manifest.json
https://server/base/moduloPompa/firmware.bin ...
```

Senza `index.json` il flash tool legge solo le cartelle `ModuloCentrale` e
`moduloPompa` (`LEGACY_FOLDERS` in `installer.py`).

## 4. Caricare il firmware

```
.venv\Scripts\python installer.py
```

Si sceglie il **Chip** (o lo si legge dalla scheda collegata con **Rileva chip**)
e poi la **Scheda**: l'elenco mostra, per quel chip, ogni tipo di scheda con il
prodotto e la versione del firmware (es. `esp32dev — Modulo Pompa (MP.26.10.23.bx)`).
Chip e scheda scelti vengono riproposti all'avvio successivo.

L'URL base predefinito è `http://100.42.178.156/init` (`DEFAULT_SERVER_URL`
in `catalog.py`). Se l'utente ne inserisce un altro e preme **Carica elenco**,
quell'URL viene salvato e riproposto all'avvio; tornando all'URL predefinito il
valore salvato viene rimosso. I file scaricati sono verificati con sha256 e tenuti in cache.

Impostazioni (`config.json`) e cache (`cache\`) stanno accanto all'eseguibile (o a
`installer.py`). Se lì non si può scrivere, ad esempio in `C:\Program Files`, il programma
usa `%APPDATA%\ST_ESP32_flash_tool\config.json` e `%LOCALAPPDATA%\ST_ESP32_flash_tool\cache`.
Un `config.json` in `%APPDATA%` salvato dalle versioni precedenti viene letto finché non
esiste quello accanto all'eseguibile.

- **Aggiornamento firmware**: scrive bootloader, partizioni, boot_app0 e app
  (come `pio run -t upload`). Configurazione e file del dispositivo restano.
- **Installazione completa**: cancella tutta la flash e scrive anche il filesystem (modalità predefinita).
  In **File aggiuntivi nel filesystem** si possono scegliere file e cartelle locali: prima del
  caricamento l'immagine del filesystem viene estratta, i file vengono aggiunti (o sostituiscono
  quelli con lo stesso percorso) e l'immagine viene ricostruita (`fs_image.py`, con
  `mklittlefs.exe` / `mkspiffs.exe` di PlatformIO in `tools/`, inclusi nell'eseguibile).

## Eseguibile Windows

Eseguire `build_exe.bat`: crea `dist\ST_ESP32_flash_tool.exe` e
`dist\ST_ESP32_manifest_creator.exe`, file unici che non richiedono Python e
possono essere copiati su qualsiasi PC Windows.
I driver USB-seriale della scheda (CP210x / CH340) vanno installati a parte.
