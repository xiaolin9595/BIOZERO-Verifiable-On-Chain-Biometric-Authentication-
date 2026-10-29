import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { ROOT } from "./config.mjs";

const stages = [
  ["inputs", "generate-inputs.mjs", []],
  ["setup", "setup.mjs", ["--fresh"]],
  ["proof benchmarks", "benchmark-proofs.mjs", []],
  ["bare verifier gas", "benchmark-verifier-gas.mjs", []],
  ["verification", "verify-results.mjs", []],
  ["manifest", "write-manifest.mjs", []],
];

for (const [label, script, args] of stages) {
  process.stdout.write(`[experiment] ${label}\n`);
  const child = spawnSync(process.execPath, [resolve(ROOT, "scripts", script), ...args], {
    cwd: ROOT,
    stdio: "inherit",
  });
  if (child.error) throw child.error;
  if (child.status !== 0) throw new Error(`${label} failed with exit status ${child.status}`);
}
process.stdout.write("[experiment] complete; results/verification.json and results/manifest.json are final gates\n");
