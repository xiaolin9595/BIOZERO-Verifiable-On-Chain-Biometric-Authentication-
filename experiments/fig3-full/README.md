# Fig. 3 compact public evidence package

Start with `REPORT.md`. The fresh primary values are in
`results/summary.{json,csv}`, the complete historical comparison is in
`results/fresh-vs-recovered.{json,csv}`, and `results/verification.json` records
43/43 passing checks.

The original full-bundle harness is retained under `harness/` for method
inspection. This public repository intentionally omits the raw remote host and
process snapshots, compiled programs, proof material, and other bulky or
sensitive per-run artifacts, so `harness/verify_bundle.sh` is not expected to
pass against this compact checkout alone. Inspect the published aggregate
verification records with:

```sh
python3 -m json.tool results/verification.json
python3 -m json.tool results/summary.json
```
