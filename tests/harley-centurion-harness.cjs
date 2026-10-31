// Synthetic fixtures only. Never distribute customer data with the tests.
'use strict';
const assert = require('node:assert/strict');
const C = require('../web/harley-centurion.js');
function fixture(part = 'TEST-PART1', calibration = 'TEST-CAL1') {
  const bytes = Buffer.alloc(200);
  bytes.write('Delphi', 0, 'ascii');
  bytes.write(part, 62, 'ascii');
  bytes.write(calibration, 82, 'ascii');
  bytes.write('VIN-SYNTHETIC-123', 102, 'ascii');
  return bytes;
}
const a = C.inspect(fixture());
assert.equal(a.recognized, true);
assert.equal(a.candidatePart, 'TEST-PART1');
assert.equal(a.candidateCalibration, 'TEST-CAL1');
assert.equal(JSON.stringify(a).includes('VIN-SYNTHETIC'), false);
const b = C.inspect(fixture('OTHER-PART1', 'TEST-CAL1'));
assert.deepEqual(C.compare(a, b), { candidatePart: 'different', candidateCalibration: 'same' });
const damaged = fixture();
damaged[62] = 0xfe; damaged[82] = 0;
const unknown = C.inspect(damaged);
assert.equal(unknown.candidatePart, null);
assert.equal(unknown.candidateCalibration, null);
assert.deepEqual(C.compare(a, unknown), { candidatePart: 'unavailable', candidateCalibration: 'unavailable' });
const other = fixture(); other[0] = 0x80;
assert.equal(C.inspect(other).recognized, false);
assert.throws(() => C.compare(a, C.inspect(other)));
assert.throws(() => C.inspect(Buffer.alloc(97)));
assert.throws(() => C.inspect(Buffer.alloc(C.MAX_SIZE + 1)));
console.log('synthetic Centurion headers passed');
