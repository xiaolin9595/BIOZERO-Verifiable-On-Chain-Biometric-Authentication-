import assert from "node:assert/strict";
import test from "node:test";
import {
  DIMENSIONS,
  ETAS,
  REPETITIONS,
  buildGrid,
  csvCell,
  median,
  sampleCount,
} from "./spotcheck_n_sweep_config.mjs";

test("Fig.3 grid contains exactly seven dimensions and four eta curves", () => {
  const grid = buildGrid();
  assert.equal(grid.length, 28);
  assert.deepEqual([...new Set(grid.map((row) => row.dimension))], DIMENSIONS);
  assert.deepEqual([...new Set(grid.map((row) => row.eta))], ETAS);
  assert.equal(new Set(grid.map((row) => row.label)).size, 28);
  assert.equal(new Set(grid.map((row) => `${row.dimension}:${row.samples}`)).size, 22);
  assert.equal(REPETITIONS, 3);
});

test("t=min(N,ceil(eta*log2(N))) for every grid point", () => {
  const expected = new Map([
    [2, [1, 2, 2, 2]],
    [4, [2, 4, 4, 4]],
    [8, [3, 6, 8, 8]],
    [16, [4, 8, 16, 16]],
    [32, [5, 10, 20, 32]],
    [64, [6, 12, 24, 48]],
    [128, [7, 14, 28, 56]],
  ]);
  for (const dimension of DIMENSIONS) {
    assert.deepEqual(ETAS.map((eta) => sampleCount(dimension, eta)), expected.get(dimension));
  }
});

test("configuration helpers reject malformed inputs and preserve CSV arrays", () => {
  assert.throws(() => sampleCount(0, 1), RangeError);
  assert.throws(() => sampleCount(2, 0), RangeError);
  assert.equal(median([5, 1, 3]), 3);
  assert.equal(csvCell("[1,2,3]"), '"[1,2,3]"');
});
