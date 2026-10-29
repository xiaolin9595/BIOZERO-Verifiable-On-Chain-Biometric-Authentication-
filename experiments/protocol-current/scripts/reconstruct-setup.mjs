// Cross-platform, benchmark-only Circom/Groth16 build and setup.
// A fresh zkey and its matching Solidity verifier are always exported together.
import { randomBytes, createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const build = resolve(root, "build");
const logs = resolve(root, "logs", "setup");
const results = resolve(root, "results");
const node = process.execPath;
const circom = resolve(root, "node_modules", "circom2", "cli.js");
const snarkjs = resolve(root, "node_modules", "snarkjs", "build", "cli.cjs");
const fresh = process.argv.includes("--fresh");

if (fresh) rmSync(build, { recursive: true, force: true });
mkdirSync(build, { recursive: true });
mkdirSync(logs, { recursive: true });
mkdirSync(results, { recursive: true });

function run(label, executable, args) {
  process.stdout.write(`[setup] ${label}\n`);
  const child = spawnSync(executable, args, { cwd: root, encoding: "utf8", maxBuffer: 64 * 2 ** 20 });
  writeFileSync(resolve(logs, `${label}.stdout.log`), child.stdout ?? "", "utf8");
  writeFileSync(resolve(logs, `${label}.stderr.log`), child.stderr ?? "", "utf8");
  if (child.error) throw child.error;
  if (child.status !== 0) throw new Error(`${label} exited with status ${child.status}; see logs/setup`);
  return child.stdout ?? "";
}

const circuits = [
  {
    name: "threshold_standin",
    source: resolve(root, "circuits", "threshold_standin.circom"),
    circuitRoot: resolve(build, "hom-complete-gas"),
    setupRoot: resolve(build, "hom-complete-gas"),
    zkey: "ts_final.zkey",
    verifier: resolve(root, "contracts", "generated", "Groth16VerifierThreshold.sol"),
  },
  ...[128, 512].map((dimension) => ({
    name: `auth_distance_${dimension}`,
    source: resolve(root, "circuits", `auth_distance_${dimension}.circom`),
    circuitRoot: resolve(build, `auth_distance_${dimension}`),
    setupRoot: resolve(build, "proving", `auth_distance_${dimension}`),
    zkey: `auth_distance_${dimension}_benchmark_final.zkey`,
    verifier: resolve(root, "contracts", "generated", `Groth16Verifier${dimension}.sol`),
  })),
];

for (const circuit of circuits) {
  mkdirSync(circuit.circuitRoot, { recursive: true });
  mkdirSync(circuit.setupRoot, { recursive: true });
  run(`circom-${circuit.name}`, node, [circom, circuit.source, "--r1cs", "--wasm", "--sym", "--inspect", "--O2", "-l", resolve(root, "node_modules"), "-o", circuit.circuitRoot]);
  const info = run(`r1cs-info-${circuit.name}`, node, [snarkjs, "r1cs", "info", resolve(circuit.circuitRoot, `${circuit.name}.r1cs`)]);
  writeFileSync(resolve(circuit.circuitRoot, "r1cs-info.txt"), info, "utf8");
}

const ceremony = resolve(build, "proving", "local-benchmark-setup");
mkdirSync(ceremony, { recursive: true });
const pot0 = resolve(ceremony, "pot15_0000.ptau");
const pot1 = resolve(ceremony, "pot15_0001.ptau");
const potFinal = resolve(ceremony, "pot15_final.ptau");
run("pot-new", node, [snarkjs, "powersoftau", "new", "bn128", "15", pot0]);
run("pot-contribute", node, [snarkjs, "powersoftau", "contribute", pot0, pot1, "--name=BioZERO-reconstructed-phase1", `-e=${randomBytes(64).toString("hex")}`]);
run("pot-prepare", node, [snarkjs, "powersoftau", "prepare", "phase2", pot1, potFinal]);
run("pot-verify", node, [snarkjs, "powersoftau", "verify", potFinal]);

for (const circuit of circuits) {
  const r1cs = resolve(circuit.circuitRoot, `${circuit.name}.r1cs`);
  const zkey0 = resolve(circuit.setupRoot, `${circuit.name}_0000.zkey`);
  const zkeyFinal = resolve(circuit.setupRoot, circuit.zkey);
  const vkey = resolve(circuit.setupRoot, "verification_key.json");
  run(`groth16-setup-${circuit.name}`, node, [snarkjs, "groth16", "setup", r1cs, potFinal, zkey0]);
  run(`zkey-contribute-${circuit.name}`, node, [snarkjs, "zkey", "contribute", zkey0, zkeyFinal, `--name=BioZERO-reconstructed-${circuit.name}`, `-e=${randomBytes(64).toString("hex")}`]);
  run(`zkey-verify-${circuit.name}`, node, [snarkjs, "zkey", "verify", r1cs, potFinal, zkeyFinal]);
  run(`export-vkey-${circuit.name}`, node, [snarkjs, "zkey", "export", "verificationkey", zkeyFinal, vkey]);
  run(`export-solidity-${circuit.name}`, node, [snarkjs, "zkey", "export", "solidityverifier", zkeyFinal, circuit.verifier]);
}

function filesUnder(path) {
  return readdirSync(path, { withFileTypes: true }).flatMap((entry) => {
    const next = resolve(path, entry.name);
    if (entry.isDirectory()) return filesUnder(next);
    return entry.isFile() ? [next] : [];
  });
}
const manifestRoots = [resolve(root, "circuits"), resolve(root, "contracts", "generated"), build];
const manifest = manifestRoots.flatMap(filesUnder).filter((path) => !path.includes(`${resolve(root, "logs")}/`)).sort().map((path) => {
  const digest = createHash("sha256").update(readFileSync(path)).digest("hex");
  return `${digest}  ${relative(root, path)}`;
});
writeFileSync(resolve(results, "setup-artifacts.sha256"), `${manifest.join("\n")}\n`, "utf8");
writeFileSync(resolve(results, "setup-summary.json"), `${JSON.stringify({
  generatedAt: new Date().toISOString(),
  reconstructed: true,
  warning: "Fresh local single-party benchmark setup; never use these keys in production.",
  compiler: run("circom-version", node, [circom, "--version"]).trim().split("\n"),
  snarkjs: "0.7.6",
  node: process.version,
  power: 15,
  matchingSolidityVerifiersExported: circuits.map((circuit) => relative(root, circuit.verifier)),
  artifacts: circuits.map((circuit) => ({
    circuit: circuit.name,
    r1csBytes: statSync(resolve(circuit.circuitRoot, `${circuit.name}.r1cs`)).size,
    zkeyBytes: statSync(resolve(circuit.setupRoot, circuit.zkey)).size,
  })),
}, null, 2)}\n`, "utf8");
process.stdout.write("[setup] complete: fresh zkeys and matching Solidity verifiers exported\n");
