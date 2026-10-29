import { spawnSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const circom = resolve(root, "node_modules", "circom2", "cli.js");
const snarkjs = resolve(root, "node_modules", "snarkjs", "build", "cli.cjs");
const build = resolve(root, "build", "reconstructed-ablation");
const logs = resolve(root, "logs", "reconstructed-ablation");
mkdirSync(build, { recursive: true });
mkdirSync(logs, { recursive: true });

function run(label, args) {
  const child = spawnSync(process.execPath, args, { cwd: root, encoding: "utf8", maxBuffer: 64 * 2 ** 20 });
  writeFileSync(resolve(logs, `${label}.stdout.log`), child.stdout ?? "", "utf8");
  writeFileSync(resolve(logs, `${label}.stderr.log`), child.stderr ?? "", "utf8");
  if (child.error) throw child.error;
  if (child.status !== 0) throw new Error(`${label} exited with status ${child.status}`);
  return child.stdout ?? "";
}

const packedConstraints = { 128: 7660, 512: 27118 };
const results = [];
for (const dimension of [128, 512]) {
  const name = `auth_distance_${dimension}_unpacked`;
  const caseRoot = resolve(build, name);
  mkdirSync(caseRoot, { recursive: true });
  run(`circom-${name}`, [circom, resolve(root, "circuits", "reconstructed", `${name}.circom`), "--r1cs", "--wasm", "--sym", "--inspect", "--O2", "-l", resolve(root, "node_modules"), "-o", caseRoot]);
  const r1cs = resolve(caseRoot, `${name}.r1cs`);
  const info = run(`r1cs-info-${name}`, [snarkjs, "r1cs", "info", r1cs]);
  const constraints = Number(info.match(/# of Constraints:\s+(\d+)/)?.[1]);
  const witness = resolve(caseRoot, `${name}.wtns`);
  run(`witness-${name}`, [snarkjs, "wtns", "calculate", resolve(caseRoot, `${name}_js`, `${name}.wasm`), resolve(root, "inputs", "generated", `${name}.json`), witness]);
  run(`witness-check-${name}`, [snarkjs, "wtns", "check", r1cs, witness]);
  results.push({
    circuit: name,
    dimension,
    provenance: "reconstructed wrapper; not recovered original source",
    constraints,
    packedConstraints: packedConstraints[dimension],
    packedReductionPercent: Number((100 * (1 - packedConstraints[dimension] / constraints)).toFixed(1)),
    witnessChecked: true,
  });
}
writeFileSync(resolve(root, "results", "reconstructed-unpacked-ablation.json"), `${JSON.stringify({
  generatedAt: new Date().toISOString(),
  status: "reconstructed, not an authenticated recovery of the missing original wrappers",
  omitted: [
    "distance_only_128.circom: design choices are not uniquely determined by the delivered source",
    "distance_only_512.circom: design choices are not uniquely determined by the delivered source",
  ],
  results,
}, null, 2)}\n`, "utf8");
writeFileSync(resolve(root, "results", "reconstructed-unpacked-ablation.csv"), `${[
  "circuit,dimension,constraints,packed_constraints,packed_reduction_percent,witness_checked,provenance",
  ...results.map((result) => [result.circuit, result.dimension, result.constraints, result.packedConstraints, result.packedReductionPercent, result.witnessChecked, result.provenance].join(",")),
].join("\n")}\n`, "utf8");
