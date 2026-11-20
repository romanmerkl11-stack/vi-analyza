#!/usr/bin/env node
'use strict';
// Regresie pre Gerlach II: objekt z názvu výkresu (SO.22.7-8 → SO 7 + SO 8), podkrovie,
// záložka Povrchy (bez VSYP, „GRES, NAT.1" jeden materiál, kontrola proti CELKOVEJ)
// a Flatmix (násobič objektov, mezonety len v rámci objektu).
// Fixture tests/fixtures-gerlach-synth.csv = výstup pdf_legend.to_app_csv zo syntetického
// výkresu v tests/test_legend_positional.py.
// Spúšťaj z adresára repa:  node tests/povrchy-regressions.js

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const repo = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(repo, 'analyza-budovy.html'), 'utf8');
function load(marker) {
  const start = html.indexOf(marker);
  const end = html.indexOf('</script>', start);
  assert(start >= 0 && end > start, 'modul ' + marker + ' sa nenašiel');
  const sb = { module: { exports: {} }, exports: {}, console };
  vm.runInNewContext(html.slice(start, end), sb);
  return sb.module.exports;
}
const Core = load('/* ============================================================================\n   core.js');
const Flat = load('/* FlatmixCore');

// --- objekty z názvu
assert.deepStrictEqual(Array.from(Core.objectsFromName('GR_SO.22.7-8-02.5_podkr.pdf')), ['7', '8']);
assert.deepStrictEqual(Array.from(Core.objectsFromName('GR_SO.22.5-02.2_1np')), ['5']);
assert.deepStrictEqual(Array.from(Core.objectsFromName('RNDZ_C_02_1NP-C.csv')), []);

// --- model: výkres SO.22.7-8 sa počíta za SO 7 aj SO 8
const csv = fs.readFileSync(path.join(__dirname, 'fixtures-gerlach-synth.csv'), 'utf8');
const model = Core.buildModel([{ name: '2NP GR_SO.22.7-8-02.3_2np.csv', text: csv }]);
assert.strictEqual(model.floors.length, 2, 'dve kópie podlažia (SO 7, SO 8)');
assert.deepStrictEqual(Array.from(model.floors.map((f) => f.so)), ['7', '8']);
assert.strictEqual(model.units.length, 4, '2 byty × 2 objekty');
const codes8 = Array.from(model.units.filter((u) => u.so === '8').map((u) => u.code)).sort();
assert.deepStrictEqual(codes8, ['8.B.1.04.', '8.B.1.05.'], 'kódy bytov prečíslované na SO 8: ' + codes8);
assert(model.rooms.some((r) => r.so === '8' && r.code === '1.01'), 'kódy miestností v byte ostávajú');

// --- povrchy
const P = Core.computePovrchy(model);
assert.deepStrictEqual(Array.from(P.soList), ['7', '8']);
const mat = {}; P.byMat.forEach((e) => { mat[e.key.mat] = e; });
assert(mat['GRES, NAT.1'], '„GRES, NAT.1" je jeden materiál');
assert(!mat['NAT.1'] && !mat['VSYP'], 'nedelí sa podľa čiarky, VSYP vynechaný');
assert.strictEqual(mat['LAMINO'].total, 2 * (5.2 + 15 + 20));
assert.strictEqual(mat['GRES M.'].total, 2 * (6 + 2), 'balkón + závetrie v GRES M.');
// spolu = všetko okrem VSYP, za oba objekty
assert.strictEqual(P.total, 2 * (18.4 + 22.1 + 4 + 5.2 + 4.3 + 15 + 6 + 20 + 1.5 + 2 + 3.25));
assert.strictEqual(P.excluded.length, 2, 'VSYP × 2 objekty');
// kontrola proti výkresu: interiér = CELKOVÁ
assert.strictEqual(P.kontrola.length, 2);
P.kontrola.forEach((k) => assert.strictEqual(k.ok, true, 'kontrola ' + JSON.stringify(k)));
// obklad: kúpeľňa + WC (KER.O.), odhad > 0, výška 2 m mení výsledok
assert.strictEqual(P.obklad.count, 4);
assert(P.obklad.total > 0);
const P3 = Core.computePovrchy(model, { obkladVyska: 3 });
assert(P3.obklad.total > P.obklad.total, 'výška obkladu sa prejaví');

// --- podkrovie
const pk = Core.buildModel([{ name: 'GR_SO.22.5-02.5_podkr.csv', text: csv.replace(/7\.B\.1\./g, '5.B.4.') }]);
assert.strictEqual(pk.floors[0].label, 'Podkrovie');

// --- Flatmix: násobič objektov, podkrovie, mezonety v rámci objektu
assert.strictEqual(Flat.floorMultiplier('GR_SO.22.7-8-02.3_2np.pdf').mult, 2);
assert.strictEqual(Flat.floorMultiplier('GR_SO.22.9-02.5_podkr.pdf').levels[0], 99);
assert.strictEqual(Flat.floorMultiplier('RNDZ_B_04_3+5+7NP-B2.pdf').mult, 3);
function f(file, units) {
  const fm = Flat.floorMultiplier(file);
  return { file, mode: 'legenda', multiplier: fm.mult, levels: fm.levels, objects: fm.objects,
           units, warn: [], control: null, unknownRooms: {} };
}
const B = Flat.build([
  f('GR_SO.22.5-02.3_2np.pdf', [{ kind: 'BYT', code: '5.2.11', izby: 2, rooms: 4, area: 50 }]),
  f('GR_SO.22.5-02.4_3np.pdf', [{ kind: 'BYT', code: '5.2.11', izby: 1, rooms: 2, area: 20 }]),
  // SO 6 2NP má chybne kód zo SO 5 — nesmie sa zlúčiť so SO 5
  f('GR_SO.22.6-02.3_2np.pdf', [{ kind: 'BYT', code: '5.2.11', izby: 2, rooms: 4, area: 48 }]),
  f('GR_SO.22.7-8-02.3_2np.pdf', [{ kind: 'BYT', code: '7.B.1.04.', izby: 2, rooms: 4, area: 40 }])
]);
assert.strictEqual(B.mezonety.length, 1, 'jeden mezonet (SO 5): ' + JSON.stringify(B.mezonety));
assert.strictEqual(B.mezonety[0].so, '5');
assert.strictEqual(B.mezonety[0].area, 70);
assert.strictEqual(B.units.length, 1 + 1 + 2, 'mezonet SO5 + byt SO6 + byt SO7-8 ×2');
assert.deepStrictEqual(Array.from(B.units.filter((u) => u.code === '7.B.1.04.').map((u) => u.so)), ['7', '8']);

console.log('povrchy-regressions: PASS');
