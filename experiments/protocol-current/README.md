# BioZERO current-artifact reconstruction (2026-10-27)

This directory is an isolated reconstruction copied from `BioZERO_TR_v3/artifact`.
It does not alter the paper artifact and does not claim to recover historical keys,
timings, or missing source. The added drivers close the reproducible path:

`Circom source -> fresh benchmark-only setup -> matching Solidity verifier -> compile/deploy/call`.

The two unpacked wrappers under `circuits/reconstructed/` are explicitly marked
**RECONSTRUCTED** because their parameters are uniquely specified by the generic
`AuthDistance` template and `generate-inputs.mjs`. The two missing distance-only
circuits are deliberately not guessed: their exact constraint design is not uniquely
determined by the delivered material.

## Run from scratch

```sh
npm ci --ignore-scripts --no-audit --no-fund
node scripts/generate-inputs.mjs
npm run reconstruct:setup
BIOZERO_REPETITIONS=5 npm run benchmark:packed
npm run benchmark:complete
node scripts/compile-reconstructed-ablation.mjs
node scripts/record-environment.mjs
node scripts/verify-reproduction.mjs
```

`reconstruct:setup` deletes only this directory's `build/` output and generates a
fresh power-15 phase-1 transcript, fresh per-circuit zkeys, verification keys, and
matching Solidity verifiers. These are local single-party benchmark keys and must
never be used in production.

Results are in `results/*.json` and `results/*.csv`; raw stdout/stderr is under
`logs/`. `results/verification.json` is the final machine-readable self-check.
Packed timing/RSS values are new macOS/Apple M4 measurements and are not historical
Windows/i9 results. RSS means cold child-process `process.resourceUsage().maxRSS`.

## This run

Environment: macOS 15.3.1 arm64, Apple M4 (10 logical processors), 16 GiB RAM,
Node 22.19.0, circom 2.2.3, snarkjs 0.7.6, solc 0.8.36, Ganache 7.9.2.

| Strategy | N / sampled coordinates | Repetitions | Median gas |
|---|---:|---:|---:|
| Spot eta=1 | 128 / 7 | 3 | 4,124,394 |
| Spot eta=2 | 128 / 14 | 3 | 5,111,692 |
| Spot eta=4 | 128 / 28 | 3 | 7,107,360 |
| Spot eta=8 | 128 / 56 | 3 | 11,196,527 |
| FullCheck | 128 / 128 | 3 | 22,097,617 |
| CircuitCheck | 128 | 3 | 255,023 |
| CircuitCheck | 512 | 3 | 255,011 |

| Packed circuit | Constraints | Cold processes | Witness median | Prove median | Verify median | Prove max-RSS median |
|---|---:|---:|---:|---:|---:|---:|
| N=128 | 7,660 | 5 | 37.43 ms | 568.70 ms | 139.28 ms | 484.80 MiB |
| N=512 | 27,118 | 5 | 71.69 ms | 1,003.23 ms | 155.41 ms | 698.22 MiB |

The reconstructed unpacked wrappers compile to 38,464 and 151,360 constraints;
relative to the delivered packed circuits this recomputes reductions of 80.1% and
82.1%. This agreement is evidence for the wrappers' inferred parameters, not proof
that the missing source files were recovered.

All ten packed proof verifications returned true. Complete-gas negative controls
passed for replay/stale proof/wrong enrollment (homomorphic) and replay/wrong nonce
(CircuitCheck); the original harness only runs the tampered-response control for
FullCheck, so sampled rows remain explicitly `not-run` in the CSV.

Fresh gas medians differ from the recorded rows by at most 0.05%; the exact deltas
are in `results/comparison-to-recorded.json`. Packed constraint counts match exactly,
while timing and RSS differ as expected across host and profiler semantics.

`npm audit --omit=dev` reported 20 transitive findings (5 high, 2 moderate, 13 low),
including pinned ethers 5.x/elliptic and `ws`. They are retained to preserve the
paper's exact benchmark dependency graph. This directory is unsafe benchmark code,
not a network-facing service or production deployment.

## Upstream artifact README (preserved below)

# BioZero artifact: complete verifiers, circuits, measurements

This folder holds the code and recorded outputs behind the evaluation section.
Everything here is **benchmark code**: the Pedersen generator `h = 5G` has a known discrete log,
the homomorphic threshold circuit is a measurement stand-in, and all Groth16 keys come from a local,
single-party setup. Never deploy any of it.

## Layout

| Path | Content |
|---|---|
| `contracts/HomomorphicCompleteVerifier.sol` | complete FullCheck/SpotCheck authentication (nonce, enrollment digest, Fiat-Shamir challenge, sampling from `prevrandao`, six equations per examined coordinate, reconstruction, Groth16 threshold verifier) |
| `contracts/CircuitCompleteVerifier.sol` | complete CircuitCheck authentication with the same state handling |
| `contracts/PedersenSamplingVerifier.sol` | equations-and-reconstruction kernel (no state, no challenge, no threshold verifier) |
| `contracts/generated/` | Groth16 verifiers exported by snarkjs for the 128- and 512-dimensional reference circuits and the threshold stand-in |
| `circuits/` | `auth_distance*.circom` (CircuitCheck reference circuit, packed 16-bit coordinates, Poseidon commitments), `threshold_standin.circom` |
| `scripts/` | `hom-complete-gas.mjs`, `circuit-complete-gas.mjs`, `pedersen-gas-benchmark.mjs`, `generate-inputs.mjs`, `commitment.mjs`, `lib/sampling.mjs` |
| `inputs/generated/` | witness inputs of the reference circuits |
| `data/` | recorded outputs and SHA-256 sums used by the paper (`SHA256SUMS`) |

## Toolchain (pinned)

Node.js 24.19.0, circom 2.2.3, snarkjs 0.7.6, circomlib 2.0.5, circomlibjs 0.1.7, ganache 7.9.2,
solc 0.8.36 (optimizer 200 runs, Shanghai), ethers 5.8.0. `toolchain.ps1` downloads and verifies the
Node.js and circom binaries (Windows). Recorded runs: Windows 11, Intel Core i9-9900T, 31.79 GiB.

## Reproduce

```
npm ci
# compile circuits and make a local benchmark-only trusted setup (powers of tau 2^15)
powershell -ExecutionPolicy Bypass -File ./benchmark.ps1
powershell -ExecutionPolicy Bypass -File ./prove-benchmark.ps1
# threshold stand-in circuit and its verifier
circom circuits/threshold_standin.circom --r1cs --wasm --sym --O2 -l node_modules -o build/hom-complete-gas
# setup, contribute, and export contracts/generated/Groth16VerifierThreshold.sol and
# build/hom-complete-gas/ts_final.zkey with snarkjs, as in benchmark.ps1
node scripts/generate-inputs.mjs
node scripts/pedersen-gas-benchmark.mjs      # kernel gas          -> build/pedersen-gas/results.json
node scripts/hom-complete-gas.mjs            # complete homomorphic -> build/hom-complete-gas/results.json
node scripts/circuit-complete-gas.mjs        # complete CircuitCheck -> build/circuit-complete-gas/results.json
```

The gas columns are the median of three authentications, i.e. the steady-state cost. The first authentication of an identity costs about 17,000 gas more because it writes the nonce slot for the first time (the recorded `gasUsed` lists show this). The remaining spread between runs, under 0.5 percent for the homomorphic verifier, comes from different transcripts (zero-byte counts in calldata and the sampled coordinates). Proving times and memory depend on the machine and on cold-process conditions. The transcript generator in `hom-complete-gas.mjs` is deterministic; `circuit-complete-gas.mjs` draws fresh random salts for each probe.

## Status of what was run

The scripts were run from the original project directory (`prototype/route-a`), not from this copy.
The copy omits `node_modules`, the compiled circuits, the zkeys, and the powers-of-tau files because of
size and because the keys must not be reused. Re-running from this folder requires the steps above.
