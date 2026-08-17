# -*- coding: utf-8 -*-
"""
Vi-Analyza LAUNCHER — maly bootstrapper, ktory sa aktualizuje z GitHub Releases.

Princip:
  - Distribuuje sa MALY subor (tento launcher ako .exe, ~pár MB).
  - Pri KAZDOM spusteni stiahne z najnovsieho GitHub release maly `manifest.json`,
    porovna hashe s lokalne ulozenymi subormi a stiahne LEN to, co sa zmenilo.
  - Tazky runtime (`Vi-Analyza.exe` s Pythonom/PDF/OCR) sa stiahne RAZ pri prvom
    spusteni; znovu az ked mu v manifeste stupne verzia. HTML a .py moduly su male
    a aktualizuju sa prakticky pri kazdom starte.
  - Potom spusti stiahnuty `Vi-Analyza.exe`. Ten uz vie citat HTML aj tool .py moduly
    z disku vedla seba (server.py `_try_import`), takze staci ich mat v install priecinku.

Konfiguracia = konstanty nizsie (OWNER/REPO). Launcher sa nemeni; aktualizacie = novy release.

Offline: ak sa manifest neda stiahnut, spusti sa posledna ulozena verzia (ak existuje).
"""

import hashlib
import json
import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

# --- KONFIGURACIA (uprav pred buildom) --------------------------------------------
OWNER = "romanmerkl11-stack"
REPO = "vi-analyza"
RUNTIME_EXE = "Vi-Analyza.exe"   # nazov runtime assetu (tazky exe)
APP_NAME = "ViAnalyza"

# Stabilna URL: vzdy najnovsi release. Publikacia noveho release = automaticka aktualizacia.
_BASE = "https://github.com/%s/%s/releases/latest/download" % (OWNER, REPO)

# GitHub ma platny certifikat; neoverujuci kontext je len poistka proti chybajucim CA na Windows.
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

_UA = {"User-Agent": "ViAnalyzaLauncher/1.0"}


def _install_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


def _log(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass


def _fetch(url, timeout=30):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
        return r.read()


def _sha256(path):
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download_to(url, dest, expected_sha=None, timeout=180):
    """Stiahne do docasneho suboru, overi hash, az potom atomicky presunie na miesto."""
    data = _fetch(url, timeout=timeout)
    if expected_sha:
        got = hashlib.sha256(data).hexdigest()
        if got.lower() != expected_sha.lower():
            raise ValueError("hash nesedi pre %s (ocakavany %s, stiahnuty %s)"
                             % (os.path.basename(dest), expected_sha[:12], got[:12]))
    tmp = dest + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dest)


def _load_local_manifest(install):
    p = os.path.join(install, "manifest.local.json")
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_local_manifest(install, manifest):
    p = os.path.join(install, "manifest.local.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)


def _show_update_popup(version, changes):
    """Vyskakovacie okno „Čo je nové" (verzia + zoznam zmien). tkinter, fallback Windows MessageBox."""
    title = "Vi-Analyza — aktualizované"
    lines = [("•  " + c) for c in (changes or [])] or ["(bez podrobností)"]
    try:
        import tkinter as tk
        from tkinter import scrolledtext
        root = tk.Tk()
        root.title(title)
        root.geometry("470x360")
        tk.Label(root, text="Vi-Analyza  %s" % version,
                 font=("Segoe UI", 14, "bold")).pack(pady=(16, 2))
        tk.Label(root, text="Čo je nové:", font=("Segoe UI", 10)).pack()
        box = scrolledtext.ScrolledText(root, wrap="word", font=("Segoe UI", 10), height=13)
        box.pack(fill="both", expand=True, padx=16, pady=10)
        box.insert("1.0", "\n".join(lines))
        box.configure(state="disabled")
        tk.Button(root, text="Zavrieť", width=14, command=root.destroy).pack(pady=(0, 14))
        root.attributes("-topmost", True)
        root.mainloop()
    except Exception:
        try:
            import ctypes
            body = "Verzia %s\n\nČo je nové:\n%s" % (version, "\n".join(lines))
            ctypes.windll.user32.MessageBoxW(0, body, title, 0x40)   # MB_ICONINFORMATION
        except Exception:
            _log("Vi-Analyza %s — čo je nové:\n%s" % (version, "\n".join(lines)))


def update(install):
    """Skontroluje manifest a stiahne zmenene subory.
    Vrati (ready, popup) — popup = (verzia, [zmeny]) ak je NOVA verzia, inak None."""
    exe_path = os.path.join(install, RUNTIME_EXE)
    try:
        manifest = json.loads(_fetch(_BASE + "/manifest.json", timeout=20).decode("utf-8"))
    except (urllib.error.URLError, ValueError, OSError) as e:
        _log("  (aktualizacia preskocena — offline? %s)" % e)
        return os.path.isfile(exe_path), None    # spusti lokalnu verziu, ak existuje

    local = _load_local_manifest(install)
    new_version = manifest.get("version") and manifest.get("version") != local.get("version")

    # 1) runtime (tazky exe) — len ak stupla verzia alebo chyba
    rt = manifest.get("runtime") or {}
    rt_ver = rt.get("version")
    if (not os.path.isfile(exe_path)) or (local.get("runtime", {}).get("version") != rt_ver):
        _log("  stahujem runtime %s (%s)…" % (RUNTIME_EXE, rt_ver))
        _download_to(_BASE + "/" + (rt.get("file") or RUNTIME_EXE), exe_path,
                     rt.get("sha256"), timeout=600)

    # 2) male subory (HTML + tool .py) — stiahni len zmenene (podla hashu)
    for item in manifest.get("files", []):
        name = item.get("name")
        if not name:
            continue
        dest = os.path.join(install, name)
        if _sha256(dest) != (item.get("sha256") or "").lower():
            _log("  aktualizujem %s…" % name)
            _download_to(_BASE + "/" + name, dest, item.get("sha256"), timeout=120)

    _save_local_manifest(install, manifest)
    popup = (manifest.get("version"), manifest.get("changes") or []) if new_version else None
    return os.path.isfile(exe_path), popup


def main():
    install = _install_dir()
    _log("Vi-Analyza — kontrolujem aktualizacie…")
    ready, popup = update(install)
    exe_path = os.path.join(install, RUNTIME_EXE)
    if not ready or not os.path.isfile(exe_path):
        _log("CHYBA: appka nie je stiahnuta a nie je pripojenie na internet.\n"
             "Pripoj sa na internet a spusti launcher znova (prve spustenie potrebuje internet).")
        try:
            input("Stlac Enter…")
        except Exception:
            pass
        return 1
    _log("Spustam appku…")
    # exe si sam otvori prehliadac a servuje z install priecinka (HTML + tool .py z disku)
    try:
        subprocess.Popen([exe_path], cwd=install)
    except Exception as e:
        _log("CHYBA pri spusteni: %s" % e)
        return 1
    # po spusteni appky ukaz „Co je nove" (len ak stupla verzia)
    if popup:
        _show_update_popup(popup[0], popup[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
