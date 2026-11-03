/* Driveline and speedometer arithmetic: what a sprocket, tyre or sensor change
 * actually does to the number on the dash.
 *
 * Three questions get confused with each other, so this file keeps them apart
 * and names each one:
 *
 *   1. PERFORMANCE — "at the same engine rpm, how much faster (or slower) does
 *      the bike go?" That is the driveline factor times the tyre factor, and it
 *      does not depend on where the speed sensor reads.
 *
 *   2. INDICATION — "at the same true road speed, what does the speedometer
 *      show now?" This DOES depend on where the sensor reads, and getting it
 *      wrong is how people buy the wrong speedo-healer setting:
 *        - sensor on the wheel (front wheel, or a rear-wheel speed ring):
 *          gearing changes do nothing to the reading; a bigger tyre makes it
 *          under-read.
 *        - sensor on the gearbox output (most shaft-drive and many ABS-less
 *          bikes): the gearing ratio is part of the calibration, so a sprocket
 *          change moves the reading too.
 *
 *   3. CORRECTION — "I measured 100 km/h indicated against 92 km/h on GPS.
 *      What factor do I put into the corrector?" That is a plain ratio,
 *      actual ÷ indicated, and it is the only one of the three that comes from
 *      a measurement rather than from arithmetic.
 *
 * Every function is pure and takes plain numbers or tyre markings. Nothing here
 * reads the DOM, the network or the vehicle.
 */
'use strict';

/** Rolling circumference in metres from a marking like 180/55-17 or 170/60 ZR17. */
function speedoCircumference(marking) {
  const text = String(marking || '').trim();
  const parts = text.split('/');
  if (parts.length < 2) throw new Error(`Cannot parse tyre marking "${text}" — use the form 180/55-17.`);
  const rest = parts[1].replace(/ZR/ig, '-').replace(/R/ig, '-').split('-');
  const width = parseFloat(parts[0]);
  const aspect = parseFloat(rest[0]);
  const rim = parseFloat(rest[1]);
  if (!Number.isFinite(width) || !Number.isFinite(aspect) || !Number.isFinite(rim)) {
    throw new Error(`Cannot parse tyre marking "${text}" — use the form 180/55-17.`);
  }
  if (width <= 0 || aspect <= 0 || rim <= 0) throw new Error('A tyre marking cannot have a zero or negative part.');
  const sidewall = (width * aspect) / 100;
  return (Math.PI * (rim * 25.4 + 2 * sidewall)) / 1000;
}

/** Final-drive ratio as a chain sees it: rear teeth ÷ front teeth. */
function speedoDriveRatio(front, rear) {
  const f = Number(front);
  const r = Number(rear);
  if (!(f > 0) || !(r > 0)) throw new Error('Sprocket tooth counts must be above zero.');
  return r / f;
}

/**
 * Speed multiplier at the same engine rpm for a sprocket change.
 * Shorter gearing (bigger rear or smaller front) returns a factor below 1:
 * the bike goes slower at the same rpm and pulls harder.
 */
function drivelineFactor({ frontFrom = 15, frontTo = 15, rearFrom = 45, rearTo = 45 } = {}) {
  const before = speedoDriveRatio(frontFrom, rearFrom);
  const after = speedoDriveRatio(frontTo, rearTo);
  const factor = before / after;
  return {
    ratioFrom: before,
    ratioTo: after,
    factor,
    percent: (factor - 1) * 100,
    taller: factor > 1,
  };
}

/**
 * Speed multiplier at the same engine rpm for a tyre change: a larger rolling
 * circumference covers more ground per wheel revolution.
 *
 * Accepts markings or already-measured circumferences in metres, because a worn
 * or a measured tyre is more honest than a nominal one.
 */
function tyreFactor(from, to) {
  const before = typeof from === 'number' ? from : speedoCircumference(from);
  const after = typeof to === 'number' ? to : speedoCircumference(to);
  if (!(before > 0) || !(after > 0)) throw new Error('Rolling circumference must be above zero.');
  const factor = after / before;
  return {
    circumferenceFrom: before,
    circumferenceTo: after,
    factor,
    percent: (factor - 1) * 100,
    growthMm: (after - before) * 1000,
  };
}

/**
 * Indicated-speed multiplier at the same true road speed.
 *
 * `sensor` is where the speed signal is taken from:
 *   'wheel'   — wheel speed; gearing does not affect the reading
 *   'gearbox' — gearbox output; the final-drive ratio is part of the calibration
 */
function indicationFactor({ drive = null, tyre = null, sensor = 'wheel' } = {}) {
  if (!['wheel', 'gearbox'].includes(sensor)) throw new Error(`Unknown speed sensor location "${sensor}".`);
  const driveFactor = drive ? drive.factor : 1;
  const tyreSpeed = tyre ? tyre.factor : 1;
  // A bigger tyre turns fewer times for the same road speed, so any sensor that
  // counts revolutions reads lower: hence the reciprocal.
  const wheelReads = 1 / tyreSpeed;
  const factor = sensor === 'gearbox' ? wheelReads * (1 / driveFactor) : wheelReads;
  return { factor, percent: (factor - 1) * 100, sensor };
}

/** Error of an indicated reading against a trusted one (GPS, timed distance). */
function speedoError({ indicated, actual, unit = 'km/h' } = {}) {
  const shown = Number(indicated);
  const truth = Number(actual);
  if (!(shown > 0)) throw new Error('Indicated speed must be above zero.');
  if (!(truth > 0)) throw new Error('Actual speed must be above zero.');
  const ratio = truth / shown;
  return {
    indicated: shown,
    actual: truth,
    unit,
    errorPercent: ((shown - truth) / truth) * 100,
    // What a corrector multiplies the sensor signal by, and the percentage
    // setting most healer boxes expect.
    correctionFactor: ratio,
    correctionPercent: (ratio - 1) * 100,
    overReads: shown > truth,
    // The reading a corrected speedometer would show for this true speed.
    correctedReading: shown * ratio,
  };
}

/**
 * One report combining the three questions.
 *
 * `indicated`/`actual` are optional: without a measurement the panel reports
 * what the hardware changes do, and says that no measurement was supplied.
 */
function speedoReport(options = {}) {
  const {
    frontFrom = 15, frontTo = 15, rearFrom = 45, rearTo = 45,
    tyreFrom = null, tyreTo = null, sensor = 'wheel',
    indicated = null, actual = null, unit = 'km/h',
  } = options;
  const drive = drivelineFactor({ frontFrom, frontTo, rearFrom, rearTo });
  const tyre = tyreFrom && tyreTo ? tyreFactor(tyreFrom, tyreTo) : null;
  const indication = indicationFactor({ drive, tyre, sensor });
  const speedFactor = drive.factor * (tyre ? tyre.factor : 1);
  const error = indicated && actual ? speedoError({ indicated, actual, unit }) : null;
  const driveChanged = Math.abs(drive.percent) > 1e-9;
  const tyreChanged = Boolean(tyre && Math.abs(tyre.percent) > 1e-9);
  return {
    drive,
    tyre,
    indication,
    sensor,
    // Speed at the same engine rpm: the performance question.
    speed: { factor: speedFactor, percent: (speedFactor - 1) * 100 },
    error,
    changed: driveChanged || tyreChanged,
    // Combined correction a corrector box needs if the hardware changes are the
    // only source of error: measured factor, then the hardware's own factor.
    suggestedFactor: indication.factor * (error ? error.correctionFactor : 1),
  };
}

if (typeof window !== 'undefined') {
  window.gobSpeedo = {
    speedoCircumference,
    speedoDriveRatio,
    drivelineFactor,
    tyreFactor,
    indicationFactor,
    speedoError,
    speedoReport,
  };
}

/* ---- panel wiring (the gearing panel's speedometer section) ------------- */

if (typeof document !== 'undefined') {
  const el = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
  const fixed = (value, digits = 2) => (Number.isFinite(value) ? value.toFixed(digits) : '—');
  const signed = (value, digits = 2) => (Number.isFinite(value)
    ? `${value > 0 ? '+' : ''}${value.toFixed(digits)}` : '—');
  const kv = (rows) => `<div class="kv">${rows.map(([label, value]) => (
    `<div><span>${esc(label)}</span><b>${value}</b></div>`
  )).join('')}</div>`;
  const numberOrNull = (id) => {
    const node = el(id);
    if (!node || String(node.value).trim() === '') return null;
    const value = Number(node.value);
    return Number.isFinite(value) ? value : null;
  };

  function render() {
    const out = el('spdOut');
    const meta = el('spdMeta');
    if (!out) return;
    try {
      const tyreToText = String(el('spdTyreTo')?.value || '').trim();
      const tyreFromText = String(el('spdTyreFrom')?.value || '').trim();
      const indicated = numberOrNull('spdIndicated');
      const actual = numberOrNull('spdActual');
      const report = speedoReport({
        frontFrom: numberOrNull('spdFrontFrom') ?? 15,
        frontTo: numberOrNull('spdFrontTo') ?? 15,
        rearFrom: numberOrNull('spdRearFrom') ?? 45,
        rearTo: numberOrNull('spdRearTo') ?? 45,
        tyreFrom: tyreFromText || null,
        tyreTo: tyreToText || null,
        sensor: String(el('spdSensor')?.value || 'wheel'),
        indicated,
        actual,
      });

      let html = kv([
        ['Final drive ratio', `${fixed(report.drive.ratioFrom, 3)} → ${fixed(report.drive.ratioTo, 3)}`
          + ` (${signed(report.drive.percent, 2)} %)`],
        ['Tyre', report.tyre
          ? `${fixed(report.tyre.circumferenceFrom, 3)} → ${fixed(report.tyre.circumferenceTo, 3)} m`
            + ` (${signed(report.tyre.percent, 2)} %, ${signed(report.tyre.growthMm, 0)} mm)`
          : 'unchanged'],
        ['Speed at the same rpm', `<b>${signed(report.speed.percent, 2)} %</b>`
          + (report.speed.percent > 0 ? ' — taller, slower to rev' : report.speed.percent < 0 ? ' — shorter, pulls harder' : '')],
        ['Dash reads, same true speed', `<b>${signed(report.indication.percent, 2)} %</b>`
          + (report.sensor === 'wheel' ? ' — the sensor counts wheel revolutions' : ' — the sensor counts gearbox output')],
      ]);

      if (report.error) {
        const e = report.error;
        html += kv([
          ['Measured error', `${signed(e.errorPercent, 1)} % (${e.overReads ? 'over-reads' : 'under-reads'})`],
          ['Corrector factor', `${fixed(e.correctionFactor, 4)} × · setting ${signed(e.correctionPercent, 1)} %`],
          ['Reading after correction', `${fixed(e.correctedReading, 1)} ${esc(e.unit)} for ${e.actual} true`],
          ['With these hardware changes', `${fixed(report.suggestedFactor, 4)} × combined`],
        ]);
      } else {
        html += '<p class="muted small">Type an indicated speed and a trusted (GPS or timed) speed to get the '
          + 'correction factor. Without a measurement this panel only says what the hardware change does.</p>';
      }

      if (!report.changed) {
        html += '<p class="muted small">Nothing has changed yet: both sprockets and the tyre are the same '
          + 'before and after, so every factor below is 1.000.</p>';
      }

      out.innerHTML = html;
      if (meta) {
        meta.textContent = report.changed
          ? `${report.sensor === 'wheel' ? 'wheel speed sensor' : 'gearbox speed sensor'} · `
            + `speed ${signed(report.speed.percent, 2)} % · dash ${signed(report.indication.percent, 2)} %`
          : 'no change entered';
      }
    } catch (error) {
      out.innerHTML = '';
      if (meta) meta.textContent = `Not calculated: ${error.message}`;
    }
  }

  const run = el('spdRun');
  if (run) run.onclick = render;
  ['spdFrontFrom', 'spdFrontTo', 'spdRearFrom', 'spdRearTo', 'spdTyreFrom', 'spdTyreTo',
    'spdSensor', 'spdIndicated', 'spdActual'].forEach((id) => {
    const node = el(id);
    if (!node) return;
    node.addEventListener('input', () => { if (el('spdOut')?.innerHTML) render(); });
    node.addEventListener('change', () => { if (el('spdOut')?.innerHTML) render(); });
  });
  // The gearing panel's own tyre field is the natural "before" tyre.
  const gearTyre = el('gearTyre');
  if (gearTyre) {
    gearTyre.addEventListener('change', () => {
      const target = el('spdTyreFrom');
      if (target) target.value = gearTyre.value;
    });
  }
}
