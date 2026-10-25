"""
Porte seriali e rilevamento del chip ESP32 collegato, usati da installer.py e
manifest_creator.py.
"""

import re
import time

import esptool
import serial
from esptool.cmds import detect_flash_size, reset_chip
from esptool.logger import TemplateLogger, log

import catalog

DETECT_BAUD = 115200

# Convertitori USB-seriale usati sulle schede ESP32 (VID, PID); None = qualsiasi PID.
ESP_USB_IDS = {
    (0x10C4, 0xEA60),  # Silicon Labs CP210x
    (0x1A86, 0x7523),  # WCH CH340
    (0x1A86, 0x7522),  # WCH CH340K
    (0x1A86, 0x55D4),  # WCH CH9102
    (0x0403, None),    # FTDI
    (0x303A, None),    # Espressif USB nativa (S2/S3/C3)
}
# FTDI a più canali (FT2232/FT4232): il primo canale è di solito JTAG,
# la seriale dell'ESP32 è sull'ultimo.
FTDI_MULTI_PIDS = {0x6010, 0x6011}
PROBE_SECONDS = 1.0

# esptool formatta alcuni messaggi con markup tipo [bold]...[/bold]
MARKUP_RE = re.compile(r"\[/?(?:bold|dim|italic|underline|red|green|yellow|blue|cyan)\]")


def port_number(port):
    m = re.search(r"(\d+)$", port.device)
    return int(m.group(1)) if m else 0


def port_score(port):
    """2 = convertitore tipico ESP32, 1 = altra porta USB, 0 = Bluetooth/virtuale."""
    if port.vid is None:
        return 0
    if (port.vid, port.pid) in ESP_USB_IDS or (port.vid, None) in ESP_USB_IDS:
        return 2
    return 1


def guess_port(ports):
    """Indice della porta più probabile per l'ESP32, senza aprirla (None se nessuna)."""
    candidates = [p for p in ports if port_score(p)]
    if not candidates:
        return None
    best = max(candidates, key=port_score)
    if best.vid == 0x0403 and best.pid in FTDI_MULTI_PIDS:
        same_chip = [p for p in candidates if (p.vid, p.pid, p.serial_number)
                     == (best.vid, best.pid, best.serial_number)]
        best = max(same_chip, key=port_number)
    return ports.index(best)


def port_receives_data(device):
    """Ascolta la porta senza resettare la scheda: True se arrivano dati.

    Un ESP32 in funzione di solito scrive log sulla seriale, così si
    distingue la porta giusta dai canali liberi dello stesso adattatore.
    """
    s = serial.Serial()
    s.port, s.baudrate, s.timeout = device, 115200, 0.1
    s.dtr = s.rts = False  # EN e IO0 non toccati: la scheda non si riavvia
    try:
        s.open()
        end = time.monotonic() + PROBE_SECONDS
        while time.monotonic() < end:
            if s.read(256):
                return True
        return False
    except serial.SerialException:
        return False
    finally:
        s.close()


def is_connect_error(error):
    return bool(re.search(r"Failed to connect|No serial data received", error or "", re.I))


def connect_hint(error, button="Carica firmware", baud_tip=True):
    if not is_connect_error(error):
        return "Controlla connessione, cavo e porta."
    return ("L'ESP32 non è entrato in modalità programmazione: alcune schede non "
            "ci entrano da sole e vanno avviate a mano.\n\n"
            "1. Controlla che la porta sia quella della scheda.\n"
            "2. Tieni premuto BOOT (IO0), premi e rilascia RESET (EN), poi rilascia BOOT.\n"
            f"3. Premi subito \"{button}\"."
            + ("\n\nSe non funziona ancora, prova la velocità 115200." if baud_tip else ""))


def detect(port):
    """Legge il chip collegato a port e riavvia la scheda.

    Ritorna {"chip": "esp32s3", "description": ..., "features": [...],
    "flash": "8MB" o None, "mac": ..., "port": port}. Solleva un'eccezione
    (anche SystemExit, come esptool) se la scheda non risponde.
    """
    esp = esptool.detect_chip(port, DETECT_BAUD)
    try:
        info = {"chip": catalog.chip_id(esp.CHIP_NAME), "port": port,
                "description": esp.get_chip_description(),
                "features": esp.get_chip_features(), "flash": None, "mac": None}
        try:
            info["mac"] = ":".join(f"{b:02x}" for b in esp.read_mac("BASE_MAC"))
        except Exception:
            pass
        try:
            esp.flash_spi_attach(0)
            info["flash"] = detect_flash_size(esp)
        except Exception:
            pass  # facoltativo: alcuni chip lo leggono solo con lo stub
        reset_chip(esp, "hard-reset")  # la scheda riparte normalmente
    finally:
        esp._port.close()
    return info


def detected_label(info):
    """"ESP32-S3 (QFN56) rev v0.2 · 8MB flash · Wi-Fi, BLE · COM5"."""
    parts = [info["description"]]
    if info.get("flash"):
        parts.append(f"{info['flash']} flash")
    if info.get("features"):
        parts.append(", ".join(info["features"]))
    parts.append(info["port"])
    return " · ".join(parts)


class QueueLogger(TemplateLogger):
    """Inoltra l'output di esptool alla GUI tramite una coda."""

    def __init__(self, events):
        self.events = events

    def print(self, *args, sep=" ", **kwargs):
        text = MARKUP_RE.sub("", sep.join(str(a) for a in args))
        if text.strip():
            self.events.put(("log", text))
        # la cancellazione non ha avanzamento: la GUI mostra una barra animata
        if text.startswith("Erasing"):
            self.events.put(("erasing", None))

    def note(self, message):
        self.print(f"Nota: {message}")

    def warning(self, message):
        self.print(f"Attenzione: {message}")

    def error(self, message):
        self.print(f"Errore: {message}")

    def stage(self, finish=False):
        pass

    def progress_bar(self, cur_iter, total_iters, prefix="", suffix="", bar_length=30):
        if total_iters:
            self.events.put(("progress", 100 * cur_iter / total_iters))

    def set_verbosity(self, verbosity):
        pass


_logger = None


def set_logger(events):
    """Manda l'output di esptool nella coda events.

    esptool accetta set_logger solo finché è attivo il suo logger: le chiamate
    successive cambiano soltanto la coda del logger già installato.
    """
    global _logger
    if _logger is None:
        _logger = QueueLogger(events)
        log.set_logger(_logger)
    _logger.events = events
