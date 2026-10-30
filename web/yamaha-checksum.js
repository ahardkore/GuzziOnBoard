/* Research-only Yamaha MT checksum observation, adapted from
 * NetworkDir/moto-ecu-checksum algorithms/yamaha-mt.js,
 * revision 43ccc5f3663e2a175b7217f802bc302830e6862b. Upstream README
 * states MIT but names no copyright holder; see LICENSES/Moto-ECU-checksum-MIT.txt.
 * Modified: explicit model/size selection, inspection and an optional research
 * copy with checksum repair; no auto-detection, ECU I/O or hardware validation.
 */
'use strict';

function inspectYamahaMt(bytes, variant) {
  const specs = { mt_1m: { length: 0x100000, target: 0x5aa5 }, mt07_2020: { length: 0xe0000, target: 0xe81f } };
  if (!Object.hasOwn(specs, variant)) throw new Error('Choose a source-reported model/size scope.');
  const spec = specs[variant], n = bytes.length;
  if (n !== spec.length) throw new Error(`Selected scope requires exactly ${spec.length} bytes; no tool headers accepted.`);
  const id = bytes.slice(n - 16, n - 8);
  if (id.length !== 8 || !id.every((c) => (c >= 48 && c <= 57) || (c >= 65 && c <= 90)) || id[4] !== 89 || bytes[n - 6] !== 0x64 || bytes[n - 5] !== 0x02) {
    throw new Error('Image trailer does not match the source-described layout; no checksum result.');
  }
  let sum = 0;
  for (let i = 0; i < n; i += 2) sum = (sum + bytes[i] * 256 + bytes[i + 1]) & 0xffff;
  return {
    trailerId: String.fromCharCode(...id),
    checksumOffset: n - 8,
    stored: bytes[n - 8] * 256 + bytes[n - 7],
    observed: sum,
    target: spec.target,
    matches: sum === spec.target,
  };
}

const yamahaFile = document.getElementById('yamahaImage');
const yamahaVariant = document.getElementById('yamahaVariant');
const yamahaOut = document.getElementById('yamahaOut');
const yamahaConfirm = document.getElementById('yamahaRepairConfirm');
const yamahaSave = document.getElementById('yamahaRepairSave');
let yamahaGeneration = 0, yamahaCandidate = null;
function invalidateYamaha() { ++yamahaGeneration; yamahaCandidate = null; yamahaSave.disabled = true; yamahaOut.textContent = ''; }
yamahaFile.addEventListener('change', invalidateYamaha);
yamahaVariant.addEventListener('change', invalidateYamaha);
yamahaConfirm.addEventListener('change', invalidateYamaha);
document.getElementById('yamahaClear').onclick = () => { invalidateYamaha(); yamahaFile.value = ''; yamahaVariant.value = ''; yamahaConfirm.checked = false; };
document.getElementById('yamahaInspect').onclick = async () => {
  const token = ++yamahaGeneration;
  yamahaOut.textContent = ''; yamahaCandidate = null; yamahaSave.disabled = true;
  try {
    const file = yamahaFile.files?.[0];
    if (!file) throw new Error('Choose a local binary image.');
    if (!yamahaVariant.value) throw new Error('Choose a source-reported model/size scope.');
    if (file.size > 0x100000) throw new Error('File exceeds the supported maximum of 1 MiB.');
    const variant = yamahaVariant.value;
    const buffer = await file.arrayBuffer();
    const result = inspectYamahaMt(new Uint8Array(buffer), variant);
    let hash = 'unavailable';
    if (globalThis.crypto?.subtle) {
      const digest = await crypto.subtle.digest('SHA-256', buffer);
      hash = [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('');
    }
    if (token !== yamahaGeneration) return;
    const hex4 = (x) => `0x${x.toString(16).toUpperCase().padStart(4, '0')}`;
    const corrected = (result.target - result.observed + result.stored) & 0xffff;
    yamahaOut.textContent = `${file.name} · ${file.size} bytes\nSHA-256: ${hash}\nTrailer characters: ${result.trailerId} (not proof of fitment)\nStored word at 0x${result.checksumOffset.toString(16).toUpperCase()}: ${hex4(result.stored)}\nObserved sum: ${hex4(result.observed)} · source target: ${hex4(result.target)}\n${result.matches ? 'Sum matches source target' : 'Sum does not match source target'} — research only; not flash or safety approval.\nProposed checksum word: ${hex4(result.stored)} → ${hex4(corrected)}; no other bytes will change.`;
    if (yamahaConfirm.checked && !result.matches && hash !== 'unavailable') {
      const output = new Uint8Array(buffer.slice(0));
      output[result.checksumOffset] = corrected >> 8;
      output[result.checksumOffset + 1] = corrected & 255;
      const verified = inspectYamahaMt(output, variant);
      if (!verified.matches) throw new Error('Corrected copy failed checksum verification.');
      const digest = await crypto.subtle.digest('SHA-256', output);
      const outputHash = [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('');
      if (token !== yamahaGeneration) return;
      yamahaCandidate = { output, hash: outputHash };
      yamahaOut.textContent += `\nOutput SHA-256: ${outputHash}\nSource remains unchanged. No signature or other checksum verified; not flash-ready.`;
      yamahaSave.disabled = false;
    }
  } catch (error) { if (token === yamahaGeneration) yamahaOut.textContent = `Not inspected: ${error.message}`; }
};

// Export is deliberately separate from inspection and writes only a new copy.
yamahaSave.onclick = async () => {
  const candidate = yamahaCandidate, token = yamahaGeneration;
  if (!candidate || !yamahaConfirm.checked) return;
  yamahaSave.disabled = true;
  try {
    const name = `yamaha-mt-checksum-research-${candidate.hash.slice(0, 12)}.bin`;
    let message;
    if (window.gobDesktop?.available) {
      if (typeof window.gobDesktop.saveBinary !== 'function') throw new Error('The desktop host does not support binary exports.');
      let text = '';
      for (let i = 0; i < candidate.output.length; i += 8192) text += String.fromCharCode(...candidate.output.subarray(i, i + 8192));
      const saved = await window.gobDesktop.saveBinary(name, btoa(text));
      message = `Saved research copy: ${saved.path}`;
    } else {
      const url = URL.createObjectURL(new Blob([candidate.output], { type: 'application/octet-stream' }));
      const link = document.createElement('a'); link.href = url; link.download = name; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      message = `Downloaded research copy: ${name}`;
    }
    if (token === yamahaGeneration) yamahaOut.textContent += `\n${message}`;
  } catch (error) { if (token === yamahaGeneration) yamahaOut.textContent += `\nExport failed: ${error.message}`; }
  finally { if (token === yamahaGeneration) yamahaSave.disabled = false; }
};
