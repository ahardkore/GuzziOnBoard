/* Render one bundled XDF against one image with the browser demo's parser.
 *
 * ``web/demo-lab.js`` carries a JavaScript port of ``guzzionboard/maps.py``
 * so the hosted demo can show real tables. A port is only worth having if it
 * agrees with the original, so this script renders a definition the way the
 * browser does and writes the result as JSON; ``tests/test_demo_mode.py``
 * renders the same definition with the Python code and compares the two.
 *
 *   node tests/demo_xdf_parity.mjs <definition.xdf> <image.bin> <out.json>
 */
import fs from 'node:fs';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const [xdfPath, binPath, outPath] = process.argv.slice(2);
if (!xdfPath || !binPath || !outPath) {
  console.error('usage: demo_xdf_parity.mjs <definition.xdf> <image.bin> <out.json>');
  process.exit(2);
}

/* demo-lab.js only needs a handful of globals and the small surface
 * demo-api.js exports; stub both rather than booting the whole shim. */
const context = vm.createContext({
  console, Math, Date, JSON, Object, Array, String, Number, Boolean, RegExp,
  Error, Function, Promise, Uint8Array, Int16Array, Int32Array, Uint32Array,
  DataView, ArrayBuffer, isFinite, isNaN, parseInt, parseFloat, setTimeout,
  performance,
  window: {
    GUZZI_DEMO: {
      helpers: {
        httpError: (status, message) => Object.assign(new Error(message), { status }),
        clamp: (v, lo, hi) => Math.max(lo, Math.min(hi, v)),
        epoch: () => Date.now() / 1000,
        mono: () => Date.now() / 1000,
        rng: (seed) => {
          let a = seed >>> 0;
          return () => {
            a |= 0; a = (a + 0x6D2B79F5) | 0;
            let t = Math.imul(a ^ (a >>> 15), 1 | a);
            t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
          };
        },
        data: () => null,
      },
      state: {}, hooks: {}, ui: {}, views: {}, localOnly: {}, register: () => {},
    },
  },
});
context.globalThis = context;
vm.runInContext(fs.readFileSync(join(ROOT, 'web', 'demo-lab.js'), 'utf8'),
  context, { filename: 'demo-lab.js' });

const lab = context.window.GUZZI_DEMO.lab;
const xdf = lab.parseXdf(fs.readFileSync(xdfPath, 'latin1'), xdfPath);
const image = { bytes: new Uint8Array(fs.readFileSync(binPath)) };
fs.writeFileSync(outPath, JSON.stringify(lab.renderXdf(xdf, image, null)));
