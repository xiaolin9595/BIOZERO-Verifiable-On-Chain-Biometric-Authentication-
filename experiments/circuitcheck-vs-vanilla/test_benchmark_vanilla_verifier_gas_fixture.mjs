#!/usr/bin/env node

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  EIP170_RUNTIME_LIMIT_BYTES,
  bytesOfHex,
  csv,
  mutateFirstPublicInput,
  parseLegacyChainSample,
  proofForAbi,
} from "./benchmark_vanilla_verifier_gas.mjs";

const harnessDir = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(harnessDir, "../../..");
const legacyRoot = path.join(
  repositoryRoot,
  "reproduction-audit-2026-10-27",
  "reconstructed",
  "fig3-full",
  "fresh",
  "chain",
);

function readLegacy(name) {
  return JSON.parse(fs.readFileSync(path.join(legacyRoot, name), "utf8"));
}

const n2 = parseLegacyChainSample(readLegacy("vanilla-2.json"));
assert.equal(n2.dimension, 2);
assert.equal(n2.measured_transactions, 5);
assert.equal(n2.valid_static_true, true);
assert.equal(n2.invalid_static_false, true);
assert.equal(n2.runtime_matches_compiler, true);
assert.equal(n2.eip170_deployable, true);
assert.ok(n2.runtime_bytecode_bytes < EIP170_RUNTIME_LIMIT_BYTES);

const n128 = parseLegacyChainSample(readLegacy("vanilla-128.json"));
assert.equal(n128.dimension, 128);
assert.equal(n128.measured_transactions, 5);
assert.equal(n128.valid_static_true, true);
assert.equal(n128.invalid_static_false, true);
assert.equal(n128.runtime_matches_compiler, true);
assert.equal(n128.eip170_deployable, false);
assert.equal(n128.standard_eip170_failure_recorded, true);
assert.ok(n128.runtime_bytecode_bytes > EIP170_RUNTIME_LIMIT_BYTES);

const tupleAbi = {
  inputs: [{ type: "tuple" }, { type: "uint256[]" }],
};
const proofJson = {
  proof: {
    a: ["1", "2"],
    b: [["3", "4"], ["5", "6"]],
    c: ["7", "8"],
  },
  inputs: ["0x01", "2"],
};
const [tupleProof, inputs] = proofForAbi(proofJson, tupleAbi);
assert.deepEqual(tupleProof, {
  a: { X: "1", Y: "2" },
  b: { X: ["3", "4"], Y: ["5", "6"] },
  c: { X: "7", Y: "8" },
});
assert.deepEqual(inputs, proofJson.inputs);
assert.deepEqual(mutateFirstPublicInput(["0x01", "2"]), ["0x02", "2"]);
assert.equal(bytesOfHex("0x0011"), 2);
assert.equal(csv([["a", "b,c"], [1, 'x"y']]), 'a,"b,c"\n1,"x""y"\n');

process.stdout.write(
  `fixture PASS: legacy N=2 runtime=${n2.runtime_bytecode_bytes}B; ` +
    `legacy N=128 runtime=${n128.runtime_bytecode_bytes}B and standard EIP-170 failure preserved\n`,
);

