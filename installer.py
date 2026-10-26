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
cartella cache, sempre accanto all'eseguibile.
Il flash avviene con esptool, nello stesso processo.
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
import theme
from esp_device import connect_hint, guess_port, is_connect_error, port_score

APP_TITLE = "ST ESP32 Flash Tool"
BAUD_RATES = ["921600", "460800", "230400", "115200"]
DEFAULT_BAUD = "460800"
HTTP_TIMEOUT = 20

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
            products = catalog.loads(response.read().decode("utf-8"))["products"]
        source = INDEX_FILE
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        # chip None: preso dal manifest della cartella
        products = [{"name": label, "targets": [{"chip": None, "board": "", "folder": folder}]}
                    for folder, label in LEGACY_FOLDERS.items()]
        source = f"cartelle predefinite ({INDEX_FILE} assente)"

    for product in products:
        for target in product["targets"]:
            target["url"] = catalog.folder_url(base, target["folder"])
            target["manifest"] = None
            try:
                manifest = fetch_json(urljoin(target["url"], "manifest.json"))
            except Exception as e:
                target["error"] = f"{type(e).__name__}: {e}"
                continue
            if target["chip"] is None:
                target["chip"] = manifest.get("chip", "esp32")
            elif manifest.get("chip", target["chip"]) != target["chip"]:
                target["error"] = f"il firmware in {target['folder']} è per {chip_label(manifest['chip'])}"
                continue
            target["manifest"] = manifest
    return products, source


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
        self.title(APP_TITLE)
        self.minsize(760, 520)
        theme.apply(self)

        self.events = queue.Queue()
        esp_device.set_logger(self.events)

        self.config_data = load_config()
        self.entries = []        # (prodotto, scheda) con firmware disponibile
        self.chips = []          # chip dell'elenco "Chip", nell'ordine mostrato
        self.board_entries = []  # voci dell'elenco "Scheda" per il chip scelto
        self.detected = None     # (porta, chip) dell'ultimo rilevamento
        self.ports = []
        self.port_auto = True  # False quando l'utente sceglie la porta a mano
        self.busy = False
        self.extras = []  # file e cartelle locali da aggiungere al filesystem
        self.status_before_erase = ""  # stato da ripristinare dopo la cancellazione

        self.url_var = tk.StringVar(
            value=clean_url(self.config_data.get("server_url", "")) or DEFAULT_SERVER_URL)
        self.chip_info_var = tk.StringVar()
        self.port_var = tk.StringVar()
        self.baud_var = tk.StringVar(value=self.config_data.get("baud", DEFAULT_BAUD))
        self.mode_var = tk.StringVar(value=MODE_FULL)
        self.extras_var = tk.BooleanVar(value=self.config_data.get("extras", False))
        self.status_var = tk.StringVar(value="Inserisci l'URL del server firmware")

        self.build_ui()
        self.refresh_chips()
        self.refresh_ports()
        theme.center(self)
        self.after(100, self.poll_events)
        if self.url_var.get():
            self.load_server()

    # ── UI ────────────────────────────────────────────────────────────────────

    def build_ui(self):
        # in fondo, sempre visibili: pulsante, avanzamento, stato e logo
        footer = ttk.Frame(self, padding=(20, 12, 20, 12))
        footer.pack(side="bottom", fill="x")
        footer.columnconfigure(0, weight=1)
        ttk.Frame(self, style="Divider.TFrame", height=1).pack(side="bottom", fill="x")
        self.flash_button = ttk.Button(footer, text="Carica firmware", style="Primary.TButton",
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

        frame = self.tabs.add("Dispositivo")
        frame.configure(padding=(20, 12, 20, 12))
        frame.columnconfigure(0, weight=1)
        device = theme.card(frame, "Connessione")
        device.grid(row=0, column=0, sticky="ew")
        device.columnconfigure(1, weight=1)

        ttk.Label(device, text="Server", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", pady=5, padx=(0, 12))
        url_entry = ttk.Entry(device, textvariable=self.url_var)
        url_entry.grid(row=0, column=1, sticky="ew", pady=5)
        url_entry.bind("<Return>", lambda _e: self.load_server())
        self.load_button = ttk.Button(device, text="Carica elenco", command=self.load_server)
        self.load_button.grid(row=0, column=2, sticky="ew", padx=(8, 0), pady=5)

        ttk.Label(device, text="Porta COM", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", pady=5, padx=(0, 12))
        self.port_box = ttk.Combobox(device, textvariable=self.port_var, state="readonly")
        self.port_box.grid(row=1, column=1, sticky="ew", pady=5)
        self.port_box.bind("<<ComboboxSelected>>", lambda _e: self.port_changed())
        ttk.Button(device, text="Aggiorna", command=self.refresh_ports).grid(
            row=1, column=2, sticky="ew", padx=(8, 0), pady=5)

        ttk.Label(device, text="Chip", style="Card.TLabel").grid(
            row=2, column=0, sticky="w", pady=5, padx=(0, 12))
        self.chip_box = ttk.Combobox(device, state="readonly")
        self.chip_box.grid(row=2, column=1, sticky="ew", pady=5)
        self.chip_box.bind("<<ComboboxSelected>>", lambda _e: self.chip_changed())
        self.detect_button = ttk.Button(device, text="Rileva chip", command=self.start_detect)
        self.detect_button.grid(row=2, column=2, sticky="ew", padx=(8, 0), pady=5)
        ttk.Label(device, textvariable=self.chip_info_var, style="Card.Muted.TLabel").grid(
            row=3, column=1, columnspan=2, sticky="w")

        ttk.Label(device, text="Scheda", style="Card.TLabel").grid(
            row=4, column=0, sticky="w", pady=5, padx=(0, 12))
        self.board_box = ttk.Combobox(device, state="readonly")
        self.board_box.grid(row=4, column=1, columnspan=2, sticky="ew", pady=5)
        self.board_box.bind("<<ComboboxSelected>>", lambda _e: self.board_changed())

        ttk.Label(device, text="Velocità", style="Card.TLabel").grid(
            row=5, column=0, sticky="w", pady=5, padx=(0, 12))
        ttk.Combobox(device, textvariable=self.baud_var, values=BAUD_RATES,
                     state="readonly", width=10).grid(row=5, column=1, sticky="w", pady=5)

        frame = self.tabs.add("Opzioni")
        frame.configure(padding=(20, 12, 20, 12))
        frame.columnconfigure(0, weight=1)
        modes = theme.card(frame, "Modalità")
        modes.grid(row=0, column=0, sticky="ew")
        ttk.Radiobutton(modes, variable=self.mode_var, value=MODE_UPDATE, command=self.mode_changed,
                        style="Card.TRadiobutton",
                        text="Aggiornamento firmware — mantiene configurazione e file del dispositivo"
                        ).pack(anchor="w")
        ttk.Radiobutton(modes, variable=self.mode_var, value=MODE_FULL, command=self.mode_changed,
                        style="Card.TRadiobutton",
                        text="Installazione completa — cancella tutta la flash e scrive anche il filesystem (data/)"
                        ).pack(anchor="w")

        extras = theme.card(frame, "File aggiuntivi nel filesystem")
        extras.grid(row=1, column=0, sticky="ew", pady=(12, 0))
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
        for row, (text, command) in enumerate((("Aggiungi file…", self.add_extra_files),
                                               ("Aggiungi cartella…", self.add_extra_folder),
                                               ("Rimuovi", self.remove_extra))):
            button = ttk.Button(self.extras_body, text=text, command=command)
            button.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=(0, 4))
            self.extra_buttons.append(button)
        ttk.Label(self.extras_body, style="Card.Muted.TLabel", wraplength=640, justify="left",
                  text="Solo con l'installazione completa: i file vengono inseriti nel filesystem "
                       "del firmware prima del caricamento. Un file va nella radice; di una cartella "
                       "si copia il contenuto. Un file con lo stesso percorso sostituisce quello "
                       "del firmware.").grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        frame = self.tabs.add("Log", scroll=False)
        frame.configure(padding=(20, 12, 20, 12))
        log_box, self.log_text = theme.log_widget(frame, height=10)
        log_box.pack(fill="both", expand=True)

        # misure prese con i file aggiuntivi visibili: accendendo l'interruttore
        # la finestra non deve cambiare altezza
        self.tabs.fit()
        self.extras_toggled()

    def refresh_chips(self, select=None):
        """Elenco "Chip": i chip che hanno almeno un firmware disponibile."""
        present = {t["chip"] for _p, t in self.entries}
        self.chips = [c for c in CHIPS if c in present] + sorted(present - set(CHIPS))
        self.chip_box["values"] = [chip_label(c) for c in self.chips]
        if not self.chips:
            self.chip_box.set("carica l'elenco dal server")
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
        for button in (self.load_button, self.detect_button):
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
            self.extra_list.insert("end", f"[cartella] {path}  (contenuto)" if path.is_dir()
                                   else f"{path.name}  —  {path.parent}")
        self.mode_changed()

    def add_extra_files(self):
        files = filedialog.askopenfilenames(parent=self, title="File da aggiungere al filesystem")
        self.extras += [f for f in files if f not in self.extras]
        self.refresh_extras()

    def add_extra_folder(self):
        folder = filedialog.askdirectory(parent=self, title="Cartella da copiare nel filesystem")
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
                        f"(preparato {manifest.get('prepared', '?')})")
        for img in manifest["images"]:
            self.append_log(f"  {img['offset']:>9}  {img['file']}")

    def port_changed(self):
        self.port_auto = False
        self.chip_info_var.set("")
        self.detected = None

    def refresh_ports(self):
        self.ports = esp_device.esp_ports()
        labels = [f"{p.device}  —  {p.description}" for p in self.ports]
        self.port_box["values"] = labels
        self.port_auto = True
        self.chip_info_var.set("")
        self.detected = None
        if not labels:
            self.port_var.set("")
            self.status_var.set("Nessuna scheda ESP32 trovata: collegala e premi Aggiorna")
            return
        self.status_var.set(f"Porte trovate: {', '.join(p.device for p in self.ports)}")
        guess = guess_port(self.ports)
        self.port_box.current(guess if guess is not None else 0)
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
        self.append_log(f"Dati seriali ricevuti su: {', '.join(active)}")
        devices = [p.device for p in self.ports]
        if self.port_auto and not self.busy and len(active) == 1 and active[0] in devices:
            self.port_box.current(devices.index(active[0]))
            self.status_var.set(f"Scheda rilevata su {active[0]}")

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
        url = clean_url(self.url_var.get())
        if not url:
            theme.showwarning(APP_TITLE, "Inserisci l'URL del server firmware")
            return
        self.url_var.set(url)
        self.set_busy(True)
        self.status_var.set(f"Lettura elenco da {url}…")
        threading.Thread(target=self.run_load_server, args=(url,), daemon=True).start()

    def run_load_server(self, url):
        try:
            products, source = load_products(url)
        except Exception as e:
            self.events.put(("server_error", (url, f"{INDEX_FILE}: {type(e).__name__}: {e}")))
            return
        if firmware_entries(products):
            self.events.put(("packages", (url, products, source)))
        else:
            self.events.put(("server_error", (url, "\n".join(
                f"{p['name']} / {describe(t)}: {t.get('error')}"
                for p in products for t in p["targets"]) or "nessun prodotto nel catalogo")))

    def packages_loaded(self, url, products, source):
        self.entries = firmware_entries(products)
        # salva solo un URL scelto dall'utente: con quello predefinito resta
        # valido il default della versione installata
        if base_url(url) == base_url(DEFAULT_SERVER_URL):
            self.config_data.pop("server_url", None)
        else:
            self.config_data["server_url"] = url
        save_config(self.config_data)

        self.append_log(f"\nServer {url} — {source}:")
        for product in products:
            for target in product["targets"]:
                if target["manifest"]:
                    self.append_log(f"  {product['name']} / {target_label(target)}: "
                                    f"{target['manifest']['version']}")
                else:
                    self.append_log(f"  {product['name']} / {describe(target)}: "
                                    f"non disponibile — {target.get('error')}")
        self.set_busy(False)
        # se è già stato rilevato un chip, l'elenco riparte da quello
        self.refresh_chips(select=self.detected[1] if self.detected else None)
        self.status_var.set(f"{len(self.entries)} firmware disponibili su {url}")

    def server_error(self, url, error):
        self.entries = []
        self.set_busy(False)
        self.refresh_chips()
        self.status_var.set("Server non raggiungibile")
        self.append_log(f"\nERRORE lettura {url}: {error}")
        theme.showerror(APP_TITLE, f"Impossibile leggere l'elenco firmware da\n{url}\n\n{error}")

    # ── Rilevamento chip ──────────────────────────────────────────────────────

    def start_detect(self):
        port = self.selected_port()
        if not port:
            theme.showwarning(APP_TITLE, "Collega la scheda e seleziona la porta COM.\n"
                              "Se la porta non compare nell'elenco, premi Aggiorna.")
            return
        self.set_busy(True)
        self.progress["value"] = 0
        self.status_var.set(f"Rilevamento chip su {port}…")
        threading.Thread(target=self.run_detect, args=(port,), daemon=True).start()

    def run_detect(self, port):
        try:
            self.events.put(("log", f"\nRilevamento chip su {port}"))
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
        self.append_log(f"Chip su {port}: {text}")
        if chip in self.chips:
            self.chip_box.current(self.chips.index(chip))
            self.chip_changed()
            self.status_var.set(f"Rilevato {chip_label(chip)} su {port}: scegli la scheda")
        elif self.entries:
            self.status_var.set(f"Rilevato {chip_label(chip)} su {port}")
            error = f"Sul server non c'è nessun firmware per {chip_label(chip)}."
            self.append_log(f"ATTENZIONE: {error}")
            theme.showwarning(APP_TITLE, error)

    def detect_error(self, error):
        self.set_busy(False)
        self.status_var.set("Chip non rilevato")
        self.chip_info_var.set("")
        self.append_log(f"\nERRORE rilevamento chip: {error}")
        hint = connect_hint(error, "Rileva chip")
        if is_connect_error(error):
            self.append_log(hint)
        theme.showerror(APP_TITLE, f"Impossibile leggere il chip:\n{error}\n\n{hint}")

    # ── Flash ─────────────────────────────────────────────────────────────────

    def start_flash(self):
        entry = self.selected_entry()
        if not entry:
            theme.showwarning(APP_TITLE, "Scegli chip e scheda da caricare.")
            return
        port = self.selected_port()
        if not port:
            theme.showwarning(APP_TITLE, "Collega la scheda e seleziona la porta COM.\n"
                              "Se la porta non compare nell'elenco, premi Aggiorna.")
            return
        product, target = entry
        if self.detected and self.detected[0] == port and self.detected[1] != target["chip"]:
            theme.showerror(APP_TITLE, f"Sulla {port} è collegato un "
                                 f"{chip_label(self.detected[1])}, ma il firmware scelto è per "
                                 f"{chip_label(target['chip'])}.")
            return
        self.confirm_and_flash(product, target, port)

    def confirm_and_flash(self, product, target, port):
        full = self.mode_var.get() == MODE_FULL
        manifest = target["manifest"]
        images = [img for img in manifest["images"] if full or img["role"] != "filesystem"]
        extras = list(self.extras) if full and self.extras_var.get() else []
        if full:
            fs = next((img for img in images if img["role"] == "filesystem"), None)
            if fs is None and extras:
                theme.showerror(APP_TITLE, "Questo pacchetto non contiene il filesystem: "
                                     "i file aggiuntivi non si possono caricare.")
                return
            if fs is None:
                if not theme.askyesno(APP_TITLE, "Questo pacchetto non contiene il "
                                           "filesystem: dopo la cancellazione le pagine web "
                                           "mancheranno. Continuare?"):
                    return
            added = ""
            if extras:
                # nomi controllati subito, prima di scaricare e cancellare
                try:
                    files = fs_image.collect(extras)
                    fs_image.check_names(fs_image.fs_type(fs["file"]), files)
                except RuntimeError as e:
                    theme.showerror(APP_TITLE, f"File aggiuntivi non validi:\n{e}")
                    return
                added = f"\n\nVerranno aggiunti {len(files)} file al filesystem."
            if not theme.askyesno(APP_TITLE, f"Installazione completa di {product['name']} "
                                       f"({target_label(target)}) su {port}:\n"
                                       "tutta la flash verrà cancellata, comprese "
                                       f"configurazione e WiFi.{added}\n\nContinuare?"):
                return

        self.config_data["baud"] = self.baud_var.get()
        save_config(self.config_data)

        package = dict(manifest, chip=target["chip"], url=target["url"],
                       cache=re.sub(r"[^\w.-]+", "_", target["url"]).strip("_"))
        self.set_busy(True)
        self.tabs.select("Log")  # i messaggi del caricamento compaiono nel log
        self.progress["value"] = 0
        self.status_var.set(f"Download {package['name']} {package['version']}…")
        threading.Thread(target=self.run_flash, daemon=True,
                         args=(package, images, port, self.baud_var.get(), full, extras)).start()

    def download_images(self, package, images):
        """Scarica le immagini in cache (se mancanti) e ne verifica lo sha256."""
        root = cache_dir()
        if root != CACHE_DIR:
            self.events.put(("log", f"{CACHE_DIR} non scrivibile: cache in {root}"))
        cache = root / package["cache"]
        cache.mkdir(parents=True, exist_ok=True)
        paths = []
        for img in images:
            path = cache / img["file"]
            expected = img.get("sha256")
            if path.exists() and expected and sha256_of(path) == expected:
                self.events.put(("log", f"{img['file']}: già in cache"))
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
                raise RuntimeError(f"{img['file']}: checksum non valido, download corrotto")
            tmp.replace(path)
            paths.append(path)
        return paths

    def add_extras(self, images, paths, extras, work_dir):
        """Sostituisce in paths l'immagine filesystem con una copia che contiene extras."""
        index = next(i for i, img in enumerate(images) if img["role"] == "filesystem")
        self.events.put(("status", "Aggiunta dei file al filesystem…"))
        self.events.put(("log", f"\nFile aggiunti a {images[index]['file']}:"))
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

                self.events.put(("status", f"Caricamento {package['name']} su {port}…"))
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
        except queue.Empty:
            pass
        self.after(100, self.poll_events)

    def show_erasing(self):
        """Barra animata durante la cancellazione, di cui esptool non dà l'avanzamento."""
        if str(self.progress["mode"]) != "indeterminate":
            self.status_before_erase = self.status_var.get()
            self.progress.configure(mode="indeterminate")
            self.progress.start(15)
        self.status_var.set("Cancellazione della flash in corso (può richiedere fino a un minuto)…")

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
            self.status_var.set("Errore")
            self.append_log(f"\nERRORE: {error}")
            hint = connect_hint(error)
            if is_connect_error(error):
                self.append_log(hint)
            theme.showerror(APP_TITLE, f"Caricamento non riuscito:\n{error}\n\n{hint}")
        else:
            self.progress["value"] = 100
            self.status_var.set("Completato — la scheda è stata riavviata")
            self.append_log("\nCompletato.")
            theme.showinfo(APP_TITLE, "Firmware caricato correttamente.")
            self.tabs.select("Dispositivo")  # pronto per la scheda successiva


if __name__ == "__main__":
    InstallerApp().mainloop()
