# E0 — Reading harness (spoľahlivosť čítania podkladov)

Meria, ako spoľahlivo appka prečíta legendu miestností z PDF — **CURRENT vs NEW** na tých
istých podkladoch. Offline, oracle-first (Python + `pdf_legend`/`krivky_na_text`, ako server).

## Spustenie
```bash
python3 tests/reading-harness.py <PDF|adresár> [...] [--save-baseline] [--json OUT]
```
Pre každý PDF zvolí cestu ako appka: **vektor → krivky → OCR** a z vyrobeného app-CSV (to isté,
čo vidí appka) spočíta `interiorSum`, `printedTotal` (CELKOVÁ), `diff`, počty.

## Tri vrstvy overenia
1. **Auto-metrika** — `diff = interiorSum − printedTotal`, kde je medzisúčet vytlačený. `diff=0`
   = číta správne bez ručnej práce.
2. **Baseline snapshot** — `--save-baseline` uloží dnešný výstup do `tests/baseline/reading.json`.
   Bežné spustenie hlási ZMENU voči baseline → regresná poistka (NEW nesmie zhoršiť dobré hárky).
3. **Ground truth** — `tests/ground-truth/<názov-bez-.pdf>.json` = ručne overené `{ "kód": plocha }`.
   Harness spočíta per-miestnosť presnosť (hit/miss/wrong/extra).

## Workflow ground-truth (IC/Šuty, kde niet oficiálnej legendy)
1. Harness vygeneruje kandidáta `tests/ground-truth/<hárok>.candidate.json` (kód→plocha, ako to
   dnes prečítal).
2. **Roman skontroluje kandidáta proti reálnemu výkresu**, opraví chybné/chýbajúce hodnoty.
3. Premenuj na `<hárok>.json` → odvtedy je to záväzná „pravda" pre daný hárok.

## Známe obmedzenia
- **OCR cesta na Macu = Apple Vision** (slabá a pomalá na celé hárky) → **OCR/skenové hárky (Šuty)
  merať na Windows** (RapidOCR tiled). Vektor a KRIVKY sú plne verné aj na Macu.
- Krivkové hárky často nemajú vytlačenú CELKOVÁ v app-CSV → auto-metrika `diff` chýba, treba
  ground-truth (bod vyššie).

## Cesty čítania (harness ich skúša v poradí)
`vektor` (textová legenda) → `krivky` (obrysy → to_app_csv_ocr) → `ocr` (sken) → `flatmix`
(apartmánové popisky v pôdoryse, bez legendy miestností — napr. IC2).

## Prvé zistenia (2026-08-21, IC) — 16/16 číta
- IC1: 8/11 **krivky**, 2 **vektor**, 1 slabý **ocr** (1pp). 4NP overený **GT 73/73**.
- IC1 **4NP diff −31,05 → −0,09 OPRAVENÉ** (Fix1 loggia do exteriéru + Fix2 spoločný blok 4B.0x).
- **IC2 = flatmix (popisky), NIE legenda** — 6/6 číta cez flatmix (20–76 jedn./hárok). Nebola to diera.
- Pozn.: appka `_run_legend` most krivky→legenda **nepoužíva** (krivky idú do flatmixu) — zvážiť
  zapojenie (IC1 legenda miestností by potom tiekla do plnej analýzy, nielen flatmix).
