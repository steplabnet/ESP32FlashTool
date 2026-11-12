"""
ST ESP32 Flash Tool — carica il firmware sugli ESP32 (Centrale Light, Modulo Pompa).

I pacchetti firmware stanno su un server remoto, sotto l'URL base inserito
nella GUI:
    <url>/index.json                     catalogo creato con manifest_creator.py:
                                         prodotti, chip e schede supportati, cartelle
    <url>/<cartella>/manifest.json       offset, dimensione e sha256 di ogni immagine
    <url>/<cartella>/<file>.bin          (cartelle create da prepare_firmware.py)

Senza index.json vengono lette le cartelle predefinite (LEGACY_FOLDERS).
Nella GUI si sceglie il chip (o lo si rileva dalla scheda collegata) e poi la
scheda: ogni scheda dell'elenco è un prodotto del catalogo con la sua cartella.

L'URL base e le scelte della GUI vengono salvati in config.json accanto
all'eseguibile. I file scaricati sono verificati con sha256 e tenuti nella
cartella cache, sempre accanto all'eseguibile, con index.json e il manifest
dei firmware scaricati: senza connessione si usano quelli (in alto a destra
compare "Offline").
L'interfaccia è in italiano o in inglese (i18n.py), scelta nella scheda Opzioni.
Il flash avviene con esptool, nello stesso processo.
All'avvio, se c'è connessione, cerca una versione più recente del programma
(updater.py) e propone di scaricarla; poi rilegge i file delle chiavi di
attivazione (activation.py), che indicano il server firmware predefinito.
Si possono salvare più chiavi, una per cliente, e passare dall'una all'altra
dall'elenco "Licenza" della scheda Opzioni: ognuna ha il suo server. Senza chiave il programma la
chiede e non carica l'elenco firmware.
"""

import hashlib
import json
import os
import queue
import re
import sys
import tempfile
import threading
import tkinter as tk
import urllib.error
import urllib.request
from pathlib import Path
from tkinter import filedialog, ttk
from urllib.parse import urljoin

import esptool

import catalog
from catalog import CHIPS, DEFAULT_SERVER_URL, INDEX_FILE, base_url, chip_label, clean_url, target_label
import esp_device
import fs_image
import activation
import i18n
import theme
import updater
from i18n import tr
from esp_device import connect_hint, guess_port, is_connect_error, port_score

APP_TITLE = "ST ESP32 Flash Tool"
# versione del programma: aumentarla prima di pubblicare un nuovo eseguibile (vedi updater.py)
VERSION = "1.4.0"
BAUD_RATES = ["921600", "460800", "230400", "115200"]
DEFAULT_BAUD = "460800"
HTTP_TIMEOUT = 20
MANIFEST_FILE = "manifest.json"

# Server senza index.json: una sottocartella per prodotto (maiuscole/minuscole contano).
LEGACY_FOLDERS = {
    "ModuloCentrale": "Modulo Centrale Light",
    "moduloPompa": "Modulo Pompa",
}

MODE_UPDATE = "update"
MODE_FULL = "full"

# config.json e cache dei firmware accanto all'eseguibile (o a installer.py); se lì
# non si può scrivere, ad esempio in C:\Program Files, in %APPDATA% / %LOCALAPPDATA%.
if getattr(sys, "frozen", False):
    PROGRAM_DIR = Path(sys.executable).resolve().parent
else:
    PROGRAM_DIR = Path(__file__).resolve().parent
CONFIG_FILE = PROGRAM_DIR / "config.json"
CACHE_DIR = PROGRAM_DIR / "cache"
APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "ST_ESP32_flash_tool"
FALLBACK_CONFIG_FILE = APP_DIR / "config.json"
FALLBACK_CACHE_DIR = Path(os.environ.get("LOCALAPPDATA", APP_DIR)) / "ST_ESP32_flash_tool" / "cache"


def load_config():
    # il file in %APPDATA% vale finché non ne esiste uno accanto all'eseguibile:
    # così le impostazioni salvate dalle versioni precedenti non si perdono
    for path in (CONFIG_FILE, FALLBACK_CONFIG_FILE):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return {}


def migrate_config(config):
    """Chiavi salvate in config["keys"]: [{"key", "server_url", "name", "user_url"}].

    server_url e name vengono dal file della chiave; user_url è il server scelto a
    mano per quella chiave. config["activation_key"] è la chiave in uso. Le versioni
    con una sola chiave usavano key_server_url, key_name e server_url.
    """
    if not isinstance(config.get("keys"), list):
        key = config.get("activation_key")
        config["keys"] = []
        if key:
            entry = {"key": key, "server_url": config.get("key_server_url", ""),
                     "name": config.get("key_name", "")}
            if clean_url(config.get("server_url", "")):
                entry["user_url"] = clean_url(config["server_url"])
            config["keys"].append(entry)
    for name in ("key_server_url", "key_name", "server_url"):
        config.pop(name, None)
    keys = [k["key"] for k in config["keys"]]
    if config.get("activation_key") not in keys:
        config["activation_key"] = keys[0] if keys else None
    return config


def key_label(entry):
    """"Nome cliente — XXXX-XXXX-XXXX-XXXX"; senza nome solo la chiave."""
    return f"{entry['name']}  —  {entry['key']}" if entry.get("name") else entry["key"]


def cache_dir():
    """CACHE_DIR se vi si può scrivere, altrimenti FALLBACK_CACHE_DIR."""
    probe = CACHE_DIR / ".scrittura"
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"")
        probe.unlink()
        return CACHE_DIR
    except OSError:
        return FALLBACK_CACHE_DIR


def save_config(config):
    text = json.dumps(config, indent=2) + "\n"
    try:
        CONFIG_FILE.write_text(text, encoding="utf-8")
    except OSError:
        FALLBACK_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        FALLBACK_CONFIG_FILE.write_text(text, encoding="utf-8")


def cache_name(url):
    """Nome di file o cartella della cache per un URL (ogni server ha la sua)."""
    return re.sub(r"[^\w.-]+", "_", url).strip("_")


def index_cache_file(base):
    return f"{cache_name(base)}_{INDEX_FILE}"


def save_cached(path, text):
    """Scrive un file della cache; se non si può, si lavora comunque senza."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError:
        pass


def is_cached(path, img):
    """True se il file in cache esiste e ha lo sha256 del manifest."""
    expected = img.get("sha256")
    return bool(expected) and path.exists() and sha256_of(path) == expected


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": APP_TITLE})
    return urllib.request.urlopen(request, timeout=HTTP_TIMEOUT)


def fetch_json(url):
    with fetch(url) as response:
        return json.loads(response.read().decode("utf-8"))


def load_products(url):
    """Legge il catalogo del server e il manifest della cartella di ogni scheda.

    Ritorna (prodotti, origine). Ogni scheda riceve "url" e "manifest" (None se
    la cartella non è disponibile, con il motivo in "error").
    """
    base = base_url(url)
    try:
        with fetch(urljoin(base, INDEX_FILE)) as response:
            text = response.read().decode("utf-8")
        products = catalog.loads(text)["products"]
        save_cached(cache_dir() / index_cache_file(base), text)
        source = INDEX_FILE
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        products = legacy_products()
        source = tr("cartelle predefinite ({file} assente)", file=INDEX_FILE)

    for product in products:
        for target in product["targets"]:
            target["url"] = catalog.folder_url(base, target["folder"])
            target["manifest"] = None
            try:
                manifest = fetch_json(urljoin(target["url"], MANIFEST_FILE))
            except Exception as e:
                target["error"] = f"{type(e).__name__}: {e}"
                continue
            use_manifest(target, manifest)
    return products, source


def load_cached_products(url):
    """Come load_products, ma dalla cache: per lavorare senza connessione.

    Sono elencate solo le schede con il firmware già scaricato e integro (tutte
    le immagini tranne, al più, il filesystem); in "cached" i file presenti.
    """
    base = base_url(url)
    root = cache_dir()
    try:
        text = (root / index_cache_file(base)).read_text(encoding="utf-8")
        products = catalog.loads(text)["products"]
    except (OSError, ValueError):
        products = legacy_products()

    for product in products:
        for target in product["targets"]:
            target["url"] = catalog.folder_url(base, target["folder"])
            target["manifest"] = None
            folder = root / cache_name(target["url"])
            try:
                manifest = json.loads((folder / MANIFEST_FILE).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                target["error"] = tr("non presente in cache")
                continue
            cached = {img["file"] for img in manifest["images"]
                      if is_cached(folder / img["file"], img)}
            if any(img["role"] != "filesystem" and img["file"] not in cached
                   for img in manifest["images"]):
                target["error"] = tr("firmware in cache incompleto")
                continue
            target["cached"] = cached
            use_manifest(target, manifest)
    return products, tr("cache (offline)")


def legacy_products():
    # chip None: preso dal manifest della cartella
    return [{"name": label, "targets": [{"chip": None, "board": "", "folder": folder}]}
            for folder, label in LEGACY_FOLDERS.items()]


def use_manifest(target, manifest):
    """Assegna il manifest alla scheda se è per il suo chip, altrimenti scrive il motivo."""
    if target["chip"] is None:
        target["chip"] = manifest.get("chip", "esp32")
    elif manifest.get("chip", target["chip"]) != target["chip"]:
        target["error"] = tr("il firmware in {folder} è per {chip}", folder=target["folder"],
                             chip=chip_label(manifest["chip"]))
        return
    target["manifest"] = manifest


def describe(target):
    """Nome della scheda; per le cartelle predefinite illeggibili il chip non è noto."""
    return target_label(target) if target["chip"] else target["folder"]


def firmware_entries(products):
    """Le schede con firmware disponibile sul server, come coppie (prodotto, scheda)."""
    return [(p, t) for p in products for t in p["targets"] if t["manifest"]]


def entry_key(product, target):
    """Chiave salvata in config.json per riproporre la scheda all'avvio."""
    return f"{product['name']}|{target['chip']}|{target['board']}"


def entry_label(product, target):
    """"esp32dev — Modulo Pompa (MP.26.10.23.bx)"; senza tipo scheda solo il prodotto."""
    name = f"{target['board']} — {product['name']}" if target["board"] else product["name"]
    return f"{name}  ({target['manifest']['version']})"


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


class InstallerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_TITLE} {VERSION}")
        self.minsize(760, 520)
        theme.apply(self)

        self.events = queue.Queue()
        esp_device.set_logger(self.events)
        updater.cleanup()

        self.config_data = migrate_config(load_config())
        i18n.set_language(self.config_data.get("language") or i18n.system_language())
        theme.set_translator(tr)
        self.entries = []        # (prodotto, scheda) con firmware disponibile
        self.chips = []          # chip dell'elenco "Chip", nell'ordine mostrato
        self.board_entries = []  # voci dell'elenco "Scheda" per il chip scelto
        self.detected = None     # (porta, chip) dell'ultimo rilevamento
        self.ports = []
        self.port_auto = True  # False quando l'utente sceglie la porta a mano
        self.busy = False
        self.extras = []  # file e cartelle locali da aggiungere al filesystem
        self.status_before_erase = ""  # stato da ripristinare dopo la cancellazione
        self.closing = False  # True quando la finestra è chiusa per riavviare la nuova versione
        self.offline = False  # elenco firmware letto dalla cache

        # URL scelto dall'utente, altrimenti quello della chiave di attivazione
        self.url_var = tk.StringVar(value=self.server_for(self.active_key()))
        self.chip_info_var = tk.StringVar()
        self.port_var = tk.StringVar()
        self.baud_var = tk.StringVar(value=self.config_data.get("baud", DEFAULT_BAUD))
        self.mode_var = tk.StringVar(value=MODE_FULL)
        self.extras_var = tk.BooleanVar(value=self.config_data.get("extras", False))
        self.status_var = tk.StringVar(value=tr("Inserisci l'URL del server firmware"))

        self.build_ui()
        self.refresh_chips()
        self.refresh_ports()
        theme.center(self)
        self.after(100, self.poll_events)
        self.show_keys()
        if not self.active_key():
            self.after(300, self.ask_key)
        elif self.url_var.get():
            self.load_server()  # dall'ultimo URL noto: funziona anche offline
        keys = [entry["key"] for entry in self.keys()]
        threading.Thread(target=self.run_startup_checks, args=(keys,), daemon=True).start()

    # ── UI ────────────────────────────────────────────────────────────────────

    def build_ui(self):
        # in fondo, sempre visibili: pulsante, avanzamento, stato e logo
        footer = ttk.Frame(self, padding=(20, 12, 20, 12))
        footer.pack(side="bottom", fill="x")
        footer.columnconfigure(0, weight=1)
        ttk.Frame(self, style="Divider.TFrame", height=1).pack(side="bottom", fill="x")
        self.flash_button = ttk.Button(footer, text=tr("Carica firmware"), style="Primary.TButton",
                                       command=self.start_flash, cursor="hand2")
        self.flash_button.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        self.flash_button.state(["disabled"])
        self.progress = ttk.Progressbar(footer, maximum=100)
        self.progress.grid(row=1, column=0, columnspan=2, sticky="ew")
        ttk.Label(footer, textvariable=self.status_var, style="Status.TLabel").grid(
            row=2, column=0, sticky="w", pady=(8, 0))
        theme.brand(footer).grid(row=2, column=1, sticky="e", pady=(8, 0))

        # il resto è diviso in schede, ognuna scorre se la finestra è troppo bassa
        self.tabs = theme.Tabs(self)
        self.tabs.pack(fill="both", expand=True)
        # in alto a destra, sulla riga delle schede: visibile solo senza connessione
        self.offline_label = ttk.Label(self.tabs, text=tr("Offline"), style="Alert.TLabel")
        self.offline_label.grid(row=0, column=0, sticky="e", padx=(0, 20), pady=(8, 0))
        if not self.offline:
            self.offline_label.grid_remove()

        frame = self.tabs.add("Dispositivo", text=tr("Dispositivo"))
        frame.configure(padding=(20, 12, 20, 12))
        frame.columnconfigure(0, weight=1)
        device = theme.card(frame, tr("Connessione"))
        device.grid(row=0, column=0, sticky="ew")
        device.columnconfigure(1, weight=1)

        ttk.Label(device, text=tr("Server"), style="Card.TLabel").grid(
            row=0, column=0, sticky="w", pady=5, padx=(0, 12))
        url_entry = ttk.Entry(device, textvariable=self.url_var)
        url_entry.grid(row=0, column=1, sticky="ew", pady=5)
        url_entry.bind("<Return>", lambda _e: self.load_server())
        self.load_button = ttk.Button(device, text=tr("Carica elenco"), command=self.load_server)
        self.load_button.grid(row=0, column=2, sticky="ew", padx=(8, 0), pady=5)

        ttk.Label(device, text=tr("Porta COM"), style="Card.TLabel").grid(
            row=1, column=0, sticky="w", pady=5, padx=(0, 12))
        self.port_box = ttk.Combobox(device, textvariable=self.port_var, state="readonly")
        self.port_box.grid(row=1, column=1, sticky="ew", pady=5)
        self.port_box.bind("<<ComboboxSelected>>", lambda _e: self.port_changed())
        ttk.Button(device, text=tr("Aggiorna"), command=self.refresh_ports).grid(
            row=1, column=2, sticky="ew", padx=(8, 0), pady=5)

        ttk.Label(device, text=tr("Chip"), style="Card.TLabel").grid(
            row=2, column=0, sticky="w", pady=5, padx=(0, 12))
        self.chip_box = ttk.Combobox(device, state="readonly")
        self.chip_box.grid(row=2, column=1, sticky="ew", pady=5)
        self.chip_box.bind("<<ComboboxSelected>>", lambda _e: self.chip_changed())
        self.detect_button = ttk.Button(device, text=tr("Rileva chip"), command=self.start_detect)
        self.detect_button.grid(row=2, column=2, sticky="ew", padx=(8, 0), pady=5)
        ttk.Label(device, textvariable=self.chip_info_var, style="Card.Muted.TLabel").grid(
            row=3, column=1, columnspan=2, sticky="w")

        ttk.Label(device, text=tr("Scheda"), style="Card.TLabel").grid(
            row=4, column=0, sticky="w", pady=5, padx=(0, 12))
        self.board_box = ttk.Combobox(device, state="readonly")
        self.board_box.grid(row=4, column=1, columnspan=2, sticky="ew", pady=5)
        self.board_box.bind("<<ComboboxSelected>>", lambda _e: self.board_changed())

        ttk.Label(device, text=tr("Velocità"), style="Card.TLabel").grid(
            row=5, column=0, sticky="w", pady=5, padx=(0, 12))
        ttk.Combobox(device, textvariable=self.baud_var, values=BAUD_RATES,
                     state="readonly", width=10).grid(row=5, column=1, sticky="w", pady=5)

        frame = self.tabs.add("Opzioni", text=tr("Opzioni"))
        frame.configure(padding=(20, 12, 20, 12))
        frame.columnconfigure(0, weight=1)
        # licenze salvate, una per cliente: quella scelta decide il server firmware
        licence = theme.card(frame, tr("Licenza"))
        licence.grid(row=0, column=0, sticky="ew")
        licence.columnconfigure(0, weight=1)
        self.key_box = ttk.Combobox(licence, state="readonly")
        self.key_box.grid(row=0, column=0, sticky="ew")
        self.key_box.bind("<<ComboboxSelected>>", lambda _e: self.key_selected())
        self.key_button = ttk.Button(licence, text=tr("Aggiungi…"), command=self.ask_key)
        self.key_button.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.key_remove_button = ttk.Button(licence, text=tr("Rimuovi"), command=self.remove_key)
        self.key_remove_button.grid(row=0, column=2, sticky="ew", padx=(8, 0))

        modes = theme.card(frame, tr("Modalità"))
        modes.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        ttk.Radiobutton(modes, variable=self.mode_var, value=MODE_UPDATE, command=self.mode_changed,
                        style="Card.TRadiobutton",
                        text=tr("Aggiornamento firmware — mantiene configurazione e file "
                                "del dispositivo")
                        ).pack(anchor="w")
        ttk.Radiobutton(modes, variable=self.mode_var, value=MODE_FULL, command=self.mode_changed,
                        style="Card.TRadiobutton",
                        text=tr("Installazione completa — cancella tutta la flash e scrive "
                                "anche il filesystem (data/)")
                        ).pack(anchor="w")

        extras = theme.card(frame, tr("File aggiuntivi nel filesystem"))
        extras.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        extras.columnconfigure(0, weight=1)
        self.extras_switch = theme.card_switch(extras, self.extras_var, self.extras_toggled)
        # con l'interruttore spento resta solo il titolo; il riquadro vuoto si
        # ridimensiona solo se ha ancora almeno un widget in griglia
        ttk.Frame(extras, style="Inner.TFrame", height=1).grid(row=0, column=0, sticky="ew")
        self.extras_body = ttk.Frame(extras, style="Inner.TFrame")
        self.extras_body.grid(row=1, column=0, sticky="ew")
        self.extras_body.columnconfigure(0, weight=1)
        extra_box = theme.field_box(self.extras_body)
        extra_box.grid(row=0, column=0, rowspan=3, sticky="nsew")
        self.extra_list = tk.Listbox(extra_box, height=3, activestyle="none")
        self.extra_list.pack(fill="both", expand=True)
        self.extra_buttons = []
        for row, (text, command) in enumerate(((tr("Aggiungi file…"), self.add_extra_files),
                                               (tr("Aggiungi cartella…"), self.add_extra_folder),
                                               (tr("Rimuovi"), self.remove_extra))):
            button = ttk.Button(self.extras_body, text=text, command=command)
            button.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=(0, 4))
            self.extra_buttons.append(button)
        ttk.Label(self.extras_body, style="Card.Muted.TLabel", wraplength=640, justify="left",
                  text=tr("Solo con l'installazione completa: i file vengono inseriti nel "
                          "filesystem del firmware prima del caricamento. Un file va nella "
                          "radice; di una cartella si copia il contenuto. Un file con lo stesso "
                          "percorso sostituisce quello del firmware.")
                  ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # il nome di ogni lingua è scritto nella lingua stessa
        language = theme.card(frame, "Lingua / Language" if i18n.language() == "it"
                              else "Language / Lingua")
        language.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self.language_box = ttk.Combobox(language, state="readonly", width=16,
                                         values=list(i18n.LANGUAGES.values()))
        self.language_box.grid(row=0, column=0, sticky="w")
        self.language_box.current(list(i18n.LANGUAGES).index(i18n.language()))
        self.language_box.bind("<<ComboboxSelected>>", lambda _e: self.language_changed())

        frame = self.tabs.add("Log", scroll=False, text=tr("Log"))
        frame.configure(padding=(20, 12, 20, 12))
        log_box, self.log_text = theme.log_widget(frame, height=10)
        log_box.pack(fill="both", expand=True)

        # misure prese con i file aggiuntivi visibili: accendendo l'interruttore
        # la finestra non deve cambiare altezza
        self.tabs.fit()
        self.extras_toggled()

    def language_changed(self):
        """Nuova lingua: l'interfaccia viene ricreata subito, lo stato resta."""
        code = list(i18n.LANGUAGES)[self.language_box.current()]
        if code == i18n.language():
            return
        i18n.set_language(code)
        self.config_data["language"] = code
        save_config(self.config_data)
        log = self.log_text.get("1.0", "end-1c")
        port = self.port_box.current()
        for child in self.winfo_children():
            child.destroy()
        self.build_ui()
        self.tabs.select("Opzioni")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", log)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")
        self.show_ports(port)
        self.refresh_extras()
        self.refresh_chips()
        self.show_keys()
        self.status_var.set(tr("Lingua: {name}", name=i18n.LANGUAGES[code]))

    def refresh_chips(self, select=None):
        """Elenco "Chip": i chip che hanno almeno un firmware disponibile."""
        present = {t["chip"] for _p, t in self.entries}
        self.chips = [c for c in CHIPS if c in present] + sorted(present - set(CHIPS))
        self.chip_box["values"] = [chip_label(c) for c in self.chips]
        if not self.chips:
            self.chip_box.set(tr("carica l'elenco dal server"))
        else:
            current = self.selected_chip()
            for chip in (select, current, self.config_data.get("chip"), self.chips[0]):
                if chip in self.chips:
                    self.chip_box.current(self.chips.index(chip))
                    break
        self.refresh_boards()

    def refresh_boards(self):
        """Elenco "Scheda": tipo di scheda e prodotto di ogni firmware per il chip scelto."""
        previous = self.selected_entry()
        chip = self.selected_chip()
        self.board_entries = [(p, t) for p, t in self.entries if t["chip"] == chip]
        self.board_box["values"] = [entry_label(p, t) for p, t in self.board_entries]
        keys = [entry_key(p, t) for p, t in self.board_entries]
        if not keys:
            self.board_box.set("")
        else:
            wanted = (entry_key(*previous) if previous else None, self.config_data.get("board"))
            self.board_box.current(next((keys.index(k) for k in wanted if k in keys), 0))
        self.set_busy(self.busy)

    def set_busy(self, busy):
        self.busy = busy
        for button in (self.load_button, self.detect_button, self.key_button,
                       self.key_remove_button, self.key_box, self.language_box):
            button.state(["disabled"] if busy else ["!disabled"])
        if busy or not self.selected_entry():
            self.flash_button.state(["disabled"])
        else:
            self.flash_button.state(["!disabled"])
        self.mode_changed()

    def mode_changed(self):
        """I file aggiuntivi valgono solo con l'installazione completa."""
        enabled = self.mode_var.get() == MODE_FULL and not self.busy
        for button in self.extra_buttons:
            button.state(["!disabled"] if enabled else ["disabled"])
        self.extra_list.configure(state="normal" if enabled else "disabled")
        self.extras_switch.state(["disabled"] if self.busy else ["!disabled"])

    def extras_toggled(self):
        """Interruttore dei file aggiuntivi: spento li nasconde e non li carica."""
        if self.extras_var.get():
            self.extras_body.grid()
        else:
            self.extras_body.grid_remove()
        if self.config_data.get("extras", False) != self.extras_var.get():
            self.config_data["extras"] = self.extras_var.get()
            save_config(self.config_data)
        self.mode_changed()

    def refresh_extras(self):
        self.extra_list.configure(state="normal")
        self.extra_list.delete(0, "end")
        for source in self.extras:
            path = Path(source)
            self.extra_list.insert("end", tr("[cartella] {path}  (contenuto)", path=path)
                                   if path.is_dir()
                                   else f"{path.name}  —  {path.parent}")
        self.mode_changed()

    def add_extra_files(self):
        files = filedialog.askopenfilenames(parent=self, title=tr("File da aggiungere al filesystem"))
        self.extras += [f for f in files if f not in self.extras]
        self.refresh_extras()

    def add_extra_folder(self):
        folder = filedialog.askdirectory(parent=self, title=tr("Cartella da copiare nel filesystem"))
        if folder and folder not in self.extras:
            self.extras.append(folder)
        self.refresh_extras()

    def remove_extra(self):
        for index in reversed(self.extra_list.curselection()):
            del self.extras[index]
        self.refresh_extras()

    def chip_changed(self):
        self.config_data["chip"] = self.selected_chip()
        save_config(self.config_data)
        self.refresh_boards()
        self.board_changed()

    def board_changed(self):
        entry = self.selected_entry()
        if not entry:
            return
        product, target = entry
        self.config_data["board"] = entry_key(product, target)
        save_config(self.config_data)
        manifest = target["manifest"]
        self.append_log(f"\n{product['name']} — {target_label(target)}: {manifest['version']} "
                        + tr("(preparato {date})", date=manifest.get("prepared", "?")))
        for img in manifest["images"]:
            self.append_log(f"  {img['offset']:>9}  {img['file']}")

    def port_changed(self):
        self.port_auto = False
        self.chip_info_var.set("")
        self.detected = None

    def show_ports(self, index=None):
        """Mostra self.ports nell'elenco "Porta COM" e sceglie quella all'indice dato."""
        self.port_box["values"] = [f"{p.device}  —  {p.description}" for p in self.ports]
        if not self.ports:
            self.port_var.set("")
        elif index is not None and 0 <= index < len(self.ports):
            self.port_box.current(index)

    def refresh_ports(self):
        self.ports = esp_device.esp_ports()
        self.port_auto = True
        self.chip_info_var.set("")
        self.detected = None
        if not self.ports:
            self.show_ports()
            self.status_var.set(tr("Nessuna scheda ESP32 trovata: collegala e premi Aggiorna"))
            return
        self.status_var.set(tr("Porte trovate: {ports}",
                               ports=", ".join(p.device for p in self.ports)))
        guess = guess_port(self.ports)
        self.show_ports(guess if guess is not None else 0)
        # poi ascolta le porte USB: quella su cui l'ESP32 sta scrivendo vince
        usb = [p.device for p in self.ports if port_score(p)]
        if usb and not self.busy:
            threading.Thread(target=self.run_probe_ports, args=(usb,), daemon=True).start()

    def run_probe_ports(self, devices):
        active = [d for d in devices if esp_device.port_receives_data(d)]
        self.events.put(("ports_probed", active))

    def ports_probed(self, active):
        if not active:
            return
        self.append_log(tr("Dati seriali ricevuti su: {ports}", ports=", ".join(active)))
        devices = [p.device for p in self.ports]
        if self.port_auto and not self.busy and len(active) == 1 and active[0] in devices:
            self.port_box.current(devices.index(active[0]))
            self.status_var.set(tr("Scheda rilevata su {port}", port=active[0]))

    def append_log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def selected_chip(self):
        index = self.chip_box.current()
        return self.chips[index] if 0 <= index < len(self.chips) else None

    def selected_entry(self):
        """(prodotto, scheda) scelti nell'elenco "Scheda", None se l'elenco è vuoto."""
        index = self.board_box.current()
        return self.board_entries[index] if 0 <= index < len(self.board_entries) else None

    def selected_port(self):
        index = self.port_box.current()
        return self.ports[index].device if index >= 0 else None

    # ── Server ────────────────────────────────────────────────────────────────

    def load_server(self):
        if not self.active_key():
            self.ask_key()
            return
        url = clean_url(self.url_var.get())
        if not url:
            theme.showwarning(APP_TITLE, tr("Inserisci l'URL del server firmware"))
            return
        self.url_var.set(url)
        self.set_busy(True)
        self.status_var.set(tr("Lettura elenco da {url}…", url=url))
        threading.Thread(target=self.run_load_server, args=(url,), daemon=True).start()

    def run_load_server(self, url):
        offline = False
        try:
            products, source = load_products(url)
        except Exception as e:
            error = f"{INDEX_FILE}: {type(e).__name__}: {e}"
            # server non raggiungibile: si usano i firmware già in cache, se ce ne sono
            try:
                products, source = load_cached_products(url)
            except Exception:
                products = []
            if not firmware_entries(products):
                self.events.put(("server_error", (url, error)))
                return
            self.events.put(("log", "\n" + tr("Server {url} non raggiungibile ({error}): "
                                               "uso i firmware in cache", url=url, error=error)))
            offline = True
        if firmware_entries(products):
            self.events.put(("packages", (url, products, source, offline)))
        else:
            self.events.put(("server_error", (url, "\n".join(
                f"{p['name']} / {describe(t)}: {t.get('error')}"
                for p in products for t in p["targets"]) or tr("nessun prodotto nel catalogo"))))

    def packages_loaded(self, url, products, source, offline):
        self.entries = firmware_entries(products)
        self.offline = offline
        if offline:
            self.offline_label.grid()
        else:
            self.offline_label.grid_remove()
        # salva solo un URL scelto dall'utente (per la chiave in uso): con quello
        # della chiave resta valido quello che la chiave indicherà in futuro
        entry = self.active_key()
        if entry:
            if base_url(url) == base_url(self.default_server_url()):
                entry.pop("user_url", None)
            else:
                entry["user_url"] = url
            save_config(self.config_data)

        self.append_log(f"\nServer {url} — {source}:")
        for product in products:
            for target in product["targets"]:
                if target["manifest"]:
                    self.append_log(f"  {product['name']} / {target_label(target)}: "
                                    f"{target['manifest']['version']}")
                else:
                    self.append_log(f"  {product['name']} / {describe(target)}: "
                                    + tr("non disponibile — {error}", error=target.get("error")))
        self.set_busy(False)
        # se è già stato rilevato un chip, l'elenco riparte da quello
        self.refresh_chips(select=self.detected[1] if self.detected else None)
        if offline:
            self.status_var.set(tr("Offline — {count} firmware disponibili in cache",
                                   count=len(self.entries)))
        else:
            self.status_var.set(tr("{count} firmware disponibili su {url}",
                                   count=len(self.entries), url=url))

    def server_error(self, url, error):
        self.entries = []
        self.offline = False
        self.offline_label.grid_remove()
        self.set_busy(False)
        self.refresh_chips()
        self.status_var.set(tr("Server non raggiungibile"))
        self.append_log("\n" + tr("ERRORE lettura {url}: {error}", url=url, error=error))
        theme.showerror(APP_TITLE, tr("Impossibile leggere l'elenco firmware da\n{url}\n\n{error}",
                                      url=url, error=error))

    def default_server_url(self):
        """Server firmware indicato dalla chiave di attivazione in uso."""
        entry = self.active_key()
        return (entry and entry.get("server_url")) or DEFAULT_SERVER_URL

    # ── Chiave di attivazione ─────────────────────────────────────────────────

    def keys(self):
        """Le chiavi salvate (una per cliente), vedi migrate_config."""
        return self.config_data["keys"]

    def find_key(self, key):
        return next((entry for entry in self.keys() if entry["key"] == key), None)

    def active_key(self):
        """La chiave in uso, None se il programma non è attivato."""
        return self.find_key(self.config_data.get("activation_key"))

    def server_for(self, entry):
        """Server firmware per una chiave: quello scelto a mano, altrimenti il suo."""
        if not entry:
            return ""
        return (clean_url(entry.get("user_url", "")) or entry.get("server_url")
                or DEFAULT_SERVER_URL)

    def run_startup_checks(self, keys):
        """All'avvio: prima gli aggiornamenti, poi i file delle chiavi (server predefinito)."""
        self.run_check_update()
        for key in keys:
            self.run_check_key(key, new=False)

    def run_check_key(self, key, new):
        try:
            info = activation.fetch(key)
        except activation.InvalidKey as e:
            self.events.put(("key_checked", (key, new, None, ("invalid", str(e)))))
        except Exception as e:  # senza connessione: resta valido l'ultimo server noto
            self.events.put(("key_checked", (key, new, None,
                                             ("network", f"{type(e).__name__}: {e}"))))
        else:
            self.events.put(("key_checked", (key, new, info, None)))

    def show_keys(self):
        entries = self.keys()
        self.key_box["values"] = [key_label(entry) for entry in entries]
        active = self.active_key()
        if active:
            self.key_box.current(entries.index(active))
        else:
            self.key_box.set(tr("non attivato"))

    def key_selected(self):
        index = self.key_box.current()
        if not 0 <= index < len(self.keys()):
            return
        entry = self.keys()[index]
        if entry is not self.active_key():
            self.append_log("\n" + tr("Licenza in uso: {key}", key=key_label(entry)))
            self.activate(entry)

    def activate(self, entry):
        """Passa alla chiave entry (None: nessuna) e carica l'elenco del suo server."""
        self.config_data["activation_key"] = entry["key"] if entry else None
        save_config(self.config_data)
        self.show_keys()
        self.entries = []
        self.offline = False
        self.offline_label.grid_remove()
        self.refresh_chips()
        if entry:
            self.url_var.set(self.server_for(entry))
            self.load_server()
        else:
            self.url_var.set("")
            self.status_var.set(tr("Programma non attivato: premi \"{button}\" nella scheda {tab}",
                                   button=tr("Aggiungi…"), tab=tr("Opzioni")))

    def remove_key(self):
        entry = self.active_key()
        if not entry:
            return
        if not theme.askyesno(APP_TITLE, tr("Rimuovere la licenza {key} da questo computer?\n"
                                            "Per usarla di nuovo andrà inserita un'altra volta.",
                                            key=key_label(entry))):
            return
        self.keys().remove(entry)
        self.append_log("\n" + tr("Licenza rimossa: {key}", key=key_label(entry)))
        self.activate(self.keys()[0] if self.keys() else None)

    def ask_key(self):
        if self.grab_current():  # sopra un'altra finestra di dialogo, dopo
            self.after(1000, self.ask_key)
            return
        text = theme.askstring(APP_TITLE, tr("Inserisci la chiave di attivazione "
                                             "(XXXX-XXXX-XXXX-XXXX).\n"
                                             "Per la verifica serve la connessione a internet."))
        if text is None:
            if not self.active_key():
                self.status_var.set(tr("Programma non attivato: premi \"{button}\" nella scheda {tab}",
                                       button=tr("Aggiungi…"), tab=tr("Opzioni")))
            return
        key = activation.normalize(text)
        if not activation.is_well_formed(key):
            theme.showerror(APP_TITLE, tr("\"{text}\" non è una chiave valida.\n"
                                          "Il formato è XXXX-XXXX-XXXX-XXXX.", text=text.strip()))
            self.ask_key()
            return
        self.set_busy(True)
        self.status_var.set(tr("Verifica della chiave di attivazione…"))
        threading.Thread(target=self.run_check_key, args=(key, True), daemon=True).start()

    def key_checked(self, key, new, info, error):
        if not new and (self.busy or self.grab_current()):
            self.after(1000, self.key_checked, key, new, info, error)
            return
        if new:
            self.set_busy(False)
        if info:
            self.key_valid(key, new, info)
        elif error[0] == "invalid":
            self.append_log("\n" + tr("Chiave di attivazione {key} non valida: {error}",
                                       key=key, error=error[1]))
            entry = self.find_key(key)
            if not new and entry:  # chiave revocata sul server: viene tolta dall'elenco
                was_active = entry is self.active_key()
                self.keys().remove(entry)
                if not was_active:
                    save_config(self.config_data)
                    self.show_keys()
                else:  # si passa a un'altra chiave salvata, se c'è
                    self.activate(self.keys()[0] if self.keys() else None)
                key = key_label(entry)
            self.status_var.set(tr("Chiave di attivazione non valida"))
            theme.showerror(APP_TITLE, tr("La chiave {key} non è valida: {error}.",
                                          key=key, error=error[1]))
            if new or not self.active_key():
                self.ask_key()
        else:
            self.append_log(tr("Verifica chiave di attivazione non riuscita: {error}",
                               error=error[1]))
            if new:
                self.status_var.set(tr("Chiave non verificata: serve la connessione"))
                theme.showerror(APP_TITLE, tr("Impossibile verificare la chiave: controlla la "
                                              "connessione a internet.\n\n{error}",
                                              error=error[1]))

    def key_valid(self, key, new, info):
        server = clean_url(str(info["server_url"]))
        entry = self.find_key(key)
        if entry is None:
            if not new:  # rimossa mentre la si verificava
                return
            entry = {"key": key}
            self.keys().append(entry)
        changed = server != entry.get("server_url")
        entry.update(server_url=server, name=str(info.get("name", "")).strip())
        self.keys().sort(key=lambda e: (e.get("name") or e["key"]).lower())
        if new:
            entry.pop("user_url", None)  # con una chiave nuova vale il suo server
            self.append_log("\n" + tr("Programma attivato con la chiave {key}: server {server}",
                                       key=key, server=server))
            self.activate(entry)
            return
        save_config(self.config_data)
        self.show_keys()
        # il server della chiave in uso vale se l'utente non ne ha scelto un altro
        if entry is self.active_key() and changed and not entry.get("user_url"):
            self.url_var.set(server)
            self.load_server()

    # ── Aggiornamento del programma ───────────────────────────────────────────

    def run_check_update(self):
        try:
            manifest = updater.check(VERSION)
        except Exception as e:  # senza connessione si continua con questa versione
            self.events.put(("log", tr("Verifica aggiornamenti non riuscita: {error}",
                                       error=f"{type(e).__name__}: {e}")))
            return
        if manifest:
            self.events.put(("update_available", manifest))

    def update_available(self, manifest):
        # non durante un caricamento o sopra un'altra finestra di dialogo
        if self.busy or self.grab_current():
            self.after(1000, self.update_available, manifest)
            return
        self.append_log("\n" + tr("Nuova versione del programma disponibile: {version}",
                                   version=manifest["version"]))
        notes = manifest.get("notes", "").strip()
        message = tr("È disponibile la versione {version} di {app} (in uso: {current}).",
                     version=manifest["version"], app=APP_TITLE, current=VERSION)
        if notes:
            message += "\n\n" + tr("Novità:") + "\n" + notes
        message += "\n\n" + tr("Scaricarla ora?")
        if theme.ask(APP_TITLE, message, [(tr("Salta"), False), (tr("Scarica"), True)], False):
            self.start_update(manifest)

    def start_update(self, manifest):
        self.set_busy(True)
        self.progress["value"] = 0
        self.status_var.set(tr("Download della versione {version}…", version=manifest["version"]))
        threading.Thread(target=self.run_update, args=(manifest,), daemon=True).start()

    def run_update(self, manifest):
        try:
            path = updater.download(manifest, lambda p: self.events.put(("progress", p)))
        except Exception as e:
            self.events.put(("update_error", f"{type(e).__name__}: {e}"))
        else:
            self.events.put(("update_downloaded", (manifest, path)))

    def update_downloaded(self, manifest, path):
        self.progress["value"] = 100
        self.set_busy(False)
        self.append_log(tr("Versione {version} scaricata: {path}",
                           version=manifest["version"], path=path))
        if not updater.can_install(path):
            # dai sorgenti, o cartella del programma non scrivibile: si installa a mano
            self.status_var.set(tr("Versione {version} scaricata", version=manifest["version"]))
            theme.showinfo(APP_TITLE, tr("La versione {version} è stata salvata in\n{path}\n\n"
                                         "Chiudi il programma e avvia il nuovo file.",
                                         version=manifest["version"], path=path))
            os.startfile(path.parent)
            return
        try:
            updater.install(path)
        except OSError as e:
            self.update_error(tr("installazione non riuscita: {error}", error=e))
            return
        theme.showinfo(APP_TITLE, tr("Versione {version} installata: il programma si riavvia.",
                                     version=manifest["version"]))
        updater.restart()
        self.closing = True
        self.destroy()

    def update_error(self, error):
        self.set_busy(False)
        self.progress["value"] = 0
        self.status_var.set(tr("Aggiornamento non riuscito"))
        self.append_log("\n" + tr("ERRORE aggiornamento: {error}", error=error))
        theme.showerror(APP_TITLE, tr("Impossibile scaricare la nuova versione:\n{error}",
                                      error=error))

    # ── Rilevamento chip ──────────────────────────────────────────────────────

    def start_detect(self):
        port = self.selected_port()
        if not port:
            theme.showwarning(APP_TITLE, tr("Collega la scheda e seleziona la porta COM.\n"
                                            "Se la porta non compare nell'elenco, premi Aggiorna."))
            return
        self.set_busy(True)
        self.progress["value"] = 0
        self.status_var.set(tr("Rilevamento chip su {port}…", port=port))
        threading.Thread(target=self.run_detect, args=(port,), daemon=True).start()

    def run_detect(self, port):
        try:
            self.events.put(("log", "\n" + tr("Rilevamento chip su {port}", port=port)))
            info = esp_device.detect(port)
        except BaseException as e:  # esptool usa anche SystemExit per gli errori
            self.events.put(("detect_error", f"{type(e).__name__}: {e}"))
        else:
            self.events.put(("detected", info))

    def chip_detected(self, info):
        port, chip = info["port"], info["chip"]
        self.detected = (port, chip)
        self.set_busy(False)
        text = esp_device.detected_label(info)
        self.chip_info_var.set(text)
        self.append_log(tr("Chip su {port}: {info}", port=port, info=text))
        if chip in self.chips:
            self.chip_box.current(self.chips.index(chip))
            self.chip_changed()
            self.status_var.set(tr("Rilevato {chip} su {port}: scegli la scheda",
                                   chip=chip_label(chip), port=port))
        elif self.entries:
            self.status_var.set(tr("Rilevato {chip} su {port}", chip=chip_label(chip), port=port))
            error = tr("Sul server non c'è nessun firmware per {chip}.", chip=chip_label(chip))
            self.append_log(tr("ATTENZIONE: {error}", error=error))
            theme.showwarning(APP_TITLE, error)

    def detect_error(self, error):
        self.set_busy(False)
        self.status_var.set(tr("Chip non rilevato"))
        self.chip_info_var.set("")
        self.append_log("\n" + tr("ERRORE rilevamento chip: {error}", error=error))
        hint = connect_hint(error, tr("Rileva chip"))
        if is_connect_error(error):
            self.append_log(hint)
        theme.showerror(APP_TITLE, tr("Impossibile leggere il chip:\n{error}", error=error)
                        + "\n\n" + hint)

    # ── Flash ─────────────────────────────────────────────────────────────────

    def start_flash(self):
        entry = self.selected_entry()
        if not entry:
            theme.showwarning(APP_TITLE, tr("Scegli chip e scheda da caricare."))
            return
        port = self.selected_port()
        if not port:
            theme.showwarning(APP_TITLE, tr("Collega la scheda e seleziona la porta COM.\n"
                                            "Se la porta non compare nell'elenco, premi Aggiorna."))
            return
        product, target = entry
        if self.detected and self.detected[0] == port and self.detected[1] != target["chip"]:
            theme.showerror(APP_TITLE, tr("Sulla {port} è collegato un {detected}, ma il "
                                          "firmware scelto è per {chip}.", port=port,
                                          detected=chip_label(self.detected[1]),
                                          chip=chip_label(target["chip"])))
            return
        self.confirm_and_flash(product, target, port)

    def confirm_and_flash(self, product, target, port):
        full = self.mode_var.get() == MODE_FULL
        manifest = target["manifest"]
        images = [img for img in manifest["images"] if full or img["role"] != "filesystem"]
        if "cached" in target:  # elenco letto dalla cache, senza connessione
            missing = [img["file"] for img in images if img["file"] not in target["cached"]]
            if missing:
                theme.showerror(APP_TITLE, tr("Offline: in cache manca {files}.\n\n"
                                              "Per l'installazione completa serve la "
                                              "connessione; l'aggiornamento firmware si può fare.",
                                              files=", ".join(missing)))
                return
        extras = list(self.extras) if full and self.extras_var.get() else []
        if full:
            fs = next((img for img in images if img["role"] == "filesystem"), None)
            if fs is None and extras:
                theme.showerror(APP_TITLE, tr("Questo pacchetto non contiene il filesystem: "
                                              "i file aggiuntivi non si possono caricare."))
                return
            if fs is None:
                if not theme.askyesno(APP_TITLE, tr("Questo pacchetto non contiene il "
                                                    "filesystem: dopo la cancellazione le pagine "
                                                    "web mancheranno. Continuare?")):
                    return
            added = ""
            if extras:
                # nomi controllati subito, prima di scaricare e cancellare
                try:
                    files = fs_image.collect(extras)
                    fs_image.check_names(fs_image.fs_type(fs["file"]), files)
                except RuntimeError as e:
                    theme.showerror(APP_TITLE, tr("File aggiuntivi non validi:\n{error}", error=e))
                    return
                added = "\n\n" + tr("Verranno aggiunti {count} file al filesystem.",
                                    count=len(files))
            if not theme.askyesno(APP_TITLE, tr("Installazione completa di {product} ({target}) "
                                                "su {port}:\ntutta la flash verrà cancellata, "
                                                "comprese configurazione e WiFi.",
                                                product=product["name"],
                                                target=target_label(target), port=port)
                                  + added + "\n\n" + tr("Continuare?")):
                return

        self.config_data["baud"] = self.baud_var.get()
        save_config(self.config_data)

        package = dict(manifest, chip=target["chip"], url=target["url"],
                       cache=cache_name(target["url"]), manifest=manifest)
        self.set_busy(True)
        self.tabs.select("Log")  # i messaggi del caricamento compaiono nel log
        self.progress["value"] = 0
        self.status_var.set(tr("Download {name} {version}…", name=package["name"],
                               version=package["version"]))
        threading.Thread(target=self.run_flash, daemon=True,
                         args=(package, images, port, self.baud_var.get(), full, extras)).start()

    def download_images(self, package, images):
        """Scarica le immagini in cache (se mancanti) e ne verifica lo sha256."""
        root = cache_dir()
        if root != CACHE_DIR:
            self.events.put(("log", tr("{dir} non scrivibile: cache in {root}",
                                       dir=CACHE_DIR, root=root)))
        cache = root / package["cache"]
        cache.mkdir(parents=True, exist_ok=True)
        paths = []
        for img in images:
            path = cache / img["file"]
            expected = img.get("sha256")
            if is_cached(path, img):
                self.events.put(("log", tr("{file}: già in cache", file=img["file"])))
                paths.append(path)
                continue

            url = urljoin(package["url"], img["file"])
            self.events.put(("log", f"Download {url}"))
            tmp = path.with_suffix(path.suffix + ".part")
            with fetch(url) as response, open(tmp, "wb") as out:
                total = int(response.headers.get("Content-Length") or img.get("size") or 0)
                done = 0
                for chunk in iter(lambda: response.read(1 << 16), b""):
                    out.write(chunk)
                    done += len(chunk)
                    if total:
                        self.events.put(("progress", 100 * done / total))
            if expected and sha256_of(tmp) != expected:
                tmp.unlink()
                raise RuntimeError(tr("{file}: checksum non valido, download corrotto",
                                      file=img["file"]))
            tmp.replace(path)
            paths.append(path)
        # salvato solo a download riuscito: il manifest in cache descrive i file presenti
        save_cached(cache / MANIFEST_FILE, json.dumps(package["manifest"], indent=2) + "\n")
        return paths

    def add_extras(self, images, paths, extras, work_dir):
        """Sostituisce in paths l'immagine filesystem con una copia che contiene extras."""
        index = next(i for i, img in enumerate(images) if img["role"] == "filesystem")
        self.events.put(("status", tr("Aggiunta dei file al filesystem…")))
        self.events.put(("log", "\n" + tr("File aggiunti a {file}:", file=images[index]["file"])))
        paths[index], changes = fs_image.add_files(paths[index], extras, work_dir)
        for rel, change in changes:
            self.events.put(("log", f"  /{rel}  ({change})"))

    def run_flash(self, package, images, port, baud, full, extras):
        try:
            paths = self.download_images(package, images)
            # la copia modificata dell'immagine vive solo fino alla fine del caricamento
            with tempfile.TemporaryDirectory(prefix="fs_") as work_dir:
                if extras:
                    self.add_extras(images, paths, extras, work_dir)

                args = ["--chip", package.get("chip", "esp32"), "--port", port, "--baud", baud,
                        "--before", "default-reset", "--after", "hard-reset", "write-flash"]
                if full:
                    args.append("--erase-all")
                for img, path in zip(images, paths):
                    args += [img["offset"], str(path)]

                self.events.put(("status", tr("Caricamento {name} su {port}…",
                                              name=package["name"], port=port)))
                self.events.put(("progress", 0))
                self.events.put(("log", f"\n> esptool {' '.join(args)}"))
                esptool.main(args)
        except BaseException as e:  # esptool usa anche SystemExit per gli errori
            self.events.put(("done", f"{type(e).__name__}: {e}"))
        else:
            self.events.put(("done", None))

    def poll_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "log":
                    self.append_log(value)
                elif kind == "progress":
                    self.set_progress(value)
                elif kind == "erasing":
                    self.show_erasing()
                elif kind == "status":
                    self.status_var.set(value)
                elif kind == "packages":
                    self.packages_loaded(*value)
                elif kind == "server_error":
                    self.server_error(*value)
                elif kind == "ports_probed":
                    self.ports_probed(value)
                elif kind == "detected":
                    self.chip_detected(value)
                elif kind == "detect_error":
                    self.detect_error(value)
                elif kind == "done":
                    self.finish_flash(value)
                elif kind == "key_checked":
                    self.key_checked(*value)
                elif kind == "update_available":
                    self.update_available(value)
                elif kind == "update_downloaded":
                    self.update_downloaded(*value)
                    if self.closing:
                        return
                elif kind == "update_error":
                    self.update_error(value)
        except queue.Empty:
            pass
        if not self.closing:
            self.after(100, self.poll_events)

    def show_erasing(self):
        """Barra animata durante la cancellazione, di cui esptool non dà l'avanzamento."""
        if str(self.progress["mode"]) != "indeterminate":
            self.status_before_erase = self.status_var.get()
            self.progress.configure(mode="indeterminate")
            self.progress.start(15)
        self.status_var.set(tr("Cancellazione della flash in corso (può richiedere fino a "
                               "un minuto)…"))

    def set_progress(self, value):
        if str(self.progress["mode"]) == "indeterminate":
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.status_var.set(self.status_before_erase)
        self.progress["value"] = value

    def finish_flash(self, error):
        self.set_progress(self.progress["value"] if error else 100)
        self.set_busy(False)
        if error:
            self.status_var.set(tr("Errore"))
            self.append_log("\n" + tr("ERRORE: {error}", error=error))
            hint = connect_hint(error)
            if is_connect_error(error):
                self.append_log(hint)
            theme.showerror(APP_TITLE, tr("Caricamento non riuscito:\n{error}", error=error)
                            + "\n\n" + hint)
        else:
            self.progress["value"] = 100
            self.status_var.set(tr("Completato — la scheda è stata riavviata"))
            self.append_log("\n" + tr("Completato."))
            theme.showinfo(APP_TITLE, tr("Firmware caricato correttamente."))
            self.tabs.select("Dispositivo")  # pronto per la scheda successiva


if __name__ == "__main__":
    InstallerApp().mainloop()
