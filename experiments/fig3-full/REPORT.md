# Fig. 3 full reconstruction report

## Outcome

The fresh exact-protocol reconstruction is complete and passes all 43 bundle
checks. It contains BioZero fixed plus every Vanilla point N=2,4,8,16,32,64,128;
no point is interpolated or extrapolated. Fresh results are the primary dataset.
The previously recovered complete 206160G campaign is retained separately for
comparison and is not overwritten.

Each proof target has one warm-up and five measured witness+proof runs. Vanilla
N=2..32 uses the default Rayon configuration; N=64,128 and BioZero fixed use
`RAYON_NUM_THREADS=1`, matching the recovered runner split. Circuit-specific
compiled programs and Groth16 setup artifacts are reused, while witnesses and
proofs are freshly generated in an isolated cache.

## Fresh primary results

Proof time is mean ± sample SD over five measured runs. Verifier gas is the
mean of five fresh receipts for each Vanilla point and 30 for BioZero fixed.
Creation size is the historical Fig. 3 bytecode-size convention; runtime size
is also reported because EIP-170 applies to runtime code.

| Target | Constraints | Proof time (s) | Proof bytes | Verifier gas | Deploy gas | Creation / runtime bytes | EIP-170 deployable |
|---|---:|---:|---:|---:|---:|---:|:---:|
| BioZero fixed | 109,900 | 2.728 ± 0.070 | 1,219 | 271,200 | 1,025,177 | 4,523 / 4,495 | yes |
| Vanilla N=2 | 439,240 | 5.701 ± 0.262 | 1,441 | 295,244 | 1,102,804 | 4,882 / 4,854 | yes |
| Vanilla N=4 | 877,629 | 10.306 ± 0.252 | 1,737 | 327,308 | 1,205,809 | 5,358 / 5,330 | yes |
| Vanilla N=8 | 1,754,406 | 20.292 ± 0.384 | 2,329 | 391,437 | 1,410,934 | 6,307 / 6,279 | yes |
| Vanilla N=16 | 3,507,959 | 40.740 ± 0.679 | 3,513 | 520,070 | 1,823,047 | 8,213 / 8,185 | yes |
| Vanilla N=32 | 7,015,064 | 80.398 ± 0.983 | 5,881 | 778,284 | 2,646,433 | 12,020 / 11,992 | yes |
| Vanilla N=64 | 14,029,273 | 351.191 ± 10.699 | 10,617 | 1,298,444 | 4,292,976 | 19,633 / 19,605 | yes |
| Vanilla N=128 | 28,057,690 | 699.007 ± 13.314 | 20,089 | 2,354,712 | 7,588,215 | 34,865 / 34,837 | **no** |

N=128 is not deployable on a standard EIP-170 chain: its 34,837-byte runtime
exceeds the 24,576-byte limit. The standard-limit control produced a status-0
deployment receipt. Its reported deploy gas and verifier gas come from an
explicitly configured local chain with `allowUnlimitedContractSize=true`,
where the same compiled verifier deployed and all five valid transactions
succeeded.

## Matching and controls

All eight targets pass the following checks:

- the proof verifies natively against its target-specific verification key;
- changing public input 0 by +1 while keeping the proof fixed is rejected;
- exporting a verifier from the same verification key reproduces the cached
  Solidity verifier byte-for-byte;
- on-chain valid static calls return true and all measured receipts have
  status 1;
- the tampered public-input static call returns false, with an additional
  on-chain negative-control transaction retained;
- deployed runtime bytecode matches the compiler output.

## Fresh versus recovered campaign

| Target | Fresh proof mean (s) | Recovered mean (s) | Delta |
|---|---:|---:|---:|
| BioZero fixed | 2.728 | 2.990 | -8.76% |
| N=2 | 5.701 | 11.034 | -48.33% |
| N=4 | 10.306 | 12.029 | -14.33% |
| N=8 | 20.292 | 20.916 | -2.98% |
| N=16 | 40.740 | 41.758 | -2.44% |
| N=32 | 80.398 | 82.363 | -2.39% |
| N=64 | 351.191 | 361.794 | -2.93% |
| N=128 | 699.007 | 727.289 | -3.89% |

Constraints, proof sizes, deployment gas, and creation-bytecode sizes match the
recovered campaign exactly. Fresh verifier gas differs by at most 120 gas
(0.0122%), consistent with freshly generated calldata. Proof-time differences
reflect a new run on the same host class under current load, cache, frequency,
and scheduling conditions; the short N=2 point is especially sensitive to
fixed overhead. Per the requested update policy, none of these fresh points is
discarded in favor of the recovered values.

## Environment and resource envelope

The accepted run used host `enine` (SSH alias `206160G`), Intel Xeon w7-3445,
40 logical CPUs, 251 GiB RAM, Linux 6.8, ZoKrates 0.8.8, Node 22.22.3,
solc-js 0.8.33, Ganache 7.9.2, and ethers 6.16.0. The high-dimension segment
finished in 1:47:09 with maximum RSS 69,233,376 KiB (about 66.0 GiB); the
low-dimension segment peaked at 17,321,732 KiB. No swap was consumed by the
timed high segment. A low-level unrelated compute load was present during part
of the campaign and is preserved in the host-load logs; the host was not CPU
saturated.

## Evidence and integrity

- `results/summary.json` and `results/summary.csv`: primary normalized data.
- `results/verification.json`: 43/43 checks, PASS.
- `results/fresh-vs-recovered.{json,csv}`: point-by-point historical comparison.
- `fresh/raw/`, `fresh/summary/`, `fresh/logs/`: raw samples and resource logs.
- `fresh/chain/`: transaction hashes, receipts, gas, deployment, and controls.
- `fresh/native-validation/`: native positive/negative controls and verifier
  re-export evidence.
- `fresh/immutable-preflight.sha256-size.tsv`: SHA-256, sizes, inodes, and link
  counts for remote multi-gigabyte compiled programs and proving keys.
- `fresh/source-artifact-manifest.tsv`: hashes and sizes of copied source,
  proof, verification-key, ABI, and verifier artifacts.
- `MANIFEST.sha256` and `SELF_CHECK.log`: local bundle integrity and final PASS.

The original shadowed Vanilla source is not silently treated as executable
ground truth. `SOURCE_TRANSFORM.md` records the single-line repair and its
semantic scope. `INCIDENTS.md` records excluded diagnostics, shared-cache
contamination, resource-monitor coverage, and chain-reporting repairs.
