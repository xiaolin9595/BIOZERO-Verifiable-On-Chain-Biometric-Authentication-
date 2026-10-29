#!/usr/bin/env bash
set -euo pipefail

bundle_root="${1:-$(cd "$(dirname "$0")/.." && pwd)}"

for script in "$bundle_root"/harness/*.sh; do
  bash -n "$script"
done
for script in "$bundle_root"/harness/*.mjs; do
  node --check "$script"
done

node --input-type=module - "$bundle_root" <<'NODE'
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const root = process.argv[2];
const readJson = (relative) => JSON.parse(fs.readFileSync(path.join(root, relative), 'utf8'));
const assert = (condition, message) => { if (!condition) throw new Error(message); };
const digest = (relative) => crypto.createHash('sha256')
  .update(fs.readFileSync(path.join(root, relative))).digest('hex');

const summary = readJson('results/summary.json');
const verification = readJson('results/verification.json');
const native = readJson('fresh/native-validation/summary.json');
const chain = readJson('fresh/chain/summary.json');
const comparison = readJson('results/fresh-vs-recovered.json');
const expected = ['biozero-fixed', 'vanilla-2', 'vanilla-4', 'vanilla-8',
  'vanilla-16', 'vanilla-32', 'vanilla-64', 'vanilla-128'];

assert(summary.verification.overall === 'PASS', 'summary verification is not PASS');
assert(verification.overall === 'PASS' && verification.failed === 0, 'verification checks failed');
assert(native.overall === 'PASS', 'native validation is not PASS');
assert(chain.overall === 'PASS' && chain.targets.length === 8, 'chain validation is not 8/8 PASS');
assert(summary.results.length === 8, 'summary does not contain eight targets');
assert(expected.every((target) => summary.results.some((row) => row.target === target)), 'missing target');
assert(comparison.comparison.length === 8, 'historical comparison does not contain eight targets');

const nativeByTarget = new Map(native.targets.map((row) => [row.target, row]));
for (const row of summary.results) {
  const expectedGasRuns = row.target === 'biozero-fixed' ? 30 : 5;
  const expectedGasWarmups = row.target === 'biozero-fixed' ? 5 : 1;
  assert(row.constraint_count > 0, `${row.target}: missing constraints`);
  assert(row.proof_time.samples === 5 && row.proof_time.measured_runs.length === 5,
    `${row.target}: proof replicate count`);
  assert(row.verifier_gas.samples === expectedGasRuns && row.verifier_gas.measured_runs.length === expectedGasRuns,
    `${row.target}: gas replicate count`);
  assert(row.verifier_gas.warmup_runs === expectedGasWarmups, `${row.target}: gas warmup count`);
  assert(Object.values(row.matching_and_controls).every(Boolean), `${row.target}: control failure`);
  assert(nativeByTarget.get(row.target)?.constraint_count === row.constraint_count,
    `${row.target}: native/latency constraint mismatch`);

  const nativeRow = nativeByTarget.get(row.target);
  const workspace = row.target === 'biozero-fixed' ? 'groth16_biozero' : `groth16_vanilla_${row.dimension}`;
  assert(digest(`fresh/cache-small/${workspace}/main.zok`) === nativeRow.artifact_hashes.fixed_source_sha256,
    `${row.target}: source hash mismatch`);
  assert(digest(`fresh/cache-small/${workspace}/proof.json`) === nativeRow.artifact_hashes.proof_sha256,
    `${row.target}: proof hash mismatch`);
  assert(digest(`fresh/cache-small/${workspace}/verification.key`) === nativeRow.artifact_hashes.verification_key_sha256,
    `${row.target}: verification-key hash mismatch`);

  const chainRow = readJson(`fresh/chain/${row.target}.json`);
  assert(chainRow.overall === 'PASS', `${row.target}: chain result not PASS`);
  assert(chainRow.valid_control.transactions.length === expectedGasRuns, `${row.target}: receipt count`);
  assert(chainRow.valid_control.transactions.every((receipt) => receipt.receipt_status === 1),
    `${row.target}: unsuccessful valid receipt`);
  assert(chainRow.invalid_public_input_control.static_return === false,
    `${row.target}: invalid public input was accepted`);
  assert(chainRow.deployment.creation_bytecode_bytes === row.verifier_creation_bytecode_bytes,
    `${row.target}: creation-bytecode mismatch`);
  assert(chainRow.deployment.compiled_runtime_bytecode_bytes === row.verifier_runtime_bytecode_bytes,
    `${row.target}: runtime-bytecode mismatch`);
}

const n128 = summary.results.find((row) => row.target === 'vanilla-128');
const n128Chain = readJson('fresh/chain/vanilla-128.json');
assert(n128.eip170_deployable === false, 'N=128 incorrectly marked EIP-170 deployable');
assert(n128Chain.standard_eip170_control.deployment_failed_as_expected === true,
  'N=128 standard-size-limit deployment did not fail as expected');
assert(n128Chain.standard_eip170_control.error_receipt.receipt_status === 0,
  'N=128 standard-size-limit failure receipt missing');

console.log('JSON, replicate, receipt, control, constraint, and hash checks: PASS');
NODE

(
  cd "$bundle_root"
  sha256sum -c MANIFEST.sha256 >/dev/null
)
echo "Bundle manifest: PASS"
echo "OVERALL: PASS"
