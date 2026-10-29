import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import ganache from "ganache";
import solc from "solc";
import { BrowserProvider, ContractFactory, version as ethersVersion } from "ethers";
import { groth16 } from "snarkjs";
import {
  DEFAULT_GAS_REPETITIONS,
  DEFAULT_WARMUPS,
  EIP170_RUNTIME_LIMIT_BYTES,
  ROOT,
  boundedCount,
  selectedDimensions,
} from "./config.mjs";
import { csv, median, receiptRecord, sha256, sha256Text, writeJson } from "./lib/audit.mjs";
import { pathsFor } from "./lib/paths.mjs";

const FIELD_MODULUS = 21_888_242_871_839_275_222_246_405_745_257_275_088_548_364_400_416_034_343_698_204_186_575_808_495_617n;
const dimensions = selectedDimensions();
const warmups = boundedCount("BIOZERO_GRID_GAS_WARMUPS", DEFAULT_WARMUPS);
const repetitions = boundedCount("BIOZERO_GRID_GAS_REPETITIONS", DEFAULT_GAS_REPETITIONS);
if (warmups !== 1 || repetitions !== 5) {
  throw new Error("auditable gas protocol is fixed at one warmup and five measured transactions");
}
const rawRoot = resolve(ROOT, "results", "verifier-gas", "raw");
await mkdir(rawRoot, { recursive: true });

function compileVerifier(source) {
  const input = {
    language: "Solidity",
    sources: { "Groth16Verifier.sol": { content: source } },
    settings: {
      optimizer: { enabled: true, runs: 200 },
      evmVersion: "shanghai",
      outputSelection: {
        "*": { "*": ["abi", "evm.bytecode.object", "evm.deployedBytecode.object"] },
      },
    },
  };
  const output = JSON.parse(solc.compile(JSON.stringify(input)));
  const errors = (output.errors ?? []).filter((entry) => entry.severity === "error");
  if (errors.length > 0) throw new Error(errors.map((entry) => entry.formattedMessage).join("\n"));
  const artifact = output.contracts?.["Groth16Verifier.sol"]?.Groth16Verifier;
  if (!artifact?.abi || !artifact?.evm?.bytecode?.object || !artifact?.evm?.deployedBytecode?.object) {
    throw new Error("solc did not produce the Groth16Verifier artifact");
  }
  return {
    abi: artifact.abi,
    creationBytecode: `0x${artifact.evm.bytecode.object}`,
    runtimeBytecode: `0x${artifact.evm.deployedBytecode.object}`,
  };
}

async function solidityArguments(proofPath, publicPath) {
  const [proof, publicSignals] = await Promise.all(
    [proofPath, publicPath].map(async (path) => JSON.parse(await readFile(path, "utf8"))),
  );
  const exported = await groth16.exportSolidityCallData(proof, publicSignals);
  const [pA, pB, pC, signals] = JSON.parse(`[${exported}]`);
  return { pA, pB, pC, signals };
}

function mutatePublicInput(signals) {
  if (!Array.isArray(signals) || signals.length === 0) throw new Error("proof has no public inputs");
  const mutated = [...signals];
  mutated[0] = ((BigInt(mutated[0]) + 1n) % FIELD_MODULUS).toString();
  return mutated;
}

const rawCsvRows = [["dimension", "kind", "run", "measured", "transaction_hash", "status", "gas_used"]];
const results = [];
for (const dimension of dimensions) {
  const paths = pathsFor(dimension);
  const verifierSource = await readFile(paths.verifier, "utf8");
  const compiled = compileVerifier(verifierSource);
  const runtimeBytes = (compiled.runtimeBytecode.length - 2) / 2;
  const creationBytes = (compiled.creationBytecode.length - 2) / 2;
  const eip1193 = ganache.provider({
    logging: { quiet: true },
    wallet: { deterministic: true, totalAccounts: 2 },
    chain: { chainId: 31_337, hardfork: "shanghai", allowUnlimitedContractSize: false },
    miner: { blockGasLimit: 60_000_000 },
  });
  try {
    const provider = new BrowserProvider(eip1193);
    const signer = await provider.getSigner(0);
    const factory = new ContractFactory(compiled.abi, compiled.creationBytecode, signer);
    const contract = await factory.deploy({ gasLimit: 15_000_000n });
    const deploymentTransaction = contract.deploymentTransaction();
    const deploymentReceipt = await deploymentTransaction.wait();
    await contract.waitForDeployment();
    const address = await contract.getAddress();
    const onchainRuntimeBytecode = await provider.getCode(address);
    const proofRoot = resolve(ROOT, "results", "proving", "raw");
    async function proofMaterial(phase, run) {
      const stem = `${paths.name}-${phase}-${String(run).padStart(2, "0")}`;
      const proofPath = resolve(proofRoot, `${stem}-proof.json`);
      const publicPath = resolve(proofRoot, `${stem}-public.json`);
      return {
        args: await solidityArguments(proofPath, publicPath),
        evidence: {
          phase,
          run,
          proof: `results/proving/raw/${stem}-proof.json`,
          proofSha256: await sha256(proofPath),
          publicSignals: `results/proving/raw/${stem}-public.json`,
          publicSignalsSha256: await sha256(publicPath),
        },
      };
    }
    const verifyProof = contract.getFunction("verifyProof");
    const warmupTransactions = [];
    for (let run = 1; run <= warmups; run += 1) {
      const material = await proofMaterial("warmup", run);
      const { args } = material;
      const staticReturn = await verifyProof.staticCall(args.pA, args.pB, args.pC, args.signals);
      const estimatedGas = await verifyProof.estimateGas(args.pA, args.pB, args.pC, args.signals);
      const transaction = await verifyProof.send(args.pA, args.pB, args.pC, args.signals, {
        gasLimit: (estimatedGas * 12n) / 10n + 50_000n,
      });
      const receipt = await transaction.wait();
      const record = {
        run,
        measured: false,
        staticReturn,
        estimatedGas: Number(estimatedGas),
        proofMaterial: material.evidence,
        ...receiptRecord(transaction, receipt),
      };
      warmupTransactions.push(record);
      rawCsvRows.push([dimension, "valid-warmup", run, false, record.transactionHash, record.status, record.gasUsed]);
    }
    const measuredTransactions = [];
    let firstMeasuredArgs;
    for (let run = 1; run <= repetitions; run += 1) {
      const material = await proofMaterial("measured", run);
      const { args } = material;
      if (run === 1) firstMeasuredArgs = args;
      const staticReturn = await verifyProof.staticCall(args.pA, args.pB, args.pC, args.signals);
      const estimatedGas = await verifyProof.estimateGas(args.pA, args.pB, args.pC, args.signals);
      const transaction = await verifyProof.send(args.pA, args.pB, args.pC, args.signals, {
        gasLimit: (estimatedGas * 12n) / 10n + 50_000n,
      });
      const receipt = await transaction.wait();
      const record = {
        run,
        measured: true,
        staticReturn,
        estimatedGas: Number(estimatedGas),
        proofMaterial: material.evidence,
        ...receiptRecord(transaction, receipt),
      };
      measuredTransactions.push(record);
      rawCsvRows.push([dimension, "valid-measured", run, true, record.transactionHash, record.status, record.gasUsed]);
    }

    const invalidSignals = mutatePublicInput(firstMeasuredArgs.signals);
    const invalidStaticReturn = await verifyProof.staticCall(firstMeasuredArgs.pA, firstMeasuredArgs.pB, firstMeasuredArgs.pC, invalidSignals);
    const invalidEstimate = await verifyProof.estimateGas(firstMeasuredArgs.pA, firstMeasuredArgs.pB, firstMeasuredArgs.pC, invalidSignals);
    const invalidTransaction = await verifyProof.send(firstMeasuredArgs.pA, firstMeasuredArgs.pB, firstMeasuredArgs.pC, invalidSignals, {
      gasLimit: (invalidEstimate * 12n) / 10n + 50_000n,
    });
    const invalidReceipt = await invalidTransaction.wait();
    const invalidRecord = receiptRecord(invalidTransaction, invalidReceipt);
    rawCsvRows.push([dimension, "invalid-public-input", 1, false, invalidRecord.transactionHash, invalidRecord.status, invalidRecord.gasUsed]);
    const deploymentRecord = receiptRecord(deploymentTransaction, deploymentReceipt);
    rawCsvRows.push([dimension, "deployment", 1, false, deploymentRecord.transactionHash, deploymentRecord.status, deploymentRecord.gasUsed]);

    const raw = {
      schemaVersion: 1,
      generatedAt: new Date().toISOString(),
      dimension,
      configuration: {
        solcJs: solc.version(),
        optimizer: { enabled: true, runs: 200 },
        evmVersion: "shanghai",
        ganache: "7.9.2",
        ethers: ethersVersion,
        chainId: 31_337,
        allowUnlimitedContractSize: false,
        warmupTransactions: warmups,
        measuredTransactions: repetitions,
      },
      artifacts: {
        verifierSource: `contracts/generated/Groth16Verifier${dimension}.sol`,
        verifierSourceSha256: await sha256(paths.verifier),
        zkeySha256: await sha256(paths.zkey),
        verificationKeySha256: await sha256(paths.vkey),
      },
      bytecode: {
        creation: compiled.creationBytecode,
        creationBytes,
        creationSha256: sha256Text(compiled.creationBytecode),
        compiledRuntime: compiled.runtimeBytecode,
        compiledRuntimeBytes: runtimeBytes,
        compiledRuntimeSha256: sha256Text(compiled.runtimeBytecode),
        onchainRuntime: onchainRuntimeBytecode,
        onchainRuntimeBytes: (onchainRuntimeBytecode.length - 2) / 2,
        onchainRuntimeSha256: sha256Text(onchainRuntimeBytecode),
        onchainMatchesCompiled: onchainRuntimeBytecode.toLowerCase() === compiled.runtimeBytecode.toLowerCase(),
        eip170LimitBytes: EIP170_RUNTIME_LIMIT_BYTES,
        eip170Compliant: runtimeBytes <= EIP170_RUNTIME_LIMIT_BYTES,
      },
      deployment: deploymentRecord,
      validControl: {
        staticReturns: [...warmupTransactions, ...measuredTransactions].map((entry) => entry.staticReturn),
        warmupTransactions,
        measuredTransactions,
      },
      invalidPublicInputControl: {
        mutation: "publicSignals[0] = (publicSignals[0] + 1) mod BN254 scalar field; proof unchanged",
        original: firstMeasuredArgs.signals[0],
        mutated: invalidSignals[0],
        staticReturn: invalidStaticReturn,
        estimatedGas: Number(invalidEstimate),
        receipt: invalidRecord,
        interpretation: "verifyProof returns false; a direct transaction still has status 1 because false is not a revert",
      },
    };
    raw.acceptance = {
      deploymentSuccessful: deploymentRecord.status === 1,
      validStaticTrue: raw.validControl.staticReturns.every((value) => value === true),
      fiveMeasuredReceiptsSuccessful: measuredTransactions.length === 5
        && measuredTransactions.every((entry) => entry.status === 1),
      invalidStaticFalse: raw.invalidPublicInputControl.staticReturn === false,
      invalidTransactionSuccessful: invalidRecord.status === 1,
      runtimeMatchesCompiler: raw.bytecode.onchainMatchesCompiled,
      eip170Compliant: raw.bytecode.eip170Compliant,
    };
    raw.overall = Object.values(raw.acceptance).every(Boolean) ? "PASS" : "FAIL";
    const rawPath = resolve(rawRoot, `auth_distance_${dimension}.json`);
    await writeJson(rawPath, raw);
    results.push({
      dimension,
      overall: raw.overall,
      raw: `results/verifier-gas/raw/auth_distance_${dimension}.json`,
      rawSha256: await sha256(rawPath),
      deploymentGas: deploymentRecord.gasUsed,
      validVerifyGas: measuredTransactions.map((entry) => entry.gasUsed),
      medianValidVerifyGas: median(measuredTransactions.map((entry) => entry.gasUsed)),
      validStaticReturn: raw.validControl.staticReturns.every((value) => value === true),
      invalidStaticReturn,
      creationBytecodeBytes: creationBytes,
      runtimeBytecodeBytes: runtimeBytes,
      eip170Compliant: raw.bytecode.eip170Compliant,
      runtimeMatchesCompiler: raw.bytecode.onchainMatchesCompiled,
    });
    process.stdout.write(`[gas] N=${dimension} deploy=${deploymentRecord.gasUsed} verify-median=${results.at(-1).medianValidVerifyGas} runtime=${runtimeBytes}B\n`);
  } finally {
    await eip1193.disconnect();
  }
}

await writeJson(resolve(ROOT, "results", "verifier-gas.json"), {
  schemaVersion: 1,
  generatedAt: new Date().toISOString(),
  status: "fresh local bare-verifier benchmark; not a historical measurement",
  dimensions,
  protocol: {
    compiler: "solc-js 0.8.33, optimizer 200, Shanghai",
    chain: "Ganache 7.9.2, Shanghai, chain id 31337, standard EIP-170 size limit",
    client: "ethers 6.16.0",
    warmups,
    measuredTransactions: repetitions,
  },
  results,
});
await writeFile(resolve(ROOT, "results", "verifier-gas-raw.csv"), csv(rawCsvRows), "utf8");
if (globalThis.curve_bn128) await globalThis.curve_bn128.terminate();
process.exit(0);
