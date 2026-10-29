#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 6 ]]; then
  echo "usage: unified_spotcheck_then_circuitcheck.sh SPOT_PROJECT SPOT_RUN SPOT_EXPECTED_HASHES GRID_PROJECT GRID_RUN GRID_EXPECTED_HASHES" >&2
  exit 2
fi

SPOT_PROJECT="$1"
SPOT_RUN="$2"
SPOT_EXPECTED_HASHES="$3"
GRID_PROJECT="$4"
GRID_RUN="$5"
GRID_EXPECTED_HASHES="$6"
HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUPERVISOR_LOG="$SPOT_RUN/logs/supervisor.log"
SAMPLER_PID=""
SAMPLER_STOP=""
CURRENT_STAGE="initializing"

export RAYON_NUM_THREADS=1
export UV_THREADPOOL_SIZE=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1

mkdir -p "$SPOT_RUN"/{logs,metadata,results} "$GRID_RUN"/{logs,metadata}
exec > >(tee -a "$SUPERVISOR_LOG") 2>&1

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
    local failed_root="$SPOT_RUN"
    [[ "$CURRENT_STAGE" == circuitcheck* ]] && failed_root="$GRID_RUN"
    {
      printf 'status=FAILED\n'
      printf 'timestamp=%s\n' "$(date -Ins)"
      printf 'exit_code=%s\n' "$rc"
      printf 'stage=%s\n' "$CURRENT_STAGE"
      printf 'supervisor_pid=%s\n' "$$"
    } >"$failed_root/FAILED"
    log "FAILED rc=$rc root=$failed_root"
  fi
  exit "$rc"
}
trap on_exit EXIT

snapshot_environment() {
  local project="$1"
  local destination="$2"
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
    printf '\ndf\n'; df -h "$project"
    printf '\nulimit\n'; ulimit -a
    printf '\ncontrolled environment\n'
    env | grep -E '^(RAYON_NUM_THREADS|UV_THREADPOOL_SIZE|OMP_NUM_THREADS|OPENBLAS_NUM_THREADS|MKL_NUM_THREADS)=' | sort
    printf '\nprocesses\n'; ps -eLo pid,tid,psr,pcpu,pmem,comm,args --sort=pid
  } >"$destination"
}

write_spot_immutable_hashes() {
  local destination="$1"
  (
    cd "$SPOT_PROJECT"
    find README.md package.json package-lock.json benchmark.ps1 toolchain.ps1 circuits contracts scripts \
      -type f ! -path 'contracts/generated/*' ! -name '._*' -print0 \
      | sort -z \
      | xargs -0 sha256sum
  ) >"$destination"
}

write_grid_source_hashes() {
  local destination="$1"
  (
    cd "$GRID_PROJECT"
    find README.md package.json package-lock.json circuits scripts \
      -type f ! -name '._*' -print0 \
      | sort -z \
      | xargs -0 sha256sum
  ) >"$destination"
}

start_sampler() {
  local output="$1"
  SAMPLER_STOP="$2"
  rm -f "$SAMPLER_STOP"
  taskset -c 1 "$HARNESS_DIR/sample_circuitcheck_environment.sh" "$output" "$SAMPLER_STOP" &
  SAMPLER_PID="$!"
}

[[ -d "$SPOT_PROJECT" ]] || { echo "missing SpotCheck project: $SPOT_PROJECT" >&2; exit 1; }
[[ -f "$SPOT_EXPECTED_HASHES" ]] || { echo "missing SpotCheck expected hashes: $SPOT_EXPECTED_HASHES" >&2; exit 1; }
[[ -d "$GRID_PROJECT" ]] || { echo "missing CircuitCheck project: $GRID_PROJECT" >&2; exit 1; }
[[ -f "$GRID_EXPECTED_HASHES" ]] || { echo "missing CircuitCheck expected hashes: $GRID_EXPECTED_HASHES" >&2; exit 1; }
[[ -x "$HARNESS_DIR/sample_circuitcheck_environment.sh" ]] || { echo "missing environment sampler" >&2; exit 1; }
[[ ! -e "$SPOT_RUN/COMPLETE" && ! -e "$SPOT_RUN/FAILED" ]] || { echo "SpotCheck run root already finalized" >&2; exit 1; }
[[ ! -e "$GRID_RUN/COMPLETE" && ! -e "$GRID_RUN/FAILED" ]] || { echo "CircuitCheck run root already finalized" >&2; exit 1; }

printf 'timestamp=%s\nsupervisor_pid=%s\nspot_project=%s\ngrid_project=%s\n' \
  "$(date -Ins)" "$$" "$SPOT_PROJECT" "$GRID_PROJECT" >"$SPOT_RUN/STARTED"
printf 'timestamp=%s\nsupervisor_pid=%s\nwaits_for=%s/COMPLETE\ngrid_project=%s\n' \
  "$(date -Ins)" "$$" "$SPOT_RUN" "$GRID_PROJECT" >"$GRID_RUN/QUEUED"

CURRENT_STAGE="spotcheck-provenance"
log "validating deployed source against local expected manifest"
cp "$SPOT_EXPECTED_HASHES" "$SPOT_RUN/metadata/source-deploy.expected.sha256"
(
  cd "$SPOT_PROJECT"
  sha256sum -c "$SPOT_EXPECTED_HASHES"
) >"$SPOT_RUN/metadata/source-deploy.check.log"
write_spot_immutable_hashes "$SPOT_RUN/metadata/source-immutable.before.sha256"
snapshot_environment "$SPOT_PROJECT" "$SPOT_RUN/metadata/environment.before.txt"
sha256sum "$HARNESS_DIR/unified_spotcheck_then_circuitcheck.sh" \
  "$HARNESS_DIR/sample_circuitcheck_environment.sh" \
  >"$SPOT_RUN/metadata/harness.sha256"

CURRENT_STAGE="spotcheck-npm-ci"
log "validating preinstalled pinned package-lock dependency graph (offline; npm ci disabled)"
[[ -d "$SPOT_PROJECT/node_modules" ]] || {
  log "missing preinstalled SpotCheck node_modules; refusing registry access"
  exit 1
}
if (
  cd "$SPOT_PROJECT"
  npm ls --all
) >"$SPOT_RUN/metadata/npm-ls.txt" 2>&1; then
  {
    printf 'mode=preinstalled-node_modules\n'
    printf 'validation=npm ls --all\n'
    printf 'npm_ci=SKIPPED\n'
    printf 'network_registry_access=DISABLED\n'
  } >"$SPOT_RUN/metadata/npm-install-mode.txt"
  log "SpotCheck npm ls passed; skipping npm ci and all registry access"
else
  log "SpotCheck npm ls failed; refusing npm ci or registry fallback"
  exit 1
fi
{
  printf 'node='; node --version
  printf 'npm='; npm --version
  printf 'circom='; node "$SPOT_PROJECT/node_modules/circom2/cli.js" --version | tr '\n' ' '; printf '\n'
  printf 'solc='; (cd "$SPOT_PROJECT" && node -e 'console.log(require("solc").version())')
  printf 'ganache=7.9.2\nethers=5.8.0\nsnarkjs=0.7.6\n'
} >"$SPOT_RUN/metadata/tool-versions.txt"

CURRENT_STAGE="spotcheck-inputs"
log "generating N=128 inputs"
/usr/bin/time -v -o "$SPOT_RUN/metadata/generate-inputs.time-v.txt" \
  taskset -c 0 node "$SPOT_PROJECT/scripts/generate-inputs.mjs" \
  >"$SPOT_RUN/logs/generate-inputs.stdout.log" \
  2>"$SPOT_RUN/logs/generate-inputs.stderr.log"

CURRENT_STAGE="spotcheck-fresh-setup"
log "starting fresh benchmark-only setup on CPU0"
start_sampler "$SPOT_RUN/logs/setup-host-load-frequency-cpu0-cpu20.tsv" "$SPOT_RUN/logs/setup-sampler.stop"
/usr/bin/time -v -o "$SPOT_RUN/metadata/fresh-setup.time-v.txt" \
  taskset -c 0 npm --prefix "$SPOT_PROJECT" run reconstruct:setup \
  >"$SPOT_RUN/logs/fresh-setup.stdout.log" \
  2>"$SPOT_RUN/logs/fresh-setup.stderr.log"
stop_sampler
(
  cd "$SPOT_PROJECT"
  sha256sum -c results/setup-artifacts.sha256
) >"$SPOT_RUN/metadata/setup-artifacts.check.log"
cp "$SPOT_PROJECT/results/setup-summary.json" "$SPOT_RUN/results/setup-summary.json"
cp "$SPOT_PROJECT/results/setup-artifacts.sha256" "$SPOT_RUN/results/setup-artifacts.sha256"

CURRENT_STAGE="spotcheck-hom-complete-gas"
log "running unchanged N=128 eta=1,2,4,8 plus FullCheck; three transactions per case"
start_sampler "$SPOT_RUN/logs/hom-host-load-frequency-cpu0-cpu20.tsv" "$SPOT_RUN/logs/hom-sampler.stop"
/usr/bin/time -v -o "$SPOT_RUN/metadata/hom-complete-gas.time-v.txt" \
  taskset -c 0 node "$SPOT_PROJECT/scripts/hom-complete-gas.mjs" \
  >"$SPOT_RUN/logs/hom-complete-gas.stdout.log" \
  2>"$SPOT_RUN/logs/hom-complete-gas.stderr.log"
stop_sampler
cp "$SPOT_PROJECT/build/hom-complete-gas/results.json" "$SPOT_RUN/results/hom-complete.json"

CURRENT_STAGE="spotcheck-verification"
log "validating exact SpotCheck grid, transaction counts, and negative controls"
SPOT_RUN="$SPOT_RUN" node <<'NODE' >"$SPOT_RUN/logs/verification.stdout.log" 2>"$SPOT_RUN/logs/verification.stderr.log"
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const root = process.env.SPOT_RUN;
const readJson = (name) => JSON.parse(fs.readFileSync(path.join(root, "results", name), "utf8"));
const setup = readJson("setup-summary.json");
const hom = readJson("hom-complete.json");
const expected = [
  { label: "spot-eta-1", eta: 1, samples: 7 },
  { label: "spot-eta-2", eta: 2, samples: 14 },
  { label: "spot-eta-4", eta: 4, samples: 28 },
  { label: "spot-eta-8", eta: 8, samples: 56 },
  { label: "full-check", eta: null, samples: 128 },
];
const checks = [];
const check = (name, pass, detail) => {
  checks.push({ name, pass: Boolean(pass), detail });
  if (!pass) throw new Error(`${name}: ${detail}`);
};
check("fresh setup labelled reconstructed", setup.reconstructed === true, setup.warning);
check("fresh setup exported three matching verifiers", setup.matchingSolidityVerifiersExported?.length === 3, setup.matchingSolidityVerifiersExported);
check("dimension fixed at N=128", hom.dimension === 128, hom.dimension);
check("exact five cases only", hom.results?.length === expected.length, hom.results?.map((row) => row.label));
for (let index = 0; index < expected.length; index += 1) {
  const actual = hom.results[index];
  const wanted = expected[index];
  check(`${wanted.label} identity`, actual.label === wanted.label && actual.eta === wanted.eta && actual.samples === wanted.samples, actual);
  check(`${wanted.label} exactly three transactions`, actual.repetitions === 3 && actual.gasUsed?.length === 3, actual.gasUsed);
  check(`${wanted.label} mandatory controls`, actual.controls?.replayRejected === true && actual.controls?.staleProofRejected === true && actual.controls?.wrongEnrollmentRejected === true, actual.controls);
  check(`${wanted.label} tamper scope`, wanted.label === "full-check" ? actual.controls?.tamperedResponseRejected === true : actual.controls?.tamperedResponseRejected === null, actual.controls);
}
const digest = (name) => crypto.createHash("sha256").update(fs.readFileSync(path.join(root, "results", name))).digest("hex");
const report = {
  overall: checks.every((entry) => entry.pass) ? "PASS" : "FAIL",
  scope: "SpotCheck N=128 eta=1,2,4,8 with three transactions each; FullCheck is companion output and not a new Fig3 point",
  checks,
  artifacts: ["setup-summary.json", "setup-artifacts.sha256", "hom-complete.json"].map((name) => ({ name, sha256: digest(name) })),
};
fs.writeFileSync(path.join(root, "results", "verification-spotcheck.json"), `${JSON.stringify(report, null, 2)}\n`);
process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
NODE
write_spot_immutable_hashes "$SPOT_RUN/metadata/source-immutable.after.sha256"
diff -u "$SPOT_RUN/metadata/source-immutable.before.sha256" "$SPOT_RUN/metadata/source-immutable.after.sha256" \
  >"$SPOT_RUN/metadata/source-immutable.after.diff"
snapshot_environment "$SPOT_PROJECT" "$SPOT_RUN/metadata/environment.after.txt"
(
  cd "$SPOT_RUN"
  find results metadata logs -type f ! -name '._*' -print0 | sort -z | xargs -0 sha256sum
) >"$SPOT_RUN/manifest.sha256"
{
  printf 'status=COMPLETE\n'
  printf 'timestamp=%s\n' "$(date -Ins)"
  printf 'supervisor_pid=%s\n' "$$"
  printf 'project_root=%s\n' "$SPOT_PROJECT"
  printf 'verification=%s\n' "$SPOT_RUN/results/verification-spotcheck.json"
} >"$SPOT_RUN/COMPLETE"
log "SpotCheck COMPLETE; proceeding serially to CircuitCheck"

CURRENT_STAGE="circuitcheck-provenance"
cp "$GRID_EXPECTED_HASHES" "$GRID_RUN/metadata/source-hashes.expected.sha256"
write_grid_source_hashes "$GRID_RUN/metadata/source-hashes.before.sha256"
diff -u "$GRID_RUN/metadata/source-hashes.expected.sha256" "$GRID_RUN/metadata/source-hashes.before.sha256" \
  >"$GRID_RUN/metadata/source-hashes.deploy.diff"
snapshot_environment "$GRID_PROJECT" "$GRID_RUN/metadata/environment.before.txt"

CURRENT_STAGE="circuitcheck-npm-ci"
log "validating preinstalled CircuitCheck package-lock dependency graph (offline; npm ci disabled)"
[[ -d "$GRID_PROJECT/node_modules" ]] || {
  log "missing preinstalled CircuitCheck node_modules; refusing registry access"
  exit 1
}
if (
  cd "$GRID_PROJECT"
  npm ls --all
) >"$GRID_RUN/metadata/npm-ls.txt" 2>&1; then
  {
    printf 'mode=preinstalled-node_modules\n'
    printf 'validation=npm ls --all\n'
    printf 'npm_ci=SKIPPED\n'
    printf 'network_registry_access=DISABLED\n'
  } >"$GRID_RUN/metadata/npm-install-mode.txt"
  log "CircuitCheck npm ls passed; skipping npm ci and all registry access"
else
  log "CircuitCheck npm ls failed; refusing npm ci or registry fallback"
  exit 1
fi

CURRENT_STAGE="circuitcheck-grid"
log "starting fresh seven-size CircuitCheck grid on CPU0; sampler CPU1; proof 1+10; gas 1+5"
start_sampler "$GRID_RUN/logs/host-load-frequency-cpu0-cpu20.tsv" "$GRID_RUN/logs/experiment-sampler.stop"
set +e
/usr/bin/time -v -o "$GRID_RUN/metadata/experiment.time-v.txt" \
  taskset -c 0 env \
    BIOZERO_GRID_WARMUPS=1 BIOZERO_GRID_REPETITIONS=10 \
    BIOZERO_GRID_GAS_WARMUPS=1 BIOZERO_GRID_GAS_REPETITIONS=5 \
    RAYON_NUM_THREADS=1 UV_THREADPOOL_SIZE=1 OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
    npm --prefix "$GRID_PROJECT" run experiment \
    >"$GRID_RUN/logs/experiment.stdout.log" \
    2>"$GRID_RUN/logs/experiment.stderr.log"
grid_rc="$?"
set -e
printf '%s\n' "$grid_rc" >"$GRID_RUN/metadata/experiment.exit"
stop_sampler
(( grid_rc == 0 )) || exit "$grid_rc"

CURRENT_STAGE="circuitcheck-verification"
[[ -f "$GRID_PROJECT/results/verification.json" ]] || { log "missing CircuitCheck verification.json"; exit 1; }
[[ -f "$GRID_PROJECT/results/manifest.json" ]] || { log "missing CircuitCheck manifest.json"; exit 1; }
GRID_VERIFICATION="$GRID_PROJECT/results/verification.json" node -e '
  const fs = require("node:fs");
  const report = JSON.parse(fs.readFileSync(process.env.GRID_VERIFICATION, "utf8"));
  if (report.overall !== "PASS") throw new Error(`CircuitCheck verification is ${report.overall}`);
'
cp "$GRID_PROJECT/results/verification.json" "$GRID_RUN/metadata/verification.json"
cp "$GRID_PROJECT/results/manifest.json" "$GRID_RUN/metadata/manifest.json"
snapshot_environment "$GRID_PROJECT" "$GRID_RUN/metadata/environment.after.txt"
write_grid_source_hashes "$GRID_RUN/metadata/source-hashes.after.sha256"
diff -u "$GRID_RUN/metadata/source-hashes.before.sha256" "$GRID_RUN/metadata/source-hashes.after.sha256" \
  >"$GRID_RUN/metadata/source-hashes.after.diff"
{
  printf 'status=COMPLETE\n'
  printf 'timestamp=%s\n' "$(date -Ins)"
  printf 'supervisor_pid=%s\n' "$$"
  printf 'experiment_exit=%s\n' "$grid_rc"
  printf 'project_root=%s\n' "$GRID_PROJECT"
} >"$GRID_RUN/COMPLETE"
log "CircuitCheck COMPLETE run_root=$GRID_RUN"
