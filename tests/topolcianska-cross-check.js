const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const repo = path.resolve(__dirname, '..');
const data = path.resolve(repo, '..', 'Topolcianska');
const html = fs.readFileSync(path.join(repo, 'analyza-budovy.html'), 'utf8');
const start = html.indexOf('/* ============================================================================\n   core.js');
const end = html.indexOf('</script>', start);
const sandbox = {module:{exports:{}}, exports:{}, console};
vm.runInNewContext(html.slice(start, end), sandbox);
const files = fs.readdirSync(data).filter(n => n.endsWith('.csv')).map(name => ({
  name,
  text: new TextDecoder('windows-1250').decode(fs.readFileSync(path.join(data, name)))
}));
const model = sandbox.module.exports.buildModel(files);
const checks = model.checks.floorChecks;
assert.strictEqual(checks.length, 10);
assert(checks.every(x => x.sumGroups > 0), 'Každé podlažie musí mať vypočítanú plochu, nie falošnú nulu');
assert(checks.every(x => x.csv === null && x.ok === null), 'Chýbajúce CSV súčty musia zostať neoverené');
assert(Math.abs(checks.reduce((n,x) => n+x.sumGroups, 0) - model.bilancie.uzitkova.total) < 0.01);
console.log('topolcianska-cross-check: PASS', checks.map(x => [x.label, x.sumGroups]));
