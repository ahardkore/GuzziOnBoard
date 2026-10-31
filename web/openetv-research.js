/* Offline torque inversion adapted from OpenETV model.rs, commit
 * 6b781e4fc11e5994531c367eb897f16d1a33318f.
 * Copyright (c) 2026 Silvio Sackewitz, MIT; see LICENSES/OpenETV-MIT.txt.
 * No ECU interaction; model outputs require independent review and testing. */
(() => {
  'use strict';
  const engineInput = document.getElementById('etvEngine');
  const requestInput = document.getElementById('etvRequest');
  const thresholdInput = document.getElementById('etvThreshold');
  const toleranceInput = document.getElementById('etvTolerance');
  const output = document.getElementById('etvOut');
  const inputs = [engineInput, requestInput, thresholdInput, toleranceInput];
  const number = (s) => {
    if (!s.trim() || !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(s.trim())) throw Error('All cells and axes must be numbers.');
    const v = Number(s);
    if (!Number.isFinite(v) || Math.abs(v) > 1000000) throw Error('Numbers must be finite and at most 1,000,000 in magnitude.');
    return v;
  };
  function table(text, label) {
    if (text.length > 500000) throw Error(`${label}: CSV exceeds the size limit.`);
    const lines = text.trim().split(/\r?\n/);
    if (lines.length < 2 || lines.length > 257) throw Error(`${label}: use 1–256 RPM rows.`);
    const rows = lines.map(line => line.split(','));
    const width = rows[0].length;
    if (width < 2 || width > 257 || rows.some(row => row.length !== width) || (lines.length - 1) * (width - 1) > 20000)
      throw Error(`${label}: CSV dimensions are invalid or exceed 20,000 cells.`);
    const axis = rows[0].slice(1).map(number);
    const rpm = rows.slice(1).map(row => number(row[0]));
    const values = rows.slice(1).map(row => row.slice(1).map(number));
    if (rpm.some(v => v < 0 || v > 100000) || axis.some(v => v < 0 || v > 100)) throw Error(`${label}: RPM must be 0–100000 and percentages 0–100.`);
    if ([rpm, axis].some(a => a.some((v, i) => i && v <= a[i - 1]))) throw Error(`${label}: breakpoints must be unique and strictly ascending.`);
    return {rpm, axis, values};
  }
  function bracket(a, x) {
    if (a.length === 1) return [0, 0, 0];
    x = Math.max(a[0], Math.min(a[a.length - 1], x));
    let hi = 1; while (hi < a.length - 1 && a[hi] <= x) hi++;
    return [hi - 1, hi, (x - a[hi - 1]) / (a[hi] - a[hi - 1])];
  }
  const lerp = (a, b, f) => a * (1 - f) + b * f;
  function lookup(t, rpm, axis) {
    const [i, k, r] = bracket(t.rpm, rpm), [j, l, c] = bracket(t.axis, axis);
    return lerp(lerp(t.values[i][j], t.values[i][l], c), lerp(t.values[k][j], t.values[k][l], c), r);
  }
  // OpenETV treats all-zero rows as placeholders when interpolating the engine table.
  function engineRow(t, rpm) {
    const real = t.rpm.map((_, i) => i).filter(i => t.values[i].some(v => v !== 0));
    if (!real.length) throw Error('Engine torque table has no nonzero rows.');
    const rpms = real.map(i => t.rpm[i]);
    const [lo, hi, f] = bracket(rpms, rpm);
    return { values: t.values[real[lo]].map((v, i) => lerp(v, t.values[real[hi]][i], f)),
      outside: rpm < rpms[0] || rpm > rpms[rpms.length - 1] };
  }
  function roundEven(value) {
    const n = value * 10, lo = Math.floor(n), rem = n - lo;
    return (rem < 0.5 ? lo : rem > 0.5 ? lo + 1 : lo % 2 === 0 ? lo : lo + 1) / 10;
  }
  function calculate(engine, request, threshold, tolerance) {
    const states = {ok: 0, saturated: 0, below_min: 0, non_monotonic: 0};
    const outside = [], values = [], status = [];
    for (const rpm of request.rpm) {
      const row = engineRow(engine, rpm); if (row.outside) outside.push(rpm);
      const max = Math.max(...row.values);
      const result = [], resultStatus = [];
      for (const grip of request.axis) {
        const target = lookup(request, rpm, grip);
        let position, state;
        if (target >= max - tolerance) {
          const near = row.values.map((value, i) => value >= max - tolerance ? i : -1).filter(i => i >= 0);
          position = engine.axis[rpm > threshold ? near[near.length - 1] : near[0]]; state = 'saturated';
        } else if (target <= row.values[0]) {
          position = engine.axis[0]; state = 'below_min';
        } else {
          const j = row.values.findIndex(value => value >= target);
          position = engine.axis[j - 1] + (target - row.values[j - 1]) / (row.values[j] - row.values[j - 1]) * (engine.axis[j] - engine.axis[j - 1]);
          state = row.values.slice(j).some(v => v < target) ? 'non_monotonic' : 'ok';
        }
        states[state]++; result.push(roundEven(position)); resultStatus.push(state);
      }
      values.push(result); status.push(resultStatus);
    }
    return {values, status, states, outside};
  }
  inputs.forEach(input => input.addEventListener('input', () => { output.textContent = 'Inputs changed; calculate again.'; }));
  document.getElementById('etvCalculate').addEventListener('click', () => {
    try {
      const engine = table(engineInput.value, 'Engine'), request = table(requestInput.value, 'Request');
      const threshold = number(thresholdInput.value), tolerance = number(toleranceInput.value);
      if (threshold < 0 || threshold > 100000 || tolerance < 0) throw Error('Threshold and tolerance must be nonnegative, with threshold at most 100000.');
      const result = calculate(engine, request, threshold, tolerance);
      const csv = ['RPM,' + request.axis.join(','), ...request.rpm.map((rpm, i) => [rpm, ...result.values[i]].join(','))].join('\n');
      const statusCsv = ['RPM,' + request.axis.join(','), ...request.rpm.map((rpm, i) => [rpm, ...result.status[i]].join(','))].join('\n');
      output.textContent = `Candidate throttle % CSV (columns are grip %):\n${csv}\n\nCell status CSV:\n${statusCsv}\n\nStatus counts: ${JSON.stringify(result.states)}\nEngine RPM clamped outside real rows: ${result.outside.length ? result.outside.join(', ') : 'none'}\nAll-zero engine rows are treated as placeholders. Saturated, below-minimum and non-monotonic results require review. This model is not a validated or flash-ready tune.`;
    } catch (error) { output.textContent = `Cannot calculate: ${error.message}`; }
  });
})();
