# Automatické vypĺňanie rozpisky

## Raz na začiatku
1. V AutoCADe zadaj `APPLOAD` a načítaj `rozpiska.lsp`. Aby sa načítal vždy, pridaj ho do **Startup Suite**.
2. Otvor jeden výkres s rozpiskou a spusti `ROZPISKA-TAGY`. Príkaz vypíše názvy atribútov (TAG) a uloží ich do `rozpiska-tagy.txt` vedľa DWG. Riadky označené `<- vyplni ROZPISKA` sa budú vypĺňať automaticky.
3. Ak niektorý TAG nie je označený, dopíš ho do zoznamu `*rozp-map*` na začiatku `rozpiska.lsp`, alebo pošli `rozpiska-tagy.txt` a mapovanie upravím.

## Pri každej zmene v registri
1. V registri klikni na **Export pre rozpisku (AutoCAD)**. Stiahne sa `rozpiska.csv`.
2. V AutoCADe otvor výkres a spusti `ROZPISKA`. Pri prvom spustení vyber `rozpiska.csv`, potom si cestu pamätá.
3. Výsledok skontroluj. Celú zmenu vrátiš jedným `U`.

## Čo sa vypĺňa
| Stĺpec z registra | Príklad | Hľadané TAGy |
|---|---|---|
| CISLO_VYKRESU | S01_ASR_001_N01 | CISLO_VYKRESU, Č.VÝKR, CISLO |
| NAZOV_VYKRESU | Pôdorys 1. NP | NAZOV_VYKRESU, NÁZOV_VÝKRESU, NAZOV |
| KOD | 25AB123_PSP_01_1122_S01_ASR_001_N01 | KOD, PORTAL_CODE |
| STUPEN | PSP | STUPEN, STUPEŇ |
| CAST | ASR | CAST, ČASŤ, PROFESIA |
| REVIZIA | 00 | REVIZIA, REV |
| OBJEKT | S01 | OBJEKT, SO |

Ostatné stĺpce (STUPEN_NAZOV, LIST, STAVBA) sa zapíšu iba do TAGu s rovnakým názvom.
Kým nie je pridelené ID stavby, kód obsahuje `XXXXXXX`. Po doplnení ID exportuj znova a spusti `ROZPISKA`.

## Párovanie s výkresmi
- Výkres a layout sa hľadajú podľa poľa **Skutočný DWG / layout** v registri, napríklad `S01_REZ.dwg / 005_REZ`.
- Ak je pole prázdne, použije sa odporúčaný interný názov DWG. Keď má DWG iba jeden layout, vyplní sa ten.

## Dôležité
- Do atribútov v **xref** rozpiske sa z výkresu zapisovať nedá. Údaje spoločné pre projekt (stavba, investor, projektanti) nechaj v xref rozpiske. Údaje, ktoré sa líšia podľa listu, daj do lokálneho bloku s atribútmi v layoute.
- Diakritika sa prenáša ako `\U+XXXX`, čo AutoCAD zobrazí správne bez ohľadu na kódovanie Windows.
- Pred prvým ostrým použitím vyskúšaj postup na kópii výkresu.
