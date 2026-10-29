# Fig. 3 full-run runbook

The accepted execution runs on SSH host `206160G` under
`/home/lzb/BioZero_remote`. It avoids `/tmp`; temporary harness files live in
`/var/tmp/biozero-fig3-full-lzb`, while the hard-linkable circuit cache remains
on the `/home` filesystem.

## Protocol

- Vanilla N=2,4,8,16,32: default Rayon configuration, one warm-up plus five
  measured witness+proof runs, native verification after every proof.
- Vanilla N=64,128: `RAYON_NUM_THREADS=1`, one warm-up plus five measured
  witness+proof runs, native verification after every proof.
- BioZero fixed: selected from the final high-dimension segment with
  `RAYON_NUM_THREADS=1`, one warm-up plus five measured runs.
- Setup is not regenerated: each target reuses its circuit-specific compiled
  `out`, Groth16 proving key, verification key, and exported verifier. Witness
  and proof files are regenerated in an isolated mutable cache.
- Chain validation recompiles each matching exported verifier with solc-js
  0.8.33, optimizer enabled with 200 runs, Shanghai EVM; it deploys on an
  in-process Ganache 7.9.2 chain. Vanilla uses one warm-up plus five measured
  verification transactions; BioZero uses five warm-ups plus 30 measured
  transactions. The harness checks a public-input mutation returns false and
  confirms N=128 fails the standard EIP-170 deployment limit while the explicit
  local `allowUnlimitedContractSize=true` configuration succeeds.

## Commands

The complete orchestration is saved in
`harness/run_protocol_split.sh`. The remote launch is:

```sh
ssh 206160G 'env \
  BIOZERO_REMOTE_ROOT="$HOME/BioZero_remote" \
  FIG3_CACHE_ROOT="$HOME/BioZero_remote/cache-fig3-full-20261028" \
  FIG3_RESULT_ROOT="$HOME/BioZero_remote/results/fig3_full_20261028" \
  FIG3_HARNESS_ROOT=/var/tmp/biozero-fig3-full-lzb/harness \
  /var/tmp/biozero-fig3-full-lzb/harness/run_protocol_split.sh'
```

The orchestrator records the exact two `npm run latency` commands, native
proof/key/verifier checks, five-run chain checks, resource monitoring, and
artifact hashes in its logs and output manifests.

After completion, only raw/summary/log files, JSON, scripts, hashes, and small
proof/VK/verifier/source artifacts are copied back. Multi-gigabyte `out`,
proving keys, witnesses, and `out.wtns` remain remote; their byte sizes and
SHA-256 values are preserved in the manifests.

