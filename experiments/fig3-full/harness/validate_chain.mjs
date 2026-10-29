#!/usr/bin/env node

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const cacheRoot = path.resolve(process.env.FIG3_CACHE_ROOT ?? 'cache-fig3-full-20261028');
const outputRoot = path.resolve(process.env.FIG3_CHAIN_OUTPUT ?? 'results/fig3_full_20261028/chain');
const nodeModulesRoot = path.resolve(process.env.FIG3_NODE_MODULES ?? 'src/experiments');
const require = createRequire(path.join(nodeModulesRoot, 'package.json'));
const solc = require('solc');
const ganache = require('ganache');
const ethers = require('ethers');
const { BrowserProvider, ContractFactory } = ethers;

function packageVersion(packageName) {
  let directory = path.dirname(require.resolve(packageName));
  while (directory !== path.dirname(directory)) {
    const candidate = path.join(directory, 'package.json');
    if (fs.existsSync(candidate)) {
      const packageJson = JSON.parse(fs.readFileSync(candidate, 'utf8'));
      if (packageJson.name === packageName) return packageJson.version;
    }
    directory = path.dirname(directory);
  }
  throw new Error(`Unable to resolve package version for ${packageName}`);
}

const targets = [
  { label: 'biozero-fixed', dimension: null, workspace: 'groth16_biozero' },
  ...[2, 4, 8, 16, 32, 64, 128].map((dimension) => ({
    label: `vanilla-${dimension}`,
    dimension,
    workspace: `groth16_vanilla_${dimension}`,
  })),
];

function sha256(data) {
  return crypto.createHash('sha256').update(data).digest('hex');
}

function compileVerifier(sourceCode) {
  const input = {
    language: 'Solidity',
    sources: { 'verifier.sol': { content: sourceCode } },
    settings: {
      optimizer: { enabled: true, runs: 200 },
      evmVersion: 'shanghai',
      outputSelection: {
        '*': { '*': ['abi', 'evm.bytecode.object', 'evm.deployedBytecode.object'] },
      },
    },
  };
  const output = JSON.parse(solc.compile(JSON.stringify(input)));
  const fatal = (output.errors ?? []).filter((entry) => entry.severity === 'error');
  if (fatal.length > 0) {
    throw new Error(fatal.map((entry) => entry.formattedMessage).join('\n'));
  }
  const contracts = output.contracts?.['verifier.sol'] ?? {};
  const verifier = contracts.Verifier ?? Object.values(contracts)[0];
  if (!verifier?.abi || !verifier?.evm?.bytecode?.object) {
    throw new Error('Solidity compiler produced no Verifier artifact');
  }
  return {
    abi: verifier.abi,
    bytecode: `0x${verifier.evm.bytecode.object}`,
    runtimeBytecode: `0x${verifier.evm.deployedBytecode.object}`,
  };
}

function proofForAbi(proofJson, verifyFunction) {
  const proof = proofJson.proof;
  const proofParameter = verifyFunction.inputs[0];
  const namedProof = {
    a: { X: proof.a[0], Y: proof.a[1] },
    b: { X: [proof.b[0][0], proof.b[0][1]], Y: [proof.b[1][0], proof.b[1][1]] },
    c: { X: proof.c[0], Y: proof.c[1] },
  };
  const proofValue = proofParameter.type === 'tuple' ? namedProof : [proof.a, proof.b, proof.c];
  return [proofValue, proofJson.inputs];
}

function mutateFirstPublicInput(inputs) {
  if (!Array.isArray(inputs) || inputs.length === 0) throw new Error('Proof has no public inputs');
  const mutated = [...inputs];
  const original = String(mutated[0]);
  const next = BigInt(original) + 1n;
  mutated[0] = original.startsWith('0x')
    ? `0x${next.toString(16).padStart(original.length - 2, '0')}`
    : next.toString();
  return mutated;
}

function receiptRecord(transaction, receipt) {
  return {
    transaction_hash: transaction.hash,
    block_number: receipt.blockNumber,
    block_hash: receipt.blockHash,
    receipt_status: Number(receipt.status),
    gas_used: Number(receipt.gasUsed),
    cumulative_gas_used: Number(receipt.cumulativeGasUsed),
    contract_address: receipt.contractAddress,
    from: receipt.from,
    to: receipt.to,
  };
}

async function standardSizeLimitControl(compiled) {
  const eip170RuntimeLimitBytes = 24_576;
  const compiledRuntimeBytes = (compiled.runtimeBytecode.length - 2) / 2;
  const standardProvider = ganache.provider({
    logging: { quiet: true },
    wallet: { totalAccounts: 1, deterministic: true },
    chain: { hardfork: 'shanghai', chainId: 2337, allowUnlimitedContractSize: false },
    miner: { blockGasLimit: 60_000_000 },
  });
  try {
    const provider = new BrowserProvider(standardProvider);
    const signer = await provider.getSigner(0);
    const factory = new ContractFactory(compiled.abi, compiled.bytecode, signer);
    try {
      const contract = await factory.deploy({ gasLimit: 15_000_000 });
      const receipt = await contract.deploymentTransaction().wait();
      return {
        attempted: true,
        deployment_failed_as_expected: false,
        unexpected_receipt: receiptRecord(contract.deploymentTransaction(), receipt),
      };
    } catch (error) {
      const errorReceipt = error?.receipt ?? null;
      const messages = [
        error?.shortMessage,
        error?.message,
        error?.reason,
        error?.info?.error?.message,
        error?.error?.message,
        error?.cause?.message,
      ].filter((value) => value != null).map(String);
      const message = messages.join(' | ').slice(0, 4000);
      const explicitSizeReason = /code size|maximum code|EIP-170|exceeds maximum/i.test(message);
      const receiptStatusZero = errorReceipt != null && Number(errorReceipt.status) === 0;
      const runtimeExceedsLimit = compiledRuntimeBytes > eip170RuntimeLimitBytes;
      const failedAsExpected = runtimeExceedsLimit && (explicitSizeReason || receiptStatusZero);
      return {
        attempted: true,
        deployment_failed_as_expected: failedAsExpected,
        classification_basis: explicitSizeReason
          ? 'provider explicitly reported contract-code-size limit'
          : 'status=0 receipt under standard size limit with compiled runtime above EIP-170 limit',
        eip170_runtime_limit_bytes: eip170RuntimeLimitBytes,
        compiled_runtime_bytecode_bytes: compiledRuntimeBytes,
        runtime_exceeds_limit: runtimeExceedsLimit,
        explicit_size_reason: explicitSizeReason,
        error_receipt: errorReceipt == null ? null : {
          transaction_hash: errorReceipt.hash,
          block_number: errorReceipt.blockNumber,
          block_hash: errorReceipt.blockHash,
          receipt_status: Number(errorReceipt.status),
          gas_used: Number(errorReceipt.gasUsed),
          cumulative_gas_used: Number(errorReceipt.cumulativeGasUsed),
          contract_address: errorReceipt.contractAddress,
          from: errorReceipt.from,
          to: errorReceipt.to,
        },
        error: message,
      };
    }
  } finally {
    await standardProvider.disconnect();
  }
}

async function validateTarget(target) {
  const workspace = path.join(cacheRoot, target.workspace);
  const verifierPath = path.join(workspace, 'verifier.sol');
  const proofPath = path.join(workspace, 'proof.json');
  const verificationKeyPath = path.join(workspace, 'verification.key');
  for (const requiredPath of [verifierPath, proofPath, verificationKeyPath]) {
    if (!fs.existsSync(requiredPath)) throw new Error(`Missing required artifact: ${requiredPath}`);
  }

  const verifierSource = fs.readFileSync(verifierPath, 'utf8');
  const proofText = fs.readFileSync(proofPath, 'utf8');
  const proofJson = JSON.parse(proofText);
  const compiled = compileVerifier(verifierSource);
  const warmupRepeats = target.dimension == null ? 5 : 1;
  const measuredRepeats = target.dimension == null ? 30 : 5;
  const standardContractSizeControl = target.dimension === 128
    ? await standardSizeLimitControl(compiled)
    : null;
  const providerConfiguration = {
    logging: { quiet: true },
    wallet: { totalAccounts: 3, deterministic: true },
    chain: { hardfork: 'shanghai', chainId: 1337, allowUnlimitedContractSize: true },
    miner: { blockGasLimit: 60_000_000 },
  };
  const ganacheProvider = ganache.provider(providerConfiguration);
  const provider = new BrowserProvider(ganacheProvider);

  try {
    const signer = await provider.getSigner(0);
    const factory = new ContractFactory(compiled.abi, compiled.bytecode, signer);
    const contract = await factory.deploy();
    const deploymentTransaction = contract.deploymentTransaction();
    const deploymentReceipt = await deploymentTransaction.wait();
    await contract.waitForDeployment();
    const address = await contract.getAddress();
    const onchainRuntime = await provider.getCode(address);
    const verifyFunction = compiled.abi.find((entry) => entry.type === 'function' && entry.name === 'verifyTx');
    if (!verifyFunction) throw new Error('verifyTx is absent from compiled ABI');
    const verifyTx = contract.getFunction('verifyTx');
    const [proofArgument, publicInputs] = proofForAbi(proofJson, verifyFunction);

    const validStaticReturn = await verifyTx.staticCall(proofArgument, publicInputs);
    const validEstimate = await verifyTx.estimateGas(proofArgument, publicInputs);
    const warmupTransactions = [];
    for (let run = 0; run < warmupRepeats; run += 1) {
      const transaction = await verifyTx.send(proofArgument, publicInputs, {
        gasLimit: (validEstimate * 12n) / 10n + 50_000n,
      });
      const receipt = await transaction.wait();
      warmupTransactions.push({ run, ...receiptRecord(transaction, receipt) });
    }
    const validTransactions = [];
    for (let run = 0; run < measuredRepeats; run += 1) {
      const transaction = await verifyTx.send(proofArgument, publicInputs, {
        gasLimit: (validEstimate * 12n) / 10n + 50_000n,
      });
      const receipt = await transaction.wait();
      validTransactions.push({ run, ...receiptRecord(transaction, receipt) });
    }

    const invalidInputs = mutateFirstPublicInput(publicInputs);
    const invalidStaticReturn = await verifyTx.staticCall(proofArgument, invalidInputs);
    const invalidEstimate = await verifyTx.estimateGas(proofArgument, invalidInputs);
    const invalidTransaction = await verifyTx.send(proofArgument, invalidInputs, {
      gasLimit: (invalidEstimate * 12n) / 10n + 50_000n,
    });
    const invalidReceipt = await invalidTransaction.wait();

    const result = {
      schema_version: 1,
      experiment_label: 'fresh Fig. 3 full-chain validation; recovered circuit semantics with documented shadow fix',
      target: target.label,
      dimension: target.dimension,
      configuration: {
        solc_version: solc.version(),
        optimizer: { enabled: true, runs: 200 },
        evm_version: 'shanghai',
        ganache_version: packageVersion('ganache'),
        ethers_version: ethers.version,
        allow_unlimited_contract_size: true,
        warmup_transaction_repeats: warmupRepeats,
        measured_transaction_repeats: measuredRepeats,
      },
      artifacts: {
        verifier_path: verifierPath,
        verifier_bytes: Buffer.byteLength(verifierSource),
        verifier_sha256: sha256(verifierSource),
        proof_path: proofPath,
        proof_bytes: Buffer.byteLength(proofText),
        proof_sha256: sha256(proofText),
        verification_key_path: verificationKeyPath,
        verification_key_bytes: fs.statSync(verificationKeyPath).size,
        verification_key_sha256: sha256(fs.readFileSync(verificationKeyPath)),
      },
      deployment: {
        ...receiptRecord(deploymentTransaction, deploymentReceipt),
        creation_bytecode_bytes: (compiled.bytecode.length - 2) / 2,
        compiled_runtime_bytecode_bytes: (compiled.runtimeBytecode.length - 2) / 2,
        onchain_runtime_bytecode_bytes: (onchainRuntime.length - 2) / 2,
        onchain_runtime_matches_compiled: onchainRuntime.toLowerCase() === compiled.runtimeBytecode.toLowerCase(),
      },
      valid_control: {
        static_return: validStaticReturn,
        estimated_gas: Number(validEstimate),
        warmup_transactions: warmupTransactions,
        transactions: validTransactions,
      },
      invalid_public_input_control: {
        mutation: 'public inputs[0] += 1; proof group elements unchanged',
        static_return: invalidStaticReturn,
        estimated_gas: Number(invalidEstimate),
        ...receiptRecord(invalidTransaction, invalidReceipt),
        interpretation: 'ZoKrates verifier returns false rather than reverting, so a status-1 receipt is expected.',
      },
      standard_eip170_control: standardContractSizeControl,
    };
    result.acceptance = {
      valid_static_true: result.valid_control.static_return === true,
      valid_receipts_successful: result.valid_control.transactions.length === measuredRepeats
        && result.valid_control.transactions.every((entry) => entry.receipt_status === 1),
      invalid_static_false: result.invalid_public_input_control.static_return === false,
      runtime_matches_compiler: result.deployment.onchain_runtime_matches_compiled,
      standard_eip170_behavior: target.dimension === 128
        ? result.standard_eip170_control?.deployment_failed_as_expected === true
        : true,
    };
    result.overall = Object.values(result.acceptance).every(Boolean) ? 'PASS' : 'FAIL';
    return result;
  } finally {
    await ganacheProvider.disconnect();
  }
}

fs.mkdirSync(outputRoot, { recursive: true });
const results = [];
const requestedTargets = new Set(
  String(process.env.FIG3_TARGET_LABELS ?? '')
    .split(',')
    .map((label) => label.trim())
    .filter(Boolean),
);
const selectedTargets = requestedTargets.size === 0
  ? targets
  : targets.filter((target) => requestedTargets.has(target.label));
if (selectedTargets.length === 0) throw new Error('FIG3_TARGET_LABELS selected no known targets');
for (const target of selectedTargets) {
  const result = await validateTarget(target);
  results.push(result);
  fs.writeFileSync(path.join(outputRoot, `${target.label}.json`), `${JSON.stringify(result, null, 2)}\n`);
  process.stdout.write(`${target.label}: ${result.overall}\n`);
}
const summary = {
  schema_version: 1,
  overall: results.every((entry) => entry.overall === 'PASS') ? 'PASS' : 'FAIL',
  targets: results.map((entry) => ({
    target: entry.target,
    dimension: entry.dimension,
    overall: entry.overall,
    verifier_gas_runs: entry.valid_control.transactions.map((row) => row.gas_used),
    deployment_gas: entry.deployment.gas_used,
    runtime_bytecode_bytes: entry.deployment.compiled_runtime_bytecode_bytes,
    valid_static_return: entry.valid_control.static_return,
    invalid_static_return: entry.invalid_public_input_control.static_return,
    standard_eip170_deployment_failed: entry.standard_eip170_control?.deployment_failed_as_expected ?? null,
  })),
};
fs.writeFileSync(path.join(outputRoot, 'summary.json'), `${JSON.stringify(summary, null, 2)}\n`);
if (summary.overall !== 'PASS') process.exitCode = 1;
