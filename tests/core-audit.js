#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const repo = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(repo, 'analyza-budovy.html'), 'utf8');
const start = html.indexOf('/* ============================================================================\n   core.js');
const end = html.indexOf('</script>', start);
if (start < 0 || end < 0) throw new Error('AnalyzaCore sa nepodarilo vybrať z HTML.');

const sandbox = { module: { exports: {} }, exports: {}, console };
vm.runInNewContext(html.slice(start, end), sandbox, { filename: 'embedded-core.js' });
const Core = sandbox.module.exports;

const fixtureDir = path.resolve(repo, '..', 'data test topolcianska');
const files = fs.readdirSync(fixtureDir)
  .filter((name) => name.toLowerCase().endsWith('.csv'))
  .sort()
  .map((name) => ({ name, text: new TextDecoder('windows-1250').decode(fs.readFileSync(path.join(fixtureDir, name))) }));

const model = Core.buildModel(files);
const totals = model.stats.totals;
const noisy = model.stats.roomTypeRows.filter((row) =>
  /HLAVN[YÝ] PROJEKTANT|D[AÁ]TUM|ZODPOVED|ZK\d|W1[AB]/i.test(row.name)
);

assert.strictEqual(files.length, 10, 'Testovacia sada Topoľčianska musí obsahovať 10 CSV.');
assert.ok(Math.abs(totals.spolocneTechnicke - 2787.58) < 0.001,
  'CSV bez celkového medzisúčtu musí použiť priamy súčet spoločných plôch.');
assert.ok(Math.abs(totals.predajnaInterior - 4139.28) < 0.001,
  'Kancelárske a obchodné jednotky musia zostať v predajnej ploche.');
assert.strictEqual(model.stats.roomTypeRows.filter((r) =>
  r.name === 'MIESTNOSŤ' && r.cat !== 'NEBYTOVÉ PRIESTORY').length, 0,
  'Generická miestnosť v predajnej nebytovej jednotke musí byť nebytový priestor.');
assert.ok(totals.spolocneTechnicke >= 0, 'Spoločná plocha nesmie byť záporná.');
assert.strictEqual(noisy.length, 0, 'Text pečiatky nesmie skončiť medzi typmi miestností.');

console.log(JSON.stringify({
  files: files.length,
  floors: model.floors.length,
  rooms: model.rooms.length,
  units: model.units.length,
  floorTotal: totals.podlahovaCelkova,
  saleable: totals.predajnaInterior,
  garages: totals.garaz.interior,
  common: totals.spolocneTechnicke,
  directPrivate: model.bilancie.byOwn['Súkromné'].total,
  directCommon: model.bilancie.byOwn['Spoločné'].total,
  directUseful: model.bilancie.uzitkova.total,
  exterior: (totals.byt.exterior || 0) + (totals.apartman.exterior || 0),
  noisyRoomTypes: noisy.map((row) => row.name)
}, null, 2));
