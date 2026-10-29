#!/usr/bin/env bash
set -euo pipefail

root="${BIOZERO_REMOTE_ROOT:-$HOME/BioZero_remote}"
cache_root="${FIG3_CACHE_ROOT:-$root/cache-fig3-full-20261028}"
result_root="${FIG3_RESULT_ROOT:-$root/results/fig3_full_20261028}"
zokrates_bin="${BIOZERO_ZOKRATES_BIN:-$root/zokrates-0.8.8-linux/zokrates}"
output_root="$result_root/native-validation"
mkdir -p "$output_root"

targets=(
  "biozero-fixed:groth16_biozero"
  "vanilla-2:groth16_vanilla_2"
  "vanilla-4:groth16_vanilla_4"
  "vanilla-8:groth16_vanilla_8"
  "vanilla-16:groth16_vanilla_16"
  "vanilla-32:groth16_vanilla_32"
  "vanilla-64:groth16_vanilla_64"
  "vanilla-128:groth16_vanilla_128"
)

for entry in "${targets[@]}"; do
  label="${entry%%:*}"
  workspace_name="${entry#*:}"
  workspace="$cache_root/$workspace_name"
  target_output="$output_root/$label"
  mkdir -p "$target_output"

  "$zokrates_bin" inspect -i "$workspace/out" >"$target_output/inspect.log" 2>&1

  valid_status=0
  "$zokrates_bin" verify \
    -j "$workspace/proof.json" \
    -v "$workspace/verification.key" \
    >"$target_output/valid-verify.log" 2>&1 || valid_status=$?

  node - "$workspace/proof.json" "$target_output/invalid-proof.json" <<'NODE'
const fs = require('node:fs');
const [inputPath, outputPath] = process.argv.slice(2);
const proof = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
const original = String(proof.inputs[0]);
const next = BigInt(original) + 1n;
proof.inputs[0] = original.startsWith('0x')
  ? `0x${next.toString(16).padStart(original.length - 2, '0')}`
  : next.toString();
fs.writeFileSync(outputPath, `${JSON.stringify(proof, null, 2)}\n`);
NODE

  invalid_status=0
  "$zokrates_bin" verify \
    -j "$target_output/invalid-proof.json" \
    -v "$workspace/verification.key" \
    >"$target_output/invalid-verify.log" 2>&1 || invalid_status=$?

  "$zokrates_bin" export-verifier \
    -i "$workspace/verification.key" \
    -o "$target_output/verifier.fresh.sol" \
    >"$target_output/export-verifier.log" 2>&1
  export_match=false
  if cmp -s "$workspace/verifier.sol" "$target_output/verifier.fresh.sol"; then
    export_match=true
  fi

  node - "$label" "$workspace" "$target_output" "$valid_status" "$invalid_status" "$export_match" <<'NODE'
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const [label, workspace, output, validStatusText, invalidStatusText, exportMatchText] = process.argv.slice(2);
const read = (name) => fs.readFileSync(path.join(output, name), 'utf8');
const digest = (filePath) => crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex');
const inspect = read('inspect.log');
const validLog = read('valid-verify.log');
const invalidLog = read('invalid-verify.log');
const constraintsMatch = inspect.match(/constraint_count\s*[:=]\s*([0-9]+)/i)
  ?? inspect.match(/constraints?\s*[:=]\s*([0-9]+)/i)
  ?? inspect.match(/([0-9]+)\s+constraints?/i);
const result = {
  schema_version: 1,
  target: label,
  workspace,
  constraint_count: constraintsMatch ? Number(constraintsMatch[1]) : null,
  valid_proof: {
    exit_status: Number(validStatusText),
    accepted: Number(validStatusText) === 0 && /PASSED/i.test(validLog),
    log: path.join(output, 'valid-verify.log'),
  },
  invalid_public_input_control: {
    mutation: 'public inputs[0] += 1; proof group elements unchanged',
    exit_status: Number(invalidStatusText),
    rejected: /FAILED/i.test(invalidLog) || Number(invalidStatusText) !== 0,
    log: path.join(output, 'invalid-verify.log'),
  },
  matching_verifier: {
    exported_from_same_verification_key: true,
    byte_exact_match_with_cached_verifier: exportMatchText === 'true',
    cached_sha256: digest(path.join(workspace, 'verifier.sol')),
    fresh_sha256: digest(path.join(output, 'verifier.fresh.sol')),
  },
  artifact_hashes: {
    proof_sha256: digest(path.join(workspace, 'proof.json')),
    verification_key_sha256: digest(path.join(workspace, 'verification.key')),
    fixed_source_sha256: digest(path.join(workspace, 'main.zok')),
  },
};
result.overall = result.valid_proof.accepted
  && result.invalid_public_input_control.rejected
  && result.matching_verifier.byte_exact_match_with_cached_verifier
  ? 'PASS'
  : 'FAIL';
fs.writeFileSync(path.join(output, 'validation.json'), `${JSON.stringify(result, null, 2)}\n`);
if (result.overall !== 'PASS') process.exitCode = 1;
NODE
done

node - "$output_root" <<'NODE'
const fs = require('node:fs');
const path = require('node:path');
const root = process.argv[2];
const entries = fs.readdirSync(root, { withFileTypes: true })
  .filter((entry) => entry.isDirectory())
  .map((entry) => JSON.parse(fs.readFileSync(path.join(root, entry.name, 'validation.json'), 'utf8')))
  .sort((left, right) => (left.constraint_count ?? 0) - (right.constraint_count ?? 0));
const summary = {
  schema_version: 1,
  overall: entries.every((entry) => entry.overall === 'PASS') ? 'PASS' : 'FAIL',
  targets: entries,
};
fs.writeFileSync(path.join(root, 'summary.json'), `${JSON.stringify(summary, null, 2)}\n`);
if (summary.overall !== 'PASS') process.exitCode = 1;
NODE

