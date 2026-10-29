import { execFileSync, spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  DEFAULT_PROOF_REPETITIONS,
  DEFAULT_WARMUPS,
  ROOT,
  boundedCount,
  selectedDimensions,
} from "./config.mjs";
import {
  csv,
  mean,
  median,
  parseR1csInfo,
  sampleStandardDeviation,
  sha256,
  writeJson,
} from "./lib/audit.mjs";
import { pathsFor } from "./lib/paths.mjs";

const dimensions = selectedDimensions();
const warmups = boundedCount("BIOZERO_GRID_WARMUPS", DEFAULT_WARMUPS);
const repetitions = boundedCount("BIOZERO_GRID_REPETITIONS", DEFAULT_PROOF_REPETITIONS);
if (warmups < 1 || repetitions < 2) {
  throw new Error("proof benchmark requires at least one warmup and two measured runs");
}
const output = resolve(ROOT, "results", "proving", "raw");
const logs = resolve(ROOT, "logs", "proving");
const operationScript = resolve(ROOT, "scripts", "benchmark-operation.mjs");
const snarkjs = resolve(ROOT, "node_modules", "snarkjs", "build", "cli.cjs");
mkdirSync(output, { recursive: true });
mkdirSync(logs, { recursive: true });

const gnuTimeCommand = process.env.BIOZERO_GRID_GNU_TIME ?? "/usr/bin/time";
const gnuTimeProbe = spawnSync(gnuTimeCommand, ["--version"], { encoding: "utf8" });
const gnuTimeAvailable = gnuTimeProbe.status === 0
  && /GNU time/i.test(`${gnuTimeProbe.stdout ?? ""}\n${gnuTimeProbe.stderr ?? ""}`);
const gnuTimeReason = gnuTimeAvailable
  ? null
  : `${gnuTimeCommand} is absent or does not support GNU time -v; Node maxRSS remains separately labelled`;

function runOperation(label, args, metricsPath) {
  const nodeArgs = ["--expose-gc", operationScript, ...args, metricsPath];
  const timePath = resolve(output, `${label}-gnu-time.txt`);
  const executable = gnuTimeAvailable ? gnuTimeCommand : process.execPath;
  const executableArgs = gnuTimeAvailable
    ? ["-v", "-o", timePath, process.execPath, ...nodeArgs]
    : nodeArgs;
  const child = spawnSync(executable, executableArgs, {
    cwd: ROOT,
    encoding: "utf8",
    maxBuffer: 32 * 2 ** 20,
  });
  writeFileSync(resolve(logs, `${label}.stdout.log`), child.stdout ?? "", "utf8");
  writeFileSync(resolve(logs, `${label}.stderr.log`), child.stderr ?? "", "utf8");
  if (child.error) throw child.error;
  if (child.status !== 0) throw new Error(`${label} exited with ${child.status}; inspect logs/proving`);
  const metrics = JSON.parse(readFileSync(metricsPath, "utf8"));
  let gnuTimeMaximumResidentSetKiB = null;
  if (gnuTimeAvailable) {
    const timeOutput = readFileSync(timePath, "utf8");
    const match = timeOutput.match(/Maximum resident set size \(kbytes\):\s+(\d+)/);
    if (!match) throw new Error(`cannot parse GNU time maximum RSS from ${timePath}`);
    gnuTimeMaximumResidentSetKiB = Number(match[1]);
  }
  const enriched = {
    ...metrics,
    externalRss: {
      available: gnuTimeAvailable,
      source: gnuTimeAvailable ? "GNU /usr/bin/time -v Maximum resident set size (kbytes)" : null,
      maximumResidentSetKiB: gnuTimeMaximumResidentSetKiB,
      maximumResidentSetMiB: gnuTimeMaximumResidentSetKiB == null
        ? null
        : Number((gnuTimeMaximumResidentSetKiB / 1024).toFixed(2)),
      raw: gnuTimeAvailable ? `results/proving/raw/${label}-gnu-time.txt` : null,
      unavailableReason: gnuTimeReason,
    },
  };
  writeFileSync(metricsPath, `${JSON.stringify(enriched, null, 2)}\n`, "utf8");
  return enriched;
}

function distribution(values) {
  return {
    samples: values.length,
    values,
    mean: Number(mean(values).toFixed(2)),
    sampleStandardDeviation: Number(sampleStandardDeviation(values).toFixed(2)),
    median: Number(median(values).toFixed(2)),
  };
}

function summarizePipeline(samples) {
  const externalValues = samples
    .map((sample) => sample.externalRss.maximumResidentSetMiB)
    .filter((value) => value != null);
  return {
    samples: samples.length,
    definition: "single cold child from immediately before wtns.calculate through Groth16 proof and proof/public JSON writes",
    endToEndMs: distribution(samples.map((sample) => sample.elapsedMs)),
    witnessSegmentMs: distribution(samples.map((sample) => sample.witnessElapsedMs)),
    proveAndWriteSegmentMs: distribution(samples.map((sample) => sample.proveElapsedMs)),
    nodeProcessMaxRssMiB: distribution(samples.map((sample) => sample.processMaxRssMiB)),
    externalGnuTimeMaxRssMiB: {
      available: externalValues.length === samples.length,
      source: "GNU /usr/bin/time -v Maximum resident set size; never mixed with Node maxRSS",
      ...(externalValues.length === samples.length
        ? distribution(externalValues)
        : { values: [], unavailableReason: gnuTimeReason }),
    },
  };
}

const rawRows = [];
const results = [];
for (const dimension of dimensions) {
  const paths = pathsFor(dimension);
  const info = execFileSync(process.execPath, [snarkjs, "r1cs", "info", paths.r1cs], { encoding: "utf8" });
  const operations = { pipeline: [], verify: [] };
  const totalRuns = warmups + repetitions;
  for (let sequence = 1; sequence <= totalRuns; sequence += 1) {
    const measured = sequence > warmups;
    const phase = measured ? "measured" : "warmup";
    const run = measured ? sequence - warmups : sequence;
    const stem = `${paths.name}-${phase}-${String(run).padStart(2, "0")}`;
    const witness = resolve(output, `${stem}.wtns`);
    const proof = resolve(output, `${stem}-proof.json`);
    const publicSignals = resolve(output, `${stem}-public.json`);
    const specifications = [
      ["pipeline", ["pipeline", paths.input, paths.wasm, paths.zkey, witness, proof, publicSignals]],
      ["verify", ["verify", paths.vkey, publicSignals, proof]],
    ];
    for (const [operation, args] of specifications) {
      const metricsPath = resolve(output, `${stem}-${operation}-metrics.json`);
      const metrics = runOperation(`${stem}-${operation}`, args, metricsPath);
      const sample = { dimension, circuit: paths.name, phase, run, measured, ...metrics };
      rawRows.push(sample);
      if (measured) operations[operation].push(metrics);
      process.stdout.write(`[proofs] N=${dimension} ${phase} ${run} ${operation}: ${metrics.elapsedMs} ms\n`);
    }
  }
  const proofMaterialForGas = [];
  for (const [phase, runs] of [["warmup", 1], ["measured", Math.min(5, repetitions)]]) {
    for (let run = 1; run <= runs; run += 1) {
      const stem = `${paths.name}-${phase}-${String(run).padStart(2, "0")}`;
      const proof = resolve(output, `${stem}-proof.json`);
      const publicSignals = resolve(output, `${stem}-public.json`);
      proofMaterialForGas.push({
        phase,
        run,
        proof: `results/proving/raw/${stem}-proof.json`,
        proofSha256: await sha256(proof),
        publicSignals: `results/proving/raw/${stem}-public.json`,
        publicSignalsSha256: await sha256(publicSignals),
      });
    }
  }
  results.push({
    dimension,
    circuit: paths.name,
    constraints: parseR1csInfo(info),
    publicInputs: 5,
    warmups,
    repetitions,
    provingPipeline: summarizePipeline(operations.pipeline),
    verification: {
      elapsedMs: distribution(operations.verify.map((sample) => sample.elapsedMs)),
      allVerified: operations.verify.every((sample) => sample.verified === true),
    },
    proofMaterialForGas,
    artifacts: {
      r1csSha256: await sha256(paths.r1cs),
      wasmSha256: await sha256(paths.wasm),
      zkeySha256: await sha256(paths.zkey),
      zkeyBytes: statSync(paths.zkey).size,
      verificationKeySha256: await sha256(paths.vkey),
    },
  });
}

await writeJson(resolve(ROOT, "results", "proving.json"), {
  generatedAt: new Date().toISOString(),
  status: "fresh local benchmark; not a historical measurement",
  dimensions,
  protocol: {
    warmups,
    measuredRuns: repetitions,
    execution: "one cold Node child for witness+prove+write, followed by one cold verification child",
    provingTimeDefinition: "endToEndMs, not prove-only: begins before witness calculation and ends after proof/public JSON writes",
    rss: {
      node: "process.resourceUsage().maxRSS, labelled separately",
      external: gnuTimeAvailable
        ? "GNU /usr/bin/time -v Maximum resident set size captured per cold child"
        : gnuTimeReason,
    },
  },
  toolchain: { node: process.version, snarkjs: "0.7.6" },
  results,
});
writeFileSync(resolve(ROOT, "results", "proving-raw.csv"), csv([
  ["dimension", "circuit", "phase", "run", "measured", "operation", "end_to_end_ms", "witness_segment_ms", "prove_write_segment_ms", "node_process_max_rss_mib", "gnu_time_max_rss_mib", "verified"],
  ...rawRows.map((row) => [row.dimension, row.circuit, row.phase, row.run, row.measured, row.operation, row.elapsedMs, row.witnessElapsedMs ?? "", row.proveElapsedMs ?? "", row.processMaxRssMiB, row.externalRss.maximumResidentSetMiB ?? "", row.verified ?? ""]),
]), "utf8");
