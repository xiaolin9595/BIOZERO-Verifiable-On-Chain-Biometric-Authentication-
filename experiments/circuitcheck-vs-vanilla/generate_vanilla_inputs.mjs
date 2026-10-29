#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";

const [dimensionText, attemptText, outputDir] = process.argv.slice(2);
const dimension = Number(dimensionText);
const attempt = Number(attemptText);

if (![2, 4, 8, 16, 32, 64, 128].includes(dimension)) {
  throw new Error(`unsupported dimension: ${dimensionText}`);
}
if (!Number.isInteger(attempt) || attempt < 0) {
  throw new Error(`attempt must be a non-negative integer: ${attemptText}`);
}
if (!outputDir) {
  throw new Error("usage: generate_vanilla_inputs.mjs DIM ATTEMPT OUTPUT_DIR");
}

const params = {
  p: 67108859n,
  g: 56544564n,
  h: 237684576n,
};

class DeterministicRng {
  constructor(seed) {
    this.state = (seed >>> 0) || 1;
  }

  nextUint32() {
    let value = this.state;
    value ^= value << 13;
    value ^= value >>> 17;
    value ^= value << 5;
    this.state = value >>> 0;
    return this.state;
  }

  bigintRange(minInclusive, maxInclusive) {
    const width = maxInclusive - minInclusive + 1n;
    return minInclusive + (BigInt(this.nextUint32()) % width);
  }
}

function modPow(base, exponent, modulus) {
  let result = 1n;
  let factor = base % modulus;
  let power = exponent;
  while (power > 0n) {
    if ((power & 1n) === 1n) {
      result = (result * factor) % modulus;
    }
    factor = (factor * factor) % modulus;
    power >>= 1n;
  }
  return result;
}

function commitment(message, randomness) {
  return (
    (modPow(params.g, message, params.p) *
      modPow(params.h, randomness, params.p)) %
    params.p
  );
}

// Independent deterministic stream per (dimension, attempt). Attempt zero is the
// warmup; attempts one through ten are measured runs.
const seed = (0x5eed2026 + dimension * 1009 + attempt * 9176) >>> 0;
const rng = new DeterministicRng(seed);
const m1 = [];
const m2 = [];
const r1 = [];
const r2 = [];
let distance = 0n;

for (let index = 0; index < dimension; index += 1) {
  const right = rng.bigintRange(1n, 200n);
  const delta = rng.bigintRange(0n, 20n);
  const left = right + delta;
  const randLeft = rng.bigintRange(1n, 10_000n);
  const randRight = rng.bigintRange(1n, 10_000n);

  m1.push(left);
  m2.push(right);
  r1.push(randLeft);
  r2.push(randRight);
  distance += delta * delta;
}

const res = [
  ...m1.map((message, index) => commitment(message, r1[index])),
  ...m2.map((message, index) => commitment(message, r2[index])),
];
const threshold = distance + 100n;
const args = [
  params.g,
  params.h,
  ...res,
  ...m1,
  ...r1,
  ...m2,
  ...r2,
  threshold,
  params.p,
].map(String);

fs.mkdirSync(outputDir, { recursive: true });
fs.writeFileSync(path.join(outputDir, "arguments.txt"), `${args.join("\n")}\n`);
fs.writeFileSync(
  path.join(outputDir, "input.json"),
  `${JSON.stringify(
    {
      scheme: "vanilla_zkbio",
      dimension,
      attempt,
      seed,
      params: Object.fromEntries(
        Object.entries(params).map(([key, value]) => [key, String(value)]),
      ),
      m1: m1.map(String),
      r1: r1.map(String),
      m2: m2.map(String),
      r2: r2.map(String),
      commitments: res.map(String),
      squared_distance: String(distance),
      threshold: String(threshold),
      arguments: args,
    },
    null,
    2,
  )}\n`,
);

