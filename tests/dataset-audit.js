#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const repo = path.resolve(__dirname, '..');
const root = path.resolve(repo, '..');
const html = fs.readFileSync(path.join(repo, 'analyza-budovy.html'), 'utf8');
const start = html.indexOf('/* ============================================================================\n   core.js');
const end = html.indexOf('</script>', start);
if (start < 0 || end < 0) throw new Error('AnalyzaCore sa nepodarilo vybrať z HTML.');
const sandbox = { module: { exports: {} }, exports: {}, console };
vm.runInNewContext(html.slice(start, end), sandbox, { filename: 'embedded-core.js' });
const Core = sandbox.module.exports;

function collect(args) {
  const out = [];
  for (const arg of args) {
    const p = path.resolve(root, arg);
    if (fs.statSync(p).isDirectory()) {
      for (const name of fs.readdirSync(p).sort()) {
        if (name.toLowerCase().endsWith('.csv')) out.push(path.join(p, name));
      }
    } else out.push(p);
  }
  return out;
}

const args = process.argv.slice(2);
if (!args.length) throw new Error('Použitie: dataset-audit.js <adresár alebo CSV> [...]');
const paths = collect(args);
const files = paths.map((p) => ({
  name: path.basename(p),
  text: new TextDecoder('windows-1250').decode(fs.readFileSync(p))
}));
const model = Core.buildModel(files);
const T = model.stats.totals;
const replacementChars = files.reduce((n, f) => n + (f.text.match(/�/g) || []).length, 0);
const badFloorChecks = model.checks.floorChecks.filter((x) => x.ok === false);
const duplicateUnits = [];
const seen = new Set();
for (const u of model.units) {
  const k = [u.floor, u.block, u.code].join('|');
  if (seen.has(k)) duplicateUnits.push(k); else seen.add(k);
}
const result = {
  dataset: args,
  files: files.length,
  floors: model.floors.length,
  rooms: model.rooms.length,
  units: model.units.length,
  totals: {
    floor: T.podlahovaCelkova,
    saleable: T.predajnaInterior,
    common: T.spolocneTechnicke,
    garage: T.garaz.interior,
    residentialExterior: (T.byt.exterior || 0) + (T.apartman.exterior || 0)
  },
  directUseful: model.bilancie.uzitkova.total,
  unknownRoomTypes: model.checks.unknown,
  zeroRoomUnits: model.checks.zeroIzby,
  badFormats: model.checks.badFormat,
  badFloorChecks: badFloorChecks.map((x) => ({ floor: x.label, calculated: x.sumGroups, csv: x.csv })),
  levelMismatch: model.checks.levelMismatch || [],
  duplicateUnits,
  replacementChars,
  failures: []
};
if (T.spolocneTechnicke < -0.001) result.failures.push('negative_common_area');
if (duplicateUnits.length) result.failures.push('duplicate_units');
if (model.checks.badFormat.length) result.failures.push('unrecognized_csv_format');
if (badFloorChecks.length) result.failures.push('floor_totals_mismatch');
if (replacementChars) result.failures.push('text_encoding_damage');
console.log(JSON.stringify(result, null, 2));
process.exitCode = result.failures.length ? 1 : 0;
