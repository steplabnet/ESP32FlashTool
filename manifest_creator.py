"""
ST ESP32 Manifest Creator — crea index.json, il catalogo letto da installer.py.

Per ogni prodotto si definiscono i chip ESP32 e i tipi di scheda supportati e
la cartella remota con il firmware di ciascuna combinazione (vedi catalog.py).
"Verifica cartelle" legge <cartella>/manifest.json dal server e controlla che
esista e che il chip corrisponda.
"Rileva" legge il chip dell'ESP32 collegato al PC e lo aggiunge all'elenco dei
chip rilevati, da cui si creano le nuove schede del catalogo.

index.json va copiato sotto l'URL base del server, accanto alle cartelle.
"""

import json
import queue
import sys
import threading
import tkinter as tk
import urllib.request
from pathlib import Path
from tkinter import filedialog, ttk
from urllib.parse import urljoin


import catalog
import esp_device
import theme
from catalog import CHIPS, INDEX_FILE, chip_label, target_label
from esp_device import connect_hint, detected_label, guess_port, is_connect_error

APP_TITLE = "ST ESP32 Manifest Creator"
HTTP_TIMEOUT = 20

if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent
FIRMWARE_DIR = ROOT / "firmware"


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": APP_TITLE})
    return urllib.request.urlopen(request, timeout=HTTP_TIMEOUT)


def check_folder(url, target):
    """Legge manifest.json della cartella: ritorna il testo per la colonna Stato."""
    try:
        with fetch(urljoin(url, "manifest.json")) as response:
            manifest = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        return f"ERRORE {type(e).__name__}: {e}"
    status = f"OK versione {manifest.get('version', '?')}"
    chip = manifest.get("chip")
    if chip and chip != target["chip"]:
        return f"ERRORE il firmware è per {chip_label(chip)}"
    board = manifest.get("board")
    if board and board != target["board"]:
        status += f" (compilato per {board})"
    return status


class TargetDialog(theme.Dialog):
    """Chip, tipo di scheda e cartella remota di una combinazione supportata."""

    def __init__(self, parent, title, target, boards):
        self.target = dict(target)
        self.boards = boards
        self.result = None
        super().__init__(parent, title)

    def body(self, master):
        master.columnconfigure(1, weight=1)
        labels = [f"{label}  ({chip})" for chip, label in CHIPS.items()]
        self.chip_box = ttk.Combobox(master, values=labels, state="readonly", width=28,
                                     style="Page.TCombobox")
        chips = list(CHIPS)
        self.chip_box.current(chips.index(self.target["chip"])
                              if self.target.get("chip") in chips else 0)
        self.board_var = tk.StringVar(value=self.target.get("board", ""))
        self.folder_var = tk.StringVar(value=self.target.get("folder", ""))

        ttk.Label(master, text="Chip").grid(row=0, column=0, sticky="w", pady=4, padx=(0, 12))
        self.chip_box.grid(row=0, column=1, columnspan=2, sticky="ew", pady=4)
        ttk.Label(master, text="Tipo scheda").grid(row=1, column=0, sticky="w", pady=4, padx=(0, 12))
        ttk.Combobox(master, textvariable=self.board_var, values=self.boards, width=28,
                     style="Page.TCombobox").grid(
            row=1, column=1, columnspan=2, sticky="ew", pady=4)
        ttk.Label(master, text="Cartella remota").grid(row=2, column=0, sticky="w", pady=4,
                                                         padx=(0, 12))
        ttk.Entry(master, textvariable=self.folder_var, width=40, style="Page.TEntry").grid(
            row=2, column=1, sticky="ew", pady=4)
        ttk.Button(master, text="Da cartella locale…", command=self.pick_local,
                   style="Page.TButton").grid(row=2, column=2, padx=(8, 0), pady=4)
        ttk.Label(master, style="Muted.TLabel", justify="left",
                  text="Relativa all'URL base del server (es. moduloPompa)\n"
                       "oppure URL completo (es. https://server/fw/moduloPompa)").grid(
            row=3, column=1, columnspan=2, sticky="w")
        return self.chip_box

    def pick_local(self):
        """Riempie i campi da una cartella creata da prepare_firmware.py."""
        folder = filedialog.askdirectory(
            parent=self, title="Cartella firmware con manifest.json",
            initialdir=FIRMWARE_DIR if FIRMWARE_DIR.is_dir() else ROOT)
        if not folder:
            return
        folder = Path(folder)
        self.folder_var.set(folder.name)
        try:
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            theme.showwarning(APP_TITLE, f"manifest.json non leggibile:\n{e}", parent=self)
            return
        if manifest.get("chip") in CHIPS:
            self.chip_box.current(list(CHIPS).index(manifest["chip"]))
        if manifest.get("board") and not self.board_var.get().strip():
            self.board_var.set(manifest["board"])

    def validate(self):
        if not self.board_var.get().strip():
            theme.showwarning(APP_TITLE, "Indica il tipo di scheda.", parent=self)
            return False
        if not self.folder_var.get().strip():
            theme.showwarning(APP_TITLE, "Indica la cartella remota.", parent=self)
            return False
        return True

    def apply(self):
        self.result = {"chip": list(CHIPS)[self.chip_box.current()],
                       "board": self.board_var.get().strip(),
                       "folder": self.folder_var.get().strip()}


class CreatorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.minsize(860, 560)
        theme.apply(self)

        self.events = queue.Queue()
        self.catalog = catalog.new_catalog()
        self.path = None
        self.dirty = False
        self.status = {}  # URL cartella -> esito della verifica
        self.ports = []
        self.detected = []  # chip letti dalle schede collegate, il più recente per primo
        esp_device.set_logger(self.events)

        self.url_var = tk.StringVar(value=catalog.DEFAULT_SERVER_URL)
        self.status_var = tk.StringVar()

        self.build_ui()
        self.refresh_ports()
        theme.center(self)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(100, self.poll_events)

        default = FIRMWARE_DIR / INDEX_FILE
        if default.exists():
            self.open_path(default)
        else:
            self.refresh()

    # ── UI ────────────────────────────────────────────────────────────────────

    def build_ui(self):
        frame = ttk.Frame(self, padding=(20, 16))
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(3, weight=1)

        device = theme.card(frame, "ESP32 collegato")
        device.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        device.columnconfigure(1, weight=1)
        ttk.Label(device, text="Porta COM", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", pady=4, padx=(0, 12))
        self.port_box = ttk.Combobox(device, state="readonly")
        self.port_box.grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Button(device, text="Aggiorna", command=self.refresh_ports).grid(
            row=0, column=2, sticky="ew", padx=(8, 0), pady=4)
        self.detect_button = ttk.Button(device, text="Rileva", command=self.start_detect)
        self.detect_button.grid(row=0, column=3, sticky="ew", padx=(8, 0), pady=4)
        ttk.Label(device, text="Chip rilevati", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", pady=4, padx=(0, 12))
        self.detected_box = ttk.Combobox(device, state="readonly")
        self.detected_box.grid(row=1, column=1, columnspan=2, sticky="ew", pady=4)
        ttk.Button(device, text="Nuova scheda", command=self.add_target).grid(
            row=1, column=3, sticky="ew", padx=(8, 0), pady=4)
        self.refresh_detected()

        ttk.Label(frame, text="Server").grid(row=0, column=0, sticky="w", pady=4, padx=(0, 12))
        ttk.Entry(frame, textvariable=self.url_var, style="Page.TEntry").grid(
            row=0, column=1, sticky="ew", pady=4)
        ttk.Button(frame, text="Apri dal server", command=self.open_server,
                   style="Page.TButton").grid(row=0, column=2, padx=(8, 0), pady=4)

        files = ttk.Frame(frame)
        files.grid(row=1, column=0, columnspan=3, sticky="w", pady=4)
        for text, command in (("Nuovo", self.new), ("Apri file…", self.open_file),
                              ("Salva", self.save), ("Salva con nome…", self.save_as)):
            ttk.Button(files, text=text, command=command,
                       style="Accent.TButton" if text == "Salva" else "Page.TButton").pack(
                side="left", padx=(0, 6))

        panes = ttk.PanedWindow(frame, orient="horizontal")
        panes.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=12)

        products = theme.card(panes, "Prodotti")
        products.rowconfigure(0, weight=1)
        products.columnconfigure(0, weight=1)
        product_box = theme.field_box(products)
        product_box.grid(row=0, column=0, sticky="nsew")
        self.product_list = tk.Listbox(product_box, exportselection=False, width=24,
                                       activestyle="none")
        self.product_list.pack(fill="both", expand=True)
        self.product_list.bind("<<ListboxSelect>>", lambda _e: self.refresh_targets())
        self.product_list.bind("<Double-1>", lambda _e: self.rename_product())
        buttons = ttk.Frame(products, style="Inner.TFrame")
        buttons.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        for text, command in (("Aggiungi", self.add_product), ("Rinomina", self.rename_product),
                              ("Elimina", self.delete_product), ("▲", lambda: self.move_product(-1)),
                              ("▼", lambda: self.move_product(1))):
            ttk.Button(buttons, text=text, command=command,
                       width=3 if len(text) == 1 else None).pack(side="left", padx=(0, 4))
        panes.add(products, weight=1)

        targets = theme.card(panes, "Chip e schede supportati")
        targets.rowconfigure(0, weight=1)
        targets.columnconfigure(0, weight=1)
        columns = {"chip": ("Chip", 90), "board": ("Tipo scheda", 130),
                   "folder": ("Cartella remota", 170), "status": ("Stato", 220)}
        self.target_tree = ttk.Treeview(targets, columns=list(columns), show="headings",
                                        selectmode="browse")
        for key, (text, width) in columns.items():
            self.target_tree.heading(key, text=text, anchor="w")
            self.target_tree.column(key, width=width, stretch=True)
        self.target_tree.grid(row=0, column=0, sticky="nsew")
        self.target_tree.bind("<Double-1>", lambda _e: self.edit_target())
        self.target_tree.tag_configure("error", foreground=theme.ERROR)
        buttons = ttk.Frame(targets, style="Inner.TFrame")
        buttons.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        for text, command in (("Aggiungi", self.add_target), ("Modifica", self.edit_target),
                              ("Elimina", self.delete_target)):
            ttk.Button(buttons, text=text, command=command).pack(side="left", padx=(0, 4))
        self.verify_button = ttk.Button(buttons, text="Verifica cartelle", command=self.verify)
        self.verify_button.pack(side="right")
        panes.add(targets, weight=3)

        ttk.Label(frame, textvariable=self.status_var, style="Status.TLabel").grid(
            row=4, column=0, columnspan=2, sticky="w")
        theme.brand(frame).grid(row=4, column=2, sticky="e")

    def refresh(self, select=None):
        """Ridisegna l'elenco prodotti; select = indice da selezionare."""
        if select is None:
            select = self.selected_index()
        self.product_list.delete(0, "end")
        for product in self.catalog["products"]:
            self.product_list.insert("end", product["name"])
        count = len(self.catalog["products"])
        if count:
            select = min(select or 0, count - 1)
            self.product_list.selection_set(select)
            self.product_list.see(select)
        self.refresh_targets()
        self.update_title()

    def refresh_targets(self):
        self.target_tree.delete(*self.target_tree.get_children())
        product = self.selected_product()
        if not product:
            return
        base = self.url_var.get()
        for i, target in enumerate(product["targets"]):
            status = self.status.get(catalog.folder_url(base, target["folder"]), "")
            self.target_tree.insert("", "end", iid=str(i), tags=(
                "error" if status.startswith("ERRORE") else ()), values=(
                chip_label(target["chip"]), target["board"], target["folder"], status))

    def update_title(self):
        name = self.path.name if self.path else "nuovo catalogo"
        self.title(f"{'*' if self.dirty else ''}{name} — {APP_TITLE}")

    def changed(self, select=None):
        self.dirty = True
        self.refresh(select)

    def selected_index(self):
        selection = self.product_list.curselection()
        return selection[0] if selection else None

    def selected_product(self):
        index = self.selected_index()
        return self.catalog["products"][index] if index is not None else None

    def selected_target_index(self):
        selection = self.target_tree.selection()
        return int(selection[0]) if selection else None

    def all_boards(self):
        return sorted({t["board"] for p in self.catalog["products"] for t in p["targets"]})

    # ── Prodotti ──────────────────────────────────────────────────────────────

    def ask_product_name(self, title, initial=""):
        name = theme.askstring(APP_TITLE, title, initialvalue=initial, parent=self)
        name = (name or "").strip()
        if not name:
            return None
        if any(p["name"] == name for p in self.catalog["products"] if p["name"] != initial):
            theme.showwarning(APP_TITLE, f"Esiste già un prodotto «{name}».")
            return None
        return name

    def add_product(self):
        name = self.ask_product_name("Nome del prodotto (come appare nel flash tool):")
        if name:
            self.catalog["products"].append({"name": name, "targets": []})
            self.changed(len(self.catalog["products"]) - 1)

    def rename_product(self):
        product = self.selected_product()
        if not product:
            return
        name = self.ask_product_name("Nuovo nome del prodotto:", product["name"])
        if name and name != product["name"]:
            product["name"] = name
            self.changed()

    def delete_product(self):
        product = self.selected_product()
        if product and theme.askyesno(APP_TITLE, f"Eliminare «{product['name']}» "
                                           f"e le sue {len(product['targets'])} schede?"):
            self.catalog["products"].remove(product)
            self.changed()

    def move_product(self, step):
        index = self.selected_index()
        products = self.catalog["products"]
        if index is None or not 0 <= index + step < len(products):
            return
        products[index], products[index + step] = products[index + step], products[index]
        self.changed(index + step)

    # ── Schede ────────────────────────────────────────────────────────────────

    def add_target(self):
        product = self.selected_product()
        if not product:
            theme.showinfo(APP_TITLE, "Aggiungi o seleziona prima un prodotto.")
            return
        # il chip proposto è quello scelto tra i rilevati, se ce n'è uno
        info = self.selected_detected()
        dialog = TargetDialog(self, f"Nuova scheda — {product['name']}",
                              {"chip": info["chip"] if info else "esp32"}, self.all_boards())
        if dialog.result and self.check_unique(product, dialog.result):
            product["targets"].append(dialog.result)
            self.changed()

    def edit_target(self):
        product, index = self.selected_product(), self.selected_target_index()
        if product is None or index is None:
            return
        dialog = TargetDialog(self, f"Modifica scheda — {product['name']}",
                              product["targets"][index], self.all_boards())
        if dialog.result and self.check_unique(product, dialog.result, skip=index):
            product["targets"][index] = dialog.result
            self.changed()

    def delete_target(self):
        product, index = self.selected_product(), self.selected_target_index()
        if product is not None and index is not None:
            del product["targets"][index]
            self.changed()

    def check_unique(self, product, target, skip=None):
        for i, other in enumerate(product["targets"]):
            if i != skip and (other["chip"], other["board"]) == (target["chip"], target["board"]):
                theme.showwarning(APP_TITLE, f"{target_label(target)} è già presente "
                                       f"in «{product['name']}».")
                return False
        return True

    # ── ESP32 collegato ───────────────────────────────────────────────────────

    def refresh_ports(self):
        self.ports = esp_device.esp_ports()
        self.port_box["values"] = [f"{p.device}  —  {p.description}" for p in self.ports]
        if not self.ports:
            self.port_box.set("")
            return
        guess = guess_port(self.ports)
        self.port_box.current(guess if guess is not None else 0)

    def refresh_detected(self):
        if self.detected:
            self.detected_box["values"] = [detected_label(info) for info in self.detected]
            self.detected_box.current(0)
        else:
            self.detected_box["values"] = []
            self.detected_box.set("premi «Rileva» con la scheda collegata")

    def selected_detected(self):
        index = self.detected_box.current()
        return self.detected[index] if 0 <= index < len(self.detected) else None

    def start_detect(self):
        index = self.port_box.current()
        if index < 0:
            theme.showwarning(APP_TITLE, "Collega la scheda e seleziona la porta COM.\n"
                              "Se la porta non compare nell'elenco, premi Aggiorna.")
            return
        port = self.ports[index].device
        self.detect_button.state(["disabled"])
        self.status_var.set(f"Rilevamento chip su {port}…")
        threading.Thread(target=self.run_detect, args=(port,), daemon=True).start()

    def run_detect(self, port):
        try:
            info = esp_device.detect(port)
        except BaseException as e:  # esptool usa anche SystemExit per gli errori
            self.events.put(("detect_error", f"{type(e).__name__}: {e}"))
        else:
            self.events.put(("detected", info))

    def chip_detected(self, info):
        self.detect_button.state(["!disabled"])
        # la stessa scheda rilevata di nuovo torna in cima all'elenco
        same = (info["mac"], info["port"]) if info["mac"] else None
        self.detected = [d for d in self.detected
                         if not same or (d["mac"], d["port"]) != same]
        self.detected.insert(0, info)
        self.refresh_detected()
        if info["chip"] not in CHIPS:
            self.status_var.set(f"Rilevato {info['description']}: chip non previsto dal catalogo")
        else:
            self.status_var.set(f"Rilevato {chip_label(info['chip'])} su {info['port']} — "
                                "«Nuova scheda» lo usa per il prodotto selezionato")

    def detect_error(self, error):
        self.detect_button.state(["!disabled"])
        self.status_var.set("Chip non rilevato")
        if not is_connect_error(error):
            theme.showerror(APP_TITLE, f"Impossibile leggere il chip:\n{error}\n\n"
                                 f"{connect_hint(error)}")
            return
        # schede senza reset automatico (RTS/DTR non collegati a EN/IO0):
        # BOOT + RESET a mano, poi Riprova
        if theme.askretrycancel(APP_TITLE, "L'ESP32 non ha risposto.\n\n"
                                     f"{connect_hint(error, 'Riprova', baud_tip=False)}", icon="warning"):
            self.start_detect()

    # ── Verifica ──────────────────────────────────────────────────────────────

    def verify(self):
        base = catalog.clean_url(self.url_var.get())
        if not base:
            theme.showwarning(APP_TITLE, "Inserisci l'URL del server.")
            return
        self.url_var.set(base)
        checks = {catalog.folder_url(base, t["folder"]): t
                  for p in self.catalog["products"] for t in p["targets"]}
        if not checks:
            return
        self.status = {url: "verifica…" for url in checks}
        self.refresh_targets()
        self.verify_button.state(["disabled"])
        self.status_var.set(f"Verifica di {len(checks)} cartelle su {base}…")
        threading.Thread(target=self.run_verify, args=(checks,), daemon=True).start()

    def run_verify(self, checks):
        for url, target in checks.items():
            self.events.put(("checked", (url, check_folder(url, target))))
        self.events.put(("verified", None))

    def poll_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "checked":
                    self.status[value[0]] = value[1]
                    self.refresh_targets()
                elif kind == "verified":
                    self.verify_button.state(["!disabled"])
                    bad = sum(s.startswith("ERRORE") for s in self.status.values())
                    self.status_var.set(f"Verifica completata: {bad} cartelle con errori"
                                        if bad else "Verifica completata: tutte le cartelle OK")
                elif kind == "server_catalog":
                    self.loaded(*value)
                elif kind == "server_error":
                    theme.showerror(APP_TITLE, value)
                    self.status_var.set("Lettura dal server non riuscita")
                elif kind == "log":  # avanzamento di esptool durante il rilevamento
                    if value.strip(". \n"):  # "Connecting" arriva un punto alla volta
                        self.status_var.set(value.strip().splitlines()[-1])
                elif kind == "detected":
                    self.chip_detected(value)
                elif kind == "detect_error":
                    self.detect_error(value)
        except queue.Empty:
            pass
        self.after(100, self.poll_events)

    # ── File ──────────────────────────────────────────────────────────────────

    def confirm_discard(self):
        if not self.dirty:
            return True
        answer = theme.askyesnocancel(APP_TITLE, "Salvare le modifiche al catalogo?")
        if answer is None:
            return False
        return self.save() if answer else True

    def loaded(self, data, path, source):
        self.catalog = data
        self.path = path
        self.dirty = False
        self.status = {}
        self.refresh(0)
        self.status_var.set(f"Aperto {source}")

    def new(self):
        if self.confirm_discard():
            self.loaded(catalog.new_catalog(), None, "nuovo catalogo")

    def open_file(self):
        if not self.confirm_discard():
            return
        path = filedialog.askopenfilename(
            title=f"Apri {INDEX_FILE}", filetypes=[("Catalogo JSON", "*.json")],
            initialdir=FIRMWARE_DIR if FIRMWARE_DIR.is_dir() else ROOT)
        if path:
            self.open_path(Path(path))

    def open_path(self, path):
        try:
            data = catalog.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            theme.showerror(APP_TITLE, f"Impossibile aprire {path}:\n{e}")
            self.refresh()
            return
        self.loaded(data, path, str(path))

    def open_server(self):
        if not self.confirm_discard():
            return
        base = catalog.clean_url(self.url_var.get())
        if not base:
            theme.showwarning(APP_TITLE, "Inserisci l'URL del server.")
            return
        self.url_var.set(base)
        url = urljoin(catalog.base_url(base), INDEX_FILE)
        self.status_var.set(f"Lettura {url}…")
        threading.Thread(target=self.run_open_server, args=(url,), daemon=True).start()

    def run_open_server(self, url):
        try:
            with fetch(url) as response:
                data = catalog.loads(response.read().decode("utf-8"))
        except Exception as e:
            self.events.put(("server_error", f"Impossibile leggere\n{url}\n\n{type(e).__name__}: {e}"))
        else:
            # non c'è un file locale: "Salva" chiederà dove salvarlo
            self.events.put(("server_catalog", (data, None, url)))

    def save(self):
        if self.path is None:
            return self.save_as()
        errors = catalog.validate(self.catalog)
        if errors and not theme.askyesno(
                APP_TITLE, "Il catalogo ha dei problemi:\n\n• " + "\n• ".join(errors[:15])
                + "\n\nSalvare comunque?"):
            return False
        try:
            self.path.write_text(catalog.dumps(self.catalog), encoding="utf-8")
        except OSError as e:
            theme.showerror(APP_TITLE, f"Impossibile salvare {self.path}:\n{e}")
            return False
        self.dirty = False
        self.update_title()
        self.status_var.set(f"Salvato {self.path} — copialo sotto l'URL base del server")
        return True

    def save_as(self):
        initial = FIRMWARE_DIR if FIRMWARE_DIR.is_dir() else ROOT
        path = filedialog.asksaveasfilename(
            title=f"Salva {INDEX_FILE}", defaultextension=".json", initialfile=INDEX_FILE,
            initialdir=self.path.parent if self.path else initial,
            filetypes=[("Catalogo JSON", "*.json")])
        if not path:
            return False
        self.path = Path(path)
        return self.save()

    def close(self):
        if self.confirm_discard():
            self.destroy()


if __name__ == "__main__":
    CreatorApp().mainloop()
