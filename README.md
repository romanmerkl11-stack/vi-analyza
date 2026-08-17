# Vi-Analyza

Nástroj Vi Group na **analýzu plôch z výkresov** (CSV / vektorové PDF / skeny s OCR) a
**ekonomiku projektu** (príjmy, náklady, zisk, konkurencia, kataster, export).

Beží celý lokálne (bez inštalácie a terminálu) — `Vi-Analyza.exe` spustí lokálny server a
otvorí appku v prehliadači.

## Auto-update

Distribuuje sa **malý launcher** (`Vi-Analyza-Launcher.exe`), ktorý sa pri každom spustení
aktualizuje z **GitHub Releases** tohto repozitára (`releases/latest`). Ťažký runtime
(Python + PDF + OCR) sa stiahne raz; HTML a moduly sa aktualizujú pri každej zmene.

Postup: [`docs/auto-update.md`](docs/auto-update.md) · Build runtime: [`docs/windows-build.md`](docs/windows-build.md)

## Obsah repozitára

- `analyza-budovy.html` — appka (frontend, celá logika analýzy a ekonomiky).
- `tools/server.py` — lokálny server (frozen-aware; tool moduly číta z disku vedľa .exe).
- `tools/pdf_legend.py` — čítanie legendy z PDF → CSV pre appku.
- `tools/kataster.py` — parcela → verejné údaje ESKN/ZBGIS.
- `tools/konkurencia.py` — developerské novostavby z webu (flatscraper, bratislavaliving).
- `tools/ocr_win.py` — OCR skenov (RapidOCR, Windows).
- `tools/launcher.py` — auto-update bootstrapper.
- `tools/build_release.py` — generátor `manifest.json` + `gh release` príkaz.

Podklady projektov (CSV/PDF/xls) nie sú v repozitári — sú súkromné (Google Drive).
