"""
Catalogo dei firmware sul server: <url>/index.json, creato con manifest_creator.py.

Per ogni prodotto elenca le combinazioni supportate di chip ESP32 e tipo di
scheda, ognuna con la sua cartella remota (relativa all'URL base oppure URL
completo) che contiene manifest.json e i .bin creati da prepare_firmware.py:

    {
      "format": 1,
      "updated": "2026-10-24T12:00:00",
      "products": [
        {"name": "Modulo Pompa",
         "targets": [
           {"chip": "esp32",   "board": "esp32dev", "folder": "moduloPompa"},
           {"chip": "esp32s3", "board": "devkitc1", "folder": "moduloPompa_s3"}
         ]}
      ]
    }
"""

import json
import re
from datetime import datetime
from urllib.parse import urljoin

INDEX_FILE = "index.json"
FORMAT = 1

# URL proposto finché l'utente non ne usa uno diverso (che viene poi salvato).
DEFAULT_SERVER_URL = "http://100.42.178.156/init"

# Nome usato da esptool (--chip) -> nome mostrato (CHIP_NAME di esptool).
CHIPS = {
    "esp32": "ESP32",
    "esp32s2": "ESP32-S2",
    "esp32s3": "ESP32-S3",
    "esp32c2": "ESP32-C2",
    "esp32c3": "ESP32-C3",
    "esp32c5": "ESP32-C5",
    "esp32c6": "ESP32-C6",
    "esp32c61": "ESP32-C61",
    "esp32h2": "ESP32-H2",
    "esp32p4": "ESP32-P4",
}


def clean_url(url):
    """Corregge gli errori di battitura più comuni nell'URL del server.

    "http://http://host/x" -> "http://host/x", "host/x" -> "http://host/x".
    """
    url = url.strip()
    schemes = re.match(r"((?:https?:/*)+)", url, re.I)
    if schemes:
        # tiene l'ultimo schema scritto e scarta i doppioni
        scheme = re.findall(r"https?", schemes.group(1), re.I)[-1].lower()
        url = f"{scheme}://{url[schemes.end():]}"
    elif url:
        url = "http://" + url
    return url


def base_url(url):
    return url.strip().rstrip("/") + "/"


def folder_url(base, folder):
    """URL della cartella di una scheda: relativa all'URL base o già completa."""
    return urljoin(base_url(base), folder.strip().strip("/") + "/")


def chip_id(chip_name):
    """"ESP32-S3" (CHIP_NAME di esptool) -> "esp32s3"."""
    return chip_name.lower().replace("-", "")


def chip_label(chip):
    return CHIPS.get(chip, chip)


def target_label(target):
    board = target.get("board")
    return f"{chip_label(target['chip'])} — {board}" if board else chip_label(target["chip"])


def new_catalog():
    return {"format": FORMAT, "products": []}


def validate(catalog):
    """Lista degli errori (vuota se il catalogo è valido)."""
    errors = []
    names = set()
    for product in catalog.get("products", []):
        name = product.get("name", "").strip()
        if not name:
            errors.append("Un prodotto non ha nome")
        elif name in names:
            errors.append(f"Prodotto duplicato: {name}")
        names.add(name)
        if not product.get("targets"):
            errors.append(f"{name}: nessuna scheda supportata")
        seen = set()
        for target in product.get("targets", []):
            key = (target.get("chip"), target.get("board", "").strip())
            if target.get("chip") not in CHIPS:
                errors.append(f"{name}: chip sconosciuto {target.get('chip')!r}")
            if not key[1]:
                errors.append(f"{name}: tipo di scheda mancante")
            if not target.get("folder", "").strip():
                errors.append(f"{name} / {target_label(target)}: cartella mancante")
            if key in seen:
                errors.append(f"{name}: {target_label(target)} ripetuto")
            seen.add(key)
    return errors


def loads(text):
    catalog = json.loads(text)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("products"), list):
        raise ValueError(f"{INDEX_FILE} non valido: manca l'elenco 'products'")
    if catalog.get("format", FORMAT) > FORMAT:
        raise ValueError(f"{INDEX_FILE} creato da una versione più recente (formato "
                         f"{catalog['format']}): aggiorna il programma")
    return catalog


def dumps(catalog):
    catalog = dict(catalog, format=FORMAT, updated=datetime.now().isoformat(timespec="seconds"))
    return json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"
