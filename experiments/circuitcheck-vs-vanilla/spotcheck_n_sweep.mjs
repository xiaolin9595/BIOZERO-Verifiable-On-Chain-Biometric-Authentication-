import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { basename, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { buildBn128 } from "ffjavascript";
import ganache from "ganache";
import solc from "solc";
import { ethers } from "ethers";
import * as snarkjs from "snarkjs";
import {
  DIMENSIONS,
  ETAS,
  REPETITIONS,
  buildGrid,
  csvCell,
  median,
  sampleCount,
} from "./spotcheck_n_sweep_config.mjs";

const [projectArgument, outputArgument, mode = "full"] = process.argv.slice(2);
if (!projectArgument || !outputArgument || !["full", "smoke"].includes(mode)) {
  throw new Error("usage: node spotcheck_n_sweep.mjs PROJECT_ROOT OUTPUT_ROOT [full|smoke]");
}
const projectRoot = resolve(projectArgument);
const outputRoot = resolve(outputArgument);
const thresholdRoot = resolve(projectRoot, "build", "hom-complete-gas");
const wasm = resolve(thresholdRoot, "threshold_standin_js", "threshold_standin.wasm");
const zkey = resolve(thresholdRoot, "ts_final.zkey");
const TAU = 1_000_000n;
const H_DLOG = 5n;
const selectedGrid = mode === "smoke" ? buildGrid([2], [1]) : buildGrid();

const mod = (a, m) => ((a % m) + m) % m;
const sha256 = (value) => createHash("sha256").update(value).digest("hex");
let counter = 0n;
function rand(bound) {
  counter += 1n;
  return mod(BigInt(`0x${sha256(`biozero-spotcheck-n-sweep-v1/${counter}`)}`), bound);
}

function calldataCost(hex) {
  const bytes = ethers.utils.arrayify(hex);
  let zeroBytes = 0;
  for (const byte of bytes) if (byte === 0) zeroBytes += 1;
  const nonzeroBytes = bytes.length - zeroBytes;
  return { bytes: bytes.length, zeroBytes, nonzeroBytes, gas: zeroBytes * 4 + nonzeroBytes * 16 };
}

async function fileRecord(path) {
  const content = await readFile(path);
  return { path, bytes: content.length, sha256: sha256(content) };
}

async function compile() {
  const sourceNames = ["HomomorphicCompleteVerifier.sol", "generated/Groth16VerifierThreshold.sol"];
  const sources = {};
  for (const name of sourceNames) {
    sources[name] = { content: await readFile(resolve(projectRoot, "contracts", name), "utf8") };
  }
  const input = {
    language: "Solidity",
    sources,
    settings: {
      optimizer: { enabled: true, runs: 200 },
      evmVersion: "shanghai",
      outputSelection: { "*": { "*": ["abi", "evm.bytecode.object", "evm.deployedBytecode.object"] } },
    },
  };
  const output = JSON.parse(solc.compile(JSON.stringify(input)));
  const errors = (output.errors ?? []).filter((entry) => entry.severity === "error");
  if (errors.length > 0) throw new Error(errors.map((entry) => entry.formattedMessage).join("\n"));
  return {
    verifier: output.contracts["HomomorphicCompleteVerifier.sol"].HomomorphicCompleteVerifier,
    groth16: output.contracts["generated/Groth16VerifierThreshold.sol"].Groth16Verifier,
  };
}

function bytecodeRecord(contract) {
  const creation = contract.evm.bytecode.object;
  const runtime = contract.evm.deployedBytecode.object;
  return {
    creation: { bytes: creation.length / 2, sha256: sha256(Buffer.from(creation, "hex")) },
    runtime: { bytes: runtime.length / 2, sha256: sha256(Buffer.from(runtime, "hex")) },
  };
}

const curve = await buildBn128();
const r = curve.r;
const point = (scalar) => {
  const normalized = mod(scalar, r);
  if (normalized === 0n) return { x: "0", y: "0" };
  const [x, y] = curve.G1.toObject(curve.G1.toAffine(curve.G1.timesScalar(curve.G1.one, normalized)));
  return { x: x.toString(), y: y.toString() };
};
const commitment = (message, blind) => mod(message + H_DLOG * blind, r);
const pointArray = "tuple(uint256 x,uint256 y)[]";

function challenge(ctxHash, id, nonce, transcript) {
  const points = (items) => items.map((item) => [item.x, item.y]);
  const h1 = ethers.utils.keccak256(ethers.utils.defaultAbiCoder.encode(
    ["bytes32", "uint256", "uint256", pointArray, pointArray, pointArray],
    [ctxHash, id, nonce, points(transcript.ce), points(transcript.cp), points(transcript.cee)],
  ));
  return mod(BigInt(ethers.utils.keccak256(ethers.utils.defaultAbiCoder.encode(
    ["bytes32", pointArray, pointArray, pointArray, pointArray],
    [h1, points(transcript.cpp), points(transcript.cep), points(transcript.alpha), points(transcript.beta)],
  ))), r);
}

function createEnrollment(dimension) {
  const template = Array.from({ length: dimension }, () => rand(1n << 16n));
  const blinds = Array.from({ length: dimension }, () => rand(r));
  const scalars = template.map((message, index) => commitment(message, blinds[index]));
  return { template, blinds, scalars, points: scalars.map(point) };
}

async function prove(ctxHash, id, nonce, enrollment) {
  const transcriptStart = process.hrtime.bigint();
  const { template, blinds, scalars, points: ce } = enrollment;
  const dimension = template.length;
  const probe = template.map((message) => {
    const value = message + rand(101n) - 50n;
    return value < 0n ? 0n : value >= 1n << 16n ? (1n << 16n) - 1n : value;
  });
  const rhoP = probe.map(() => rand(r));
  const rhoEE = probe.map(() => rand(r));
  const rhoPP = probe.map(() => rand(r));
  const rhoEP = probe.map(() => rand(r));
  const cpS = probe.map((message, index) => commitment(message, rhoP[index]));
  const ceeS = template.map((message, index) => commitment(message * message, rhoEE[index]));
  const cppS = probe.map((message, index) => commitment(message * message, rhoPP[index]));
  const cepS = template.map((message, index) => commitment(message * probe[index], rhoEP[index]));
  const relation = (index) => [
    [template[index], blinds[index], scalars[index], blinds[index], rhoEE[index]],
    [probe[index], rhoP[index], cpS[index], rhoP[index], rhoPP[index]],
    [probe[index], rhoP[index], scalars[index], blinds[index], rhoEP[index]],
  ];
  const masks = [];
  const alpha = [];
  const beta = [];
  for (let index = 0; index < dimension; index += 1) {
    for (const [, , baseScalar] of relation(index)) {
      const values = [rand(r), rand(r), rand(r)];
      masks.push(values);
      alpha.push(point(commitment(values[0], values[1])));
      beta.push(point(mod(values[0] * baseScalar + H_DLOG * values[2], r)));
    }
  }
  const transcript = {
    ce,
    cp: cpS.map(point),
    cee: ceeS.map(point),
    cpp: cppS.map(point),
    cep: cepS.map(point),
    alpha,
    beta,
  };
  const epsilon = challenge(ctxHash, id, nonce, transcript);
  const z = [];
  for (let index = 0; index < dimension; index += 1) {
    relation(index).forEach(([message, anchorBlind, , baseBlind, targetBlind], relationIndex) => {
      const [b1, b2, b3] = masks[3 * index + relationIndex];
      z.push(
        mod(b1 + epsilon * message, r),
        mod(b2 + epsilon * anchorBlind, r),
        mod(b3 + epsilon * (targetBlind - baseBlind * message), r),
      );
    });
  }
  let distanceScalar = 0n;
  let delta = 0n;
  for (let index = 0; index < dimension; index += 1) {
    distanceScalar = mod(distanceScalar + ceeS[index] + cppS[index] - 2n * cepS[index], r);
    delta += (template[index] - probe[index]) ** 2n;
  }
  const distance = point(distanceScalar);
  const low = (value) => (BigInt(value) & ((1n << 128n) - 1n)).toString();
  const high = (value) => (BigInt(value) >> 128n).toString();
  const fullProveStart = process.hrtime.bigint();
  const { proof } = await snarkjs.groth16.fullProve({
    cxHi: high(distance.x),
    cxLo: low(distance.x),
    cyHi: high(distance.y),
    cyLo: low(distance.y),
    tau: TAU.toString(),
    delta: delta.toString(),
  }, wasm, zkey);
  const fullProveEnd = process.hrtime.bigint();
  const pA = [proof.pi_a[0], proof.pi_a[1]];
  const pB = [[proof.pi_b[0][1], proof.pi_b[0][0]], [proof.pi_b[1][1], proof.pi_b[1][0]]];
  const pC = [proof.pi_c[0], proof.pi_c[1]];
  const transcriptAndFullProveMilliseconds = Number(fullProveEnd - transcriptStart) / 1e6;
  const fullProveMilliseconds = Number(fullProveEnd - fullProveStart) / 1e6;
  const transcriptConstructionMilliseconds = Number(fullProveStart - transcriptStart) / 1e6;
  const proofAbi = ethers.utils.defaultAbiCoder.encode(
    ["uint256[2]", "uint256[2][2]", "uint256[2]"],
    [pA, pB, pC],
  );
  return {
    ...transcript,
    z: z.map(String),
    pA,
    pB,
    pC,
    delta: delta.toString(),
    measurement: {
      fullProveMilliseconds,
      transcriptConstructionMilliseconds,
      transcriptAndFullProveMilliseconds,
      proofAbiBytes: ethers.utils.arrayify(proofAbi).length,
      proofAbiSha256: sha256(Buffer.from(ethers.utils.arrayify(proofAbi))),
      proofJsonBytes: Buffer.byteLength(JSON.stringify(proof), "utf8"),
    },
  };
}

const rejects = async (operation) => {
  try {
    await operation();
    return false;
  } catch {
    return true;
  }
};

const compiled = await compile();
let eip1193;
try {
  eip1193 = ganache.provider({
    chain: { chainId: 31337, hardfork: "shanghai" },
    miner: { blockGasLimit: 80_000_000 },
    logging: { quiet: true },
    wallet: { deterministic: true, totalAccounts: 2 },
  });
  const provider = new ethers.providers.Web3Provider(eip1193);
  const signer = provider.getSigner(0);
  const grothFactory = new ethers.ContractFactory(compiled.groth16.abi, `0x${compiled.groth16.evm.bytecode.object}`, signer);
  const groth16 = await grothFactory.deploy();
  const grothReceipt = await groth16.deployTransaction.wait();
  const verifierFactory = new ethers.ContractFactory(compiled.verifier.abi, `0x${compiled.verifier.evm.bytecode.object}`, signer);
  const enrollments = new Map(DIMENSIONS.map((dimension) => [dimension, createEnrollment(dimension)]));
  const results = [];
  for (const gridPoint of selectedGrid) {
    const { dimension, eta, samples, label } = gridPoint;
    if (samples !== sampleCount(dimension, eta)) throw new Error(`${label}: internal t mismatch`);
    const verifier = await verifierFactory.deploy(dimension, samples, TAU, groth16.address);
    const deployReceipt = await verifier.deployTransaction.wait();
    const deploymentTransactionBytes = ethers.utils.arrayify(verifier.deployTransaction.data);
    const deployedRuntimeBytes = ethers.utils.arrayify(await provider.getCode(verifier.address));
    const ctxHash = await verifier.ctxHash();
    const id = 1;
    const enrollment = enrollments.get(dimension);
    const enrollRequest = await verifier.populateTransaction.enroll(id, enrollment.points);
    const enrollReceipt = await (await signer.sendTransaction({ ...enrollRequest, gasLimit: 79_000_000 })).wait();
    const authentications = [];
    let lastTranscript;
    for (let repetition = 1; repetition <= REPETITIONS; repetition += 1) {
      const transcript = await prove(ctxHash, id, repetition, enrollment);
      const request = await verifier.populateTransaction.authenticate(id, repetition, transcript);
      const calldata = calldataCost(request.data);
      const receipt = await (await signer.sendTransaction({ ...request, gasLimit: 79_000_000 })).wait();
      if (receipt.status !== 1) throw new Error(`${label}: authentication ${repetition} failed`);
      authentications.push({
        repetition,
        nonce: repetition,
        transactionHash: receipt.transactionHash,
        blockNumber: receipt.blockNumber,
        status: receipt.status,
        gasUsed: receipt.gasUsed.toNumber(),
        calldata,
        intrinsicGas: 21_000 + calldata.gas,
        executionGasAfterIntrinsic: receipt.gasUsed.toNumber() - 21_000 - calldata.gas,
        fullProveMilliseconds: transcript.measurement.fullProveMilliseconds,
        transcriptConstructionMilliseconds: transcript.measurement.transcriptConstructionMilliseconds,
        transcriptAndFullProveMilliseconds: transcript.measurement.transcriptAndFullProveMilliseconds,
        proofAbiBytes: transcript.measurement.proofAbiBytes,
        proofAbiSha256: transcript.measurement.proofAbiSha256,
        proofJsonBytes: transcript.measurement.proofJsonBytes,
      });
      lastTranscript = transcript;
    }
    const controlTranscript = await prove(ctxHash, id, REPETITIONS + 1, enrollment);
    const replayRejected = await rejects(() => verifier.callStatic.authenticate(id, REPETITIONS, lastTranscript));
    const staleProofRejected = await rejects(() => verifier.callStatic.authenticate(id, REPETITIONS + 1, {
      ...controlTranscript,
      pA: lastTranscript.pA,
      pB: lastTranscript.pB,
      pC: lastTranscript.pC,
    }));
    const wrongEnrollment = [...controlTranscript.ce];
    wrongEnrollment[0] = controlTranscript.cp[0];
    const wrongEnrollmentRejected = await rejects(() => verifier.callStatic.authenticate(id, REPETITIONS + 1, {
      ...controlTranscript,
      ce: wrongEnrollment,
    }));
    const tamperedResponses = [...controlTranscript.z];
    for (let index = 0; index < dimension; index += 1) {
      tamperedResponses[9 * index] = mod(BigInt(tamperedResponses[9 * index]) + 1n, r).toString();
    }
    const tamperedResponseRejected = await rejects(() => verifier.callStatic.authenticate(id, REPETITIONS + 1, {
      ...controlTranscript,
      z: tamperedResponses,
    }));
    const controls = { replayRejected, staleProofRejected, wrongEnrollmentRejected, tamperedResponseRejected };
    if (!Object.values(controls).every(Boolean)) throw new Error(`${label}: mandatory negative control accepted`);
    const gasUsed = authentications.map((entry) => entry.gasUsed);
    const fullProveMilliseconds = authentications.map((entry) => entry.fullProveMilliseconds);
    const transcriptConstructionMilliseconds = authentications.map((entry) => entry.transcriptConstructionMilliseconds);
    const transcriptAndFullProveMilliseconds = authentications.map((entry) => entry.transcriptAndFullProveMilliseconds);
    const calldataBytes = authentications.map((entry) => entry.calldata.bytes);
    const calldataGas = authentications.map((entry) => entry.calldata.gas);
    results.push({
      ...gridPoint,
      repetitions: REPETITIONS,
      gasUsed,
      medianGasUsed: median(gasUsed),
      calldataBytes,
      medianCalldataBytes: median(calldataBytes),
      calldataGas,
      medianCalldataGas: median(calldataGas),
      fullProveMilliseconds,
      medianFullProveMilliseconds: median(fullProveMilliseconds),
      transcriptConstructionMilliseconds,
      medianTranscriptConstructionMilliseconds: median(transcriptConstructionMilliseconds),
      transcriptAndFullProveMilliseconds,
      medianTranscriptAndFullProveMilliseconds: median(transcriptAndFullProveMilliseconds),
      proofAbiBytes: authentications.map((entry) => entry.proofAbiBytes),
      proofAbiSha256: authentications.map((entry) => entry.proofAbiSha256),
      proofJsonBytes: authentications.map((entry) => entry.proofJsonBytes),
      enrollmentGas: enrollReceipt.gasUsed.toNumber(),
      deploymentGas: deployReceipt.gasUsed.toNumber(),
      deployedBytecode: {
        creationTransaction: { bytes: deploymentTransactionBytes.length, sha256: sha256(Buffer.from(deploymentTransactionBytes)) },
        runtime: { bytes: deployedRuntimeBytes.length, sha256: sha256(Buffer.from(deployedRuntimeBytes)) },
      },
      authentications,
      controlFullProveMilliseconds: controlTranscript.measurement.fullProveMilliseconds,
      controls,
    });
    process.stdout.write(`${label}: t=${samples} gas=${median(gasUsed)} fullProve=${median(fullProveMilliseconds).toFixed(3)}ms\n`);
  }
  const samplingModule = await import(pathToFileURL(resolve(projectRoot, "scripts", "lib", "sampling.mjs")));
  const samplingAgreement = selectedGrid.every((row) => samplingModule.sampleCount(row.dimension, row.eta) === row.samples);
  if (!samplingAgreement) throw new Error("isolated grid disagrees with project sampling.mjs");
  const record = {
    schemaVersion: 1,
    generatedAt: new Date().toISOString(),
    mode,
    scope: "Fig.3 SpotCheck dimension sweep: complete authentication transaction on BN254, including nonce and enrollment checks, Fiat-Shamir transcript, sampled consistency equations, full distance reconstruction, and the reused five-public-input Groth16 threshold verifier.",
    securityWarning: "Benchmark-only reconstructed setup. h=5G has a known discrete log, and threshold_standin range-checks delta but does not prove the opening of the reconstructed Pedersen commitment.",
    dimensions: mode === "full" ? DIMENSIONS : [2],
    etas: mode === "full" ? ETAS : [1],
    repetitions: REPETITIONS,
    threshold: TAU.toString(),
    samplingFormula: "t=min(N,ceil(eta*log2(N)))",
    samplingAgreementWithProjectLibrary: samplingAgreement,
    uniqueDimensionSamplePairs: new Set(selectedGrid.map((row) => `${row.dimension}:${row.samples}`)).size,
    interpretationWarning: "The 28 eta-labelled settings contain only 22 unique (N,t) pairs because t saturates at N for small dimensions. Saturated eta labels are retained for the four Fig.3 curves and must not be interpreted as independent threshold evidence.",
    proofTimingPolicy: "Every mined authentication executes a fresh snarkjs.groth16.fullProve call. fullProveMilliseconds brackets only that call; transcriptConstructionMilliseconds is recorded separately; transcriptAndFullProveMilliseconds brackets both. The reused threshold circuit, wasm, and zkey are independent of N; no timing value is copied or synthesized.",
    compiler: solc.version(),
    optimizerRuns: 200,
    evmVersion: "shanghai",
    chain: "Ganache 7.9.2, chain id 31337, block gas limit 80,000,000",
    setupArtifacts: {
      wasm: await fileRecord(wasm),
      zkey: await fileRecord(zkey),
      verificationKey: await fileRecord(resolve(thresholdRoot, "verification_key.json")),
      generatedVerifier: await fileRecord(resolve(projectRoot, "contracts", "generated", "Groth16VerifierThreshold.sol")),
    },
    bytecode: {
      homomorphicCompleteVerifier: bytecodeRecord(compiled.verifier),
      groth16ThresholdVerifier: bytecodeRecord(compiled.groth16),
      deployedGroth16ThresholdVerifier: {
        creationTransaction: {
          bytes: ethers.utils.arrayify(groth16.deployTransaction.data).length,
          sha256: sha256(Buffer.from(ethers.utils.arrayify(groth16.deployTransaction.data))),
        },
        runtime: {
          bytes: ethers.utils.arrayify(await provider.getCode(groth16.address)).length,
          sha256: sha256(Buffer.from(ethers.utils.arrayify(await provider.getCode(groth16.address)))),
        },
      },
    },
    groth16VerifierDeploymentGas: grothReceipt.gasUsed.toNumber(),
    results,
  };
  await mkdir(resolve(outputRoot, "results"), { recursive: true });
  const jsonPath = resolve(outputRoot, "results", "spotcheck-n-sweep.json");
  await writeFile(jsonPath, `${JSON.stringify(record, null, 2)}\n`, "utf8");
  const columns = [
    "dimension", "eta", "samples", "repetitions", "gas_used", "median_gas_used",
    "calldata_bytes", "median_calldata_bytes", "calldata_gas", "median_calldata_gas",
    "full_prove_milliseconds", "median_full_prove_milliseconds", "transcript_construction_milliseconds", "median_transcript_construction_milliseconds", "transcript_and_full_prove_milliseconds", "median_transcript_and_full_prove_milliseconds", "proof_abi_bytes", "proof_abi_sha256", "proof_json_bytes",
    "enrollment_gas", "deployment_gas", "replay_rejected", "stale_proof_rejected",
    "wrong_enrollment_rejected", "tampered_response_rejected",
  ];
  const csvRows = record.results.map((row) => [
    row.dimension, row.eta, row.samples, row.repetitions, JSON.stringify(row.gasUsed), row.medianGasUsed,
    JSON.stringify(row.calldataBytes), row.medianCalldataBytes, JSON.stringify(row.calldataGas), row.medianCalldataGas,
    JSON.stringify(row.fullProveMilliseconds), row.medianFullProveMilliseconds,
    JSON.stringify(row.transcriptConstructionMilliseconds), row.medianTranscriptConstructionMilliseconds,
    JSON.stringify(row.transcriptAndFullProveMilliseconds), row.medianTranscriptAndFullProveMilliseconds,
    JSON.stringify(row.proofAbiBytes),
    JSON.stringify(row.proofAbiSha256), JSON.stringify(row.proofJsonBytes), row.enrollmentGas, row.deploymentGas, row.controls.replayRejected,
    row.controls.staleProofRejected, row.controls.wrongEnrollmentRejected, row.controls.tamperedResponseRejected,
  ].map(csvCell).join(","));
  await writeFile(resolve(outputRoot, "results", "spotcheck-n-sweep.csv"), `${columns.join(",")}\n${csvRows.join("\n")}\n`, "utf8");
  process.stdout.write(`wrote ${record.results.length} settings to ${basename(jsonPath)}\n`);
} finally {
  if (eip1193) await eip1193.disconnect();
  await curve.terminate();
  if (globalThis.curve_bn128) await globalThis.curve_bn128.terminate();
}
process.exit(0);
