"""
Aggiunge file locali a un'immagine filesystem ESP32 (LittleFS o SPIFFS) prima
del caricamento, con gli stessi programmi usati da PlatformIO (vedi tools/).

L'immagine scaricata viene estratta, i file aggiunti la sovrascrivono (stesso
percorso = file sostituito) e l'immagine viene ricostruita con la stessa
dimensione, cioè quella della partizione.
"""

import shutil
import subprocess
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    TOOLS_DIR = Path(sys._MEIPASS) / "tools"
else:
    TOOLS_DIR = Path(__file__).resolve().parent / "tools"

TOOLS = {"littlefs": "mklittlefs.exe", "spiffs": "mkspiffs.exe"}
PAGE_SIZE = 256
BLOCK_SIZE = 4096
# Limiti dei programmi di PlatformIO per Arduino ESP32 (provati con tools/).
LITTLEFS_NAME_MAX = 32  # ogni nome di file o cartella
SPIFFS_PATH_MAX = 31    # percorso completo, "/" iniziale compreso
# niente finestra del prompt quando l'eseguibile è senza console
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def fs_type(image_name):
    """"littlefs" o "spiffs" dal nome dell'immagine (littlefs.bin, spiffs.bin)."""
    name = image_name.lower()
    return next((fs for fs in TOOLS if fs in name), None)


def collect(sources):
    """Percorso nel filesystem -> file locale.

    Un file va nella radice; di una cartella si copia il contenuto, con le
    sottocartelle, come la cartella data/ dei progetti.
    """
    files = {}
    for source in map(Path, sources):
        if source.is_dir():
            for path in sorted(p for p in source.rglob("*") if p.is_file()):
                files[path.relative_to(source).as_posix()] = path
        elif source.is_file():
            files[source.name] = source
        else:
            raise RuntimeError(f"{source}: file o cartella non trovati")
    return files


def check_names(fs, files):
    for rel in files:
        if fs == "spiffs" and len("/" + rel) > SPIFFS_PATH_MAX:
            raise RuntimeError(f"/{rel}: percorso troppo lungo per SPIFFS "
                               f"(massimo {SPIFFS_PATH_MAX} caratteri, «/» compreso)")
        if fs == "littlefs":
            for part in rel.split("/"):
                if len(part) > LITTLEFS_NAME_MAX:
                    raise RuntimeError(f"{part}: nome troppo lungo per LittleFS "
                                       f"(massimo {LITTLEFS_NAME_MAX} caratteri)")


def run_tool(fs, *args, cwd=None):
    tool = TOOLS_DIR / TOOLS[fs]
    if not tool.exists():
        raise RuntimeError(f"manca {tool}")
    result = subprocess.run([str(tool), *args], capture_output=True, text=True, cwd=cwd,
                            errors="replace", creationflags=NO_WINDOW)
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        tail = "\n".join(output.splitlines()[-6:])
        raise RuntimeError(f"{TOOLS[fs]} non riuscito:\n{tail}")
    return output


def add_files(image, sources, work_dir):
    """Crea in work_dir una copia di image con i file di sources aggiunti.

    Ritorna (immagine nuova, [(percorso, aggiunto/sostituito)]). Solleva
    RuntimeError se un nome non è valido o i file non ci stanno.
    """
    image, work_dir = Path(image), Path(work_dir)
    fs = fs_type(image.name)
    if fs is None:
        raise RuntimeError(f"{image.name}: filesystem non riconosciuto (attesi LittleFS o SPIFFS)")
    files = collect(sources)
    if not files:
        raise RuntimeError("nessun file da aggiungere")
    check_names(fs, files)

    size = str(image.stat().st_size)
    params = ["-b", str(BLOCK_SIZE), "-p", str(PAGE_SIZE), "-s", size]
    # mklittlefs -u accetta solo una cartella relativa: si lavora dentro work_dir
    content = work_dir / "content"
    if content.exists():
        shutil.rmtree(content)
    run_tool(fs, "-u", content.name, *params, str(image.resolve()), cwd=work_dir)

    changes = []
    for rel, source in files.items():
        target = content / rel
        changes.append((rel, "sostituito" if target.exists() else "aggiunto"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    output = work_dir / image.name
    try:
        run_tool(fs, "-c", content.name, *params, output.name, cwd=work_dir)
    except RuntimeError as e:
        total = sum(p.stat().st_size for p in content.rglob("*") if p.is_file())
        raise RuntimeError(f"{e}\n\nI file occupano {total // 1024} KB su "
                           f"{int(size) // 1024} KB del filesystem: forse non ci stanno.") from None
    return output, changes
