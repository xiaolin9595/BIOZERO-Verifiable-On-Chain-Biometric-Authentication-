# Fig. 3 full-run incidents and exclusions

## Shared-cache write incident

An initial fresh latency command was started against
`/home/lzb/BioZero_remote/cache`. The recovered runner removes and rewrites
`proof.json` on each proof attempt, and `compute-witness` rewrites both
`witness` and `out.wtns`. The command was stopped as soon as this behavior was
identified. Before it stopped, the shared N=2 and N=4 `out.wtns` mtimes were
updated; proof files were also transiently removed/replaced.

Those mutable files are **not used as recovered historical evidence**. The
historical campaign claim is based only on the already mirrored raw CSV,
summary CSV, logs, scripts, and immutable circuit-specific `out`,
`proving.key`, `verification.key`, and `verifier.sol` hashes. The latter four
were not rewritten by the incident.

The accepted fresh campaign uses
`/home/lzb/BioZero_remote/cache-fig3-full-20261028`. Only immutable `out`,
`proving.key`, `verification.key`, and `verifier.sol` are hard-linked from the
shared cache. Before measurement, `main.zok`, `proof.json`, `witness`, and
`out.wtns` are deleted from the clone and recreated privately.

## All-single-thread diagnostic exclusion

The first isolated-cache attempt set `RAYON_NUM_THREADS=1` for every Vanilla
dimension. It completed N=2 and N=4, but N=4 was much slower than the recovered
campaign. A script audit then established that the old campaign used the
default Rayon configuration for N=2..32 and single-thread mode only for N=64,
N=128, and the selected BioZero fixed point.

The all-single-thread output was preserved remotely under a directory named
`fig3_full_20261028_diagnostic_all_single_*`, but is diagnostic-only and is not
merged into the accepted summary.

## Competing-load exclusion

Before the accepted campaign, another user-owned compute suite was observed
running `r11_completion_setup` at roughly five to six CPU cores. The accepted
runner waits until all actual `r11_completion_setup` and ZoKrates compute
processes have been absent for four consecutive 30-second checks. Immutable
artifact hashing happens outside the timed benchmark, followed by another
stable-idle gate. Host load and CPU-frequency snapshots are retained in the
resource logs.

## Resource-monitor restart

The auxiliary per-child `/proc` sampler exited during N=64 after a process
terminated between the sampler's existence check and its read of
`/proc/<pid>/stat`. The proving campaign itself was not interrupted, and the
segment-level `/usr/bin/time -v` log remained active. The sampler was patched
to tolerate this race and restarted during the then-active proof; existing TSV
rows were appended rather than overwritten. Consequently, the first N=64
proof and all post-restart proofs have detailed child records, while the gap is
covered only by raw wall-clock samples and segment-level resource accounting.

## Chain-validator reporting repair

The first complete chain pass correctly produced successful unlimited-size
receipts for N=128 and a reverted deployment under the standard contract-size
limit, but the validator inspected only ethers' top-level short error string
and therefore classified the expected standard-limit failure as FAIL. The
first-pass JSON and logs are preserved under
`fresh/diagnostic-chain-first-attempt/`.

The validator was amended to retain the failure receipt, compiled runtime
size, the 24,576-byte EIP-170 limit, and its classification basis. A subsequent
full pass completed BioZero and N=2..64 before a field-name typo stopped it at
N=128. Those seven completed outputs were retained; only N=128 chain
validation was rerun after correcting `deployedBytecode` to
`runtimeBytecode`. The final combined `fresh/chain/summary.json` is 8/8 PASS.
No latency or native-proof measurement was rerun or altered during this repair.

## Native constraint parser repair

The native inspection logs contained the correct `constraint_count` for every
target. An overly broad fallback regular expression initially captured the
`128` in `bn128` instead. The parser was tightened to prefer the explicit
`constraint_count:` field, and the local derived validation JSON/summary was
regenerated from the preserved inspection logs. Proof, key, verifier, and
control results were unchanged.

