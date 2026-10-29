import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { DIMENSIONS, ETAS, REPETITIONS, buildGrid, sampleCount } from "./spotcheck_n_sweep_config.mjs";

const [runArgument, mode = "full"] = process.argv.slice(2);
if (!runArgument || !["full", "smoke"].includes(mode)) {
  throw new Error("usage: node verify_spotcheck_n_sweep.mjs RUN_ROOT [full|smoke]");
}
const runRoot = resolve(runArgument);
const resultPath = resolve(runRoot, "results", "spotcheck-n-sweep.json");
const csvPath = resolve(runRoot, "results", "spotcheck-n-sweep.csv");
const record = JSON.parse(await readFile(resultPath, "utf8"));
const checks = [];
function check(name, pass, detail) {
  const entry = { name, pass: Boolean(pass), detail };
  checks.push(entry);
  if (!entry.pass) throw new Error(`${name}: ${JSON.stringify(detail)}`);
}
const expected = mode === "full" ? buildGrid() : buildGrid([2], [1]);
check("schema version", record.schemaVersion === 1, record.schemaVersion);
check("execution mode", record.mode === mode, record.mode);
check("exact grid size", record.results?.length === expected.length, record.results?.length);
check("sampling library agreement", record.samplingAgreementWithProjectLibrary === true, record.samplingAgreementWithProjectLibrary);
check("proof timing provenance", /fresh snarkjs\.groth16\.fullProve/u.test(record.proofTimingPolicy), record.proofTimingPolicy);
check("saturation interpretation disclosed", record.uniqueDimensionSamplePairs === (mode === "full" ? 22 : 1) && /must not be interpreted as independent threshold evidence/u.test(record.interpretationWarning), { uniqueDimensionSamplePairs: record.uniqueDimensionSamplePairs, warning: record.interpretationWarning });
check("reused setup has four hashed artifacts", Object.keys(record.setupArtifacts ?? {}).length === 4 && Object.values(record.setupArtifacts).every((entry) => /^[0-9a-f]{64}$/u.test(entry.sha256) && entry.bytes > 0), record.setupArtifacts);
for (let index = 0; index < expected.length; index += 1) {
  const wanted = expected[index];
  const actual = record.results[index];
  check(`${wanted.label} identity and formula`, actual.dimension === wanted.dimension && actual.eta === wanted.eta && actual.samples === sampleCount(wanted.dimension, wanted.eta), actual);
  check(`${wanted.label} exactly three fresh mined authentications`, actual.repetitions === REPETITIONS && actual.authentications?.length === REPETITIONS && actual.gasUsed?.length === REPETITIONS, actual.authentications?.length);
  check(`${wanted.label} gas/calldata arrays`, actual.gasUsed.every((value) => Number.isInteger(value) && value > 21_000) && actual.calldataBytes?.length === REPETITIONS && actual.calldataGas?.length === REPETITIONS, { gas: actual.gasUsed, calldata: actual.calldataBytes });
  check(`${wanted.label} real separated prove timings`, actual.fullProveMilliseconds?.length === REPETITIONS && actual.fullProveMilliseconds.every((value) => Number.isFinite(value) && value > 0) && actual.transcriptConstructionMilliseconds?.every((value) => Number.isFinite(value) && value > 0) && actual.transcriptAndFullProveMilliseconds?.every((value, timingIndex) => value >= actual.fullProveMilliseconds[timingIndex]), { fullProve: actual.fullProveMilliseconds, transcript: actual.transcriptConstructionMilliseconds, complete: actual.transcriptAndFullProveMilliseconds });
  check(`${wanted.label} proof byte measurements`, actual.proofAbiBytes?.length === REPETITIONS && actual.proofAbiBytes.every((value) => value === 256) && actual.proofJsonBytes?.every((value) => Number.isInteger(value) && value > 0), { abi: actual.proofAbiBytes, json: actual.proofJsonBytes });
  check(`${wanted.label} fresh proof hashes`, actual.proofAbiSha256?.length === REPETITIONS && new Set(actual.proofAbiSha256).size === REPETITIONS && actual.proofAbiSha256.every((value) => /^[0-9a-f]{64}$/u.test(value)), actual.proofAbiSha256);
  check(`${wanted.label} enrollment/deployment`, Number.isInteger(actual.enrollmentGas) && actual.enrollmentGas > 0 && Number.isInteger(actual.deploymentGas) && actual.deploymentGas > 0, { enrollment: actual.enrollmentGas, deployment: actual.deploymentGas });
  check(`${wanted.label} actual creation/runtime bytecode`, actual.deployedBytecode?.creationTransaction?.bytes > 0 && /^[0-9a-f]{64}$/u.test(actual.deployedBytecode.creationTransaction.sha256) && actual.deployedBytecode?.runtime?.bytes > 0 && /^[0-9a-f]{64}$/u.test(actual.deployedBytecode.runtime.sha256), actual.deployedBytecode);
  check(`${wanted.label} transaction receipts`, actual.authentications.every((entry) => /^0x[0-9a-f]{64}$/u.test(entry.transactionHash) && Number.isInteger(entry.blockNumber) && entry.blockNumber > 0 && entry.status === 1), actual.authentications.map(({ transactionHash, blockNumber, status }) => ({ transactionHash, blockNumber, status })));
  check(`${wanted.label} mandatory negative controls`, ["replayRejected", "staleProofRejected", "wrongEnrollmentRejected", "tamperedResponseRejected"].every((name) => actual.controls?.[name] === true), actual.controls);
}
if (mode === "full") {
  check("exact N axis", JSON.stringify(record.dimensions) === JSON.stringify(DIMENSIONS), record.dimensions);
  check("exact four eta curves", JSON.stringify(record.etas) === JSON.stringify(ETAS), record.etas);
  for (const eta of ETAS) check(`eta=${eta} has seven N points`, record.results.filter((row) => row.eta === eta).length === DIMENSIONS.length, eta);
}
const allProofHashes = record.results.flatMap((row) => row.proofAbiSha256);
check("all mined authentications use distinct fresh proofs", new Set(allProofHashes).size === expected.length * REPETITIONS, { total: allProofHashes.length, unique: new Set(allProofHashes).size });
const sha256 = async (path) => createHash("sha256").update(await readFile(path)).digest("hex");
const verification = {
  generatedAt: new Date().toISOString(),
  overall: checks.every((entry) => entry.pass) ? "PASS" : "FAIL",
  mode,
  scope: mode === "full" ? "28 SpotCheck settings: N=[2,4,8,16,32,64,128], eta=[1,2,4,8], three fresh authentications each" : "N=2 eta=1 smoke setting",
  checks,
};
await writeFile(resolve(runRoot, "results", "verification.json"), `${JSON.stringify(verification, null, 2)}\n`, "utf8");
const artifacts = [
  ["results/spotcheck-n-sweep.json", resultPath],
  ["results/spotcheck-n-sweep.csv", csvPath],
  ["results/verification.json", resolve(runRoot, "results", "verification.json")],
  ["metadata/environment.txt", resolve(runRoot, "metadata", "environment.txt")],
  ["metadata/provenance.txt", resolve(runRoot, "metadata", "provenance.txt")],
  ["metadata/setup-artifacts.check.log", resolve(runRoot, "metadata", "setup-artifacts.check.log")],
];
const manifest = {
  generatedAt: new Date().toISOString(),
  mode,
  artifacts: await Promise.all(artifacts.map(async ([name, path]) => ({ name, sha256: await sha256(path) }))),
};
await writeFile(resolve(runRoot, "results", "manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
process.stdout.write(`verification=${verification.overall} checks=${checks.length} artifacts=${manifest.artifacts.length}\n`);
