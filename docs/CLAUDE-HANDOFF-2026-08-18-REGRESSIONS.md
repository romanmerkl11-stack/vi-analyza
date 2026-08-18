# Claude handoff — regresie Analýzy budovy

## Začni tu

Pracuj v tomto Git clone, nie priamo v nadradenom Google Drive exporte.

- Repo: `romanmerkl11-stack/vi-analyza`
- Lokálny clone: `Vi group/vi-analyza-repo`
- Aktívna vetva: `fix/building-analysis-regressions`
- Remote `main`: `d84e449`
- Aktuálny HEAD vetvy: `6c3615d`
- Vetva zatiaľ nebola pushnutá a release nebol zmenený.

## Prečo vznikla vetva

Roman nahlásil:

1. balkóny a lodžie sa nenačítajú do stavebných nákladov,
2. spoločné priestory majú zápornú plochu,
3. Typy miestností obsahujú nezmyselné texty z výkresu,
4. treba upratať bunky Kompletných nákladov,
5. priemerná cena konkurencie nie je podľa očakávania,
6. Windows hlási nedostupný modul `krivky_na_text`.

## Dôležité zistenie o Gite a release

Tagy `v1.0.0`, `v1.0.1`, `origin/main` aj lokálny `main` ukazovali na rovnaký commit
`d84e449`. Produkčná pracovná kópia v nadradenom Google Drive priečinku však mala odlišný
`analyza-budovy.html`, `tools/pdf_legend.py` a `tools/ocr_win.py`.

Commit `8f4cb26` preto zachytáva túto aktuálnu pracovnú verziu ako východiskový snapshot.
Nezahadzuj ho a nevracaj aplikáciu iba na obsah `d84e449`.

## Dokončená oprava

Commit `6c3615d` opravuje zápornú plochu spoločných priestorov pri CSV bez riadku
`PODLAHOVÁ PLOCHA CELKOVÁ`.

Pôvodný vzorec bol:

`floorTotal - predajna - garaze`

Topoľčianska nemá použiteľný celkový medzisúčet, preto `floorTotal = 0` a výsledok bol
`-18,50 m²`. Jadro teraz najprv vypočíta priame bilancie klasifikovaných plôch. Ak
`floorTotal <= 0`, spoločné/technické priestory preberie z priameho súčtu
`model.bilancie.byOwn['Spoločné'].total`.

## Regresný test a výsledok

Test: `tests/core-audit.js`

Spustenie:

```bash
/Users/roman/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node tests/core-audit.js
```

Overený výsledok na `../data test topolcianska/*.csv`:

- 10 CSV,
- 10 podlaží,
- 239 miestností,
- 4 rozpoznané jednotky,
- `floorTotal = 0`,
- predajná plocha `18,50 m²`,
- spoločná plocha pred opravou `-18,50 m²`,
- spoločná plocha po oprave `1 694,47 m²`,
- priamy súčet úžitkovej plochy `1 712,97 m²`,
- exteriér bytov/apartmánov `37,05 m²`,
- zachytené hlučné typy miestností v tejto sade: 0.

Test po oprave prešiel. Python syntax pre `pdf_legend.py`, `ocr_win.py`,
`konkurencia.py` a `server.py` tiež prešla.

## Zatiaľ neopravované problémy

### Balkóny/lodžie v stavebných nákladoch

`ekAreaSources()` už vytvára zdroje `balkony` a `terasy`. Vzor Panorama má príslušné
stavebné riadky, ale `ekBlankProject()` vytvára iba riadok Byty (`resiInterior`). Nový
projekt preto nemá cieľové riadky, do ktorých by `ekApplySources()` plochy zapísal.

Odporúčaný ďalší bounded task: doplniť bezpečné defaultné stavebné riadky nového projektu
pre interiér, balkóny/lodžie, terasy, spoločné priestory, obchody, sklady a garáže;
pridať test, že každý podporovaný zdroj má cieľové mapovanie. Nemeň sadzby bez Romanovho
potvrdenia — môžu zostať 0.

### Typy miestností

Screenshot `../typy miestnosti.jpg` ukazuje text pečiatky a pomocných tabuliek medzi
typmi miestností. Topoľčianska tento konkrétny šum nereprodukuje. Treba nájsť konkrétny
PDF/CSV fixture, ktorý screenshot vytvoril, a až potom rozšíriť filter parsera. Nepridávať
široký regex bez regresie na dobrých výkresoch.

### Priemer konkurencie

Celkový priemer používa vážený výpočet `Σ cena bez DPH / Σ výmera`. Priemer podľa
dispozície používa jednoduchý aritmetický priemer `€/m²`. Najprv potvrdiť s Romanom,
ktorý výsledok považuje za správny a či má byť s DPH alebo bez DPH; potom zjednotiť KPI,
graf, tabuľku a XLSX.

### Krivky na text vo Windows

Screenshot `../nedostupne krivky na text.jpg` potvrdzuje runtime hlášku:
`No module named 'krivky_na_text'`. Súbor `tools/krivky_na_text.py` je v nadradenom
pracovnom priečinku, ale nie je v Git repo ani zozname malých release súborov. Treba
rozhodnúť, či ho pridať ako disk-updatovateľný modul, alebo spraviť nový runtime s
hidden importom a závislosťami. Overiť následne `/api/ping` s `krivky: true` na Windows.

### Kompletné náklady

Výpočty zatiaľ nemenili. UI úpravu robiť oddelene po dohľadaní presného screenshotu;
zachovať všetky `data-ek`, ID, eventy a exportné vzorce.

## Čo nesmieš meniť naraz

- Nemiešaj parser, ekonomické výpočty, vizuálny redizajn a release do jedného commitu.
- Nepracuj priamo na `main`.
- Nepublikuj release bez regresných testov a Romanovho potvrdenia.
- Nezahoď snapshot `8f4cb26`; obsahuje zmeny, ktoré v pôvodnom remote commite chýbali.

## Presný prompt na pokračovanie

> Pokračuj vo vetve `fix/building-analysis-regressions` podľa
> `docs/CLAUDE-HANDOFF-2026-08-18-REGRESSIONS.md`. Najprv urob bounded task pre mapovanie
> balkónov/lodžií a ostatných podporovaných plôch do stavebných nákladov nového projektu.
> Pridaj regresný test, zachovaj sadzby ako editovateľné a nič nepublikuj do releasu.
