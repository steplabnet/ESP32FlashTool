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

## Lingua

Il flash tool è in italiano o in inglese: si sceglie in **Opzioni → Lingua / Language**
(cambia subito, senza riavvio) e viene salvata in `config.json`. Al primo avvio vale la
lingua di Windows (italiano se Windows è in italiano, altrimenti inglese). I testi sono in
`i18n.py`; `python i18n.py` controlla che ogni testo abbia la traduzione inglese.
Il manifest creator resta in italiano.

## Chiave di attivazione

Il flash tool carica l'elenco firmware solo con una chiave di attivazione
(`XXXX-XXXX-XXXX-XXXX`, chiesta al primo avvio o con **Aggiungi…** nel riquadro **Licenza** della scheda **Opzioni**). Ogni
chiave è un file `https://drive.steplab.net/esp32/<CHIAVE>.json` con il server firmware predefinito:

```json
{"server_url": "http://100.42.178.156/init", "name": "Nome cliente"}
```

Si possono salvare più chiavi, una per cliente: l'elenco **Licenza** (scheda **Opzioni**) mostra `nome — chiave` e,
scegliendone una, il programma passa al suo server e ricarica l'elenco firmware. **Rimuovi**
toglie la chiave in uso da questo PC. Un server scelto a mano vale solo per la chiave con cui è
stato scelto. In `config.json`: `keys` (elenco delle chiavi) e `activation_key` (quella in uso);
il `config.json` delle versioni con una sola chiave viene convertito da solo.

All'avvio, dopo la verifica degli aggiornamenti, il programma rilegge i file di tutte le chiavi:
se il `server_url` della chiave in uso è cambiato (e l'utente non ha scelto a mano un altro
server) ricarica l'elenco. Senza connessione usa l'ultimo server noto. Se il file non esiste più
la chiave non è valida: il programma la toglie dall'elenco (se era in uso passa a un'altra, o ne
chiede una nuova). I file `.json` non vanno in cache sul CDN, quindi modifiche e revoche valgono
subito.

Le chiavi si gestiscono con il **license tool** (`license_tool.py`, `dist\ST_ESP32_license_tool.exe`):
nome del cliente e server firmware → **Crea e carica** carica `<CHIAVE>.json` via SFTP
(`storage.bunnycdn.com`, cartella `esp32/`), lo verifica dall'URL pubblico e copia la chiave negli
appunti; una copia resta in `keys\` accanto al programma. L'elenco mostra le licenze sul server;
**Revoca…** cancella il file della chiave scelta. La password SFTP viene chiesta al primo uso e
salvata in `%APPDATA%\ST_ESP32_license_tool\config.json`.

In alternativa, da riga di comando (file in `dist\keys\`, da copiare a mano sul server):

```
.venv\Scripts\python activation.py http://100.42.178.156/init "Nome cliente"
```

## Aggiornamento automatico del flash tool

All'avvio, se c'è connessione, il flash tool legge
`https://drive.steplab.net/esp32/ST_ESP32_flash_tool.json` (`updater.py`); se la versione
indicata è più recente della sua (`VERSION` in `installer.py`) propone **Scarica** o **Salta**.
Scaricato e verificato con sha256, il nuovo eseguibile sostituisce quello in uso e il
programma si riavvia; se la cartella del programma non è scrivibile viene salvato in Download.

Per pubblicare una nuova versione:
1. aumentare `VERSION` in `installer.py`;
2. eseguire `build_exe.bat`, che crea anche `dist\ST_ESP32_flash_tool_<versione>.exe` e
   `dist\ST_ESP32_flash_tool.json` (versione, nome del file, dimensione, sha256; il campo
   `notes`, facoltativo, compare nel messaggio);
3. copiare in `https://drive.steplab.net/esp32/` prima `ST_ESP32_flash_tool_<versione>.exe`,
   poi `ST_ESP32_flash_tool.json`. Ogni versione deve avere il suo nome di file: il CDN tiene
   in cache gli `.exe` per 30 giorni, quindi un file sovrascritto verrebbe servito vecchio.
