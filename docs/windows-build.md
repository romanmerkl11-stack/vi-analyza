# Windows natívny balík — `Vi-Analyza.exe`

Jeden spustiteľný súbor (~30 MB), dvojklik → spustí lokálny server a otvorí appku
v prehliadači. Žiadny Python ani terminál pre koncového používateľa. **Overené na
`grafik-pc` (Windows, Python 3.14.6).**

## Čo balík obsahuje
- `tools/server.py` (frozen-aware: appku serví z priečinka vedľa `.exe`, ak tam je —
  aktualizovateľná cez Google Drive; inak z priloženého balíka `_MEIPASS`).
- `tools/pdf_legend.py` (čítanie legendy z PDF → `api/legend`).
- `tools/kataster.py` (parcela → verejné údaje ESKN/ZBGIS → `api/kataster`).
- `tools/konkurencia.py` (konkurencia z webu podľa lokality/URL → `api/konkurencia`).
- `analyza-budovy.html` (priložená cez `--add-data`, takže `.exe` je samostatný).
- `tools/ocr_win.py` — OCR skenov cez **RapidOCR** (offline, ONNX). OCR sa bundluje do
  `.exe`, takže sa **inštaluje spolu s appkou** — používateľ nič doinštalovať nemusí.
- PyMuPDF (`fitz`), RapidOCR + onnxruntime (modely) — bundluje PyInstaller.
- `tools/krivky_na_text.py` + `tools/znaky.json` — presný fallback pre text prevedený
  na krivky (najmä IC1). Launcher ich aktualizuje ako malé súbory vedľa `.exe`.

## Predpoklady (raz)
```
py -m pip install pymupdf pyinstaller rapidocr-onnxruntime
```
PyMuPDF 1.28.2 (abi3) aj PyInstaller 6.22.0 fungujú na Pythone 3.14.
**POZOR (overiť pri inštalácii):** `onnxruntime` (ťahá ho RapidOCR) nemusí mať wheels pre
úplne nový Python 3.14. Ak `pip install rapidocr-onnxruntime` zlyhá na onnxruntime, možnosti:
(a) postaviť balík pod Python 3.12 (nainštalovať vedľa), (b) `rapidocr-openvino`, alebo
(c) Windows natívne OCR (winrt). Bez OCR balík funguje ako predtým (vektorové PDF).

## Build (overený postup)
Buduje sa v `C:\vitab\build` (bez medzier/diakritiky v ceste — priamo v Google Drive
priečinku `G:\Môj disk\…` PyInstaller robí problémy).

1. Skopíruj do `C:\vitab\build\`: `server.py`, `pdf_legend.py`, `kataster.py`,
   `konkurencia.py`, `ocr_win.py`, `krivky_na_text.py`, `znaky.json`, `analyza-budovy.html`
   (napr. `scp … grafik@192.168.100.54:/C:/vitab/build/`).
2. Ak beží starý exe, zabi ho: `taskkill /IM Vi-Analyza.exe /F`.
3. Build (vrátane OCR):
```
py -m PyInstaller --onefile --name Vi-Analyza --paths C:\vitab\build --hidden-import pdf_legend --hidden-import ocr_win --hidden-import kataster --hidden-import konkurencia --hidden-import krivky_na_text --collect-all rapidocr_onnxruntime --collect-all onnxruntime --add-data C:\vitab\build\analyza-budovy.html;. --add-data C:\vitab\build\znaky.json;. --distpath C:\vitab\build\dist --workpath C:\vitab\build\work --specpath C:\vitab\build --noconfirm C:\vitab\build\server.py
```
**DÔLEŽITÉ:** `kataster.py` a `konkurencia.py` sa importujú dynamicky (`_try_import`), preto ich
PyInstaller sám nenájde — bez `--hidden-import kataster --hidden-import konkurencia` by ich exe
nemalo (ping by ukázal `kataster:false`). Over cez `api/ping`, že sú `true`.
**Pozn.: onefile s OCR (~115 MB) sa pri prvom štarte rozbaľuje ~40 s** — pri teste počkaj, kým
`api/ping` odpovie; skoršie „Unable to connect" je len ešte nenabehnutý server, nie chyba.
Výsledok: `C:\vitab\build\dist\Vi-Analyza.exe` (s OCR ~150–250 MB; ponesie ONNX modely).
Bez OCR (menší, len vektorové PDF): vynechaj `--hidden-import ocr_win` a obidva `--collect-all`.

## Nasadenie
- **Odporúčané**: `Vi-Analyza.exe` do **projektového priečinka** vedľa `analyza-budovy.html`
  (Google Drive) → dvojklik serví živú (aktualizovateľnú) appku.
- **Samostatne**: `.exe` sám v ľubovoľnom priečinku → serví appku z balíka (overené).

## Test (headless, cez SSH)
```
C:\vitab\build\dist\Vi-Analyza.exe            (spustí server na 127.0.0.1:8765)
curl http://127.0.0.1:8765/api/ping           -> {"ok":true,...,"legend":true,"platform":"win32"}
curl http://127.0.0.1:8765/                    -> HTTP 200, ~1,5 MB (appka)
curl -X POST --data-binary @test.pdf http://127.0.0.1:8765/api/legend  -> {"ok":true,"csv":...}
```

## Kozmetika — ikona a skratka
- **Ikona** `vi-analyza.ico` (v koreni projektu, multi-size 16–256, monogram „Vi" + náznak
  pôdorysu; generuje ju `scratchpad/mkicon.py` cez PIL). Do exe sa zapečie pri buildе pridaním
  `--icon C:\vitab\build\vi-analyza.ico` do príkazu vyššie (skopíruj `.ico` aj do `C:\vitab\build`).
- **Skratka na ploche** „Vi Analýza.lnk" (bez prebuildu) — cieľ `C:\vitab\standalone\Vi-Analyza.exe`,
  `IconLocation` = `C:\vitab\standalone\vi-analyza.ico`. Vytvorená cez PowerShell `WScript.Shell`
  (ps1 v UTF-8 s BOM kvôli diakritike; skript `scratchpad/mklnk.ps1`). `.ico` leží vedľa exe.

## Prvé otvorenie (Windows SmartScreen)
Nepodpísaný `.exe` → SmartScreen môže hlásiť „Windows chránil váš počítač".
Klik **Ďalšie informácie → Napriek tomu spustiť**. (Podpis/notarizácia = neriešime, Roman 2026-08-16.)

## Známe / ďalej
- Startup `--onefile` sa rozbaľuje do temp (~2–4 s) — akceptovateľné.
- OCR skenov na Windows = doplniť RapidOCR (endpoint `api/ocr` je pripravený).
- Pri zmene `analyza-budovy.html`: ak je vedľa exe, stačí Drive sync; ak treba
  aktualizovať aj bundled fallback, prebuduj.
