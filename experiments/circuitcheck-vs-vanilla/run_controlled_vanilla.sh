#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-}"
if [[ "$MODE" != "smoke" && "$MODE" != "full" ]]; then
  echo "usage: run_controlled_vanilla.sh smoke|full [RUN_ROOT]" >&2
  exit 2
fi

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_ROOT="${2:-/var/tmp/biozero-circuitcheck-vs-vanilla-20261028/runs/${MODE}-$(date -u +%Y%m%dT%H%M%SZ)}"
CACHE_ROOT="${CACHE_ROOT:-/home/lzb/BioZero_remote/cache-fig3-full-20261028}"
PREFLIGHT_MANIFEST="${PREFLIGHT_MANIFEST:-/home/lzb/BioZero_remote/results/fig3_full_20261028/immutable-preflight.sha256-size.tsv}"
ZOKRATES_BIN="${ZOKRATES_BIN:-/home/lzb/BioZero_remote/zokrates-0.8.8-linux/zokrates}"
ZOKRATES_STDLIB="${ZOKRATES_STDLIB:-/home/lzb/BioZero_remote/zokrates-0.8.8-linux/stdlib}"

export RAYON_NUM_THREADS=1
export UV_THREADPOOL_SIZE=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export ZOKRATES_STDLIB

if [[ "$MODE" == "smoke" ]]; then
  DIMS=(2)
  ATTEMPTS=(0)
else
  DIMS=(2 4 8 16 32 64 128)
  ATTEMPTS=(0 1 2 3 4 5 6 7 8 9 10)
fi

mkdir -p "$RUN_ROOT"/{logs,metadata,records,runs}
RUN_LOG="$RUN_ROOT/logs/run.log"
RAW_CSV="$RUN_ROOT/records/raw.csv"
RAW_JSON="$RUN_ROOT/records/raw.json"
printf 'dimension,attempt,measured_round,witness_wall_ms,prove_wall_ms,witness_bytes,proof_bytes,input_sha256,witness_sha256,proof_sha256,verified,run_dir\n' >"$RAW_CSV"

log() {
  printf '[%s] %s\n' "$(date -Ins)" "$*" | tee -a "$RUN_LOG"
}

die() {
  log "FATAL: $*"
  exit 1
}

require_file() {
  [[ -f "$1" ]] || die "required file missing: $1"
}

snapshot_host() {
  local destination="$1"
  {
    date -Ins
    hostnamectl 2>/dev/null || true
    uname -a
    lscpu
    printf '\nthread_siblings_cpu0='; cat /sys/devices/system/cpu/cpu0/topology/thread_siblings_list
    printf 'governor_cpu0='; cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || true
    printf '\n/proc/loadavg\n'; cat /proc/loadavg
    printf '\nfree\n'; free -h
    printf '\ndf\n'; df -h "$RUN_ROOT" "$CACHE_ROOT"
    printf '\nulimit\n'; ulimit -a
    printf '\nenvironment controls\n'
    env | grep -E '^(RAYON_NUM_THREADS|UV_THREADPOOL_SIZE|OMP_NUM_THREADS|OPENBLAS_NUM_THREADS|MKL_NUM_THREADS|ZOKRATES_STDLIB)=' | sort
    printf '\nprocesses\n'; ps -eLo pid,tid,psr,pcpu,pmem,comm,args --sort=pid
  } >"$destination"
}

idle_gate() {
  local gate_log="$RUN_ROOT/logs/idle-gate.log"
  local passed=0
  local gate=0
  : >"$gate_log"
  log "idle gate: require four consecutive 30-second windows without zokrates/r11"
  while (( passed < 4 )); do
    gate=$((gate + 1))
    local clean=1
    printf '[%s] gate=%d start\n' "$(date -Ins)" "$gate" >>"$gate_log"
    for _ in $(seq 1 30); do
      local competing
      competing="$(pgrep -a -x zokrates 2>/dev/null || true)"
      if [[ -z "$competing" ]]; then
        competing="$(pgrep -a -x r11 2>/dev/null || true)"
      fi
      if [[ -n "$competing" ]]; then
        clean=0
        printf '[%s] gate=%d competition=%q\n' "$(date -Ins)" "$gate" "$competing" >>"$gate_log"
        break
      fi
      sleep 1
    done
    if (( clean == 1 )); then
      passed=$((passed + 1))
      printf '[%s] gate=%d PASS consecutive=%d\n' "$(date -Ins)" "$gate" "$passed" >>"$gate_log"
    else
      passed=0
      printf '[%s] gate=%d FAIL consecutive_reset=0\n' "$(date -Ins)" "$gate" >>"$gate_log"
      sleep 30
    fi
  done
  log "idle gate passed"
}

record_setup_metadata() {
  local trusted="$RUN_ROOT/metadata/trusted-setup-preflight.tsv"
  local current="$RUN_ROOT/metadata/setup-current-stat.tsv"
  local sources="$RUN_ROOT/metadata/source-hashes.sha256"
  : >"$trusted"
  printf 'size\tinode\tlinks\tmtime_epoch\tpath\n' >"$current"
  : >"$sources"

  require_file "$PREFLIGHT_MANIFEST"
  sha256sum "$PREFLIGHT_MANIFEST" >"$RUN_ROOT/metadata/trusted-manifest.sha256"
  sha256sum "$ZOKRATES_BIN" "$HARNESS_DIR"/* >"$RUN_ROOT/metadata/tool-and-harness.sha256"

  local dimension workspace artifact line
  for dimension in "${DIMS[@]}"; do
    workspace="$CACHE_ROOT/groth16_vanilla_${dimension}"
    for artifact in main.zok abi.json out proving.key verification.key verifier.sol; do
      require_file "$workspace/$artifact"
    done
    sha256sum "$workspace/main.zok" "$workspace/abi.json" >>"$sources"
    for artifact in out proving.key verification.key verifier.sol; do
      line="$(awk -F '\t' -v target="$workspace/$artifact" '$5 == target {print; found=1} END {if (!found) exit 1}' "$PREFLIGHT_MANIFEST")" \
        || die "trusted preflight entry missing: $workspace/$artifact"
      printf '%s\n' "$line" >>"$trusted"
      stat --printf='%s\t%i\t%h\t%Y\t%n\n' "$workspace/$artifact" >>"$current"
      local expected_size expected_inode current_size current_inode
      expected_size="$(printf '%s\n' "$line" | cut -f2)"
      expected_inode="$(printf '%s\n' "$line" | cut -f3)"
      current_size="$(stat --printf='%s' "$workspace/$artifact")"
      current_inode="$(stat --printf='%i' "$workspace/$artifact")"
      [[ "$expected_size" == "$current_size" ]] || die "size drift: $workspace/$artifact"
      [[ "$expected_inode" == "$current_inode" ]] || die "inode drift: $workspace/$artifact"
    done
  done
}

check_setup_unchanged() {
  local after="$RUN_ROOT/metadata/setup-after-stat.tsv"
  printf 'size\tinode\tlinks\tmtime_epoch\tpath\n' >"$after"
  local dimension artifact workspace
  for dimension in "${DIMS[@]}"; do
    workspace="$CACHE_ROOT/groth16_vanilla_${dimension}"
    for artifact in out proving.key verification.key verifier.sol; do
      stat --printf='%s\t%i\t%h\t%Y\t%n\n' "$workspace/$artifact" >>"$after"
    done
  done
  diff -u "$RUN_ROOT/metadata/setup-current-stat.tsv" "$after" >"$RUN_ROOT/metadata/setup-stat.diff" \
    || die "cached setup stat changed during run"
}

run_timed_phase() {
  local phase="$1"
  local phase_dir="$2"
  shift 2
  local start_ns end_ns rc sampler_pid stop_file
  stop_file="$phase_dir/${phase}.sampler.stop"
  rm -f "$stop_file"
  taskset -c 1 "$HARNESS_DIR/sample_environment.sh" \
    "$phase_dir/${phase}.host-load-frequency-cpu20.tsv" "$stop_file" &
  sampler_pid=$!
  start_ns="$(date +%s%N)"
  set +e
  /usr/bin/time -v -o "$phase_dir/${phase}.time-v.txt" \
    taskset -c 0 env \
      RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=1 OMP_NUM_THREADS=1 \
      OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 ZOKRATES_STDLIB="$ZOKRATES_STDLIB" \
      "$@" >"$phase_dir/${phase}.stdout.log" 2>"$phase_dir/${phase}.stderr.log"
  rc=$?
  set -e
  end_ns="$(date +%s%N)"
  touch "$stop_file"
  wait "$sampler_pid" || true
  rm -f "$stop_file"
  printf '%s\n' "$rc" >"$phase_dir/${phase}.exit"
  printf '%s\n' "$(((end_ns - start_ns) / 1000000))" >"$phase_dir/${phase}.wall-ms"
  (( rc == 0 )) || die "$phase failed rc=$rc; see $phase_dir"
}

run_attempt() {
  local dimension="$1"
  local attempt="$2"
  local kind measured_round phase_dir workspace witness proof
  if (( attempt == 0 )); then
    kind="warmup"
    measured_round=0
  else
    kind="measured"
    measured_round="$attempt"
  fi
  phase_dir="$RUN_ROOT/runs/N${dimension}/${kind}-$(printf '%02d' "$attempt")"
  workspace="$CACHE_ROOT/groth16_vanilla_${dimension}"
  witness="$phase_dir/witness"
  proof="$phase_dir/proof.json"
  mkdir -p "$phase_dir"

  node "$HARNESS_DIR/generate_vanilla_inputs.mjs" "$dimension" "$attempt" "$phase_dir"
  sha256sum "$phase_dir/input.json" "$phase_dir/arguments.txt" >"$phase_dir/input.sha256"
  mapfile -t witness_args <"$phase_dir/arguments.txt"

  log "N=$dimension attempt=$attempt kind=$kind compute-witness"
  run_timed_phase witness "$phase_dir" \
    "$ZOKRATES_BIN" compute-witness \
      -i "$workspace/out" -o "$witness" -a "${witness_args[@]}"
  sha256sum "$witness" >"$phase_dir/witness.sha256"
  stat --printf='%s\n' "$witness" >"$phase_dir/witness.bytes"

  log "N=$dimension attempt=$attempt kind=$kind generate-proof"
  run_timed_phase prove "$phase_dir" \
    "$ZOKRATES_BIN" generate-proof \
      -i "$workspace/out" -p "$workspace/proving.key" -w "$witness" -j "$proof"

  taskset -c 0 env \
    RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=1 OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 ZOKRATES_STDLIB="$ZOKRATES_STDLIB" \
    "$ZOKRATES_BIN" verify -v "$workspace/verification.key" -j "$proof" \
      >"$phase_dir/verify.stdout.log" 2>"$phase_dir/verify.stderr.log" \
    || die "verify failed: $phase_dir"
  printf 'true\n' >"$phase_dir/verified"

  sha256sum "$proof" >"$phase_dir/proof.sha256"
  stat --printf='%s\n' "$proof" >"$phase_dir/proof.bytes"
  chmod 0444 "$proof"
  sha256sum -c "$phase_dir/proof.sha256" >"$phase_dir/proof-post-chmod-check.log"

  local input_hash witness_hash proof_hash witness_ms prove_ms witness_bytes proof_bytes
  input_hash="$(awk '$2 ~ /input.json$/ {print $1}' "$phase_dir/input.sha256")"
  witness_hash="$(awk '{print $1}' "$phase_dir/witness.sha256")"
  proof_hash="$(awk '{print $1}' "$phase_dir/proof.sha256")"
  witness_ms="$(<"$phase_dir/witness.wall-ms")"
  prove_ms="$(<"$phase_dir/prove.wall-ms")"
  witness_bytes="$(<"$phase_dir/witness.bytes")"
  proof_bytes="$(<"$phase_dir/proof.bytes")"

  printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,true,%s\n' \
    "$dimension" "$attempt" "$measured_round" "$witness_ms" "$prove_ms" \
    "$witness_bytes" "$proof_bytes" "$input_hash" "$witness_hash" "$proof_hash" "$phase_dir" \
    >>"$RAW_CSV"
  node "$HARNESS_DIR/records_to_json.mjs" "$RAW_CSV" "$RAW_JSON"

  # The immutable per-attempt proof and public inputs remain. The large witness is
  # represented by its SHA-256, size, time -v, stdout/stderr, and input record.
  rm -f "$witness"
  log "N=$dimension attempt=$attempt complete witness_ms=$witness_ms prove_ms=$prove_ms proof_sha256=$proof_hash"
}

require_file "$ZOKRATES_BIN"
[[ -x "$ZOKRATES_BIN" ]] || die "zokrates is not executable: $ZOKRATES_BIN"
snapshot_host "$RUN_ROOT/metadata/host-before.txt"
record_setup_metadata
idle_gate

for dimension in "${DIMS[@]}"; do
  for attempt in "${ATTEMPTS[@]}"; do
    run_attempt "$dimension" "$attempt"
  done
done

check_setup_unchanged
snapshot_host "$RUN_ROOT/metadata/host-after.txt"
log "COMPLETE mode=$MODE run_root=$RUN_ROOT"
sha256sum "$RUN_ROOT/records/raw.csv" "$RUN_ROOT/records/raw.json" >"$RUN_ROOT/records/raw.sha256"
find "$RUN_ROOT" -type f ! -name 'manifest.sha256.tmp' -print0 \
  | grep -zv '/manifest\.sha256$' \
  | sort -z \
  | xargs -0 sha256sum >"$RUN_ROOT/manifest.sha256.tmp"
mv "$RUN_ROOT/manifest.sha256.tmp" "$RUN_ROOT/manifest.sha256"
printf '%s\n' "$RUN_ROOT"

