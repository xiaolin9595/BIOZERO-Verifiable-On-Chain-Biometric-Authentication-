#!/usr/bin/env bash
set -euo pipefail

root="${BIOZERO_REMOTE_ROOT:-$HOME/BioZero_remote}"
cache_root="${FIG3_CACHE_ROOT:-$root/cache-fig3-full-20261028}"
result_root="${FIG3_RESULT_ROOT:-$root/results/fig3_full_20261028}"
harness_root="${FIG3_HARNESS_ROOT:-/var/tmp/biozero-fig3-full-lzb/harness}"
latency_pid="$(cat "$result_root/logs/latency.pid")"
supervisor_log="$result_root/logs/post-latency-supervisor.log"

printf '[%s] waiting for latency pid=%s\n' "$(date -Is)" "$latency_pid" >>"$supervisor_log"
while kill -0 "$latency_pid" 2>/dev/null; do
  sleep 30
done

if [ ! -s "$result_root/raw/latency/latency_raw.csv" ] \
  || [ ! -s "$result_root/summary/latency/latency_summary.csv" ]; then
  printf '[%s] latency outputs missing; refusing post-run validation\n' "$(date -Is)" >>"$supervisor_log"
  exit 1
fi
if ! grep -q 'Exit status: 0' "$result_root/logs/latency.stderr.log"; then
  printf '[%s] latency command did not report exit status 0\n' "$(date -Is)" >>"$supervisor_log"
  exit 1
fi

printf '[%s] starting native proof/key/verifier validation\n' "$(date -Is)" >>"$supervisor_log"
BIOZERO_REMOTE_ROOT="$root" FIG3_CACHE_ROOT="$cache_root" FIG3_RESULT_ROOT="$result_root" \
  /usr/bin/time -v "$harness_root/validate_native.sh" \
  >"$result_root/logs/native-validation.stdout.log" \
  2>"$result_root/logs/native-validation.stderr.log"

printf '[%s] starting fresh chain validation\n' "$(date -Is)" >>"$supervisor_log"
FIG3_CACHE_ROOT="$cache_root" \
FIG3_CHAIN_OUTPUT="$result_root/chain" \
FIG3_NODE_MODULES="$root/src/experiments" \
FIG3_GAS_REPEATS=5 \
  /usr/bin/time -v node "$harness_root/validate_chain.mjs" \
  >"$result_root/logs/chain-validation.stdout.log" \
  2>"$result_root/logs/chain-validation.stderr.log"

printf '[%s] hashing cache artifacts\n' "$(date -Is)" >>"$supervisor_log"
manifest="$result_root/cache-artifacts.sha256-size.tsv"
printf 'sha256\tbytes\tpath\n' >"$manifest"
while IFS= read -r -d '' artifact; do
  hash="$(sha256sum "$artifact" | awk '{print $1}')"
  bytes="$(stat -c '%s' "$artifact")"
  printf '%s\t%s\t%s\n' "$hash" "$bytes" "$artifact" >>"$manifest"
done < <(find "$cache_root" -mindepth 2 -maxdepth 2 -type f -print0 | sort -z)

printf '[%s] complete\n' "$(date -Is)" >>"$supervisor_log"
printf 'PASS\n' >"$result_root/POST_LATENCY_COMPLETE"
