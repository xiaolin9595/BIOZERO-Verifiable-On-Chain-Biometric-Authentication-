#!/usr/bin/env bash
set -euo pipefail

root="${BIOZERO_REMOTE_ROOT:-$HOME/BioZero_remote}"
cache_root="${FIG3_CACHE_ROOT:-$root/cache-fig3-full-20261028}"
result_root="${FIG3_RESULT_ROOT:-$root/results/fig3_full_20261028}"
harness_root="${FIG3_HARNESS_ROOT:-/var/tmp/biozero-fig3-full-lzb/harness}"
zokrates_bin="${BIOZERO_ZOKRATES_BIN:-$root/zokrates-0.8.8-linux/zokrates}"
zokrates_stdlib="${ZOKRATES_STDLIB:-$root/zokrates-0.8.8-linux/stdlib}"
wait_pid="${FIG3_WAIT_PID:-}"

mkdir -p "$result_root/logs" \
  "$result_root/raw/latency-low" "$result_root/summary/latency-low" \
  "$result_root/raw/latency-high" "$result_root/summary/latency-high"
protocol_log="$result_root/logs/protocol-split.log"
printf '[%s] protocol split supervisor started\n' "$(date -Is)" >>"$protocol_log"

if [ -n "$wait_pid" ]; then
  while kill -0 "$wait_pid" 2>/dev/null; do
    printf '[%s] waiting for interfering pid=%s; ' "$(date -Is)" "$wait_pid" >>"$protocol_log"
    uptime >>"$protocol_log"
    sleep 30
  done
fi

wait_for_stable_idle() {
  local stable_checks=0
  local competitors
  while [ "$stable_checks" -lt 4 ]; do
    competitors="$(ps -u "$USER" -o pid=,args= | awk '
      {
        executable=$2
        sub(/^.*\//, "", executable)
        if (executable == "r11_completion_setup" || executable == "zokrates") print $1
      }' || true)"
    if [ -n "$competitors" ]; then
      stable_checks=0
      printf '[%s] waiting for competing compute pids=%s; ' "$(date -Is)" "$(echo "$competitors" | paste -sd, -)" >>"$protocol_log"
      uptime >>"$protocol_log"
    else
      stable_checks=$((stable_checks + 1))
      printf '[%s] idle stability check %s/4; ' "$(date -Is)" "$stable_checks" >>"$protocol_log"
      uptime >>"$protocol_log"
    fi
    sleep 30
  done
}

wait_for_stable_idle

printf '[%s] resetting mutable cache paths\n' "$(date -Is)" >>"$protocol_log"
find "$cache_root" -mindepth 2 -maxdepth 2 -type f \
  \( -name main.zok -o -name proof.json -o -name witness -o -name out.wtns \) -delete

printf '[%s] immutable preflight hashes begin\n' "$(date -Is)" >>"$protocol_log"
preflight="$result_root/immutable-preflight.sha256-size.tsv"
printf 'sha256\tbytes\tinode\tlinks\tpath\n' >"$preflight"
while IFS= read -r -d '' artifact; do
  hash="$(sha256sum "$artifact" | awk '{print $1}')"
  read -r bytes inode links < <(stat -c '%s %i %h' "$artifact")
  printf '%s\t%s\t%s\t%s\t%s\n' "$hash" "$bytes" "$inode" "$links" "$artifact" >>"$preflight"
done < <(find "$cache_root" -mindepth 2 -maxdepth 2 -type f \
  \( -name out -o -name proving.key -o -name verification.key -o -name verifier.sol \) \
  -print0 | sort -z)
sync
wait_for_stable_idle

{
  printf '\n[%s] pre-low-run host state\n' "$(date -Is)"
  uptime
  free -h
  ps -eo user,pid,ppid,etime,%cpu,%mem,rss,cmd --sort=-%cpu | head -15
} >>"$protocol_log"

cd "$root/src/experiments"
printf '[%s] low dimensions start; RAYON_NUM_THREADS explicitly unset\n' "$(date -Is)" >>"$protocol_log"
env -u RAYON_NUM_THREADS \
  BIOZERO_ZOKRATES_BIN="$zokrates_bin" ZOKRATES_STDLIB="$zokrates_stdlib" \
  /usr/bin/time -v npm run latency -- \
    --dims 2,4,8,16,32 \
    --rounds 30 --warmup 5 \
    --zokrates-rounds 5 --zokrates-warmup 1 \
    --zokrates-bin "$zokrates_bin" \
    --zokrates-stdlib "$zokrates_stdlib" \
    --cache-root "$cache_root" \
    --raw-dir "$result_root/raw/latency-low" \
    --summary-dir "$result_root/summary/latency-low" \
  >"$result_root/logs/latency-low.stdout.log" \
  2>"$result_root/logs/latency-low.stderr.log"
printf '[%s] low dimensions complete\n' "$(date -Is)" >>"$protocol_log"

printf '[%s] high dimensions start; RAYON_NUM_THREADS=1\n' "$(date -Is)" >>"$protocol_log"
env RAYON_NUM_THREADS=1 \
  BIOZERO_ZOKRATES_BIN="$zokrates_bin" ZOKRATES_STDLIB="$zokrates_stdlib" \
  /usr/bin/time -v npm run latency -- \
    --dims 64,128 \
    --rounds 30 --warmup 5 \
    --zokrates-rounds 5 --zokrates-warmup 1 \
    --zokrates-bin "$zokrates_bin" \
    --zokrates-stdlib "$zokrates_stdlib" \
    --cache-root "$cache_root" \
    --raw-dir "$result_root/raw/latency-high" \
    --summary-dir "$result_root/summary/latency-high" \
  >"$result_root/logs/latency-high.stdout.log" \
  2>"$result_root/logs/latency-high.stderr.log"
printf '[%s] high dimensions and selected BioZero fixed complete\n' "$(date -Is)" >>"$protocol_log"

printf '[%s] native proof/key/verifier validation start\n' "$(date -Is)" >>"$protocol_log"
BIOZERO_REMOTE_ROOT="$root" FIG3_CACHE_ROOT="$cache_root" FIG3_RESULT_ROOT="$result_root" \
  /usr/bin/time -v "$harness_root/validate_native.sh" \
  >"$result_root/logs/native-validation.stdout.log" \
  2>"$result_root/logs/native-validation.stderr.log"

printf '[%s] fresh chain validation start\n' "$(date -Is)" >>"$protocol_log"
FIG3_CACHE_ROOT="$cache_root" \
FIG3_CHAIN_OUTPUT="$result_root/chain" \
FIG3_NODE_MODULES="$root/src/experiments" \
FIG3_GAS_REPEATS=5 \
  /usr/bin/time -v node "$harness_root/validate_chain.mjs" \
  >"$result_root/logs/chain-validation.stdout.log" \
  2>"$result_root/logs/chain-validation.stderr.log"

printf '[%s] mutable artifact hash manifest start\n' "$(date -Is)" >>"$protocol_log"
manifest="$result_root/cache-artifacts.sha256-size.tsv"
printf 'sha256\tbytes\tpath\n' >"$manifest"
while IFS= read -r -d '' artifact; do
  hash="$(sha256sum "$artifact" | awk '{print $1}')"
  bytes="$(stat -c '%s' "$artifact")"
  printf '%s\t%s\t%s\n' "$hash" "$bytes" "$artifact" >>"$manifest"
done < <(find "$cache_root" -mindepth 2 -maxdepth 2 -type f \
  \( -name main.zok -o -name proof.json -o -name witness -o -name out.wtns \) \
  -print0 | sort -z)

printf '[%s] complete\n' "$(date -Is)" >>"$protocol_log"
printf 'PASS\n' >"$result_root/PROTOCOL_SPLIT_COMPLETE"
