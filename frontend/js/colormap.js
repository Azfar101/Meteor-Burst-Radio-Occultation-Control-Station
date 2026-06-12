// Plasma-frequency colormap (matplotlib "plasma", 0..8 MHz).

export const FP_STOPS = [
  [0.0, [13, 8, 135]],
  [1.3, [91, 2, 163]],
  [2.6, [156, 23, 158]],
  [3.9, [204, 71, 120]],
  [5.2, [237, 121, 83]],
  [6.5, [253, 180, 47]],
  [8.0, [240, 249, 33]],
];

export function fpColor(v) {
  const s = FP_STOPS;
  if (v <= s[0][0]) return rgb(s[0][1]);
  for (let i = 1; i < s.length; i++) {
    if (v <= s[i][0]) {
      const t = (v - s[i - 1][0]) / (s[i][0] - s[i - 1][0]);
      const c = s[i - 1][1].map((a, j) => Math.round(a + t * (s[i][1][j] - a)));
      return rgb(c);
    }
  }
  return rgb(s[s.length - 1][1]);
}

function rgb(c) { return `rgb(${c[0]},${c[1]},${c[2]})`; }

// MapLibre data-driven expression for a numeric property
export function fpColorExpression(prop) {
  const expr = ["interpolate", ["linear"], ["get", prop]];
  for (const [v, c] of FP_STOPS) expr.push(v, rgb(c));
  return expr;
}

// Operating-frequency colormap (max usable freq, "turbo"-like, ~10..45 MHz).
// Distinct from the plasma scale so footprints read as operating frequency.
export const OPFREQ_STOPS = [
  [10, [48, 18, 120]],
  [18, [33, 144, 209]],
  [26, [60, 200, 120]],
  [34, [240, 220, 50]],
  [40, [248, 150, 35]],
  [45, [220, 40, 30]],
];
export const OPFREQ_MIN = OPFREQ_STOPS[0][0];
export const OPFREQ_MAX = OPFREQ_STOPS[OPFREQ_STOPS.length - 1][0];

export function opFreqColor(v) {
  const s = OPFREQ_STOPS;
  if (v <= s[0][0]) return rgb(s[0][1]);
  for (let i = 1; i < s.length; i++) {
    if (v <= s[i][0]) {
      const t = (v - s[i - 1][0]) / (s[i][0] - s[i - 1][0]);
      const c = s[i - 1][1].map((a, j) => Math.round(a + t * (s[i][1][j] - a)));
      return rgb(c);
    }
  }
  return rgb(s[s.length - 1][1]);
}

export function opFreqColorExpression(prop) {
  const expr = ["interpolate", ["linear"], ["get", prop]];
  for (const [v, c] of OPFREQ_STOPS) expr.push(v, rgb(c));
  return expr;
}

// CSS gradient string for legends.
export function opFreqGradientCss() {
  return "linear-gradient(90deg," + OPFREQ_STOPS.map(([, c]) => rgb(c)).join(",") + ")";
}
