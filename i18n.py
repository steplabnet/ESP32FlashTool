"""
Lingua dell'interfaccia del flash tool: italiano o inglese.

I testi nel codice sono in italiano e passano da tr():
    tr("Rilevato {chip} su {port}", chip="ESP32", port="COM5")
con l'inglese scelto, tr() li cerca in EN (chiave = testo italiano esatto, segnaposti
compresi); un testo senza traduzione resta in italiano. I segnaposti {nome} sono
riempiti con str.format, quindi le graffe letterali vanno scritte {{ }}.

Ogni testo nuovo va aggiunto a EN: lo controlla `python i18n.py`, che elenca le
chiamate tr() del progetto senza traduzione.
"""

import ctypes
import sys

LANGUAGES = {"it": "Italiano", "en": "English"}
DEFAULT = "it"

_language = DEFAULT


def system_language():
    """"it" se Windows è in italiano, altrimenti "en"."""
    try:
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return "it" if lang_id & 0x3FF == 0x10 else "en"  # 0x10 = LANG_ITALIAN
    except (AttributeError, OSError):
        return DEFAULT


def set_language(code):
    global _language
    _language = code if code in LANGUAGES else DEFAULT


def language():
    return _language


def tr(text, **values):
    if _language == "en":
        text = EN.get(text, text)
    return text.format(**values) if values else text


EN = {
    # theme.py: pulsanti dei dialoghi
    "Annulla": "Cancel",
    "OK": "OK",
    "No": "No",
    "Sì": "Yes",
    "Riprova": "Retry",

    # schede, riquadri, etichette e pulsanti
    "Dispositivo": "Device",
    "Opzioni": "Options",
    "Log": "Log",
    "Connessione": "Connection",
    "Server": "Server",
    "Carica elenco": "Load list",
    "Porta COM": "COM port",
    "Aggiorna": "Refresh",
    "Chip": "Chip",
    "Rileva chip": "Detect chip",
    "Scheda": "Board",
    "Velocità": "Speed",
    "Licenza": "Licence",
    "Aggiungi…": "Add…",
    "non attivato": "not activated",
    "Modalità": "Mode",
    "Aggiornamento firmware — mantiene configurazione e file del dispositivo":
        "Firmware update — keeps the device configuration and files",
    "Installazione completa — cancella tutta la flash e scrive anche il filesystem (data/)":
        "Full installation — erases the whole flash and also writes the filesystem (data/)",
    "File aggiuntivi nel filesystem": "Extra files in the filesystem",
    "Aggiungi file…": "Add files…",
    "Aggiungi cartella…": "Add folder…",
    "Rimuovi": "Remove",
    "Solo con l'installazione completa: i file vengono inseriti nel filesystem del firmware "
    "prima del caricamento. Un file va nella radice; di una cartella si copia il contenuto. "
    "Un file con lo stesso percorso sostituisce quello del firmware.":
        "Full installation only: the files are put into the firmware filesystem before "
        "flashing. A file goes in the root; for a folder, its contents are copied. A file "
        "with the same path replaces the firmware's one.",
    "[cartella] {path}  (contenuto)": "[folder] {path}  (contents)",
    "File da aggiungere al filesystem": "Files to add to the filesystem",
    "Cartella da copiare nel filesystem": "Folder to copy into the filesystem",
    "Carica firmware": "Flash firmware",
    "Offline": "Offline",
    "Lingua: {name}": "Language: {name}",
    "carica l'elenco dal server": "load the list from the server",

    # porte e rilevamento
    "Nessuna scheda ESP32 trovata: collegala e premi Aggiorna":
        "No ESP32 board found: connect it and press Refresh",
    "Porte trovate: {ports}": "Ports found: {ports}",
    "Dati seriali ricevuti su: {ports}": "Serial data received on: {ports}",
    "Scheda rilevata su {port}": "Board detected on {port}",
    "Collega la scheda e seleziona la porta COM.\n"
    "Se la porta non compare nell'elenco, premi Aggiorna.":
        "Connect the board and select the COM port.\n"
        "If the port is not in the list, press Refresh.",
    "Rilevamento chip su {port}…": "Detecting chip on {port}…",
    "Rilevamento chip su {port}": "Detecting chip on {port}",
    "Chip su {port}: {info}": "Chip on {port}: {info}",
    "Rilevato {chip} su {port}: scegli la scheda": "{chip} detected on {port}: choose the board",
    "Rilevato {chip} su {port}": "{chip} detected on {port}",
    "Sul server non c'è nessun firmware per {chip}.": "The server has no firmware for {chip}.",
    "ATTENZIONE: {error}": "WARNING: {error}",
    "Chip non rilevato": "Chip not detected",
    "ERRORE rilevamento chip: {error}": "ERROR detecting chip: {error}",
    "Impossibile leggere il chip:\n{error}": "Unable to read the chip:\n{error}",

    # server ed elenco firmware
    "Inserisci l'URL del server firmware": "Enter the firmware server URL",
    "Lettura elenco da {url}…": "Reading list from {url}…",
    "Server {url} non raggiungibile ({error}): uso i firmware in cache":
        "Server {url} unreachable ({error}): using cached firmware",
    "nessun prodotto nel catalogo": "no products in the catalogue",
    "non disponibile — {error}": "not available — {error}",
    "Offline — {count} firmware disponibili in cache": "Offline — {count} firmware available in cache",
    "{count} firmware disponibili su {url}": "{count} firmware available on {url}",
    "Server non raggiungibile": "Server unreachable",
    "ERRORE lettura {url}: {error}": "ERROR reading {url}: {error}",
    "Impossibile leggere l'elenco firmware da\n{url}\n\n{error}":
        "Unable to read the firmware list from\n{url}\n\n{error}",
    "cartelle predefinite ({file} assente)": "default folders ({file} missing)",
    "non presente in cache": "not in cache",
    "firmware in cache incompleto": "cached firmware incomplete",
    "cache (offline)": "cache (offline)",
    "il firmware in {folder} è per {chip}": "the firmware in {folder} is for {chip}",
    "(preparato {date})": "(prepared {date})",
    "{file} non valido: manca l'elenco 'products'": "invalid {file}: the 'products' list is missing",
    "{file} creato da una versione più recente (formato {format}): aggiorna il programma":
        "{file} was created by a newer version (format {format}): update the program",

    # chiave di attivazione
    "Inserisci la chiave di attivazione (XXXX-XXXX-XXXX-XXXX).\n"
    "Per la verifica serve la connessione a internet.":
        "Enter the activation key (XXXX-XXXX-XXXX-XXXX).\n"
        "An internet connection is needed to verify it.",
    'Programma non attivato: premi "{button}" nella scheda {tab}':
        'Program not activated: press "{button}" in the {tab} tab',
    '"{text}" non è una chiave valida.\nIl formato è XXXX-XXXX-XXXX-XXXX.':
        '"{text}" is not a valid key.\nThe format is XXXX-XXXX-XXXX-XXXX.',
    "Verifica della chiave di attivazione…": "Verifying the activation key…",
    "Licenza in uso: {key}": "Licence in use: {key}",
    "Licenza rimossa: {key}": "Licence removed: {key}",
    "Rimuovere la licenza {key} da questo computer?\n"
    "Per usarla di nuovo andrà inserita un'altra volta.":
        "Remove the licence {key} from this computer?\n"
        "To use it again you will have to enter it again.",
    "Chiave di attivazione {key} non valida: {error}": "Activation key {key} not valid: {error}",
    "Chiave di attivazione non valida": "Activation key not valid",
    "La chiave {key} non è valida: {error}.": "The key {key} is not valid: {error}.",
    "Verifica chiave di attivazione non riuscita: {error}":
        "Activation key check failed: {error}",
    "Chiave non verificata: serve la connessione": "Key not verified: a connection is needed",
    "Impossibile verificare la chiave: controlla la connessione a internet.\n\n{error}":
        "Unable to verify the key: check the internet connection.\n\n{error}",
    "Programma attivato con la chiave {key}: server {server}":
        "Program activated with key {key}: server {server}",
    "formato non valido (XXXX-XXXX-XXXX-XXXX)": "invalid format (XXXX-XXXX-XXXX-XXXX)",
    "chiave non riconosciuta": "key not recognised",
    "file della chiave non valido: {error}": "invalid key file: {error}",
    "nel file della chiave manca server_url": "server_url is missing from the key file",

    # aggiornamento del programma
    "Verifica aggiornamenti non riuscita: {error}": "Update check failed: {error}",
    "Nuova versione del programma disponibile: {version}":
        "New program version available: {version}",
    "È disponibile la versione {version} di {app} (in uso: {current}).":
        "Version {version} of {app} is available (installed: {current}).",
    "Novità:": "What's new:",
    "Scaricarla ora?": "Download it now?",
    "Salta": "Skip",
    "Scarica": "Download",
    "Download della versione {version}…": "Downloading version {version}…",
    "Versione {version} scaricata: {path}": "Version {version} downloaded: {path}",
    "Versione {version} scaricata": "Version {version} downloaded",
    "La versione {version} è stata salvata in\n{path}\n\n"
    "Chiudi il programma e avvia il nuovo file.":
        "Version {version} was saved to\n{path}\n\nClose the program and start the new file.",
    "installazione non riuscita: {error}": "installation failed: {error}",
    "Versione {version} installata: il programma si riavvia.":
        "Version {version} installed: the program will restart.",
    "Aggiornamento non riuscito": "Update failed",
    "ERRORE aggiornamento: {error}": "ERROR updating: {error}",
    "Impossibile scaricare la nuova versione:\n{error}":
        "Unable to download the new version:\n{error}",
    "{file}: mancano version o file": "{file}: version or file is missing",

    # caricamento del firmware
    "Scegli chip e scheda da caricare.": "Choose the chip and board to flash.",
    "Sulla {port} è collegato un {detected}, ma il firmware scelto è per {chip}.":
        "{port} has a {detected} connected, but the chosen firmware is for {chip}.",
    "Offline: in cache manca {files}.\n\n"
    "Per l'installazione completa serve la connessione; l'aggiornamento firmware si può fare.":
        "Offline: {files} missing from the cache.\n\n"
        "A full installation needs a connection; a firmware update is possible.",
    "Questo pacchetto non contiene il filesystem: i file aggiuntivi non si possono caricare.":
        "This package has no filesystem: the extra files cannot be flashed.",
    "Questo pacchetto non contiene il filesystem: dopo la cancellazione le pagine web "
    "mancheranno. Continuare?":
        "This package has no filesystem: after the erase the web pages will be missing. "
        "Continue?",
    "File aggiuntivi non validi:\n{error}": "Invalid extra files:\n{error}",
    "Verranno aggiunti {count} file al filesystem.": "{count} files will be added to the filesystem.",
    "Installazione completa di {product} ({target}) su {port}:\n"
    "tutta la flash verrà cancellata, comprese configurazione e WiFi.":
        "Full installation of {product} ({target}) on {port}:\n"
        "the whole flash will be erased, including configuration and WiFi.",
    "Continuare?": "Continue?",
    "Download {name} {version}…": "Downloading {name} {version}…",
    "{dir} non scrivibile: cache in {root}": "{dir} not writable: cache in {root}",
    "{file}: già in cache": "{file}: already in cache",
    "{file}: checksum non valido, download corrotto": "{file}: invalid checksum, corrupted download",
    "Aggiunta dei file al filesystem…": "Adding the files to the filesystem…",
    "File aggiunti a {file}:": "Files added to {file}:",
    "Caricamento {name} su {port}…": "Flashing {name} on {port}…",
    "Cancellazione della flash in corso (può richiedere fino a un minuto)…":
        "Erasing the flash (this can take up to a minute)…",
    "Errore": "Error",
    "ERRORE: {error}": "ERROR: {error}",
    "Caricamento non riuscito:\n{error}": "Flashing failed:\n{error}",
    "Completato — la scheda è stata riavviata": "Done — the board has been restarted",
    "Completato.": "Done.",
    "Firmware caricato correttamente.": "Firmware flashed successfully.",

    # esp_device.py
    "Controlla connessione, cavo e porta.": "Check the connection, cable and port.",
    "L'ESP32 non è entrato in modalità programmazione: alcune schede non ci entrano da sole "
    "e vanno avviate a mano.\n\n"
    "1. Controlla che la porta sia quella della scheda.\n"
    "2. Tieni premuto BOOT (IO0), premi e rilascia RESET (EN), poi rilascia BOOT.\n"
    "3. Premi subito \"{button}\".":
        "The ESP32 did not enter programming mode: some boards don't do it by themselves "
        "and must be started by hand.\n\n"
        "1. Check that the port is the board's one.\n"
        "2. Hold BOOT (IO0), press and release RESET (EN), then release BOOT.\n"
        "3. Press \"{button}\" right away.",
    "Se non funziona ancora, prova la velocità 115200.":
        "If it still doesn't work, try speed 115200.",
    "Nota: {message}": "Note: {message}",
    "Attenzione: {message}": "Warning: {message}",
    "Errore: {message}": "Error: {message}",

    # fs_image.py
    "{source}: file o cartella non trovati": "{source}: file or folder not found",
    "/{rel}: percorso troppo lungo per SPIFFS (massimo {max} caratteri, «/» compreso)":
        "/{rel}: path too long for SPIFFS (at most {max} characters, «/» included)",
    "{part}: nome troppo lungo per LittleFS (massimo {max} caratteri)":
        "{part}: name too long for LittleFS (at most {max} characters)",
    "manca {tool}": "{tool} is missing",
    "{tool} non riuscito:\n{tail}": "{tool} failed:\n{tail}",
    "{image}: filesystem non riconosciuto (attesi LittleFS o SPIFFS)":
        "{image}: unknown filesystem (expected LittleFS or SPIFFS)",
    "nessun file da aggiungere": "no files to add",
    "sostituito": "replaced",
    "aggiunto": "added",
    "I file occupano {used} KB su {size} KB del filesystem: forse non ci stanno.":
        "The files take {used} KB of the {size} KB filesystem: they may not fit.",
}


def _missing():
    """Le chiamate tr("...") del progetto senza traduzione in EN: [(file, riga, testo)]."""
    import ast
    from pathlib import Path
    found = []
    for path in sorted(Path(__file__).resolve().parent.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("tr", "_t")
                    and node.args and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value not in EN):
                found.append((path.name, node.lineno, node.args[0].value))
    return found


def _wrong_placeholders():
    """Le traduzioni con segnaposti {nome} diversi dal testo italiano."""
    import string

    def fields(text):
        return sorted(f for _, f, _, _ in string.Formatter().parse(text) if f)
    return [(it, en) for it, en in EN.items() if fields(it) != fields(en)]


if __name__ == "__main__":
    missing = _missing()
    for name, line, text in missing:
        print(f"{name}:{line}: manca la traduzione di {text!r}")
    wrong = _wrong_placeholders()
    for it, en in wrong:
        print(f"segnaposti diversi: {it!r} -> {en!r}")
    print(f"{len(EN)} traduzioni, {len(missing)} mancanti, {len(wrong)} con segnaposti diversi")
    sys.exit(1 if missing or wrong else 0)
