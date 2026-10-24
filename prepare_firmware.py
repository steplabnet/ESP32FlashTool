"""
Raccoglie i binari compilati da PlatformIO nei progetti Solaria e li copia in
firmware/<prodotto>/ insieme a un manifest.json letto da installer.py.

Le sottocartelle di firmware/ vanno copiate così come sono sotto l'URL base del
server: installer.py legge <url>/ModuloCentrale/manifest.json e
<url>/moduloPompa/manifest.json.

Uso:
    python prepare_firmware.py                 # tutti i prodotti, binari già compilati
    python prepare_firmware.py ModuloCentrale  # solo un prodotto
    python prepare_firmware.py --build         # prima esegue "pio run" e "pio run -t buildfs"

Attenzione: --build sulla centrale incrementa il contatore di versione
(scripts/build_version.py) come una normale compilazione.
"""

import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOLARIA = ROOT.parent
OUT_DIR = ROOT / "firmware"

# La chiave è anche il nome della sottocartella sul server; "chip" è il nome
# esptool (esp32, esp32s3, esp32c3, ...). Per altre schede aggiungere una voce
# con la propria cartella e associarla al prodotto con manifest_creator.py.
PRODUCTS = {
    "ModuloCentrale": {
        "name": "Centrale Light",
        "project": SOLARIA / "Solaria_centrale_light_ms",
        "env": "upesy_wroom",
        "chip": "esp32",
    },
    "moduloPompa": {
        "name": "Modulo Pompa",
        "project": SOLARIA / "ModuloPompe2022",
        "env": "esp32dev",
        "chip": "esp32",
    },
}

PIO = Path.home() / ".platformio" / "penv" / "Scripts" / "pio.exe"
VERSION_RE = re.compile(r'#define\s+FW_VERSION\s+"([^"]+)"')
# Modulo Pompa: String FW_VERSION = "MP.26.10.23.bx"; in src/main.cpp
VERSION_VAR_RE = re.compile(r'String\s+FW_VERSION\s*=\s*"([^"]+)"')

# Sottotipi di partizione dati usati come filesystem.
FS_SUBTYPES = {0x82: "spiffs", 0x83: "littlefs"}


def read_fs_partition(partitions_bin):
    """Ritorna l'offset della partizione filesystem dalla tabella partizioni."""
    data = partitions_bin.read_bytes()
    for i in range(0, len(data), 32):
        entry = data[i:i + 32]
        if entry[:2] != b"\xaa\x50":
            break
        ptype, subtype = entry[2], entry[3]
        offset, _size = struct.unpack("<II", entry[4:12])
        if ptype == 0x01 and subtype in FS_SUBTYPES:
            return offset
    return None


def read_version(project, firmware_bin):
    header = project / "include" / "version.h"
    if header.exists():
        m = VERSION_RE.search(header.read_text(encoding="utf-8", errors="ignore"))
        if m:
            return m.group(1).strip()
    main_cpp = project / "src" / "main.cpp"
    if main_cpp.exists():
        m = VERSION_VAR_RE.search(main_cpp.read_text(encoding="utf-8", errors="ignore"))
        if m:
            return m.group(1).strip()
    built = datetime.fromtimestamp(firmware_bin.stat().st_mtime)
    return built.strftime("build %Y-%m-%d %H:%M")


def newest_mtime(folder):
    files = [p for p in folder.rglob("*") if p.is_file()]
    return max((p.stat().st_mtime for p in files), default=0)


def run_pio(project, env, *extra):
    cmd = [str(PIO), "run", "-e", env, *extra]
    print("  >", " ".join(cmd))
    if subprocess.run(cmd, cwd=project).returncode != 0:
        raise RuntimeError(f"compilazione fallita: {' '.join(cmd)}")


def prepare(key, product, build):
    project, env = product["project"], product["env"]
    build_dir = project / ".pio" / "build" / env
    print(f"[{key}] {project}")

    if build:
        run_pio(project, env)
        run_pio(project, env, "-t", "buildfs")

    firmware_bin = build_dir / "firmware.bin"
    idedata_file = build_dir / "idedata.json"
    for f in (firmware_bin, idedata_file):
        if not f.exists():
            raise RuntimeError(f"manca {f} — compila il progetto (o usa --build)")

    idedata = json.loads(idedata_file.read_text(encoding="utf-8"))
    extra = idedata["extra"]

    # bootloader, partitions, boot_app0 + applicazione, come fa "pio run -t upload"
    images = []
    for img in extra["flash_images"]:
        path = Path(img["path"])
        images.append({"offset": img["offset"], "source": path, "role": path.stem})
    images.append({"offset": extra["application_offset"], "source": firmware_bin, "role": "app"})

    fs_bin = next((build_dir / n for n in ("littlefs.bin", "spiffs.bin")
                   if (build_dir / n).exists()), None)
    if fs_bin:
        fs_offset = read_fs_partition(build_dir / "partitions.bin")
        if fs_offset is None:
            raise RuntimeError("nessuna partizione filesystem in partitions.bin")
        images.append({"offset": hex(fs_offset), "source": fs_bin, "role": "filesystem"})
        data_dir = project / "data"
        if data_dir.is_dir() and newest_mtime(data_dir) > fs_bin.stat().st_mtime:
            print(f"  ATTENZIONE: {fs_bin.name} è più vecchio dei file in data/ "
                  f"(esegui 'pio run -t buildfs' o usa --build)")
    else:
        print("  ATTENZIONE: nessuna immagine filesystem — l'installazione completa "
              "non scriverà data/")

    if newest_mtime(project / "src") > firmware_bin.stat().st_mtime:
        print("  ATTENZIONE: firmware.bin è più vecchio dei sorgenti in src/")

    target = OUT_DIR / key
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    manifest_images = []
    for img in images:
        src = img["source"]
        if not src.exists():
            raise RuntimeError(f"manca {src}")
        shutil.copy2(src, target / src.name)
        content = src.read_bytes()
        manifest_images.append({"offset": img["offset"], "file": src.name, "role": img["role"],
                                "size": len(content),
                                "sha256": hashlib.sha256(content).hexdigest()})
        print(f"  {img['offset']:>9}  {src.name}")

    manifest = {
        "name": product["name"],
        "chip": product.get("chip", "esp32"),
        "board": env,
        "version": read_version(project, firmware_bin),
        "prepared": datetime.now().isoformat(timespec="seconds"),
        "images": manifest_images,
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"  versione {manifest['version']} -> {target}")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("products", nargs="*",
                        help=f"prodotti da preparare: {', '.join(PRODUCTS)} (default: tutti)")
    parser.add_argument("--build", action="store_true",
                        help="compila firmware e filesystem con PlatformIO prima di copiare")
    args = parser.parse_args()
    unknown = set(args.products) - set(PRODUCTS)
    if unknown:
        parser.error(f"prodotto sconosciuto: {', '.join(sorted(unknown))}")

    failed = False
    for key in args.products or PRODUCTS:
        try:
            prepare(key, PRODUCTS[key], args.build)
        except RuntimeError as e:
            print(f"  ERRORE: {e}")
            failed = True
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
