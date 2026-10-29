#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';

const fig3FullRoot = path.resolve(import.meta.dirname, '..');
const freshRoot = path.resolve(process.env.FIG3_FRESH_ROOT ?? path.join(fig3FullRoot, 'fresh'));
const outputRoot = path.resolve(process.env.FIG3_SUMMARY_OUTPUT ?? path.join(fig3FullRoot, 'results'));

function readJson(relativePath) {
  return JSON.parse(fs.readFileSync(path.join(freshRoot, relativePath), 'utf8'));
}

function parseCsv(relativePath) {
  const lines = fs.readFileSync(path.join(freshRoot, relativePath), 'utf8').trim().split(/\r?\n/);
  const headers = lines.shift().split(',');
  return lines.filter(Boolean).map((line) => Object.fromEntries(
    line.split(',').map((value, index) => [headers[index], value]),
  ));
}

function number(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function sampleSd(values) {
  if (values.length < 2) return 0;
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  return Math.sqrt(values.reduce((sum, value) => sum + ((value - mean) ** 2), 0) / (values.length - 1));
}

const lowRaw = parseCsv('raw/latency-low/latency_raw.csv');
const highRaw = parseCsv('raw/latency-high/latency_raw.csv');
const lowSummary = parseCsv('summary/latency-low/latency_summary.csv');
const highSummary = parseCsv('summary/latency-high/latency_summary.csv');
const nativeSummary = readJson('native-validation/summary.json');
const chainSummary = readJson('chain/summary.json');
const environment = readJson('environment.json');

const targets = [
  { label: 'biozero-fixed', scheme: 'biozero_zk', dimension: 0, source: 'high' },
  ...[2, 4, 8, 16, 32].map((dimension) => ({
    label: `vanilla-${dimension}`, scheme: 'vanilla_zkbio', dimension, source: 'low',
  })),
  ...[64, 128].map((dimension) => ({
    label: `vanilla-${dimension}`, scheme: 'vanilla_zkbio', dimension, source: 'high',
  })),
];

const results = targets.map((target) => {
  const rawRows = (target.source === 'low' ? lowRaw : highRaw).filter(
    (row) => row.scheme === target.scheme && Number(row.dimension) === target.dimension,
  );
  const latencyRow = (target.source === 'low' ? lowSummary : highSummary).find(
    (row) => row.scheme === target.scheme && Number(row.dimension) === target.dimension,
  );
  const native = nativeSummary.targets.find((entry) => entry.target === target.label);
  const chain = readJson(`chain/${target.label}.json`);
  const provingRuns = rawRows.map((row) => number(row.prove_ms));
  const verificationRuns = rawRows.map((row) => number(row.verify_ms));
  const gasRuns = chain.valid_control.transactions.map((row) => Number(row.gas_used));
  return {
    target: target.label,
    dimension: target.dimension === 0 ? null : target.dimension,
    protocol_partition: target.source === 'low'
      ? 'N=2..32; RAYON_NUM_THREADS unset'
      : target.label === 'biozero-fixed'
        ? 'BioZero fixed after N=128; RAYON_NUM_THREADS=1'
        : 'N=64,128; RAYON_NUM_THREADS=1',
    setup_policy: environment.protocol.setup_policy,
    constraint_count: number(latencyRow.constraints) ?? native.constraint_count,
    proof_time: {
      unit: 'ms',
      warmup_runs: 1,
      measured_runs: provingRuns,
      samples: provingRuns.length,
      mean: number(latencyRow.prove_mean_ms),
      sample_sd: sampleSd(provingRuns),
      p50: number(latencyRow.prove_p50_ms),
      p95: number(latencyRow.prove_p95_ms),
    },
    native_verification_time: {
      unit: 'ms',
      measured_runs: verificationRuns,
      mean: number(latencyRow.verify_mean_ms),
    },
    proof_size: {
      unit: 'bytes',
      measured_runs: rawRows.map((row) => number(row.proof_bytes)),
      mean: number(latencyRow.proof_mean_bytes),
    },
    verifier_gas: {
      warmup_runs: chain.valid_control.warmup_transactions.length,
      measured_runs: gasRuns,
      samples: gasRuns.length,
      mean: gasRuns.reduce((sum, value) => sum + value, 0) / gasRuns.length,
      sample_sd: sampleSd(gasRuns),
      estimate: chain.valid_control.estimated_gas,
    },
    deployment_gas: chain.deployment.gas_used,
    // Historical Fig. 3 stored creation bytecode under verifier_bytecode_bytes.
    // Keep that compatibility field, and record runtime size separately for EIP-170.
    verifier_bytecode_bytes: chain.deployment.creation_bytecode_bytes,
    verifier_creation_bytecode_bytes: chain.deployment.creation_bytecode_bytes,
    verifier_runtime_bytecode_bytes: chain.deployment.compiled_runtime_bytecode_bytes,
    eip170_deployable: chain.deployment.compiled_runtime_bytecode_bytes <= 24_576,
    matching_and_controls: {
      native_valid_proof_accepted: native.valid_proof.accepted,
      native_invalid_public_input_rejected: native.invalid_public_input_control.rejected,
      verifier_reexport_byte_exact_match: native.matching_verifier.byte_exact_match_with_cached_verifier,
      chain_valid_static_true: chain.valid_control.static_return === true,
      chain_invalid_static_false: chain.invalid_public_input_control.static_return === false,
      onchain_runtime_matches_compiler: chain.deployment.onchain_runtime_matches_compiled,
      standard_eip170_behavior: chain.acceptance.standard_eip170_behavior,
    },
    hashes: {
      fixed_source_sha256: native.artifact_hashes.fixed_source_sha256,
      proof_sha256: native.artifact_hashes.proof_sha256,
      verification_key_sha256: native.artifact_hashes.verification_key_sha256,
      verifier_solidity_sha256: native.matching_verifier.cached_sha256,
    },
  };
});

const checks = [];
function check(name, passed, detail = null) {
  checks.push({ name, passed: Boolean(passed), detail });
}
check('all eight Fig. 3 targets present', results.length === 8, results.map((row) => row.target));
check('native validation overall PASS', nativeSummary.overall === 'PASS', nativeSummary.overall);
check('chain validation overall PASS', chainSummary.overall === 'PASS', chainSummary.overall);
for (const result of results) {
  check(`${result.target}: constraint count recorded`, Number.isInteger(result.constraint_count) && result.constraint_count > 0, result.constraint_count);
  check(`${result.target}: five measured proofs`, result.proof_time.samples === 5, result.proof_time.samples);
  const expectedGasSamples = result.target === 'biozero-fixed' ? 30 : 5;
  const expectedGasWarmups = result.target === 'biozero-fixed' ? 5 : 1;
  check(`${result.target}: old-protocol gas receipt count`, result.verifier_gas.samples === expectedGasSamples, result.verifier_gas.samples);
  check(`${result.target}: old-protocol gas warmup count`, result.verifier_gas.warmup_runs === expectedGasWarmups, result.verifier_gas.warmup_runs);
  check(`${result.target}: all matching/control checks`, Object.values(result.matching_and_controls).every(Boolean), result.matching_and_controls);
}
const verification = {
  schema_version: 1,
  overall: checks.every((entry) => entry.passed) ? 'PASS' : 'FAIL',
  passed: checks.filter((entry) => entry.passed).length,
  failed: checks.filter((entry) => !entry.passed).length,
  checks,
};

const summary = {
  schema_version: 1,
  experiment_label: 'fresh full Fig. 3 reconstruction; not original raw data',
  recovered_campaign_is_separate_evidence: true,
  environment,
  results,
  verification: { overall: verification.overall, passed: verification.passed, failed: verification.failed },
};

fs.mkdirSync(outputRoot, { recursive: true });
fs.writeFileSync(path.join(outputRoot, 'summary.json'), `${JSON.stringify(summary, null, 2)}\n`);
fs.writeFileSync(path.join(outputRoot, 'verification.json'), `${JSON.stringify(verification, null, 2)}\n`);
const csvHeaders = [
  'target', 'dimension', 'constraints', 'proof_samples', 'proof_mean_ms', 'proof_sample_sd_ms',
  'proof_p50_ms', 'proof_p95_ms', 'proof_mean_bytes', 'verifier_gas_samples', 'verifier_gas_mean',
  'verifier_gas_sample_sd', 'deployment_gas', 'verifier_creation_bytecode_bytes',
  'verifier_runtime_bytecode_bytes', 'eip170_deployable', 'overall_controls',
];
const csvRows = results.map((row) => [
  row.target,
  row.dimension ?? '',
  row.constraint_count,
  row.proof_time.samples,
  row.proof_time.mean,
  row.proof_time.sample_sd,
  row.proof_time.p50,
  row.proof_time.p95,
  row.proof_size.mean,
  row.verifier_gas.samples,
  row.verifier_gas.mean,
  row.verifier_gas.sample_sd,
  row.deployment_gas,
  row.verifier_creation_bytecode_bytes,
  row.verifier_runtime_bytecode_bytes,
  row.eip170_deployable,
  Object.values(row.matching_and_controls).every(Boolean),
]);
fs.writeFileSync(
  path.join(outputRoot, 'summary.csv'),
  `${[csvHeaders, ...csvRows].map((row) => row.join(',')).join('\n')}\n`,
);
process.stdout.write(`${JSON.stringify(verification, null, 2)}\n`);
if (verification.overall !== 'PASS') process.exitCode = 1;
