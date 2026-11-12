"""
Chiave di attivazione del flash tool.

Ogni chiave è un file JSON nella cartella degli aggiornamenti (updater.UPDATE_URL):
    https://drive.steplab.net/esp32/<CHIAVE>.json

    {"server_url": "http://100.42.178.156/init", "name": "Cliente (facoltativo)"}

server_url è il server firmware predefinito per chi usa quella chiave. Il file
non va in cache sul CDN: cambiarlo o cancellarlo vale dall'avvio successivo
(una chiave cancellata non è più valida e il programma ne chiede un'altra).

Creare una chiave nuova (file in dist\\keys\\, da copiare poi sul server):
    .venv\\Scripts\\python activation.py http://server/base "Nome cliente"
"""

import json
import re
import secrets
import sys
import urllib.error
from pathlib import Path
from urllib.parse import urljoin

import updater
from i18n import tr

KEY_PATTERN = re.compile(r"^[A-Z0-9]{4}(-[A-Z0-9]{4}){3}$")  # XXXX-XXXX-XXXX-XXXX
KEY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # senza 0/O e 1/I, facili da confondere


class InvalidKey(Exception):
    """La chiave non esiste sul server (o il suo file non è valido)."""


def normalize(key):
    """Maiuscole, senza spazi; i trattini mancanti vengono aggiunti."""
    key = re.sub(r"[\s-]+", "", key or "").upper()
    if len(key) == 16:
        key = "-".join(key[i:i + 4] for i in range(0, 16, 4))
    return key


def is_well_formed(key):
    return bool(KEY_PATTERN.match(key))


def fetch(key):
    """Il contenuto del file della chiave.

    InvalidKey se la chiave non esiste; gli errori di rete escono come eccezioni.
    """
    if not is_well_formed(key):
        raise InvalidKey(tr("formato non valido (XXXX-XXXX-XXXX-XXXX)"))
    try:
        with updater._open(urljoin(updater.UPDATE_URL, f"{key}.json"),
                           updater.CHECK_TIMEOUT) as response:
            info = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            raise InvalidKey(tr("chiave non riconosciuta")) from e
        raise
    except ValueError as e:
        raise InvalidKey(tr("file della chiave non valido: {error}", error=e)) from e
    if not isinstance(info, dict) or not str(info.get("server_url", "")).strip():
        raise InvalidKey(tr("nel file della chiave manca server_url"))
    return info


def new_key():
    return "-".join("".join(secrets.choice(KEY_ALPHABET) for _ in range(4)) for _ in range(4))


def write_key(server_url, name="", folder=None):
    """Crea <chiave>.json in folder (default dist\\keys); ritorna (chiave, file)."""
    folder = Path(folder or Path(__file__).resolve().parent / "dist" / "keys")
    folder.mkdir(parents=True, exist_ok=True)
    key = new_key()
    info = {"server_url": server_url, "name": name}
    path = folder / f"{key}.json"
    path.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return key, path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit('uso: python activation.py <server_url> ["nome cliente"]')
    key, path = write_key(sys.argv[1], " ".join(sys.argv[2:]))
    print(f"Chiave {key}\nCreato {path}: copiarlo in {updater.UPDATE_URL}")
