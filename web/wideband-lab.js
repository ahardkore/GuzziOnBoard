/* Wideband transfer-function lab.
 *
 * Curves are the controllers' published analog-output defaults:
 *  - Innovate LC-2 / MTX-L: 0 V = 7.35 AFR, 5 V = 22.39 AFR (LC-2 manual, 11-0137C).
 *  - Zeitronix ZT-2: AFR = 2 x V + 9.6 (ZT-2 instructions; output range 9.5-21 AFR).
 *  - AEM X-series 30-0300: AFR = 2.3750 x V + 7.3125, valid 0.5-4.5 V; below 0.5 V the
 *    controller reports "sensor not ready", above 4.5 V "sensor error" (30-0300 manual).
 * A curve is only as good as the unit it was programmed with: every field here is editable.
 */
'use strict';

const WIDEBAND_CURVES = {
  innovate_lc2: {
    label: 'Innovate LC-2 / MTX-L',
    source: 'LC-2 manual 11-0137C: analog output 1, 0 V = 7.35 AFR, 5 V = 22.39 AFR.',
    voltLow: 0, voltHigh: 5, afrLow: 7.35, afrHigh: 22.39,
    validLow: 0, validHigh: 5, notReady: null, error: null,
  },
  zeitronix_zt2: {
    label: 'Zeitronix ZT-2',
    source: 'ZT-2 instructions: linear wideband output AFR = 2 x V + 9.6 (9.5-21 AFR range).',
    voltLow: 0, voltHigh: 5, afrLow: 9.6, afrHigh: 19.6,
    validLow: 0, validHigh: 5, notReady: null, error: null,
  },
  aem_xseries: {
    label: 'AEM X-series 30-0300',
    source: '30-0300 manual: AFR = 2.3750 x V + 7.3125, valid 0.5-4.5 V.',
    voltLow: 0.5, voltHigh: 4.5, afrLow: 8.5, afrHigh: 18.0,
    validLow: 0.5, validHigh: 4.5, notReady: 0.5, error: 4.5,
  },
  custom: {
    label: 'Custom two-point',
    source: 'Endpoints supplied by the operator.',
    voltLow: 0, voltHigh: 5, afrLow: 9.0, afrHigh: 20.0,
    validLow: 0, validHigh: 5, notReady: null, error: null,
  },
};

const WIDEBAND_FUELS = {
  14.7: 'Petrol / E0',
  14.1: 'E10',
  9.8: 'E85',
  6.5: 'Methanol',
  14.5: 'Diesel',
};

function widebandCurve(preset, overrides = {}) {
  const base = WIDEBAND_CURVES[preset];
  if (!base) throw new Error(`Unknown wideband preset "${preset}".`);
  return { ...base, ...overrides, id: preset };
}

function voltsToAfr(preset, volts, options = {}) {
  const curve = widebandCurve(preset, options.curve);
  const stoich = Number(options.stoich || 14.7);
  if (!Number.isFinite(volts)) throw new Error('Voltage must be a number.');
  if (!Number.isFinite(stoich) || stoich <= 0) throw new Error('Stoichiometric ratio must be positive.');
  let status = 'ok';
  if (curve.notReady !== null && volts < curve.notReady) status = 'not ready';
  else if (curve.error !== null && volts > curve.error) status = 'sensor error';
  else if (volts < 0 || volts > 5) status = 'outside 0-5 V';
  const span = curve.afrHigh - curve.afrLow;
  const slope = span / (curve.voltHigh - curve.voltLow);
  const afr = curve.afrLow + (volts - curve.voltLow) * slope;
  return {
    volts,
    status,
    afr: status === 'ok' ? afr : null,
    lambda: status === 'ok' ? afr / stoich : null,
    stoich,
    curve: curve.id,
  };
}

function widebandNumbers(line) {
  const matches = String(line).match(/-?\d+(?:[.,]\d+)?/g);
  if (!matches) return [];
  return matches.map((token) => Number(token.replace(',', '.')));
}

/** Convert a pasted column/list of voltages. Returns samples plus a summary. */
function convertVoltages(text, options = {}) {
  const preset = options.preset || 'innovate_lc2';
  const hasTime = Boolean(options.hasTime);
  const stoich = Number(options.stoich || 14.7);
  const curve = widebandCurve(preset, options.curve);
  const samples = [];
  const rejected = [];
  String(text || '').split(/\r?\n/).forEach((line, index) => {
    const trimmed = line.trim();
    if (!trimmed || /^[a-z#]/i.test(trimmed)) return;
    const numbers = widebandNumbers(trimmed);
    if (!numbers.length) {
      rejected.push({ line: index + 1, text: trimmed, why: 'no number' });
      return;
    }
    const volts = hasTime ? numbers[1] : numbers[0];
    if (!Number.isFinite(volts)) {
      rejected.push({ line: index + 1, text: trimmed, why: 'no voltage column' });
      return;
    }
    const time = hasTime ? numbers[0] : null;
    try {
      samples.push({ time, ...voltsToAfr(preset, volts, { stoich, curve }) });
    } catch (error) {
      rejected.push({ line: index + 1, text: trimmed, why: error.message });
    }
  });
  const good = samples.filter((sample) => sample.status === 'ok');
  const summary = good.length ? {
    count: good.length,
    minAfr: Math.min(...good.map((s) => s.afr)),
    maxAfr: Math.max(...good.map((s) => s.afr)),
    meanAfr: good.reduce((a, s) => a + s.afr, 0) / good.length,
    meanLambda: good.reduce((a, s) => a + s.lambda, 0) / good.length,
  } : { count: 0, minAfr: null, maxAfr: null, meanAfr: null, meanLambda: null };
  return {
    samples,
    rejected,
    summary,
    stoich,
    curve,
    unusable: samples.filter((sample) => sample.status !== 'ok').length,
  };
}

function widebandCsv(result) {
  const lines = ['time_s,volts,afr,lambda,status'];
  result.samples.forEach((sample) => {
    lines.push([
      sample.time === null ? '' : sample.time,
      sample.volts,
      sample.afr === null ? '' : sample.afr.toFixed(3),
      sample.lambda === null ? '' : sample.lambda.toFixed(4),
      sample.status,
    ].join(','));
  });
  return lines.join('\n');
}

/** What a two-point correction would do to a log: scale and offset from one reference. */
function compareCalibration(measured, actual) {
  const m = Number(measured), a = Number(actual);
  if (!Number.isFinite(m) || !Number.isFinite(a)) throw new Error('Both readings must be numbers.');
  if (m <= 0 || a <= 0) throw new Error('Readings must be positive.');
  const scale = a / m;
  return {
    measured: m,
    actual: a,
    scale,
    errorPct: (m - a) / a * 100,
    deltaAtStoich: (14.7 * scale) - 14.7,
    direction: scale < 1 ? 'the log reads lean of the reference' : (scale > 1 ? 'the log reads rich of the reference' : 'no correction needed'),
  };
}

if (typeof window !== 'undefined') {
  window.gobWidebandLab = {
    curves: WIDEBAND_CURVES,
    fuels: WIDEBAND_FUELS,
    voltsToAfr,
    convertVoltages,
    widebandCsv,
    compareCalibration,
  };
}

/* ---- panel wiring ------------------------------------------------------- */

if (typeof document !== 'undefined') {
  const el = (id) => document.getElementById(id);
  const preset = () => el('wbPreset')?.value || 'innovate_lc2';
  const customCurve = () => ({
    afrLow: Number(el('wbAfrLow')?.value || 9),
    afrHigh: Number(el('wbAfrHigh')?.value || 20),
  });
  const curveOptions = () => (preset() === 'custom' ? { curve: customCurve() } : {});
  const setText = (id, text) => { const node = el(id); if (node) node.textContent = text; };
  const setHtml = (id, html) => { const node = el(id); if (node) node.innerHTML = html; };

  const presetSelect = el('wbPreset');
  if (presetSelect) {
    const sync = () => {
      el('wbCustom').classList.toggle('hidden', preset() !== 'custom');
      const curve = WIDEBAND_CURVES[preset()];
      setText('wbMeta', `${curve.label} · ${curve.voltLow}-${curve.voltHigh} V → ${curve.afrLow}-${curve.afrHigh} AFR`);
    };
    presetSelect.addEventListener('change', sync);
    sync();
  }

  const convert = el('wbConvertBtn');
  if (convert) {
    convert.onclick = () => {
      setHtml('wbOut', '');
      setText('wbMeta', '');
      try {
        const result = convertVoltages(el('wbIn').value, {
          preset: preset(),
          hasTime: el('wbHasTime').checked,
          stoich: Number(el('wbFuel').value || 14.7),
          ...curveOptions(),
        });
        if (!result.samples.length) {
          setText('wbMeta', 'Nothing numeric to convert.');
          return;
        }
        const rows = result.samples.slice(0, 40).map((sample) => `<tr><td>${sample.time === null ? '' : sample.time}</td>`
          + `<td>${sample.volts.toFixed(3)}</td>`
          + `<td>${sample.afr === null ? '&mdash;' : sample.afr.toFixed(2)}</td>`
          + `<td>${sample.lambda === null ? '&mdash;' : sample.lambda.toFixed(3)}</td>`
          + `<td>${sample.status}</td></tr>`).join('');
        setHtml('wbOut', `<div class="table-wrap"><table class="data"><thead><tr><th>Time</th><th>Volts</th>`
          + `<th>AFR</th><th>&lambda;</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table></div>`
          + (result.samples.length > 40 ? `<p class="muted small">Showing the first 40 of ${result.samples.length} samples.</p>` : '')
          + `<p class="muted small">${result.rejected.length} line(s) ignored.</p>`
          + `<details><summary class="small">CSV for the whole log</summary><textarea class="mono-out" rows="6" readonly>${widebandCsv(result)}</textarea></details>`);
        const s = result.summary;
        setText('wbMeta', `${s.count} sample(s) · AFR ${s.minAfr === null ? '—' : s.minAfr.toFixed(2)}–${s.maxAfr.toFixed(2)}`
          + ` · mean ${s.meanAfr === null ? '—' : s.meanAfr.toFixed(2)} AFR / λ ${s.meanLambda === null ? '—' : s.meanLambda.toFixed(3)}`
          + (result.unusable ? ` · ${result.unusable} unusable` : ''));
      } catch (error) {
        setText('wbMeta', `Not converted: ${error.message}`);
      }
    };
  }

  const cal = el('wbCalBtn');
  if (cal) {
    cal.onclick = () => {
      setText('wbCalOut', '');
      try {
        const result = compareCalibration(el('wbCalMeasured').value, el('wbCalActual').value);
        setText('wbCalOut', `scale ×${result.scale.toFixed(4)} · ${result.errorPct.toFixed(2)}% · `
          + `${result.direction} · ${result.deltaAtStoich >= 0 ? '+' : ''}${result.deltaAtStoich.toFixed(2)} AFR at λ 1`);
      } catch (error) {
        setText('wbCalOut', `Not compared: ${error.message}`);
      }
    };
  }

  const clear = el('wbClear');
  if (clear) {
    clear.onclick = () => {
      el('wbIn').value = '';
      setHtml('wbOut', '');
      setText('wbMeta', '');
      setText('wbCalOut', '');
    };
  }
}
