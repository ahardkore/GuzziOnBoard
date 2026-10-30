/* Dell'Orto RS200 checksum research, adapted from NetworkDir/moto-ecu-checksum
 * algorithms/dellorto-ecm.js at 43ccc5f3663e2a175b7217f802bc302830e6862b.
 * MIT notice: LICENSES/Moto-ECU-checksum-MIT.txt. Exact source-reported part
 * label required; no ECU communication or claim of physical validation. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id), image = $('bajajImage'), confirm = $('bajajConfirm');
  const out = $('bajajOut'), save = $('bajajSave');
  const size = 0xc0000, start = 0x80000, offset = 0x921fe;
  const part = 'JL351458010651', signature = 'DellOrto 32bit Engine Management System';
  let generation = 0, candidate = null;
  function reset() { generation++; candidate = null; save.disabled = true; out.textContent = ''; }
  image.addEventListener('change', reset); confirm.addEventListener('change', reset);
  $('bajajClear').onclick = () => { image.value = ''; confirm.checked = false; reset(); };
  async function hash(bytes) {
    if (!globalThis.crypto?.subtle) throw new Error('SHA-256 is unavailable.');
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    return [...new Uint8Array(digest)].map(x => x.toString(16).padStart(2, '0')).join('');
  }
  function inspect(bytes) {
    if (bytes.length !== size) throw new Error('Expected exactly 768 KiB, with no external file header.');
    const encoder = new TextEncoder(), id = encoder.encode(part), sig = encoder.encode(signature);
    if (!id.every((v, i) => bytes[start + i] === v)) throw new Error('The source-reported part label is not present at the calibration start.');
    // Bound the signature scan and require all bytes, not a substring of decoded text.
    let found = false;
    for (let i = 0; i <= bytes.length - sig.length && !found; i++) {
      if (bytes[i] === sig[0] && sig.every((v, j) => bytes[i + j] === v)) found = true;
    }
    if (!found) throw new Error('The source-described DellOrto signature was not found.');
    let sum = 0;
    for (let i = start; i < offset; i++) sum = (sum + bytes[i]) & 0xffff;
    const computed = (~sum) & 0xffff, stored = (bytes[offset] << 8) | bytes[offset + 1];
    return { stored, computed };
  }
  $('bajajInspect').onclick = async () => {
    const token = ++generation; candidate = null; save.disabled = true; out.textContent = '';
    try {
      const file = image.files?.[0];
      if (!file || file.size !== size) throw new Error('Choose a raw image of exactly 768 KiB.');
      const input = new Uint8Array(await file.arrayBuffer());
      const result = inspect(input), sourceHash = await hash(input);
      const output = Uint8Array.from(input); output[offset] = result.computed >> 8; output[offset + 1] = result.computed & 255;
      const verified = inspect(output);
      if (verified.stored !== verified.computed) throw new Error('Corrected checksum did not verify.');
      const outputHash = await hash(output);
      if (token !== generation) return;
      const hex = n => '0x' + n.toString(16).toUpperCase().padStart(4, '0');
      out.textContent = `${file.name} · ${file.size} bytes\nSource SHA-256: ${sourceHash}\nPart label: ${part} (not ECU identification)\nChecksum at 0x921FE: ${hex(result.stored)} → ${hex(result.computed)}\n${result.stored === result.computed ? 'Checksum matches' : 'Checksum differs'}; proposed output SHA-256: ${outputHash}\nOnly the checksum word may change. Other checksums and signatures are not verified; research only, not flash-ready.`;
      if (confirm.checked && result.stored !== result.computed) { candidate = { output, hash: outputHash }; save.disabled = false; }
    } catch (error) { if (token === generation) out.textContent = `Not inspected: ${error.message}`; }
  };
  save.onclick = async () => {
    const item = candidate, token = generation; if (!item || !confirm.checked) return;
    save.disabled = true;
    try {
      const name = `bajaj-rs200-checksum-research-${item.hash.slice(0, 12)}.bin`;
      let message;
      if (window.gobDesktop?.available) {
        if (typeof window.gobDesktop.saveBinary !== 'function') throw new Error('The desktop host does not support binary exports.');
        let binary = '';
        for (let i = 0; i < item.output.length; i += 8192) binary += String.fromCharCode(...item.output.subarray(i, i + 8192));
        const result = await window.gobDesktop.saveBinary(name, btoa(binary)); message = `Saved research copy: ${result.path}`;
      } else {
        const url = URL.createObjectURL(new Blob([item.output], { type: 'application/octet-stream' }));
        const link = document.createElement('a'); link.href = url; link.download = name; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000); message = `Downloaded research copy: ${name}`;
      }
      if (token === generation) out.textContent += `\n${message}`;
    } catch (error) { if (token === generation) out.textContent += `\nExport failed: ${error.message}`; }
    finally { if (token === generation) save.disabled = false; }
  };
})();
