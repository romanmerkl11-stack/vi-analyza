# Auto-update cez GitHub Releases

Cieľ: PM dostane **malý launcher**, ktorý sa pri **každom spustení** sám aktualizuje z GitHub
Releases. Prenášaný súbor je malý; ťažký runtime sa stiahne raz cez internet.

## Ako to funguje

```
Vi-Analyza-Launcher.exe (malý, ~pár MB)   ──každý štart──▶  GitHub release „latest"
   1. stiahne manifest.json (verzie + sha256)                manifest.json
   2. porovná s lokálne uloženými súbormi                    Vi-Analyza.exe (runtime, ~120 MB)
   3. stiahne LEN zmenené                                    analyza-budovy.html
   4. spustí Vi-Analyza.exe z %LOCALAPPDATA%\ViAnalyza        pdf_legend.py, kataster.py,
                                                              konkurencia.py, ocr_win.py
```

- **runtime `Vi-Analyza.exe`** (Python + PDF + OCR + `server.py`) = ťažký, mení sa **zriedka**
  (vlastná verzia `rN`). Stiahne sa raz; znovu len keď `rN` stúpne.
- **malé súbory** (HTML + tool `.py`) = menia sa **často**, launcher ich stiahne pri každej zmene
  hashu — **bez rebuildu**. (Exe ich číta z disku vedľa seba cez `server.py _try_import`.)
- `server.py` je **súčasť runtime** (nie disk-updatovateľný) → jeho zmena = nový runtime `rN`.

Stabilná URL `…/releases/latest/download/<súbor>` vždy ukazuje na najnovší release, takže
**launcher sa nikdy nemení** — aktualizácia = publikovať nový release.

## Jednorazové nastavenie

1. **GitHub repo** (napr. `vigroup/vi-analyza`). Môže byť aj private — pri private treba
   do launchera doplniť token (napíš, doriešime); pri public stačí verejné URL.
2. V `tools/launcher.py` nastav `OWNER` a `REPO`.
3. Postav **launcher exe** (malý, bez OCR/PDF — len stdlib):
   ```
   py -m PyInstaller --onefile --name Vi-Analyza-Launcher tools/launcher.py
   ```
   → `Vi-Analyza-Launcher.exe` (~8–10 MB) = TOTO posielaš PM.
4. `gh auth login` (raz, na stroji kde publikuješ).

## Publikovanie aktualizácie

1. (Ak sa menil runtime — nová závislosť / OCR / `server.py`) prebuild `Vi-Analyza.exe`
   podľa `docs/windows-build.md` a stúpni `--runtime-version`.
2. Vygeneruj manifest + príkaz (`--notes` = zmeny do okna „Čo je nové“, riadky oddelené `|`):
   ```
   python tools/build_release.py --version 2026.08.17 \
       --runtime C:\vitab\build\dist\Vi-Analyza.exe --runtime-version r3 \
       --notes "Krasnany: oprava plôch|Kataster funguje|Konkurencia z flatscraper"
   ```
   (Alebo `--notes-file changelog.txt`, jeden riadok = jedna zmena.)
3. Spusti vypísaný `gh release create v… …` (alebo `gh release upload v… <súbor> --clobber`).

**Okno „Čo je nové":** keď launcher zistí NOVÚ `version` v manifeste, po spustení appky ukáže
okno s verziou a zoznamom zmien (`changes`). Ak sa verzia nezmenila, okno sa neukáže. (tkinter;
fallback natívny Windows MessageBox.)

Hotovo — pri ďalšom spustení si to launcher u PM stiahne sám. Pri zmene len HTML/`.py`
netreba krok 1 (runtime ostáva), stačí re-generovať manifest a nahrať zmenené súbory.

## Offline

Ak launcher nevie stiahnuť manifest (bez internetu), spustí **poslednú uloženú verziu**.
Úplne prvé spustenie internet potrebuje (stiahne runtime).

## Bezpečnosť

Kto vie publikovať release do repa, mení kód bežiaci u PM → prístup k repu drž pod kontrolou.
