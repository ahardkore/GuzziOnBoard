/* Local MSE6 record inspection, adapted from NetworkDir/moto-ecu-checksum,
 * algorithms/bosch-mse6.js, revision 43ccc5f3663e2a175b7217f802bc302830e6862b.
 * Upstream README declares MIT but supplies no copyright notice; see
 * LICENSES/Moto-ECU-checksum-MIT.txt. This version does not alter or write files. */
'use strict';

function inspectMse6(bytes) {
  if (bytes.length < 0x140410 || bytes.length > 8 * 1024 * 1024) {
    throw new Error('Image must be between 0x140410 bytes and 8 MiB, without external headers.');
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const records = [];
  let work = 0;
  for (let off = 0x140000; off <= 0x140400; off += 4) {
    const start = view.getUint32(off), end = view.getUint32(off + 4);
    const stored = view.getUint32(off + 8), complement = view.getUint32(off + 12);
    if (((stored ^ complement) >>> 0) !== 0xffffffff || start >= end || end >= bytes.length || end - start < 0x1000) continue;
    work += Math.ceil((end - start) / 2);
    if (records.length >= 32 || work > 32 * 1024 * 1024) throw new Error('Too many candidate records or too much checksum work; inspection stopped.');
    let computed = 0;
    // Match the upstream executable loop: word starts are strictly < end.
    for (let i = start; i < end; i += 2) computed = (computed + bytes[i] * 256 + bytes[i + 1]) >>> 0;
    records.push({ offset: off, start, end, stored, computed, matches: stored === computed });
  }
  return records;
}

const mseFile = document.getElementById('mseImage');
const mseOut = document.getElementById('mseOut');
let mseGeneration = 0;
function invalidateMse() { ++mseGeneration; mseOut.textContent = ''; }
mseFile.addEventListener('change', invalidateMse);
document.getElementById('mseClear').onclick = () => { invalidateMse(); mseFile.value = ''; };
document.getElementById('mseInspect').onclick = async () => {
  const token = ++mseGeneration;
  mseOut.textContent = '';
  try {
    const file = mseFile.files?.[0];
    if (!file) throw new Error('Choose a local binary image.');
    if (file.size > 8 * 1024 * 1024) throw new Error('Image exceeds 8 MiB.');
    const buffer = await file.arrayBuffer();
    const records = inspectMse6(new Uint8Array(buffer));
    let hash = 'unavailable';
    if (globalThis.crypto?.subtle) {
      const digest = await crypto.subtle.digest('SHA-256', buffer);
      hash = [...new Uint8Array(digest)].map((v) => v.toString(16).padStart(2, '0')).join('');
    }
    if (token !== mseGeneration) return;
    const hex = (v) => `0x${v.toString(16).toUpperCase().padStart(8, '0')}`;
    const lines = records.map((r) => `Record ${hex(r.offset)} · range ${hex(r.start)} to ${hex(r.end)} · stored ${hex(r.stored)} · computed ${hex(r.computed)} · ${r.matches ? 'match' : 'mismatch'}`);
    mseOut.textContent = `${file.name} · ${file.size} bytes\nSHA-256: ${hash}\n${records.length} candidate record(s) found in source scan window.\n${lines.join('\n')}\nHeuristic inspection only; not ECU identification or flash approval. Source reports untouched 450SR factory images can mismatch.`;
  } catch (error) { if (token === mseGeneration) mseOut.textContent = `Not inspected: ${error.message}`; }
};
