#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const freshSummaryPath = path.resolve(process.env.FIG3_FRESH_SUMMARY ?? path.join(root, 'results/summary.json'));
const recoveredRoot = path.resolve(process.env.FIG3_RECOVERED_ROOT ?? path.join(root, 'recovered-campaign/results'));
const outputRoot = path.dirname(freshSummaryPath);

function parseCsv(filePath) {
  const lines = fs.readFileSync(filePath, 'utf8').trim().split(/\r?\n/);
  const headers = lines.shift().split(',');
  return lines.filter(Boolean).map((line) => Object.fromEntries(
    line.split(',').map((value, index) => [headers[index], value]),
  ));
}

function rows(relativePath) {
  return parseCsv(path.join(recoveredRoot, relativePath));
}

function find(rowsToSearch, scheme, dimension) {
  const row = rowsToSearch.find((entry) => entry.scheme === scheme && Number(entry.dimension) === dimension);
  if (!row) throw new Error(`Missing recovered row ${scheme}:${dimension}`);
  return row;
}

const recoveredLow = rows('summary/latency_2_64/latency_summary.csv');
const recovered64 = rows('summary/latency_64_lowmem/latency_summary.csv');
const recovered128 = rows('summary/latency_128_lowmem/latency_summary.csv');
const recoveredGasBiozero = rows('summary/groth16_biozero/groth16_gas_ci95.csv');
const recoveredGasLow = rows('summary/groth16_vanilla_2_64/groth16_gas_ci95.csv');
const recoveredGas128 = rows('summary/groth16_vanilla_128/groth16_gas_ci95.csv');
const fresh = JSON.parse(fs.readFileSync(freshSummaryPath, 'utf8'));

function delta(freshValue, recoveredValue) {
  return {
    fresh: freshValue,
    recovered: recoveredValue,
    absolute_delta: freshValue - recoveredValue,
    percent_delta: recoveredValue === 0 ? null : ((freshValue - recoveredValue) / recoveredValue) * 100,
  };
}

const comparison = fresh.results.map((freshRow) => {
  const dimension = freshRow.dimension ?? 0;
  const scheme = freshRow.dimension == null ? 'biozero_zk' : 'vanilla_zkbio';
  const latencyRows = dimension <= 32 && dimension !== 0 ? recoveredLow
    : dimension === 64 ? recovered64
      : recovered128;
  const latency = find(latencyRows, scheme, dimension);
  const gasScheme = freshRow.dimension == null ? 'biozero' : 'vanilla';
  const gasRows = freshRow.dimension == null ? recoveredGasBiozero
    : dimension === 128 ? recoveredGas128
      : recoveredGasLow;
  const gas = find(gasRows, gasScheme, dimension);
  return {
    target: freshRow.target,
    dimension: freshRow.dimension,
    constraints: delta(freshRow.constraint_count, Number(gas.constraints)),
    proof_mean_ms: delta(freshRow.proof_time.mean, Number(latency.prove_mean_ms)),
    proof_mean_bytes: delta(freshRow.proof_size.mean, Number(latency.proof_mean_bytes)),
    verifier_gas_mean: delta(freshRow.verifier_gas.mean, Number(gas.gas_mean)),
    deployment_gas: delta(freshRow.deployment_gas, Number(gas.deploy_gas)),
    verifier_bytecode_bytes: delta(freshRow.verifier_bytecode_bytes, Number(gas.verifier_bytecode_bytes)),
  };
});

const output = {
  schema_version: 1,
  interpretation: 'Fresh exact-split results are primary; the recovered complete 206160G campaign is retained as a separate comparison.',
  comparison,
};
fs.writeFileSync(path.join(outputRoot, 'fresh-vs-recovered.json'), `${JSON.stringify(output, null, 2)}\n`);
const metrics = [
  'constraints', 'proof_mean_ms', 'proof_mean_bytes', 'verifier_gas_mean',
  'deployment_gas', 'verifier_bytecode_bytes',
];
const csv = [['target', 'dimension', 'metric', 'fresh', 'recovered', 'absolute_delta', 'percent_delta']];
for (const entry of comparison) {
  for (const metric of metrics) {
    csv.push([
      entry.target,
      entry.dimension ?? '',
      metric,
      entry[metric].fresh,
      entry[metric].recovered,
      entry[metric].absolute_delta,
      entry[metric].percent_delta ?? '',
    ]);
  }
}
fs.writeFileSync(path.join(outputRoot, 'fresh-vs-recovered.csv'), `${csv.map((row) => row.join(',')).join('\n')}\n`);
