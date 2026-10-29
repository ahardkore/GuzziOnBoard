/* Offline Harley Delphi calibration-region workspace.
 * Mapping follows HarleyECUTool's published memory-map description at
 * rob9206/lawflo commit 6255518dc9118d960efa42d6d9dc975926bbd579.
 * Independently implemented; no upstream program or firmware is copied.
 * No ECU communications, checksum repair, definitions, or flash authorization.
 */
'use strict';

const HarleyRegion = (() => {
  const CAL_SIZE = 0x28000;
  const TUNE_OFFSET = 0x1c000;
  const TUNE_SIZE = 0x4000;

  function tuneRegion(bytes) {
    if (!(bytes instanceof Uint8Array)) throw new Error('Expected raw binary data.');
    if (bytes.length === TUNE_SIZE) return { kind: '16 KiB tune', bytes: Uint8Array.from(bytes) };
    if (bytes.length === CAL_SIZE) return {
      kind: '160 KiB calibration', bytes: Uint8Array.from(bytes.subarray(TUNE_OFFSET, TUNE_OFFSET + TUNE_SIZE)),
    };
    throw new Error('Expected exactly 160 KiB calibration or 16 KiB tune; tool containers and headers are not supported.');
  }

  function buildCalibration(calibration, tune) {
    if (!(calibration instanceof Uint8Array) || calibration.length !== CAL_SIZE ||
        !(tune instanceof Uint8Array) || tune.length !== TUNE_SIZE) {
      throw new Error('A 160 KiB calibration and a 16 KiB replacement tune are required.');
    }
    const result = Uint8Array.from(calibration);
    result.set(tune, TUNE_OFFSET);
    return result;
  }

  function compare(a, b, limit = 40) {
    const left = tuneRegion(a).bytes, right = tuneRegion(b).bytes;
    let count = 0, totalRanges = 0, ranges = [], start = -1;
    for (let i = 0; i <= TUNE_SIZE; i++) {
      const differs = i < TUNE_SIZE && left[i] !== right[i];
      if (differs) { count++; if (start < 0) start = i; }
      else if (start >= 0) {
        totalRanges++;
        if (ranges.length < limit) ranges.push({ offset: start, length: i - start });
        start = -1;
      }
    }
    return { changedBytes: count, ranges, truncated: totalRanges > ranges.length };
  }
  return { CAL_SIZE, TUNE_OFFSET, TUNE_SIZE, tuneRegion, compare, buildCalibration };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = HarleyRegion;

if (typeof document !== 'undefined' && document.getElementById('harleyRegionInspect')) {
  const first = document.getElementById('harleyRegionFirst');
  const second = document.getElementById('harleyRegionSecond');
  const confirm = document.getElementById('harleyRegionConfirm');
  const replaceConfirm = document.getElementById('harleyRegionReplaceConfirm');
  const build = document.getElementById('harleyRegionBuild');
  const out = document.getElementById('harleyRegionOut');
  const save = document.getElementById('harleyRegionSave');
  let generation = 0, inspected = null;
  const invalidate = () => { generation++; inspected = null; save.disabled = true; build.disabled = true; out.textContent = ''; };
  [first, second, confirm, replaceConfirm].forEach((el) => el.addEventListener('change', invalidate));
  document.getElementById('harleyRegionClear').onclick = () => {
    first.value = ''; second.value = ''; confirm.checked = false; replaceConfirm.checked = false; invalidate();
  };
  const hex = (value) => '0x' + value.toString(16).toUpperCase();
  async function digest(bytes) {
    if (!globalThis.crypto?.subtle) throw new Error('SHA-256 is unavailable in this browser.');
    const hash = await crypto.subtle.digest('SHA-256', bytes);
    return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, '0')).join('');
  }
  async function read(file) {
    if (!file) throw new Error('Choose a first calibration or tune file.');
    if (/\.ori$/i.test(file.name)) throw new Error('Centurion .ori containers are not raw calibration files.');
    if (file.size !== HarleyRegion.CAL_SIZE && file.size !== HarleyRegion.TUNE_SIZE) {
      throw new Error('Expected exactly 160 KiB calibration or 16 KiB tune; tool containers and headers are not supported.');
    }
    const data = new Uint8Array(await file.arrayBuffer());
    const region = HarleyRegion.tuneRegion(data);
    return { name: file.name, data, ...region, fileHash: await digest(data), tuneHash: await digest(region.bytes) };
  }
  document.getElementById('harleyRegionInspect').onclick = async () => {
    const token = ++generation;
    inspected = null; save.disabled = true; build.disabled = true; out.textContent = 'Inspecting locally…';
    try {
      if (!confirm.checked) throw new Error('Confirm you intend to inspect the source-described Delphi layout.');
      const [a, b] = await Promise.all([read(first.files?.[0]), second.files?.[0] ? read(second.files[0]) : null]);
      if (token !== generation) return;
      let text = `First: ${a.name} · ${a.kind}\nFile SHA-256: ${a.fileHash}\n16 KiB region SHA-256: ${a.tuneHash}`;
      if (a.kind === '160 KiB calibration') text += '\nRegion: offsets 0x1C000–0x1FFFF, end exclusive 0x20000.';
      if (b) {
        const diff = HarleyRegion.compare(a.bytes, b.bytes);
        text += `\n\nSecond: ${b.name} · ${b.kind}\nFile SHA-256: ${b.fileHash}\n16 KiB region SHA-256: ${b.tuneHash}`;
        text += `\nChanged bytes: ${diff.changedBytes}`;
        if (diff.ranges.length) text += '\nChanged tune-relative ranges:\n' + diff.ranges.map((r) =>
          `  ${hex(r.offset)}–${hex(r.offset + r.length - 1)} (${r.length} bytes)`).join('\n');
        if (diff.truncated) text += '\n  Additional ranges omitted.';
      }
      text += '\n\nResearch workspace only. File length and SHA-256 do not identify an ECU, verify a calibration checksum, or authorize flashing.';
      inspected = { a, b };
      out.textContent = text;
      save.disabled = a.kind !== '160 KiB calibration';
      build.disabled = !(a.kind === '160 KiB calibration' && b?.kind === '16 KiB tune' && replaceConfirm.checked);
    } catch (error) { if (token === generation) out.textContent = `Not inspected: ${error.message}`; }
  };
  async function saveBytes(filename, bytes) {
    if (window.gobDesktop?.available) {
      if (typeof window.gobDesktop.saveBinary !== 'function') throw new Error('The desktop host does not support binary exports.');
      let text = '';
      for (let i = 0; i < bytes.length; i += 8192) text += String.fromCharCode(...bytes.subarray(i, i + 8192));
      const result = await window.gobDesktop.saveBinary(filename, btoa(text));
      return `Saved research copy: ${result.path}`;
    }
    const url = URL.createObjectURL(new Blob([bytes], { type: 'application/octet-stream' }));
    const link = document.createElement('a'); link.href = url; link.download = filename; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return `Downloaded research copy: ${filename}`;
  }
  save.onclick = async () => {
    const item = inspected?.a, token = generation;
    if (!item || item.kind !== '160 KiB calibration') return;
    save.disabled = true;
    try {
      const filename = `harley-region-research-${item.tuneHash.slice(0, 12)}.bin`;
      const message = await saveBytes(filename, item.bytes);
      if (token === generation) out.textContent += `\n\n${message}`;
    } catch (error) { if (token === generation) out.textContent += `\n\nExport failed: ${error.message}`; }
    finally { if (token === generation) save.disabled = false; }
  };
  build.onclick = async () => {
    const item = inspected, token = generation;
    if (!item || !replaceConfirm.checked || item.a.kind !== '160 KiB calibration' || item.b?.kind !== '16 KiB tune') return;
    build.disabled = true;
    try {
      const output = HarleyRegion.buildCalibration(item.a.data, item.b.bytes);
      const hash = await digest(output);
      if (token !== generation) return;
      const filename = `harley-calibration-research-${hash.slice(0, 12)}.bin`;
      const message = await saveBytes(filename, output);
      if (token === generation) out.textContent += `\n\n${message}\nOutput SHA-256: ${hash}\nNo checksum repaired. Research copy only, not flash-ready.`;
    } catch (error) { if (token === generation) out.textContent += `\n\nBuild failed: ${error.message}`; }
    finally { if (token === generation) build.disabled = false; }
  };
}
