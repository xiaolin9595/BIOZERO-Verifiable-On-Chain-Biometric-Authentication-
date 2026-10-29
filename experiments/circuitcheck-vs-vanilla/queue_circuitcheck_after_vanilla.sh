#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 6 ]]; then
  echo "usage: queue_circuitcheck_after_vanilla.sh VANILLA_PID VANILLA_RUN PROJECT_ROOT RUN_ROOT EXPECTED_SOURCE_HASHES VANILLA_GAS_SCRIPT" >&2
  exit 2
fi

VANILLA_PID="$1"
VANILLA_RUN="$2"
PROJECT_ROOT="$3"
RUN_ROOT="$4"
EXPECTED_SOURCE_HASHES="$5"
VANILLA_GAS_SCRIPT="$6"
HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VANILLA_LOG="$VANILLA_RUN/logs/run.log"
SUPERVISOR_LOG="$RUN_ROOT/logs/supervisor.log"
SAMPLER_PID=""
SAMPLER_STOP="$RUN_ROOT/logs/experiment-sampler.stop"

export RAYON_NUM_THREADS=1
export UV_THREADPOOL_SIZE=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1

mkdir -p "$RUN_ROOT"/{logs,metadata}
exec > >(tee -a "$SUPERVISOR_LOG") 2>&1

log() {
  printf '[%s] %s\n' "$(date -Ins)" "$*"
}

stop_sampler() {
  if [[ -n "$SAMPLER_PID" ]]; then
    touch "$SAMPLER_STOP"
    set +e
    wait "$SAMPLER_PID"
    set -e
    SAMPLER_PID=""
  fi
}

on_exit() {
  local rc="$?"
  trap - EXIT
  stop_sampler
  if (( rc != 0 )); then
    {
      printf 'timestamp=%s\n' "$(date -Ins)"
      printf 'exit_code=%s\n' "$rc"
      printf 'supervisor_pid=%s\n' "$$"
    } >"$RUN_ROOT/FAILED"
    log "FAILED rc=$rc run_root=$RUN_ROOT"
  fi
  exit "$rc"
}
trap on_exit EXIT

snapshot_environment() {
  local destination="$1"
  {
    date -Ins
    hostnamectl 2>/dev/null || true
    uname -a
    lscpu
    printf '\nthread_siblings_cpu0='; cat /sys/devices/system/cpu/cpu0/topology/thread_siblings_list
    printf 'thread_siblings_cpu20='; cat /sys/devices/system/cpu/cpu20/topology/thread_siblings_list
    printf 'governor_cpu0='; cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || true
    printf '\n/proc/loadavg\n'; cat /proc/loadavg
    printf '\nfree\n'; free -h
    printf '\ndf\n'; df -h "$RUN_ROOT" "$PROJECT_ROOT"
    printf '\nulimit\n'; ulimit -a
    printf '\ncontrolled environment\n'
    env | grep -E '^(RAYON_NUM_THREADS|UV_THREADPOOL_SIZE|OMP_NUM_THREADS|OPENBLAS_NUM_THREADS|MKL_NUM_THREADS)=' | sort
    printf '\nprocesses\n'; ps -eLo pid,tid,psr,pcpu,pmem,comm,args --sort=pid
  } >"$destination"
}

write_source_hashes() {
  local destination="$1"
  (
    cd "$PROJECT_ROOT"
    find README.md package.json package-lock.json circuits scripts \
      -type f ! -name '._*' -print0 \
      | sort -z \
      | xargs -0 sha256sum
  ) >"$destination"
}

competing_processes() {
  ps -e -o pid=,comm=,args= | awk '
    BEGIN { IGNORECASE=1 }
    $2 != "awk" && (
      $2 ~ /^(zokrates|r11|snarkjs|circom|circom2)$/ ||
      $0 ~ /(^|[\/[:space:]])(zokrates|r11|snarkjs|circom|circom2)([[:space:]]|$)/
    ) { print }
  '
}

idle_gate() {
  local gate_log="$RUN_ROOT/logs/idle-gate.log"
  local consecutive=0
  local gate=0
  local clean competing
  : >"$gate_log"
  log "idle gate: require four consecutive 30-second windows without zokrates/r11/snarkjs/circom"
  while (( consecutive < 4 )); do
    gate=$((gate + 1))
    clean=1
    printf '[%s] gate=%d start\n' "$(date -Ins)" "$gate" >>"$gate_log"
    for _ in $(seq 1 30); do
      competing="$(competing_processes || true)"
      if [[ -n "$competing" ]]; then
        clean=0
        printf '[%s] gate=%d competition=%q\n' "$(date -Ins)" "$gate" "$competing" >>"$gate_log"
        break
      fi
      sleep 1
    done
    if (( clean == 1 )); then
      consecutive=$((consecutive + 1))
      printf '[%s] gate=%d PASS consecutive=%d\n' "$(date -Ins)" "$gate" "$consecutive" >>"$gate_log"
    else
      consecutive=0
      printf '[%s] gate=%d FAIL consecutive_reset=0\n' "$(date -Ins)" "$gate" >>"$gate_log"
      sleep 30
    fi
  done
  log "idle gate passed"
}

[[ "$VANILLA_PID" =~ ^[0-9]+$ ]] || { log "invalid Vanilla PID: $VANILLA_PID"; exit 2; }
[[ -d "$VANILLA_RUN" ]] || { log "missing Vanilla run root: $VANILLA_RUN"; exit 1; }
[[ -d "$PROJECT_ROOT" ]] || { log "missing CircuitCheck project root: $PROJECT_ROOT"; exit 1; }
[[ -f "$EXPECTED_SOURCE_HASHES" ]] || { log "missing expected source hashes: $EXPECTED_SOURCE_HASHES"; exit 1; }
[[ -f "$VANILLA_GAS_SCRIPT" ]] || { log "missing Vanilla gas harness: $VANILLA_GAS_SCRIPT"; exit 1; }
[[ -x "$HARNESS_DIR/sample_circuitcheck_environment.sh" ]] || { log "missing sampler"; exit 1; }
[[ ! -e "$RUN_ROOT/COMPLETE" && ! -e "$RUN_ROOT/FAILED" ]] || { log "run root already finalized: $RUN_ROOT"; exit 1; }

printf 'timestamp=%s\nsupervisor_pid=%s\nvanilla_pid=%s\nvanilla_run=%s\nproject_root=%s\n' \
  "$(date -Ins)" "$$" "$VANILLA_PID" "$VANILLA_RUN" "$PROJECT_ROOT" >"$RUN_ROOT/QUEUED"

if [[ -r "/proc/$VANILLA_PID/stat" ]]; then
  VANILLA_START_TICKS="$(awk '{print $22}' "/proc/$VANILLA_PID/stat")"
  VANILLA_CMDLINE="$(tr '\0' ' ' <"/proc/$VANILLA_PID/cmdline")"
  printf 'start_ticks=%s\ncmdline=%s\n' "$VANILLA_START_TICKS" "$VANILLA_CMDLINE" >>"$RUN_ROOT/QUEUED"
  [[ "$VANILLA_CMDLINE" == *run_controlled_vanilla.sh* ]] || { log "PID $VANILLA_PID is not the expected Vanilla runner"; exit 1; }
else
  log "Vanilla PID $VANILLA_PID already exited before supervisor captured it"
  VANILLA_START_TICKS=""
fi

log "queued; waiting for Vanilla PID $VANILLA_PID"
while [[ -n "$VANILLA_START_TICKS" && -r "/proc/$VANILLA_PID/stat" ]]; do
  current_start_ticks="$(awk '{print $22}' "/proc/$VANILLA_PID/stat")"
  [[ "$current_start_ticks" == "$VANILLA_START_TICKS" ]] || {
    log "PID $VANILLA_PID was reused; treating original Vanilla process as exited"
    break
  }
  sleep 30
done
log "Vanilla process exited; validating completion evidence"

[[ -f "$VANILLA_LOG" ]] || { log "missing Vanilla run log: $VANILLA_LOG"; exit 1; }
grep -F "COMPLETE mode=full run_root=$VANILLA_RUN" "$VANILLA_LOG" >"$RUN_ROOT/metadata/vanilla-COMPLETE.marker" \
  || { log "Vanilla COMPLETE marker absent"; exit 1; }
if grep -E '(^|[^[:alpha:]])(FAILED|FATAL)([^[:alpha:]]|$)' "$VANILLA_LOG" >"$RUN_ROOT/metadata/vanilla-failure-lines.txt"; then
  log "Vanilla log contains FAILED/FATAL"
  exit 1
fi
if find "$VANILLA_RUN" -type f \( -name FAILED -o -name '*.FAILED' -o -name '*.failed' \) -print -quit | grep -q .; then
  log "Vanilla run tree contains a FAILED marker"
  exit 1
fi
[[ -f "$VANILLA_RUN/manifest.sha256" ]] || { log "Vanilla manifest missing"; exit 1; }
(cd "$VANILLA_RUN" && sha256sum -c manifest.sha256) >"$RUN_ROOT/metadata/vanilla-manifest-check.log"

log "starting Vanilla direct-verifier gas stage with six distinct proof artifacts per dimension"
vanilla_gas_output="$VANILLA_RUN/verifier-gas"
/usr/bin/time -v -o "$RUN_ROOT/metadata/vanilla-gas.time-v.txt" \
  taskset -c 0 env \
    RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=1 OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
    node "$VANILLA_GAS_SCRIPT" "$VANILLA_RUN" "$vanilla_gas_output" \
    >"$RUN_ROOT/logs/vanilla-gas.stdout.log" \
    2>"$RUN_ROOT/logs/vanilla-gas.stderr.log"
[[ -f "$vanilla_gas_output/verification.json" ]] || { log "Vanilla gas verification is missing"; exit 1; }
node -e '
  const fs = require("node:fs");
  const report = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
  if (report.overall !== "PASS") process.exit(1);
' "$vanilla_gas_output/verification.json" || { log "Vanilla gas verification did not PASS"; exit 1; }
(
  cd "$vanilla_gas_output"
  find . -type f ! -name '._*' -print0 | sort -z | xargs -0 sha256sum
) >"$RUN_ROOT/metadata/vanilla-gas.sha256"
sha256sum "$VANILLA_GAS_SCRIPT" >"$RUN_ROOT/metadata/vanilla-gas-harness.sha256"
log "Vanilla direct-verifier gas stage passed"

cp "$EXPECTED_SOURCE_HASHES" "$RUN_ROOT/metadata/source-hashes.expected.sha256"
write_source_hashes "$RUN_ROOT/metadata/source-hashes.before.sha256"
diff -u "$RUN_ROOT/metadata/source-hashes.expected.sha256" "$RUN_ROOT/metadata/source-hashes.before.sha256" \
  >"$RUN_ROOT/metadata/source-hashes.deploy.diff"
sha256sum "$HARNESS_DIR/queue_circuitcheck_after_vanilla.sh" \
  "$HARNESS_DIR/sample_circuitcheck_environment.sh" \
  >"$RUN_ROOT/metadata/harness-hashes.sha256"

snapshot_environment "$RUN_ROOT/metadata/environment.before.txt"
(
  cd "$PROJECT_ROOT"
  npm ci --ignore-scripts --no-audit --no-fund
) >"$RUN_ROOT/logs/npm-ci.log" 2>&1
{
  printf 'node='; node --version
  printf 'npm='; npm --version
  printf 'time='; /usr/bin/time --version | head -n 1
  printf 'taskset='; taskset --version | head -n 1
} >"$RUN_ROOT/metadata/tool-versions.txt"
(
  cd "$PROJECT_ROOT"
  npm ls --all
) >"$RUN_ROOT/metadata/npm-ls.txt" 2>&1

idle_gate

log "starting unchanged CircuitCheck full experiment on CPU0"
taskset -c 1 "$HARNESS_DIR/sample_circuitcheck_environment.sh" \
  "$RUN_ROOT/logs/host-load-frequency-cpu0-cpu20.tsv" "$SAMPLER_STOP" &
SAMPLER_PID="$!"
set +e
/usr/bin/time -v -o "$RUN_ROOT/metadata/experiment.time-v.txt" \
  taskset -c 0 env \
    RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=1 OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
    npm --prefix "$PROJECT_ROOT" run experiment \
    >"$RUN_ROOT/logs/experiment.stdout.log" \
    2>"$RUN_ROOT/logs/experiment.stderr.log"
experiment_rc="$?"
set -e
printf '%s\n' "$experiment_rc" >"$RUN_ROOT/metadata/experiment.exit"
stop_sampler

snapshot_environment "$RUN_ROOT/metadata/environment.after.txt"
write_source_hashes "$RUN_ROOT/metadata/source-hashes.after.sha256"
diff -u "$RUN_ROOT/metadata/source-hashes.before.sha256" "$RUN_ROOT/metadata/source-hashes.after.sha256" \
  >"$RUN_ROOT/metadata/source-hashes.after.diff"

(( experiment_rc == 0 )) || { log "CircuitCheck experiment failed rc=$experiment_rc"; exit "$experiment_rc"; }
[[ -f "$PROJECT_ROOT/results/verification.json" ]] || { log "missing final verification gate"; exit 1; }
[[ -f "$PROJECT_ROOT/results/manifest.json" ]] || { log "missing final manifest gate"; exit 1; }

{
  printf 'timestamp=%s\n' "$(date -Ins)"
  printf 'supervisor_pid=%s\n' "$$"
  printf 'experiment_exit=%s\n' "$experiment_rc"
  printf 'project_root=%s\n' "$PROJECT_ROOT"
} >"$RUN_ROOT/COMPLETE"
log "COMPLETE run_root=$RUN_ROOT"
