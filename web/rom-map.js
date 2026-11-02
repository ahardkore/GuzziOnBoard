/* ROM region and entropy map.
 *
 * A sliding-window Shannon entropy strip, a merged region table and a two-image
 * diff. The technique is the one binwalk and every "where do the tables start"
 * write-up describes; this file computes it locally on bytes the operator chose
 * and sends nothing anywhere. Entropy tells you what kind of data a region
 * holds, never which table it is — an XDF still has to make that claim.
 */
'use strict';

const ROM_KINDS = {
  blank: { label: 'padding / blank', className: 'rom-blank', note: 'a repeated fill byte' },
  code: { label: 'code or compressed', className: 'rom-code', note: 'high entropy, little repetition' },
  data: { label: 'table-like data', className: 'rom-data', note: 'structured, mid entropy' },
  sparse: { label: 'sparse / low entropy', className: 'rom-sparse', note: 'few distinct values' },
};

function romEntropy(bytes, windowSize = 256, maxWindows = 4096) {
  if (!(bytes instanceof Uint8Array) || !bytes.length) throw new Error('Load a binary image first.');
  const size = Math.max(16, Math.min(65536, Number(windowSize) || 256));
  const stride = Math.max(size, Math.ceil(bytes.length / maxWindows));
  const windows = [];
  for (let offset = 0; offset < bytes.length; offset += stride) {
    const end = Math.min(bytes.length, offset + size);
    const counts = new Uint32Array(256);
    for (let i = offset; i < end; i += 1) counts[bytes[i]] += 1;
    let dominant = 0;
    for (let i = 0; i < 256; i += 1) if (counts[i] > counts[dominant]) dominant = i;
    const fill = counts[dominant] / (end - offset);
    let entropy = 0;
    for (let i = 0; i < 256; i += 1) {
      if (!counts[i]) continue;
      const p = counts[i] / (end - offset);
      entropy -= p * Math.log2(p);
    }
    windows.push({
      offset,
      end,
      length: end - offset,
      entropy,
      fill,
      dominant,
      distinct: counts.reduce((count, n) => count + (n ? 1 : 0), 0),
    });
  }
  windows.forEach((window) => {
    if (window.fill >= 0.98) window.kind = 'blank';
    else if (window.entropy >= 7.2) window.kind = 'code';
    else if (window.entropy >= 3.5) window.kind = 'data';
    else window.kind = 'sparse';
  });
  return { windows, windowSize: size, stride, length: bytes.length };
}

function romRegions(profile, minWindows = 2) {
  const windows = profile?.windows || [];
  const regions = [];
  let current = null;
  windows.forEach((window) => {
    if (current && current.kind === window.kind) {
      current.end = window.end;
      current.windows += 1;
      current.entropySum += window.entropy;
      current.fillMax = Math.max(current.fillMax, window.fill);
      return;
    }
    if (current) regions.push(current);
    current = {
      kind: window.kind,
      start: window.offset,
      end: window.end,
      windows: 1,
      entropySum: window.entropy,
      fillMax: window.fill,
      dominant: window.dominant,
    };
  });
  if (current) regions.push(current);
  return regions
    .filter((region) => region.windows >= minWindows)
    .map((region) => ({
      kind: region.kind,
      label: ROM_KINDS[region.kind].label,
      className: ROM_KINDS[region.kind].className,
      start: region.start,
      end: region.end,
      size: region.end - region.start,
      meanEntropy: region.entropySum / region.windows,
      fillRatio: region.fillMax,
      dominantByte: region.dominant,
    }));
}

function romDiff(first, second) {
  if (!(first instanceof Uint8Array) || !(second instanceof Uint8Array)) throw new Error('Two images are needed to compare.');
  const limit = Math.min(first.length, second.length);
  const runs = [];
  let open = null;
  for (let i = 0; i < limit; i += 1) {
    if (first[i] === second[i]) {
      if (open) {
        runs.push(open);
        open = null;
      }
      continue;
    }
    if (!open) open = { start: i, end: i + 1, bytes: 1 };
    else {
      open.end = i + 1;
      open.bytes += 1;
    }
  }
  if (open) runs.push(open);
  return {
    sameSize: first.length === second.length,
    lengths: [first.length, second.length],
    tailBytes: Math.abs(first.length - second.length),
    changedBytes: runs.reduce((total, run) => total + run.bytes, 0),
    changedRuns: runs,
    identical: runs.length === 0 && first.length === second.length,
  };
}

function romStripSvg(profile, width = 1000, height = 64) {
  const windows = profile?.windows || [];
  if (!windows.length) return '';
  const barWidth = Math.max(0.5, width / windows.length);
  const bands = windows.map((window) => {
    const ratio = Math.min(1, window.entropy / 8);
    const y = height - Math.max(2, ratio * height);
    return `<rect x="${(window.offset / profile.stride * barWidth).toFixed(2)}" y="${y.toFixed(2)}"`
      + ` width="${Math.max(barWidth, 0.6).toFixed(2)}" height="${(height - y).toFixed(2)}"`
      + ` class="${ROM_KINDS[window.kind].className}"><title>0x${window.offset.toString(16).toUpperCase()}`
      + ` · entropy ${window.entropy.toFixed(2)} · fill ${(window.fill * 100).toFixed(0)}%</title></rect>`;
  }).join('');
  return `<svg class="rom-strip" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img"`
    + ` aria-label="entropy strip: ${windows.length} windows">${bands}</svg>`;
}

if (typeof window !== 'undefined') {
  window.gobRomMap = { romEntropy, romRegions, romDiff, romStripSvg, kinds: ROM_KINDS };
}

/* ---- panel wiring ------------------------------------------------------- */

if (typeof document !== 'undefined') {
  const el = (id) => document.getElementById(id);
  const setText = (id, text) => { const node = el(id); if (node) node.textContent = text; };
  const setHtml = (id, html) => { const node = el(id); if (node) node.innerHTML = html; };
  const hex = (value) => `0x${value.toString(16).toUpperCase()}`;
  const size = (bytes) => (bytes >= 1024 ? `${(bytes / 1024).toFixed(bytes >= 10240 ? 0 : 1)} KiB` : `${bytes} B`);

  const mapBtn = el('romMapBtn');
  if (mapBtn) {
    mapBtn.onclick = async () => {
      setHtml('romStrip', '');
      setHtml('romOut', '');
      setHtml('romDiff', '');
      setText('romMeta', '');
      try {
        const file = el('romFile').files?.[0];
        if (!file) throw new Error('Choose a local binary image.');
        if (file.size > 16 * 1024 * 1024) throw new Error('Images above 16 MiB are not mapped.');
        const bytes = new Uint8Array(await file.arrayBuffer());
        const profile = romEntropy(bytes, Number(el('romWindow').value));
        const regions = romRegions(profile);
        setHtml('romStrip', romStripSvg(profile) + '<p class="muted small">Height is Shannon entropy per window; '
          + 'flat runs are padding, tall runs are code or compressed data, mid-height plateaus are usually tables. '
          + 'Hover a band for its offset.</p>');
        setHtml('romOut', regions.length
          ? `<div class="table-wrap"><table class="data"><thead><tr><th>Region</th><th>Start</th><th>End</th><th>Size</th>`
            + `<th>Entropy</th><th>Fill</th><th>Dominant byte</th></tr></thead><tbody>`
            + regions.map((region) => `<tr><td>${region.label}</td><td>${hex(region.start)}</td><td>${hex(region.end)}</td>`
              + `<td>${size(region.size)}</td><td>${region.meanEntropy.toFixed(2)}</td>`
              + `<td>${(region.fillRatio * 100).toFixed(0)}%</td><td>${hex(region.dominantByte)}</td></tr>`).join('')
            + '</tbody></table></div>'
          : '<p class="muted small">The image is too uniform to split into regions at this window size.</p>');
        setText('romMeta', `${file.name} · ${size(bytes.length)} · ${profile.windows.length} window(s) of ${profile.windowSize} B`
          + ` · ${regions.length} region(s)`);
        el('romClear').disabled = false;

        const second = el('romFileB').files?.[0];
        if (second) {
          const other = new Uint8Array(await second.arrayBuffer());
          const diff = romDiff(bytes, other);
          const runs = diff.changedRuns.slice(0, 20);
          setHtml('romDiff', `<h3>Comparison with ${second.name}</h3>`
            + `<p class="small">${diff.identical
              ? 'The two images are byte-identical.'
              : `${diff.changedBytes} byte(s) differ in ${diff.changedRuns.length} run(s)`
                + `${diff.sameSize ? '' : ` · sizes ${size(diff.lengths[0])} vs ${size(diff.lengths[1])}`}.`}</p>`
            + (runs.length ? `<div class="table-wrap"><table class="data"><thead><tr><th>Start</th><th>End</th>`
              + '<th>Length</th></tr></thead><tbody>'
              + runs.map((run) => `<tr><td>${hex(run.start)}</td><td>${hex(run.end)}</td><td>${run.bytes} B</td></tr>`).join('')
              + '</tbody></table></div>' : '')
            + (diff.changedRuns.length > runs.length
              ? `<p class="muted small">Showing the first ${runs.length} of ${diff.changedRuns.length} changed runs.</p>` : '')
            + '<p class="muted small">A changed run is not an edited table: the checksum word, the header and every '
            + 'axis moved by the same edit all appear here.</p>');
        }
      } catch (error) {
        setText('romMeta', `Not mapped: ${error.message}`);
      }
    };
  }

  const clear = el('romClear');
  if (clear) {
    clear.onclick = () => {
      el('romFile').value = '';
      el('romFileB').value = '';
      setHtml('romStrip', '');
      setHtml('romOut', '');
      setHtml('romDiff', '');
      setText('romMeta', '');
      clear.disabled = true;
    };
  }
}
