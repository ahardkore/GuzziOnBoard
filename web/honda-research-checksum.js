/* Offline Honda source-ID one-byte sum; based on the source tables and
 * checksum algorithm of HondaECU forks (GPL-3.0). See
 * LICENSES/HondaECU-GPL-3.0.txt and docs/HONDA_VFR_RESEARCH.md.
 * Synthetic-tested; this is not flash or fitment approval. */
'use strict';
const HondaResearchChecksum = (() => {
  const candidates = typeof module !== 'undefined' && module.exports
    ? require('./honda-checksum-candidates.js') : HONDA_CHECKSUM_CANDIDATES;
  function sum(data) { let result = 0; for (const byte of data) result = (result + byte) & 255; return result; }
  function inspect(original, edited, variant) {
    if (!Object.hasOwn(candidates, variant)) throw new Error('Choose an exact source candidate.');
    const spec = candidates[variant], id = variant.match(/../g).map(x => parseInt(x,16));
    if (!(original instanceof Uint8Array) || !(edited instanceof Uint8Array) || original.length !== spec.size || edited.length !== spec.size)
      throw new Error(`Both images must be exactly ${spec.size} bytes without an external header.`);
    if (!id.every((byte, i) => original[spec.id_offset+i] === byte && edited[spec.id_offset+i] === byte))
      throw new Error('Both images must contain the selected ID candidate at the stated file offset.');
    if (sum(original) !== 0) throw new Error('Original does not have the source-described zero byte sum.');
    let changed = 0;
    for (let i = 0; i < spec.size; i++) if (i !== spec.checksum_offset && original[i] !== edited[i]) changed++;
    if (!changed) throw new Error('No calibration changes found outside the checksum byte.');
    const corrected = edited.slice(), before = corrected[spec.checksum_offset];
    corrected[spec.checksum_offset] = (before - sum(corrected)) & 255;
    if (sum(corrected) !== 0) throw new Error('Checksum calculation failed.');
    return {corrected, changed, before, after:corrected[spec.checksum_offset], editedSum:sum(edited), spec};
  }
  return {candidates, inspect};
})();
if (typeof module !== 'undefined' && module.exports) module.exports = HondaResearchChecksum;
if (typeof document !== 'undefined') {
  const original = document.getElementById('hondaVfrOriginal'), edited = document.getElementById('hondaVfrEdited');
  const confirm = document.getElementById('hondaVfrConfirm'), out = document.getElementById('hondaVfrOut');
  const variant = document.getElementById('hondaVfrVariant');
  const inspect = document.getElementById('hondaVfrInspect'), exportButton = document.getElementById('hondaVfrExport');
  for (const [id, spec] of Object.entries(HondaResearchChecksum.candidates).sort((a,b) => a[1].part.localeCompare(b[1].part))) {
    const option = document.createElement('option'); option.value = id;
    option.textContent = `${spec.part} · ${id.match(/../g).join(' ')} · ${spec.size} bytes`;
    variant.append(option);
  }
  let generation = 0, candidate = null;
  function invalidate() { generation++; candidate = null; exportButton.disabled = true; out.textContent = 'Selection changed; review again.'; }
  for (const field of [original, edited, confirm, variant]) field.addEventListener('change', invalidate);
  const hash = async data => {
    if (!globalThis.crypto?.subtle) throw new Error('SHA-256 is unavailable.');
    const digest = await crypto.subtle.digest('SHA-256', data);
    return [...new Uint8Array(digest)].map(x => x.toString(16).padStart(2, '0')).join('');
  };
  inspect.onclick = async () => {
    const token = ++generation; candidate = null; exportButton.disabled = true;
    try {
      const a = original.files?.[0], b = edited.files?.[0], selectedVariant = variant.value;
      if (!a || !b) throw new Error('Choose original and edited image files.');
      const spec = HondaResearchChecksum.candidates[selectedVariant];
      if (!spec) throw new Error('Choose an exact source candidate.');
      if (a.size !== spec.size || b.size !== spec.size) throw new Error(`Both images must be exactly ${spec.size} bytes.`);
      const [origBuffer, editBuffer] = await Promise.all([a.arrayBuffer(), b.arrayBuffer()]);
      const result = HondaResearchChecksum.inspect(new Uint8Array(origBuffer), new Uint8Array(editBuffer), selectedVariant);
      const [origHash, editHash, outputHash] = await Promise.all([hash(origBuffer), hash(editBuffer), hash(result.corrected)]);
      if (token !== generation) return;
      const hex = n => `0x${n.toString(16).toUpperCase()}`;
      out.textContent = `Source candidate: ${spec.part} · ${selectedVariant.match(/../g).join(' ')}\nSource: ${spec.source}\nID position: ${hex(spec.id_offset)} (${spec.id_basis}) · assumed read start: ${hex(spec.read_start)}${spec.commented ? '\nID association is commented out in one source table.' : ''}${spec.conflict ? `\nSource conflict: ${spec.conflict}` : ''}${spec.part === '38770-MGE-701' ? '\nWarning: the 701 XDF filename and title conflict.' : ''}\nOriginal SHA-256: ${origHash}\nEdited SHA-256: ${editHash}\nCorrected SHA-256: ${outputHash}\n${result.changed} bytes differ outside the checksum.\nEdited sum: ${hex(result.editedSum)}\nChecksum at ${hex(spec.checksum_offset)}: ${result.before} → ${result.after}; corrected byte sum is zero.\nOnly the checksum byte is changed in the exported copy. This is not flash-ready or proof of fitment.`;
      if (confirm.checked) { candidate = {data:result.corrected, hash:outputHash, part:spec.part}; exportButton.disabled = false; }
    } catch (error) { if (token === generation) out.textContent = `Not inspected: ${error.message}`; }
  };
  exportButton.onclick = async () => {
    const token = generation, selected = candidate;
    if (!selected || !confirm.checked) return;
    exportButton.disabled = true;
    try {
      const name = `honda-${selected.part.toLowerCase()}-research-${selected.hash.slice(0,12)}.bin`;
      let message;
      if (window.gobDesktop?.available) {
        if (typeof window.gobDesktop.saveBinary !== 'function') throw new Error('Desktop binary export unavailable.');
        let binary = '';
        for (let i = 0; i < selected.data.length; i += 8192) binary += String.fromCharCode(...selected.data.subarray(i, i+8192));
        const saved = await window.gobDesktop.saveBinary(name, btoa(binary));
        message = `Saved research copy: ${saved.path}`;
      } else {
        const url = URL.createObjectURL(new Blob([selected.data], {type:'application/octet-stream'}));
        const link = document.createElement('a'); link.href = url; link.download = name; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000); message = `Downloaded research copy: ${name}`;
      }
      if (token === generation) out.textContent += `\n${message}`;
    } catch (error) { if (token === generation) out.textContent += `\nSave failed: ${error.message}`; }
    finally { if (token === generation) exportButton.disabled = false; }
  };
}
