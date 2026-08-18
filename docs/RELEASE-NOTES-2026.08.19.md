# Vi-Analyza 2026.08.19 (runtime r4)

## Opravené

- balkóny, lodžie, terasy a ostatné plochy sa mapujú do stavebných nákladov,
- spoločná plocha sa pri chýbajúcom medzisúčte nezmení na záporné číslo,
- kancelárie, obchody a miestnosti v jednotkách sa správne rozlišujú od spoločných technických plôch,
- jednotná vážená priemerná cena konkurencie a živé prepočty kariet,
- čisté bunky kompletných nákladov, perzistentné normy a prázdna šablóna nového projektu,
- skrátené parcely (`17353/1,2,7`) sa rozvinú na úplné čísla,
- OCR už nepredvyplní falošné miesto `POZEM`.

## Pridané

- runtime r4 obsahuje OCR skenov aj presný čítač textu prevedeného na krivky,
- automatické testy ekonomiky, vstupov a metadát,
- mapa znakov sa aktualizuje cez launcher spolu s ostatnými malými modulmi.

## Overenie

- Windows ping: všetky moduly `true`,
- IC1 5NP: 3 063 znakov, 367 buniek, 0 nezaradených,
- Nové Šuty A 1NP: legenda načítaná cez OCR do CSV,
- regresné testy plôch, ekonomiky, parciel a PDF metadát: PASS.

## Aktualizácia a návrat

Existujúci launcher pri ďalšom online spustení stiahne runtime r4 a malé súbory.
Návrat je možný opätovným publikovaním predchádzajúceho manifestu/runtime r3.
