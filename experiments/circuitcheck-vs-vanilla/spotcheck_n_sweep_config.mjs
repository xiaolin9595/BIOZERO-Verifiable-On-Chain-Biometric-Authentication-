export const DIMENSIONS = Object.freeze([2, 4, 8, 16, 32, 64, 128]);
export const ETAS = Object.freeze([1, 2, 4, 8]);
export const REPETITIONS = 3;

export function sampleCount(dimension, eta) {
  if (!Number.isInteger(dimension) || dimension <= 0) {
    throw new RangeError("dimension must be a positive integer");
  }
  if (!Number.isFinite(eta) || eta <= 0) {
    throw new RangeError("eta must be positive");
  }
  return Math.min(dimension, Math.ceil(eta * Math.log2(dimension)));
}

export function buildGrid(dimensions = DIMENSIONS, etas = ETAS) {
  return dimensions.flatMap((dimension) =>
    etas.map((eta) => ({
      dimension,
      eta,
      samples: sampleCount(dimension, eta),
      label: `spot-n-${dimension}-eta-${eta}`,
    })),
  );
}

export function median(values) {
  if (!Array.isArray(values) || values.length === 0) {
    throw new RangeError("median requires at least one value");
  }
  return [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];
}

export function csvCell(value) {
  const text = String(value);
  return /[",\n]/u.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}
