import { resolve } from "node:path";

export const ROOT = resolve(import.meta.dirname, "..");
export const DIMENSIONS = Object.freeze([2, 4, 8, 16, 32, 64, 128]);
export const PUBLIC_INPUTS = 5;
export const PACK_SIZE = 15;
export const DISTANCE_BITS = 48;
export const EIP170_RUNTIME_LIMIT_BYTES = 24_576;
export const DEFAULT_WARMUPS = 1;
export const DEFAULT_PROOF_REPETITIONS = 10;
export const DEFAULT_GAS_REPETITIONS = 5;

export function circuitName(dimension) {
  assertDimension(dimension);
  return `auth_distance_${dimension}`;
}

export function circuitParameters(dimension) {
  assertDimension(dimension);
  const blocks = Math.ceil(dimension / PACK_SIZE);
  return {
    dimension,
    bits: 16,
    qSpan: 65_535,
    packSize: PACK_SIZE,
    blocks,
    paddedBlocks: blocks % 2 === 0 ? blocks : blocks + 1,
    distanceBits: DISTANCE_BITS,
  };
}

export function assertDimension(dimension) {
  if (!DIMENSIONS.includes(Number(dimension))) {
    throw new Error(`dimension must be one of ${DIMENSIONS.join(",")}; received ${dimension}`);
  }
}

export function selectedDimensions(argv = process.argv.slice(2)) {
  const option = argv.find((argument) => argument.startsWith("--dimensions="));
  if (!option) return [...DIMENSIONS];
  const values = option.slice("--dimensions=".length).split(",").map(Number);
  if (values.length === 0 || new Set(values).size !== values.length) {
    throw new Error("--dimensions must contain a non-empty unique comma-separated list");
  }
  values.forEach(assertDimension);
  return values;
}

export function boundedCount(name, fallback) {
  const value = Number(process.env[name] ?? fallback);
  if (!Number.isInteger(value) || value < 0 || value > 50) {
    throw new Error(`${name} must be an integer from 0 to 50`);
  }
  return value;
}
