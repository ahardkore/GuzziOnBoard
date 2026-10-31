/* Synthetic fixtures only; this parser does not validate a tune definition. */
'use strict';
const assert = require('node:assert/strict');
const ini = require('../web/rusefi-ini.js');
const sig = 'rusEFI master.2024.02.02.alphax-4chan.1293678056';
assert.equal(ini.signature(`; comment\n[MegaTune]\nsignature = "other"\n[TunerStudio]\nsignature = "${sig}" ; comment\n`), sig);
assert.equal(ini.lookup(sig), 'https://rusefi.com/online/ini/rusefi/master/2024/02/02/alphax-4chan/1293678056.ini');
for (const invalid of ['rusEFI ../../evil', 'rusEFI foo/../../x', 'rusEFI master.2024.02.02.x.123?evil', 'rusEFI a.b.2024.02.02.x.123', '', 'other master.2024.02.02.x.123']) assert.equal(ini.lookup(invalid), null);
assert.throws(() => ini.signature('[TunerStudio]\n#if X\nsignature = "rusEFI x"\n#endif'));
assert.throws(() => ini.signature('[TunerStudio]\nsignature = "rusEFI x"\nsignature = "rusEFI y"'));
assert.throws(() => ini.signature('[TunerStudio]\nsignature = @@TS_SIGNATURE@@'));
assert.throws(() => ini.signature('[Other]\nsignature = "rusEFI x"'));
assert.throws(() => ini.signature('[TunerStudio]\n#endif\nsignature = "rusEFI x"'));
assert.throws(() => ini.signature('x'.repeat(ini.MAX_BYTES + 1)));
console.log('synthetic INI tests passed');
