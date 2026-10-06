/* GuzziOnBoard — hosted demo, part two: the simulated workbench.
 * ===========================================================================
 *
 * ``demo-api.js`` answers the conversational half of the ``/api`` seam in the
 * browser: garage, connect, identify, live data, fault codes, service
 * actions. Everything else used to answer 501 "local workstation only",
 * because it touches files, serial ports or twenty-minute jobs.
 *
 * This file simulates that other half instead of refusing it:
 *
 *   * ECU memory — read, backup, validate, write and verify a *synthesised*
 *     flash image held in a virtual filesystem in this tab. A real 5AM read
 *     is about twenty minutes; here it is about three seconds, and the
 *     progress line says so while it runs.
 *   * Maps & tables — the bundled TunerPro XDFs are ordinary files in this
 *     repository, so the browser fetches them and parses them with a port of
 *     ``guzzionboard/maps.py``. The dump they are rendered against is the
 *     synthesised image: the *definitions* are real, the *calibration* is
 *     invented and is labelled as such everywhere it is shown.
 *   * Sessions — recording, replay, CSV export and comparison, over sessions
 *     this page records in memory (plus two canned ones so the view has
 *     something to compare on a fresh load).
 *   * Reports — the same text report the Python workstation writes.
 *   * Guided tests — the real step lists from ``procedures.py`` with the
 *     observation windows time-compressed against the simulated engine.
 *   * Tools — gearing, Zeitronix→DIF, the bench RPM WAV generator, and the
 *     CAN/K-Line capture analysers (pasted text only: no disk here).
 *   * Comms quality — the drop/corrupt/pending/latency sliders now actually
 *     spoil the reads, at the API seam rather than on a wire.
 *
 * Two things are still refused rather than faked, on purpose:
 *
 *   * opening a real serial port or CAN interface from a web page, and
 *   * anything that reads or writes a file on your machine.
 *
 * A simulation that is announced is a demonstration; one that is not is a
 * lie. Every payload below carries ``simulated: true`` and a note, and the
 * UI is decorated to match.
 */
(function () {
  'use strict';

  var D = window.GUZZI_DEMO;
  if (!D) return;                       // live backend: demo-api stood down
  var H = D.helpers;
  var WS = D.state;
  var httpError = H.httpError;
  var clamp = H.clamp;
  var epoch = H.epoch;
  var mono = H.mono;
  var data = H.data;

  var SIM = 'Simulated in your browser — no motorcycle, no serial port and '
    + 'no files were involved.';

  function bad(message, extra) {
    return httpError(400, message, 'bad_request', extra);
  }

  /* Python's round() is half-to-even, and the rendered tables are compared
   * against the Python original in the test harness, so match it. */
  function round(value, digits) {
    var f = Math.pow(10, digits || 0);
    var scaled = value * f;
    var rounded = Math.round(scaled);
    if (Math.abs(scaled - Math.trunc(scaled)) === 0.5) {
      rounded = 2 * Math.round(scaled / 2);
    }
    return rounded / f;
  }

  function pad(text, width) {
    text = String(text);
    while (text.length < width) text += ' ';
    return text;
  }

  var rand = H.rng(20261006);

  /* ======================================================================
   * 1. Digests
   * ======================================================================
   * An image description carries md5 and sha256 because the workstation's
   * does. Computing them here (rather than omitting them, or inventing
   * them) keeps the demo's output comparable with the real tool's: the same
   * bytes give the same digests on both sides.
   */

  function md5(bytes) {
    var S = [7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22,
      5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
      4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23,
      6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21];
    var K = new Int32Array(64);
    for (var ki = 0; ki < 64; ki++) {
      K[ki] = (Math.floor(Math.abs(Math.sin(ki + 1)) * 4294967296)) | 0;
    }
    var a0 = 0x67452301, b0 = 0xefcdab89, c0 = 0x98badcfe, d0 = 0x10325476;
    var length = bytes.length;
    var padded = new Uint8Array(((length + 8 >> 6) + 1) << 6);
    padded.set(bytes);
    padded[length] = 0x80;
    var bitsLo = (length << 3) >>> 0;
    var bitsHi = Math.floor(length / 536870912);
    var tail = padded.length - 8;
    padded[tail] = bitsLo & 0xFF;
    padded[tail + 1] = (bitsLo >>> 8) & 0xFF;
    padded[tail + 2] = (bitsLo >>> 16) & 0xFF;
    padded[tail + 3] = (bitsLo >>> 24) & 0xFF;
    padded[tail + 4] = bitsHi & 0xFF;

    var M = new Int32Array(16);
    for (var off = 0; off < padded.length; off += 64) {
      for (var j = 0; j < 16; j++) {
        M[j] = padded[off + j * 4] | (padded[off + j * 4 + 1] << 8)
          | (padded[off + j * 4 + 2] << 16) | (padded[off + j * 4 + 3] << 24);
      }
      var A = a0, B = b0, C = c0, Dd = d0;
      for (var i = 0; i < 64; i++) {
        var F, g;
        if (i < 16) { F = (B & C) | (~B & Dd); g = i; }
        else if (i < 32) { F = (Dd & B) | (~Dd & C); g = (5 * i + 1) % 16; }
        else if (i < 48) { F = B ^ C ^ Dd; g = (3 * i + 5) % 16; }
        else { F = C ^ (B | ~Dd); g = (7 * i) % 16; }
        F = (F + A + K[i] + M[g]) | 0;
        A = Dd; Dd = C; C = B;
        B = (B + ((F << S[i]) | (F >>> (32 - S[i])))) | 0;
      }
      a0 = (a0 + A) | 0; b0 = (b0 + B) | 0;
      c0 = (c0 + C) | 0; d0 = (d0 + Dd) | 0;
    }
    return [a0, b0, c0, d0].map(function (word) {
      var out = '';
      for (var n = 0; n < 4; n++) {
        out += ('0' + ((word >>> (n * 8)) & 0xFF).toString(16)).slice(-2);
      }
      return out;
    }).join('');
  }

  function sha256(bytes) {
    var K = [
      0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
      0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
      0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
      0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
      0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
      0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
      0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
      0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
      0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
      0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
      0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2];
    var h = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
      0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    var length = bytes.length;
    var padded = new Uint8Array((((length + 8) >> 6) + 1) << 6);
    padded.set(bytes);
    padded[length] = 0x80;
    var bits = length * 8;
    var view = new DataView(padded.buffer);
    view.setUint32(padded.length - 8, Math.floor(bits / 4294967296));
    view.setUint32(padded.length - 4, bits >>> 0);

    var w = new Int32Array(64);
    for (var off = 0; off < padded.length; off += 64) {
      for (var i = 0; i < 16; i++) w[i] = view.getInt32(off + i * 4);
      for (i = 16; i < 64; i++) {
        var x = w[i - 15], y = w[i - 2];
        var s0 = ((x >>> 7) | (x << 25)) ^ ((x >>> 18) | (x << 14)) ^ (x >>> 3);
        var s1 = ((y >>> 17) | (y << 15)) ^ ((y >>> 19) | (y << 13)) ^ (y >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
      }
      var a = h[0], b = h[1], c = h[2], d = h[3];
      var e = h[4], f = h[5], g = h[6], hh = h[7];
      for (i = 0; i < 64; i++) {
        var S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
        var ch = (e & f) ^ (~e & g);
        var t1 = (hh + S1 + ch + K[i] + w[i]) | 0;
        var S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
        var maj = (a & b) ^ (a & c) ^ (b & c);
        var t2 = (S0 + maj) | 0;
        hh = g; g = f; f = e; e = (d + t1) | 0;
        d = c; c = b; b = a; a = (t1 + t2) | 0;
      }
      h[0] = (h[0] + a) | 0; h[1] = (h[1] + b) | 0;
      h[2] = (h[2] + c) | 0; h[3] = (h[3] + d) | 0;
      h[4] = (h[4] + e) | 0; h[5] = (h[5] + f) | 0;
      h[6] = (h[6] + g) | 0; h[7] = (h[7] + hh) | 0;
    }
    return h.map(function (word) {
      return ('00000000' + (word >>> 0).toString(16)).slice(-8);
    }).join('');
  }

  /* ======================================================================
   * 2. Firmware arithmetic — a port of guzzionboard/firmware.py
   * ====================================================================== */

  var VECTOR_MARKER = 0xFA;
  var VECTOR_ENTRY_LEN = 4;
  var HW_PATTERN = /IAW[0-9A-Z]{2,5}HW([0-9]{3})/g;

  function checksums(bytes) {
    var sum = 0;
    for (var i = 0; i < bytes.length; i++) sum += bytes[i];
    var wordBe = 0, wordLe = 0;
    for (i = 0; i + 1 < bytes.length; i += 2) {
      wordBe += (bytes[i] << 8) | bytes[i + 1];
      wordLe += (bytes[i + 1] << 8) | bytes[i];
    }
    if (bytes.length % 2) {
      wordBe += bytes[bytes.length - 1] << 8;
      wordLe += bytes[bytes.length - 1];
    }
    return {
      length: bytes.length,
      sum16: sum & 0xFFFF,
      sum32: sum >>> 0 & 0xFFFFFFFF,
      word_sum16_be: wordBe & 0xFFFF,
      word_sum16_le: wordLe & 0xFFFF,
      md5: md5(bytes),
      sha256: sha256(bytes),
    };
  }

  function looksLikeVectorTable(bytes, entries) {
    entries = entries || 16;
    if (bytes.length < entries * VECTOR_ENTRY_LEN) return false;
    for (var i = 0; i < entries; i++) {
      if (bytes[i * VECTOR_ENTRY_LEN] !== VECTOR_MARKER) return false;
    }
    return true;
  }

  function isBlank(bytes) {
    if (!bytes.length) return true;
    var first = bytes[0];
    if (first !== 0x00 && first !== 0xFF) return false;
    for (var i = 1; i < bytes.length; i++) if (bytes[i] !== first) return false;
    return true;
  }

  function entropyEstimate(bytes, sample) {
    sample = sample || 65536;
    var n = Math.min(sample, bytes.length);
    if (!n) return 0;
    var counts = new Uint32Array(256);
    for (var i = 0; i < n; i++) counts[bytes[i]]++;
    var total = 0;
    for (i = 0; i < 256; i++) {
      if (!counts[i]) continue;
      var p = counts[i] / n;
      total -= p * Math.log2(p);
    }
    return total;
  }

  function asciiOf(bytes) {
    var out = '';
    for (var i = 0; i < bytes.length; i++) {
      out += String.fromCharCode(bytes[i]);
    }
    return out;
  }

  function hardwareStrings(bytes) {
    var text = asciiOf(bytes);
    var found = {};
    var match;
    HW_PATTERN.lastIndex = 0;
    while ((match = HW_PATTERN.exec(text)) !== null) found[match[0]] = true;
    return Object.keys(found).sort();
  }

  function hardwareFamily(hardware) {
    var m = /HW([0-9])/.exec(String(hardware || ''));
    return m ? m[1] : '';
  }

  /* ======================================================================
   * 3. The virtual filesystem
   * ======================================================================
   * Paths look like the ones the workstation writes so the UI, the report
   * and the copy/paste instructions all read the same — but nothing leaves
   * this tab, and the prefix says so.
   */

  var IMAGE_DIR = '/browser-demo/.guzzionboard/images/';
  var FS = {};                 // path -> { bytes, meta }

  function stamp(when) {
    var d = new Date((when || epoch()) * 1000);
    var two = function (n) { return ('0' + n).slice(-2); };
    return String(d.getFullYear()) + two(d.getMonth() + 1) + two(d.getDate())
      + '-' + two(d.getHours()) + two(d.getMinutes()) + two(d.getSeconds());
  }

  function timeText(when) {
    var d = new Date((when || epoch()) * 1000);
    var two = function (n) { return ('0' + n).slice(-2); };
    return d.getFullYear() + '-' + two(d.getMonth() + 1) + '-' + two(d.getDate())
      + ' ' + two(d.getHours()) + ':' + two(d.getMinutes()) + ':' + two(d.getSeconds());
  }

  function saveImage(path, image) {
    FS[path] = image;
    image.path = path;
    return path;
  }

  function describeImage(image) {
    return {
      ecu_id: image.ecu_id,
      region: image.region,
      source: image.source,
      path: image.path,
      read_at: image.read_at,
      read_at_text: timeText(image.read_at),
      identity: image.identity,
      checksums: checksums(image.bytes),
      hardware_strings: hardwareStrings(image.bytes),
      vector_table: looksLikeVectorTable(image.bytes),
      entropy: round(entropyEstimate(image.bytes), 2),
      blank: isBlank(image.bytes),
      meta: image.meta || {},
      simulated: true,
      simulation_note: 'Synthesised in the browser: a plausible image, not a '
        + 'dump of any real ECU. Digests and checksums are computed over the '
        + 'bytes that are actually here, so they are true of this image.',
    };
  }

  /* ======================================================================
   * 4. XML and TunerPro XDF — a port of guzzionboard/maps.py
   * ======================================================================
   * The bundled XDFs are published by GitHub Pages like any other file in
   * the repository, so the browser can fetch the real definition and parse
   * it. A hand-rolled scanner is used instead of DOMParser so the same code
   * runs under the Node test harness.
   */

  var ENTITIES = {
    amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ',
  };

  function unescapeXml(text) {
    return String(text).replace(/&(#x?[0-9a-fA-F]+|[a-zA-Z]+);/g, function (all, body) {
      if (body.charAt(0) === '#') {
        var code = body.charAt(1) === 'x' || body.charAt(1) === 'X'
          ? parseInt(body.slice(2), 16) : parseInt(body.slice(1), 10);
        return isNaN(code) ? all : String.fromCharCode(code);
      }
      return ENTITIES[body.toLowerCase()] !== undefined
        ? ENTITIES[body.toLowerCase()] : all;
    });
  }

  function parseXml(text) {
    var root = { tag: '#root', attrs: {}, children: [], text: '' };
    var stack = [root];
    var i = 0;
    var attrRe = /([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*("([^"]*)"|'([^']*)')/g;
    while (i < text.length) {
      var lt = text.indexOf('<', i);
      if (lt < 0) break;
      if (lt > i) {
        var chunk = text.slice(i, lt);
        if (chunk.trim()) stack[stack.length - 1].text += unescapeXml(chunk);
      }
      if (text.substr(lt, 4) === '<!--') {
        i = text.indexOf('-->', lt);
        i = i < 0 ? text.length : i + 3;
        continue;
      }
      if (text.substr(lt, 9) === '<![CDATA[') {
        var cend = text.indexOf(']]>', lt);
        cend = cend < 0 ? text.length : cend;
        stack[stack.length - 1].text += text.slice(lt + 9, cend);
        i = cend + 3;
        continue;
      }
      if (text.charAt(lt + 1) === '?' || text.charAt(lt + 1) === '!') {
        i = text.indexOf('>', lt);
        i = i < 0 ? text.length : i + 1;
        continue;
      }
      var gt = text.indexOf('>', lt);
      if (gt < 0) break;
      var inner = text.slice(lt + 1, gt);
      i = gt + 1;
      if (inner.charAt(0) === '/') {
        if (stack.length > 1) stack.pop();
        continue;
      }
      var selfClosing = inner.charAt(inner.length - 1) === '/';
      if (selfClosing) inner = inner.slice(0, -1);
      var space = inner.search(/\s/);
      var tag = space < 0 ? inner : inner.slice(0, space);
      var node = { tag: tag, attrs: {}, children: [], text: '' };
      if (space >= 0) {
        var rest = inner.slice(space);
        attrRe.lastIndex = 0;
        var m;
        while ((m = attrRe.exec(rest)) !== null) {
          node.attrs[m[1]] = unescapeXml(m[3] !== undefined ? m[3] : m[4]);
        }
      }
      stack[stack.length - 1].children.push(node);
      if (!selfClosing) stack.push(node);
    }
    return root.children.length ? root.children[0] : root;
  }

  function kids(node, tag) {
    return (node.children || []).filter(function (c) { return c.tag === tag; });
  }
  function kid(node, tag) {
    var found = kids(node, tag);
    return found.length ? found[0] : null;
  }
  function kidText(node, tag) {
    var found = kid(node, tag);
    return found ? found.text : '';
  }
  function intOf(text, fallback) {
    if (text === null || text === undefined || text === '') return fallback || 0;
    var clean = String(text).trim();
    var value = /^[-+]?0[xX]/.test(clean) ? parseInt(clean, 16) : parseInt(clean, 10);
    return isNaN(value) ? (fallback || 0) : value;
  }

  var MATH_ALLOWED = /^[Xx0-9+\-*/(). ]+$/;

  function compileMath(equation) {
    var text = String(equation || 'X').trim() || 'X';
    if (text === 'X' || text === 'x') return function (x) { return x; };
    if (!MATH_ALLOWED.test(text) || text.indexOf('**') >= 0) {
      throw new Error('unsupported equation ' + JSON.stringify(text));
    }
    var body = text.replace(/[Xx]/g, '(X)');
    /* The whitelist above admits digits, X and arithmetic only: no names,
     * no calls, no property access. */
    var fn = new Function('X', 'return (' + body + ');');  // eslint-disable-line no-new-func
    return function (x) {
      var value = fn(Number(x));
      if (typeof value !== 'number' || !isFinite(value)) {
        throw new Error('equation ' + text + ' failed on ' + x);
      }
      return value;
    };
  }

  /* Python's "%g": six significant digits, half-to-even, and an exponent
   * only outside 1e-5 .. 1e6. JavaScript's toPrecision rounds half away
   * from zero, which puts 11438.25 one tenth above where Python puts it. */
  function gFormat(value) {
    if (value === 0) return '0';
    var exp = Math.floor(Math.log10(Math.abs(value)));
    var rounded = round(value, 5 - exp);
    if (rounded !== 0) {
      var settled = Math.floor(Math.log10(Math.abs(rounded)));
      if (settled !== exp) {                 // rounding carried into a new decade
        exp = settled;
        rounded = round(value, 5 - exp);
      }
    }
    if (exp < -4 || exp >= 6) {
      var mantissa = String(+(rounded / Math.pow(10, exp)).toFixed(5));
      var magnitude = Math.abs(exp);
      return mantissa + 'e' + (exp < 0 ? '-' : '+')
        + (magnitude < 10 ? '0' + magnitude : String(magnitude));
    }
    return String(rounded);
  }

  function formatNumber(value) {
    if (Number.isInteger(value)) return String(value);
    return gFormat(value);
  }

  function parseEmbedded(node, signedDefault) {
    var sizeBits = intOf(node.attrs.mmedelementsizebits, 8);
    if (sizeBits !== 8 && sizeBits !== 16 && sizeBits !== 32) {
      throw new Error('unsupported element size ' + sizeBits + ' bits');
    }
    var flags = intOf(node.attrs.mmedtypeflags, 0);
    return {
      address: intOf(node.attrs.mmedaddress, 0),
      size_bits: sizeBits,
      rows: Math.max(1, intOf(node.attrs.mmedrowcount, 1)),
      cols: Math.max(1, intOf(node.attrs.mmedcolcount, 1)),
      major_stride_bits: intOf(node.attrs.mmedmajorstridebits, 0),
      minor_stride_bits: intOf(node.attrs.mmedminorstridebits, 0),
      signed: !!(flags & 0x1) || !!signedDefault,
    };
  }

  function spanBits(embedded) {
    var minor = embedded.minor_stride_bits || embedded.size_bits;
    var major = embedded.major_stride_bits || (minor * embedded.cols);
    return (embedded.rows - 1) * major + (embedded.cols - 1) * minor
      + embedded.size_bits;
  }

  function embeddedPositions(embedded, offset) {
    var size = embedded.size_bits / 8;
    var minor = (embedded.minor_stride_bits || embedded.size_bits) / 8;
    var major = embedded.major_stride_bits
      ? embedded.major_stride_bits / 8 : minor * embedded.cols;
    var out = [];
    for (var r = 0; r < embedded.rows; r++) {
      for (var c = 0; c < embedded.cols; c++) {
        out.push({ pos: offset + r * major + c * minor, size: size });
      }
    }
    return out;
  }

  function readEmbedded(embedded, bytes, offset, littleEndian) {
    return embeddedPositions(embedded, offset).map(function (slot) {
      if (slot.pos < 0 || slot.pos + slot.size > bytes.length) {
        throw new Error('data at 0x' + embedded.address.toString(16).toUpperCase()
          + ' falls outside the image');
      }
      var value = 0;
      for (var n = 0; n < slot.size; n++) {
        var byte = bytes[slot.pos + (littleEndian ? slot.size - 1 - n : n)];
        value = value * 256 + byte;
      }
      if (embedded.signed) {
        var limit = Math.pow(2, slot.size * 8 - 1);
        if (value >= limit) value -= limit * 2;
      }
      return value;
    });
  }

  function writeEmbedded(embedded, bytes, offset, littleEndian, raws) {
    embeddedPositions(embedded, offset).forEach(function (slot, index) {
      if (slot.pos < 0 || slot.pos + slot.size > bytes.length) return;
      var limit = Math.pow(2, slot.size * 8);
      var value = Math.round(raws[index]);
      if (embedded.signed && value < 0) value += limit;
      value = ((value % limit) + limit) % limit;
      for (var n = 0; n < slot.size; n++) {
        var shift = littleEndian ? n : slot.size - 1 - n;
        bytes[slot.pos + n] = Math.floor(value / Math.pow(256, shift)) & 0xFF;
      }
    });
  }

  function parseAxis(node, signedDefault) {
    var count = Math.max(1, intOf(kidText(node, 'indexcount'), 1));
    var labels = [];
    for (var i = 0; i < count; i++) labels.push('');
    kids(node, 'LABEL').forEach(function (label) {
      var index = intOf(label.attrs.index, 0);
      if (index >= 0 && index < count) {
        labels[index] = (label.attrs.value || '').trim();
      }
    });
    var embedded = null;
    var dataNode = kid(node, 'EMBEDDEDDATA');
    if (dataNode && dataNode.attrs.mmedaddress !== undefined) {
      embedded = parseEmbedded(dataNode, signedDefault);
      embedded.rows = 1;
      embedded.cols = count;
    }
    return {
      ident: node.attrs.id || '?',
      units: (kidText(node, 'units') || '').trim(),
      labels: labels,
      count: count,
      embedded: embedded,
      math: mathOf(node),
    };
  }

  function mathOf(node) {
    var math = kid(node, 'MATH');
    if (!math) return 'X';
    return (math.attrs.equation || 'X').trim();
  }

  /* Python's repr() for a plain string, so the "unsupported equation"
   * messages read identically in both implementations. */
  function pyRepr(text) {
    var body = String(text).replace(/\\/g, '\\\\');
    if (body.indexOf("'") >= 0 && body.indexOf('"') < 0) {
      return '"' + body + '"';
    }
    return "'" + body.replace(/'/g, "\\'") + "'";
  }

  function checkMath(node, what) {
    var maths = kids(node, 'MATH');
    var equation = mathOf(node);
    var linked = maths.some(function (m) {
      return kids(m, 'VAR').some(function (v) { return v.attrs.type; });
    });
    if (maths.length > 1 || linked) {
      throw new Error(what + ': per-cell or address-linked equations are not supported');
    }
    try {
      compileMath(equation);    // throws on anything outside the whitelist
    } catch (exc) {
      throw new Error(what + ': unsupported equation ' + pyRepr(equation));
    }
    return equation;
  }

  function axisHeader(axis, bytes, offset, littleEndian) {
    if (axis.embedded) {
      var fn = compileMath(axis.math);
      return readEmbedded(axis.embedded, bytes, offset, littleEndian)
        .map(function (raw) { return formatNumber(fn(raw)); });
    }
    if (axis.labels.some(function (l) { return l; })) return axis.labels;
    var out = [];
    for (var i = 0; i < axis.count; i++) out.push(String(i));
    return out;
  }

  function parseXdf(text, path) {
    var root = parseXml(text);
    var header = kid(root, 'XDFHEADER');
    if (!header) throw new Error('no XDFHEADER - this is not a TunerPro XDF');

    var xdf = {
      title: (kidText(header, 'deftitle') || '').trim(),
      description: (kidText(header, 'description') || '').trim(),
      author: (kidText(header, 'author') || '').trim(),
      version: (kidText(header, 'fileversion') || '').trim(),
      path: path || '',
      region_size: null,
      base_offset: 0,
      base_subtract: false,
      little_endian: false,
      signed_default: false,
      categories: {},
      tables: [],
      constants: [],
      checksums: [],
      unsupported: [],
    };
    kids(header, 'REGION').forEach(function (region) {
      if (region.attrs.size) xdf.region_size = intOf(region.attrs.size, 0);
    });
    var base = kid(header, 'BASEOFFSET');
    if (base) {
      xdf.base_offset = intOf(base.attrs.offset, 0);
      xdf.base_subtract = !!intOf(base.attrs.subtract, 0);
    }
    var defaults = kid(header, 'DEFAULTS');
    if (defaults) {
      xdf.little_endian = !!intOf(defaults.attrs.lsbfirst, 0);
      xdf.signed_default = !!intOf(defaults.attrs.signed, 0);
    }
    kids(header, 'CATEGORY').forEach(function (category) {
      xdf.categories[intOf(category.attrs.index, 0)] =
        (category.attrs.name || '').trim();
    });

    function categoryOf(node) {
      return kids(node, 'CATEGORYMEM').map(function (mem) {
        return xdf.categories[intOf(mem.attrs.category, 0)] || '';
      }).filter(Boolean).join(' / ');
    }

    kids(root, 'XDFTABLE').forEach(function (node) {
      var title = (kidText(node, 'title') || '').trim() || '(untitled table)';
      try {
        var axes = {};
        kids(node, 'XDFAXIS').forEach(function (axisNode) {
          axes[axisNode.attrs.id || '?'] = parseAxis(axisNode, xdf.signed_default);
        });
        var z = axes.z;
        if (!z || !z.embedded) throw new Error(title + ': no z-axis data');
        var zNode = kids(node, 'XDFAXIS').filter(function (n) {
          return n.attrs.id === 'z';
        })[0];
        // TunerPro repeats the row count in both places; trust the axis.
        z.embedded.rows = 1;
        z.embedded.cols = intOf((kid(zNode, 'EMBEDDEDDATA') || { attrs: {} })
          .attrs.mmedcolcount, 1);
        z.embedded.rows = Math.max(1, intOf((kid(zNode, 'EMBEDDEDDATA')
          || { attrs: {} }).attrs.mmedrowcount, 1));
        if (axes.y && z.embedded.rows !== axes.y.count) z.embedded.rows = axes.y.count;
        if (axes.x && z.embedded.cols === 1 && axes.x.count > 1) {
          z.embedded.cols = axes.x.count;
        }
        var decimals = kidText(zNode, 'decimalpl');
        var table = {
          title: title,
          description: (kidText(node, 'description') || '').trim(),
          category: categoryOf(node),
          units: (z.units || kidText(node, 'units') || '').trim(),
          x: axes.x || { ident: 'x', units: '', labels: [], count: 1, embedded: null, math: 'X' },
          y: axes.y || { ident: 'y', units: '', labels: [], count: 1, embedded: null, math: 'X' },
          embedded: z.embedded,
          math: checkMath(zNode, title),
          decimalpl: decimals ? (intOf(decimals, 0) || null) : null,
          uniqueid: node.attrs.uniqueid || '',
        };
        kids(node, 'XDFAXIS').forEach(function (axisNode) {
          var ident = axisNode.attrs.id;
          if (ident === 'x' || ident === 'y') {
            table[ident].math = checkMath(axisNode, title + ' (' + ident + ')');
          }
        });
        xdf.tables.push(table);
      } catch (exc) {
        xdf.unsupported.push({ title: title, kind: 'table', reason: String(exc.message || exc) });
      }
    });

    kids(root, 'XDFCONSTANT').forEach(function (node) {
      var title = (kidText(node, 'title') || '').trim() || '(untitled constant)';
      try {
        var dataNode = kid(node, 'EMBEDDEDDATA');
        if (!dataNode || dataNode.attrs.mmedaddress === undefined) {
          throw new Error(title + ': no embedded data');
        }
        var decimals = kidText(node, 'decimalpl');
        xdf.constants.push({
          title: title,
          description: (kidText(node, 'description') || '').trim(),
          category: categoryOf(node),
          units: (kidText(node, 'units') || '').trim(),
          embedded: parseEmbedded(dataNode, xdf.signed_default),
          math: checkMath(node, title),
          decimalpl: decimals ? (intOf(decimals, 0) || null) : null,
          uniqueid: node.attrs.uniqueid || '',
        });
      } catch (exc) {
        xdf.unsupported.push({ title: title, kind: 'constant', reason: String(exc.message || exc) });
      }
    });

    kids(root, 'XDFCHECKSUM').forEach(function (node) {
      var title = (kidText(node, 'title') || '').trim();
      if (title) xdf.checksums.push(title);
    });

    if (!xdf.tables.length && !xdf.constants.length) {
      throw new Error('no readable tables or constants in ' + (path || 'this XDF'));
    }
    return xdf;
  }

  function fileOffset(xdf, address) {
    return xdf.base_subtract ? address - xdf.base_offset : address + xdf.base_offset;
  }

  function dataEnd(xdf) {
    var end = 0;
    var consider = function (address, bits) {
      end = Math.max(end, fileOffset(xdf, address) + Math.ceil(bits / 8));
    };
    xdf.tables.forEach(function (table) {
      consider(table.embedded.address, spanBits(table.embedded));
      [table.x, table.y].forEach(function (axis) {
        if (axis.embedded) consider(axis.embedded.address, spanBits(axis.embedded));
      });
    });
    xdf.constants.forEach(function (constant) {
      consider(constant.embedded.address, spanBits(constant.embedded));
    });
    return end;
  }

  function suggestAddressBase(xdf, imageLength) {
    var end = dataEnd(xdf);
    if (end <= imageLength) return 0;
    var guesses = [0x4000, 0x8000, 0xC000];
    for (var i = 0; i < guesses.length; i++) {
      if (end - guesses[i] <= imageLength) return guesses[i];
    }
    return 0;
  }

  function tableValues(table, bytes, offset, littleEndian) {
    var fn = compileMath(table.math);
    var raw = readEmbedded(table.embedded, bytes, offset, littleEndian);
    var rows = [];
    for (var r = 0; r < table.embedded.rows; r++) {
      var row = [];
      for (var c = 0; c < table.embedded.cols; c++) {
        var value = fn(raw[r * table.embedded.cols + c]);
        row.push(table.decimalpl ? round(value, table.decimalpl) : value);
      }
      rows.push(row);
    }
    return rows;
  }

  function renderXdf(xdf, image, addressBase) {
    var bytes = image.bytes;
    if (addressBase === null || addressBase === undefined) {
      addressBase = suggestAddressBase(xdf, bytes.length);
    }
    var hint = function () {
      return 'outside this ' + bytes.length + '-byte image (base 0x'
        + addressBase.toString(16).toUpperCase() + '). If this is a region '
        + 'read of a full-device XDF, pass address_base=0x4000.';
    };
    var axisOffset = function (axis, dataOffset) {
      if (!axis.embedded) return dataOffset;
      return fileOffset(xdf, axis.embedded.address) - addressBase;
    };

    var tables = [];
    var errors = [];
    xdf.tables.forEach(function (table) {
      var offset = fileOffset(xdf, table.embedded.address) - addressBase;
      try {
        tables.push({
          title: table.title,
          category: table.category,
          units: table.units,
          address: '0x' + table.embedded.address.toString(16).toUpperCase(),
          rows: table.y.count,
          cols: table.x.count,
          x: axisHeader(table.x, bytes, axisOffset(table.x, offset), xdf.little_endian),
          y: axisHeader(table.y, bytes, axisOffset(table.y, offset), xdf.little_endian),
          values: tableValues(table, bytes, offset, xdf.little_endian),
        });
      } catch (exc) {
        errors.push({
          title: table.title, kind: 'table',
          reason: table.title + ': ' + (exc.message || exc) + ' ' + hint(),
        });
      }
    });

    var constants = [];
    xdf.constants.forEach(function (constant) {
      var offset = fileOffset(xdf, constant.embedded.address) - addressBase;
      try {
        var raw = readEmbedded(constant.embedded, bytes, offset, xdf.little_endian)[0];
        var value = compileMath(constant.math)(raw);
        constants.push({
          title: constant.title,
          category: constant.category,
          units: constant.units,
          address: '0x' + constant.embedded.address.toString(16).toUpperCase(),
          raw: raw,
          value: constant.decimalpl ? round(value, constant.decimalpl) : value,
        });
      } catch (exc) {
        errors.push({
          title: constant.title, kind: 'constant',
          reason: constant.title + ': ' + (exc.message || exc) + ' ' + hint(),
        });
      }
    });

    return {
      xdf: {
        title: xdf.title, description: xdf.description, author: xdf.author,
        version: xdf.version, path: xdf.path,
        categories: Object.keys(xdf.categories).map(function (k) {
          return xdf.categories[k];
        }).sort(),
      },
      image_size: bytes.length,
      address_base: addressBase,
      tables: tables,
      constants: constants,
      unsupported: xdf.unsupported,
      errors: errors,
      checksums: xdf.checksums,
    };
  }

  function diffXdf(xdf, before, after, addressBase) {
    var a = before.bytes, b = after.bytes;
    if (a.length !== b.length) {
      throw new Error('images differ in size (' + a.length + ' vs ' + b.length
        + '); compare like with like');
    }
    if (addressBase === null || addressBase === undefined) {
      addressBase = suggestAddressBase(xdf, a.length);
    }
    var tables = [];
    xdf.tables.forEach(function (table) {
      var offset = fileOffset(xdf, table.embedded.address) - addressBase;
      var beforeRows, afterRows, x, y;
      try {
        beforeRows = tableValues(table, a, offset, xdf.little_endian);
        afterRows = tableValues(table, b, offset, xdf.little_endian);
        x = axisHeader(table.x, a, table.x.embedded
          ? fileOffset(xdf, table.x.embedded.address) - addressBase : offset,
        xdf.little_endian);
        y = axisHeader(table.y, a, table.y.embedded
          ? fileOffset(xdf, table.y.embedded.address) - addressBase : offset,
        xdf.little_endian);
      } catch (exc) {
        tables.push({ title: table.title, error: String(exc.message || exc) });
        return;
      }
      var cells = [];
      beforeRows.forEach(function (rowA, r) {
        (afterRows[r] || []).forEach(function (vb, c) {
          var va = rowA[c];
          if (va !== vb) {
            cells.push({
              row: r, col: c,
              x: c < x.length ? x[c] : String(c),
              y: r < y.length ? y[r] : String(r),
              before: va, after: vb,
            });
          }
        });
      });
      if (cells.length) {
        tables.push({
          title: table.title, category: table.category, units: table.units,
          changed_cells: cells.length,
          cells: cells.slice(0, 512),
          cells_truncated: cells.length > 512,
        });
      }
    });

    var constants = [];
    xdf.constants.forEach(function (constant) {
      var offset = fileOffset(xdf, constant.embedded.address) - addressBase;
      try {
        var fn = compileMath(constant.math);
        var va = fn(readEmbedded(constant.embedded, a, offset, xdf.little_endian)[0]);
        var vb = fn(readEmbedded(constant.embedded, b, offset, xdf.little_endian)[0]);
        if (va !== vb) {
          constants.push({
            title: constant.title, units: constant.units,
            before: va, after: vb,
          });
        }
      } catch (exc) { /* unreadable in one of the two: nothing to compare */ }
    });

    return {
      xdf: { title: xdf.title, path: xdf.path },
      image_size: a.length,
      address_base: addressBase,
      identical: !tables.length && !constants.length,
      tables: tables,
      constants: constants,
    };
  }

  /* ======================================================================
   * 5. Synthesising a flash image
   * ======================================================================
   * The local workstation reads 311,296 real bytes out of a real ECU. There
   * is no ECU here, so the demo builds an image that behaves like one: an
   * IAW vector table at offset 0, the identity strings the simulated ECU
   * reports, code-like filler at a believable entropy, and — where a
   * bundled XDF says a table lives — a smooth, plausible calibration
   * surface written at exactly that address with that table's own scaling.
   *
   * The definitions are real. The numbers are invented. Every payload that
   * carries them says so.
   */

  function xdfIndex() {
    return (data().xdfs || []);
  }

  /* The definition file to synthesise against: the richest GuzziDiag XDF
   * whose filename starts with this ECU family's id (5AM_..., 15M_..., ...),
   * skipping the EEPROM definitions, which describe a different region. */
  function xdfForEcu(ecuId) {
    var prefix = String(ecuId || '').toUpperCase() + '_';
    var best = null;
    xdfIndex().forEach(function (entry) {
      var name = entry.path.split('/').pop().toUpperCase();
      if (name.indexOf(prefix) !== 0 || name.indexOf('EEPROM') >= 0) return;
      if (!best || entry.tables > best.tables) best = entry;
    });
    return best;
  }

  var xdfCache = {};

  function loadXdf(entry) {
    if (xdfCache[entry.path]) return Promise.resolve(xdfCache[entry.path]);
    return fetch(entry.url, { cache: 'force-cache' }).then(function (r) {
      if (!r.ok) throw new Error(entry.path + ': HTTP ' + r.status);
      return r.text();
    }).then(function (text) {
      var xdf = parseXdf(text, entry.path);
      xdfCache[entry.path] = xdf;
      return xdf;
    });
  }

  function invertMath(equation) {
    var fn = compileMath(equation);
    var f0 = fn(0), f1 = fn(1), f2 = fn(2);
    var slope = f1 - f0;
    if (Math.abs((f2 - f1) - slope) < 1e-9 && Math.abs(slope) > 1e-12) {
      return function (target) { return (target - f0) / slope; };
    }
    return function (target, lo, hi) {        // monotonic bisection
      var a = lo === undefined ? 0 : lo;
      var b = hi === undefined ? 65535 : hi;
      var rising = fn(b) >= fn(a);
      for (var i = 0; i < 48; i++) {
        var mid = (a + b) / 2;
        var value = fn(mid);
        if ((value < target) === rising) a = mid; else b = mid;
      }
      return (a + b) / 2;
    };
  }

  function rawLimits(embedded) {
    var bits = embedded.size_bits;
    if (embedded.signed) {
      return { lo: -Math.pow(2, bits - 1), hi: Math.pow(2, bits - 1) - 1 };
    }
    return { lo: 0, hi: Math.pow(2, bits) - 1 };
  }

  /* What a table of this name and unit plausibly holds. ``fx`` runs 0..1
   * across the columns and ``fy`` 0..1 down the rows — load and speed on a
   * 3-D map, a single sweep on a 2-D one. */
  function surfaceFor(title, units) {
    var text = (title + ' ' + units).toLowerCase();
    var has = function (needle) { return text.indexOf(needle) >= 0; };

    if (has('rpm') || has('giri')) {
      return function (fx) { return 650 + fx * 7350; };
    }
    if (has('km/h') || has('speed')) {
      return function (fx) { return 10 + fx * 190; };
    }
    if (has('ms') || has('inject') || has('fuel') || has('iniez')) {
      return function (fx, fy) {
        return 1.1 + 6.4 * fx * (0.55 + 0.45 * fy)
          + 0.25 * Math.sin(fx * 6.2) * (0.3 + fy * 0.7);
      };
    }
    if (has('spark') || has('advance') || has('ignition') || has('anticipo')
        || has('\u00b0') || has('deg')) {
      return function (fx, fy) {
        return 8 + 26 * (1 - Math.pow(fx, 1.4)) * (0.45 + 0.55 * fy)
          + 1.5 * Math.sin(fy * 5.0);
      };
    }
    if (has('lambda') || has('afr')) {
      return function (fx, fy) { return 14.7 - 1.9 * Math.pow(fx, 2) * (0.4 + 0.6 * fy); };
    }
    if (has('temp') || has('\u00b0c')) {
      return function (fx) { return -10 + fx * 120; };
    }
    if (has('%') || has('duty') || has('trim') || has('correct')) {
      return function (fx, fy) { return 100 * (0.35 + 0.6 * fx * (0.4 + 0.6 * fy)); };
    }
    if (has('volt') || has(' v')) {
      return function (fx) { return 11.5 + fx * 3.0; };
    }
    if (has('mbar') || has('press') || has('map')) {
      return function (fx) { return 220 + fx * 780; };
    }
    return null;
  }

  function paintTable(xdf, table, bytes, addressBase) {
    var offset = fileOffset(xdf, table.embedded.address) - addressBase;
    var span = Math.ceil(spanBits(table.embedded) / 8);
    if (offset < 0 || offset + span > bytes.length) return false;

    var limits = rawLimits(table.embedded);
    var rows = table.embedded.rows, cols = table.embedded.cols;
    var surface = surfaceFor(table.title, table.units);
    var invert = invertMath(table.math);
    var raws = [];
    for (var r = 0; r < rows; r++) {
      for (var c = 0; c < cols; c++) {
        var fx = cols > 1 ? c / (cols - 1) : 0.5;
        var fy = rows > 1 ? r / (rows - 1) : 0.5;
        var raw;
        if (surface) {
          raw = invert(surface(fx, fy), limits.lo, limits.hi);
        } else {
          // No idea what this table means: a smooth raw ramp still renders
          // as something continuous in whatever unit it carries.
          raw = limits.lo + (limits.hi - limits.lo)
            * (0.18 + 0.64 * (0.6 * fx + 0.4 * fy)
              + 0.03 * Math.sin(fx * 7 + fy * 3));
        }
        raws.push(clamp(Math.round(raw), limits.lo, limits.hi));
      }
    }
    writeEmbedded(table.embedded, bytes, offset, xdf.little_endian, raws);
    return true;
  }

  function paintAxis(xdf, axis, bytes, addressBase) {
    if (!axis.embedded) return;
    var offset = fileOffset(xdf, axis.embedded.address) - addressBase;
    var span = Math.ceil(spanBits(axis.embedded) / 8);
    if (offset < 0 || offset + span > bytes.length) return;
    var limits = rawLimits(axis.embedded);
    var count = axis.embedded.cols;
    var surface = surfaceFor(axis.units + ' ' + axis.ident, axis.units);
    var invert = invertMath(axis.math);
    var raws = [];
    for (var i = 0; i < count; i++) {
      var fx = count > 1 ? i / (count - 1) : 0;
      var raw = surface
        ? invert(surface(fx, fx), limits.lo, limits.hi)
        : limits.lo + (limits.hi - limits.lo) * (0.05 + 0.9 * fx);
      raws.push(clamp(Math.round(raw), limits.lo, limits.hi));
    }
    writeEmbedded(axis.embedded, bytes, offset, xdf.little_endian, raws);
  }

  function fillerBytes(size, seed) {
    /* Firmware is not noise: it is mostly a small alphabet of opcodes and
     * near-zero operands, which is why a real dump sits around 5-6 bits of
     * entropy per byte and an encrypted container sits at 8. */
    var next = H.rng(seed || 4242);
    var bytes = new Uint8Array(size);
    var common = [0x00, 0x00, 0x00, 0xFF, 0x4E, 0x71, 0x60, 0x66, 0x67, 0x2F,
      0x10, 0x20, 0x30, 0x12, 0x22, 0x32, 0x6B, 0x4A, 0x08, 0x01, 0x02, 0x03,
      0x04, 0x06, 0x0C, 0x0E, 0x18, 0x1C, 0x40, 0x41, 0x42, 0x48];
    for (var i = 0; i < size; i++) {
      var pick = next();
      if (pick < 0.72) bytes[i] = common[Math.floor(next() * common.length)];
      else bytes[i] = Math.floor(next() * 256) & 0xFF;
    }
    return bytes;
  }

  function putAscii(bytes, offset, text) {
    for (var i = 0; i < text.length && offset + i < bytes.length; i++) {
      bytes[offset + i] = text.charCodeAt(i) & 0x7F;
    }
  }

  function regionSpec(profile, region) {
    var memory = profile.memory || {};
    var regions = memory.regions || {};
    return regions[region] || null;
  }

  /* Build the image. Returns a promise because the XDF it paints against is
   * fetched from the site. */
  function synthesiseImage(profile, region, identity, options) {
    options = options || {};
    var spec = regionSpec(profile, region);
    if (!spec || !spec.size) {
      return Promise.reject(bad('the ' + region + ' region of ' + profile.family
        + ' has no declared geometry, so there is nothing to read'));
    }
    var bytes = fillerBytes(spec.size, options.seed || 4242);

    // An IAW vector table: 64 four-byte entries, each opening with 0xFA.
    for (var v = 0; v < 64; v++) {
      bytes[v * 4] = VECTOR_MARKER;
      bytes[v * 4 + 1] = (0x40 + v) & 0xFF;
      bytes[v * 4 + 2] = (v * 7) & 0xFF;
      bytes[v * 4 + 3] = (v * 29) & 0xFF;
    }

    // The strings a real dump carries, taken from the simulated ECU's own
    // identity block rather than typed in again here.
    var at = 0x120;
    putAscii(bytes, at, 'MAGNETI MARELLI  ' + (profile.family || ''));
    at += 64;
    Object.keys(identity || {}).forEach(function (field) {
      putAscii(bytes, at, field + ' ' + identity[field]);
      at += 32;
    });
    putAscii(bytes, at, 'SIMULATED IMAGE - GuzziOnBoard browser demo');

    var entry = options.xdf || xdfForEcu(profile.id);
    if (!entry) {
      return Promise.resolve({ bytes: bytes, painted: null });
    }
    return loadXdf(entry).then(function (xdf) {
      var base = suggestAddressBase(xdf, bytes.length);
      var painted = 0;
      xdf.tables.forEach(function (table) {
        paintAxis(xdf, table.x, bytes, base);
        paintAxis(xdf, table.y, bytes, base);
        if (paintTable(xdf, table, bytes, base)) painted++;
      });
      return { bytes: bytes, painted: painted, xdf: xdf, entry: entry, address_base: base };
    }).catch(function () {
      // The definition could not be fetched (offline, or a trimmed deploy).
      // An unpainted image is still a usable image; maps will just look flat.
      return { bytes: bytes, painted: null };
    });
  }

  /* A second image that differs from the first in a way the map diff can
   * name: every fuelling table 6% richer. This is what "I changed the map
   * and want to see exactly what moved" looks like. */
  function enrichFuel(source, xdf, addressBase, factor) {
    var bytes = new Uint8Array(source);
    xdf.tables.forEach(function (table) {
      var text = (table.title + ' ' + table.units).toLowerCase();
      if (text.indexOf('ms') < 0 && text.indexOf('inject') < 0
        && text.indexOf('fuel') < 0 && text.indexOf('iniez') < 0) return;
      var offset = fileOffset(xdf, table.embedded.address) - addressBase;
      var span = Math.ceil(spanBits(table.embedded) / 8);
      if (offset < 0 || offset + span > bytes.length) return;
      var limits = rawLimits(table.embedded);
      var raws;
      try {
        raws = readEmbedded(table.embedded, bytes, offset, xdf.little_endian);
      } catch (exc) { return; }
      raws = raws.map(function (raw) {
        return clamp(Math.round(raw * factor), limits.lo, limits.hi);
      });
      writeEmbedded(table.embedded, bytes, offset, xdf.little_endian, raws);
    });
    return bytes;
  }

  /* ======================================================================
   * 6. Long jobs, time-compressed
   * ======================================================================
   * A 5AM flash read is 311,296 bytes at K-Line speed: about twenty minutes,
   * twice that for a verified backup. Waiting twenty minutes for a demo
   * would teach nobody anything, so the same phases run over about three
   * seconds — and every progress line and every result says how much real
   * time it stands for.
   */

  var DEMO_JOB_SECONDS = 3.0;

  var JOB = {
    name: '', state: 'idle', started: 0, finished: 0, running: false,
    progress: null, result: null, error: null,
  };

  function jobStatus() {
    return {
      name: JOB.name, state: JOB.state, started: JOB.started,
      finished: JOB.finished || null, running: JOB.running,
      progress: JOB.progress, result: JOB.result, error: JOB.error,
      simulated: true,
      compression: JOB.compression || null,
      note: JOB.note || '',
    };
  }

  function realMinutes(profile, passes) {
    var minutes = ((profile.memory || {}).approx_read_minutes) || 0;
    return minutes * (passes || 1);
  }

  /* ``phases`` is [{phase, total, share, message(done,total)}]; ``finish``
   * produces the result once the clock runs out. */
  function startJob(name, phases, finish, options) {
    options = options || {};
    if (JOB.running) {
      throw httpError(409, 'a ' + JOB.name + ' job is already running', 'busy');
    }
    var seconds = options.seconds || DEMO_JOB_SECONDS;
    JOB.name = name;
    JOB.state = 'running';
    JOB.running = true;
    JOB.started = epoch();
    JOB.finished = 0;
    JOB.result = null;
    JOB.error = null;
    JOB.compression = options.real_minutes
      ? {
        real_seconds: Math.round(options.real_minutes * 60),
        demo_seconds: seconds,
        factor: Math.round(options.real_minutes * 60 / seconds),
        note: 'Time-compressed: ' + options.real_minutes + ' minutes of real '
          + 'K-Line transfer shown in ' + seconds + ' seconds.',
      }
      : null;
    JOB.note = options.note || SIM;

    var totalShare = phases.reduce(function (sum, p) { return sum + (p.share || 1); }, 0);
    var startedAt = mono();
    var tick = function () {
      var elapsed = mono() - startedAt;
      var fraction = clamp(elapsed / seconds, 0, 1);
      var walked = fraction * totalShare;
      var cursor = 0;
      var current = phases[phases.length - 1];
      var within = 1;
      for (var i = 0; i < phases.length; i++) {
        var share = phases[i].share || 1;
        if (walked <= cursor + share || i === phases.length - 1) {
          current = phases[i];
          within = clamp((walked - cursor) / share, 0, 1);
          break;
        }
        cursor += share;
      }
      var done = Math.round(current.total * within);
      JOB.progress = {
        phase: current.phase,
        done: done,
        total: current.total,
        fraction: within,
        eta_s: Math.max(0, round(seconds * (1 - fraction), 1)),
        message: current.message ? current.message(done, current.total) : '',
        simulated: true,
        real_eta_s: JOB.compression
          ? Math.round(JOB.compression.real_seconds * (1 - fraction)) : null,
      };
      if (fraction >= 1) {
        clearInterval(JOB.timer);
        JOB.timer = null;
        Promise.resolve().then(finish).then(function (result) {
          JOB.result = result;
          JOB.state = 'done';
        }).catch(function (exc) {
          JOB.error = String((exc && exc.message) || exc);
          JOB.state = 'failed';
        }).then(function () {
          JOB.running = false;
          JOB.finished = epoch();
        });
      }
    };
    JOB.timer = setInterval(tick, 100);
    tick();
    return jobStatus();
  }

  var addressMessage = function (start) {
    return function (done) {
      return '0x' + ('000000' + (start + done).toString(16).toUpperCase()).slice(-6);
    };
  };

  /* ======================================================================
   * 7. ECU memory: read, backup, validate, write, verify
   * ====================================================================== */

  function currentProfile() {
    var profile = WS.sessionProfile || WS.selection.profile;
    if (!profile) throw httpError(409, 'select a vehicle first', 'not_connected');
    return profile;
  }

  function memoryCapabilities(profile) {
    var memory = profile.memory || {};
    return {
      ecu: profile.id,
      family: profile.family,
      protocol: memory.protocol || (profile.id === '5am' ? 'iaw_transfer' : 'kwp_transfer'),
      regions: memory.regions || {},
      read_supported: !!memory.read_supported,
      write_supported: !!memory.write_supported,
      write_blocked_reason: memory.write_blocked_reason || '',
      simulated: true,
      simulation_note: (memory.simulation_note || '')
        + ' In this hosted demo the image itself is synthesised in your '
        + 'browser and the transfer is time-compressed to about '
        + DEMO_JOB_SECONDS + ' seconds; against a real ECU it is '
        + (realMinutes(profile, 1) || 20) + ' minutes a pass.',
      security_required: true,
      security_available: WS.gate.allow_unverified_keys,
      hardware_note: memory.hardware_note || '',
      estimated_read_minutes: memory.approx_read_minutes || null,
    };
  }

  var CHECKPOINTS = {};

  D.register('GET', '/api/memory', function () {
    var profile = currentProfile();
    var regions = (profile.memory || {}).regions || {};
    var checkpoints = {};
    Object.keys(regions).forEach(function (name) {
      checkpoints[name] = CHECKPOINTS[name] || null;
    });
    return [200, {
      capabilities: memoryCapabilities(profile),
      job: jobStatus(),
      checkpoints: checkpoints,
      acknowledgement: 'I have a verified backup and accept the risk',
      programming_enabled: WS.gate.allow_programming,
      unverified_keys_accepted: WS.gate.allow_unverified_keys,
      simulated: true,
      demo_note: 'Simulated ECU memory. The image is synthesised in this tab '
        + 'and every transfer is time-compressed.',
    }];
  });

  D.register('GET', '/api/memory/progress', function () {
    return [200, jobStatus()];
  });

  function securityGate() {
    if (!WS.gate.allow_unverified_keys) {
      throw httpError(
        409,
        'only unverified key providers are available (iaw5am-kwp-divmod). The '
        + 'key algorithm is transcribed from 5am_util and has never been '
        + "confirmed against a Guzzi-fitted ECU. Tick 'accept unverified key "
        + "providers' to continue — in this demo that risk is simulated, on a "
        + 'real bike it is a lockout.',
        'security_unavailable'
      );
    }
  }

  function readJob(profile, region, options) {
    options = options || {};
    var spec = regionSpec(profile, region);
    if (!spec || !spec.size) {
      throw bad('the ' + region + ' region of ' + profile.family + ' has no '
        + 'declared geometry here, so a read would be a guess');
    }
    securityGate();
    var passes = options.passes || 1;
    var phases = [];
    for (var pass = 0; pass < passes; pass++) {
      phases.push({
        phase: passes > 1 ? 'read pass ' + (pass + 1) : 'read',
        total: spec.size,
        share: 1,
        message: addressMessage(spec.start),
      });
    }
    var identity = WS.identity ? WS.identity.fields : null;
    return startJob(
      (passes > 1 ? 'backup:' : 'read:') + region,
      phases,
      function () {
        return synthesiseImage(profile, region, identity, {}).then(function (built) {
          var image = {
            ecu_id: profile.id, region: region, source: 'read',
            bytes: built.bytes, identity: identity, read_at: epoch(),
            meta: {
              protocol: memoryCapabilities(profile).protocol,
              duration_s: DEMO_JOB_SECONDS,
              region: spec,
              simulated: true,
              painted_tables: built.painted,
              painted_from: built.entry ? built.entry.path : null,
            },
          };
          var name = profile.id + '-' + region + '-'
            + (passes > 1 ? stamp() : 'read') + '.bin';
          saveImage(IMAGE_DIR + name, image);
          LAST_IMAGE = image;
          if (passes > 1) {
            // A backup is read twice and compared; the simulation is
            // deterministic, so the two passes agree — as they should.
            WS.gate.state.verified_backup = true;
            WS.gate.state.backup_path = image.path;
            CHECKPOINTS[region] = {
              path: image.path, at: image.read_at, verified: true,
            };
          }
          // A second image that differs in a nameable way, so the map diff
          // view has something to compare on a fresh page.
          if (built.xdf) {
            var tunedBytes = enrichFuel(built.bytes, built.xdf,
              built.address_base, 1.06);
            var tuned = {
              ecu_id: profile.id, region: region, source: 'edited',
              bytes: tunedBytes, identity: identity, read_at: epoch(),
              meta: {
                simulated: true, derived_from: image.path,
                edit: 'every fuelling table 6% richer, applied in the browser',
              },
            };
            saveImage(IMAGE_DIR + profile.id + '-' + region + '-tuned-demo.bin', tuned);
          }

          var result = {
            path: image.path,
            describe: describeImage(image),
            simulated: true,
            note: 'Synthesised image, ' + (built.painted === null
              ? 'no map definition available to paint against'
              : built.painted + ' tables painted from '
                + (built.entry ? built.entry.path : 'a bundled XDF'))
              + '. ' + SIM,
          };
          if (passes > 1) {
            result.verified = true;
            result.attempts = passes;
          }
          return result;
        });
      },
      {
        real_minutes: realMinutes(profile, passes),
        note: 'Time-compressed simulation of a ' + region + ' '
          + (passes > 1 ? 'backup (two verified passes)' : 'read') + '.',
      }
    );
  }

  var LAST_IMAGE = null;

  D.register('POST', '/api/memory/read', function (body) {
    var profile = currentProfile();
    return [202, readJob(profile, body.region || 'flash', { passes: 1 })];
  });

  D.register('POST', '/api/memory/backup', function (body) {
    var profile = currentProfile();
    return [202, readJob(profile, body.region || 'flash', { passes: 2 })];
  });

  function imageAt(path) {
    var image = FS[path];
    if (!image) {
      throw bad('no image at ' + JSON.stringify(path) + ' in this tab. The '
        + 'hosted demo has no disk: read or back up the ECU first, and use '
        + 'the path it gives you. Known images: '
        + (Object.keys(FS).join(', ') || 'none yet'));
    }
    return image;
  }

  function validateImage(image, profile, region) {
    var spec = regionSpec(profile, region) || {};
    var findings = [];
    var bytes = image.bytes;

    if (spec.size) {
      if (bytes.length === spec.size) {
        findings.push({ level: 'ok', check: 'size', detail: bytes.length + ' bytes, exactly as expected' });
      } else {
        findings.push({
          level: 'fatal', check: 'size',
          detail: 'image is ' + bytes.length + ' bytes, the ' + region
            + ' region of ' + profile.family + ' is ' + spec.size + ' bytes',
        });
      }
    } else {
      findings.push({
        level: 'warn', check: 'size',
        detail: 'no declared size for the ' + region + ' region of '
          + profile.family + '; cannot confirm this image belongs here',
      });
    }

    if (isBlank(bytes)) {
      findings.push({ level: 'fatal', check: 'blank', detail: 'image is entirely 0x00 or 0xFF' });
    }

    if (spec.expect_vector_table) {
      if (looksLikeVectorTable(bytes)) {
        findings.push({ level: 'ok', check: 'vector-table', detail: 'IAW vector table present at offset 0' });
      } else {
        var head = [];
        for (var i = 0; i < 16 && i < bytes.length; i++) head.push(H.hex2(bytes[i]));
        findings.push({
          level: 'fatal', check: 'vector-table',
          detail: 'no IAW vector table at offset 0 (starts ' + head.join(' ')
            + '). This is usually an encrypted .ddg container or an image for '
            + 'a different ECU, not a flashable binary.',
        });
      }
    }

    var entropy = entropyEstimate(bytes);
    if (entropy > 7.8) {
      findings.push(looksLikeVectorTable(bytes)
        ? {
          level: 'warn', check: 'entropy',
          detail: 'entropy ' + entropy.toFixed(2) + ' bits/byte is unusually '
            + 'high for firmware, but the vector table is intact',
        }
        : {
          level: 'fatal', check: 'entropy',
          detail: 'entropy ' + entropy.toFixed(2) + ' bits/byte and no vector '
            + 'table - this is an encrypted or compressed container, not a '
            + 'flashable image',
        });
    }

    var targetHw = WS.identity && WS.identity.fields
      ? String(WS.identity.fields.Hardware || '').trim() : '';
    var imageHw = hardwareStrings(bytes);
    if (targetHw && imageHw.length) {
      var family = hardwareFamily(targetHw);
      var families = imageHw.map(hardwareFamily);
      if (family && families.indexOf(family) >= 0) {
        findings.push({ level: 'ok', check: 'hardware', detail: 'image matches ' + targetHw });
      } else {
        findings.push({
          level: 'fatal', check: 'hardware',
          detail: 'ECU reports ' + targetHw + ' but the image carries '
            + imageHw.join(', ') + '. Flashing across hardware families '
            + 'bricks the ECU.',
        });
      }
    } else if (targetHw) {
      findings.push({
        level: 'warn', check: 'hardware',
        detail: 'ECU reports ' + targetHw + ' but the image embeds no hardware '
          + 'string, so compatibility cannot be confirmed',
      });
    } else {
      findings.push({
        level: 'warn', check: 'hardware',
        detail: 'ECU identity unknown; identify the ECU before writing',
      });
    }

    var fatal = findings.filter(function (f) { return f.level === 'fatal'; });
    var warnings = findings.filter(function (f) { return f.level === 'warn'; });
    return {
      ok: !fatal.length,
      fatal: fatal.length,
      warnings: warnings.length,
      findings: findings,
      image: describeImage(image),
      simulated: true,
      note: 'The checks are the workstation\'s own; the image they are run '
        + 'against was synthesised in this tab.',
    };
  }

  D.register('POST', '/api/memory/validate', function (body) {
    var profile = currentProfile();
    if (!body.path) throw bad("a 'path' to an image file is required");
    return [200, validateImage(imageAt(body.path), profile, body.region || 'flash')];
  });

  D.register('POST', '/api/memory/check-write', function (body) {
    var profile = currentProfile();
    var region = body.region || 'flash';
    var decision = WS.gate.evaluate('write:' + region, 'irreversible', {
      profile: profile, capability: 'memory_write',
    });
    return [200, decision];
  });

  D.register('POST', '/api/programming/enable', function (body) {
    var ack = 'I have a verified backup and accept the risk';
    if (String(body.acknowledgement || '').trim() !== ack) {
      throw httpError(403, 'enable-programming refused: acknowledgement: to '
        + "enable ECU programming, repeat exactly: '" + ack + "'", 'safety');
    }
    WS.gate.allow_programming = true;
    WS.gate.mode = 'programming';
    if (body.allow_unverified_keys) WS.gate.allow_unverified_keys = true;
    WS.gate.audit.push({
      at: epoch(),
      event: 'programming enabled (simulated ECU, browser demo)',
    });
    return [200, {
      programming_enabled: true,
      unverified_keys_accepted: WS.gate.allow_unverified_keys,
      simulated: true,
    }];
  });

  D.register('POST', '/api/programming/disable', function () {
    WS.gate.allow_programming = false;
    WS.gate.mode = 'simulator';
    WS.gate.audit.push({ at: epoch(), event: 'programming disabled' });
    return [200, { programming_enabled: false }];
  });

  D.register('POST', '/api/security/unverified', function (body) {
    WS.gate.allow_unverified_keys = !!body.accept;
    WS.gate.audit.push({
      at: epoch(),
      event: body.accept
        ? 'unverified key providers accepted for this session'
        : 'unverified key providers refused',
    });
    return [200, {
      allow_unverified_keys: WS.gate.allow_unverified_keys,
      simulated: true,
    }];
  });

  D.register('POST', '/api/memory/write', function (body) {
    var profile = currentProfile();
    var region = body.region || 'flash';
    if (!body.path || !body.token) throw bad("'path' and 'token' are both required");
    var image = imageAt(body.path);
    WS.gate.consume(body.token, 'write:' + region);
    securityGate();
    var spec = regionSpec(profile, region) || {};
    var validation = validateImage(image, profile, region);
    if (!validation.ok) {
      throw httpError(409, 'refusing to write: ' + validation.findings
        .filter(function (f) { return f.level === 'fatal'; })
        .map(function (f) { return f.check + ': ' + f.detail; }).join('; '),
      'validation');
    }
    return [202, startJob('write:' + region, [
      { phase: 'erase', total: spec.size || image.bytes.length, share: 0.5, message: addressMessage(spec.start || 0) },
      { phase: 'write', total: spec.size || image.bytes.length, share: 2, message: addressMessage(spec.start || 0) },
      { phase: 'verify', total: spec.size || image.bytes.length, share: 1, message: addressMessage(spec.start || 0) },
    ], function () {
      // The ECU now holds what was written: that is what a write means.
      var written = {
        ecu_id: profile.id, region: region, source: 'write',
        bytes: new Uint8Array(image.bytes), identity: image.identity,
        read_at: epoch(),
        meta: {
          protocol: memoryCapabilities(profile).protocol,
          duration_s: DEMO_JOB_SECONDS * 1.5,
          region: spec, simulated: true, written_from: image.path,
        },
      };
      ECU_CONTENT = written;
      return {
        path: image.path,
        verified: true,
        attempts: 1,
        blocks: spec.block ? Math.ceil(written.bytes.length / spec.block) : null,
        describe: describeImage(written),
        simulated: true,
        note: 'Simulated write: the bytes were "programmed" into the in-tab '
          + 'ECU model and read back for verification. Against a real 5AM '
          + 'this is the one operation GuzziOnBoard still refuses — the key '
          + 'algorithm has never been confirmed on a Guzzi-fitted ECU, and a '
          + 'failed write is a brick.',
      };
    }, {
      real_minutes: Math.max(1, Math.round(realMinutes(profile, 1) * 0.6)),
      note: 'Time-compressed simulation of erase, write and verify.',
    })];
  });

  var ECU_CONTENT = null;

  /* ======================================================================
   * 8. Maps and tables
   * ======================================================================
   * The XDFs are real third-party definition files, vendored into this
   * repository and published by Pages alongside this page; the browser
   * fetches and parses the same bytes the Python workstation reads. The
   * dump they are rendered against is the synthesised one, so the shape of
   * every table is real and the calibration in it is not.
   */

  function xdfEntryFor(ref) {
    var wanted = String(ref || '').trim();
    var found = null;
    xdfIndex().forEach(function (entry) {
      if (found) return;
      if (entry.title === wanted || entry.path.split('/').pop() === wanted
        || entry.path === wanted) found = entry;
    });
    if (!found) {
      throw bad('no XDF named ' + JSON.stringify(wanted) + ' in the bundled '
        + 'library. The hosted demo can only use the ' + xdfIndex().length
        + ' definitions shipped with the project — the local workstation also '
        + 'reads ~/.guzzionboard/xdfs.');
    }
    return found;
  }

  function addressBaseOf(body) {
    var base = body.address_base;
    if (base === null || base === undefined || base === '') return null;
    var value = /^0[xX]/.test(String(base))
      ? parseInt(String(base), 16) : parseInt(String(base), 10);
    if (isNaN(value)) throw bad('address_base ' + JSON.stringify(base) + ' is not a number');
    return value;
  }

  D.register('GET', '/api/maps', function () {
    return [200, {
      directory: 'guzzionboard/xdfs, bundled with the project and fetched '
        + 'from this site (the local workstation also reads ~/.guzzionboard/xdfs)',
      bundled_directory: 'guzzionboard/xdfs (fetched from this site)',
      xdfs: xdfIndex().map(function (entry) {
        return {
          title: entry.title, path: entry.path, version: entry.version,
          tables: entry.tables, constants: entry.constants,
          unsupported: entry.unsupported, region_size: entry.region_size,
          categories: entry.categories,
        };
      }),
      simulated: true,
      demo_note: 'The definitions are the real bundled XDFs. The dump they '
        + 'are rendered against is synthesised in your browser.',
    }];
  });

  D.register('POST', '/api/maps/render', function (body) {
    if (!body.path) throw bad("an image 'path' is required");
    if (!body.xdf) throw bad("an 'xdf' (title or .xdf path) is required");
    var image = imageAt(body.path);
    var base = addressBaseOf(body);
    return loadXdf(xdfEntryFor(body.xdf)).then(function (xdf) {
      var render = renderXdf(xdf, image, base);
      render.image = describeImage(image);
      render.simulated = true;
      render.demo_note = 'Real TunerPro definition, simulated dump: the table '
        + 'names, addresses, axes and scalings come from ' + xdf.path
        + '; the values come from an image this page invented.';
      return [200, render];
    });
  });

  D.register('POST', '/api/maps/diff', function (body) {
    if (!(body.path_a && body.path_b)) throw bad("'path_a' and 'path_b' are both required");
    if (!body.xdf) throw bad("an 'xdf' (title or .xdf path) is required");
    var before = imageAt(body.path_a);
    var after = imageAt(body.path_b);
    var base = addressBaseOf(body);
    return loadXdf(xdfEntryFor(body.xdf)).then(function (xdf) {
      var diff;
      try {
        diff = diffXdf(xdf, before, after, base);
      } catch (exc) {
        throw bad(String(exc.message || exc));
      }
      diff.image = describeImage(before);
      diff.simulated = true;
      return [200, diff];
    });
  });

  /* ======================================================================
   * 9. Sessions: recording, replay, export, comparison
   * ======================================================================
   * The workstation writes every frame, sample, decision and action to a
   * JSONL file under ~/.guzzionboard/sessions. A web page has no disk, so
   * this records the same events into memory for as long as the tab is
   * open — and ships two pre-recorded ones so the replay and compare views
   * have something to work with the moment you open them.
   */

  var SESSIONS = [];              // newest first, like the real listing
  var LIVE_SESSION = null;

  function sessionBytes(session) {
    // The size the same log would have on disk, so the listing is not a lie
    // about scale: the events really are this big as JSONL.
    var total = 0;
    session.events.forEach(function (event) {
      total += JSON.stringify(event).length + 1;
    });
    return total;
  }

  function sessionEntry(session) {
    return {
      path: '(in this browser tab) ' + session.name,
      name: session.name,
      size: sessionBytes(session),
      modified: session.modified || session.started,
      meta: session.meta,
      simulated: true,
      live: !!session.live,
    };
  }

  function findSession(name) {
    var found = null;
    SESSIONS.forEach(function (s) { if (s.name === name) found = s; });
    if (!found) {
      throw httpError(404, 'no such session: ' + JSON.stringify(name), 'not_found');
    }
    return found;
  }

  function record(session, kind, payload) {
    if (!session) return;
    var event = Object.assign({ t: round(epoch(), 4), kind: kind }, payload);
    session.events.push(event);
    session.modified = event.t;
    if (session.events.length > 20000) session.events.shift();
  }

  function startLiveSession() {
    var profile = WS.sessionProfile || WS.selection.profile || {};
    var session = {
      name: stamp() + '-browser-demo.jsonl',
      started: epoch(),
      modified: epoch(),
      live: true,
      meta: {
        app_version: data().version,
        model: WS.selection.model,
        year: WS.selection.year,
        ecu: profile.id || '',
        ecu_family: profile.family || '',
        transport: 'simulator (browser)',
        mode: WS.gate.mode,
        demo: true,
        simulated: true,
      },
      events: [],
    };
    record(session, 'session_start', { meta: session.meta, id: session.name });
    SESSIONS.unshift(session);
    LIVE_SESSION = session;
    return session;
  }

  /* -- the two pre-recorded sessions ----------------------------------- */

  function encodeRaw(key, value) {
    /* Encode an engineering value back into the bytes the ECU would have
     * sent, using this family's own scaling — so an exported CSV carries
     * raw bytes that really do decode to the value beside them. */
    var profiles = data().profiles || {};
    var profile = profiles[(WS.selection.profile || {}).id || '5am'] || profiles['5am'];
    var meta = profile && profile.parameters ? profile.parameters[key] : null;
    if (!meta) return '';
    var raw = meta.recip
      ? (value ? Math.round(meta.recip / value) : 0)
      : Math.round((value - (meta.bias || 0)) / (meta.scale === undefined ? 1 : meta.scale));
    var length = meta.length || 1;
    var limit = Math.pow(2, length * 8);
    raw = ((Math.round(raw) % limit) + limit) % limit;
    var out = '';
    for (var i = length - 1; i >= 0; i--) {
      out += ('0' + (Math.floor(raw / Math.pow(256, i)) & 0xFF).toString(16)).slice(-2);
    }
    return out;
  }

  var UNITS = {
    rpm: 'rpm', coolant_temp: '\u00b0C', air_temp: '\u00b0C', throttle: '\u00b0',
    battery: 'V', injection_ms: 'ms', lambda_f: 'mV', lambda_r: 'mV',
    lambda_int_f: '%', lambda_int_r: '%', idle_target: 'rpm',
    stepper_position: 'steps', stepper_base: 'steps', road_speed: 'km/h',
    advance: '\u00b0',
  };

  function cannedSession(spec) {
    var session = {
      name: spec.name,
      started: epoch() - spec.ago,
      modified: epoch() - spec.ago + spec.seconds,
      live: false,
      canned: true,
      meta: Object.assign({
        app_version: data().version,
        transport: 'simulator (pre-recorded for the demo)',
        mode: 'simulator',
        demo: true,
        simulated: true,
      }, spec.meta),
      events: [],
    };
    var t = session.started;
    session.events.push({
      t: round(t, 4), kind: 'session_start',
      meta: session.meta, id: session.name,
    });
    var step = 0.5;
    var noise = H.rng(spec.seed || 11);
    for (var elapsed = 0; elapsed <= spec.seconds; elapsed += step) {
      var values = spec.sample(elapsed, function (amount) {
        return (noise() * 2 - 1) * amount;
      });
      var at = session.started + elapsed;
      Object.keys(values).forEach(function (key) {
        var value = round(values[key], 2);
        session.events.push({
          t: round(at, 4), kind: 'sample', key: key,
          lid: 0, raw: encodeRaw(key, value), value: value,
          unit: UNITS[key] || '',
        });
        at += 0.012;              // the sweep takes time, like a real one
      });
    }
    if (spec.dtcs && spec.dtcs.length) {
      session.events.push({
        t: round(session.modified, 4), kind: 'action', name: 'read_dtcs',
        detail: { dtcs: spec.dtcs, context: {} },
      });
    }
    session.events.push({
      t: round(session.modified, 4), kind: 'session_end',
      counts: { sample: session.events.length },
    });
    return session;
  }

  function seedSessions() {
    if (SESSIONS.some(function (s) { return s.canned; })) return;
    SESSIONS.push(cannedSession({
      name: 'demo-20260912-warmup-healthy.jsonl',
      ago: 86400 * 3, seconds: 180, seed: 11,
      meta: { model: 'Griso 1200 8V', year: 2012, ecu: '5am', ecu_family: 'IAW 5AM' },
      dtcs: [],
      sample: function (t, jitter) {
        var warm = 1 - Math.exp(-t / 95);
        var coolant = 18 + 74 * warm;
        var closed = coolant > 60;
        return {
          rpm: 1180 + jitter(35) + (closed ? 0 : 160 * (1 - warm)),
          idle_target: 1250 - 100 * warm,
          coolant_temp: coolant + jitter(0.4),
          air_temp: 18.5 + jitter(0.5),
          throttle: 3.2 + jitter(0.1),
          battery: 13.9 + jitter(0.08),
          injection_ms: 2.45 - 0.55 * warm + jitter(0.05),
          lambda_f: closed ? 450 + 330 * Math.sin(t * 2.1) : 440 + jitter(10),
          lambda_r: closed ? 450 + 320 * Math.sin(t * 2.1 + 0.6) : 445 + jitter(10),
          lambda_int_f: closed ? 1.4 + 2.0 * Math.sin(t / 7) : 0,
          lambda_int_r: closed ? 1.1 + 2.2 * Math.sin(t / 7 + 1) : 0,
          stepper_base: 42,
          stepper_position: 44 - 2 * warm + jitter(0.6),
          advance: 11 + 2 * warm + jitter(0.5),
          road_speed: 0,
        };
      },
    }));
    SESSIONS.push(cannedSession({
      name: 'demo-20260919-idle-hunting.jsonl',
      ago: 86400, seconds: 150, seed: 29,
      meta: { model: 'Griso 1200 8V', year: 2012, ecu: '5am', ecu_family: 'IAW 5AM' },
      dtcs: [
        { code: 'P0505', status: 'stored', description: 'Idle control system - stepper or air leak' },
        { code: 'P0130', status: 'stored', description: 'Lambda sensor circuit, bank 1 sensor 1' },
      ],
      sample: function (t, jitter) {
        var hunt = 240 * Math.sin(t / 3.1) + 90 * Math.sin(t / 1.3);
        return {
          rpm: 1640 + hunt + jitter(50),
          idle_target: 1150,
          coolant_temp: 88 + jitter(0.6),
          air_temp: 21 + jitter(0.5),
          throttle: 3.1 + jitter(0.1),
          battery: 13.75 + jitter(0.1),
          injection_ms: 2.9 + jitter(0.12),
          lambda_f: 452 + 18 * Math.sin(t * 1.7),      // barely moving
          lambda_r: 450 + 300 * Math.sin(t * 2.3),
          lambda_int_f: 7.5 + jitter(0.8),
          lambda_int_r: -5.2 + jitter(0.8),
          stepper_base: 42,
          stepper_position: 28 + jitter(1.2),          // closing right down
          advance: 14 + jitter(0.6),
          road_speed: 0,
        };
      },
    }));
    SESSIONS.sort(function (a, b) { return b.modified - a.modified; });
  }

  /* -- sweeps, CSV, replay (ports of guzzionboard/replay.py) ------------ */

  var SWEEP_GAP_S = 0.35;

  function sweepsOf(events) {
    var out = [];
    var current = null;
    events.forEach(function (event) {
      if (event.kind !== 'sample') return;
      var t = Number(event.t || 0);
      if (!current || t - current.t_last > SWEEP_GAP_S
        || Object.prototype.hasOwnProperty.call(current.values, event.key)) {
        current = { t: t, t_last: t, values: {} };
        out.push(current);
      }
      current.t_last = t;
      current.values[event.key] = {
        key: event.key, value: event.value, unit: event.unit || '',
        raw: event.raw || '',
        local_id: event.local_id !== undefined ? event.local_id : event.lid,
      };
    });
    out.forEach(function (sweep) { delete sweep.t_last; });
    return out;
  }

  function channelsOf(sweepList) {
    var seen = [];
    sweepList.forEach(function (sweep) {
      Object.keys(sweep.values).forEach(function (key) {
        if (seen.indexOf(key) < 0) seen.push(key);
      });
    });
    return seen;
  }

  function csvCell(value) {
    var text = value === null || value === undefined ? '' : String(value);
    return /[",\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
  }

  function sessionCsv(events) {
    var sweepList = sweepsOf(events);
    var keys = channelsOf(sweepList);
    var units = {};
    sweepList.forEach(function (sweep) {
      Object.keys(sweep.values).forEach(function (key) {
        if (units[key] === undefined) units[key] = sweep.values[key].unit || '';
      });
    });
    var lines = [];
    lines.push(['time_unix', 'elapsed_s'].concat(keys,
      keys.map(function (k) { return k + '_raw'; })).map(csvCell).join(','));
    lines.push(['', 's'].concat(keys.map(function (k) { return units[k] || ''; }),
      keys.map(function () { return 'bytes'; })).map(csvCell).join(','));
    var t0 = sweepList.length ? sweepList[0].t : 0;
    sweepList.forEach(function (sweep) {
      var row = [sweep.t.toFixed(4), (sweep.t - t0).toFixed(3)];
      keys.forEach(function (key) {
        row.push(sweep.values[key] ? sweep.values[key].value : '');
      });
      keys.forEach(function (key) {
        row.push(sweep.values[key] ? sweep.values[key].raw : '');
      });
      lines.push(row.map(csvCell).join(','));
    });
    return lines.join('\n') + (lines.length ? '\n' : '');
  }

  /* Derived channels and findings are recomputed from the recorded samples,
   * with the live window temporarily replaced by the recorded one so a
   * sixty-second average means the same thing on replay as it did live. */
  function withRecordedHistory(sweepList, index, fn) {
    var saved = WS.history;
    var now = mono();
    var last = sweepList[index].t;
    WS.history = [];
    for (var i = 0; i < index; i++) {
      var values = {};
      Object.keys(sweepList[i].values).forEach(function (key) {
        var value = sweepList[i].values[key].value;
        if (typeof value === 'number') values[key] = value;
      });
      var age = last - sweepList[i].t;
      if (age <= 60) WS.history.push([now - age, values]);
    }
    try {
      return fn();
    } finally {
      WS.history = saved;
    }
  }

  function replayFrames(session) {
    var sweepList = sweepsOf(session.events);
    var t0 = sweepList.length ? sweepList[0].t : 0;
    var frames = sweepList.map(function (sweep, index) {
      var samples = Object.keys(sweep.values).map(function (key) {
        var entry = sweep.values[key];
        return {
          key: key, name: key, local_id: entry.local_id || 0,
          raw: entry.raw || '', value: entry.value, unit: entry.unit || '',
          text: '', error: '',
        };
      });
      var derived = withRecordedHistory(sweepList, index, function () {
        return H.computeDerived(samples);
      });
      return {
        t: round(sweep.t, 4),
        elapsed: round(sweep.t - t0, 3),
        values: sweep.values,
        derived: derived,
        findings: plausibility(samples, derived),
      };
    });
    return {
      name: session.name,
      frames: frames,
      channels: channelsOf(sweepList),
      duration_s: frames.length ? round(frames[frames.length - 1].elapsed, 3) : 0,
      simulated: true,
      note: 'Replayed from the recorded samples. Derived values and findings '
        + 'are recomputed now, from the bytes that were recorded then.',
    };
  }

  function statsOf(values) {
    return {
      count: values.length,
      first: round(values[0], 2),
      last: round(values[values.length - 1], 2),
      min: round(Math.min.apply(null, values), 2),
      max: round(Math.max.apply(null, values), 2),
      mean: round(values.reduce(function (a, b) { return a + b; }, 0) / values.length, 2),
    };
  }

  function summariseSession(session) {
    var samples = {};
    var units = {};
    var dtcs = [];
    var counts = {};
    var span = [];
    session.events.forEach(function (event) {
      if (event.kind === 'session_end') counts = event.counts || {};
      else if (event.kind === 'sample') {
        if (typeof event.value === 'number') {
          if (!samples[event.key]) samples[event.key] = [];
          samples[event.key].push(event.value);
          units[event.key] = event.unit || '';
        }
        span.push(Number(event.t || 0));
      } else if (event.kind === 'action' && event.name === 'read_dtcs') {
        dtcs = (event.detail || {}).dtcs || [];
      }
    });
    var channels = {};
    Object.keys(samples).forEach(function (key) {
      channels[key] = Object.assign(statsOf(samples[key]), { unit: units[key] || '' });
    });
    return {
      name: session.name,
      meta: session.meta,
      channels: channels,
      dtcs: dtcs.map(function (d) { return d.code; }).filter(Boolean),
      counts: counts,
      span_s: span.length > 1 ? round(span[span.length - 1] - span[0], 1) : 0,
    };
  }

  function compareSessions(a, b) {
    var sa = summariseSession(a);
    var sb = summariseSession(b);
    var keys = Object.keys(sa.channels).concat(Object.keys(sb.channels))
      .filter(function (key, index, all) { return all.indexOf(key) === index; })
      .sort();
    var channels = keys.map(function (key) {
      var ca = sa.channels[key] || null;
      var cb = sb.channels[key] || null;
      return {
        key: key,
        unit: (ca || cb || {}).unit || '',
        a: ca, b: cb,
        delta_mean: ca && cb ? round(cb.mean - ca.mean, 2) : null,
      };
    });
    var codesA = sa.dtcs, codesB = sb.dtcs;
    var inBoth = codesA.filter(function (c) { return codesB.indexOf(c) >= 0; });
    return {
      a: { name: sa.name, meta: sa.meta, counts: sa.counts, span_s: sa.span_s },
      b: { name: sb.name, meta: sb.meta, counts: sb.counts, span_s: sb.span_s },
      channels: channels,
      channels_only_in_a: channels.filter(function (c) { return c.a && !c.b; })
        .map(function (c) { return c.key; }),
      channels_only_in_b: channels.filter(function (c) { return c.b && !c.a; })
        .map(function (c) { return c.key; }),
      dtcs: {
        both: inBoth.slice().sort(),
        only_a: codesA.filter(function (c) { return codesB.indexOf(c) < 0; }).sort(),
        only_b: codesB.filter(function (c) { return codesA.indexOf(c) < 0; }).sort(),
      },
      simulated: true,
    };
  }

  D.register('GET', '/api/sessions', function () {
    seedSessions();
    var list = SESSIONS.slice().sort(function (a, b) { return b.modified - a.modified; });
    return [200, {
      sessions: list.map(sessionEntry),
      simulated: true,
      note: 'Recorded in this browser tab, not on disk — closing the tab '
        + 'throws them away. Two of them were pre-recorded from the same '
        + 'simulated engine so the replay and compare views have something '
        + 'to chew on. The local workstation writes real JSONL files to '
        + '~/.guzzionboard/sessions.',
    }];
  });

  D.register('GET', '/api/sessions/events', function (q) {
    seedSessions();
    var session = findSession(q.get('name') || '');
    var limit = parseInt(q.get('limit') || '500', 10) || 500;
    return [200, {
      name: session.name,
      total: session.events.length,
      events: session.events.slice(-limit),
      simulated: true,
    }];
  });

  D.register('GET', '/api/sessions/export', function (q) {
    seedSessions();
    var session = findSession(q.get('name') || '');
    var format = q.get('format') || 'csv';
    var content;
    if (format === 'json') {
      content = JSON.stringify(sweepsOf(session.events).map(function (sweep) {
        var row = { time: round(sweep.t, 2) };
        Object.keys(sweep.values).forEach(function (key) {
          row[key] = sweep.values[key].value;
        });
        return row;
      }), null, 2);
    } else if (format === 'csv' || format === 'csv_plain') {
      content = sessionCsv(session.events);
    } else {
      throw bad('unknown format ' + JSON.stringify(format));
    }
    var headerRows = format === 'csv' ? 2 : 1;
    return [200, {
      format: format,
      name: session.name,
      filename: session.name.replace(/\.jsonl$/, '') + (format === 'json' ? '.json' : '.csv'),
      rows: Math.max(0, (content.split('\n').length - 1) - headerRows),
      content: content,
      csv: format === 'json' ? '' : content,
      simulated: true,
      note: 'One row per polling sweep. The second row carries the units, and '
        + 'the raw bytes travel with every value.',
    }];
  });

  D.register('GET', '/api/sessions/replay', function (q) {
    seedSessions();
    return [200, replayFrames(findSession(q.get('name') || ''))];
  });

  D.register('POST', '/api/sessions/compare', function (body) {
    seedSessions();
    if (!(body.a && body.b)) throw bad("two session names, 'a' and 'b', are required");
    if (body.a === body.b) throw bad('pick two different sessions');
    return [200, compareSessions(findSession(body.a), findSession(body.b))];
  });

  /* ======================================================================
   * 10. Plausibility checks — a port of the rules in derived.py
   * ======================================================================
   * These are the workstation's opinion, not the ECU's: every one of them
   * is labelled as an interpretation in the UI, and so it is here.
   */

  function readings(samples) {
    var byKey = {};
    samples.forEach(function (s) { byKey[s.key] = s; });
    return {
      v: function (key) {
        var s = byKey[key];
        return s && typeof s.value === 'number' ? s.value : null;
      },
      text: function (key) {
        var s = byKey[key];
        return s && s.text ? s.text : '';
      },
      running: function () {
        var text = this.text('stop_state');
        if (text) return text === 'Running';
        var rpm = this.v('rpm');
        if (rpm === null) return null;
        return rpm > 200;
      },
    };
  }

  function finding(key, level, title, detail, suspects, evidence) {
    return {
      key: key, level: level, title: title, detail: detail,
      suspects: suspects || [], evidence: evidence || {},
    };
  }

  function plausibility(samples, derived) {
    var r = readings(samples);
    var d = {};
    (derived || []).forEach(function (c) { d[c.key] = c.value; });
    var out = [];
    var running = r.running();

    var coolant = r.v('coolant_temp');
    if (coolant !== null && (coolant <= -30 || coolant >= 130)) {
      out.push(finding('coolant_sensor_range', 'bad',
        'Head temperature is outside anything physical',
        coolant.toFixed(0) + ' \u00b0C is the rail, not a temperature. An open '
        + 'circuit reads one end of the scale and a short reads the other, '
        + 'and the ECU will be fuelling to that number.',
        ['Head temperature sensor', 'Sensor wiring or connector'],
        { coolant_temp: coolant.toFixed(1) + ' \u00b0C' }));
    }

    var split = d.temp_split;
    if (split !== undefined && running === false && split < -8) {
      out.push(finding('sensor_disagreement', 'warn',
        'Head reads colder than the intake air',
        'A ' + Math.abs(split).toFixed(0) + ' \u00b0C split the wrong way on a '
        + 'stopped engine means one of the two sensors, or its scaling, is wrong.',
        ['Head temperature sensor', 'Air temperature sensor',
          'Catalog scaling for this family'],
        { temp_split: split.toFixed(1) + ' \u00b0C' }));
    }

    var volts = r.v('battery');
    if (volts !== null) {
      if (running && volts < 13.0) {
        out.push(finding('charging', 'bad', 'Not charging',
          volts.toFixed(1) + ' V with the engine running. A healthy charging '
          + 'system holds 13.5-14.5 V; below 13 V the bike is running off the '
          + 'battery and will eventually stop.',
          ['Alternator or stator', 'Regulator/rectifier', 'Charging wiring'],
          { battery: volts.toFixed(1) + ' V' }));
      } else if (running && volts > 15.2) {
        out.push(finding('overcharge', 'bad', 'Charging voltage too high',
          volts.toFixed(1) + ' V will cook the battery and can take '
          + 'electronics with it.',
          ['Regulator/rectifier', 'Earth connections'],
          { battery: volts.toFixed(1) + ' V' }));
      } else if (running === false && volts < 12.0) {
        out.push(finding('battery_low', 'warn', 'Resting battery is low',
          volts.toFixed(1) + ' V with the engine stopped. Below about 12.0 V '
          + 'the battery is flat enough to confuse every other reading here, '
          + 'and actuator tests will brown out the ECU.',
          ['Battery', 'Parasitic drain'],
          { battery: volts.toFixed(1) + ' V' }));
      }
    }

    var error = d.idle_error;
    if (error !== undefined && running
      && ['', 'Shut'].indexOf(r.text('throttle_closed')) >= 0
      && Math.abs(error) >= 200) {
      var drift = d.stepper_drift;
      var suspects;
      if (error > 0 && drift !== undefined && drift < -5) {
        suspects = ['Air leak after the throttle', 'Throttle stop adjustment',
          'Throttle plate not closing'];
      } else if (error > 0) {
        suspects = ['Idle stepper stuck open', 'Air leak after the throttle',
          'Throttle stop adjustment'];
      } else {
        suspects = ['Idle stepper jammed closed', 'Idle fuelling',
          'Throttle body balance'];
      }
      var evidence = { idle_error: (error > 0 ? '+' : '') + error.toFixed(0) + ' rpm' };
      if (drift !== undefined) {
        evidence.stepper_drift = (drift > 0 ? '+' : '') + drift.toFixed(0) + ' steps';
      }
      out.push(finding('idle_control', 'warn',
        'Idle is not sitting on its target',
        (error > 0 ? '+' : '') + error.toFixed(0) + ' rpm away from the ECU\'s target'
        + (drift !== undefined
          ? ', with the stepper ' + (drift > 0 ? '+' : '') + drift.toFixed(0)
            + ' steps off its base' : '')
        + '. The ECU is asking for one speed and getting another.',
        suspects, evidence));
    }

    var duty = d.inj_duty;
    if (duty !== undefined && duty > 85) {
      out.push(finding('inj_duty', 'bad', 'Injectors are nearly flat out',
        duty.toFixed(0) + '% duty leaves no headroom: the injector is open '
        + 'almost continuously and cannot deliver more fuel.',
        ['Fuel pressure', 'Blocked injectors',
          'Undersized injectors for a modified engine', 'Lean-biased map'],
        { inj_duty: duty.toFixed(0) + ' %' }));
    }

    var share = d.closed_loop_share;
    if (running && share !== undefined && share >= 50) {
      [['f', 'front'], ['r', 'rear']].some(function (bank) {
        var swing = d['lambda_swing_' + bank[0]];
        if (swing === undefined || swing >= 100) return false;
        var evid = {};
        evid['lambda_swing_' + bank[0]] = swing.toFixed(0) + ' mV';
        out.push(finding('lambda_lazy_' + bank[0], 'warn',
          'Lambda sensor (' + bank[1] + ') is barely moving',
          swing.toFixed(0) + ' mV of swing over the last minute while the ECU '
          + 'says it is in closed loop. A working narrowband sensor sweeps '
          + 'several hundred millivolts as the mixture crosses stoichiometric.',
          ['Lambda sensor, ' + bank[1] + ' bank', 'Sensor heater',
            'Exhaust leak upstream of the sensor'], evid));
        return true;
      });
    }

    var balance = d.bank_balance;
    if (balance !== undefined && running && Math.abs(balance) >= 10) {
      var lean = balance > 0 ? 'front' : 'rear';
      out.push(finding('bank_split', 'warn',
        'The ' + lean + ' cylinder needs much more correction',
        Math.abs(balance).toFixed(1) + ' percentage points between the two '
        + 'integrators. Both cylinders run off one map, so a persistent split '
        + 'is a mechanical or air-path difference, not a mapping one.',
        ['Air leak on the ' + lean + ' cylinder', 'Injector, ' + lean + ' cylinder',
          'Throttle body balance', 'Valve clearances'],
        { bank_balance: (balance > 0 ? '+' : '') + balance.toFixed(1) + ' %' }));
    }

    if (running && share !== undefined && coolant !== null
      && coolant > 70 && share < 10) {
      out.push(finding('open_loop', 'warn', 'Still open loop on a warm engine',
        'The head is at ' + coolant.toFixed(0) + ' \u00b0C but the ECU stayed '
        + 'in open loop for ' + (100 - share).toFixed(0) + '% of the last '
        + 'minute. It is fuelling from the map alone and ignoring the sensors.',
        ['Lambda sensors or heaters', 'A stored fault forcing open loop',
          'Decatted or modified exhaust'],
        {
          closed_loop_share: share.toFixed(0) + ' %',
          coolant_temp: coolant.toFixed(0) + ' \u00b0C',
        }));
    }

    return out;
  }

  /* ======================================================================
   * 11. Comms quality: the sliders now spoil something
   * ======================================================================
   * There is no wire here, so these act at the API seam instead of on
   * frames: a "dropped" read returns the timeout the stack would have
   * raised, a "corrupted" one the checksum error, responsePending adds the
   * wait it causes, and the latency slider adds real milliseconds. The
   * shape of the failure is right; the layer it happens at is not, and the
   * UI says so.
   */

  var commsRand = H.rng(99991);

  function applyComms(samples) {
    var comms = (WS.ecu && WS.ecu.comms) || {};
    var drop = Number(comms.drop_rate || 0);
    var corrupt = Number(comms.corrupt_rate || 0);
    var pending = Number(comms.pending_rate || 0);
    var spoiled = { dropped: 0, corrupted: 0, pending: 0 };
    var out = samples.map(function (sample) {
      if (drop > 0 && commsRand() < drop) {
        spoiled.dropped++;
        return Object.assign({}, sample, {
          value: null, text: '', raw: '',
          error: 'no response within 250 ms (simulated dropped frame)',
        });
      }
      if (corrupt > 0 && commsRand() < corrupt) {
        spoiled.corrupted++;
        return Object.assign({}, sample, {
          value: null, text: '', raw: sample.raw,
          error: 'checksum mismatch, frame discarded (simulated line noise)',
        });
      }
      if (pending > 0 && commsRand() < pending) {
        spoiled.pending++;
        return Object.assign({}, sample, {
          pending_waits: 1,
          note: 'ECU answered responsePending (0x78) once before the data',
        });
      }
      return sample;
    });
    return { samples: out, spoiled: spoiled };
  }

  function commsDelay() {
    var comms = (WS.ecu && WS.ecu.comms) || {};
    var extra = Number(comms.extra_latency || 0);
    var pendingCost = 0;
    if (!extra && !pendingCost) return null;
    return clamp(extra, 0, 5);
  }

  D.hooks.comms = true;          // demo-api leaves the sliders enabled

  D.hooks.live = function (samples, keys) {
    var spoiled = applyComms(samples);
    var kept = spoiled.samples;
    var derived = H.computeDerived(kept.filter(function (s) { return !s.error; }));
    var findings = plausibility(kept, derived);
    var payload = {
      at: epoch(),
      samples: kept,
      derived: derived,
      findings: findings,
      analysis_note: 'Derived values are computed by the workstation from the '
        + 'samples above, not read from the ECU. Findings are interpretations, '
        + 'not measurements.',
      simulated: true,
    };
    if (spoiled.spoiled.dropped || spoiled.spoiled.corrupted || spoiled.spoiled.pending) {
      payload.comms = Object.assign({ simulated: true }, spoiled.spoiled);
      payload.comms_note = 'Comms quality is simulated at the API seam, not on '
        + 'a wire: ' + spoiled.spoiled.dropped + ' read(s) dropped, '
        + spoiled.spoiled.corrupted + ' corrupted, '
        + spoiled.spoiled.pending + ' delayed by responsePending.';
    }
    if (LIVE_SESSION) {
      kept.forEach(function (sample) {
        if (sample.error) return;
        record(LIVE_SESSION, 'sample', {
          key: sample.key, lid: sample.local_id,
          raw: (sample.raw || '').replace(/ /g, ''),
          value: sample.value, unit: sample.unit,
        });
      });
    }
    var delay = commsDelay();
    if (!delay) return [200, payload];
    return new Promise(function (resolve) {
      setTimeout(function () { resolve([200, payload]); }, delay * 1000);
    });
  };

  D.hooks.event = function (kind, detail) {
    if (kind === 'connect') {
      startLiveSession();
      return;
    }
    if (kind === 'disconnect') {
      if (LIVE_SESSION) {
        record(LIVE_SESSION, 'session_end', { counts: { sample: LIVE_SESSION.events.length } });
        LIVE_SESSION.live = false;
      }
      LIVE_SESSION = null;
      return;
    }
    if (!LIVE_SESSION) return;
    if (kind === 'safety') record(LIVE_SESSION, 'safety', detail);
    else if (kind === 'dtcs') {
      record(LIVE_SESSION, 'action', { name: 'read_dtcs', detail: { dtcs: detail, context: {} } });
    } else if (kind === 'action') record(LIVE_SESSION, 'action', detail);
  };

  /* ======================================================================
   * 12. The report — a port of Workstation.build_report / report_text
   * ====================================================================== */

  function isCelsius(unit) { return String(unit || '').indexOf('\u00b0C') >= 0; }

  function buildReport() {
    var profile = WS.sessionProfile || WS.selection.profile;
    var samples = Object.keys(WS.lastSamples).map(function (key) {
      return WS.lastSamples[key];
    });
    var derived = samples.length ? H.computeDerived(samples) : [];
    var dtcs = [];
    if (WS.connected && WS.ecu) {
      try { dtcs = WS.ecu.readDtcs(); } catch (exc) { dtcs = []; }
    }
    return {
      generated_at: epoch(),
      generated_at_text: timeText(),
      tool: { name: 'GuzziOnBoard', version: data().version },
      vehicle: H.describeSelection(),
      mode: WS.gate.mode,
      trust: {
        ecu_definition_confidence: profile ? profile.confidence : 'unknown',
        transport: 'simulator',
        simulated: true,
        caveat: 'Values are decoded with catalog scalings. Anything below '
          + "'documented' confidence is an interpretation, not a measurement.",
      },
      identity: WS.identity,
      samples: samples,
      dtcs: dtcs,
      safety_audit: WS.gate.audit,
      session: H.sessionSummary(),
      derived: derived,
      findings: plausibility(samples, derived),
      demo: true,
      demo_note: 'Built in the browser from the simulated ECU. The local '
        + 'workstation writes the same report to text, JSON and PDF.',
    };
  }

  function reportText(report, tempUnit) {
    var fahrenheit = String(tempUnit || 'C').trim().toUpperCase().charAt(0) === 'F';
    var rule = new Array(61).join('-');
    var lines = [
      'GuzziOnBoard diagnostic report',
      new Array(61).join('='),
      'Generated : ' + report.generated_at_text,
      'Tool      : ' + report.tool.name + ' ' + report.tool.version,
      'Mode      : ' + report.mode
        + (report.trust.simulated ? '   *** SIMULATED - NOT A REAL MOTORCYCLE ***' : ''),
      '',
      'Vehicle',
      rule,
    ];
    var sel = report.vehicle || {};
    lines.push('Model     : ' + (sel.model || 'n/a') + ' ' + (sel.year || ''));
    if (sel.ecu) {
      lines.push('ECU       : ' + sel.ecu.display_name + ' (' + sel.ecu.years + ')');
      lines.push('Confidence: ' + sel.ecu.confidence);
    }
    lines.push('Transport : ' + report.trust.transport);

    if (report.identity && report.identity.fields) {
      lines.push('', 'ECU identification', rule);
      Object.keys(report.identity.fields).forEach(function (key) {
        lines.push(pad(key, 12) + ': ' + report.identity.fields[key]);
      });
    }

    lines.push('', 'Fault codes', rule);
    if (report.dtcs && report.dtcs.length) {
      report.dtcs.forEach(function (d) {
        lines.push((d.warning_indicator ? '!' : ' ') + ' ' + d.code + '  '
          + pad(d.status, 8) + ' ' + (d.description || ''));
      });
    } else {
      lines.push('None reported.');
    }

    lines.push('', 'Live values at capture', rule);
    report.samples.forEach(function (s) {
      if (s.error) {
        lines.push(pad(s.name, 30) + ' ERROR ' + s.error);
        return;
      }
      var value = s.value;
      var unit = s.unit;
      if (fahrenheit && isCelsius(unit) && typeof value === 'number') {
        value = round(value * 9 / 5 + 32, 1);
        unit = '\u00b0F';
      }
      var shown = s.text || (String(value) + ' ' + unit).trim();
      lines.push(pad(s.name, 30) + ' ' + pad(shown, 18) + ' raw=' + s.raw
        + '  (0x' + H.hex2(s.local_id).toUpperCase() + ')');
    });

    if (report.derived && report.derived.length) {
      lines.push('', 'Derived by the workstation (not read from the ECU)', rule);
      report.derived.forEach(function (c) {
        var value = c.value, unit = c.unit;
        if (fahrenheit && isCelsius(unit)) {
          value = c.delta ? round(value * 9 / 5, 1) : round(value * 9 / 5 + 32, 1);
          unit = unit.replace('\u00b0C', '\u00b0F');
        }
        lines.push(pad(c.name, 30) + ' ' + pad((String(value) + ' ' + unit).trim(), 18)
          + ' from ' + c.sources.join(', '));
      });
    }

    if (report.findings && report.findings.length) {
      lines.push('', 'Plausibility checks (interpretation, not measurement)', rule);
      report.findings.forEach(function (f) {
        lines.push('[' + pad(f.level.toUpperCase(), 4) + '] ' + f.title);
        lines.push('        ' + f.detail);
        if (f.suspects.length) {
          lines.push('        Usual suspects: ' + f.suspects.join('; '));
        }
      });
    }

    if (report.safety_audit && report.safety_audit.length) {
      lines.push('', 'Safety decisions and gate events', rule);
      report.safety_audit.forEach(function (entry) {
        if (entry.event) {
          lines.push(pad('EVENT', 8) + ' ' + entry.event);
          return;
        }
        lines.push(pad(entry.allowed ? 'ALLOWED' : 'REFUSED', 8) + ' '
          + pad(entry.operation, 28) + ' ' + entry.reason);
      });
    }

    lines.push('', rule, report.trust.caveat,
      'Not affiliated with Piaggio or the GuzziDiag author.',
      '',
      'This report was produced by the hosted browser demo: the motorcycle, '
      + 'the ECU and every value above are simulated.');
    return lines.join('\n');
  }

  D.register('GET', '/api/report', function (q) {
    var unit = q.get('temp_unit') || 'C';
    var report = buildReport();
    return [200, {
      report: report,
      temp_unit: String(unit).toUpperCase().charAt(0) === 'F' ? 'F' : 'C',
      text: reportText(report, unit),
      simulated: true,
    }];
  });

  /* ======================================================================
   * 13. Guided tests
   * ======================================================================
   * The step lists, wording and caveats are exported from procedures.py by
   * scripts/build_demo_data.py, so they cannot drift from the real ones.
   * The verdicts are reimplemented here, and the observation windows are
   * time-compressed: a ten-second watch becomes about a second of wall
   * clock, with the simulated engine fast-forwarded by the difference so
   * the warm-up curve still means something.
   */

  var OBSERVE_COMPRESSION = 8;       // 8 s of observation per 1 s of waiting
  var RUN = null;

  function procedureList() {
    return (data().procedures || []);
  }

  function procedureByKey(key) {
    var found = null;
    procedureList().forEach(function (p) { if (p.key === key) found = p; });
    return found;
  }

  function missingFor(procedure, profile) {
    if (!profile) return ['no ECU selected'];
    var channels = {};
    var actuators = {};
    H.publicParameters(profile).forEach(function (p) { channels[p.key] = true; });
    (profile.actuators || []).forEach(function (a) { actuators[a.key] = true; });
    var missing = [];
    var wantedChannels = {};
    var wantedActuators = {};
    procedure.steps.forEach(function (step) {
      (step.channels || []).forEach(function (c) { wantedChannels[c] = true; });
      if (step.actuator) wantedActuators[step.actuator] = true;
    });
    Object.keys(wantedChannels).sort().forEach(function (c) {
      if (!channels[c]) missing.push('channel ' + c);
    });
    Object.keys(wantedActuators).sort().forEach(function (a) {
      if (!actuators[a]) missing.push('actuator ' + a);
    });
    return missing;
  }

  function stat(context, step, channel, which) {
    var entry = (context.observations[step] || {})[channel];
    if (!entry) return null;
    var value = entry[which || 'mean'];
    return typeof value === 'number' ? value : null;
  }

  function verdict(level, title, detail, suspects) {
    return { level: level, title: title, detail: detail, suspects: suspects || [] };
  }

  var VERDICTS = {
    idle_health: function (ctx) {
      var rpm = stat(ctx, 'watch', 'rpm');
      var target = stat(ctx, 'watch', 'idle_target');
      var spread = (stat(ctx, 'watch', 'rpm', 'max') || 0) - (stat(ctx, 'watch', 'rpm', 'min') || 0);
      var position = stat(ctx, 'watch', 'stepper_position');
      var base = stat(ctx, 'watch', 'stepper_base');
      if (rpm === null || target === null) {
        return verdict('info', 'Not enough data',
          'The idle channels did not answer for long enough to judge.');
      }
      var error = rpm - target;
      var drift = (position === null || base === null) ? null : position - base;
      var bits = [rpm.toFixed(0) + ' rpm against a target of ' + target.toFixed(0),
        'wandering ' + spread.toFixed(0) + ' rpm'];
      if (drift !== null) {
        bits.push('stepper ' + (drift > 0 ? '+' : '') + drift.toFixed(0) + ' steps from base');
      }
      if (Math.abs(error) < 120 && spread < 180) {
        return verdict('ok', 'Idle is in control', 'Measured ' + bits.join(', ')
          + '. The ECU is asking for a speed and getting it.');
      }
      if (error > 0 && drift !== null && drift < -5) {
        return verdict('warn', 'Idle high with the stepper closing down',
          'Measured ' + bits.join(', ') + '. The controller is shutting its air '
          + 'passage and still cannot bring the speed down, which is what '
          + 'unmetered air looks like.',
          ['Air leak after the throttle', 'Throttle stop adjustment',
            'Throttle plate not closing']);
      }
      if (Math.abs(error) >= 120) {
        return verdict('warn', 'Idle is off target', 'Measured ' + bits.join(', ') + '.',
          ['Idle stepper', 'Throttle body balance', 'Air leak']);
      }
      return verdict('warn', 'Idle is hunting', 'Measured ' + bits.join(', ')
        + '. The average is fine but it will not sit still.',
      ['Idle stepper', 'Lambda control at idle', 'Air leak']);
    },

    charging_system: function (ctx) {
      var rest = stat(ctx, 'rest', 'battery');
      var idle = stat(ctx, 'idle', 'battery');
      var revs = stat(ctx, 'revs', 'battery');
      if (rest === null || idle === null) {
        return verdict('info', 'Not enough data',
          'The battery channel did not answer in both states.');
      }
      var bits = [rest.toFixed(1) + ' V stopped', idle.toFixed(1) + ' V at idle'];
      if (revs !== null) bits.push(revs.toFixed(1) + ' V held up');
      var measured = bits.join(', ');
      var best = revs === null ? idle : Math.max(idle, revs);
      if (rest < 12.0) {
        return verdict('warn', 'The battery was flat before we started',
          'Measured ' + measured + '. Charge it and repeat: every other reading '
          + 'on this bike is suspect at this voltage.', ['Battery', 'Parasitic drain']);
      }
      if (best < 13.0) {
        return verdict('bad', 'Not charging', 'Measured ' + measured
          + '. The alternator is not contributing.',
        ['Alternator or stator', 'Regulator/rectifier', 'Charging wiring']);
      }
      if (best > 15.2) {
        return verdict('bad', 'Charging too hard', 'Measured ' + measured
          + '. This will boil the battery.',
        ['Regulator/rectifier', 'Earth connections']);
      }
      if (revs !== null && revs - idle < 0.1 && idle < 13.5) {
        return verdict('warn', 'Charging does not improve with revs',
          'Measured ' + measured + '. A healthy system climbs as the rpm comes up.',
          ['Stator windings', 'Regulator/rectifier']);
      }
      return verdict('ok', 'Charging system is doing its job', 'Measured ' + measured + '.');
    },

    fuel_pressure: function (ctx) {
      var primed = ctx.inputs.pressure_primed;
      var rested = ctx.inputs.pressure_rested;
      if (primed === undefined || rested === undefined) {
        return verdict('info', 'No readings entered',
          'Both gauge readings are needed to judge the decay.');
      }
      var drop = Number(primed) - Number(rested);
      var measured = primed + ' bar after priming, ' + rested + ' bar sixty seconds later';
      if (primed < 2.5) {
        return verdict('bad', 'Pressure never came up', measured
          + '. A 5AM-era Guzzi wants roughly 3 bar at the rail.',
        ['Fuel pump', 'Blocked filter', 'Pressure regulator', 'Weak battery']);
      }
      if (drop > 0.5) {
        return verdict('warn', 'Pressure bleeds away', measured + ' - a '
          + drop.toFixed(1) + ' bar drop. The rail should hold pressure for '
          + 'minutes, not seconds; this is why it is hard to start after standing.',
        ['Leaking injector', 'Pump non-return valve', 'Pressure regulator']);
      }
      return verdict('ok', 'Rail holds pressure', measured
        + '. Both the delivery and the seal are good.');
    },

    injector_click: function (ctx) {
      var silent = [];
      if (ctx.inputs.heard_front === false) silent.push('front');
      if (ctx.inputs.heard_rear === false) silent.push('rear');
      if (!silent.length) {
        return verdict('ok', 'Both injectors answered',
          'Each one clicked when it was commanded, so the ECU driver, the '
          + 'wiring and the solenoid are all alive.');
      }
      return verdict('bad', 'No click from the ' + silent.join(' and ') + ' injector',
        'The ECU commanded it and nothing moved. This is an electrical result '
        + 'only - a clicking injector can still be blocked.',
        ['Injector connector', 'Injector solenoid', 'ECU driver stage',
          'Wiring to the injector']);
    },

    cold_sensor_check: function (ctx) {
      var coolant = stat(ctx, 'soak', 'coolant_temp');
      var air = stat(ctx, 'soak', 'air_temp');
      if (coolant === null || air === null) {
        return verdict('info', 'Not enough data', 'Both temperature channels are needed.');
      }
      var split = coolant - air;
      var measured = 'head ' + coolant.toFixed(0) + ' \u00b0C, intake air '
        + air.toFixed(0) + ' \u00b0C';
      if (coolant <= -30 || coolant >= 130) {
        return verdict('bad', 'The head sensor is on a rail', measured
          + '. That is an open or shorted circuit, not a temperature.',
        ['Head temperature sensor', 'Sensor wiring or connector']);
      }
      if (Math.abs(split) > 8) {
        return verdict('warn', 'The two sensors disagree on a cold engine',
          measured + ', a ' + (split > 0 ? '+' : '') + split.toFixed(0)
          + ' \u00b0C split. On a bike that has stood overnight they should be '
          + 'within a few degrees.',
          ['Head temperature sensor', 'Air temperature sensor',
            'Catalog scaling for this family']);
      }
      return verdict('ok', 'Both sensors agree', measured
        + '. The ECU is starting from a believable picture.');
    },
  };

  function runState() {
    if (!RUN) return null;
    var step = RUN.index < RUN.procedure.steps.length
      ? RUN.procedure.steps[RUN.index] : null;
    return {
      procedure: RUN.procedure.key,
      name: RUN.procedure.name,
      caveat: RUN.procedure.caveat,
      status: RUN.status,
      step_index: RUN.index,
      step_count: RUN.procedure.steps.length,
      step: step,
      results: RUN.results,
      verdict: RUN.verdict,
      simulated: true,
      note: 'Observations are ordinary live reads; any output is commanded '
        + 'through the safety gate with the workstation\'s own deadline. The '
        + 'verdict is an interpretation, not a measurement. In this demo the '
        + 'observation windows are time-compressed against the simulated '
        + 'engine: a ' + OBSERVE_COMPRESSION + '-second watch takes about a '
        + 'second, with the engine model fast-forwarded to match.',
    };
  }

  D.register('GET', '/api/procedures', function () {
    var profile = WS.sessionProfile || WS.selection.profile;
    return [200, {
      procedures: procedureList().map(function (procedure) {
        var missing = missingFor(procedure, profile);
        return Object.assign({}, procedure, {
          available: !missing.length, missing: missing,
        });
      }),
      run: runState(),
      simulated: true,
      note: 'A procedure only puts together things the catalog already '
        + 'describes. Observations are live reads, outputs go through the '
        + 'safety gate, and the verdict is an interpretation. In this hosted '
        + 'demo the observation windows are time-compressed against the '
        + 'simulated engine by about ' + OBSERVE_COMPRESSION + 'x.',
    }];
  });

  D.register('POST', '/api/procedures/start', function (body) {
    var ecu = H.requireService();
    var procedure = procedureByKey(body.key || '');
    if (!procedure) throw bad('unknown procedure ' + JSON.stringify(body.key || ''));
    var missing = missingFor(procedure, WS.sessionProfile);
    if (missing.length) throw bad('this ECU family is missing: ' + missing.join(', '));
    RUN = {
      procedure: procedure, index: 0, status: 'running',
      results: [], verdict: null,
      context: { observations: {}, inputs: {} },
    };
    if (LIVE_SESSION) {
      record(LIVE_SESSION, 'action', {
        name: 'procedure_start',
        detail: { key: procedure.key, name: procedure.name },
      });
    }
    return [200, { run: runState() }];
  });

  function observeStep(step) {
    /* Sample the simulated engine repeatedly, fast-forwarding it between
     * sweeps so ``seconds`` of engine behaviour is covered in roughly
     * ``seconds / OBSERVE_COMPRESSION`` of your time. */
    var seconds = Math.max(0.5, Number(step.seconds || 5));
    var sweeps = Math.max(4, Math.round(seconds / 0.4));
    var collected = {};
    var errors = {};
    (step.channels || []).forEach(function (key) { collected[key] = []; });
    for (var i = 0; i < sweeps; i++) {
      (step.channels || []).forEach(function (key) {
        var sample;
        try {
          sample = H.readParameter(key);
        } catch (exc) {
          errors[key] = String(exc.message || exc);
          return;
        }
        if (sample.error) errors[key] = sample.error;
        else if (typeof sample.value === 'number') collected[key].push(sample.value);
      });
      if (WS.ecu && WS.ecu.engine && WS.ecu.engine.advance) {
        WS.ecu.engine.advance(seconds / sweeps);
      }
    }
    var stats = {};
    Object.keys(collected).forEach(function (key) {
      var values = collected[key];
      if (!values.length) return;
      stats[key] = {
        mean: round(values.reduce(function (a, b) { return a + b; }, 0) / values.length, 2),
        min: round(Math.min.apply(null, values), 2),
        max: round(Math.max.apply(null, values), 2),
        count: values.length,
      };
    });
    return { stats: stats, errors: errors, sweeps: sweeps, seconds: seconds };
  }

  D.register('POST', '/api/procedures/advance', function (body) {
    if (!RUN) throw bad('no procedure is running');
    if (RUN.status !== 'running') throw bad('this run is ' + RUN.status);
    var step = RUN.procedure.steps[RUN.index];
    if (!step) {
      RUN.status = 'done';
      return [200, { run: runState() }];
    }
    var value = body.value;
    var result;

    if (step.kind === 'instruct') {
      result = {
        step: step.key, kind: 'instruct', title: step.title,
        detail: 'Confirmed by the operator.',
      };
    } else if (step.kind === 'input') {
      var parsed, shown;
      if (step.input_kind === 'yesno') {
        if (value === null || value === undefined) {
          throw bad(step.key + ': answer the question first');
        }
        parsed = !!value;
        shown = parsed ? 'yes' : 'no';
      } else {
        parsed = parseFloat(value);
        if (isNaN(parsed)) throw bad(step.key + ': a number is needed');
        shown = (String(parsed) + ' ' + (step.input_unit || '')).trim();
      }
      RUN.context.inputs[step.key] = parsed;
      result = {
        step: step.key, kind: 'input', title: step.title,
        detail: 'Operator entered ' + shown + '.', value: parsed,
      };
    } else if (step.kind === 'observe') {
      var observed = observeStep(step);
      RUN.context.observations[step.key] = observed.stats;
      var detail = Object.keys(observed.stats).map(function (key) {
        var entry = observed.stats[key];
        return key + ' ' + entry.mean + ' (' + entry.min + '\u2026' + entry.max + ')';
      }).join(', ') || 'nothing answered';
      result = {
        step: step.key, kind: 'observe', title: step.title,
        detail: observed.sweeps + ' sweeps over ' + observed.seconds
          + ' s of simulated engine time (compressed): ' + detail,
        stats: observed.stats, errors: observed.errors, simulated: true,
      };
    } else if (step.kind === 'actuate') {
      var decision = WS.gate.evaluate('actuator:' + step.actuator, 'reversible', {
        profile: WS.sessionProfile, capability: 'actuators',
      });
      if (!decision.allowed) {
        result = {
          step: step.key, kind: 'actuate', title: step.title, blocked: true,
          detail: 'Refused by the safety gate: ' + decision.reason,
          decision: decision,
        };
      } else {
        WS.gate.consume(decision.token, 'actuator:' + step.actuator);
        var duration = Number(step.pulse_s || 2);
        if (WS.ecu) WS.ecu.activeOutputs[step.actuator] = mono() + duration;
        result = {
          step: step.key, kind: 'actuate', title: step.title,
          detail: step.actuator + ' energised for ' + duration.toFixed(1)
            + ' s, then released by the workstation\'s deadline.',
          decision: decision,
        };
      }
    } else if (step.kind === 'verdict') {
      var evaluate = VERDICTS[RUN.procedure.key];
      RUN.verdict = evaluate
        ? evaluate(RUN.context)
        : verdict('info', 'No verdict available',
          'This procedure has no verdict rule in the browser demo.');
      result = {
        step: step.key, kind: 'verdict', title: step.title,
        detail: RUN.verdict.detail, verdict: RUN.verdict,
      };
    } else {
      throw bad('unknown step kind ' + step.kind);
    }

    RUN.results.push(result);
    if (result.blocked) {
      RUN.status = 'blocked';
      return [200, { run: runState() }];
    }
    RUN.index += 1;
    if (RUN.index >= RUN.procedure.steps.length) RUN.status = 'done';
    if (LIVE_SESSION && (RUN.status === 'done' || RUN.status === 'blocked')) {
      record(LIVE_SESSION, 'action', {
        name: 'procedure_end',
        detail: { key: RUN.procedure.key, status: RUN.status, verdict: RUN.verdict },
      });
    }
    return [200, { run: runState() }];
  });

  D.register('POST', '/api/procedures/abort', function () {
    if (!RUN) throw bad('no procedure is running');
    RUN.status = 'aborted';
    if (WS.ecu) WS.ecu.activeOutputs = {};
    RUN.results.push({
      step: 'abort', kind: 'abort',
      detail: 'Stopped by the operator; outputs released.',
    });
    return [200, { run: runState() }];
  });

  /* ======================================================================
   * 14. Tools
   * ======================================================================
   * These never needed an ECU in the first place: they are arithmetic and
   * file conversion. The local workstation reads and writes files; here
   * everything goes in and out through the text boxes and the browser's
   * own download, which is the only difference.
   */

  /* -- gearing (port of guzzionboard/tools.py) -------------------------- */

  function tyreCircumference(marking) {
    var parts = String(marking || '').split('/');
    if (parts.length < 2) throw bad('cannot parse tyre marking ' + JSON.stringify(marking));
    var rest = parts[1].replace(/ZR/i, '-').replace(/R/i, '-').split('-');
    var width = parseFloat(parts[0]);
    var aspect = parseFloat(rest[0]);
    var rim = parseFloat(rest[1]);
    if (!isFinite(width) || !isFinite(aspect) || !isFinite(rim)) {
      throw bad('cannot parse tyre marking ' + JSON.stringify(marking));
    }
    var sidewall = width * aspect / 100;
    return Math.PI * (rim * 25.4 + 2 * sidewall) / 1000;
  }

  D.register('GET', '/api/tools/gearing', function (q) {
    var presets = data().gearing_presets || {};
    var defaults = data().gearing_defaults || {};
    var number = function (name, fallback) {
      var value = parseFloat(q.get(name));
      return isFinite(value) ? value : fallback;
    };
    var floats = function (name) {
      return String(q.get(name) || '').replace(/;/g, ',').split(',')
        .map(function (part) { return parseFloat(part.trim()); })
        .filter(function (value) { return isFinite(value) && value > 0; });
    };
    var presetName = q.get('preset') || '';
    var preset = presets[presetName] || null;
    var gears = floats('gears');
    if (!gears.length && preset) gears = preset.gears.slice();
    if (!gears.length) gears = (defaults.gears || [2.308, 1.619, 1.25, 1.038, 0.87, 0.75]).slice();
    var rpmValues = floats('rpm').map(function (v) { return Math.round(v); });
    if (!rpmValues.length) {
      rpmValues = [];
      for (var rpm = 1000; rpm <= 8000; rpm += 500) rpmValues.push(rpm);
    }
    var finalDrive = number('final_drive', defaults.final_drive || 4.125);
    var primary = number('primary', 1.0);
    var tyre = q.get('tyre') || defaults.tyre || '180/55-17';
    var circumference = tyreCircumference(tyre);

    var gearTable = {};
    gears.forEach(function (ratio, index) {
      gearTable['gear' + (index + 1)] = rpmValues.map(function (rpm) {
        var wheelRpm = rpm / (primary * ratio * finalDrive);
        return round(wheelRpm * circumference * 60 / 1000, 1);
      });
    });

    var result = {
      tyre: tyre,
      circumference_m: round(circumference, 3),
      final_drive: finalDrive,
      rpm: rpmValues,
      gears: gearTable,
      presets: presets,
      gear_ratios_used: gears,
    };
    if (presetName && preset) {
      result.preset = presetName;
      result.max_rpm = preset.max_rpm;
    }
    return [200, result];
  });

  /* -- Zeitronix ZT-2 CSV -> LogWorks DIF (port of logconvert.py) ------- */

  var Z2_LABELS = [
    ['afr', 'AFR'], ['lambda', 'Lambda'], ['rpm', 'RPM'], ['tps', 'TPS (%)'],
    ['throttle', 'TPS (%)'], ['map', 'MAP'], ['boost', 'Boost'],
    ['egt', 'EGT'], ['user', 'USER1'],
  ];

  function z2Canonical(label) {
    if (label.indexOf('(') >= 0) return label.trim();
    var low = label.trim().toLowerCase();
    var canon = label.trim();
    Z2_LABELS.some(function (pair) {
      if (low.indexOf(pair[0]) >= 0) { canon = pair[1]; return true; }
      return false;
    });
    return canon;
  }

  D.register('POST', '/api/tools/z2dif', function (body) {
    if (body.path && !body.text) {
      throw bad('the hosted demo has no disk: paste the ZT-2 CSV into the box '
        + 'instead of giving a path (the local workstation reads the file).');
    }
    var text = String(body.text || '');
    if (!text.trim()) throw bad("a ZT-2 CSV 'path' or pasted 'text' is required");
    var sampleRate = parseFloat(body.sample_rate);
    if (!isFinite(sampleRate)) sampleRate = 65;
    var factor = parseFloat(body.timeline_factor);
    if (!isFinite(factor)) factor = 4;
    if (sampleRate <= 0) throw bad('sample_rate must be positive');
    if (factor <= 0) throw bad('timeline_factor must be positive');

    var lines = text.replace(/\r\n/g, '\n').split('\n')
      .filter(function (line) { return line.trim(); });
    if (lines.length < 2) throw bad('need a header row and at least one data row');
    var delimiter = (lines[0].split(';').length - 1) > (lines[0].split(',').length - 1) ? ';' : ',';
    var header = lines[0].split(delimiter).map(function (h) { return h.trim(); })
      .filter(Boolean);
    if (!header.length) throw bad('the header row has no channel names');
    var named = header.map(function (h) { return h.toLowerCase(); });
    if (!named.some(function (h) { return h.indexOf('afr') >= 0 || h.indexOf('lambda') >= 0; })) {
      throw bad('no AFR/Lambda column in the header - this does not look like '
        + 'a ZT-2 (ZDL) export');
    }
    var channels = header.map(z2Canonical);
    var rows = [];
    for (var i = 1; i < lines.length; i++) {
      var parts = lines[i].split(delimiter).filter(function (p) { return p.trim(); });
      if (parts.length !== header.length) {
        throw bad('row ' + (rows.length + 2) + ' has ' + parts.length
          + ' fields, expected ' + header.length);
      }
      rows.push(parts.map(function (token) {
        var value = parseFloat(token.trim().replace(',', '.'));
        if (!isFinite(value)) throw bad('not a number: ' + JSON.stringify(token) + ' in a data row');
        return value;
      }));
    }
    var step = factor / sampleRate;
    var out = [['Time (s)'].concat(channels).join('\t')];
    rows.forEach(function (row, index) {
      out.push([(index * step).toFixed(3)].concat(row.map(function (v) {
        return String(+v.toPrecision(6));
      })).join('\t'));
    });
    return [200, {
      dif: out.join('\r\n') + '\r\n',
      channels: channels,
      rows: rows.length,
      duration_s: rows.length ? round((rows.length - 1) * step, 3) : 0,
      sample_rate: sampleRate,
      timeline_factor: factor,
      time_column_in_source: named.some(function (h) { return h.indexOf('time') >= 0; }),
      note: 'Time axis rebuilt from the row index: row N sits at N * '
        + (+factor.toPrecision(6)) + '/' + (+sampleRate.toPrecision(6)) + ' s '
        + "(the reference converter's documented factor-4 timeline error, "
        + 'corrected; timeline_factor=1.0 reproduces its output). DIF is '
        + "LogWorks' spreadsheet-table interchange: tab separated, header "
        + 'row, first column time.',
    }];
  });

  /* -- bench RPM trigger signal (port of rpmsignal.py) ------------------ */

  function renderTriggerWav(wheel, events, options) {
    var sampleRate = options.sample_rate || 44100;
    var duty = options.duty === undefined ? 0.5 : options.duty;
    var amplitude = options.amplitude === undefined ? 0.7 : options.amplitude;
    if (!(duty >= 0.05 && duty <= 0.95)) throw bad('duty must be between 0.05 and 0.95');
    if (!(amplitude > 0 && amplitude <= 1)) throw bad('amplitude must be in (0, 1]');
    if (sampleRate < 8000) throw bad('sample_rate must be at least 8000 Hz');

    var slots = wheel.teeth + wheel.missing;
    var hi = Math.round(amplitude * 32767);
    var total = 0;
    events.forEach(function (event) {
      total += Math.floor(sampleRate * event[0] / 1000);
    });
    var pcm = new Int16Array(total);
    var cursor = 0;
    var pos = 0;
    events.forEach(function (event) {
      var n = Math.floor(sampleRate * event[0] / 1000);
      var r1 = event[1], r2 = event.length > 2 ? event[2] : event[1];
      for (var i = 0; i < n; i++) {
        var rpm = r1 + (r2 - r1) * (n ? i / n : 0);
        var revRate = (wheel.wheel === 'crankshaft' ? rpm : rpm / 2) / 60;
        pos += revRate * slots / sampleRate;
        var slot = Math.floor(pos) % slots;
        var within = pos - Math.floor(pos);
        pcm[cursor++] = (slot < wheel.teeth && within < duty) ? hi : -hi;
      }
    });

    var bytes = new Uint8Array(44 + pcm.length * 2);
    var view = new DataView(bytes.buffer);
    var ascii = function (offset, text) {
      for (var i = 0; i < text.length; i++) bytes[offset + i] = text.charCodeAt(i);
    };
    ascii(0, 'RIFF');
    view.setUint32(4, 36 + pcm.length * 2, true);
    ascii(8, 'WAVEfmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    ascii(36, 'data');
    view.setUint32(40, pcm.length * 2, true);
    for (var s = 0; s < pcm.length; s++) view.setInt16(44 + s * 2, pcm[s], true);
    return { bytes: bytes, duration_s: pcm.length / sampleRate, sample_rate: sampleRate };
  }

  function downloadBytes(name, bytes, mime) {
    if (typeof Blob === 'undefined' || typeof document === 'undefined') return false;
    try {
      var url = URL.createObjectURL(new Blob([bytes], { type: mime }));
      var a = document.createElement('a');
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 5000);
      return true;
    } catch (exc) {
      return false;
    }
  }

  D.register('POST', '/api/tools/rpmsignal', function (body) {
    var wheels = data().rpm_wheels || {};
    var wheel;
    if (body.pattern) {
      wheel = wheels[String(body.pattern).toLowerCase()];
      if (!wheel) {
        throw bad('unknown pattern ' + JSON.stringify(body.pattern),
          { presets: Object.keys(wheels).sort() });
      }
    } else {
      var teeth = parseInt(body.teeth, 10);
      if (!teeth) {
        throw bad("missing field 'teeth'; need a preset 'pattern' or 'teeth' "
          + "(+ 'missing', 'wheel')");
      }
      wheel = {
        teeth: teeth,
        missing: parseInt(body.missing, 10) || 0,
        wheel: String(body.wheel || 'crankshaft'),
      };
      if (['crankshaft', 'camshaft'].indexOf(wheel.wheel) < 0) {
        throw bad("'wheel' must be crankshaft or camshaft");
      }
    }

    var events = body.events;
    if (!events) {
      var rpm = parseFloat(body.rpm) || 0;
      var seconds = parseFloat(body.seconds) || 0;
      if (rpm <= 0 || seconds <= 0) {
        throw bad("pass 'rpm' + 'seconds', or 'events': [[duration_ms, rpm (, rpm_end)], ...]");
      }
      events = [[Math.round(seconds * 10) * 100, rpm]];
    }
    events = events.map(function (row) {
      if (!row || (row.length !== 2 && row.length !== 3)) {
        throw bad('batch row ' + JSON.stringify(row) + ': expected duration|rpm1[|rpm2]');
      }
      var duration = Math.round(row[0]);
      if (duration <= 0 || duration % 100) {
        throw bad('duration ' + duration + ' ms is not a multiple of 100 ms');
      }
      if (row[1] <= 0 || (row.length === 3 && row[2] <= 0)) {
        throw bad('rpm values must be positive');
      }
      return row.length === 3 ? [duration, row[1], row[2]] : [duration, row[1]];
    });
    if (!events.length) throw bad('no events to render');

    var totalMs = events.reduce(function (sum, e) { return sum + e[0]; }, 0);
    if (totalMs > 120000) {
      throw bad('the browser renders up to 120 s of signal at a time; the '
        + 'local workstation has no such limit');
    }

    var rendered = renderTriggerWav(wheel, events, {
      sample_rate: parseInt(body.sample_rate, 10) || 44100,
      duty: body.duty === undefined ? 0.5 : parseFloat(body.duty),
      amplitude: body.amplitude === undefined ? 0.7 : parseFloat(body.amplitude),
    });
    var tag = body.name || (wheel.teeth + '-' + wheel.missing + 'missing-' + wheel.wheel);
    var filename = 'rpmsim-' + tag + '-' + stamp() + '.wav';
    var downloaded = downloadBytes(filename, rendered.bytes, 'audio/wav');

    return [200, {
      path: filename + (downloaded
        ? ' (downloaded by your browser)'
        : ' (not written: this browser blocked the download)'),
      downloaded: downloaded,
      pattern: tag,
      wheel: wheel.wheel,
      teeth: wheel.teeth,
      missing: wheel.missing,
      slots: wheel.teeth + wheel.missing,
      duration_s: round(rendered.duration_s, 3),
      sample_rate: rendered.sample_rate,
      duty: body.duty === undefined ? 0.5 : parseFloat(body.duty),
      amplitude: body.amplitude === undefined ? 0.7 : parseFloat(body.amplitude),
      events: events,
      bytes: rendered.bytes.length,
      simulated: false,
      safety: 'Bench aid: AC-couple and attenuate into the sensor input, never '
        + 'drive a harness directly. An ECU that believes the engine turns can '
        + 'energise coils and injectors — disconnect the outputs you do not '
        + 'want live.',
      note: 'Gap length is ' + (wheel.missing + 1) + 'x the tooth period ('
        + wheel.missing + ' missing teeth + the low halves of the neighbouring '
        + 'duty cycles); wheel geometry from the reference tool\'s config '
        + 'files. This WAV is real: the browser rendered the same samples the '
        + 'workstation would have written, and handed them to your downloads '
        + 'folder instead of ~/.guzzionboard/signals.',
    }];
  });

  /* -- CAN capture analysis (port of guzzionboard/canlog.py) ------------ */

  var SID_NAMES = {
    0x10: 'start diagnostic session', 0x11: 'ECU reset',
    0x14: 'clear diagnostic information', 0x18: 'read DTC by status',
    0x19: 'read DTC information', 0x1A: 'read ECU identification',
    0x21: 'read data by local identifier', 0x22: 'read data by identifier',
    0x23: 'read memory by address', 0x27: 'security access',
    0x28: 'communication control', 0x2C: 'dynamically define identifier',
    0x2E: 'write data by identifier', 0x2F: 'input/output control by identifier',
    0x30: 'input/output control (KWP)', 0x31: 'routine control',
    0x34: 'request download', 0x35: 'request upload', 0x36: 'transfer data',
    0x37: 'request transfer exit', 0x3B: 'write data by local identifier',
    0x3D: 'write memory by address', 0x3E: 'tester present',
    0x83: 'access timing parameter', 0x84: 'secured data transmission',
    0x85: 'control DTC setting', 0x86: 'response on event', 0x87: 'link control',
  };
  // Recognition labels for observed logs, never motorcycle defaults.
  var STANDARD_PAIRS = {
    '7E0:7E8': 'the conventional 11-bit ISO 15765-4 reference pair',
    '18DA10F1:18DAF110': 'the conventional 29-bit ISO 15765-4 reference pair',
  };
  var FUNCTIONAL_ID = 0x7DF;

  function hexId(token) {
    var clean = String(token || '').trim().toLowerCase().replace(/^0x/, '');
    if (!clean || !/^[0-9a-f]+$/.test(clean)) return null;
    return parseInt(clean, 16);
  }

  function frameMeta(frame) {
    var nibble = frame.data.length ? frame.data[0] >> 4 : -1;
    var pci = { 0: 'sf', 1: 'ff', 2: 'cf', 3: 'fc' }[nibble] || (frame.data.length ? 'other' : 'empty');
    var sid = null;
    if (frame.data.length) {
      if (pci === 'sf') sid = frame.data.length > 1 ? frame.data[1] : null;
      else if (pci === 'ff') sid = frame.data.length > 2 ? frame.data[2] : null;
    }
    var kind = '';
    if (sid !== null) {
      if (sid === 0x7F) kind = 'negative';
      else if (SID_NAMES[sid]) kind = 'request';
      else if (SID_NAMES[sid - 0x40]) kind = 'response';
    }
    return { pci: pci, sid: sid, kind: kind };
  }

  function parseCanText(text) {
    if (!text || !text.trim()) throw bad('the capture is empty');
    var lines = text.split(/\r?\n/);
    var frames = [];
    var skipped = 0;
    var format = 'candump';
    lines.forEach(function (line) {
      var trimmed = line.trim();
      if (!trimmed || /^[#/$;]/.test(trimmed) || /^I /.test(trimmed)) return;
      var tokens = trimmed.split(/\s+/);
      var timestamp = 0;
      if (tokens[0].charAt(0) === '(' && tokens[0].indexOf('#') < 0) {
        var inner = tokens.shift().replace(/[()]/g, '');
        timestamp = inner.indexOf(':') >= 0
          ? (function () {
            var bits = inner.split(':');
            return parseInt(bits[0], 10) * 3600 + parseInt(bits[1], 10) * 60
              + parseFloat(bits[2]);
          }())
          : parseFloat(inner);
        if (!isFinite(timestamp)) { skipped++; return; }
      }
      // CRTD: <ts> R11 <id> <bytes...>
      if (tokens.length >= 3 && /^(R|T)(11|29)?$/i.test(tokens[0] === '' ? '' : tokens[0])) {
        var kindToken = tokens[0].toUpperCase();
        var ident = hexId(tokens[1]);
        if (ident !== null) {
          format = 'crtd';
          frames.push({
            timestamp: timestamp, id: ident, extended: kindToken.indexOf('29') >= 0,
            data: tokens.slice(2).map(hexId).filter(function (b) { return b !== null; })
              .slice(0, 8),
          });
          return;
        }
      }
      if (tokens.length && tokens[0].indexOf('#') < 0 && tokens[0].charAt(0) !== '['
        && (hexId(tokens[0]) !== null || /^can\d*$/.test(tokens[0]))
        && tokens.length > 1) {
        // interface name, or an id followed by a verbose body
        if (/^can\d*$/.test(tokens[0]) || tokens[1].indexOf('#') >= 0) tokens.shift();
      }
      if (!tokens.length) { skipped++; return; }
      var head = tokens[0];
      if (head.indexOf('#') >= 0) {
        var bits = head.split('#');
        var id2 = hexId(bits[0]);
        if (id2 === null || bits[1].charAt(0) === '#') { skipped++; return; }
        var payload = bits[1] || '';
        var bytes = [];
        if (!/^R/i.test(payload)) {
          for (var i = 0; i + 1 < payload.length; i += 2) {
            bytes.push(parseInt(payload.substr(i, 2), 16));
          }
        }
        frames.push({ timestamp: timestamp, id: id2, extended: id2 > 0x7FF, data: bytes });
        return;
      }
      var id3 = hexId(head);
      if (id3 === null || tokens.length < 2) { skipped++; return; }
      var rest = tokens.slice(1).filter(function (t) { return t.charAt(0) !== '['; });
      var data = rest.map(hexId).filter(function (b) { return b !== null; });
      if (!data.length) { skipped++; return; }
      frames.push({ timestamp: timestamp, id: id3, extended: id3 > 0x7FF, data: data });
    });
    if (!frames.length) {
      throw bad('no frames recognised - expected candump or CRTD lines. The '
        + 'hosted demo reads pasted text only; the local workstation also '
        + 'reads SavvyCAN CSV files from disk.');
    }
    var warnings = [];
    if (skipped) warnings.push(skipped + ' line(s) did not look like frames and were skipped');
    return { frames: frames, format: format, warnings: warnings };
  }

  function analyseCanFrames(frames) {
    var stamps = frames.map(function (f) { return f.timestamp; });
    var span = Math.max.apply(null, stamps) - Math.min.apply(null, stamps);
    var byId = {};
    frames.forEach(function (frame) {
      var traffic = byId[frame.id];
      if (!traffic) {
        traffic = byId[frame.id] = {
          frames: 0, requests: 0, responses: 0, negatives: 0,
          first_frames: [], flow_controls: [], tester_presents: [], padding: {},
        };
      }
      traffic.frames++;
      var meta = frameMeta(frame);
      if (meta.kind === 'request') traffic.requests++;
      else if (meta.kind === 'response') traffic.responses++;
      else if (meta.kind === 'negative') traffic.negatives++;
      if (meta.pci === 'ff') traffic.first_frames.push(frame.timestamp);
      else if (meta.pci === 'fc') traffic.flow_controls.push(frame.timestamp);
      if (meta.pci === 'sf' && meta.sid === 0x3E) traffic.tester_presents.push(frame.timestamp);
      if (frame.data.length === 8) {
        var filler = frame.data[7];
        traffic.padding[filler] = (traffic.padding[filler] || 0) + 1;
      }
    });

    var ffEvents = frames.filter(function (f) { return frameMeta(f).pci === 'ff'; })
      .map(function (f) { return [f.timestamp, f.id]; })
      .sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
    var edges = {};
    Object.keys(byId).forEach(function (identKey) {
      byId[identKey].flow_controls.forEach(function (fcTime) {
        for (var i = ffEvents.length - 1; i >= 0; i--) {
          if (ffEvents[i][0] > fcTime) continue;
          if (fcTime - ffEvents[i][0] > 0.1) break;
          if (ffEvents[i][1] !== Number(identKey)) {
            var key = ffEvents[i][1] + ':' + identKey;
            edges[key] = (edges[key] || 0) + 1;
            break;
          }
        }
      });
    });
    var answeredFf = {};
    Object.keys(edges).forEach(function (key) {
      var sender = key.split(':')[0];
      answeredFf[sender] = (answeredFf[sender] || 0) + edges[key];
    });

    var pairs = [];
    Object.keys(byId).forEach(function (testerKey) {
      var tester = byId[testerKey];
      var testerId = Number(testerKey);
      var isCandidate = tester.requests || tester.tester_presents.length
        || Object.keys(edges).some(function (k) { return Number(k.split(':')[0]) === testerId; });
      if (!isCandidate) return;
      Object.keys(byId).forEach(function (ecuKey) {
        var ecuId = Number(ecuKey);
        if (ecuId === testerId) return;
        var ecu = byId[ecuKey];
        var ffToEcu = edges[testerId + ':' + ecuId] || 0;
        var fcToTester = edges[ecuId + ':' + testerId] || 0;
        if (!(tester.requests || ffToEcu || tester.tester_presents.length)) return;
        if (!(ecu.responses || ecu.negatives || fcToTester || answeredFf[ecuKey])) return;
        var evidence = {
          request_frames: tester.requests,
          response_frames: ecu.responses + ecu.negatives,
          multi_frame_to_ecu: ffToEcu,
          multi_frame_from_ecu: fcToTester,
          ecu_first_frames: ecu.first_frames.length,
          ecu_answered_first_frames: answeredFf[ecuKey] || 0,
        };
        var score = 3 * Math.min(evidence.request_frames, 5)
          + 3 * Math.min(evidence.response_frames, 5)
          + 5 * Math.min(ffToEcu, 2) + 5 * Math.min(fcToTester, 2)
          + 4 * (tester.tester_presents.length >= 3 ? 1 : 0)
          + 2 * Math.min(evidence.ecu_answered_first_frames, 3);
        if (score < 4) return;

        var interval = null;
        if (tester.tester_presents.length >= 3 && span) {
          var times = tester.tester_presents.slice().sort(function (a, b) { return a - b; });
          var deltas = [];
          for (var i = 1; i < times.length; i++) {
            if (times[i] > times[i - 1]) deltas.push(times[i] - times[i - 1]);
          }
          if (deltas.length) {
            deltas.sort(function (a, b) { return a - b; });
            interval = round(deltas[Math.floor(deltas.length / 2)], 3);
          }
        }
        var padding = null;
        var best = null;
        Object.keys(tester.padding).forEach(function (byte) {
          if (!best || tester.padding[byte] > best[1]) best = [Number(byte), tester.padding[byte]];
        });
        if (best && best[1] >= 3 && best[1] >= 0.5 * tester.frames) {
          padding = '0x' + H.hex2(best[0]).toUpperCase();
        }
        var sidsFor = function (ident, kind, shift) {
          var seen = {};
          frames.forEach(function (f) {
            if (f.id !== ident) return;
            var meta = frameMeta(f);
            if (meta.kind !== kind || meta.sid === null) return;
            var sid = meta.sid - shift;
            if (SID_NAMES[sid]) seen['0x' + H.hex2(sid).toUpperCase() + ' ' + SID_NAMES[sid]] = true;
          });
          return Object.keys(seen).sort().slice(0, 8);
        };
        var strong = (ffToEcu || fcToTester)
          && (evidence.request_frames || evidence.response_frames);
        pairs.push({
          request_id: '0x' + testerId.toString(16).toUpperCase(),
          response_id: '0x' + ecuId.toString(16).toUpperCase(),
          extended: frames.some(function (f) {
            return (f.id === testerId || f.id === ecuId) && f.extended;
          }),
          score: score,
          confidence: strong ? 'strong'
            : (evidence.request_frames && evidence.response_frames ? 'likely' : 'weak'),
          evidence: evidence,
          request_sids: sidsFor(testerId, 'request', 0),
          response_sids: sidsFor(ecuId, 'response', 0x40),
          tester_present_interval_s: interval,
          padding_byte: padding,
          frames_on_request_id: tester.frames,
          frames_on_response_id: ecu.frames,
          _key: testerId.toString(16).toUpperCase() + ':' + ecuId.toString(16).toUpperCase(),
          _unordered: [testerId, ecuId].sort().join(':'),
        });
      });
    });

    pairs.sort(function (a, b) { return b.score - a.score; });
    var seen = {};
    pairs = pairs.filter(function (pair) {
      if (seen[pair._unordered]) return false;
      seen[pair._unordered] = true;
      return true;
    }).slice(0, 5);
    pairs.forEach(function (pair) {
      pair.matches = STANDARD_PAIRS[pair._key] || null;
      delete pair._key;
      delete pair._unordered;
    });

    var notes = [];
    if (byId[FUNCTIONAL_ID] && byId[FUNCTIONAL_ID].requests) {
      notes.push('Requests were also seen on 0x7DF - the functional '
        + '(broadcast) address. Ignore it: the physical pair above is what '
        + 'the workstation needs.');
    }
    if (span > 120) {
      notes.push('The capture spans ' + (span / 60).toFixed(0) + ' minutes; a '
        + 'minute or two of a live diagnostic session is enough.');
    }
    if (!pairs.length) {
      notes.push('No ISO-TP diagnostic traffic was recognised. Either the log '
        + 'has no diagnostic session in it (start one with GuzziCanDiag while '
        + 'capturing), or the pair does not speak ISO-TP the standard way - '
        + 'in which case this project wants to hear about it.');
    }
    return {
      frames: frames.length,
      span_seconds: span ? round(span, 3) : null,
      bus_ids: Object.keys(byId).map(Number).sort(function (a, b) { return a - b; })
        .map(function (i) { return '0x' + i.toString(16).toUpperCase(); }),
      pairs: pairs,
      notes: notes,
      diagnostic_traffic_found: !!pairs.length,
    };
  }

  D.register('POST', '/api/tools/canlog', function (body) {
    if (body.path && !body.text) {
      throw bad('the hosted demo has no disk: paste the capture lines instead '
        + 'of giving a path (the local workstation reads candump, SavvyCAN '
        + 'CSV and CRTD files).');
    }
    var parsed = parseCanText(String(body.text || ''));
    var result = analyseCanFrames(parsed.frames);
    result.format = parsed.format;
    result.notes = parsed.warnings.concat(result.notes);
    result.analysed_in = 'browser';
    return [200, result];
  });

  /* -- K-Line capture analysis ----------------------------------------- */
  /* A reduced port: the hosted version characterises which local
   * identifiers answered and how their bytes behaved, which is the half of
   * klinelog.py that needs no files. Solving scalings against the other
   * tool's CSV needs that second file, so it stays with the workstation. */

  D.register('POST', '/api/tools/klinelog', function (body) {
    if (body.path && !body.text) {
      throw bad('the hosted demo has no disk: paste the capture instead of '
        + 'giving a path.');
    }
    var text = String(body.text || '');
    if (!text.trim()) throw bad("a capture 'path' or pasted 'text' is required");

    /* One frame a line: an optional timestamp and tx/rx marker, then the
     * raw KWP2000 bytes. The header walk is the one in klinelog.py. */
    var frames = [];
    text.split(/\r?\n/).forEach(function (line) {
      var raw = (line.match(/\b[0-9a-fA-F]{2}\b/g) || [])
        .map(function (token) { return parseInt(token, 16); });
      if (raw.length < 3) return;
      var fmt = raw[0];
      var length = fmt & 0x3F;
      var header = (fmt & 0x80) ? 3 : 1;
      var target = (fmt & 0x80) ? raw[1] : null;
      var source = (fmt & 0x80) ? raw[2] : null;
      if (length === 0) {
        length = raw[header];
        header += 1;
      }
      var payload = raw.slice(header, header + length);
      if (!payload.length) return;
      frames.push({ raw: raw, payload: payload, source: source, target: target });
    });
    if (!frames.length) {
      throw bad('no hex frames recognised. Paste lines of hex bytes, one '
        + 'frame per line (anything else on the line is ignored).');
    }

    var ids = {};
    var services = {};
    var identification = [];
    var refused = 0;
    var pendingRequest = null;
    frames.forEach(function (frame) {
      var body2 = frame.payload;
      var sid = body2[0];
      if (sid === 0x21 && body2.length > 1) {
        pendingRequest = body2[1];
        services['0x21'] = 'read data by local identifier';
        return;
      }
      if (sid === 0x1A && body2.length > 1) {
        pendingRequest = null;
        services['0x1A'] = 'read ECU identification';
        return;
      }
      if (sid === 0x7F) {
        refused++;
        pendingRequest = null;
        return;
      }
      if (sid === 0x5A) {
        var ascii = '';
        body2.slice(2).forEach(function (b) {
          ascii += (b >= 32 && b < 127) ? String.fromCharCode(b) : '';
        });
        if (ascii.trim()) identification.push({ ascii: ascii.trim() });
        return;
      }
      if (sid === 0x61 && body2.length > 1) {
        var localId = body2[1];
        var payload = body2.slice(2);
        if (!payload.length) return;
        var entry = ids[localId];
        if (!entry) {
          entry = ids[localId] = {
            local_id: localId,
            hex: '0x' + H.hex2(localId).toUpperCase(),
            length: payload.length,
            samples: 0, values: [],
          };
        }
        var value = 0;
        payload.forEach(function (b) { value = value * 256 + b; });
        entry.samples++;
        entry.values.push(value);
        pendingRequest = null;
      }
    });

    var identifiers = Object.keys(ids).map(Number).sort(function (a, b) { return a - b; })
      .map(function (localId) {
        var entry = ids[localId];
        var min = Math.min.apply(null, entry.values);
        var max = Math.max.apply(null, entry.values);
        return {
          local_id: entry.local_id, hex: entry.hex, length: entry.length,
          answers: true, samples: entry.samples,
          min: min, max: max,
          moved: max !== min,
          always_zero: max === 0 && min === 0,
        };
      });

    var answered = identifiers.length;
    var summary = {
      answered: answered,
      moved: identifiers.filter(function (e) { return e.moved; }).length,
      always_zero: identifiers.filter(function (e) { return e.always_zero; }).length,
      refused: refused,
    };

    return [200, {
      frames: frames.length,
      summary: summary,
      identifiers: identifiers,
      matches: [],
      identification: identification,
      services_seen: Object.keys(services).map(function (sid) {
        return { service: sid, name: services[sid] };
      }),
      draft: {
        note: 'A draft catalog fragment: every identifier that answered, with '
          + 'the width and range seen. Nothing here is a scaling — in the '
          + 'hosted demo no reference log can be loaded, so no scaling is '
          + 'solved and nothing may be called verified-capture. Run the local '
          + 'workstation with the other tool\'s CSV to solve them.',
        family: String(body.family || 'unknown'),
        parameters: identifiers.map(function (entry) {
          return {
            local_id: entry.local_id, length: entry.length,
            observed_min: entry.min, observed_max: entry.max,
            confidence: 'unknown',
          };
        }),
      },
      note: answered
        ? 'Characterised in the browser: which identifiers answered and how '
          + 'their bytes behaved. Scalings are solved only by the local '
          + 'workstation, against the reference CSV.'
        : 'No 0x61 responses were found. Paste a capture of a diagnostic '
          + 'session, one frame of hex bytes per line.',
      analysed_in: 'browser',
    }];
  });

  /* -- adapter pre-flight ----------------------------------------------- */

  D.register('GET', '/api/adapter', function () {
    return [200, {
      ports: [],
      report: {},
      text: 'No serial ports: this is a web page. A browser cannot enumerate '
        + 'USB serial adapters, read an FTDI latency timer or set one — and '
        + 'GuzziOnBoard will not pretend otherwise by faking an adapter that '
        + 'is not there.\n\n'
        + 'On the local workstation this view lists every port it can see, '
        + 'flags the ones that look like a K-Line adapter, reads the FTDI '
        + 'latency timer (16 ms by default, 1 ms is what KWP2000 timing '
        + 'wants) and tells you how to fix it on your OS.\n\n'
        + '    python3 run_server.py   ->   http://127.0.0.1:8000',
      simulated: false,
      demo: true,
    }];
  });

  D.register('POST', '/api/adapter/latency', function () {
    return [200, {
      ok: false,
      latency_ms: null,
      instructions: 'A web page cannot touch a USB device\'s driver settings. '
        + 'Run the local workstation and this button will set the FTDI '
        + 'latency timer for you (or tell you the one command that does).',
    }];
  });

  /* ======================================================================
   * 15. What the page says about itself
   * ======================================================================
   * Every view below now does something, so the "local workstation only"
   * notices would be lies. They are replaced by notices that say what is
   * simulated and what the compression is — the honesty requirement does
   * not go away just because the demo got better.
   */

  var V = D.views;
  Object.keys(V).forEach(function (key) { delete V[key]; });

  V.firmware = '<b>Simulated, and time-compressed.</b> The image is '
    + 'synthesised in your browser from the selected ECU family, not read off '
    + 'a bike. A read that takes about twenty minutes over K-Line at 10.4 '
    + 'kBaud here takes a few seconds — the progress, block counts and '
    + 'timings are scaled, and every result says so. Checksums, backups, '
    + 'validation and verify-after-write are the real algorithms on the '
    + 'simulated image.';
  V.procedures = '<b>Simulated, and time-compressed.</b> The steps, wording '
    + 'and verdict rules are the real ones; the observation windows run '
    + 'against the simulated engine at about ' + OBSERVE_COMPRESSION + 'x, so '
    + 'a ten-second watch takes roughly a second. Actuator steps still go '
    + 'through the safety gate.';
  V.sessions = '<b>Simulated.</b> Recording, replay, CSV/JSON export and the '
    + 'before/after comparison all work, in memory — two pre-recorded demo '
    + 'sessions are loaded so there is something to compare. Nothing is '
    + 'written to disk; the local workstation keeps JSONL files.';
  V.report = '<b>Simulated.</b> The report is built from this browser '
    + 'session: simulated samples, simulated faults, the real derived '
    + 'channels, plausibility rules and safety audit. The local workstation '
    + 'writes the same thing to text, JSON and PDF.';
  V.tools = '<b>Real arithmetic, no bike needed.</b> Gearing, the '
    + 'Zeitronix→DIF conversion, the bench RPM WAV and the CAN capture '
    + 'analysis are the shipping algorithms, running here. They read pasted '
    + 'text rather than files, and the WAV arrives through your browser\'s '
    + 'downloads. K-Line captures are characterised but scalings are not '
    + 'solved: that needs a reference log from disk.';
  V.discovery = '<b>Hardware is the one thing not faked.</b> Serial ports, '
    + 'FTDI latency timers and a CAN bus do not exist in a web page, and '
    + 'inventing them would teach you something false. Everything else here '
    + 'is a simulation; this is a refusal.';

  D.ui.banner = '<b>Hosted demo</b> — the whole workstation, with a simulated '
    + 'ECU and a simulated motorcycle running in your browser. Memory reads '
    + 'and flashes are time-compressed (seconds, not twenty minutes), maps '
    + 'come from the bundled XDF definitions applied to a synthesised image, '
    + 'and guided tests run against the engine model at '
    + OBSERVE_COMPRESSION + 'x. Nothing here has touched a motorcycle. Real '
    + 'hardware — serial adapters, CAN — needs the local tool: '
    + '<code>python3 run_server.py</code>. '
    + '<a href="../index.html">About GuzziOnBoard</a>';

  var MAPS_NOTE = '<b>Simulated.</b> Tables are rendered through the '
    + "project's bundled XDF definitions, applied to the synthesised image "
    + 'above. The parser, the axis maths and the diff are the shipping ones; '
    + 'the bytes underneath them are not from a motorcycle.';

  function labNotice(html) {
    var note = document.createElement('div');
    note.className = 'notice warn';
    note.setAttribute('style', [
      'margin:0 0 16px', 'padding:12px 14px', 'border-radius:8px',
      'background:#2a2118', 'border:1px solid #6b4f24', 'color:#f0d9a8',
    ].join(';'));
    note.innerHTML = html;
    return note;
  }

  function decorateLab() {
    if (typeof document === 'undefined') return;
    /* The maps panel lives inside the firmware view, so it needs its own
     * notice rather than a view-level one. */
    var mapsOut = document.getElementById('mapsOut');
    var mapsPanel = mapsOut && mapsOut.closest ? mapsOut.closest('.panel') : null;
    if (mapsPanel) mapsPanel.insertBefore(labNotice(MAPS_NOTE), mapsPanel.firstChild);
    var drop = document.getElementById('simDrop');
    var panel = drop && drop.closest ? drop.closest('.panel') : null;
    if (panel) {
      var note = document.createElement('p');
      note.className = 'muted small';
      note.innerHTML = '<b>Simulated wire.</b> There is no K-Line here, so '
        + 'these sliders spoil the simulated one instead: dropped frames come '
        + 'back as timeouts, corrupted ones as checksum errors, '
        + 'responsePending adds a wait, and the latency slider really does '
        + 'delay your live data. The faults are drawn from a seeded generator '
        + 'so a given setting behaves the same way twice.';
      panel.appendChild(note);
    }
  }

  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', decorateLab);
    } else {
      decorateLab();
    }
  }

  /* Exposed for the Node test harness (tests/demo_browser_check.mjs) so the
   * ports above can be compared against the Python originals. */
  D.lab = {
    md5: md5, sha256: sha256, checksums: checksums,
    entropyEstimate: entropyEstimate, looksLikeVectorTable: looksLikeVectorTable,
    hardwareStrings: hardwareStrings, parseXml: parseXml, parseXdf: parseXdf,
    renderXdf: renderXdf, diffXdf: diffXdf, suggestAddressBase: suggestAddressBase,
    parseCanText: parseCanText, analyseCanFrames: analyseCanFrames,
    tyreCircumference: tyreCircumference, renderTriggerWav: renderTriggerWav,
    buildReport: buildReport, reportText: reportText, verdicts: VERDICTS,
    plausibility: plausibility, applyComms: applyComms,
    sessions: SESSIONS, seedSessions: seedSessions, replayFrames: replayFrames,
    compareSessions: compareSessions, sessionCsv: sessionCsv, sweepsOf: sweepsOf,
    fs: FS, job: function () { return JOB; }, validateImage: validateImage,
    synthesiseImage: synthesiseImage, enrichFuel: enrichFuel, xdfForEcu: xdfForEcu,
  };
}());
