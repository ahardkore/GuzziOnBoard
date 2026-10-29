/*
 * Axis-aware interpolation adapted from Atlas TableInterpolation.java,
 * LinearInterpolationFunction.java, and NearestNeighborInterpolationFunction.java.
 * Source: https://github.com/jakka351/atlas/tree/91499280f20a81cabdd891c5e0ca70143bb8c800/java/src/main/java/com/github/manevolent/atlas/math
 * Atlas contributors, including manevolent, 2024. Upstream license: AGPL-3.0.
 * Modified for GuzziOnBoard on 2026-10-28: JavaScript adaptation, strict axis
 * validation, and pure computations; does not write an image or reach hardware.
 * SPDX-License-Identifier: AGPL-3.0-only
 */
'use strict';

const AtlasInterpolation = Object.freeze({
  // Returns the relative axis position used by Atlas's row/column regions.
  // The UI may opt for ordinal cell spacing to preserve the original behavior.
  positions(axis, first, last, axisAware) {
    if (!Number.isInteger(first) || !Number.isInteger(last) || first < 0 || last <= first) {
      throw new Error('Interpolation bounds are invalid.');
    }
    if (!axisAware) return Array.from({ length: last - first + 1 }, (_, i) => i / (last - first));
    if (!Array.isArray(axis) || last >= axis.length) throw new Error('This table has no complete numeric axis.');
    const values = axis.slice(first, last + 1).map((value) => {
      if (!['number', 'string'].includes(typeof value)
          || (typeof value === 'string' && !value.trim())) return NaN;
      return Number(value);
    });
    if (values.some((value) => !Number.isFinite(value))) {
      throw new Error('Axis-aware interpolation requires numeric axis values; select cell spacing instead.');
    }
    const ascending = values[1] > values[0];
    if (values.some((value, i) => i && (ascending ? value <= values[i - 1] : value >= values[i - 1]))) {
      throw new Error('Axis-aware interpolation requires a strictly monotonic axis with no duplicate values.');
    }
    const low = values[0], high = values[values.length - 1];
    const span = high - low;
    if (!Number.isFinite(span) || span === 0) throw new Error('Axis range is too large for interpolation.');
    const result = values.map((value, i) => i === 0 ? 0 : (value - low) / span);
    if (result.some((value) => !Number.isFinite(value) || value < 0 || value > 1)) {
      throw new Error('Axis range cannot be represented safely.');
    }
    return result;
  },
  interpolate(a, b, fraction, method) {
    if (![a, b, fraction].every(Number.isFinite) || fraction < 0 || fraction > 1) {
      throw new Error('Interpolation requires finite values within the selected bounds.');
    }
    if (method === 'nearest') return fraction > 0.5 ? b : a;
    if (method === 'linear') {
      const value = a + ((b - a) * fraction);
      if (!Number.isFinite(value)) throw new Error('Interpolated value is not finite.');
      return value;
    }
    throw new Error('Unknown interpolation method.');
  },
});
