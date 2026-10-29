import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const logs = resolve(root, "logs", "complete");
const results = resolve(root, "results");
mkdirSync(logs, { recursive: true });
mkdirSync(results, { recursive: true });

const cases = [
  ["hom-complete", resolve(root, "scripts", "hom-complete-gas.mjs"), resolve(root, "build", "hom-complete-gas", "results.json")],
  ["circuit-complete", resolve(root, "scripts", "circuit-complete-gas.mjs"), resolve(root, "build", "circuit-complete-gas", "results.json")],
];
for (const [name, script, sourceResult] of cases) {
  process.stdout.write(`[complete] running ${name}\n`);
  const child = spawnSync(process.execPath, [script], { cwd: root, encoding: "utf8", maxBuffer: 64 * 2 ** 20 });
  writeFileSync(resolve(logs, `${name}.stdout.log`), child.stdout ?? "", "utf8");
  writeFileSync(resolve(logs, `${name}.stderr.log`), child.stderr ?? "", "utf8");
  if (child.error) throw child.error;
  if (child.status !== 0) throw new Error(`${name} exited with status ${child.status}; see logs/complete`);
  process.stdout.write(child.stdout ?? "");
  copyFileSync(sourceResult, resolve(results, `${name}.json`));
}

const hom = JSON.parse(readFileSync(resolve(results, "hom-complete.json"), "utf8"));
const circuit = JSON.parse(readFileSync(resolve(results, "circuit-complete.json"), "utf8"));
const rows = ["strategy,dimension,samples,repetitions,median_gas,calldata_bytes,enrollment_gas,deployment_gas,mandatory_controls_passed,tampered_response_control"];
for (const result of hom.results) {
  const controls = result.controls.replayRejected && result.controls.staleProofRejected && result.controls.wrongEnrollmentRejected;
  const tamper = result.controls.tamperedResponseRejected === null ? "not-run" : result.controls.tamperedResponseRejected;
  rows.push([result.label, hom.dimension, result.samples, result.repetitions, result.medianGasUsed, result.calldata.bytes, result.enrollmentGas, result.deploymentGas, controls, tamper].join(","));
}
for (const result of circuit.results) {
  const controls = Object.values(result.controls).every(Boolean);
  rows.push(["circuit-check", result.dimension, "", result.repetitions, result.medianGasUsed, result.calldata.bytes, result.enrollmentGas, result.deploymentGas, controls, "not-applicable"].join(","));
}
writeFileSync(resolve(results, "complete-gas-summary.csv"), `${rows.join("\n")}\n`, "utf8");
