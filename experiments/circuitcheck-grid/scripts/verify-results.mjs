import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import {
  DIMENSIONS,
  EIP170_RUNTIME_LIMIT_BYTES,
  PUBLIC_INPUTS,
  ROOT,
  circuitParameters,
} from "./config.mjs";
import { sha256, writeJson } from "./lib/audit.mjs";
import { pathsFor } from "./lib/paths.mjs";

const readJson = async (path) => JSON.parse(await readFile(resolve(ROOT, path), "utf8"));
const [inputs, setup, proving, gas] = await Promise.all([
  readJson("results/inputs.json"),
  readJson("results/setup.json"),
  readJson("results/proving.json"),
  readJson("results/verifier-gas.json"),
]);
const checks = [];
function check(name, condition, detail) {
  const record = { name, pass: Boolean(condition), detail };
  checks.push(record);
  if (!record.pass) throw new Error(`${name}: ${JSON.stringify(detail)}`);
}
const exactGrid = (values) => JSON.stringify(values) === JSON.stringify(DIMENSIONS);
check("input grid is complete", exactGrid(inputs.dimensions), inputs.dimensions);
check("setup grid is complete", exactGrid(setup.dimensions), setup.dimensions);
check("proving grid is complete", exactGrid(proving.dimensions), proving.dimensions);
check("gas grid is complete", exactGrid(gas.dimensions), gas.dimensions);
check("one setup artifact per dimension", setup.artifacts.length === DIMENSIONS.length, setup.artifacts.length);
check("one proving row per dimension", proving.results.length === DIMENSIONS.length, proving.results.length);
check("one gas row per dimension", gas.results.length === DIMENSIONS.length, gas.results.length);

for (const dimension of DIMENSIONS) {
  const paths = pathsFor(dimension);
  const parameters = circuitParameters(dimension);
  const source = await readFile(paths.source, "utf8");
  check(`N=${dimension} entry parameters`, source.includes(
    `AuthDistance(${dimension}, 16, 65535, 15, ${parameters.blocks}, ${parameters.paddedBlocks}, 48)`,
  ), parameters);
  const setupRow = setup.artifacts.find((row) => row.dimension === dimension);
  check(`N=${dimension} setup artifact present`, setupRow != null, setup.artifacts.map((row) => row.dimension));
  check(`N=${dimension} zkey hash current`, setupRow.zkeySha256 === await sha256(paths.zkey), setupRow.zkeySha256);
  check(`N=${dimension} verification key hash current`, setupRow.verificationKeySha256 === await sha256(paths.vkey), setupRow.verificationKeySha256);
  check(`N=${dimension} matching verifier hash current`, setupRow.solidityVerifierSha256 === await sha256(paths.verifier), setupRow.solidityVerifierSha256);

  const proofRow = proving.results.find((row) => row.dimension === dimension);
  check(`N=${dimension} proof protocol`, proofRow.warmups === 1 && proofRow.repetitions === 10, { warmups: proofRow.warmups, repetitions: proofRow.repetitions });
  check(`N=${dimension} five public inputs`, proofRow.publicInputs === PUBLIC_INPUTS, proofRow.publicInputs);
  check(`N=${dimension} ten end-to-end proving samples`, proofRow.provingPipeline.samples === 10 && proofRow.provingPipeline.endToEndMs.samples === 10, proofRow.provingPipeline);
  check(`N=${dimension} proving distributions complete`, ["mean", "sampleStandardDeviation", "median"].every((key) => Number.isFinite(proofRow.provingPipeline.endToEndMs[key])), proofRow.provingPipeline.endToEndMs);
  check(`N=${dimension} GNU time RSS captured`, proofRow.provingPipeline.externalGnuTimeMaxRssMiB.available === true && proofRow.provingPipeline.externalGnuTimeMaxRssMiB.samples === 10, proofRow.provingPipeline.externalGnuTimeMaxRssMiB);
  check(`N=${dimension} ten native proof verifications`, proofRow.verification.elapsedMs.samples === 10, proofRow.verification);
  check(`N=${dimension} all native proof verifications pass`, proofRow.verification.allVerified === true, proofRow.verification);
  check(`N=${dimension} proving zkey matches setup`, proofRow.artifacts.zkeySha256 === setupRow.zkeySha256, proofRow.artifacts.zkeySha256);

  const gasRow = gas.results.find((row) => row.dimension === dimension);
  const raw = await readJson(gasRow.raw);
  check(`N=${dimension} bare verifier gas complete`, gasRow.validVerifyGas.length === 5, gasRow.validVerifyGas);
  check(`N=${dimension} valid public inputs return true`, gasRow.validStaticReturn === true, gasRow.validStaticReturn);
  check(`N=${dimension} invalid public input returns false`, gasRow.invalidStaticReturn === false, gasRow.invalidStaticReturn);
  check(`N=${dimension} raw receipt protocol`, raw.validControl.warmupTransactions.length === 1 && raw.validControl.measuredTransactions.length === 5, { warmups: raw.validControl.warmupTransactions.length, measured: raw.validControl.measuredTransactions.length });
  check(`N=${dimension} gas uses independent proofs`, new Set(raw.validControl.measuredTransactions.map((row) => row.proofMaterial.proofSha256)).size === 5
    && raw.validControl.warmupTransactions[0].proofMaterial.phase === "warmup"
    && raw.validControl.measuredTransactions.every((row, index) => row.proofMaterial.phase === "measured" && row.proofMaterial.run === index + 1), raw.validControl.measuredTransactions.map((row) => row.proofMaterial));
  check(`N=${dimension} all gas proof calls static-true`, raw.validControl.staticReturns.length === 6 && raw.validControl.staticReturns.every((value) => value === true), raw.validControl.staticReturns);
  check(`N=${dimension} receipts successful`, raw.deployment.status === 1 && raw.validControl.measuredTransactions.every((row) => row.status === 1), raw.acceptance);
  check(`N=${dimension} runtime matches compiler`, gasRow.runtimeMatchesCompiler === true, raw.bytecode);
  check(`N=${dimension} EIP-170`, gasRow.eip170Compliant === true && gasRow.runtimeBytecodeBytes <= EIP170_RUNTIME_LIMIT_BYTES, { runtimeBytes: gasRow.runtimeBytecodeBytes, limit: EIP170_RUNTIME_LIMIT_BYTES });
  check(`N=${dimension} raw evidence hash current`, gasRow.rawSha256 === await sha256(resolve(ROOT, gasRow.raw)), gasRow.rawSha256);
}

const report = {
  schemaVersion: 1,
  generatedAt: new Date().toISOString(),
  overall: checks.every((entry) => entry.pass) ? "PASS" : "FAIL",
  checkCount: checks.length,
  checks,
};
await writeJson(resolve(ROOT, "results", "verification.json"), report);
process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
