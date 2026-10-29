// Fresh benchmark-only Circom/Groth16 setup for the seven-size grid.
import { randomBytes } from "node:crypto";
import { spawnSync } from "node:child_process";
import { mkdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { relative, resolve, sep } from "node:path";
import { ROOT, selectedDimensions } from "./config.mjs";
import { parseR1csInfo, sha256, writeJson } from "./lib/audit.mjs";
import { pathsFor } from "./lib/paths.mjs";

const dimensions = selectedDimensions();
const compileOnly = process.argv.includes("--compile-only");
const fresh = process.argv.includes("--fresh");
const build = resolve(ROOT, "build");
const setupLogs = resolve(ROOT, "logs", "setup");
const generatedContracts = resolve(ROOT, "contracts", "generated");
const node = process.execPath;
const circom = resolve(ROOT, "node_modules", "circom2", "cli.js");
const snarkjs = resolve(ROOT, "node_modules", "snarkjs", "build", "cli.cjs");

function resetOwnedDirectory(path) {
  const relativePath = relative(ROOT, path);
  if (!relativePath || relativePath.startsWith(`..${sep}`) || relativePath === "..") {
    throw new Error(`refusing to remove path outside experiment root: ${path}`);
  }
  rmSync(path, { recursive: true, force: true });
}

if (fresh) {
  resetOwnedDirectory(build);
  resetOwnedDirectory(setupLogs);
  resetOwnedDirectory(generatedContracts);
}
[build, setupLogs, generatedContracts, resolve(ROOT, "results")].forEach((path) => (
  mkdirSync(path, { recursive: true })
));

function run(label, executable, args) {
  process.stdout.write(`[setup] ${label}\n`);
  const child = spawnSync(executable, args, {
    cwd: ROOT,
    encoding: "utf8",
    maxBuffer: 128 * 2 ** 20,
  });
  writeFileSync(resolve(setupLogs, `${label}.stdout.log`), child.stdout ?? "", "utf8");
  writeFileSync(resolve(setupLogs, `${label}.stderr.log`), child.stderr ?? "", "utf8");
  if (child.error) throw child.error;
  if (child.status !== 0) {
    throw new Error(`${label} exited with ${child.status}; inspect logs/setup/${label}.*.log`);
  }
  return child.stdout ?? "";
}

const compiled = [];
for (const dimension of dimensions) {
  const paths = pathsFor(dimension);
  mkdirSync(paths.circuitBuild, { recursive: true });
  run(`circom-${paths.name}`, node, [
    circom,
    paths.source,
    "--r1cs",
    "--wasm",
    "--sym",
    "--inspect",
    "--O2",
    "-l",
    resolve(ROOT, "node_modules"),
    "-o",
    paths.circuitBuild,
  ]);
  const info = run(`r1cs-info-${paths.name}`, node, [snarkjs, "r1cs", "info", paths.r1cs]);
  writeFileSync(resolve(paths.circuitBuild, "r1cs-info.txt"), info, "utf8");
  compiled.push({
    dimension,
    circuit: paths.name,
    constraints: parseR1csInfo(info),
    r1csBytes: statSync(paths.r1cs).size,
    r1csSha256: await sha256(paths.r1cs),
    wasmBytes: statSync(paths.wasm).size,
    wasmSha256: await sha256(paths.wasm),
    sourceSha256: await sha256(paths.source),
  });
}

if (compileOnly) {
  for (const record of compiled) {
    const paths = pathsFor(record.dimension);
    const witness = resolve(paths.circuitBuild, `${paths.name}-smoke.wtns`);
    run(`witness-${paths.name}`, node, [snarkjs, "wtns", "calculate", paths.wasm, paths.input, witness]);
    run(`witness-check-${paths.name}`, node, [snarkjs, "wtns", "check", paths.r1cs, witness]);
    record.witnessChecked = true;
    record.witnessSha256 = await sha256(witness);
  }
  await writeJson(resolve(ROOT, "results", "compile-smoke.json"), {
    generatedAt: new Date().toISOString(),
    status: "compile and witness-check only; no powers-of-tau, zkeys, proofs, or gas measurements were generated",
    dimensions,
    compiler: run("circom-version", node, [circom, "--version"]).trim().split("\n"),
    compiled,
  });
  process.stdout.write("[setup] compile-only complete\n");
  process.exit(0);
}

const ceremony = resolve(build, "ceremony");
mkdirSync(ceremony, { recursive: true });
const pot0 = resolve(ceremony, "pot15_0000.ptau");
const pot1 = resolve(ceremony, "pot15_0001.ptau");
const potFinal = resolve(ceremony, "pot15_final.ptau");
run("pot-new", node, [snarkjs, "powersoftau", "new", "bn128", "15", pot0]);
run("pot-contribute", node, [
  snarkjs,
  "powersoftau",
  "contribute",
  pot0,
  pot1,
  "--name=BioZERO-CircuitCheck-grid-phase1",
  `-e=${randomBytes(64).toString("hex")}`,
]);
run("pot-prepare", node, [snarkjs, "powersoftau", "prepare", "phase2", pot1, potFinal]);
run("pot-verify", node, [snarkjs, "powersoftau", "verify", potFinal]);

const artifacts = [];
for (const dimension of dimensions) {
  const paths = pathsFor(dimension);
  mkdirSync(paths.provingBuild, { recursive: true });
  run(`groth16-setup-${paths.name}`, node, [snarkjs, "groth16", "setup", paths.r1cs, potFinal, paths.zkey0]);
  run(`zkey-contribute-${paths.name}`, node, [
    snarkjs,
    "zkey",
    "contribute",
    paths.zkey0,
    paths.zkey,
    `--name=BioZERO-CircuitCheck-grid-${paths.name}`,
    `-e=${randomBytes(64).toString("hex")}`,
  ]);
  run(`zkey-verify-${paths.name}`, node, [snarkjs, "zkey", "verify", paths.r1cs, potFinal, paths.zkey]);
  run(`export-vkey-${paths.name}`, node, [snarkjs, "zkey", "export", "verificationkey", paths.zkey, paths.vkey]);
  run(`export-solidity-${paths.name}`, node, [snarkjs, "zkey", "export", "solidityverifier", paths.zkey, paths.verifier]);
  artifacts.push({
    dimension,
    circuit: paths.name,
    zkey: relative(ROOT, paths.zkey),
    zkeyBytes: statSync(paths.zkey).size,
    zkeySha256: await sha256(paths.zkey),
    verificationKey: relative(ROOT, paths.vkey),
    verificationKeySha256: await sha256(paths.vkey),
    solidityVerifier: relative(ROOT, paths.verifier),
    solidityVerifierSha256: await sha256(paths.verifier),
  });
}

await writeJson(resolve(ROOT, "results", "setup.json"), {
  generatedAt: new Date().toISOString(),
  status: "fresh local single-party benchmark setup; never use these keys in production",
  dimensions,
  power: 15,
  entropy: "operating-system random entropy; secret contribution values are intentionally not recorded",
  toolchain: {
    node: process.version,
    circom: run("circom-version", node, [circom, "--version"]).trim().split("\n"),
    snarkjs: "0.7.6",
  },
  sharedSource: {
    path: "circuits/auth_distance.circom",
    sha256: await sha256(resolve(ROOT, "circuits", "auth_distance.circom")),
    provenance: "copied from reconstructed/current then made self-contained for remote single-directory execution",
  },
  ptau: {
    path: relative(ROOT, potFinal),
    bytes: statSync(potFinal).size,
    sha256: await sha256(potFinal),
  },
  compiled,
  artifacts,
});
process.stdout.write("[setup] complete: seven fresh zkeys and matching Solidity verifiers exported\n");
