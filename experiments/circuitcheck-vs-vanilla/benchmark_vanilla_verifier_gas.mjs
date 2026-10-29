#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

export const DIMENSIONS = Object.freeze([2, 4, 8, 16, 32, 64, 128]);
export const EIP170_RUNTIME_LIMIT_BYTES = 24_576;
export const BN254_SCALAR_FIELD =
  21_888_242_871_839_275_222_246_405_745_257_275_088_548_364_400_416_034_343_698_204_186_575_808_495_617n;

const DEFAULT_RUN_ROOT =
  "/var/tmp/biozero-circuitcheck-vs-vanilla-20261028/runs/full-20261028T1754-controlled";
const DEFAULT_CACHE_ROOT = "/home/lzb/BioZero_remote/cache-fig3-full-20261028";
const DEFAULT_NODE_MODULES_ROOT = "/home/lzb/BioZero_remote/src/experiments";
const EXPECTED_VERSIONS = Object.freeze({
  solcPrefix: "0.8.33+commit.64118f21.",
  ganache: "7.9.2",
  ethers: "6.16.0",
});

export function sha256(data) {
  return crypto.createHash("sha256").update(data).digest("hex");
}

export function bytesOfHex(hex) {
  if (typeof hex !== "string" || !/^0x(?:[0-9a-fA-F]{2})*$/.test(hex)) {
    throw new Error("expected an even-length 0x-prefixed hex string");
  }
  return (hex.length - 2) / 2;
}

export function csv(rows) {
  return `${rows
    .map((row) =>
      row
        .map((value) => {
          const text = value == null ? "" : String(value);
          return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
        })
        .join(","),
    )
    .join("\n")}\n`;
}

export function proofForAbi(proofJson, verifyFunction) {
  if (!proofJson || typeof proofJson !== "object") throw new Error("proof JSON must be an object");
  if (!proofJson.proof || !Array.isArray(proofJson.inputs)) {
    throw new Error("proof JSON must contain proof and inputs");
  }
  const { proof } = proofJson;
  if (
    !Array.isArray(proof.a) ||
    !Array.isArray(proof.b) ||
    !Array.isArray(proof.b[0]) ||
    !Array.isArray(proof.b[1]) ||
    !Array.isArray(proof.c)
  ) {
    throw new Error("unsupported ZoKrates proof shape");
  }
  const proofParameter = verifyFunction?.inputs?.[0];
  if (!proofParameter) throw new Error("verifyTx proof parameter is absent from ABI");
  const namedProof = {
    a: { X: proof.a[0], Y: proof.a[1] },
    b: { X: [proof.b[0][0], proof.b[0][1]], Y: [proof.b[1][0], proof.b[1][1]] },
    c: { X: proof.c[0], Y: proof.c[1] },
  };
  const proofValue = proofParameter.type === "tuple" ? namedProof : [proof.a, proof.b, proof.c];
  return [proofValue, proofJson.inputs];
}

export function mutateFirstPublicInput(inputs) {
  if (!Array.isArray(inputs) || inputs.length === 0) throw new Error("proof has no public inputs");
  const mutated = [...inputs];
  const original = String(mutated[0]);
  const next = (BigInt(original) + 1n) % BN254_SCALAR_FIELD;
  mutated[0] = original.startsWith("0x")
    ? `0x${next.toString(16).padStart(original.length - 2, "0")}`
    : next.toString();
  return mutated;
}

export function parseLegacyChainSample(sample) {
  if (!sample || typeof sample !== "object") throw new Error("legacy chain fixture must be an object");
  const measured = sample.valid_control?.transactions;
  const deployment = sample.deployment;
  if (!Array.isArray(measured) || !deployment) throw new Error("legacy chain fixture has no chain records");
  const runtimeBytes = Number(deployment.compiled_runtime_bytecode_bytes);
  const eip170Deployable = runtimeBytes <= EIP170_RUNTIME_LIMIT_BYTES;
  return {
    target: String(sample.target),
    dimension: Number(sample.dimension),
    measured_transactions: measured.length,
    measured_gas: measured.map((entry) => Number(entry.gas_used)),
    deployment_gas: Number(deployment.gas_used),
    creation_bytecode_bytes: Number(deployment.creation_bytecode_bytes),
    runtime_bytecode_bytes: runtimeBytes,
    runtime_matches_compiler: deployment.onchain_runtime_matches_compiled === true,
    valid_static_true: sample.valid_control?.static_return === true,
    invalid_static_false: sample.invalid_public_input_control?.static_return === false,
    eip170_deployable: eip170Deployable,
    standard_eip170_failure_recorded:
      sample.standard_eip170_control?.deployment_failed_as_expected === true,
  };
}

function packageVersion(requireFromTools, packageName) {
  let directory = path.dirname(requireFromTools.resolve(packageName));
  while (directory !== path.dirname(directory)) {
    const candidate = path.join(directory, "package.json");
    if (fs.existsSync(candidate)) {
      const packageJson = JSON.parse(fs.readFileSync(candidate, "utf8"));
      if (packageJson.name === packageName) return packageJson.version;
    }
    directory = path.dirname(directory);
  }
  throw new Error(`unable to resolve package version for ${packageName}`);
}

function loadPinnedTools(nodeModulesRoot) {
  const packageJsonPath = path.join(nodeModulesRoot, "package.json");
  if (!fs.existsSync(packageJsonPath)) {
    throw new Error(
      `tool package.json is missing: ${packageJsonPath}; set VANILLA_GAS_NODE_MODULES`,
    );
  }
  const requireFromTools = createRequire(packageJsonPath);
  const solc = requireFromTools("solc");
  const ganache = requireFromTools("ganache");
  const ethers = requireFromTools("ethers");
  const versions = {
    solc: solc.version(),
    ganache: packageVersion(requireFromTools, "ganache"),
    ethers: ethers.version,
  };
  if (!versions.solc.startsWith(EXPECTED_VERSIONS.solcPrefix)) {
    throw new Error(`expected solc-js 0.8.33, got ${versions.solc}`);
  }
  if (versions.ganache !== EXPECTED_VERSIONS.ganache) {
    throw new Error(`expected Ganache ${EXPECTED_VERSIONS.ganache}, got ${versions.ganache}`);
  }
  if (versions.ethers !== EXPECTED_VERSIONS.ethers) {
    throw new Error(`expected ethers ${EXPECTED_VERSIONS.ethers}, got ${versions.ethers}`);
  }
  return { solc, ganache, ethers, versions };
}

function compileVerifier(solc, sourceCode) {
  const input = {
    language: "Solidity",
    sources: { "verifier.sol": { content: sourceCode } },
    settings: {
      optimizer: { enabled: true, runs: 200 },
      evmVersion: "shanghai",
      outputSelection: {
        "*": { "*": ["abi", "evm.bytecode.object", "evm.deployedBytecode.object"] },
      },
    },
  };
  const output = JSON.parse(solc.compile(JSON.stringify(input)));
  const fatal = (output.errors ?? []).filter((entry) => entry.severity === "error");
  if (fatal.length > 0) throw new Error(fatal.map((entry) => entry.formattedMessage).join("\n"));
  const contracts = output.contracts?.["verifier.sol"] ?? {};
  const verifier = contracts.Verifier ?? Object.values(contracts)[0];
  if (
    !verifier?.abi ||
    !verifier?.evm?.bytecode?.object ||
    !verifier?.evm?.deployedBytecode?.object
  ) {
    throw new Error("solc produced no complete Verifier artifact");
  }
  return {
    abi: verifier.abi,
    creationBytecode: `0x${verifier.evm.bytecode.object}`,
    runtimeBytecode: `0x${verifier.evm.deployedBytecode.object}`,
  };
}

function verifierSnapshot(verifierPath) {
  const source = fs.readFileSync(verifierPath);
  const stat = fs.statSync(verifierPath);
  return {
    path: verifierPath,
    bytes: source.length,
    sha256: sha256(source),
    mode: stat.mode & 0o777,
    mtime_ms: stat.mtimeMs,
    source,
  };
}

function sameVerifierSnapshot(before, after) {
  return (
    before.path === after.path &&
    before.bytes === after.bytes &&
    before.sha256 === after.sha256 &&
    before.mode === after.mode &&
    before.mtime_ms === after.mtime_ms
  );
}

function receiptRecord(transaction, receipt) {
  return {
    transaction_hash: transaction?.hash ?? receipt?.hash ?? null,
    block_number: receipt?.blockNumber ?? null,
    block_hash: receipt?.blockHash ?? null,
    receipt_status: receipt?.status == null ? null : Number(receipt.status),
    gas_used: receipt?.gasUsed == null ? null : Number(receipt.gasUsed),
    cumulative_gas_used:
      receipt?.cumulativeGasUsed == null ? null : Number(receipt.cumulativeGasUsed),
    contract_address: receipt?.contractAddress ?? null,
    from: receipt?.from ?? null,
    to: receipt?.to ?? null,
  };
}

function errorText(error) {
  return [
    error?.shortMessage,
    error?.message,
    error?.reason,
    error?.info?.error?.message,
    error?.error?.message,
    error?.cause?.message,
  ]
    .filter((value) => value != null)
    .map(String)
    .join(" | ")
    .slice(0, 8_000);
}

async function createChain(tools, dimension, allowUnlimitedContractSize) {
  const chainId = (allowUnlimitedContractSize ? 41_337 : 31_337) + dimension;
  const eip1193 = tools.ganache.provider({
    logging: { quiet: true },
    wallet: { totalAccounts: 2, deterministic: true },
    chain: {
      hardfork: "shanghai",
      chainId,
      allowUnlimitedContractSize,
    },
    miner: { blockGasLimit: 60_000_000 },
  });
  const provider = new tools.ethers.BrowserProvider(eip1193);
  const signer = await provider.getSigner(0);
  return { eip1193, provider, signer, chainId };
}

async function deploy(chain, tools, compiled) {
  const factory = new tools.ethers.ContractFactory(
    compiled.abi,
    compiled.creationBytecode,
    chain.signer,
  );
  let contract;
  let transaction;
  try {
    contract = await factory.deploy({ gasLimit: 15_000_000n });
    transaction = contract.deploymentTransaction();
    const receipt = await transaction.wait();
    await contract.waitForDeployment();
    return { success: true, contract, transaction, receipt, error: null };
  } catch (error) {
    const receipt = error?.receipt ?? null;
    return {
      success: false,
      contract: null,
      transaction,
      receipt,
      error: errorText(error),
    };
  }
}

function proofSpec(runRoot, dimension, phase, run) {
  const directory = phase === "warmup" ? "warmup-00" : `measured-${String(run).padStart(2, "0")}`;
  return {
    phase,
    run,
    measured: phase === "measured",
    path: path.join(runRoot, "runs", `N${dimension}`, directory, "proof.json"),
  };
}

function readProofMaterial(spec, verifyFunction) {
  if (!fs.existsSync(spec.path)) throw new Error(`required proof is missing: ${spec.path}`);
  const text = fs.readFileSync(spec.path, "utf8");
  const parsed = JSON.parse(text);
  const [proofArgument, publicInputs] = proofForAbi(parsed, verifyFunction);
  return {
    ...spec,
    proofArgument,
    publicInputs,
    evidence: {
      proof_path: spec.path,
      proof_bytes: Buffer.byteLength(text),
      proof_sha256: sha256(text),
    },
  };
}

async function sendProof(contract, material) {
  const verifyTx = contract.getFunction("verifyTx");
  const calldata = contract.interface.encodeFunctionData("verifyTx", [
    material.proofArgument,
    material.publicInputs,
  ]);
  const staticReturn = await verifyTx.staticCall(material.proofArgument, material.publicInputs);
  const estimatedGas = await verifyTx.estimateGas(material.proofArgument, material.publicInputs);
  const transaction = await verifyTx.send(material.proofArgument, material.publicInputs, {
    gasLimit: (estimatedGas * 12n) / 10n + 50_000n,
  });
  const receipt = await transaction.wait();
  return {
    phase: material.phase,
    run: material.run,
    measured: material.measured,
    ...material.evidence,
    calldata_bytes: bytesOfHex(calldata),
    calldata_sha256: sha256(calldata),
    static_return: staticReturn,
    estimated_gas: Number(estimatedGas),
    receipt: receiptRecord(transaction, receipt),
  };
}

async function invalidPublicInputControl(contract, material) {
  const verifyTx = contract.getFunction("verifyTx");
  const invalidInputs = mutateFirstPublicInput(material.publicInputs);
  const calldata = contract.interface.encodeFunctionData("verifyTx", [
    material.proofArgument,
    invalidInputs,
  ]);
  const staticReturn = await verifyTx.staticCall(material.proofArgument, invalidInputs);
  return {
    mutation: "inputs[0] = (inputs[0] + 1) mod BN254 scalar field; proof unchanged",
    source_proof_path: material.evidence.proof_path,
    source_proof_sha256: material.evidence.proof_sha256,
    original_public_input: String(material.publicInputs[0]),
    mutated_public_input: String(invalidInputs[0]),
    calldata_bytes: bytesOfHex(calldata),
    calldata_sha256: sha256(calldata),
    static_return: staticReturn,
  };
}

function standardAttemptRecord(deployment, runtimeBytes) {
  const message = deployment.error ?? "";
  const explicitSizeReason = /code size|maximum code|EIP-170|exceeds maximum/i.test(message);
  const receiptStatusZero =
    deployment.receipt != null && Number(deployment.receipt.status) === 0;
  const runtimeExceedsLimit = runtimeBytes > EIP170_RUNTIME_LIMIT_BYTES;
  return {
    attempted: true,
    allow_unlimited_contract_size: false,
    success: deployment.success,
    eip170_runtime_limit_bytes: EIP170_RUNTIME_LIMIT_BYTES,
    compiled_runtime_bytecode_bytes: runtimeBytes,
    runtime_exceeds_limit: runtimeExceedsLimit,
    deployment_failed_as_expected:
      runtimeExceedsLimit && !deployment.success && (explicitSizeReason || receiptStatusZero),
    classification_basis: explicitSizeReason
      ? "provider explicitly reported the contract-code-size limit"
      : receiptStatusZero && runtimeExceedsLimit
        ? "status=0 receipt under standard limit with compiled runtime above EIP-170"
        : null,
    explicit_size_reason: explicitSizeReason,
    receipt:
      deployment.receipt == null
        ? null
        : receiptRecord(deployment.transaction, deployment.receipt),
    error: deployment.error,
  };
}

async function benchmarkDimension(context, dimension) {
  const verifierPath = path.join(context.cacheRoot, `groth16_vanilla_${dimension}`, "verifier.sol");
  if (!fs.existsSync(verifierPath)) throw new Error(`cached verifier is missing: ${verifierPath}`);
  const verifierBefore = verifierSnapshot(verifierPath);
  const compiled = compileVerifier(context.tools.solc, verifierBefore.source.toString("utf8"));
  const creationBytes = bytesOfHex(compiled.creationBytecode);
  const runtimeBytes = bytesOfHex(compiled.runtimeBytecode);
  const runtimeExceedsLimit = runtimeBytes > EIP170_RUNTIME_LIMIT_BYTES;

  const standardChain = await createChain(context.tools, dimension, false);
  let measurementChain = standardChain;
  let standardDeployment;
  let measurementDeployment;
  let unlimitedChain = null;
  try {
    standardDeployment = await deploy(standardChain, context.tools, compiled);
    if (runtimeExceedsLimit) {
      if (standardDeployment.success) {
        throw new Error(`N=${dimension} unexpectedly deployed above EIP-170 on the standard chain`);
      }
      await standardChain.eip1193.disconnect();
      measurementChain = null;
      unlimitedChain = await createChain(context.tools, dimension, true);
      measurementChain = unlimitedChain;
      measurementDeployment = await deploy(unlimitedChain, context.tools, compiled);
      if (!measurementDeployment.success) {
        throw new Error(`N=${dimension} unlimited benchmark deployment failed: ${measurementDeployment.error}`);
      }
    } else {
      if (!standardDeployment.success) {
        throw new Error(`N=${dimension} standard deployment failed: ${standardDeployment.error}`);
      }
      measurementDeployment = standardDeployment;
    }

    const contract = measurementDeployment.contract;
    const verifyFunction = compiled.abi.find(
      (entry) => entry.type === "function" && entry.name === "verifyTx",
    );
    if (!verifyFunction) throw new Error("verifyTx is absent from compiled ABI");
    const proofSpecs = [
      proofSpec(context.runRoot, dimension, "warmup", 0),
      ...[1, 2, 3, 4, 5].map((run) =>
        proofSpec(context.runRoot, dimension, "measured", run),
      ),
    ];
    const materials = proofSpecs.map((spec) => readProofMaterial(spec, verifyFunction));
    const transactions = [];
    for (const material of materials) transactions.push(await sendProof(contract, material));
    const invalidControl = await invalidPublicInputControl(contract, materials[1]);
    const address = await contract.getAddress();
    const onchainRuntime = await measurementChain.provider.getCode(address);
    const verifierAfter = verifierSnapshot(verifierPath);
    const cacheSourceUnchanged = sameVerifierSnapshot(verifierBefore, verifierAfter);
    const standardAttempt = standardAttemptRecord(standardDeployment, runtimeBytes);
    const measurementReceipt = receiptRecord(
      measurementDeployment.transaction,
      measurementDeployment.receipt,
    );
    const proofHashes = transactions.map((entry) => entry.proof_sha256);
    const proofPaths = transactions.map((entry) => entry.proof_path);
    const warmups = transactions.filter((entry) => !entry.measured);
    const measured = transactions.filter((entry) => entry.measured);
    const eip170Deployable = !runtimeExceedsLimit && standardDeployment.success;
    const result = {
      schema_version: 1,
      generated_at: new Date().toISOString(),
      target: `vanilla-${dimension}`,
      dimension,
      classification: "fresh direct-verifier benchmark over per-attempt controlled Vanilla proofs",
      configuration: {
        solc_js_version: context.tools.versions.solc,
        optimizer: { enabled: true, runs: 200 },
        evm_version: "shanghai",
        ganache_version: context.tools.versions.ganache,
        ethers_version: context.tools.versions.ethers,
        chain_id: measurementChain.chainId,
        allow_unlimited_contract_size: runtimeExceedsLimit,
        warmup_transactions: 1,
        measured_transactions: 5,
      },
      artifacts: {
        verifier_path: verifierPath,
        verifier_bytes: verifierBefore.bytes,
        verifier_sha256: verifierBefore.sha256,
        verifier_mode: verifierBefore.mode.toString(8).padStart(3, "0"),
        verifier_mtime_ms: verifierBefore.mtime_ms,
        cache_source_unchanged: cacheSourceUnchanged,
      },
      bytecode: {
        creation_bytecode_bytes: creationBytes,
        creation_bytecode_sha256: sha256(compiled.creationBytecode),
        compiled_runtime_bytecode_bytes: runtimeBytes,
        compiled_runtime_bytecode_sha256: sha256(compiled.runtimeBytecode),
        onchain_runtime_bytecode_bytes: bytesOfHex(onchainRuntime),
        onchain_runtime_bytecode_sha256: sha256(onchainRuntime),
        onchain_runtime_matches_compiled:
          onchainRuntime.toLowerCase() === compiled.runtimeBytecode.toLowerCase(),
        eip170_runtime_limit_bytes: EIP170_RUNTIME_LIMIT_BYTES,
        eip170_deployable: eip170Deployable,
      },
      standard_eip170_deployment: standardAttempt,
      benchmark_deployment: {
        policy: runtimeExceedsLimit
          ? "unlimited-contract-size local benchmark only; NOT EIP-170 deployable"
          : "standard EIP-170 contract-size limit",
        allow_unlimited_contract_size: runtimeExceedsLimit,
        eip170_deployable: eip170Deployable,
        ...measurementReceipt,
      },
      valid_control: {
        warmup_transactions: warmups,
        measured_transactions: measured,
      },
      invalid_public_input_control: invalidControl,
    };
    result.acceptance = {
      pinned_versions:
        result.configuration.solc_js_version.startsWith(EXPECTED_VERSIONS.solcPrefix) &&
        result.configuration.ganache_version === EXPECTED_VERSIONS.ganache &&
        result.configuration.ethers_version === EXPECTED_VERSIONS.ethers,
      cache_verifier_unchanged: cacheSourceUnchanged,
      six_distinct_proof_paths: new Set(proofPaths).size === 6,
      six_distinct_proof_hashes: new Set(proofHashes).size === 6,
      one_warmup_receipt:
        warmups.length === 1 && warmups.every((entry) => entry.receipt.receipt_status === 1),
      five_measured_receipts:
        measured.length === 5 && measured.every((entry) => entry.receipt.receipt_status === 1),
      all_valid_static_true: transactions.every((entry) => entry.static_return === true),
      invalid_public_input_static_false: invalidControl.static_return === false,
      onchain_runtime_matches_compiler: result.bytecode.onchain_runtime_matches_compiled,
      eip170_policy_correct: runtimeExceedsLimit
        ? standardAttempt.deployment_failed_as_expected === true &&
          result.benchmark_deployment.allow_unlimited_contract_size === true &&
          result.bytecode.eip170_deployable === false &&
          measurementReceipt.receipt_status === 1
        : standardDeployment.success === true &&
          result.benchmark_deployment.allow_unlimited_contract_size === false &&
          result.bytecode.eip170_deployable === true &&
          measurementReceipt.receipt_status === 1,
    };
    result.overall = Object.values(result.acceptance).every(Boolean) ? "PASS" : "FAIL";
    return result;
  } finally {
    if (measurementChain === standardChain) {
      await standardChain.eip1193.disconnect();
    } else if (unlimitedChain != null) {
      await unlimitedChain.eip1193.disconnect();
    }
  }
}

function preflightInputs(runRoot, cacheRoot) {
  const manifestPath = path.join(runRoot, "manifest.sha256");
  if (!fs.existsSync(manifestPath)) {
    throw new Error(
      `controlled full run is not complete (manifest.sha256 is missing): ${runRoot}`,
    );
  }
  const proofs = [];
  for (const dimension of DIMENSIONS) {
    const verifierPath = path.join(cacheRoot, `groth16_vanilla_${dimension}`, "verifier.sol");
    if (!fs.existsSync(verifierPath)) throw new Error(`cached verifier is missing: ${verifierPath}`);
    const specs = [
      proofSpec(runRoot, dimension, "warmup", 0),
      ...[1, 2, 3, 4, 5].map((run) => proofSpec(runRoot, dimension, "measured", run)),
    ];
    for (const spec of specs) {
      if (!fs.existsSync(spec.path)) throw new Error(`required proof is missing: ${spec.path}`);
      const stat = fs.statSync(spec.path);
      if ((stat.mode & 0o222) !== 0) throw new Error(`proof is not read-only: ${spec.path}`);
      const sidecarPath = path.join(path.dirname(spec.path), "proof.sha256");
      if (!fs.existsSync(sidecarPath)) throw new Error(`proof SHA-256 sidecar is missing: ${sidecarPath}`);
      const expected = fs.readFileSync(sidecarPath, "utf8").trim().split(/\s+/, 1)[0];
      const actual = sha256(fs.readFileSync(spec.path));
      if (expected !== actual) throw new Error(`proof SHA-256 sidecar mismatch: ${spec.path}`);
      proofs.push({ path: spec.path, sha256: actual, bytes: stat.size });
    }
  }
  return {
    full_run_manifest_path: manifestPath,
    full_run_manifest_sha256: sha256(fs.readFileSync(manifestPath)),
    checked_proofs: proofs.length,
    proof_sidecars_match: true,
    proofs_read_only: true,
  };
}

function buildCsvRows(results) {
  const rows = [[
    "dimension",
    "kind",
    "run",
    "measured",
    "proof_path",
    "proof_sha256",
    "proof_bytes",
    "static_return",
    "transaction_hash",
    "receipt_status",
    "gas_used",
    "estimated_gas",
    "calldata_bytes",
    "deployment_gas",
    "creation_bytecode_bytes",
    "runtime_bytecode_bytes",
    "eip170_deployable",
    "allow_unlimited_contract_size",
  ]];
  for (const result of results) {
    const common = [
      result.benchmark_deployment.gas_used,
      result.bytecode.creation_bytecode_bytes,
      result.bytecode.compiled_runtime_bytecode_bytes,
      result.bytecode.eip170_deployable,
      result.benchmark_deployment.allow_unlimited_contract_size,
    ];
    for (const entry of [
      ...result.valid_control.warmup_transactions,
      ...result.valid_control.measured_transactions,
    ]) {
      rows.push([
        result.dimension,
        entry.measured ? "valid-measured" : "valid-warmup",
        entry.run,
        entry.measured,
        entry.proof_path,
        entry.proof_sha256,
        entry.proof_bytes,
        entry.static_return,
        entry.receipt.transaction_hash,
        entry.receipt.receipt_status,
        entry.receipt.gas_used,
        entry.estimated_gas,
        entry.calldata_bytes,
        ...common,
      ]);
    }
    const invalid = result.invalid_public_input_control;
    rows.push([
      result.dimension,
      "invalid-public-input-static",
      1,
      false,
      invalid.source_proof_path,
      invalid.source_proof_sha256,
      "",
      invalid.static_return,
      "",
      "",
      "",
      "",
      invalid.calldata_bytes,
      ...common,
    ]);
  }
  return rows;
}

function buildVerification(results) {
  const checks = [];
  const check = (name, passed, detail = null) =>
    checks.push({ name, passed: Boolean(passed), detail });
  check(
    "all seven Vanilla dimensions present",
    results.length === DIMENSIONS.length &&
      DIMENSIONS.every((dimension) => results.some((entry) => entry.dimension === dimension)),
    results.map((entry) => entry.dimension),
  );
  check(
    "only N=128 exceeds EIP-170",
    results
      .filter((entry) => !entry.bytecode.eip170_deployable)
      .map((entry) => entry.dimension)
      .join(",") === "128",
    results.map((entry) => ({
      dimension: entry.dimension,
      runtime_bytes: entry.bytecode.compiled_runtime_bytecode_bytes,
      eip170_deployable: entry.bytecode.eip170_deployable,
    })),
  );
  for (const result of results) {
    for (const [name, passed] of Object.entries(result.acceptance)) {
      check(`N=${result.dimension}: ${name}`, passed);
    }
    check(
      `N=${result.dimension}: result overall PASS`,
      result.overall === "PASS",
      result.overall,
    );
  }
  return {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    overall: checks.every((entry) => entry.passed) ? "PASS" : "FAIL",
    passed: checks.filter((entry) => entry.passed).length,
    failed: checks.filter((entry) => !entry.passed).length,
    checks,
  };
}

async function main() {
  const [runRootArgument, outputRootArgument] = process.argv.slice(2);
  const runRoot = path.resolve(
    runRootArgument ?? process.env.VANILLA_GAS_RUN_ROOT ?? DEFAULT_RUN_ROOT,
  );
  const outputRoot = path.resolve(
    outputRootArgument ??
      process.env.VANILLA_GAS_OUTPUT_ROOT ??
      path.join(runRoot, "verifier-gas"),
  );
  const cacheRoot = path.resolve(process.env.VANILLA_GAS_CACHE_ROOT ?? DEFAULT_CACHE_ROOT);
  const nodeModulesRoot = path.resolve(
    process.env.VANILLA_GAS_NODE_MODULES ?? DEFAULT_NODE_MODULES_ROOT,
  );
  if (!fs.existsSync(runRoot)) throw new Error(`controlled full-run root is missing: ${runRoot}`);
  const relativeToCache = path.relative(cacheRoot, outputRoot);
  if (relativeToCache === "" || (!relativeToCache.startsWith("..") && !path.isAbsolute(relativeToCache))) {
    throw new Error("output root must not be the read-only cache root or one of its descendants");
  }
  const preflight = preflightInputs(runRoot, cacheRoot);
  const tools = loadPinnedTools(nodeModulesRoot);
  fs.mkdirSync(path.join(outputRoot, "raw"), { recursive: true });
  const context = { runRoot, outputRoot, cacheRoot, nodeModulesRoot, tools };
  const results = [];
  for (const dimension of DIMENSIONS) {
    const result = await benchmarkDimension(context, dimension);
    results.push(result);
    fs.writeFileSync(
      path.join(outputRoot, "raw", `vanilla-${dimension}.json`),
      `${JSON.stringify(result, null, 2)}\n`,
    );
    process.stdout.write(
      `[gas] N=${dimension} overall=${result.overall} deploy=${result.benchmark_deployment.gas_used} ` +
        `runtime=${result.bytecode.compiled_runtime_bytecode_bytes}B ` +
        `eip170=${result.bytecode.eip170_deployable}\n`,
    );
  }
  const verification = buildVerification(results);
  const summary = {
    schema_version: 1,
    generated_at: new Date().toISOString(),
    overall: verification.overall,
    classification:
      "fresh Vanilla direct-verifier gas/deployment evidence; N=128 unlimited result is benchmark-only and not deployable under EIP-170",
    run_root: runRoot,
    cache_root: cacheRoot,
    output_root: outputRoot,
    preflight,
    protocol: {
      dimensions: DIMENSIONS,
      compiler: "solc-js 0.8.33, optimizer 200, Shanghai",
      chain: "Ganache 7.9.2, Shanghai; standard EIP-170 except explicit over-limit control",
      client: "ethers 6.16.0",
      proof_transactions: "warmup-00 once; measured-01..05 once each",
      invalid_control: "mutate measured-01 public input; static call only",
    },
    results: results.map((result) => ({
      target: result.target,
      dimension: result.dimension,
      raw: `raw/vanilla-${result.dimension}.json`,
      raw_sha256: sha256(`${JSON.stringify(result, null, 2)}\n`),
      overall: result.overall,
      deployment_gas: result.benchmark_deployment.gas_used,
      measured_verify_gas: result.valid_control.measured_transactions.map(
        (entry) => entry.receipt.gas_used,
      ),
      creation_bytecode_bytes: result.bytecode.creation_bytecode_bytes,
      runtime_bytecode_bytes: result.bytecode.compiled_runtime_bytecode_bytes,
      eip170_deployable: result.bytecode.eip170_deployable,
      unlimited_contract_size_benchmark_only:
        result.benchmark_deployment.allow_unlimited_contract_size,
      runtime_matches_compiler: result.bytecode.onchain_runtime_matches_compiled,
    })),
  };
  fs.writeFileSync(
    path.join(outputRoot, "benchmark.json"),
    `${JSON.stringify(summary, null, 2)}\n`,
  );
  fs.writeFileSync(path.join(outputRoot, "benchmark.csv"), csv(buildCsvRows(results)));
  fs.writeFileSync(
    path.join(outputRoot, "verification.json"),
    `${JSON.stringify(verification, null, 2)}\n`,
  );
  process.stdout.write(`${JSON.stringify(verification, null, 2)}\n`);
  if (verification.overall !== "PASS") process.exitCode = 1;
}

const isMain =
  process.argv[1] != null && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) await main();

