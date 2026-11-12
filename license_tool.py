"""
ST ESP32 License Tool — crea e revoca le chiavi di attivazione del flash tool.

Ogni chiave è un file <CHIAVE>.json nella cartella esp32/ dello storage
(https://drive.steplab.net/esp32/, vedi activation.py):
    {"server_url": "http://100.42.178.156/init", "name": "Nome cliente"}

I file vengono caricati e cancellati via SFTP su storage.bunnycdn.com, con la
chiave dell'host verificata (HOST_KEY_SHA256). La password SFTP non è nel
codice: viene chiesta al primo uso e salvata in %APPDATA%\\ST_ESP32_license_tool.
Una copia di ogni chiave creata resta nella cartella keys accanto al programma.
"""

import base64
import hashlib
import io
import json
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import paramiko

import theme  # prima di tk.Tk(): registra la finestra da cui si è partiti (vedi theme.center)
import activation
from catalog import DEFAULT_SERVER_URL, clean_url

APP_TITLE = "ST ESP32 License Tool"
SFTP_HOST = "storage.bunnycdn.com"
SFTP_PORT = 22
SFTP_USER = "schema"
SFTP_FOLDER = "esp32"  # = https://drive.steplab.net/esp32/
# impronta SHA256 della chiave RSA del server: un server diverso non riceve la password
HOST_KEY_SHA256 = "quUKWPbEisQnyRjOXfMyDcgLomXV3zHaz4JzKl0fE9I"
TIMEOUT = 20

if getattr(sys, "frozen", False):
    PROGRAM_DIR = Path(sys.executable).resolve().parent
else:
    PROGRAM_DIR = Path(__file__).resolve().parent
KEYS_DIR = PROGRAM_DIR / "keys"
CONFIG_FILE = Path(os.environ.get("APPDATA", Path.home())) / "ST_ESP32_license_tool" / "config.json"


def load_config():
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(config):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


class Storage:
    """Connessione SFTP alla cartella delle chiavi; da usare con with."""

    def __init__(self, password):
        self.password = password

    def __enter__(self):
        self.transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        try:
            self.transport.start_client(timeout=TIMEOUT)
            key = self.transport.get_remote_server_key()
            fingerprint = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode()
            if fingerprint.rstrip("=") != HOST_KEY_SHA256:
                raise RuntimeError(f"{SFTP_HOST}: chiave del server sconosciuta "
                                   f"(SHA256:{fingerprint}), connessione interrotta")
            self.transport.auth_password(SFTP_USER, self.password)
            self.sftp = paramiko.SFTPClient.from_transport(self.transport)
        except BaseException:
            self.transport.close()
            raise
        return self

    def __exit__(self, *exc):
        self.transport.close()

    def keys(self):
        """[(chiave, contenuto del file)] delle chiavi sul server, in ordine di nome cliente."""
        result = []
        for name in self.sftp.listdir(SFTP_FOLDER):
            key = name[:-5] if name.endswith(".json") else ""
            if not activation.is_well_formed(key):
                continue  # manifest del programma e altri file
            try:
                with self.sftp.open(f"{SFTP_FOLDER}/{name}") as f:
                    info = json.loads(f.read().decode("utf-8"))
            except (OSError, ValueError):
                info = {"name": "(file non leggibile)", "server_url": ""}
            result.append((key, info))
        return sorted(result, key=lambda item: (str(item[1].get("name", "")).lower(), item[0]))

    def upload(self, key, text):
        self.sftp.putfo(io.BytesIO(text.encode("utf-8")), f"{SFTP_FOLDER}/{key}.json")

    def remove(self, key):
        self.sftp.remove(f"{SFTP_FOLDER}/{key}.json")


class LicenseApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(720, 520)
        theme.apply(self)
        self.events = queue.Queue()
        self.config_data = load_config()
        self.keys = []  # [(chiave, contenuto)] come nell'elenco
        self.busy = False

        self.name_var = tk.StringVar()
        self.url_var = tk.StringVar(value=self.config_data.get("server_url", DEFAULT_SERVER_URL))
        self.key_var = tk.StringVar(value=activation.new_key())
        self.status_var = tk.StringVar(value="")

        self.build_ui()
        theme.center(self)
        self.after(100, self.poll_events)
        self.after(200, self.refresh)

    # ── UI ────────────────────────────────────────────────────────────────────

    def build_ui(self):
        frame = ttk.Frame(self, padding=(20, 16))
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)

        new = theme.card(frame, "Nuova licenza")
        new.grid(row=0, column=0, sticky="ew")
        new.columnconfigure(1, weight=1)
        ttk.Label(new, text="Cliente", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", pady=5, padx=(0, 12))
        self.name_entry = ttk.Entry(new, textvariable=self.name_var)
        self.name_entry.grid(row=0, column=1, columnspan=2, sticky="ew", pady=5)
        ttk.Label(new, text="Server firmware", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", pady=5, padx=(0, 12))
        ttk.Entry(new, textvariable=self.url_var).grid(
            row=1, column=1, columnspan=2, sticky="ew", pady=5)
        ttk.Label(new, text="Chiave", style="Card.TLabel").grid(
            row=2, column=0, sticky="w", pady=5, padx=(0, 12))
        ttk.Entry(new, textvariable=self.key_var, state="readonly").grid(
            row=2, column=1, sticky="ew", pady=5)
        ttk.Button(new, text="Genera chiave", command=self.new_key).grid(
            row=2, column=2, sticky="ew", padx=(8, 0), pady=5)

        self.create_button = ttk.Button(frame, text="Crea e carica", style="Primary.TButton",
                                        command=self.create, cursor="hand2")
        self.create_button.grid(row=1, column=0, sticky="ew", pady=(12, 0))

        existing = theme.card(frame, "Licenze sul server")
        existing.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        existing.columnconfigure(0, weight=1)
        existing.rowconfigure(0, weight=1)
        box = theme.field_box(existing)
        box.grid(row=0, column=0, rowspan=4, sticky="nsew")
        self.key_list = tk.Listbox(box, height=8, activestyle="none")
        self.key_list.pack(fill="both", expand=True)
        self.refresh_button = ttk.Button(existing, text="Aggiorna", command=self.refresh)
        self.copy_button = ttk.Button(existing, text="Copia chiave", command=self.copy_key)
        self.revoke_button = ttk.Button(existing, text="Revoca…", command=self.revoke)
        for row, button in enumerate((self.refresh_button, self.copy_button, self.revoke_button)):
            button.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=(0, 4))
        ttk.Button(existing, text="Password SFTP…", command=self.change_password).grid(
            row=3, column=1, sticky="sew", padx=(8, 0))

        footer = ttk.Frame(frame)
        footer.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var, style="Status.TLabel").grid(
            row=0, column=0, sticky="w")
        theme.brand(footer).grid(row=0, column=1, sticky="e")
        self.name_entry.focus_set()

    def set_busy(self, busy):
        self.busy = busy
        for button in (self.create_button, self.refresh_button, self.revoke_button):
            button.state(["disabled"] if busy else ["!disabled"])

    def show_keys(self, keys):
        self.keys = keys
        self.key_list.delete(0, "end")
        for key, info in keys:
            self.key_list.insert("end", f"{key}   {info.get('name') or '(senza nome)'}   "
                                        f"→ {info.get('server_url', '')}")

    def selected_key(self):
        selection = self.key_list.curselection()
        return self.keys[selection[0]] if selection else None

    # ── Azioni ────────────────────────────────────────────────────────────────

    def new_key(self):
        self.key_var.set(activation.new_key())

    def password(self):
        """La password SFTP salvata; se manca la chiede (None se l'utente annulla)."""
        if not self.config_data.get("sftp_password"):
            self.change_password()
        return self.config_data.get("sftp_password")

    def change_password(self):
        text = theme.askstring(APP_TITLE, f"Password SFTP di {SFTP_USER}@{SFTP_HOST}.\n"
                                          f"Viene salvata in {CONFIG_FILE}.",
                               initialvalue=self.config_data.get("sftp_password", ""))
        if text is not None and text.strip():
            self.config_data["sftp_password"] = text.strip()
            save_config(self.config_data)

    def run(self, job, *args):
        """Esegue job(storage, *args) in un thread, con la connessione SFTP aperta."""
        password = self.password()
        if not password:
            self.status_var.set("Serve la password SFTP")
            return
        self.set_busy(True)

        def work():
            try:
                with Storage(password) as storage:
                    job(storage, *args)
            except paramiko.AuthenticationException:
                self.events.put(("error", ("Password SFTP non accettata dal server.", True)))
            except Exception as e:
                self.events.put(("error", (f"{type(e).__name__}: {e}", False)))
        threading.Thread(target=work, daemon=True).start()

    def refresh(self):
        self.status_var.set(f"Lettura delle licenze da {SFTP_HOST}…")
        self.run(lambda storage: self.events.put(("keys", storage.keys())))

    def create(self):
        name = self.name_var.get().strip()
        url = clean_url(self.url_var.get())
        key = self.key_var.get()
        if not name:
            theme.showwarning(APP_TITLE, "Inserisci il nome del cliente.")
            self.name_entry.focus_set()
            return
        if not url:
            theme.showwarning(APP_TITLE, "Inserisci l'URL del server firmware.")
            return
        if any(info.get("name", "").strip().lower() == name.lower() for _k, info in self.keys):
            if not theme.askyesno(APP_TITLE, f"Esiste già una licenza per «{name}». "
                                             "Crearne un'altra?"):
                return
        self.url_var.set(url)
        self.config_data["server_url"] = url
        save_config(self.config_data)
        text = json.dumps({"server_url": url, "name": name}, indent=2, ensure_ascii=False) + "\n"
        self.status_var.set(f"Caricamento della chiave {key}…")
        self.run(self.run_create, key, name, text)

    def run_create(self, storage, key, name, text):
        if f"{key}.json" in storage.sftp.listdir(SFTP_FOLDER):
            raise RuntimeError(f"la chiave {key} esiste già sul server: generane un'altra")
        storage.upload(key, text)
        try:  # copia locale, per sapere a chi è stata data ogni chiave
            KEYS_DIR.mkdir(parents=True, exist_ok=True)
            (KEYS_DIR / f"{key}.json").write_text(text, encoding="utf-8")
        except OSError:
            pass
        # come la leggerà il flash tool: dall'URL pubblico
        try:
            activation.fetch(key)
            check = "verificata su " + activation.updater.UPDATE_URL
        except Exception as e:
            check = f"non ancora leggibile dall'URL pubblico ({e})"
        self.events.put(("created", (key, name, check, storage.keys())))

    def created(self, key, name, check, keys):
        self.set_busy(False)
        self.show_keys(keys)
        index = next((i for i, (k, _info) in enumerate(keys) if k == key), None)
        if index is not None:
            self.key_list.selection_set(index)
            self.key_list.see(index)
        self.clipboard_clear()
        self.clipboard_append(key)
        self.status_var.set(f"Creata {key} (negli appunti)")
        theme.showinfo(APP_TITLE, f"Licenza creata per {name}:\n\n{key}\n\n"
                                  f"La chiave è stata copiata negli appunti; {check}.")
        self.name_var.set("")
        self.new_key()

    def copy_key(self):
        entry = self.selected_key()
        if not entry:
            theme.showwarning(APP_TITLE, "Scegli una licenza nell'elenco.")
            return
        self.clipboard_clear()
        self.clipboard_append(entry[0])
        self.status_var.set(f"Chiave {entry[0]} copiata negli appunti")

    def revoke(self):
        entry = self.selected_key()
        if not entry:
            theme.showwarning(APP_TITLE, "Scegli una licenza nell'elenco.")
            return
        key, info = entry
        if not theme.askyesno(APP_TITLE, f"Revocare la licenza di {info.get('name') or key}?\n\n"
                                         f"{key}\n\nIl file viene cancellato dal server: al "
                                         "prossimo avvio con connessione il flash tool di "
                                         "questo cliente chiederà una nuova chiave."):
            return
        self.status_var.set(f"Revoca della chiave {key}…")

        def job(storage):
            storage.remove(key)
            self.events.put(("revoked", (key, storage.keys())))
        self.run(job)

    def poll_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "keys":
                    self.set_busy(False)
                    self.show_keys(value)
                    self.status_var.set(f"{len(value)} licenze sul server")
                elif kind == "created":
                    self.created(*value)
                elif kind == "revoked":
                    self.set_busy(False)
                    self.show_keys(value[1])
                    self.status_var.set(f"Licenza {value[0]} revocata")
                elif kind == "error":
                    message, bad_password = value
                    self.set_busy(False)
                    self.status_var.set("Errore")
                    theme.showerror(APP_TITLE, f"Operazione non riuscita:\n{message}")
                    if bad_password:
                        self.change_password()
        except queue.Empty:
            pass
        self.after(100, self.poll_events)


if __name__ == "__main__":
    LicenseApp().mainloop()
