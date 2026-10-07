/* GuzziOnBoard — hosted demo backend.
 *
 * The workstation UI (index.html + app.js) talks to a local Python process
 * over /api. On a static host — GitHub Pages — there is no such process, so
 * this file answers those requests inside the browser instead.
 *
 * What it is:
 *   * the real catalog (web/demo-data.json, generated from the Python
 *     definitions by scripts/build_demo_data.py — never hand-written),
 *   * a port of the simulated engine model (guzzionboard/transports/
 *     simulator.py: EngineModel, fault seeding and maturation),
 *   * a port of the safety gate (guzzionboard/safety.py), including the
 *     named checks, the per-operation confirmation token and the audit log.
 *
 * What it is NOT: the KWP2000 stack. The real workstation encodes a frame,
 * checksums it and hands it to a transport; here the raw bytes next to each
 * channel are reconstructed from the catalog scaling, so they are simulated,
 * not a wire capture. demo-lab.js supplies virtual files, jobs, firmware,
 * maps, sessions, workshop tools, and an explicitly simulated adapter so the
 * hosted product tour remains self-contained. Real hardware belongs only to
 * the separately installed local application.
 *
 * The Python server marks the page it serves with <body data-backend="live">,
 * so when the real backend is present this file does nothing at all.
 */
(function () {
  'use strict';

  if (document.body && document.body.dataset.backend === 'live') return;

  var DEMO_HINT = 'Hosted demo: the motorcycle, ECU, cable, adapter, files, and jobs are virtual.';

  /* Extension points for web/demo-lab.js, which simulates the views that
   * need files and long jobs (ECU memory, maps, sessions, reports, tools).
   * Nothing here changes behaviour on its own: if demo-lab.js is absent the
   * hooks stay empty and this file behaves exactly as it did before. */
  var HOOKS = {};

  /* ------------------------------------------------------------- data */

  var DATA = null;
  var dataPromise = fetch('demo-data.json', { cache: 'no-cache' })
    .then(function (r) {
      if (!r.ok) throw new Error('demo-data.json: HTTP ' + r.status);
      return r.json();
    })
    .then(function (d) { DATA = d; return d; });

  /* ------------------------------------------------------------ clocks */

  var mono = function () {
    return (typeof performance !== 'undefined' ? performance.now() : Date.now()) / 1000;
  };
  var epoch = function () { return Date.now() / 1000; };

  /* --------------------------------------------------- deterministic rng */

  // The Python simulator seeds random.Random(7) so a demo is repeatable.
  // Same intent, different generator: mulberry32.
  function rng(seed) {
    var a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      var t = a;
      t = Math.imul(t ^ (t >>> 15), 1 | t);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  var clamp = function (v, lo, hi) { return Math.max(lo, Math.min(hi, v)); };
  var hex2 = function (n) { return ('0' + (n & 0xFF).toString(16)).slice(-2); };

  /* ------------------------------------------------------- engine model */
  /* Port of guzzionboard/transports/simulator.py :: EngineModel. */

  var IDLE_RPM = 1250.0;
  var REDLINE_RPM = 8500.0;

  function EngineModel(ambient) {
    this.ambient_c = ambient === undefined ? 18.0 : ambient;
    this.started_at = mono();
    this.running = true;
    this.throttle_pct = 0.0;
    this.in_gear = false;
    this.auto_blip = true;
    this.battery_health = 1.0;
    this.faults = {};
    this._rand = rng(7);
    this._coolant = this.ambient_c;
    this._last_tick = mono();
    this._stepper_frozen = null;
  }

  EngineModel.prototype.t = function () { return mono() - this.started_at; };
  EngineModel.prototype.noise = function (a) { return (this._rand() * 2 - 1) * a; };
  EngineModel.prototype.has = function (k) { return !!this.faults[k]; };
  EngineModel.prototype.faultKeys = function () { return Object.keys(this.faults).sort(); };

  EngineModel.prototype.setFaults = function (keys) {
    var known = {};
    (DATA.sim_faults || []).forEach(function (f) { known[f.key] = true; });
    this.faults = {};
    var self = this;
    keys.forEach(function (k) { if (known[k]) self.faults[k] = true; });
    if (!this.has('stepper_stuck')) this._stepper_frozen = null;
    return this.faultKeys();
  };

  EngineModel.prototype.start = function () { this.running = true; };
  EngineModel.prototype.stop = function () {
    this.running = false;
    this.throttle_pct = 0.0;
  };

  EngineModel.prototype.advance = function (seconds) {
    this._tick();
    this.started_at -= seconds;
    var remaining = seconds;
    while (remaining > 0) {
      var dt = Math.min(5.0, remaining);
      remaining -= dt;
      if (this.running) this._coolant += (92.0 - this._coolant) * (dt / 180.0);
      else this._coolant += (this.ambient_c - this._coolant) * (dt / 900.0);
    }
  };

  EngineModel.prototype._tick = function () {
    var now = mono();
    var dt = clamp(now - this._last_tick, 0, 30);
    this._last_tick = now;
    if (!dt) return;
    if (this.running) this._coolant += (92.0 - this._coolant) * (dt / 180.0);
    else this._coolant += (this.ambient_c - this._coolant) * (dt / 900.0);
  };

  EngineModel.prototype.trueCoolant = function () { this._tick(); return this._coolant; };

  EngineModel.prototype.coolant = function () {
    var truth = this.trueCoolant();
    if (this.has('coolant_sensor_open')) return -40.0;
    if (this.has('coolant_sensor_short')) return 135.0;
    return truth;
  };

  EngineModel.prototype.air = function () { return this.ambient_c + this.noise(0.4); };

  EngineModel.prototype.idleTarget = function () {
    var cold = clamp((70.0 - this.trueCoolant()) / 55.0, 0, 1);
    return IDLE_RPM + 320.0 * cold;
  };

  EngineModel.prototype.rpm = function () {
    if (!this.running) return 0.0;
    var target = this.idleTarget();
    if (this.has('air_leak')) target += 380;
    if (this.has('stepper_stuck')) target -= 260;
    if (this.has('coolant_sensor_open')) target += 180;
    if (this.throttle_pct > 0) {
      target += this.throttle_pct / 100.0 * (REDLINE_RPM - target) * 1.02;
    } else if (this.auto_blip) {
      target += 1400 * Math.max(0, Math.pow(Math.sin(this.t() / 23.0), 8));
    }
    var hunt = 28 * Math.sin(this.t() * 1.7) + this.noise(12);
    if (this.has('misfire_rear')) hunt += this.noise(160);
    return clamp(target + hunt, 0, REDLINE_RPM);
  };

  EngineModel.prototype.throttleDeg = function () {
    if (this.has('tps_fault')) return 0.0;
    if (!this.running) return 1.6;
    var base = 4.7 + this.throttle_pct * 0.85;
    if (this.throttle_pct === 0 && this.auto_blip) {
      base += 42 * Math.max(0, Math.pow(Math.sin(this.t() / 23.0), 8));
    }
    return base + this.noise(0.05);
  };

  EngineModel.prototype.batteryV = function () {
    var rest = 12.4 * this.battery_health + 0.2;
    if (this.has('charging_failure')) {
      return Math.max(10.8, 12.3 * this.battery_health - 0.004 * this.t() + this.noise(0.04));
    }
    if (!this.running) return rest + this.noise(0.05);
    return 14.1 - 0.0004 * this.rpm() + this.noise(0.04);
  };

  EngineModel.prototype.injectionMs = function () {
    if (!this.running) return 0.0;
    var enrich = 1.0 + 0.9 * clamp((70.0 - this.coolant()) / 70.0, 0, 1);
    if (this.has('coolant_sensor_open')) enrich = 2.0;
    if (this.has('coolant_sensor_short')) enrich = 0.8;
    var load = 1.0 + this.throttle_pct / 55.0;
    return (1.35 + 0.0008 * (this.rpm() - 1200)) * enrich * load + this.noise(0.02);
  };

  EngineModel.prototype.advanceDeg = function () {
    if (!this.running) return 8.0;
    return 20.0 + 0.0035 * (this.rpm() - 1200) + this.noise(0.1);
  };

  EngineModel.prototype.closedLoop = function () {
    if (this.has('coolant_sensor_open')) return false;
    return this.running && this.coolant() > 45;
  };

  EngineModel.prototype.lambdaMv = function (bank) {
    bank = bank || 0;
    if (bank === 0 && this.has('lambda_dead_front')) return 450 + this.noise(6);
    if (!this.closedLoop()) return 450 + this.noise(5);
    if (bank === 1 && this.has('misfire_rear')) return 180 + this.noise(20);
    return 450 + 380 * Math.sin(this.t() * (2.1 + 0.3 * bank) + bank);
  };

  EngineModel.prototype.lambdaIntegrator = function (bank) {
    bank = bank || 0;
    if (!this.closedLoop()) return 0.0;
    var base = 3.0 * Math.sin(this.t() / 9.0 + bank) + this.noise(0.3);
    if (this.has('air_leak')) base += 9.0;
    if (bank === 0 && this.has('injector_blocked_front')) base += 18.0;
    if (bank === 1 && this.has('misfire_rear')) base += 12.0;
    return base;
  };

  EngineModel.prototype.roadSpeed = function () {
    if (!this.in_gear || !this.running) return 0.0;
    return Math.max(0, (this.rpm() - 1100) / 7400 * 180.0);
  };

  EngineModel.prototype.stepperBase = function () {
    var cold = clamp((70.0 - this.trueCoolant()) / 55.0, 0, 1);
    return Math.trunc(100 + 17 * cold);
  };

  EngineModel.prototype.stepperPosition = function () {
    if (this.has('stepper_stuck')) {
      if (this._stepper_frozen === null) this._stepper_frozen = this.stepperBase() + 25;
      return Math.trunc(this._stepper_frozen);
    }
    var position = this.stepperBase() + 2;
    if (this.has('air_leak')) position -= 24;
    return Math.max(0, Math.trunc(position));
  };

  EngineModel.prototype.asDict = function () {
    var r = function (v, d) { var f = Math.pow(10, d); return Math.round(v * f) / f; };
    return {
      running: this.running,
      throttle_pct: r(this.throttle_pct, 1),
      ambient_c: r(this.ambient_c, 1),
      in_gear: this.in_gear,
      auto_blip: this.auto_blip,
      battery_health: r(this.battery_health, 2),
      coolant_c: r(this.trueCoolant(), 1),
      rpm: Math.round(this.rpm()),
      battery_v: r(this.batteryV(), 2),
      road_speed: Math.round(this.roadSpeed()),
      closed_loop: this.closedLoop(),
      faults: this.faultKeys(),
      seconds_since_start: r(this.t(), 1),
    };
  };

  /* --------------------------------------------------------- simulated ECU */

  var PENDING_STATUS = 0x24;
  var CONFIRMED_STATUS = 0x2A;
  var DTC_PREFIX = ['P', 'C', 'B', 'U'];

  function SimEcu(ecuId) {
    this.ecuId = ecuId;
    this.engine = new EngineModel(18.0);
    this.dtcs = [['P0130', 0x2A], ['P0505', 0x24]];
    this._faultSince = {};
    this.pendingAfter = 2.0;
    this.confirmAfter = 8.0;
    this.comms = { drop_rate: 0, corrupt_rate: 0, pending_rate: 0, extra_latency: 0 };
    this.activeOutputs = {};
  }

  SimEcu.prototype.profile = function () { return ecuPublic(this.ecuId); };
  SimEcu.prototype.internals = function () { return DATA.profiles[this.ecuId]; };

  SimEcu.prototype.identity = function () {
    var ident = this.internals().identity;
    var bytes = [];
    Object.keys(ident).forEach(function (field) {
      var v = String(ident[field]);
      for (var i = 0; i < v.length; i++) bytes.push(v.charCodeAt(i) & 0xFF);
      // The capture pads each field out; mirror the shape, not the content.
      for (var p = v.length; p < 11; p++) bytes.push(0x20);
    });
    return {
      fields: ident,
      raw: bytes.map(hex2).join(' '),
      ecu_id: this.ecuId,
      family: this.profile().family,
    };
  };

  /** Raw bytes this ECU would report for a local identifier. */
  SimEcu.prototype.rawFor = function (key) {
    var param = this.internals().parameters[key];
    if (!param) return null;
    if (param.dead) return [0x00, 0x00];
    var e = this.engine;
    var producers = {
      rpm: function () { return Math.trunc(Math.max(0, e.rpm())); },
      air_temp: function () { return Math.trunc(e.air() + 40); },
      coolant_temp: function () { return Math.trunc(e.coolant() + 40); },
      throttle: function () { return Math.trunc(e.throttleDeg() * 10); },
      advance: function () { return Math.trunc(e.advanceDeg() * 10); },
      advance_latched: function () { return Math.trunc(e.advanceDeg() * 10); },
      injection_ms: function () { return Math.trunc(e.injectionMs() * 1000); },
      idle_target: function () { return Math.trunc(e.idleTarget()); },
      battery: function () { return Math.trunc(e.batteryV() * 10); },
      lambda_f: function () { return Math.trunc(Math.max(0, e.lambdaMv(0))); },
      lambda_r: function () { return Math.trunc(Math.max(0, e.lambdaMv(1))); },
      lambda_int_f: function () { return Math.trunc(e.lambdaIntegrator(0) * 10); },
      lambda_int_r: function () { return Math.trunc(e.lambdaIntegrator(1) * 10); },
      lambda_loop: function () { return e.closedLoop() ? 2 : 0; },
      lambda_phase_f: function () { return e.closedLoop() ? 5 : 2; },
      road_speed: function () { return Math.trunc(e.roadSpeed()); },
      stepper_base: function () { return e.stepperBase(); },
      stepper_position: function () { return e.stepperPosition(); },
      stepper_trim: function () { return e.stepperPosition() - e.stepperBase(); },
      engine_state: function () { return e.running ? 0x07 : 0x00; },
      stop_state: function () { return e.running ? 4 : 8; },
      throttle_closed: function () { return e.throttleDeg() < 5 ? 1 : 4; },
      engine_run_flag: function () { return e.running ? 4 : 0; },
      neutral: function () { return e.in_gear ? 0 : 1; },
      sidestand: function () { return 1; },
      clutch: function () { return 0; },
      kill_run: function () { return e.running ? 1 : 0; },
      kill_stop: function () { return e.running ? 0 : 1; },
      starter: function () { return e.running ? 1 : 0; },
      dwell_f: function () { return 120; },
      dwell_r: function () { return 120; },
    };
    var value = producers[key] ? producers[key]() : 0;
    var length = param.length || ((Math.abs(value) > 0xFF || param.signed) ? 2 : 1);
    var out = [];
    var v = value;
    if (param.signed && v < 0) v = (1 << (8 * length)) + v;
    for (var i = length - 1; i >= 0; i--) out[i] = v & 0xFF, v = Math.floor(v / 256);
    return out;
  };

  /** Seeded faults age into fault memory, exactly like the Python simulator. */
  SimEcu.prototype.matureFaults = function () {
    var now = mono();
    var active = this.engine.faults;
    var self = this;
    Object.keys(active).forEach(function (k) {
      if (self._faultSince[k] === undefined) self._faultSince[k] = now;
    });
    Object.keys(this._faultSince).forEach(function (k) {
      if (!active[k]) delete self._faultSince[k];
    });

    var byKey = {};
    (DATA.sim_faults || []).forEach(function (f) { byKey[f.key] = f; });
    var stored = {};
    this.dtcs.forEach(function (d, i) { stored[d[0]] = i; });

    Object.keys(this._faultSince).forEach(function (key) {
      var fault = byKey[key];
      if (!fault || !fault.dtc) return;
      var age = now - self._faultSince[key];
      if (age < self.pendingAfter) return;
      var status = age >= self.confirmAfter ? CONFIRMED_STATUS : PENDING_STATUS;
      if (stored[fault.dtc] !== undefined) {
        var index = stored[fault.dtc];
        if (self.dtcs[index][1] < status) self.dtcs[index] = [fault.dtc, status];
      } else {
        stored[fault.dtc] = self.dtcs.length;
        self.dtcs.push([fault.dtc, status]);
      }
    });
  };

  SimEcu.prototype.readDtcs = function () {
    this.matureFaults();
    var descriptions = dtcDescriptions(this.ecuId);
    return this.dtcs.map(function (pair) {
      var raw = pair[1];
      return {
        code: pair[0],
        status: (raw & 0x20) ? 'stored' : 'current',
        status_byte: raw,
        warning_indicator: !!(raw & 0x40),
        kind: raw & 0x0F,
        description: descriptions[pair[0]] || '',
      };
    });
  };

  SimEcu.prototype.clearDtcs = function () {
    this.dtcs = [];
    var now = mono();
    var self = this;
    this._faultSince = {};
    Object.keys(this.engine.faults).forEach(function (k) { self._faultSince[k] = now; });
  };

  /* ------------------------------------------------------- safety gate */
  /* Port of guzzionboard/safety.py :: SafetyGate. */

  var CONFIDENCE_LEVELS = [
    'verified-bench', 'verified-capture', 'documented', 'inferred', 'unknown',
  ];
  function confidenceRank(level) {
    var i = CONFIDENCE_LEVELS.indexOf(level);
    return i === -1 ? CONFIDENCE_LEVELS.length : i;
  }
  function meets(level, minimum) {
    return confidenceRank(level) <= confidenceRank(minimum || 'documented');
  }

  /* Port of guzzionboard/firmware.py :: hardware_family - the family digit
   * that must match between an image and the ECU (HW610 -> '6', HW320 ->
   * '3'). Flashing across families bricks the ECU; the 7SM documentation
   * says so in exactly those words. */
  function hardwareFamily(hardware) {
    var m = /HW([0-9])/.exec(String(hardware || ''));
    return m ? m[1] : '';
  }

  var BRICK_WARNING = 'flashing an image from one hardware family into an '
    + 'ECU of another bricks the ECU - never flash HW1xx into HW3xx or '
    + 'vice versa';

  function SafetyGate(mode) {
    this.mode = mode || 'simulator';
    this.min_battery_v = 11.5;
    this.allow_programming = false;
    this.allow_unverified_keys = false;
    this.state = {
      identified: false, ecu_confidence: 'unknown', ecu_hardware: '',
      engine_running: null,
      battery_v: null, verified_backup: false, backup_path: '',
      /* An intact base map - the guaranteed way back to the calibration
       * the bike arrived with - is on file for this exact ECU. */
      base_map: false, base_map_path: '',
      checklist_accepted: false,
    };
    this._tokens = {};
    this.audit = [];
  }

  SafetyGate.prototype._record = function (decision) {
    this.audit.push({
      at: epoch(), allowed: decision.allowed, operation: decision.operation,
      risk: decision.risk, checks: decision.checks, reason: decision.reason,
    });
    if (this.audit.length > 200) this.audit.shift();
    if (HOOKS.event) HOOKS.event('safety', decision);
  };

  SafetyGate.prototype.evaluate = function (operation, risk, opts) {
    opts = opts || {};
    var profile = opts.profile || null;
    var checks = [];
    var simulated = this.mode === 'simulator';

    if (risk === 'read') {
      var readOnly = {
        allowed: true, operation: operation, risk: risk,
        checks: [{ name: 'read-only', passed: true, detail: '' }],
        reason: 'all preconditions satisfied', token: null,
      };
      this._record(readOnly);
      return readOnly;
    }

    var needed = {
      reversible: ['simulator', 'service', 'programming'],
      adaptation: ['simulator', 'service', 'programming'],
      irreversible: ['programming'],
    }[risk];
    checks.push({
      name: 'mode',
      passed: needed.indexOf(this.mode) !== -1,
      detail: 'mode is ' + this.mode + ', needs one of ' + needed.join(', '),
    });

    if (profile && opts.capability) {
      checks.push({
        name: 'capability',
        passed: profile.capabilities.indexOf(opts.capability) !== -1,
        detail: profile.family + " does not declare '" + opts.capability + "'",
      });
      checks.push({
        name: 'definition-confidence',
        passed: meets(profile.confidence),
        detail: profile.family + " definition is '" + profile.confidence
          + "'; control actions need 'documented' or better",
      });
    }

    checks.push({
      name: 'identified',
      passed: this.state.identified,
      detail: 'read the ECU identification block before commanding anything',
    });

    if (opts.requires_engine_off) {
      checks.push({
        name: 'engine-off',
        passed: this.state.engine_running === false,
        detail: 'engine must be stopped and its state must be observed first',
      });
    }
    if (opts.requires_engine_running) {
      checks.push({
        name: 'engine-running',
        passed: this.state.engine_running === true,
        detail: 'this operation only works with the engine running',
      });
    }

    if (!simulated) {
      var volts = this.state.battery_v;
      checks.push({
        name: 'stable-power',
        passed: volts !== null && volts >= this.min_battery_v,
        detail: 'battery reads ' + (volts === null ? 'unknown' : volts)
          + ' V, needs >= ' + this.min_battery_v + ' V (put it on a charger)',
      });
      checks.push({
        name: 'checklist',
        passed: this.state.checklist_accepted,
        detail: 'accept the hardware checklist for this session first',
      });
    }

    if (risk === 'irreversible') {
      checks.push({
        name: 'programming-enabled', passed: this.allow_programming,
        detail: 'ECU programming has not been enabled for this session.',
      });
      checks.push({
        name: 'verified-backup', passed: this.state.verified_backup,
        detail: 'take a full ECU backup and verify it by re-reading before writing',
      });
      /* A backup inside this session is not the same as having a way back
       * afterwards. The base map is the original verified calibration,
       * filed in its own vault and checked before every write. */
      checks.push({
        name: 'base-map', passed: this.state.base_map,
        detail: 'save a base map for this ECU first: a verified backup '
          + 'filed as the guaranteed restore image',
      });
      /* The hardware-family gate, ported with the rest of safety.py. It
       * runs only when a concrete candidate image is on the bench; the
       * write endpoint always passes one, so an HW1xx image aimed at an
       * HW3xx ECU is refused before a byte moves. */
      if (opts.image_hardware !== undefined
          || opts.image_embedded_hardware !== undefined) {
        checks.push(this._hardwareFamilyCheck(
          opts.image_hardware || '', opts.image_embedded_hardware || []
        ));
      }
    }

    var allowed = checks.every(function (c) { return c.passed; });
    var token = null;
    if (allowed) {
      token = 'demo-' + Math.random().toString(36).slice(2, 14);
      this._tokens[token] = { operation: operation, at: mono() };
    }
    var decision = {
      allowed: allowed, operation: operation, risk: risk, checks: checks,
      token: token,
      reason: allowed ? 'all preconditions satisfied'
        : checks.filter(function (c) { return !c.passed; })
          .map(function (c) { return c.name + ': ' + (c.detail || 'not satisfied'); })
          .join('; '),
    };
    this._record(decision);
    return decision;
  };

  /* Port of SafetyGate._hardware_family_check. Both pieces of evidence - the
   * provenance identity captured with the image and the IAW..HWnnn strings
   * embedded in its bytes - must agree with the identified ECU, and a file
   * with neither is refused rather than assumed fine. */
  SafetyGate.prototype._hardwareFamilyCheck = function (imageHardware, imageEmbedded) {
    var target = String(this.state.ecu_hardware || '').trim();
    var targetFamily = hardwareFamily(target);
    var provenance = String(imageHardware || '').trim();
    var provenanceFamily = hardwareFamily(provenance);
    var embedded = (imageEmbedded || []).filter(function (h) { return !!h; });
    var families = {};
    embedded.forEach(function (h) { families[hardwareFamily(h)] = true; });

    if (!targetFamily) {
      return {
        name: 'hardware-family', passed: false,
        detail: 'the ECU reported no usable hardware identity (' + (target || 'none')
          + '); identify it before writing anything',
      };
    }
    if (!provenanceFamily) {
      return {
        name: 'hardware-family', passed: false,
        detail: 'the image carries no captured hardware identity, so '
          + 'compatibility with the identified ECU (' + target + ') cannot be '
          + 'confirmed; writing is refused',
      };
    }
    if (provenanceFamily !== targetFamily) {
      return {
        name: 'hardware-family', passed: false,
        detail: 'image provenance reports ' + provenance + ', but the ECU '
          + 'reports ' + target + '; ' + BRICK_WARNING,
      };
    }
    if (embedded.length && !families[targetFamily]) {
      return {
        name: 'hardware-family', passed: false,
        detail: 'the image embeds ' + embedded.join(', ') + ', but the ECU '
          + 'reports ' + target + '; ' + BRICK_WARNING,
      };
    }
    return {
      name: 'hardware-family', passed: true,
      detail: embedded.length
        ? 'image matches the ECU\'s hardware family (' + target + ')'
        : 'image provenance matches the ECU\'s hardware family (' + target
          + '); the image embeds no hardware string of its own',
    };
  }

  SafetyGate.prototype.consume = function (token, operation) {
    var entry = token && this._tokens[token];
    if (!entry) {
      throw httpError(403, operation + ': no valid confirmation token; re-run the safety check', 'token');
    }
    delete this._tokens[token];
    if (entry.operation !== operation) {
      throw httpError(403, 'token was minted for ' + entry.operation + ', not ' + operation, 'token');
    }
    if (mono() - entry.at > 120) {
      throw httpError(403, operation + ': confirmation token has expired', 'token');
    }
  };

  /* ------------------------------------------------------ catalog helpers */

  function ecuPublic(ecuId) {
    var found = null;
    DATA.catalog.ecus.forEach(function (e) { if (e.id === ecuId) found = e; });
    if (!found) throw httpError(400, 'unknown ECU ' + ecuId, 'bad_request');
    return found;
  }

  function dtcDescriptions(ecuId) {
    var out = {};
    Object.keys(DATA.dtc_descriptions).forEach(function (k) {
      out[k] = DATA.dtc_descriptions[k];
    });
    var overrides = (DATA.profiles[ecuId] || {}).dtc_overrides || {};
    Object.keys(overrides).forEach(function (k) { out[k] = overrides[k]; });
    return out;
  }

  function vehicleMatches(model, year, make) {
    return DATA.vehicle_entries.filter(function (v) {
      if (model && v.model.toLowerCase() !== String(model).toLowerCase()) return false;
      if (make && v.make.toLowerCase() !== String(make).toLowerCase()) return false;
      if (year) {
        if (v.year_from > year) return false;
        if (v.year_to !== null && v.year_to !== undefined && year > v.year_to) return false;
      }
      return true;
    });
  }

  function supports(profile, capability) {
    if (profile.capabilities.indexOf(capability) === -1) return false;
    if (['identify', 'live', 'dtc_read'].indexOf(capability) !== -1) return true;
    return meets(profile.confidence);
  }

  /** guzzionboard/workstation.py :: _effective_profile */
  function effectiveProfile(entry, base) {
    var profile = JSON.parse(JSON.stringify(base));
    if (entry && entry.confidence !== profile.confidence
        && confidenceRank(entry.confidence) > confidenceRank(profile.confidence)) {
      profile.confidence = entry.confidence;
      profile.notes = 'Selected as ' + entry.make + ' ' + entry.model
        + ": this vehicle mapping is '" + entry.confidence + "' while the "
        + profile.family + " definition is '" + base.confidence + "'. The stricter "
        + 'level applies - the identifier tables below were captured on another '
        + 'make and are unverified here, so control actions stay disabled. The '
        + 'workstation does not ask the owner to validate cross-brand assumptions.';
    }
    profile.effective_capabilities = profile.capabilities.filter(function (c) {
      return supports(profile, c);
    });
    return profile;
  }

  /** guzzionboard/workstation.py :: _simulated_capable_profile */
  function simulatedCapableProfile(base) {
    var profile = JSON.parse(JSON.stringify(base));
    var memory = profile.memory || {};
    var regions = memory.regions || {};
    var flipped = [];
    Object.keys(regions).forEach(function (name) {
      var spec = regions[name];
      if (Number(spec.size || 0) && !spec.writable) {
        spec.writable = true;
        flipped.push(name);
      }
    });
    var hardwareReason = memory.write_blocked_reason || '';
    if (flipped.length) memory.write_supported = true;
    memory.write_blocked_reason = '';
    memory.simulated = true;
    memory.simulation_note = 'Simulated ECU: these capabilities are proven against '
      + 'the built-in protocol simulation, not against hardware.'
      + (hardwareReason ? ' Against a real ' + profile.family
        + ', writing stays refused: ' + hardwareReason : '');
    profile.memory = memory;
    if (flipped.length && profile.capabilities.indexOf('memory_write') === -1) {
      profile.capabilities = profile.capabilities.concat(['memory_write']);
    }
    profile.effective_capabilities = profile.capabilities.filter(function (c) {
      return supports(profile, c);
    });
    return profile;
  }

  /* ----------------------------------------------------------- the state */

  var WS = {
    selection: {
      make: '', model: '', year: 0, entry: null, profile: null,
      transport: 'simulator', device: '', can_overrides: {},
    },
    notices: [],
    gate: new SafetyGate('simulator'),
    ecu: null,              // SimEcu while connected
    sessionProfile: null,   // the profile in force for the session
    connected: false,
    init: null,
    identity: null,
    lastSamples: {},
    startedAt: null,
    counts: {},
    history: [],            // [[t, {key: value}]] for the derived window
  };

  function httpError(status, message, code, extra) {
    var err = new Error(message);
    err.status = status;
    err.payload = Object.assign({ error: message, code: code || 'error' }, extra || {});
    return err;
  }

  function localOnly(what) {
    return httpError(
      501,
      what + ' needs the local workstation: it touches files, serial ports or '
      + 'long-running jobs that a web page cannot. Run python3 run_server.py '
      + 'and open http://127.0.0.1:8000 for this view.',
      'demo_local_only'
    );
  }

  function requireService() {
    if (!WS.connected || !WS.ecu) throw httpError(409, 'connect to an ECU first', 'not_connected');
    return WS.ecu;
  }

  function requireCapability(capability, label) {
    var profile = WS.sessionProfile;
    if (!profile || profile.capabilities.indexOf(capability) === -1) {
      throw httpError(
        400,
        (profile ? profile.family : 'This ECU') + ': ' + label + ' is not validated',
        'protocol_error'
      );
    }
  }

  function bump(kind) { WS.counts[kind] = (WS.counts[kind] || 0) + 1; }

  function describeSelection() {
    var s = WS.selection;
    return {
      make: s.make, model: s.model, year: s.year,
      entry: s.entry, ecu: s.profile,
      transport: s.transport, device: s.device,
      can_overrides: s.can_overrides, notices: WS.notices,
    };
  }

  function transports() {
    return [{
      id: 'simulator', name: 'Demo motorcycle', available: true,
      detail: 'Everything stays in this browser tab; virtual ECU, bike, cable, and adapter are ready.',
      demo: true,
    }];
  }

  function sessionSummary() {
    if (!WS.startedAt) return null;
    return {
      id: 'browser-demo',
      path: '(not recorded — the hosted demo keeps nothing)',
      started_at: WS.startedAt,
      duration_s: Math.round((epoch() - WS.startedAt) * 10) / 10,
      counts: WS.counts,
      meta: {
        app_version: DATA.version,
        model: WS.selection.model,
        year: WS.selection.year,
        ecu: WS.selection.profile ? WS.selection.profile.id : '',
        ecu_family: WS.selection.profile ? WS.selection.profile.family : '',
        transport: WS.selection.transport,
        mode: WS.gate.mode,
        demo: true,
      },
    };
  }

  function diagnosticsStatus() {
    var profile = WS.sessionProfile;
    return {
      connected: true,
      transport: { name: 'simulator (browser)', physical: false },
      ecu: profile,
      init: {
        ok: true, method: 'simulated-fast', protocol: 'iso14230',
        detail: 'simulated ' + profile.family + ' — in-browser demo',
        key_bytes: [0xEA, 0x8F], attempts: [], handshake_complete: true,
      },
      identity: WS.identity,
      mode: WS.gate.mode,
      vehicle_state: WS.gate.state,
      active_outputs: activeOutputs(),
      samples: WS.lastSamples,
    };
  }

  function activeOutputs() {
    var out = {};
    var ecu = WS.ecu;
    if (!ecu) return out;
    Object.keys(ecu.activeOutputs).forEach(function (key) {
      var left = ecu.activeOutputs[key] - mono();
      if (left <= 0) delete ecu.activeOutputs[key];
      else out[key] = Math.round(left * 10) / 10;
    });
    return out;
  }

  function status() {
    var base = {
      version: DATA.version,
      selection: describeSelection(),
      mode: WS.gate.mode,
      connected: WS.connected,
      checklist: DATA.checklist,
      vehicle_state: WS.gate.state,
      session: sessionSummary(),
      audit: WS.gate.audit.slice(-20),
      transports: transports(),
      demo: true,
      demo_note: DEMO_HINT,
    };
    if (WS.connected) base.diagnostics = diagnosticsStatus();
    return base;
  }

  /* ------------------------------------------------------------ sampling */

  function publicParameters(profile) {
    return profile.parameters || [];
  }

  function readParameter(key) {
    var ecu = requireService();
    var profile = WS.sessionProfile;
    var meta = null;
    publicParameters(profile).forEach(function (p) { if (p.key === key) meta = p; });
    if (!meta) throw httpError(400, profile.id + ": no parameter '" + key + "'", 'bad_request');
    var internals = ecu.internals().parameters[key] || {};
    var bytes = ecu.rawFor(key);
    if (bytes === null) throw httpError(400, 'no local identifier for ' + key, 'bad_request');

    var offset = internals.offset || 0;
    var length = internals.length || (bytes.length - offset);
    var chunk = bytes.slice(offset, offset + length);
    var rawInt = 0;
    var ordered = (internals.endian === 'little') ? chunk.slice().reverse() : chunk;
    ordered.forEach(function (b) { rawInt = rawInt * 256 + b; });
    if (internals.signed) {
      var span = Math.pow(2, 8 * ordered.length);
      if (rawInt >= span / 2) rawInt -= span;
    }

    var value;
    if (internals.recip) value = rawInt ? internals.recip / rawInt : 0;
    else value = rawInt * (internals.scale === undefined ? 1 : internals.scale)
      + (internals.bias || 0);
    var digits = meta.digits === undefined ? 1 : meta.digits;
    value = digits ? Math.round(value * Math.pow(10, digits)) / Math.pow(10, digits)
      : Math.round(value);
    var text = (meta.states && meta.states[String(Math.trunc(rawInt))]) || '';

    var sample = {
      key: key, name: meta.name, local_id: meta.local_id,
      raw: bytes.map(hex2).join(' '), value: value, unit: meta.unit,
      text: text, at: epoch(), error: '',
    };
    WS.lastSamples[key] = sample;
    bump('sample');

    // Feed the safety gate from what was observed, never from assumptions.
    if (key === 'battery') WS.gate.state.battery_v = value;
    else if (key === 'rpm') WS.gate.state.engine_running = value > 200;
    else if (key === 'stop_state' && text) WS.gate.state.engine_running = text === 'Running';
    return sample;
  }

  function defaultParameterKeys(profile) {
    var defaults = publicParameters(profile).filter(function (p) { return p.default; });
    var list = defaults.length ? defaults : publicParameters(profile);
    return list.map(function (p) { return p.key; });
  }

  /* --------------------------------------------------- derived channels */
  /* Port of the arithmetic in guzzionboard/derived.py. Each value is
   * labelled derived=true, exactly as the Python side labels it. */

  var WINDOW_S = 60.0;

  function pushHistory(values) {
    var now = mono();
    WS.history.push([now, values]);
    while (WS.history.length && now - WS.history[0][0] > WINDOW_S) WS.history.shift();
  }

  function series(key) {
    var out = [];
    WS.history.forEach(function (row) {
      var v = row[1][key];
      if (typeof v === 'number') out.push([row[0], v]);
    });
    return out;
  }

  function span(key) {
    var values = series(key).map(function (p) { return p[1]; });
    if (values.length < 3) return null;
    return Math.max.apply(null, values) - Math.min.apply(null, values);
  }

  function ratePerMin(key) {
    var points = series(key);
    if (points.length < 3) return null;
    var a = points[0], b = points[points.length - 1];
    if (b[0] - a[0] < 5.0) return null;
    return (b[1] - a[1]) / (b[0] - a[0]) * 60.0;
  }

  var DERIVED_COMPUTE = {
    inj_duty: function (v) {
      if (!has(v, 'injection_ms', 'rpm') || v.rpm < 200) return null;
      return v.injection_ms * v.rpm / 1200.0;
    },
    idle_error: function (v) {
      if (!has(v, 'rpm', 'idle_target') || v.rpm < 200) return null;
      return v.rpm - v.idle_target;
    },
    stepper_drift: function (v) {
      if (!has(v, 'stepper_position', 'stepper_base')) return null;
      return v.stepper_position - v.stepper_base;
    },
    temp_split: function (v) {
      if (!has(v, 'coolant_temp', 'air_temp')) return null;
      return v.coolant_temp - v.air_temp;
    },
    warmup_rate: function () { return ratePerMin('coolant_temp'); },
    bank_balance: function (v) {
      if (!has(v, 'lambda_int_f', 'lambda_int_r')) return null;
      return v.lambda_int_f - v.lambda_int_r;
    },
    lambda_swing_f: function () { return span('lambda_f'); },
    lambda_swing_r: function () { return span('lambda_r'); },
    closed_loop_share: function () {
      var points = series('lambda_loop');
      if (points.length < 3) return null;
      var closed = points.filter(function (p) { return p[1] > 0; }).length;
      return closed / points.length * 100.0;
    },
    advance_split: function (v) {
      if (!has(v, 'advance', 'advance_latched')) return null;
      return v.advance - v.advance_latched;
    },
    charge_margin: function (v) {
      if (!has(v, 'battery')) return null;
      return v.battery - 12.8;
    },
  };

  function has(values) {
    for (var i = 1; i < arguments.length; i++) {
      if (typeof values[arguments[i]] !== 'number') return false;
    }
    return true;
  }

  function computeDerived(samples) {
    var values = {};
    samples.forEach(function (s) {
      if (typeof s.value === 'number') values[s.key] = s.value;
    });
    pushHistory(values);

    var byKey = {};
    publicParameters(WS.sessionProfile).forEach(function (p) { byKey[p.key] = p; });

    var out = [];
    (DATA.derived_channels || []).forEach(function (channel) {
      var fn = DERIVED_COMPUTE[channel.key];
      if (!fn) return;
      var value;
      try { value = fn(values); } catch (_) { value = null; }
      if (value === null || value === undefined || !isFinite(value)) return;
      // A derived channel inherits the worst confidence of its inputs.
      var confidence = 'verified-bench';
      channel.sources.forEach(function (src) {
        var p = byKey[src];
        if (p && confidenceRank(p.confidence) > confidenceRank(confidence)) {
          confidence = p.confidence;
        }
      });
      var digits = channel.digits === undefined ? 1 : channel.digits;
      out.push({
        key: channel.key, name: channel.name,
        value: Math.round(value * Math.pow(10, digits)) / Math.pow(10, digits),
        unit: channel.unit, group: channel.group, delta: channel.delta,
        note: channel.note, sources: channel.sources,
        confidence: confidence, derived: true,
      });
    });
    return out;
  }

  /* ------------------------------------------------------------- routes */

  var GET = {};
  var POST = {};

  GET['/api/catalog'] = function () { return [200, DATA.catalog]; };

  GET['/api/catalog/resolve'] = function (q) {
    var model = q.get('model') || '';
    var make = q.get('make') || '';
    var year = parseInt(q.get('year') || '0', 10) || 0;
    var matches = vehicleMatches(model, year, make);
    return [200, {
      model: model, make: make, year: year,
      ambiguous: matches.length > 1,
      matches: matches.map(function (m) {
        return Object.assign({}, m, { ecu_detail: ecuPublic(m.ecu) });
      }),
    }];
  };

  GET['/api/status'] = function () { return [200, status()]; };

  POST['/api/select'] = function (body) {
    var entry = null;
    var base;
    if (body.ecu) {
      base = ecuPublic(body.ecu);
    } else if (body.model && body.year) {
      var matches = vehicleMatches(body.model, parseInt(body.year, 10), body.make || '');
      if (!matches.length) {
        throw httpError(400, 'no catalog entry for ' + body.model + ' ' + body.year, 'bad_request');
      }
      matches.sort(function (a, b) {
        var wa = (a.year_to || 9999) - a.year_from;
        var wb = (b.year_to || 9999) - b.year_from;
        return wa - wb || b.year_from - a.year_from;
      });
      entry = matches[0];
      base = ecuPublic(entry.ecu);
    } else {
      throw httpError(400, 'select needs either an ecu id or a model and year', 'bad_request');
    }

    var profile = effectiveProfile(entry, base);
    WS.selection = {
      make: body.make || (entry ? entry.make : ''),
      model: body.model || profile.family,
      year: parseInt(body.year, 10) || 0,
      entry: entry,
      profile: profile,
      // Hosted demo is deliberately virtual-only. Ignore stale browser prefs
      // or crafted requests that name a physical transport.
      transport: 'simulator',
      device: 'demo://virtual-adapter',
      can_overrides: {},
    };

    var notices = [];
    if (entry && vehicleMatches(entry.model, entry.year_from, '').length > 1) {
      notices.push({
        level: 'warn',
        text: entry.model + ' spans more than one ECU family in this year. Moto '
          + 'Guzzi changed ECUs as running changes - read the label on your ECU '
          + 'and override the selection if it disagrees.',
      });
    }
    if (['inferred', 'unknown'].indexOf(profile.confidence) !== -1) {
      notices.push({
        level: 'warn',
        text: 'The ' + profile.family + " definition is marked '" + profile.confidence
          + "'. Control actions are disabled; identification, fault codes and the "
          + 'read-only discovery scan are available.',
      });
    }
    if (entry && entry.notes) notices.push({ level: 'info', text: entry.notes });
    WS.notices = notices;
    return [200, describeSelection()];
  };

  POST['/api/connect'] = function () {
    if (!WS.selection.profile) throw httpError(400, 'select a vehicle before connecting', 'bad_request');
    if (WS.connected) return [200, status()];

    WS.selection.transport = 'simulator';
    WS.selection.device = 'demo://virtual-adapter';
    WS.gate = new SafetyGate('simulator');
    WS.sessionProfile = simulatedCapableProfile(WS.selection.profile);
    WS.ecu = new SimEcu(WS.selection.profile.id);
    WS.connected = true;
    WS.identity = null;
    WS.lastSamples = {};
    WS.history = [];
    WS.startedAt = epoch();
    WS.counts = { session_start: 1 };
    WS.gate.state.ecu_confidence = WS.sessionProfile.confidence;
    // Browser-only fixtures are already attached and cannot lock a real ECU,
    // so remove setup dead-ends while preserving operation tokens and backup
    // requirements in the workflow itself.
    WS.gate.state.checklist_accepted = true;
    WS.gate.allow_unverified_keys = true;
    if (HOOKS.event) HOOKS.event('connect', sessionSummary());
    return [200, status()];
  };

  POST['/api/disconnect'] = function () {
    if (HOOKS.event) HOOKS.event('disconnect', sessionSummary());
    WS.connected = false;
    WS.ecu = null;
    WS.sessionProfile = null;
    WS.identity = null;
    WS.lastSamples = {};
    WS.history = [];
    // The hardware identity leaves with the session that produced it; a
    // string from ECU A must never vouch for ECU B.
    if (WS.gate) WS.gate.state.ecu_hardware = '';
    return [200, status()];
  };

  POST['/api/checklist'] = function (body) {
    WS.gate.state.checklist_accepted = !!body.accepted;
    return [200, { ok: true, vehicle_state: WS.gate.state }];
  };

  GET['/api/identify'] = function () {
    var ecu = requireService();
    requireCapability('identify', 'identification request');
    WS.identity = ecu.identity();
    WS.gate.state.identified = true;
    WS.gate.state.ecu_confidence = WS.sessionProfile.confidence;
    // Recorded from the ECU's own answer, exactly like the Python side, so
    // the write path's hardware-family gate compares against what is
    // actually on the bench - never the selection or a filename.
    WS.gate.state.ecu_hardware = String(
      (WS.identity && WS.identity.fields && WS.identity.fields.Hardware) || ''
    ).trim();
    bump('action');
    return [200, WS.identity];
  };

  GET['/api/parameters'] = function () {
    var profile = WS.sessionProfile || WS.selection.profile;
    if (!profile) throw httpError(409, 'select a vehicle first', 'not_connected');
    return [200, { parameters: publicParameters(profile) }];
  };

  GET['/api/derived'] = function () {
    return [200, {
      channels: (DATA.derived_channels || []).map(function (c) {
        return {
          key: c.key, name: c.name, unit: c.unit, group: c.group,
          sources: c.sources, note: c.note, delta: c.delta,
        };
      }),
      note: 'Derived channels are computed by the workstation from samples, '
        + 'never read from the ECU.',
    }];
  };

  GET['/api/live'] = function (q) {
    requireService();
    requireCapability('live', 'live-data requests');
    var keys = (q.get('keys') || '').split(',').filter(Boolean);
    if (!keys.length) keys = defaultParameterKeys(WS.sessionProfile);
    var samples = keys.map(function (k) { return readParameter(k); });
    // demo-lab.js adds the plausibility findings, the comms-quality effects
    // and the session recording; it may answer asynchronously (added
    // latency is latency, not a lie about latency).
    if (HOOKS.live) return HOOKS.live(samples, keys);
    return [200, {
      at: epoch(),
      samples: samples,
      derived: computeDerived(samples),
      findings: [],
      analysis_note: 'Derived values are computed by the workstation from the '
        + 'samples above, not read from the ECU. Findings are interpretations, '
        + 'not measurements.',
    }];
  };

  GET['/api/dtcs'] = function () {
    var ecu = requireService();
    requireCapability('dtc_read', 'fault-memory request');
    var dtcs = ecu.readDtcs();
    var context = {};
    var contextKeys = WS.sessionProfile.capabilities.indexOf('live') !== -1
      ? defaultParameterKeys(WS.sessionProfile).slice(0, 8) : [];
    contextKeys.forEach(function (key) {
      try {
        var s = readParameter(key);
        context[key] = { name: s.name, value: s.value, unit: s.unit };
      } catch (_) { /* a channel that fails is skipped, not faked */ }
    });
    bump('action');
    if (HOOKS.event) HOOKS.event('dtcs', dtcs);
    return [200, {
      dtcs: dtcs,
      context: context,
      context_note: 'Observed by the workstation at read time - these ECUs do '
        + 'not expose an ECU-stored freeze frame, and this is not one.',
      clear: WS.gate.evaluate('clear-dtcs', 'adaptation', {
        profile: WS.sessionProfile, capability: 'dtc_clear',
      }),
    }];
  };

  POST['/api/dtcs/clear'] = function (body) {
    var ecu = requireService();
    WS.gate.consume(body.token, 'clear-dtcs');
    ecu.clearDtcs();
    bump('action');
    return [200, { ok: true, remaining: ecu.readDtcs() }];
  };

  GET['/api/actuators'] = function () {
    requireService();
    var profile = WS.sessionProfile;
    var out = (profile.actuators || []).map(function (a) {
      return Object.assign({}, a, {
        decision: WS.gate.evaluate('actuator:' + a.key, 'reversible', {
          profile: profile, capability: 'actuators',
          requires_engine_off: a.requires_engine_off,
          requires_engine_running: a.requires_engine_running,
        }),
      });
    });
    return [200, { actuators: out, active: activeOutputs() }];
  };

  POST['/api/actuators/pulse'] = function (body) {
    var ecu = requireService();
    var actuator = null;
    (WS.sessionProfile.actuators || []).forEach(function (a) {
      if (a.key === body.key) actuator = a;
    });
    if (!actuator) throw httpError(400, 'no actuator ' + body.key, 'bad_request');
    WS.gate.consume(body.token, 'actuator:' + body.key);
    var duration = Math.max(0.2, Math.min(
      Number(body.seconds || actuator.max_pulse_s), actuator.max_pulse_s
    ));
    ecu.activeOutputs[body.key] = mono() + duration;
    bump('action');
    if (HOOKS.event) HOOKS.event('action', { name: 'actuator_pulse', detail: { key: body.key, seconds: duration } });
    return [200, { ok: true, key: body.key, duration_s: duration }];
  };

  POST['/api/actuators/release'] = function (body) {
    var ecu = requireService();
    delete ecu.activeOutputs[body.key];
    return [200, { ok: true, key: body.key }];
  };

  GET['/api/routines'] = function () {
    requireService();
    var profile = WS.sessionProfile;
    var out = (profile.routines || []).map(function (r) {
      return Object.assign({}, r, {
        decision: WS.gate.evaluate('routine:' + r.key,
          r.reversible ? 'reversible' : 'adaptation', {
            profile: profile, capability: r.key,
            requires_engine_off: r.requires_engine_off,
            requires_engine_running: r.requires_engine_running,
          }),
      });
    });
    return [200, { routines: out }];
  };

  POST['/api/routines/run'] = function (body) {
    requireService();
    var routine = null;
    (WS.sessionProfile.routines || []).forEach(function (r) {
      if (r.key === body.key) routine = r;
    });
    if (!routine) throw httpError(400, 'no routine ' + body.key, 'bad_request');
    WS.gate.consume(body.token, 'routine:' + body.key);
    var internals = (WS.ecu.internals().routines || {})[body.key] || {};
    var response = routine.service === 0x31
      ? '71 ' + hex2(routine.local_id)
        + (internals.expect !== null && internals.expect !== undefined
          ? ' ' + hex2(internals.expect) : '')
      : '70 ' + hex2(routine.local_id);
    bump('action');
    return [200, {
      ok: true, key: body.key, name: routine.name,
      response: response, follow_up: routine.follow_up,
    }];
  };

  POST['/api/discover'] = function (body) {
    var ecu = requireService();
    requireCapability('discover', 'identifier discovery');
    var start = Math.max(0, Math.min(255, parseInt(body.start, 10) || 0x30));
    var end = Math.max(0, Math.min(255, parseInt(body.end, 10) || 0x7F));
    var byId = {};
    publicParameters(WS.sessionProfile).forEach(function (p) { byId[p.local_id] = p; });
    var internals = ecu.internals().parameters;
    var deadById = {};
    Object.keys(internals).forEach(function (k) {
      if (internals[k].dead) deadById[internals[k].local_id] = true;
    });

    var identifiers = [];
    for (var id = start; id <= end; id++) {
      var param = byId[id];
      var bytes = null;
      if (param) bytes = ecu.rawFor(param.key);
      else if (deadById[id]) bytes = [0x00, 0x00];
      if (bytes) {
        var intBe = 0;
        bytes.forEach(function (b) { intBe = intBe * 256 + b; });
        identifiers.push({
          local_id: id, hex_id: '0x' + hex2(id).toUpperCase(),
          length: bytes.length, raw: bytes.map(hex2).join(' '),
          int_be: intBe, answered: true,
        });
      } else {
        identifiers.push({
          local_id: id, hex_id: '0x' + hex2(id).toUpperCase(),
          answered: false, nrc: 0x12,
        });
      }
    }
    bump('action');
    return [200, {
      range: [start, end],
      answered: identifiers.filter(function (i) { return i.answered; }).length,
      scanned: identifiers.length,
      identifiers: identifiers,
    }];
  };

  /* -------------------------------------------------- simulator controls */

  function simPayload() {
    var ecu = WS.ecu;
    var active = ecu.engine.faults;
    return {
      available: true,
      transport: 'simulator',
      engine: ecu.engine.asDict(),
      faults: (DATA.sim_faults || []).map(function (f) {
        return Object.assign({}, f, { active: !!active[f.key] });
      }),
      comms: ecu.comms,
      dtc_timing: { pending_after: ecu.pendingAfter, confirm_after: ecu.confirmAfter },
      note: 'This is the simulated motorcycle, not a setting on a real one. '
        + 'Seeded faults change the live channels first and mature into fault '
        + 'memory afterwards.',
    };
  }

  GET['/api/sim'] = function () {
    if (!WS.connected || !WS.ecu) {
      return [200, {
        available: false,
        transport: WS.selection.transport,
        faults: DATA.sim_faults,
        reason: 'Connect with the simulator to drive the simulated engine.',
      }];
    }
    return [200, simPayload()];
  };

  POST['/api/sim/engine'] = function (body) {
    if (!WS.connected || !WS.ecu) throw httpError(400, 'not connected to a simulated ECU', 'bad_request');
    var e = WS.ecu.engine;
    if ('running' in body) { if (body.running) e.start(); else e.stop(); }
    if ('throttle_pct' in body) {
      e.throttle_pct = clamp(Number(body.throttle_pct), 0, 100);
      e.auto_blip = false;
    }
    if ('ambient_c' in body) e.ambient_c = clamp(Number(body.ambient_c), -30, 55);
    if ('battery_health' in body) e.battery_health = clamp(Number(body.battery_health), 0.5, 1.1);
    if ('in_gear' in body) e.in_gear = !!body.in_gear;
    if ('auto_blip' in body) e.auto_blip = !!body.auto_blip;
    if ('advance_s' in body) e.advance(clamp(Number(body.advance_s), 0, 3600));
    return [200, simPayload()];
  };

  POST['/api/sim/faults'] = function (body) {
    if (!WS.connected || !WS.ecu) throw httpError(400, 'not connected to a simulated ECU', 'bad_request');
    var engine = WS.ecu.engine;
    var requested;
    if ('faults' in body) {
      requested = body.faults || [];
    } else {
      requested = engine.faultKeys();
      var key = body.key;
      if (key) {
        requested = requested.filter(function (k) { return k !== key; });
        if (body.active) requested.push(key);
      }
    }
    engine.setFaults(requested);
    return [200, simPayload()];
  };

  POST['/api/sim/comms'] = function (body) {
    if (!WS.connected || !WS.ecu) throw httpError(400, 'not connected to a simulated ECU', 'bad_request');
    var c = WS.ecu.comms;
    ['drop_rate', 'corrupt_rate', 'pending_rate'].forEach(function (k) {
      if (k in body) c[k] = clamp(Number(body[k]), 0, 1);
    });
    if ('extra_latency' in body) c.extra_latency = clamp(Number(body.extra_latency), 0, 5);
    /* Honesty: with demo-lab.js loaded these knobs really do spoil the
     * simulated reads; without it there is nothing to spoil, so say which. */
    c.note = HOOKS.comms
      ? 'There is no wire here, so these spoil the simulated one: dropped '
        + 'frames come back as timeouts, corrupted ones as checksum errors, '
        + 'responsePending adds a wait and the latency really is waited out.'
      : 'Fault injection on the wire needs the real protocol stack — these '
        + 'knobs are recorded here but only the local workstation acts on them.';
    return [200, simPayload()];
  };

  /* -------------------------------------------------------- sessions etc */

  GET['/api/sessions'] = function () {
    return [200, {
      sessions: [],
      note: 'The hosted demo records nothing: session logs are files, and this '
        + 'page has no disk. The local workstation writes every frame and '
        + 'sample to ~/.guzzionboard/sessions.',
    }];
  };

  GET['/api/security'] = function () {
    return [200, {
      providers: {
        '5am': [{
          ecu_id: '5am', name: 'virtual-demo-unlock', verified: true,
          note: 'Virtual demo provider. It unlocks only the synthetic image in '
            + 'this browser and never computes a key for real hardware.',
          source: 'in-browser fixture',
        }],
      },
      plugin_dir: 'demo://virtual-key-providers',
      unverified_keys_accepted: !!WS.gate.allow_unverified_keys,
      simulated: true,
      demo: true,
    }];
  };

  /* Everything below needs files, ports or long jobs: refused, not faked. */
  var LOCAL_ONLY = {
    '/api/procedures': 'Guided tests',
    '/api/procedures/start': 'Guided tests',
    '/api/procedures/advance': 'Guided tests',
    '/api/procedures/abort': 'Guided tests',
    '/api/memory': 'ECU memory',
    '/api/memory/progress': 'ECU memory',
    '/api/memory/backup': 'ECU backup',
    '/api/memory/read': 'ECU memory read',
    '/api/memory/validate': 'Firmware validation',
    '/api/memory/write': 'ECU programming',
    '/api/memory/check-write': 'ECU programming',
    '/api/programming/enable': 'ECU programming',
    '/api/programming/disable': 'ECU programming',
    '/api/security/unverified': 'Key-provider opt-in',
    '/api/maps': 'Maps & tables',
    '/api/checksum-providers': 'Calibration checksum plugin registry',
    '/api/recommendations': 'Recommendation package registry',
    '/api/recommendations/validate': 'Recommendation package validator',
    '/api/physical-validation': 'Physical validation evidence registry',
    '/api/physical-validation/validate': 'Physical validation manifest validator',
    '/api/protocol-updates': 'Signed protocol update registry',
    '/api/protocol-updates/check': 'Signed protocol update check',
    '/api/protocol-updates/apply': 'Signed protocol update apply',
    '/api/protocol-updates/revert': 'Signed protocol update revert',
    '/api/protocol-updates/pin-key': 'Protocol update key pinning',
    '/api/protocol-updates/unpin-key': 'Protocol update key pinning',
    '/api/confirmations/build': 'Field confirmation builder',
    '/api/confirmations/verify': 'Field confirmation verifier',
    '/api/confirmations/validate': 'Field confirmation validator',
    '/api/maps/render': 'Maps & tables',
    '/api/maps/diff': 'Map diff',
    '/api/maps/validate-definition': 'Calibration definition validator',
    '/api/maps/analyze-log': 'Offline map log overlay',
    '/api/maps/preview': 'Map build preview',
    '/api/maps/build': 'Evidence-backed map builder',
    '/api/report': 'Report export',
    '/api/sessions/events': 'Session events',
    '/api/sessions/replay': 'Session replay',
    '/api/sessions/export': 'Session export',
    '/api/sessions/compare': 'Session comparison',
    '/api/adapter': 'Adapter pre-flight',
    '/api/adapter/latency': 'Adapter pre-flight',
    '/api/tools/gearing': 'The gearing calculator',
    '/api/tools/canlog': 'CAN capture analysis',
    '/api/tools/klinelog': 'K-Line capture analysis',
    '/api/tools/z2dif': 'Zeitronix log conversion',
    '/api/tools/rpmsignal': 'The bench RPM signal generator',
  };

  /* ------------------------------------------------------------ dispatch */

  function respond(status, payload) {
    return new Response(JSON.stringify(payload), {
      status: status,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  async function handle(path, query, method, body) {
    await dataPromise;
    var table = method === 'GET' ? GET : POST;
    var handler = table[path];
    if (!handler) {
      if (LOCAL_ONLY[path]) throw localOnly(LOCAL_ONLY[path]);
      throw httpError(404, 'no route ' + path, 'not_found');
    }
    var result = handler(method === 'GET' ? query : (body || {}));
    return result;
  }

  var realFetch = window.fetch.bind(window);

  window.fetch = function (input, init) {
    var url = typeof input === 'string' ? input : (input && input.url) || '';
    var isApi = url.indexOf('/api/') === 0 || url.indexOf('api/') === 0;
    if (!isApi) return realFetch(input, init);

    var method = ((init && init.method) || 'GET').toUpperCase();
    var parsed = new URL(url, window.location.href);
    var body = {};
    if (init && init.body) {
      try { body = JSON.parse(init.body); } catch (_) { body = {}; }
    }

    return handle(parsed.pathname.replace(/^.*(\/api\/)/, '/api/'),
      parsed.searchParams, method, body)
      .then(function (result) { return respond(result[0], result[1]); })
      .catch(function (err) {
        if (err && err.payload) return respond(err.status || 400, err.payload);
        return respond(500, { error: String(err && err.message || err), code: 'demo' });
      });
  };

  /* ------------------------------------------------------------- the UI */
  /* A demo that quietly behaves differently would be dishonest: say so on
   * the page, and mark the views that only the local workstation can serve. */

  /* Per-view notices, as raw HTML: demo-lab.js replaces the ones it has
   * taken over with an honest "this is simulated" note instead. */
  var LOCAL_ONLY_VIEWS = {
    procedures: '<b>Local workstation only.</b> Guided tests drive timed '
      + 'sequences against the ECU and keep a transcript.',
    firmware: '<b>Local workstation only.</b> Reading, backing up, validating '
      + 'and writing ECU memory moves files around and takes twenty minutes '
      + 'a pass.',
    tools: '<b>Local workstation only.</b> The gearing calculator, log '
      + 'conversion, bench RPM signal and capture analysis all run in the '
      + 'Python process.',
    sessions: '<b>Local workstation only.</b> Sessions are JSONL files on '
      + 'disk. This page records nothing.',
    report: '<b>Local workstation only.</b> Reports are written out as text, '
      + 'JSON and PDF by the local tool.',
  };

  var UI = {
    banner: '<b>Hosted demo</b> — a virtual motorcycle, ECU, connector, adapter, '
      + 'files, and workshop session running entirely in this browser. Nothing '
      + 'here can connect to real hardware. '
      + '<a href="../index.html">About GuzziOnBoard</a>',
  };

  function decorate() {
    document.body.dataset.demo = 'true';

    // Keep the hosted product tour virtual-only. The installed application
    // retains every hardware control; this page exposes one ready-to-run demo
    // motorcycle and virtual stand-ins for connector-dependent steps.
    var heading = document.getElementById('connectionHeading');
    if (heading) heading.textContent = '2 · Start the demo';
    var modeField = document.getElementById('sessionModeField');
    if (modeField) modeField.hidden = true;
    var connectionTip = document.getElementById('connectionTip');
    if (connectionTip) connectionTip.innerHTML = 'Pick a motorcycle, then start the demo. '
      + 'The ECU, motorcycle, cable, adapter, files, and long-running jobs are all virtual.';
    var connectButton = document.getElementById('connectBtn');
    if (connectButton) connectButton.textContent = 'Start demo';
    var disconnectButton = document.getElementById('disconnectBtn');
    if (disconnectButton) disconnectButton.textContent = 'Reset demo';
    var override = document.getElementById('ecuOverride');
    var overrideDetails = override && override.closest ? override.closest('details') : null;
    if (overrideDetails) overrideDetails.hidden = true;
    var disclaimer = document.querySelector('.disclaimer');
    if (disclaimer) disclaimer.textContent = 'Hosted demo only — nothing on this page can connect to a motorcycle or ECU.';

    ['canlogFileControls', 'klinelogFileControls'].forEach(function (id) {
      var controls = document.getElementById(id);
      if (controls) controls.hidden = true;
    });
    Array.prototype.forEach.call(document.querySelectorAll('.hardware-capture-help'), function (el) {
      el.hidden = true;
    });

    var adapterPort = document.getElementById('adapterPort');
    if (adapterPort) adapterPort.value = 'demo://virtual-kline';
    var adapterHelp = document.getElementById('adapterHelp');
    if (adapterHelp) adapterHelp.innerHTML = '<b>Demo connector.</b> Run this virtual pre-flight '
      + 'to see the adapter checks without installing drivers or attaching a cable.';
    var adapterButton = document.getElementById('adapterBtn');
    if (adapterButton) adapterButton.textContent = 'Run virtual pre-flight';
    var ack = document.getElementById('ackInput');
    if (ack) ack.value = 'I have a verified backup and accept the risk';
    var keys = document.getElementById('unverifiedKeysChk');
    if (keys) keys.checked = true;
    var securityPanel = document.getElementById('securityPanel');
    if (securityPanel) securityPanel.hidden = true;

    var canSample = document.getElementById('canlogText');
    if (canSample) canSample.value = [
      '(1.000) can0 7E0#0210C0AAAAAAAA',
      '(1.010) can0 7E8#0650C0AAAAAAAA',
      '(1.100) can0 7E0#021A80AAAAAAAA',
      '(1.110) can0 7E8#10145A80313233',
      '(1.120) can0 7E0#3000000000000000',
      '(2.000) can0 7E0#023E00AAAAAAAA',
    ].join('\n');
    var canPaste = document.getElementById('canlogPasteBtn');
    if (canPaste) canPaste.textContent = 'Analyze sample CAN log';
    var klineSample = document.getElementById('klinelogText');
    if (klineSample) klineSample.value = [
      '0.000 tx 80 10 F1 02 21 30 1D',
      '0.020 rx 80 F1 10 04 61 30 0B B8',
      '0.100 tx 80 10 F1 02 21 30 1D',
      '0.120 rx 80 F1 10 04 61 30 0C 1A',
    ].join('\n');
    var klinePaste = document.getElementById('klinelogPasteBtn');
    if (klinePaste) klinePaste.textContent = 'Analyze sample K-Line log';

    var bar = document.createElement('div');
    bar.id = 'demoBanner';
    bar.innerHTML = UI.banner;
    bar.setAttribute('style', [
      'position:relative', 'z-index:5', 'padding:10px 18px',
      'background:#3a2a16', 'color:#f0d9a8',
      'border-bottom:1px solid #6b4f24', 'font-size:13px', 'line-height:1.5',
    ].join(';'));
    var main = document.querySelector('main') || document.body;
    var topbar = main.querySelector ? main.querySelector('.topbar') : null;
    if (topbar && topbar.nextSibling) main.insertBefore(bar, topbar.nextSibling);
    else main.insertBefore(bar, main.firstChild);

    Object.keys(LOCAL_ONLY_VIEWS).forEach(function (view) {
      var el = document.getElementById(view);
      if (!el) return;
      var note = document.createElement('div');
      note.className = 'notice warn';
      note.setAttribute('style', [
        'margin:0 0 16px', 'padding:12px 14px', 'border-radius:8px',
        'background:#2a2118', 'border:1px solid #6b4f24', 'color:#f0d9a8',
      ].join(';'));
      note.innerHTML = LOCAL_ONLY_VIEWS[view];
      el.insertBefore(note, el.firstChild);
    });

    // Comms quality degrades a real wire: dropped frames, bad checksums,
    // responsePending, added latency. There is no wire here, so rather than
    // move sliders that do nothing, turn them off and say why.
    var drop = document.getElementById('simDrop');
    var panel = drop && drop.closest ? drop.closest('.panel') : null;
    if (panel && !HOOKS.comms) {
      ['simDrop', 'simCorrupt', 'simPending', 'simLatency'].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) { el.disabled = true; el.title = 'Local workstation only'; }
      });
      var commsNote = document.createElement('p');
      commsNote.className = 'muted small';
      commsNote.innerHTML = '<b>Local workstation only.</b> Dropping frames and '
        + 'corrupting checksums needs the real KWP2000 stack underneath — '
        + 'this page has no wire to spoil.';
      panel.appendChild(commsNote);
    }

    document.title = 'GuzziOnBoard — workstation demo (in-browser)';
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', decorate);
  } else {
    decorate();
  }

  /* What demo-lab.js builds on. Keeping this to one small object means the
   * second file can simulate a view without reaching into this one's guts. */
  window.GUZZI_DEMO = {
    data: dataPromise,
    state: WS,
    hooks: HOOKS,
    ui: UI,
    views: LOCAL_ONLY_VIEWS,
    localOnly: LOCAL_ONLY,
    /* Take over a route: the handler may return [status, payload] or a
     * promise of one, and the 501 'local only' entry for it is dropped. */
    register: function (method, path, handler) {
      (String(method).toUpperCase() === 'GET' ? GET : POST)[path] = handler;
      delete LOCAL_ONLY[path];
    },
    helpers: {
      httpError: httpError, localOnly: localOnly, requireService: requireService,
      clamp: clamp, hex2: hex2, rng: rng, mono: mono, epoch: epoch,
      readParameter: readParameter, publicParameters: publicParameters,
      defaultParameterKeys: defaultParameterKeys, computeDerived: computeDerived,
      ecuPublic: ecuPublic, status: status, sessionSummary: sessionSummary,
      describeSelection: describeSelection, bump: bump,
      data: function () { return DATA; },
    },
  };
}());
