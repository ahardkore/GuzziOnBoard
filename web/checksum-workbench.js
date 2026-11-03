/* Checksum workbench: find, verify and repair a whole-file checksum in an image
 * the operator supplies. Nothing here contacts an ECU, writes an original file
 * or decides that a repaired image is flash-ready. The algorithm set and the
 * family notes follow NetworkDir/moto-ecu-checksum (algorithms/*.js, revision
 * 43ccc5f3663e2a175b7217f802bc302830e6862b) and this program's own
 * guzzionboard/checksums.py; only the arithmetic is shared knowledge, no code
 * is copied from either. */
'use strict';

const CHECKSUM_ALGORITHMS = [
  { id: 'sum8', label: 'byte sum, 8-bit', width: 1, weak: true },
  { id: 'xor8', label: 'byte XOR, 8-bit', width: 1, weak: true },
  { id: 'sum16bytes', label: 'byte sum, 16-bit', width: 2 },
  { id: 'sum16words_be', label: '16-bit word sum, big-endian words', width: 2 },
  { id: 'sum16words_le', label: '16-bit word sum, little-endian words', width: 2 },
  { id: 'sum32words_be', label: '32-bit word sum, big-endian words', width: 4 },
  { id: 'crc16ccitt', label: 'CRC-16/CCITT-FALSE (init 0xFFFF)', width: 2 },
  { id: 'crc16xmodem', label: 'CRC-16/XMODEM (init 0x0000)', width: 2 },
  { id: 'crc32', label: 'CRC-32 (zlib / IEEE)', width: 4 },
];

const CHECKSUM_FAMILIES = [
  { family: 'Bosch MSE6.0', note: 'Record table at the end of the image; each record carries a stored word and its one\u2019s complement. Use the CFMoto MSE6 tool for the full walk.', tool: '#cfmotoChecksum' },
  { family: 'Bosch MSE8.0 / MG1', note: 'Multi-block whole-file checksum; published only as research in the same source. Not verified here.', tool: '' },
  { family: 'Honda Keihin (PGM-FI)', note: 'Per-profile byte sum with a source ID in the header; the Honda tools carry the exact offsets.', tool: '#hondaVfrChecksum' },
  { family: 'Dell\u2019Orto ECM', note: 'Word sum over the calibration block. The Bajaj RS200 tool implements the documented variant.', tool: '#bajajChecksum' },
  { family: 'Yamaha MT image', note: 'Whole-file sum; the Yamaha tool checks it and reports the source conflict.', tool: '#yamahaResearch' },
  { family: 'Italjet / Suzuki, QH250', note: 'Source-described variants; not implemented here, listed so a mismatch can be recognised.', tool: '' },
];

const crc32Table = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function checksumCrc16(bytes, from, to, init) {
  let crc = init & 0xffff;
  for (let i = from; i < to; i += 1) {
    crc ^= bytes[i] << 8;
    for (let bit = 0; bit < 8; bit += 1) crc = crc & 0x8000 ? ((crc << 1) ^ 0x1021) & 0xffff : (crc << 1) & 0xffff;
  }
  return crc & 0xffff;
}

function checksumCrc32(bytes, from, to) {
  let crc = 0xffffffff;
  for (let i = from; i < to; i += 1) crc = crc32Table[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function checksumSum(bytes, from, to, mod) {
  let total = 0;
  for (let i = from; i < to; i += 1) total = (total + bytes[i]) % mod;
  return total;
}

function checksumXor(bytes, from, to) {
  let value = 0;
  for (let i = from; i < to; i += 1) value ^= bytes[i];
  return value & 0xff;
}

function checksumWords(bytes, from, to, width, littleEndian) {
  const mod = width === 4 ? 0x100000000 : 0x10000;
  let total = 0;
  for (let i = from; i + width <= to; i += width) {
    let word = 0;
    if (littleEndian) {
      for (let j = width - 1; j >= 0; j -= 1) word = (word * 256) + bytes[i + j];
    } else {
      for (let j = 0; j < width; j += 1) word = (word * 256) + bytes[i + j];
    }
    total = (total + word) % mod;
  }
  return total;
}

function checksumCompute(id, bytes, from, to) {
  switch (id) {
    case 'sum8': return checksumSum(bytes, from, to, 0x100);
    case 'xor8': return checksumXor(bytes, from, to);
    case 'sum16bytes': return checksumSum(bytes, from, to, 0x10000);
    case 'sum16words_be': return checksumWords(bytes, from, to, 2, false);
    case 'sum16words_le': return checksumWords(bytes, from, to, 2, true);
    case 'sum32words_be': return checksumWords(bytes, from, to, 4, false);
    case 'crc16ccitt': return checksumCrc16(bytes, from, to, 0xffff);
    case 'crc16xmodem': return checksumCrc16(bytes, from, to, 0x0000);
    case 'crc32': return checksumCrc32(bytes, from, to);
    default: throw new Error(`Unknown algorithm "${id}".`);
  }
}

function checksumMask(width) {
  return width === 1 ? 0xff : (width === 2 ? 0xffff : 0xffffffff);
}

function readStored(bytes, offset, width, littleEndian) {
  let value = 0;
  if (littleEndian) {
    for (let j = width - 1; j >= 0; j -= 1) value = (value * 256) + bytes[offset + j];
  } else {
    for (let j = 0; j < width; j += 1) value = (value * 256) + bytes[offset + j];
  }
  return value >>> 0;
}

function writeStored(bytes, offset, width, littleEndian, value) {
  for (let j = 0; j < width; j += 1) {
    const shift = littleEndian ? j : width - 1 - j;
    bytes[offset + j] = Math.floor(value / (2 ** (8 * shift))) & 0xff;
  }
}

function checksumCandidateOffsets(length, storedOffset, dataStart) {
  const offsets = new Set();
  const add = (value) => {
    if (Number.isInteger(value) && value >= dataStart && value + 1 <= length) offsets.add(value);
  };
  if (Number.isInteger(storedOffset)) {
    add(storedOffset);
  } else {
    [length - 1, length - 2, length - 3, length - 4, length - 6, length - 8, length - 12, length - 16, length - 32]
      .forEach(add);
    [0, 4, 8, 12, 16, 0x1c, 0x20, 0x24, 0x40, 0x100].forEach(add);
  }
  return Array.from(offsets).sort((a, b) => b - a);
}

/**
 * Sweep the candidate offsets and report every arithmetic combination that
 * agrees with the bytes already stored in the image.
 */
function scanChecksums(bytes, options = {}) {
  if (!(bytes instanceof Uint8Array) || !bytes.length) throw new Error('Load a binary image first.');
  const dataStart = Math.max(0, Number(options.dataStart) || 0);
  if (dataStart >= bytes.length) throw new Error('The data start is past the end of the image.');
  const storedOffset = Number.isInteger(options.storedOffset) ? options.storedOffset : null;
  if (storedOffset !== null && (storedOffset < dataStart || storedOffset >= bytes.length)) {
    throw new Error('The checksum offset has to sit inside the image, after the data start.');
  }
  const offsets = checksumCandidateOffsets(bytes.length, storedOffset, dataStart);
  const matches = [];
  const perAlgorithm = {};
  CHECKSUM_ALGORITHMS.forEach((algorithm) => {
    perAlgorithm[algorithm.id] = 0;
    const width = algorithm.width;
    offsets.forEach((offset) => {
      if (offset <= dataStart || offset + width > bytes.length) return;
      const computed = checksumCompute(algorithm.id, bytes, dataStart, offset);
      [false, true].forEach((littleEndian) => {
        const stored = readStored(bytes, offset, width, littleEndian);
        const mask = checksumMask(width);
        if (stored === computed) {
          matches.push({
            algorithm: algorithm.id, algorithmLabel: algorithm.label, weak: Boolean(algorithm.weak),
            offset, width, littleEndian, stored, computed, dataStart, form: 'direct',
          });
          perAlgorithm[algorithm.id] += 1;
        } else if (complementMatch(stored, computed, mask)) {
          matches.push({
            algorithm: algorithm.id, algorithmLabel: algorithm.label, weak: Boolean(algorithm.weak),
            offset, width, littleEndian, stored, computed, dataStart, form: 'complement',
          });
          perAlgorithm[algorithm.id] += 1;
        }
      });
    });
  });
  const ranked = matches
    .map((match) => ({ ...match, confidence: matchConfidence(match, perAlgorithm) }))
    .sort((a, b) => b.confidence - a.confidence || b.width - a.width || a.offset - b.offset);
  return {
    matches: ranked,
    dataStart,
    length: bytes.length,
    offsets,
    perAlgorithm,
    storedOffset,
  };
}

function complementMatch(stored, computed, mask) {
  // A stored one's complement is a real convention; a zeroes/ones pair is not
  // evidence, so exclude the degenerate cases.
  if (computed === 0 || computed === mask) return false;
  return stored === ((computed ^ mask) >>> 0);
}

function matchConfidence(match, perAlgorithm) {
  let score = match.width * 10;
  if (match.form === 'direct') score += 4;
  if (!match.weak) score += 6;
  if (match.algorithm === 'crc32' || match.algorithm === 'crc16ccitt') score += 4;
  if (perAlgorithm[match.algorithm] === 1) score += 5;
  if (match.offset >= 16 && match.offset <= 0x100) score += 1;
  return score;
}

/** Write the computed value into a copy of the image, leaving `bytes` untouched. */
function repairChecksum(bytes, match) {
  if (!(bytes instanceof Uint8Array)) throw new Error('No image to repair.');
  if (!match || !Number.isInteger(match.offset)) throw new Error('Choose a matching row first.');
  const copy = new Uint8Array(bytes);
  const dataStart = Number.isInteger(match.dataStart) ? match.dataStart : 0;
  const computed = checksumCompute(match.algorithm, bytes, dataStart, match.offset);
  writeStored(copy, match.offset, match.width, match.littleEndian, computed);
  return { bytes: copy, computed, offset: match.offset, width: match.width };
}

async function sha256Hex(bytes) {
  if (!globalThis.crypto?.subtle) return 'unavailable';
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('');
}

if (typeof window !== 'undefined') {
  window.gobChecksumWorkbench = {
    algorithms: CHECKSUM_ALGORITHMS,
    families: CHECKSUM_FAMILIES,
    scanChecksums,
    repairChecksum,
    checksumCompute,
    readStored,
    writeStored,
    sha256Hex,
  };
}

/* ---- panel wiring ------------------------------------------------------- */

if (typeof document !== 'undefined') {
  const el = (id) => document.getElementById(id);
  const setText = (id, text) => { const node = el(id); if (node) node.textContent = text; };
  const setHtml = (id, html) => { const node = el(id); if (node) node.innerHTML = html; };
  const state = { bytes: null, name: '', scan: null };

  const hex = (value, width) => `0x${value.toString(16).toUpperCase().padStart(width * 2, '0')}`;
  const familiesHtml = () => '<details class="advanced"><summary>Families this program already knows</summary>'
    + '<div class="table-wrap"><table class="data"><thead><tr><th>Family</th><th>What the checksum covers</th></tr></thead><tbody>'
    + CHECKSUM_FAMILIES.map((row) => `<tr><td><b>${row.family}</b></td><td>${row.note}`
      + (row.tool ? ` <a href="#" data-cks-goto="${row.tool}">Open that tool</a>` : '') + '</td></tr>').join('')
    + '</tbody></table></div><p class="muted small">A match below is arithmetic on your file. It does not show the '
    + 'image is complete, that it belongs to a particular ECU, or that it is safe to flash.</p></details>';

  const scanBtn = el('cksScanBtn');
  if (scanBtn) {
    scanBtn.onclick = async () => {
      setHtml('cksOut', '');
      setHtml('cksDetail', '');
      setText('cksMeta', '');
      try {
        const file = el('cksFile').files?.[0];
        if (!file) throw new Error('Choose a local binary image.');
        if (file.size > 16 * 1024 * 1024) throw new Error('Images above 16 MiB are not swept.');
        state.bytes = new Uint8Array(await file.arrayBuffer());
        state.name = file.name;
        const startText = String(el('cksStart').value || '0').trim();
        const dataStart = /^0x/i.test(startText) ? parseInt(startText, 16) : parseInt(startText, 10);
        if (!Number.isInteger(dataStart) || dataStart < 0) throw new Error('Data start must be a byte offset.');
        const storedText = String(el('cksStored').value || '').trim();
        const storedOffset = storedText ? (/^0x/i.test(storedText) ? parseInt(storedText, 16) : parseInt(storedText, 10)) : null;
        if (storedText && !Number.isInteger(storedOffset)) throw new Error('Checksum offset must be a byte offset.');
        const scan = scanChecksums(state.bytes, { dataStart, storedOffset });
        state.scan = scan;
        const usable = scan.matches.filter((match) => !match.weak);
        setHtml('cksOut', familiesHtml()
          + (scan.matches.length
            ? `<div class="table-wrap"><table class="data"><thead><tr><th>Algorithm</th><th>Stored at</th><th>Width</th>`
              + `<th>Byte order</th><th>Stored</th><th>Computed</th><th>Form</th><th></th></tr></thead><tbody>`
              + scan.matches.slice(0, 24).map((match, index) => `<tr><td>${match.algorithmLabel}${match.weak ? ' <em>(weak)</em>' : ''}</td>`
                + `<td>${hex(match.offset, 4)}</td><td>${match.width}</td>`
                + `<td>${match.littleEndian ? 'little' : 'big'}</td>`
                + `<td>${hex(match.stored, match.width)}</td><td>${hex(match.computed, match.width)}</td>`
                + `<td>${match.form === 'complement' ? 'one\u2019s complement' : 'direct'}</td>`
                + `<td><button class="btn" data-cks-row="${index}">Repair a copy</button></td></tr>`).join('')
              + '</tbody></table></div>'
              + `<p class="muted small">${scan.matches.length} arithmetic match(es) across ${scan.offsets.length} candidate position(s)`
              + `${usable.length ? '' : ' — only weak 8-bit matches, which happen by chance'}. `
              + 'A one\u2019s complement row means the file stores the inverse of the computed value.</p>'
            : '<p class="tip warn"><b>No match.</b> The checksum may use an algorithm or region this workbench does not '
              + 'know, it may sit outside the swept positions, or the image may genuinely be damaged. Set the data start '
              + 'or the exact checksum position and try again.</p>'));
        setText('cksMeta', `${state.name} · ${state.bytes.length} byte(s) · data from ${hex(dataStart, 4)}`
          + ` · ${scan.matches.length} match(es)`);
        el('cksClear').disabled = false;
      } catch (error) {
        setText('cksMeta', `Not scanned: ${error.message}`);
      }
    };
  }

  document.addEventListener('click', async (event) => {
    const rowButton = event.target.closest?.('[data-cks-row]');
    if (rowButton && state.bytes && state.scan) {
      const match = state.scan.matches[Number(rowButton.dataset.cksRow)];
      if (!match) return;
      try {
        const before = await sha256Hex(state.bytes);
        const repaired = repairChecksum(state.bytes, match);
        const after = await sha256Hex(repaired.bytes);
        const blob = new Blob([repaired.bytes], { type: 'application/octet-stream' });
        const url = URL.createObjectURL(blob);
        setHtml('cksDetail', `<div class="kv">`
          + `<div><span>Original SHA-256</span><code>${before}</code></div>`
          + `<div><span>Repaired SHA-256</span><code>${after}</code></div>`
          + `<div><span>Word written</span><b>${hex(repaired.computed, match.width)} at ${hex(match.offset, 4)}</b></div>`
          + `<div><span>Saved as</span><b>${state.name.replace(/\.[^.]+$/, '')}.repaired.bin</b></div>`
          + `</div><div class="toolbar"><a class="btn primary" download="${state.name.replace(/\.[^.]+$/, '')}.repaired.bin" href="${url}">Download repaired copy</a>`
          + `<span class="muted small">The original file on disk was not modified.</span></div>`
          + '<p class="tip warn"><b>A matching checksum is not flash approval.</b> A repaired copy still needs the '
          + 'verified backup, base-map check and operator confirmation the programming view requires.</p>');
      } catch (error) {
        setHtml('cksDetail', `<p class="tip warn">Not repaired: ${error.message}</p>`);
      }
      return;
    }
    const jump = event.target.closest?.('[data-cks-goto]');
    if (jump) {
      event.preventDefault();
      const target = document.querySelector(jump.dataset.cksGoto);
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        target.classList.add('help-focus-ring');
        setTimeout(() => target.classList.remove('help-focus-ring'), 2200);
      }
    }
  });

  const clear = el('cksClear');
  if (clear) {
    clear.onclick = () => {
      state.bytes = null;
      state.scan = null;
      el('cksFile').value = '';
      el('cksStored').value = '';
      setHtml('cksOut', '');
      setHtml('cksDetail', '');
      setText('cksMeta', '');
      clear.disabled = true;
    };
  }
}
