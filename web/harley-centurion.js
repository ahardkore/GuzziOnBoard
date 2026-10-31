/* Local, read-only inspection of candidate header fields in selected Delphi
 * Centurion files. Field offsets were independently observed in the public
 * Performance-Harley-Davidson-Tuning repository (a3250e4); no source binaries,
 * VINs, registration data, executable code, or tune values are bundled.
 * Header matching does not identify a vehicle, decode a tune, or authorize ECU writing.
 */
'use strict';

const HarleyCenturion = (() => {
  const MAX_SIZE = 16 * 1024 * 1024;
  const MIN_SIZE = 98;
  function field(data, offset, length) {
    const bytes = data.subarray(offset, offset + length);
    let end = bytes.indexOf(0);
    if (end < 0) end = bytes.length;
    // Reject binary, embedded control characters and unrecognised fillers;
    // never interpret arbitrary payload bytes as a known identifier.
    const trimmed = bytes.subarray(0, end);
    if (!trimmed.length || [...trimmed].some((n) => n < 0x20 || n > 0x7e)) return null;
    const text = String.fromCharCode(...trimmed).trim();
    return /[0-9]/.test(text) && /^[A-Za-z0-9][A-Za-z0-9 ._/-]{1,15}$/.test(text) ? text : null;
  }
  function inspect(data) {
    if (!(data instanceof Uint8Array)) throw new Error('Expected local file bytes.');
    if (data.length < MIN_SIZE || data.length > MAX_SIZE) {
      throw new Error('File must be between 98 bytes and 16 MiB.');
    }
    const tag = [68, 101, 108, 112, 104, 105];
    if (!tag.every((value, i) => data[i] === value) || ![0, 32].includes(data[6])) {
      return { recognized: false, size: data.length };
    }
    // Inspect only these two bounded header slots. Do not read or expose the
    // observed VIN slot or surrounding customer / registration information.
    return { recognized: true, size: data.length,
      candidatePart: field(data, 62, 16), candidateCalibration: field(data, 82, 16) };
  }
  function compare(a, b) {
    if (!a.recognized || !b.recognized) throw new Error('Both headers must be recognized before comparing fields.');
    const compareField = (x, y) => !x || !y ? 'unavailable' : x === y ? 'same' : 'different';
    return { candidatePart: compareField(a.candidatePart, b.candidatePart),
      candidateCalibration: compareField(a.candidateCalibration, b.candidateCalibration) };
  }
  return { MAX_SIZE, inspect, compare };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = HarleyCenturion;

if (typeof document !== 'undefined' && document.getElementById('centurionInspect')) {
  const first = document.getElementById('centurionFirst');
  const second = document.getElementById('centurionSecond');
  const output = document.getElementById('centurionOut');
  let generation = 0;
  const invalidate = () => { generation++; output.textContent = ''; };
  [first, second].forEach((input) => input.addEventListener('change', invalidate));
  document.getElementById('centurionClear').onclick = () => {
    first.value = ''; second.value = ''; invalidate();
  };
  async function read(file) {
    if (!file) throw new Error('Choose a file to inspect.');
    if (file.size < 98 || file.size > HarleyCenturion.MAX_SIZE) throw new Error('File must be between 98 bytes and 16 MiB.');
    // Only read the header, not the remainder of the file.
    const header = new Uint8Array(await file.slice(0, 98).arrayBuffer());
    return { ...HarleyCenturion.inspect(header), size: file.size };
  }
  function describe(label, result) {
    if (!result.recognized) return `${label}: header not recognized (${result.size} bytes). This does not prove encryption or corruption.`;
    return `${label}: Delphi-like header (${result.size} bytes)`
      + `\n  Candidate ECU-part field (0x3E): ${result.candidatePart || 'unavailable / unrecognized'}`
      + `\n  Candidate calibration field (0x52): ${result.candidateCalibration || 'unavailable / unrecognized'}`;
  }
  document.getElementById('centurionInspect').onclick = async () => {
    const token = ++generation;
    output.textContent = 'Inspecting selected headers locally…';
    try {
      const [a, b] = await Promise.all([read(first.files?.[0]), second.files?.[0] ? read(second.files[0]) : null]);
      if (generation !== token) return;
      let text = describe('First', a);
      if (b) {
        text += '\n\n' + describe('Second', b);
        if (a.recognized && b.recognized) {
          const result = HarleyCenturion.compare(a, b);
          text += `\n\nCandidate part field: ${result.candidatePart}\nCandidate calibration field: ${result.candidateCalibration}`;
        }
      }
      text += '\n\nCandidate fields only. The observed VIN slot and filenames are not displayed or uploaded. Candidate fields may themselves contain sensitive information; review before sharing. Matching fields do not prove fitment, checksum validity, interchangeability, or permission to flash.';
      output.textContent = text;
    } catch (error) { if (generation === token) output.textContent = `Not inspected: ${error.message}`; }
  };
}
