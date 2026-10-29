import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const readJson = (path) => JSON.parse(readFileSync(resolve(root, path), "utf8"));
const checks = [];
const check = (name, condition, detail) => {
  checks.push({ name, pass: Boolean(condition), detail });
  if (!condition) throw new Error(`${name}: ${detail}`);
};

const setup = readJson("results/setup-summary.json");
const hom = readJson("results/hom-complete.json");
const circuit = readJson("results/circuit-complete.json");
const packed = readJson("results/packed-proving.json");
const ablation = readJson("results/reconstructed-unpacked-ablation.json");
check("fresh setup labelled reconstructed", setup.reconstructed === true, setup.warning);
check("three matching verifiers exported", setup.matchingSolidityVerifiersExported.length === 3, setup.matchingSolidityVerifiersExported);
check("Full/Spot cases complete", hom.results.length === 5 && hom.results.every((row) => row.repetitions === 3 && row.gasUsed.length === 3), "five cases, three transactions each");
check("Full/Spot mandatory controls pass", hom.results.every((row) => row.controls.replayRejected && row.controls.staleProofRejected && row.controls.wrongEnrollmentRejected && row.controls.tamperedResponseRejected !== false), "sampled tamper remains untested/null by original harness");
check("CircuitCheck cases complete", circuit.results.length === 2 && circuit.results.every((row) => row.repetitions === 3 && row.gasUsed.length === 3), "N=128/512, three transactions each");
check("CircuitCheck controls pass", circuit.results.every((row) => Object.values(row.controls).every(Boolean)), "replay and wrong-nonce proofs rejected");
check("packed five-run protocol", packed.results.length === 2 && packed.results.every((row) => row.repetitions === 5 && row.proof.elapsedMs.length === 5), "five cold child processes per N");
check("packed proof verifications pass", [128, 512].every((dimension) => Array.from({ length: 5 }, (_, index) => readJson(`results/packed-proving/auth_distance_${dimension}-run-${String(index + 1).padStart(2, "0")}-verify-metrics.json`).verified).every(Boolean)), "ten verification operations returned true");
check("reconstructed unpacked witnesses pass", ablation.results.length === 2 && ablation.results.every((row) => row.witnessChecked), "only uniquely inferable unpacked wrappers reconstructed");
check("distance-only circuits not guessed", ablation.omitted.length === 2, ablation.omitted);

const digest = (path) => createHash("sha256").update(readFileSync(resolve(root, path))).digest("hex");
const artifactHashes = [
  "contracts/generated/Groth16VerifierThreshold.sol", "contracts/generated/Groth16Verifier128.sol", "contracts/generated/Groth16Verifier512.sol",
  "build/hom-complete-gas/ts_final.zkey", "build/proving/auth_distance_128/auth_distance_128_benchmark_final.zkey", "build/proving/auth_distance_512/auth_distance_512_benchmark_final.zkey",
].map((path) => ({ path, sha256: digest(path) }));
const report = { overall: checks.every((item) => item.pass) ? "PASS" : "FAIL", checks, artifactHashes };
const serialized = `${JSON.stringify(report, null, 2)}\n`;
const verificationPath = resolve(root, "results", "verification.json");
let previous = null;
try {
  previous = readFileSync(verificationPath, "utf8");
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}
// Keep self-checks idempotent: identical evidence must not rewrite the file or
// invalidate the evidence manifest merely because the check was run again.
if (previous !== serialized) writeFileSync(verificationPath, serialized, "utf8");
process.stdout.write(serialized);
