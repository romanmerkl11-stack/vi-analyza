# -*- coding: utf-8 -*-
"""
Priprava GitHub Release pre auto-update launcher.

Vygeneruje `manifest.json` (verzie + sha256 vsetkych assetov) a vypise prikaz
`gh release create`, ktory ho aj so subormi publikuje. Launcher potom cita z
`releases/latest/download/…`.

DVE VRSTVY:
  - runtime = tazky `Vi-Analyza.exe` (Python + PDF + OCR + server.py). Meni sa ZRIEDKA
    → ma vlastnu verziu (--runtime-version rN). Stupni ju len ked prebuildujes exe
    (nova zavislost / OCR modely / zmena server.py).
  - male subory = HTML + tool .py moduly. Menia sa CASTO; launcher ich stiahne pri
    kazdej zmene hashu (nemusis stupat runtime verziu).

Pouzitie (v koreni projektu):
  python tools/build_release.py --version 2026.08.17 \
      --runtime /cesta/Vi-Analyza.exe --runtime-version r3
Vysledok: manifest.json + hotovy `gh release create …` prikaz.
"""

import argparse
import hashlib
import json
import os
import sys

# male subory, ktore launcher aktualizuje pri kazdej zmene (bez rebuildu runtime).
# server.py TU NIE JE — je sucastou runtime exe (disk-override plati len pre tool moduly).
SMALL_FILES = [
    "analyza-budovy.html",
    "tools/pdf_legend.py",
    "tools/kataster.py",
    "tools/konkurencia.py",
    "tools/ocr_win.py",
    "tools/krivky_na_text.py",
    "tools/znaky.json",
]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="verzia release, napr. 2026.08.17")
    ap.add_argument("--runtime", required=True, help="cesta k Vi-Analyza.exe (runtime)")
    ap.add_argument("--runtime-version", required=True, help="verzia runtime, napr. r3")
    ap.add_argument("--notes", default="", help="zmeny do okna Co je nove (riadky oddelene | alebo newline)")
    ap.add_argument("--notes-file", help="súbor so zmenami, jeden riadok = jedna zmena")
    ap.add_argument("--out", default=os.path.join(ROOT, "manifest.json"))
    a = ap.parse_args(argv)

    raw = ""
    if a.notes_file and os.path.isfile(a.notes_file):
        with open(a.notes_file, encoding="utf-8") as f:
            raw = f.read()
    raw = (raw + "\n" + a.notes).replace("|", "\n")
    changes = [ln.strip().lstrip("-•* ").strip() for ln in raw.splitlines() if ln.strip()]

    if not os.path.isfile(a.runtime):
        print("CHYBA: runtime exe neexistuje: %s" % a.runtime)
        return 1

    assets = [a.runtime]                              # asset zoznam pre gh
    files = []
    for rel in SMALL_FILES:
        p = os.path.join(ROOT, rel)
        if not os.path.isfile(p):
            print("VAROVANIE: chyba %s (preskakujem)" % rel)
            continue
        files.append({"name": os.path.basename(rel), "sha256": _sha256(p)})
        assets.append(p)

    manifest = {
        "version": a.version,
        "changes": changes,                          # → okno „Čo je nové" v launcheri
        "runtime": {
            "file": os.path.basename(a.runtime),
            "version": a.runtime_version,
            "sha256": _sha256(a.runtime),
        },
        "files": files,
    }
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    assets.append(a.out)

    print("Manifest: %s (runtime %s, %d malych suborov)"
          % (a.out, a.runtime_version, len(files)))
    print("\nPublikuj release prikazom (potrebny `gh auth login`):\n")
    quoted = " ".join('"%s"' % p for p in assets)
    print('gh release create v%s %s --title "Vi-Analyza %s" --notes "auto-update"'
          % (a.version, quoted, a.version))
    print("\n(Ak release uz existuje, nahrad assety: `gh release upload v%s <subor> --clobber`)"
          % a.version)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
