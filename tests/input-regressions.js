const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const html = fs.readFileSync('analyza-budovy.html', 'utf8');
const fn = html.match(/function ekKatParseNumbers\(str\)\{[\s\S]*?\n  \}/);
assert(fn, 'Parser parciel sa nenašiel');
const ctx = {};
vm.runInNewContext(fn[0] + ';result=ekKatParseNumbers("17353/1,2,7,8,9,11,13, 17328/34, 17342/255")', ctx);
assert.deepStrictEqual(Array.from(ctx.result), [
  '17353/1','17353/2','17353/7','17353/8','17353/9','17353/11','17353/13','17328/34','17342/255'
]);
vm.runInNewContext('result=ekKatParseNumbers("4757/4, 4784/143, 4784/144, 4784/260, 4784/283")', ctx);
assert.deepStrictEqual(Array.from(ctx.result), ['4757/4','4784/143','4784/144','4784/260','4784/283']);
console.log('input-regressions: PASS');
