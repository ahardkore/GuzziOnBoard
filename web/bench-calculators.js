/* Bench calculators: fuel system sizing, dyno correction, fuel blend and lambda.
 *
 * Three panels, one file, no motorcycle. Every number is arithmetic on values
 * the operator supplies; nothing here reads a map, a log or an ECU.
 *
 * The constants that matter are stated with their sources:
 *  - Stoichiometric ratios: petrol 14.7, ethanol 9.0, methanol 6.5, diesel 14.5.
 *    Blends interpolate on volume fraction between petrol and ethanol.
 *  - Densities at 15 °C: petrol 0.745, ethanol 0.789, methanol 0.792 kg/L.
 *    Real pump fuel varies by season and refinery; these are teaching values.
 *  - Lower heating values: petrol 43.5, ethanol 26.8 MJ/kg.
 *  - SAE J1349 correction: CF = 1.176 [(990/P_d)(T/298)^0.5] - 0.176, P_d in hPa
 *    (dry air), T in kelvin, 990 hPa and 298 K (25 °C) reference.
 *  - DIN 70020 / SAE J607 / ISO 1585 are given in their density form against
 *    each standard's own reference conditions, which is what those documents
 *    reduce to without the humidity correction.
 *
 * The rule the rest of the program uses still holds: a calculated number is a
 * starting point for a measurement, not a verified calibration.
 */
'use strict';

const ETHANOL_STOICH = 9.0;
const ETHANOL_DENSITY = 0.789;
const ETHANOL_LHV = 26.8;
const PETROL_STOICH = 14.7;
const PETROL_DENSITY = 0.745;
const PETROL_LHV = 43.5;

const LB_TO_KG = 0.45359237;

/**
 * Linear blend between petrol and ethanol on volume fraction.
 *
 * This is a model, not a measurement: a pump marked E10 can run E5–E15, and
 * winter E85 is nearer E50–E70. Published handbooks quote E85 at 9.8:1 and this
 * linear model says 9.86:1 — close, and the difference is stated rather than
 * hidden, because both panels here use the model so at least they agree.
 */
function ethanolBlend(percent) {
  const e = Number(percent);
  if (!Number.isFinite(e) || e < 0 || e > 100) throw new Error('Ethanol content must be between 0 and 100 %.');
  const f = e / 100;
  const stoich = PETROL_STOICH * (1 - f) + ETHANOL_STOICH * f;
  const density = PETROL_DENSITY * (1 - f) + ETHANOL_DENSITY * f;
  // Mass-weighted heating value: volume fraction → mass fraction via density.
  const massEthanol = (f * ETHANOL_DENSITY) / density;
  const lhv = (1 - massEthanol) * PETROL_LHV + massEthanol * ETHANOL_LHV;
  return {
    percent: e,
    stoich,
    density,
    lhv,
    energyPerLitre: density * lhv,
    label: e === 0 ? 'Petrol / E0' : `E${e % 1 === 0 ? e.toFixed(0) : e.toFixed(1)}`,
  };
}

/* One source of truth for the petrol-family fuels: the blend model above.
 * Methanol and diesel are separate substances, so they carry their own
 * published constants. BSFC is a tuning assumption, not a fuel property. */
const BENCH_FUELS = {
  petrol: { ...ethanolBlend(0), id: 'petrol', label: 'Petrol / E0', bsfc: 0.50 },
  e10: { ...ethanolBlend(10), id: 'e10', label: 'E10', bsfc: 0.51 },
  e85: { ...ethanolBlend(85), id: 'e85', label: 'E85', bsfc: 0.66 },
  methanol: { id: 'methanol', label: 'Methanol (M100)', stoich: 6.5, density: 0.792, lhv: 19.9, bsfc: 1.00 },
  diesel: { id: 'diesel', label: 'Diesel', stoich: 14.5, density: 0.832, lhv: 42.6, bsfc: 0.38 },
};

function benchFuel(id) {
  const fuel = BENCH_FUELS[id];
  if (!fuel) throw new Error(`Unknown fuel "${id}".`);
  return fuel;
}

/* -- fuel system ---------------------------------------------------------- */

/** Millilitres per minute needed to make `powerHp` at `bsfc` lb/(hp·h). */
function fuelFlowCcMin(powerHp, bsfc, fuelId = 'petrol') {
  const fuel = benchFuel(fuelId);
  const power = Number(powerHp);
  const consumption = Number(bsfc);
  if (!(power > 0)) throw new Error('Target power must be greater than zero.');
  if (!(consumption > 0)) throw new Error('BSFC must be greater than zero.');
  const massLbPerHour = power * consumption;
  const massKgPerHour = massLbPerHour * LB_TO_KG;
  const litresPerHour = massKgPerHour / fuel.density;
  return {
    massLbPerHour,
    massKgPerHour,
    litresPerHour,
    ccMin: (litresPerHour * 1000) / 60,
  };
}

/**
 * Size injectors from a target power.
 *
 * Flow scales with the square root of the pressure difference across the
 * injector, so a rating quoted at 3 bar becomes something else at 3.5 bar.
 * `ratedCc` is therefore converted back to the pressure the vendor quoted.
 */
function injectorSizing(options = {}) {
  const {
    powerHp, bsfc = 0.50, cylinders = 4, maxDuty = 0.80,
    fuelPressure = 3.0, ratedPressure = 3.0, fuel = 'petrol',
  } = options;
  const fuelEntry = benchFuel(fuel);
  const count = Number(cylinders);
  const duty = Number(maxDuty);
  const pActual = Number(fuelPressure);
  const pRated = Number(ratedPressure);
  if (!(count >= 1) || !Number.isInteger(count)) throw new Error('Injector count must be a whole number of at least one.');
  if (!(duty > 0 && duty <= 1)) throw new Error('Maximum duty cycle must be between 0 and 100 %.');
  if (!(pActual > 0) || !(pRated > 0)) throw new Error('Pressures must be above zero bar.');

  const demand = fuelFlowCcMin(powerHp, bsfc, fuelEntry.id);
  const neededAtDuty = demand.ccMin / duty;
  const perInjectorAtPressure = neededAtDuty / count;
  const pressureRatio = pActual / pRated;
  const ratedNeeded = perInjectorAtPressure / Math.sqrt(pressureRatio);
  return {
    fuel: fuelEntry,
    demand,
    duty,
    count,
    perInjectorAtPressure,
    ratedNeeded,
    pressureRatio,
    ratedPressure: pRated,
    fuelPressure: pActual,
  };
}

/** Duty cycle for injectors of a known flow, at the same target power. */
function injectorDuty(options = {}) {
  const { flowCc, ratedPressure = 3.0, fuelPressure = 3.0, ...rest } = options;
  const flow = Number(flowCc);
  if (!(flow > 0)) throw new Error('Injector flow must be greater than zero cc/min.');
  const sizing = injectorSizing({ ...rest, fuelPressure, ratedPressure });
  const perInjector = flow * Math.sqrt(Number(fuelPressure) / Number(ratedPressure));
  const available = perInjector * sizing.count;
  const duty = sizing.demand.ccMin / available;
  // Past about 85 % most injectors stop being linear and the published flow
  // figure stops describing them; past 100 % they physically cannot deliver.
  return { ...sizing, perInjector, available, duty, sufficient: duty <= 1, linear: duty <= 0.85 };
}

/** Milliseconds available for one injection at a four-stroke's `rpm`. */
function injectionWindowMs(rpm) {
  const speed = Number(rpm);
  if (!(speed > 0)) throw new Error('Engine speed must be above zero.');
  return 120000 / speed;
}

/* -- air and dyno correction ---------------------------------------------- */

const DYNO_STANDARDS = {
  sae_j1349: {
    id: 'sae_j1349', label: 'SAE J1349', tempK: 298.15, pressureHpa: 990,
    note: 'Documented form: CF = 1.176 × (990 / P_dry) × (T / 298)^0.5 − 0.176. Defined for naturally aspirated engines.',
    humidityApplied: true,
  },
  din_70020: {
    id: 'din_70020', label: 'DIN 70020', tempK: 293.15, pressureHpa: 1013.25,
    note: 'Density form against 20 °C and 1013.25 hPa. The standard’s own humidity term is not applied here.',
    humidityApplied: false,
  },
  sae_j607: {
    id: 'sae_j607', label: 'SAE J607 (STD)', tempK: 288.15, pressureHpa: 1013.25,
    note: 'Density form against 15 °C and 1013.25 hPa — the older “STD” numbers that read higher than SAE J1349.',
    humidityApplied: false,
  },
  iso_1585: {
    id: 'iso_1585', label: 'ISO 1585 / EEC 80/1269', tempK: 293.15, pressureHpa: 1000,
    note: 'Density form against 20 °C and 1000 hPa. Approximate: the standard’s humidity correction is not applied.',
    humidityApplied: false,
  },
  uncorrected: {
    id: 'uncorrected', label: 'Uncorrected (as measured)', tempK: 293.15, pressureHpa: 1013.25,
    note: 'No correction: the number the dyno printed, with the density ratio shown for context only.',
    humidityApplied: false,
  },
};

/** Saturation vapour pressure over water, hPa (Buck 1981). */
function saturationVapourPressureHpa(tempC) {
  const t = Number(tempC);
  if (!Number.isFinite(t)) throw new Error('Temperature must be a number.');
  return 6.1121 * Math.exp((18.678 - t / 234.5) * (t / (257.14 + t)));
}

/** Pressure at altitude, hPa (ISA, troposphere only). */
function pressureAtAltitude(hpaSeaLevel, altitudeM) {
  const p0 = Number(hpaSeaLevel);
  const h = Number(altitudeM);
  if (!(p0 > 0)) throw new Error('Sea-level pressure must be above zero.');
  if (!Number.isFinite(h) || Math.abs(h) > 11000) throw new Error('Altitude must be between −11,000 and 11,000 m.');
  return p0 * Math.pow(1 - 2.25577e-5 * h, 5.25588);
}

/** Dry-air density in kg/m³ from temperature, total pressure and humidity. */
function airDensity({ tempC, pressureHpa, humidity = 0 }) {
  const t = Number(tempC);
  const p = Number(pressureHpa);
  const rh = Math.min(1, Math.max(0, Number(humidity)));
  if (!Number.isFinite(t)) throw new Error('Temperature must be a number.');
  if (!(p > 0)) throw new Error('Pressure must be above zero hPa.');
  const vapour = rh * saturationVapourPressureHpa(t);
  const dry = p - vapour;
  const tK = t + 273.15;
  const density = (dry * 100) / (287.058 * tK) + (vapour * 100) / (461.495 * tK);
  return { density, dryPressureHpa: dry, vapourPressureHpa: vapour, tempK: tK };
}

/**
 * Correct a measured power or torque to a standard.
 *
 * `measured` is in the unit you name (hp or kW); the returned `corrected` is in
 * the same unit, so nothing is converted behind the operator's back.
 */
function dynoCorrection(options = {}) {
  const {
    standard = 'sae_j1349', tempC, pressureHpa, humidity = 0, altitudeM = null,
    measured, unit = 'hp', boosted = false,
  } = options;
  const spec = DYNO_STANDARDS[standard];
  if (!spec) throw new Error(`Unknown correction standard "${standard}".`);
  const value = Number(measured);
  if (!Number.isFinite(value)) throw new Error('Measured power must be a number.');
  const temperature = Number(tempC);
  if (!Number.isFinite(temperature)) throw new Error('Ambient temperature must be a number.');

  let pressure = pressureHpa === null || pressureHpa === undefined || pressureHpa === '' ? null : Number(pressureHpa);
  let pressureSource = 'measured';
  if (pressure === null) {
    if (altitudeM === null || altitudeM === undefined || altitudeM === '') {
      throw new Error('Give a barometric pressure, or an altitude to estimate one.');
    }
    pressure = pressureAtAltitude(1013.25, altitudeM);
    pressureSource = `estimated from ${Number(altitudeM)} m (ISA)`;
  }
  if (!(pressure > 0)) throw new Error('Barometric pressure must be above zero hPa.');

  const air = airDensity({ tempC: temperature, pressureHpa: pressure, humidity });
  const dry = air.dryPressureHpa;
  const tK = air.tempK;
  let factor;
  if (standard === 'uncorrected') {
    factor = 1;
  } else if (standard === 'sae_j1349') {
    factor = 1.176 * ((990 / dry) * Math.sqrt(tK / 298.15)) - 0.176;
  } else {
    factor = (spec.pressureHpa / pressure) * (tK / spec.tempK);
  }
  const densityRatio = (dry * 100 / (287.058 * tK)) / ((1013.25 * 100) / (287.058 * 288.15));

  return {
    spec,
    factor,
    corrected: value * factor,
    measured: value,
    unit,
    tempC: temperature,
    pressureHpa: pressure,
    pressureSource,
    humidity: Math.min(1, Math.max(0, Number(humidity))),
    densityRatio,
    air,
    boosted: Boolean(boosted),
    // SAE J1349 is a naturally-aspirated correction: for a boosted engine the
    // number is reported but flagged, because the standard does not cover it.
    valid: !(boosted && standard === 'sae_j1349'),
  };
}

/* -- fuel blend and lambda ------------------------------------------------- */

function afrToLambda(afr, stoich) {
  const value = Number(afr);
  const ratio = Number(stoich);
  if (!(ratio > 0)) throw new Error('Stoichiometric ratio must be above zero.');
  if (!Number.isFinite(value) || value <= 0) throw new Error('AFR must be a positive number.');
  return value / ratio;
}

function lambdaToAfr(lambda, stoich) {
  const value = Number(lambda);
  const ratio = Number(stoich);
  if (!(ratio > 0)) throw new Error('Stoichiometric ratio must be above zero.');
  if (!Number.isFinite(value) || value <= 0) throw new Error('Lambda must be a positive number.');
  return value * ratio;
}

/**
 * Extra fuel volume a blend needs for the same lambda, relative to petrol.
 * Mass scales with the stoich ratio; volume divides by density again.
 */
function fuelVolumeRatio(blend, reference = null) {
  const target = typeof blend === 'number' ? ethanolBlend(blend) : blend;
  const base = reference === null ? ethanolBlend(0) : (typeof reference === 'number' ? ethanolBlend(reference) : reference);
  return (base.stoich / target.stoich) * (base.density / target.density);
}

/** Mass flow (and injector duty) for the same lambda on a different blend. */
function blendInjectorImpact({ petrolDuty, blendPercent }) {
  const ratio = fuelVolumeRatio(blendPercent);
  const duty = Number(petrolDuty);
  if (!(duty > 0) || duty > 1) throw new Error('Petrol duty cycle must be between 0 and 100 %.');
  const blend = ethanolBlend(blendPercent);
  return { blend, volumeRatio: ratio, duty: duty * ratio, sufficient: duty * ratio <= 1, linear: duty * ratio <= 0.85 };
}

if (typeof window !== 'undefined') {
  window.gobBenchCalc = {
    fuels: BENCH_FUELS,
    standards: DYNO_STANDARDS,
    fuelFlowCcMin,
    injectorSizing,
    injectorDuty,
    injectionWindowMs,
    airDensity,
    pressureAtAltitude,
    saturationVapourPressureHpa,
    dynoCorrection,
    ethanolBlend,
    afrToLambda,
    lambdaToAfr,
    fuelVolumeRatio,
    blendInjectorImpact,
  };
}

/* ---- panel wiring ------------------------------------------------------- */

if (typeof document !== 'undefined') {
  const el = (id) => document.getElementById(id);
  const num = (id, fallback = NaN) => {
    const node = el(id);
    if (!node || String(node.value).trim() === '') return fallback;
    const value = Number(node.value);
    return Number.isFinite(value) ? value : fallback;
  };
  const text = (id, fallback = '') => (el(id) ? String(el(id).value) : fallback);
  const checked = (id) => Boolean(el(id)?.checked);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
  const fixed = (value, digits = 1) => (Number.isFinite(value) ? value.toFixed(digits) : '—');
  const kv = (rows) => `<div class="kv">${rows.map(([label, value]) => (
    `<div><span>${esc(label)}</span><b>${value}</b></div>`
  )).join('')}</div>`;
  const table = (head, rows) => {
    if (!rows.length) return '';
    return '<div class="table-wrap"><table class="data"><thead><tr>'
      + head.map((cell) => `<th>${esc(cell)}</th>`).join('')
      + '</tr></thead><tbody>'
      + rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join('')}</tr>`).join('')
      + '</tbody></table></div>';
  };
  const warn = (message) => `<p class="tip warn"><b>Check this.</b> ${esc(message)}</p>`;

  /* ---- 1. injector & fuel flow ---------------------------------------- */

  function runInjector() {
    const out = el('injOut');
    const meta = el('injMeta');
    try {
      const fuel = text('injFuel', 'petrol');
      const sizing = injectorSizing({
        powerHp: num('injPower'),
        bsfc: num('injBsfc', 0.5),
        cylinders: num('injCylinders', 4),
        maxDuty: num('injDuty', 80) / 100,
        fuelPressure: num('injPressure', 3),
        ratedPressure: num('injRated', 3),
        fuel,
      });
      const rpm = num('injRpm', 0);
      const window = rpm > 0 ? injectionWindowMs(rpm) : null;
      const flow = num('injFlow', 0);
      const duty = flow > 0
        ? injectorDuty({
          flowCc: flow,
          ratedPressure: num('injRated', 3),
          fuelPressure: num('injPressure', 3),
          powerHp: num('injPower'),
          bsfc: num('injBsfc', 0.5),
          cylinders: num('injCylinders', 4),
          fuel,
        })
        : null;

      let html = kv([
        ['Target power', `${fixed(num('injPower'), 1)} hp (${fixed(num('injPower') * 0.7457, 1)} kW)`],
        ['Fuel', `${esc(sizing.fuel.label)} · stoich ${fixed(sizing.fuel.stoich, 1)}:1 · ${fixed(sizing.fuel.density, 3)} kg/L`],
        ['Fuel mass', `${fixed(sizing.demand.massLbPerHour, 1)} lb/h · ${fixed(sizing.demand.massKgPerHour, 1)} kg/h`],
        ['Fuel volume', `${fixed(sizing.demand.litresPerHour, 1)} L/h · ${fixed(sizing.demand.ccMin, 0)} cc/min`],
        ['Injectors', `${sizing.count} × at ${fixed(sizing.duty * 100, 0)} % maximum duty`],
        ['Per injector now', `${fixed(sizing.perInjectorAtPressure, 0)} cc/min at ${fixed(sizing.fuelPressure, 2)} bar`],
        ['Per injector at rating', `${fixed(sizing.ratedNeeded, 0)} cc/min at ${fixed(sizing.ratedPressure, 2)} bar`],
      ]);
      if (window !== null) {
        html += kv([
          ['Injection window', `${fixed(window, 2)} ms at ${fixed(rpm, 0)} rpm`],
          ['Available pulse', `${fixed(window * sizing.duty, 2)} ms at ${fixed(sizing.duty * 100, 0)} % duty`],
        ]);
      }
      if (duty) {
        html += kv([
          ['Your injector at pressure', `${fixed(duty.perInjector, 0)} cc/min each`],
          ['Duty at this power', `${fixed(duty.duty * 100, 1)} %`],
        ]);
        if (!duty.sufficient) {
          html += warn(`At ${fixed(num('injFlow'), 0)} cc/min these injectors cannot deliver the target: `
            + `${fixed(duty.duty * 100, 0)} % duty needed. Either the power target, the fuel, or the injector is wrong.`);
        }
      }
      html += '<p class="tip warn"><b>This is a starting point.</b> BSFC is the assumption that decides the answer: '
        + '0.50 lb/(hp·h) suits a naturally aspirated four-stroke at peak power, and a two-valve air-cooled twin can be '
        + 'worse. Vendor flow numbers are quoted at a stated pressure with a test fluid, not with your fuel. '
        + 'Measure duty cycle on the bike before you buy anything.</p>';
      out.innerHTML = html;
      meta.textContent = `Sized at ${fixed(num('injDuty', 80), 0)} % duty limit · ${esc(sizing.fuel.label)}`;
    } catch (error) {
      out.innerHTML = '';
      meta.textContent = `Not calculated: ${error.message}`;
    }
  }

  /* ---- 2. dyno correction --------------------------------------------- */

  function runDyno() {
    const out = el('dynoOut');
    const meta = el('dynoMeta');
    try {
      const pressure = text('dynoPressure').trim() === '' ? null : num('dynoPressure');
      const altitude = text('dynoAltitude').trim() === '' ? null : num('dynoAltitude');
      const measured = num('dynoMeasured');
      const unit = text('dynoUnit', 'hp');
      const boosted = checked('dynoBoosted');
      const chosen = text('dynoStandard', 'sae_j1349');
      const result = dynoCorrection({
        standard: chosen,
        tempC: num('dynoTemp', 20),
        pressureHpa: pressure,
        humidity: num('dynoHumidity', 0) / 100,
        altitudeM: altitude,
        measured,
        unit,
        boosted,
      });
      const rows = Object.values(DYNO_STANDARDS).map((spec) => {
        const one = dynoCorrection({
          standard: spec.id,
          tempC: result.tempC,
          pressureHpa: result.pressureHpa,
          humidity: result.humidity,
          measured,
          unit,
          boosted,
        });
        const highlight = spec.id === chosen ? ' style="font-weight:600"' : '';
        return [
          `<span${highlight}>${esc(spec.label)}</span>`,
          fixed(one.factor, 4),
          `${fixed(one.corrected, 1)} ${esc(unit)}`,
        ];
      });

      let html = kv([
        ['Measured', `${fixed(result.measured, 1)} ${esc(unit)}`],
        ['Air temperature', `${fixed(result.tempC, 1)} °C`],
        ['Barometric pressure', `${fixed(result.pressureHpa, 1)} hPa (${esc(result.pressureSource)})`],
        ['Relative humidity', `${fixed(result.humidity * 100, 0)} %`],
        ['Dry air pressure', `${fixed(result.air.dryPressureHpa, 1)} hPa`],
        ['Air density', `${fixed(result.air.density, 4)} kg/m³`],
        ['Density vs 15 °C / 1013 hPa', `${fixed(result.densityRatio, 4)}`],
        ['Correction factor', `${fixed(result.factor, 4)} (${esc(result.spec.label)})`],
        [`Corrected power`, `<b>${fixed(result.corrected, 1)} ${esc(unit)}</b>`],
      ]);
      html += table(['Standard', 'Factor', 'Corrected'], rows);
      html += `<p class="muted small">${esc(result.spec.note)}</p>`;
      if (!result.valid) {
        html += warn('SAE J1349 is defined for naturally aspirated engines. A boosted engine’s corrected number is shown '
          + 'because people ask for it, but it is not a J1349 result: use the density ratio and say which method you used.');
      }
      html += '<p class="tip warn"><b>Correction is a comparison tool, not a claim about the engine.</b> '
        + 'It scales a measurement to reference air; it cannot fix a heat-soaked intake, a slipping tyre on the drum '
        + 'or a dyno operator’s throttle ramp. A different standard on the same run can move the number by several '
        + 'percent, so quote the standard with the figure.</p>';
      out.innerHTML = html;
      meta.textContent = `${esc(result.spec.label)} · factor ${fixed(result.factor, 3)}`;
    } catch (error) {
      out.innerHTML = '';
      meta.textContent = `Not calculated: ${error.message}`;
    }
  }

  /* ---- 3. fuel blend and lambda --------------------------------------- */

  function runBlend() {
    const out = el('blendOut');
    const meta = el('blendMeta');
    try {
      const percent = num('blendEthanol', 0);
      const blend = ethanolBlend(percent);
      const mode = text('blendMode', 'lambda');
      const value = num('blendValue', 1);
      const lambda = mode === 'lambda' ? value : afrToLambda(value, blend.stoich);
      const reference = ethanolBlend(0);
      const ratio = fuelVolumeRatio(blend);

      const rows = [0, 10, 85, 100].map((e) => {
        const one = ethanolBlend(e);
        return [
          `${esc(one.label)}`,
          `${fixed(one.stoich, 2)}:1`,
          fixed(lambda * one.stoich, 2),
          fixed(one.density, 3),
          fixed(one.energyPerLitre, 1),
          fixed(fuelVolumeRatio(one), 3),
        ];
      });

      let html = kv([
        ['Blend', esc(blend.label)],
        ['Stoichiometric ratio', `${fixed(blend.stoich, 2)}:1`],
        ['Density', `${fixed(blend.density, 3)} kg/L`],
        ['Energy per litre', `${fixed(blend.energyPerLitre, 1)} MJ/L`],
        ['Lambda', fixed(lambda, 3)],
        [`AFR on ${esc(blend.label)}`, fixed(lambdaToAfr(lambda, blend.stoich), 2)],
        [`AFR on petrol`, fixed(lambdaToAfr(lambda, reference.stoich), 2)],
        ['Volume vs petrol, same lambda', `${fixed(ratio, 3)} ×`],
      ]);
      html += table(['Blend', 'Stoich', 'AFR at this λ', 'kg/L', 'MJ/L', 'Volume vs petrol'], rows);

      const petrolDuty = num('blendPetrolDuty', NaN);
      if (Number.isFinite(petrolDuty) && petrolDuty > 0) {
        const impact = blendInjectorImpact({ petrolDuty: petrolDuty / 100, blendPercent: percent });
        html += kv([
          ['Petrol duty you measured', `${fixed(petrolDuty, 1)} %`],
          [`Duty on ${esc(blend.label)}`, `${fixed(impact.duty * 100, 1)} %`],
        ]);
        if (!impact.sufficient) {
          html += warn(`The same injectors would sit at ${fixed(impact.duty * 100, 0)} % duty on ${blend.label}. `
            + 'They cannot deliver that: the fuel change needs bigger injectors, more pressure, or a lower target.');
        } else if (!impact.linear) {
          html += warn(`The same injectors would sit at ${fixed(impact.duty * 100, 0)} % duty on ${blend.label}. `
            + 'That is past the point where most injectors stay linear, so the flow figure you sized with no longer '
            + 'describes them. Check duty on the bike before trusting the top of the range.');
        }
      }
      // The panel's own caution covers the blend assumption; this line adds the
      // one thing the panel cannot say before a conversion: AFR logs are only
      // comparable when the assumed stoichiometric ratio is the same.
      html += '<p class="muted small">Two AFR logs are only comparable when the assumed stoichiometric ratio is '
        + 'the same. If the wideband controller can output lambda, log that instead.</p>';
      out.innerHTML = html;
      meta.textContent = `${esc(blend.label)} · stoich ${fixed(blend.stoich, 2)}:1 · λ ${fixed(lambda, 3)}`;
    } catch (error) {
      out.innerHTML = '';
      meta.textContent = `Not calculated: ${error.message}`;
    }
  }

  const wire = (buttonId, fn) => {
    const button = el(buttonId);
    if (button) button.onclick = fn;
  };
  wire('injRun', runInjector);
  wire('dynoRun', runDyno);
  wire('blendRun', runBlend);

  // Redo the maths whenever an input changes, so the panel never shows a stale
  // answer next to a changed input.
  /* BSFC is a property of the engine, but its *default* depends on the fuel.
   * Follow the fuel choice while the field still holds the previous default,
   * and never overwrite a number the operator typed. */
  const bsfcField = el('injBsfc');
  const fuelField = el('injFuel');
  if (bsfcField && fuelField) {
    let lastDefault = String(bsfcField.value);
    fuelField.addEventListener('change', () => {
      const next = BENCH_FUELS[fuelField.value];
      if (!next) return;
      if (String(bsfcField.value) === lastDefault) {
        bsfcField.value = Number(next.bsfc).toFixed(2);
        lastDefault = String(bsfcField.value);
      }
    });
  }

  const live = (ids, fn) => ids.forEach((id) => {
    const node = el(id);
    if (!node) return;
    node.addEventListener('input', fn);
    node.addEventListener('change', fn);
  });
  const injReady = () => { if (el('injOut')?.innerHTML) runInjector(); };
  const dynoReady = () => { if (el('dynoOut')?.innerHTML) runDyno(); };
  const blendReady = () => { if (el('blendOut')?.innerHTML) runBlend(); };
  live(['injPower', 'injBsfc', 'injCylinders', 'injDuty', 'injFuel', 'injPressure', 'injRated', 'injRpm', 'injFlow'], injReady);
  live(['dynoMeasured', 'dynoUnit', 'dynoStandard', 'dynoTemp', 'dynoPressure', 'dynoHumidity', 'dynoAltitude', 'dynoBoosted'], dynoReady);
  live(['blendEthanol', 'blendMode', 'blendValue', 'blendPetrolDuty'], blendReady);
}
