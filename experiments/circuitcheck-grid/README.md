# CircuitCheck seven-size reconstruction driver

This directory is a self-contained isolated extension of `../current`. It adds CircuitCheck entry
circuits for `N={2,4,8,16,32,64,128}` without modifying the preserved 128/512
reconstruction or its evidence. The reviewed generic `AuthDistance` template and
its two local circuit libraries are copied here so a remote run does not depend on
a sibling path; all seven entry circuits import that one local template.

The driver creates fresh, local, single-party Groth16 benchmark keys. They are not
production keys and must never be deployed outside an ephemeral benchmark chain.
No checked-in file claims measurements that were not produced by a local run.

## Pinned protocol

- Circom 2.2.3 (`circom2` npm 0.2.23), snarkjs 0.7.6, circomlib 2.0.5.
- solc-js 0.8.33, optimizer enabled with 200 runs, Shanghai EVM.
- Ganache 7.9.2, Shanghai hardfork, chain id 31337.
- ethers 6.16.0.
- Proof timing: one warmup plus ten measured cold pipeline processes per size.
  `endToEndMs` begins immediately before witness calculation and ends after the
  proof/public JSON writes; mean, sample SD, and median are recorded.
- Each cold pipeline is wrapped by GNU `/usr/bin/time -v`. Its Maximum resident
  set is kept separate from Node `process.resourceUsage().maxRSS`; the final
  verification gate requires all ten GNU-time RSS samples. On systems where
  `/usr/bin/time` is not GNU time, set `BIOZERO_GRID_GNU_TIME` to the GNU binary.
- Bare Solidity verifier gas: one warmup transaction plus five measured valid
  transactions per size. The six transactions use warmup-01 and measured-01..05
  proof/public pairs respectively; a mutated public input must return `false`.
- Creation/runtime bytecode, deployed runtime equality, and EIP-170 status are
  recorded for every verifier.

## Full run

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm run experiment
```

`npm run experiment` runs inputs, fresh setup, proof benchmarks, bare-verifier gas,
self-checks, and the final manifest. The fresh powers-of-tau and zkey contributions
use operating-system entropy; their hashes make each run auditable, not bit-for-bit
identical to another fresh ceremony. Copy this directory without `node_modules`,
AppleDouble `._*` metadata, or generated `build/`/`results/`, then run `npm ci`; no
sibling reconstruction directory is required. The manifest also excludes
`node_modules` and AppleDouble metadata by construction.

For a lightweight compile-and-witness check (no powers-of-tau ceremony and no proofs):

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm run smoke
```

All scripts accept `--dimensions=2,4,...` for diagnostic subsets. A publishable full
run must use the default seven-size grid. `BIOZERO_GRID_WARMUPS` and
`BIOZERO_GRID_REPETITIONS` change diagnostic proof counts; proof defaults are 1
warmup plus 10 measured. The gas protocol is fixed at 1 warmup plus 5 measured.

## Audit outputs

- `results/setup.json`: circuit constraints and matching zkey/verifier hashes.
- `results/proving.json`, `results/proving-raw.csv`, `results/proving/raw/`: raw
  end-to-end witness+prove/write and verify samples, optional GNU time output, and
  proof material.
- `results/verifier-gas.json`, `results/verifier-gas-raw.csv`,
  `results/verifier-gas/raw/`: raw receipts, valid/invalid controls, bytecode.
- `results/verification.json`: invariant checks; failure stops the full run.
- `results/manifest.json` and `results/manifest.csv`: versions, SHA-256 hashes,
  sizes, and the classification of sources, generated artifacts, and raw evidence.

`npm run setup` removes only this directory's `build/`, generated verifier sources,
and setup logs. Existing results are overwritten only by the stage that owns them.
