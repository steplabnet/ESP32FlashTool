"""
Aggiornamento automatico del flash tool.

Sul server (UPDATE_URL) stanno l'eseguibile dell'ultima versione e il suo manifest:
    https://drive.steplab.net/esp32/ST_ESP32_flash_tool.json
    https://drive.steplab.net/esp32/ST_ESP32_flash_tool_1.1.0.exe

    {"version": "1.1.0", "file": "ST_ESP32_flash_tool_1.1.0.exe", "size": 123456,
     "sha256": "...", "date": "2026-11-04", "notes": "testo facoltativo"}

All'avvio installer.py legge il manifest (in un thread: senza connessione non
succede niente) e, se la versione è più recente della sua, propone il download.
L'eseguibile scaricato, verificato con sha256, prende il posto di quello in uso
(che Windows lascia rinominare, ma non cancellare: la copia .old viene tolta
all'avvio successivo) e il programma si riavvia.

Ogni versione ha il suo nome di file: il CDN tiene in cache gli .exe per 30
giorni (anche ignorando ?v=...), mentre il .json non va in cache. Sovrascrivendo
lo stesso .exe i client scaricherebbero quello vecchio (e il checksum fallirebbe).

Creare il manifest dopo la compilazione (lo fa build_exe.bat):
    .venv\\Scripts\\python updater.py dist\\ST_ESP32_flash_tool.exe [note]
copia l'eseguibile in dist\\ST_ESP32_flash_tool_<versione>.exe (versione = VERSION
in installer.py) e scrive dist\\ST_ESP32_flash_tool.json. Poi copiare in UPDATE_URL
prima il .exe con la versione, poi il .json.
"""

import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

from i18n import tr

# ST_ESP32_UPDATE_URL permette di provare un aggiornamento da un altro server prima di pubblicarlo
UPDATE_URL = os.environ.get("ST_ESP32_UPDATE_URL") or "https://drive.steplab.net/esp32/"
MANIFEST_NAME = "ST_ESP32_flash_tool.json"
CHECK_TIMEOUT = 8      # la verifica all'avvio non deve far aspettare
DOWNLOAD_TIMEOUT = 30
USER_AGENT = "ST ESP32 Flash Tool"
FROZEN = getattr(sys, "frozen", False)


def version_key(version):
    """"1.10.2" -> (1, 10, 2): confronto numerico, non alfabetico."""
    return tuple(int(n) for n in re.findall(r"\d+", str(version)))


def is_newer(remote, local):
    return version_key(remote) > version_key(local)


def _open(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Cache-Control": "no-cache"})
    return urllib.request.urlopen(request, timeout=timeout)


def check(current_version):
    """Il manifest se sul server c'è una versione più recente, altrimenti None.

    Gli errori di rete escono come eccezioni: chi chiama decide di ignorarli.
    """
    with _open(urljoin(UPDATE_URL, MANIFEST_NAME), CHECK_TIMEOUT) as response:
        manifest = json.loads(response.read().decode("utf-8"))
    if not manifest.get("version") or not manifest.get("file"):
        raise ValueError(tr("{file}: mancano version o file", file=MANIFEST_NAME))
    return manifest if is_newer(manifest["version"], current_version) else None


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def target_path(manifest):
    """Dove scaricare il nuovo eseguibile.

    Dall'eseguibile: accanto a quello in uso, così può sostituirlo; se lì non si
    può scrivere (es. C:\\Program Files), e quando si lavora dai sorgenti, in Download.
    """
    if FROZEN:
        exe = Path(sys.executable).resolve()
        new = exe.with_name(f"{exe.stem}.new{exe.suffix}")
        try:
            new.write_bytes(b"")
            return new
        except OSError:
            pass
    downloads = Path.home() / "Downloads"
    if not downloads.is_dir():
        downloads = Path.home()
    return downloads / Path(manifest["file"]).name


def download(manifest, progress=None):
    """Scarica l'eseguibile del manifest, ne verifica lo sha256 e ritorna il percorso.

    progress(percentuale) viene chiamato durante il download.
    """
    path = target_path(manifest)
    tmp = path.with_name(path.name + ".part")
    try:
        with _open(urljoin(UPDATE_URL, manifest["file"]), DOWNLOAD_TIMEOUT) as response, \
                open(tmp, "wb") as out:
            total = int(response.headers.get("Content-Length") or manifest.get("size") or 0)
            done = 0
            for chunk in iter(lambda: response.read(1 << 16), b""):
                out.write(chunk)
                done += len(chunk)
                if total and progress:
                    progress(100 * done / total)
        expected = manifest.get("sha256")
        if expected and _sha256(tmp) != expected:
            raise RuntimeError(tr("{file}: checksum non valido, download corrotto",
                                  file=manifest["file"]))
        tmp.replace(path)
    except BaseException:
        _remove(tmp)
        if path.exists() and path.stat().st_size == 0:  # file vuoto di target_path
            _remove(path)
        raise
    return path


def _remove(path):
    try:
        path.unlink()
    except OSError:
        pass


def can_install(path):
    """True se path è il nuovo eseguibile accanto a quello in uso (vedi target_path)."""
    return FROZEN and path.parent == Path(sys.executable).resolve().parent


def install(path):
    """Mette path al posto dell'eseguibile in uso; poi chiamare restart()."""
    exe = Path(sys.executable).resolve()
    old = exe.with_name(f"{exe.stem}.{os.getpid()}.old")
    os.replace(exe, old)          # l'eseguibile in uso si può rinominare
    try:
        os.replace(path, exe)
    except OSError:
        os.replace(old, exe)      # rimette a posto la versione in uso
        raise


def restart():
    """Avvia l'eseguibile (già aggiornato); chi chiama deve poi chiudere il programma."""
    exe = Path(sys.executable).resolve()
    # il nuovo processo non deve riusare la cartella temporanea di questo
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    subprocess.Popen([str(exe)], env=env, cwd=str(exe.parent), close_fds=True,
                     creationflags=subprocess.DETACHED_PROCESS
                     | subprocess.CREATE_NEW_PROCESS_GROUP)


def cleanup():
    """Toglie le copie .old e i download interrotti lasciati dagli aggiornamenti."""
    if not FROZEN:
        return
    exe = Path(sys.executable).resolve()
    for pattern in (f"{exe.stem}.*.old", f"{exe.stem}.new{exe.suffix}*"):
        for leftover in exe.parent.glob(pattern):
            _remove(leftover)  # se è ancora in uso, la prossima volta


def write_manifest(exe, notes=""):
    """Copia l'eseguibile in <nome>_<versione>.exe e crea il manifest accanto.

    La versione è VERSION in installer.py. Ritorna (manifest, eseguibile, versione).
    """
    exe = Path(exe)
    source = (Path(__file__).resolve().parent / "installer.py").read_text(encoding="utf-8")
    version = re.search(r'^VERSION = "([^"]+)"', source, re.M).group(1)
    release = exe.with_name(f"{exe.stem}_{version}{exe.suffix}")
    shutil.copyfile(exe, release)
    manifest = {
        "version": version,
        "file": release.name,
        "size": release.stat().st_size,
        "sha256": _sha256(release),
        "date": datetime.date.today().isoformat(),
        "notes": notes,
    }
    out = exe.with_name(MANIFEST_NAME)
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out, release, version


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("uso: python updater.py dist\\ST_ESP32_flash_tool.exe [note]")
    out, release, version = write_manifest(sys.argv[1], " ".join(sys.argv[2:]))
    print(f"Creati {release} e {out} (versione {version})")
