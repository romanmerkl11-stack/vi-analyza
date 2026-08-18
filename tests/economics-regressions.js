const fs = require('fs');
const assert = require('assert');

const html = fs.readFileSync('analyza-budovy.html', 'utf8');

assert(!/Odhad tržieb \(GDV\)/.test(html), 'GDV sa nesmie vrátiť do Normiem');
assert(/if\(act==='new'\)\{ var np=ekBlankProject\(\)/.test(html), 'Nový projekt musí použiť prázdnu šablónu');
[
  "src:'resiInterior'", "src:'obchodInterior'", "src:'balkony'", "src:'terasy'",
  "src:'spolocne'", "src:'garazInterior'", "src:'skladInterior'"
].forEach(src => assert(html.includes(src), `Chýba mapovanie ${src}`));
assert(/function nad\(x\)\{ return x>0\?Math\.ceil\(os\/x\):0; \}/.test(html), 'Nádoby sa musia zaokrúhľovať nahor');
assert(html.includes("localStorage.setItem(NORM_KEY,JSON.stringify(normValues))"), 'Normy sa musia ukladať');
assert(html.includes("el.closest('.ek-competitor')"), 'Prepojené polia konkurencie musia hľadať kartu');
assert(html.includes("ek_o_stavbaOstatneSdph2"), 'Kompletné náklady musia ukázať Stavba + ostatné s DPH');
assert(html.includes('function escAttr(s)'), 'Hodnoty HTML atribútov musia byť escapované');
assert(html.includes('function ekCompPrice(c)'), 'Konkurencia musí mať jeden zdroj jednotkovej ceny');
assert(!html.includes('Mapovanie plôch'), 'Interné mapovanie plôch sa nemá zobrazovať ako samostatná karta');
assert(!html.includes('ekMapCard('), 'Odstránená karta mapovania sa nesmie renderovať');

console.log('economics-regressions: PASS');
