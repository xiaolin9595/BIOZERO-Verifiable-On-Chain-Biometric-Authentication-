# Controlled Vanilla ZoKrates harness

This harness reuses the already-hashed Vanilla setup in
`/home/lzb/BioZero_remote/cache-fig3-full-20261028` without compiling or
running setup. It runs one warmup plus ten measured attempts for each of
N=2,4,8,16,32,64,128. `smoke` runs only the N=2 warmup attempt.

Each timed `compute-witness` and `generate-proof` process is an independent
child pinned to CPU0 with all relevant thread-pool counts fixed at one. A
sampler pinned to CPU1 records load, CPU0/CPU20 frequency and counters, and
tasks scheduled on sibling CPU20. Four consecutive clean 30-second windows
with no process named `zokrates` or `r11` are required before timing begins.

The harness keeps every proof as a read-only per-attempt artifact, including
its public inputs, SHA-256, verification logs, `/usr/bin/time -v` output, and
stdout/stderr. Large witness files are hashed and sized, then removed after
successful verification to bound disk usage.

```bash
./run_controlled_vanilla.sh smoke /var/tmp/biozero-circuitcheck-vs-vanilla-20261028/runs/smoke
./run_controlled_vanilla.sh full /var/tmp/biozero-circuitcheck-vs-vanilla-20261028/runs/full
```

## Direct verifier gas and deployment stage

After the controlled full run has produced all seven `warmup-00` and
`measured-01..05` proofs, run the separate chain stage. It compiles only the
read-only cached `verifier.sol` files in memory with solc-js 0.8.33, optimizer
200 and Shanghai, then uses Ganache 7.9.2 and ethers 6.16.0. It writes
`benchmark.json`, `benchmark.csv`, per-dimension raw JSON, and
`verification.json` below `<FULL_RUN_ROOT>/verifier-gas`.

```bash
node benchmark_vanilla_verifier_gas.mjs \
  /var/tmp/biozero-circuitcheck-vs-vanilla-20261028/runs/full-20261028T1754-controlled
```

The normal path keeps the standard EIP-170 contract-size limit. If a compiled
runtime exceeds 24,576 bytes (expected only for N=128), the harness first
records the failed standard deployment and then uses an explicit
`allowUnlimitedContractSize=true` local chain. Such a result is marked
benchmark-only and `eip170_deployable=false`; it is never reported as a
deployable verifier.

The remote dependency root defaults to `/home/lzb/BioZero_remote/src/experiments`.
Override it only with a package containing the exact pinned versions:

```bash
VANILLA_GAS_NODE_MODULES=/path/to/pinned/package \
  node benchmark_vanilla_verifier_gas.mjs FULL_RUN_ROOT OPTIONAL_OUTPUT_ROOT
```
