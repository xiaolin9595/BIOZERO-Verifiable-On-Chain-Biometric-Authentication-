import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const read = (path) => JSON.parse(readFileSync(resolve(root, path), "utf8"));
const currentHom = read("results/hom-complete.json");
const currentCircuit = read("results/circuit-complete.json");
const currentPacked = read("results/packed-proving.json");
const recordedHom = read("data/hom-complete-gas.json");
const recordedCircuit = read("data/circuit-complete-gas.json");
const recordedPacked = read("data/routea-proving.json");

const delta = (current, recorded) => ({
  current,
  recorded,
  absoluteDelta: Number((current - recorded).toFixed(2)),
  percentDelta: Number((100 * (current / recorded - 1)).toFixed(3)),
});
const gas = [
  ...currentHom.results.map((row) => {
    const recorded = recordedHom.results.find((candidate) => candidate.label === row.label);
    return { strategy: row.label, dimension: 128, ...delta(row.medianGasUsed, recorded.medianGasUsed) };
  }),
  ...currentCircuit.results.map((row) => {
    const recorded = recordedCircuit.results.find((candidate) => candidate.dimension === row.dimension);
    return { strategy: "circuit-check", dimension: row.dimension, ...delta(row.medianGasUsed, recorded.medianGasUsed) };
  }),
];
const proving = currentPacked.results.map((row) => {
  const recorded = recordedPacked.results.find((candidate) => candidate.circuit === row.circuit);
  return {
    circuit: row.circuit,
    dimension: row.dimension,
    constraintsMatch: row.constraints === recorded.constraints,
    proveElapsedMs: delta(row.proof.medianElapsedMs, recorded.proof.medianElapsedMs),
    proveMaxRssMiB: delta(row.proof.medianProcessMaxRssMiB, recorded.proof.medianPeakWorkingSetMiB),
    caveat: "Different OS/CPU/Node and reconstructed profiler semantics; comparison is descriptive, not a reproduction tolerance test.",
  };
});
writeFileSync(resolve(root, "results", "comparison-to-recorded.json"), `${JSON.stringify({
  generatedAt: new Date().toISOString(),
  gas,
  proving,
}, null, 2)}\n`, "utf8");
writeFileSync(resolve(root, "results", "comparison-to-recorded-gas.csv"), `${[
  "strategy,dimension,current_median_gas,recorded_median_gas,absolute_delta,percent_delta",
  ...gas.map((row) => [row.strategy, row.dimension, row.current, row.recorded, row.absoluteDelta, row.percentDelta].join(",")),
].join("\n")}\n`, "utf8");
