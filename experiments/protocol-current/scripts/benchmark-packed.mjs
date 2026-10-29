import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { arch, cpus, freemem, hostname, platform, release, totalmem } from "node:os";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const output = resolve(root, "results", "packed-proving");
const logs = resolve(root, "logs", "packed-proving");
const operation = resolve(root, "scripts", "benchmark-operation.mjs");
const snarkjs = resolve(root, "node_modules", "snarkjs", "build", "cli.cjs");
const repetitions = Number(process.env.BIOZERO_REPETITIONS ?? "3");
if (!Number.isInteger(repetitions) || repetitions < 1 || repetitions > 20) throw new Error("BIOZERO_REPETITIONS must be an integer from 1 to 20");
mkdirSync(output, { recursive: true });
mkdirSync(logs, { recursive: true });

const sha256 = (path) => createHash("sha256").update(readFileSync(path)).digest("hex");
const median = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
};
const round = (value) => Number(value.toFixed(2));
function execute(label, args, metricsPath) {
  try {
    const stdout = execFileSync(process.execPath, ["--expose-gc", operation, ...args, metricsPath], { cwd: root, encoding: "utf8", maxBuffer: 16 * 2 ** 20 });
    writeFileSync(resolve(logs, `${label}.stdout.log`), stdout, "utf8");
    writeFileSync(resolve(logs, `${label}.stderr.log`), "", "utf8");
    return JSON.parse(readFileSync(metricsPath, "utf8"));
  } catch (error) {
    writeFileSync(resolve(logs, `${label}.stdout.log`), error.stdout?.toString() ?? "", "utf8");
    writeFileSync(resolve(logs, `${label}.stderr.log`), error.stderr?.toString() ?? error.stack ?? String(error), "utf8");
    throw error;
  }
}
const rows = [];
const results = [];
for (const dimension of [128, 512]) {
  const name = `auth_distance_${dimension}`;
  const circuitRoot = resolve(root, "build", name);
  const provingRoot = resolve(root, "build", "proving", name);
  const input = resolve(root, "inputs", "generated", `${name}.json`);
  const wasm = resolve(circuitRoot, `${name}_js`, `${name}.wasm`);
  const r1cs = resolve(circuitRoot, `${name}.r1cs`);
  const zkey = resolve(provingRoot, `${name}_benchmark_final.zkey`);
  const vkey = resolve(provingRoot, "verification_key.json");
  const info = execFileSync(process.execPath, [snarkjs, "r1cs", "info", r1cs], { encoding: "utf8" });
  const constraints = Number(info.match(/# of Constraints:\s+(\d+)/)?.[1]);
  const byOperation = { witness: [], prove: [], verify: [] };
  for (let run = 1; run <= repetitions; run += 1) {
    const stem = `run-${String(run).padStart(2, "0")}`;
    const witness = resolve(output, `${name}-${stem}.wtns`);
    const proof = resolve(output, `${name}-${stem}-proof.json`);
    const publicSignals = resolve(output, `${name}-${stem}-public.json`);
    const specs = [
      ["witness", ["witness", input, wasm, witness]],
      ["prove", ["prove", zkey, witness, proof, publicSignals]],
      ["verify", ["verify", vkey, publicSignals, proof]],
    ];
    for (const [kind, args] of specs) {
      const metricsPath = resolve(output, `${name}-${stem}-${kind}-metrics.json`);
      const metrics = execute(`${name}-${stem}-${kind}`, args, metricsPath);
      byOperation[kind].push(metrics);
      rows.push({ circuit: name, dimension, run, ...metrics });
      process.stdout.write(`[packed] ${name} ${stem} ${kind}: ${metrics.elapsedMs} ms, maxRSS ${metrics.processMaxRssMiB} MiB\n`);
    }
  }
  const summarize = (values) => ({
    elapsedMs: values.map((value) => value.elapsedMs),
    medianElapsedMs: round(median(values.map((value) => value.elapsedMs))),
    processMaxRssMiB: values.map((value) => value.processMaxRssMiB),
    medianProcessMaxRssMiB: round(median(values.map((value) => value.processMaxRssMiB))),
    baselineRssMiB: values.map((value) => value.baselineRssMiB),
  });
  results.push({
    circuit: name,
    dimension,
    constraints,
    publicInputs: 5,
    repetitions,
    witness: summarize(byOperation.witness),
    proof: { ...summarize(byOperation.prove), canonicalUncompressedBytes: 256 },
    verification: summarize(byOperation.verify),
    artifacts: {
      sourceSha256: sha256(resolve(root, "circuits", `${name}.circom`)),
      r1csSha256: sha256(r1cs),
      wasmSha256: sha256(wasm),
      zkeySha256: sha256(zkey),
      provingKeyBytes: statSync(zkey).size,
      verificationKeyJsonBytes: statSync(vkey).size,
    },
  });
}

const record = {
  generatedAt: new Date().toISOString(),
  status: "reconstructed fresh run; not the historical Windows measurement",
  warning: "Fresh local single-party benchmark setup; never use these keys in production.",
  rssSemantics: "Cold child process process.resourceUsage().maxRSS, Node reports KiB, converted to MiB.",
  host: {
    hostname: hostname(), platform: platform(), release: release(), arch: arch(),
    cpu: cpus()[0]?.model, logicalProcessors: cpus().length,
    totalMemoryGiB: round(totalmem() / 2 ** 30), freeMemoryAtRecordGiB: round(freemem() / 2 ** 30),
    node: process.version, snarkjs: "0.7.6", circom: "2.2.3 (circom2 npm 0.2.23)",
  },
  results,
};
writeFileSync(resolve(root, "results", "packed-proving.json"), `${JSON.stringify(record, null, 2)}\n`, "utf8");
const csvHeader = "circuit,dimension,run,operation,elapsed_ms,baseline_rss_mib,sampled_peak_rss_mib,process_max_rss_mib,verified";
const csvRows = rows.map((row) => [row.circuit, row.dimension, row.run, row.operation, row.elapsedMs, row.baselineRssMiB, row.sampledPeakRssMiB, row.processMaxRssMiB, row.verified ?? ""].join(","));
writeFileSync(resolve(root, "results", "packed-proving-raw.csv"), `${[csvHeader, ...csvRows].join("\n")}\n`, "utf8");
const summaryHeader = "circuit,dimension,constraints,repetitions,witness_median_ms,prove_median_ms,verify_median_ms,prove_median_max_rss_mib";
const summaryRows = results.map((result) => [result.circuit, result.dimension, result.constraints, result.repetitions, result.witness.medianElapsedMs, result.proof.medianElapsedMs, result.verification.medianElapsedMs, result.proof.medianProcessMaxRssMiB].join(","));
writeFileSync(resolve(root, "results", "packed-proving-summary.csv"), `${[summaryHeader, ...summaryRows].join("\n")}\n`, "utf8");
