#!/usr/bin/env node

import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';

const root = path.resolve(process.env.BIOZERO_REMOTE_ROOT ?? path.join(os.homedir(), 'BioZero_remote'));
const outputPath = path.resolve(process.env.FIG3_ENV_OUTPUT ?? path.join(root, 'results/fig3_full_20261028/environment.json'));
const zokratesPath = path.resolve(process.env.BIOZERO_ZOKRATES_BIN ?? path.join(root, 'zokrates-0.8.8-linux/zokrates'));
const experimentRoot = path.join(root, 'src/experiments');
const require = createRequire(path.join(experimentRoot, 'package.json'));

function command(commandName, args = []) {
  return execFileSync(commandName, args, { encoding: 'utf8' }).trim();
}

function sha256File(filePath) {
  return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex');
}

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
  return null;
}

const result = {
  schema_version: 1,
  captured_at: new Date().toISOString(),
  hostname: os.hostname(),
  platform: os.platform(),
  release: os.release(),
  architecture: os.arch(),
  cpu: {
    logical_count: os.cpus().length,
    model: os.cpus()[0]?.model ?? null,
    lscpu: command('lscpu'),
  },
  memory: {
    physical_bytes: os.totalmem(),
    free_bytes_at_capture: os.freemem(),
    proc_meminfo: fs.readFileSync('/proc/meminfo', 'utf8'),
  },
  software: {
    node: process.version,
    npm: command('npm', ['--version']),
    zokrates: {
      path: zokratesPath,
      version: command(zokratesPath, ['--version']),
      bytes: fs.statSync(zokratesPath).size,
      sha256: sha256File(zokratesPath),
    },
    solc_js: packageVersion('solc'),
    ganache: packageVersion('ganache'),
    ethers: packageVersion('ethers'),
  },
  protocol: {
    vanilla_dimensions: [2, 4, 8, 16, 32, 64, 128],
    low_dimensions_rayon_num_threads: null,
    high_dimensions_rayon_num_threads: 1,
    biozero_fixed_rayon_num_threads: 1,
    warmup_runs_per_target: 1,
    measured_runs_per_target: 5,
    setup_policy: 'reuse circuit-specific out/proving.key/verification.key/verifier.sol; regenerate witness and proof in isolated mutable cache',
    solidity_optimizer: { enabled: true, runs: 200 },
    evm_version: 'shanghai',
    chain_policy: 'in-process Ganache with allowUnlimitedContractSize=true for N=128 reporting beyond EIP-170',
  },
  storage: {
    home: command('df', ['-h', os.homedir()]),
    var_tmp: command('df', ['-h', '/var/tmp']),
  },
};

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, `${JSON.stringify(result, null, 2)}\n`);
process.stdout.write(`${outputPath}\n`);
