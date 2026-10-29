#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 5 ]]; then
  echo "usage: run_spotcheck_n_sweep.sh PROJECT_ROOT RUN_ROOT DEPLOY_ROOT REUSED_COMPLETE_RUN full|smoke" >&2
  exit 2
fi

PROJECT_ROOT="$1"
RUN_ROOT="$2"
DEPLOY_ROOT="$3"
REUSED_COMPLETE_RUN="$4"
MODE="$5"
BASE_ROOT="/var/tmp/biozero-circuitcheck-vs-vanilla-20261028"
RUN_ID="$(basename "$RUN_ROOT")"
TMP_ROOT="$BASE_ROOT/tmp/$RUN_ID"
SAMPLER_PID=""
SAMPLER_STOP="$RUN_ROOT/logs/sampler.stop"
CURRENT_STAGE="initializing"

[[ "$MODE" == "full" || "$MODE" == "smoke" ]] || { echo "mode must be full or smoke" >&2; exit 2; }
[[ "$PROJECT_ROOT" == "$BASE_ROOT/spotcheck-enine" ]] || { echo "unexpected project root" >&2; exit 1; }
[[ "$RUN_ROOT" == "$BASE_ROOT/runs/"* ]] || { echo "run root must be below controlled runs directory" >&2; exit 1; }
[[ "$DEPLOY_ROOT" == "$BASE_ROOT/deploy/"* ]] || { echo "deploy root must be below controlled deploy directory" >&2; exit 1; }
[[ "$TMP_ROOT" == "$BASE_ROOT/tmp/"* ]] || { echo "invalid TMPDIR" >&2; exit 1; }
[[ ! -e "$RUN_ROOT" ]] || { echo "refusing to reuse existing run root: $RUN_ROOT" >&2; exit 1; }
[[ -f "$REUSED_COMPLETE_RUN/COMPLETE" ]] || { echo "missing COMPLETE marker on reused setup run" >&2; exit 1; }
[[ -d "$PROJECT_ROOT/node_modules" ]] || { echo "missing exact preinstalled node_modules" >&2; exit 1; }
[[ -L "$DEPLOY_ROOT/node_modules" ]] || { echo "deployment must link exact project node_modules" >&2; exit 1; }

export TMPDIR="$TMP_ROOT"
export TMP="$TMP_ROOT"
export TEMP="$TMP_ROOT"
export RAYON_NUM_THREADS=1
export UV_THREADPOOL_SIZE=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1

mkdir -p "$RUN_ROOT"/{logs,metadata,results} "$TMP_ROOT"
chmod 700 "$TMP_ROOT"
exec > >(tee -a "$RUN_ROOT/logs/supervisor.log") 2>&1

log() {
  printf '[%s] stage=%s %s\n' "$(date -Ins)" "$CURRENT_STAGE" "$*"
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
      printf 'status=FAILED\n'
      printf 'timestamp=%s\n' "$(date -Ins)"
      printf 'exit_code=%s\n' "$rc"
      printf 'stage=%s\n' "$CURRENT_STAGE"
      printf 'supervisor_pid=%s\n' "$$"
    } >"$RUN_ROOT/FAILED"
    log "FAILED rc=$rc"
  fi
  exit "$rc"
}
trap on_exit EXIT

printf 'timestamp=%s\nsupervisor_pid=%s\nproject_root=%s\nrun_root=%s\ndeploy_root=%s\nmode=%s\ntmpdir=%s\n' \
  "$(date -Ins)" "$$" "$PROJECT_ROOT" "$RUN_ROOT" "$DEPLOY_ROOT" "$MODE" "$TMPDIR" >"$RUN_ROOT/STARTED"

CURRENT_STAGE="provenance"
log "checking reused setup artifacts and pinned offline dependency graph"
cmp "$PROJECT_ROOT/results/setup-artifacts.sha256" "$REUSED_COMPLETE_RUN/results/setup-artifacts.sha256"
(
  cd "$PROJECT_ROOT"
  sha256sum -c results/setup-artifacts.sha256
) >"$RUN_ROOT/metadata/setup-artifacts.check.log"
node -e '
  const fs = require("node:fs");
  const report = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
  if (report.overall !== "PASS") throw new Error(`reused run verification is ${report.overall}`);
' "$REUSED_COMPLETE_RUN/results/verification-spotcheck.json"
(
  cd "$PROJECT_ROOT"
  npm ls --all
) >"$RUN_ROOT/metadata/npm-ls.txt" 2>&1
{
  printf 'setup_source_run=%s\n' "$REUSED_COMPLETE_RUN"
  printf 'setup_reused=true\nsetup_rerun=false\n'
  printf 'node_modules=%s/node_modules\n' "$PROJECT_ROOT"
  printf 'npm_registry_access=DISABLED\n'
  printf 'tmpdir=%s\n' "$TMPDIR"
  sha256sum "$PROJECT_ROOT/build/hom-complete-gas/threshold_standin_js/threshold_standin.wasm" \
    "$PROJECT_ROOT/build/hom-complete-gas/ts_final.zkey" \
    "$PROJECT_ROOT/build/hom-complete-gas/verification_key.json" \
    "$PROJECT_ROOT/contracts/generated/Groth16VerifierThreshold.sol"
  sha256sum "$DEPLOY_ROOT/spotcheck_n_sweep.mjs" \
    "$DEPLOY_ROOT/spotcheck_n_sweep_config.mjs" \
    "$DEPLOY_ROOT/verify_spotcheck_n_sweep.mjs" \
    "$DEPLOY_ROOT/run_spotcheck_n_sweep.sh"
} >"$RUN_ROOT/metadata/provenance.txt"
{
  date -Ins
  hostnamectl 2>/dev/null || true
  uname -a
  lscpu
  printf 'thread_siblings_cpu0='; cat /sys/devices/system/cpu/cpu0/topology/thread_siblings_list
  printf 'thread_siblings_cpu1='; cat /sys/devices/system/cpu/cpu1/topology/thread_siblings_list
  printf 'governor_cpu0='; cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || true
  printf '\nloadavg\n'; cat /proc/loadavg
  printf '\nmemory\n'; free -h
  printf '\ndisk\n'; df -h "$RUN_ROOT"
  printf '\nversions\n'; node --version; npm --version
  (cd "$PROJECT_ROOT" && node -e 'console.log(require("solc").version())')
  printf '\ncontrolled_environment\n'
  env | grep -E '^(TMPDIR|TMP|TEMP|RAYON_NUM_THREADS|UV_THREADPOOL_SIZE|OMP_NUM_THREADS|OPENBLAS_NUM_THREADS|MKL_NUM_THREADS)=' | sort
  printf '\nprocesses\n'; ps -eLo pid,tid,psr,pcpu,pmem,comm,args --sort=pid
} >"$RUN_ROOT/metadata/environment.txt"

CURRENT_STAGE="benchmark"
log "starting SpotCheck N sweep on CPU0 with sampler on CPU1"
rm -f "$SAMPLER_STOP"
taskset -c 1 "$DEPLOY_ROOT/sample_circuitcheck_environment.sh" "$RUN_ROOT/logs/host-load-frequency.tsv" "$SAMPLER_STOP" &
SAMPLER_PID="$!"
/usr/bin/time -v -o "$RUN_ROOT/metadata/benchmark.time-v.txt" \
  taskset -c 0 node "$DEPLOY_ROOT/spotcheck_n_sweep.mjs" "$PROJECT_ROOT" "$RUN_ROOT" "$MODE" \
  >"$RUN_ROOT/logs/benchmark.stdout.log" \
  2>"$RUN_ROOT/logs/benchmark.stderr.log"
stop_sampler

CURRENT_STAGE="verification"
log "verifying grid, formula, repetitions, controls, timings, and manifests"
node "$DEPLOY_ROOT/verify_spotcheck_n_sweep.mjs" "$RUN_ROOT" "$MODE" \
  >"$RUN_ROOT/logs/verification.stdout.log" \
  2>"$RUN_ROOT/logs/verification.stderr.log"
{
  printf 'status=COMPLETE\n'
  printf 'timestamp=%s\n' "$(date -Ins)"
  printf 'supervisor_pid=%s\n' "$$"
  printf 'mode=%s\n' "$MODE"
  printf 'run_root=%s\n' "$RUN_ROOT"
} >"$RUN_ROOT/COMPLETE"
CURRENT_STAGE="complete"
log "COMPLETE run_root=$RUN_ROOT"
