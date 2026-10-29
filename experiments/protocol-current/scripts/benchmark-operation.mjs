// Reconstructed replacement for the missing operation helper referenced by
// prove-benchmark.ps1. Each invocation performs exactly one cold-process
// witness/prove/verify operation and writes machine-readable metrics.
import { performance } from "node:perf_hooks";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { groth16, wtns } from "snarkjs";

const args = process.argv.slice(2);
if (args.length < 2) {
  throw new Error("usage: benchmark-operation.mjs <witness|prove|verify> <arguments...> <metrics.json>");
}

const operation = args.shift();
const metricsPath = resolve(args.pop());
if (globalThis.gc) globalThis.gc();
const baselineRssMiB = process.memoryUsage().rss / 2 ** 20;
let sampledPeakRssMiB = baselineRssMiB;
const sampler = setInterval(() => {
  sampledPeakRssMiB = Math.max(sampledPeakRssMiB, process.memoryUsage().rss / 2 ** 20);
}, 5);
sampler.unref();

const started = performance.now();
let verified;
try {
  if (operation === "witness") {
    if (args.length !== 3) throw new Error("witness requires <input.json> <circuit.wasm> <output.wtns>");
    const [inputPath, wasmPath, witnessPath] = args;
    const input = JSON.parse(await readFile(resolve(inputPath), "utf8"));
    await wtns.calculate(input, resolve(wasmPath), resolve(witnessPath), {});
  } else if (operation === "prove") {
    if (args.length !== 4) throw new Error("prove requires <final.zkey> <input.wtns> <proof.json> <public.json>");
    const [zkeyPath, witnessPath, proofPath, publicPath] = args;
    const { proof, publicSignals } = await groth16.prove(resolve(zkeyPath), resolve(witnessPath));
    await writeFile(resolve(proofPath), `${JSON.stringify(proof, null, 2)}\n`, "utf8");
    await writeFile(resolve(publicPath), `${JSON.stringify(publicSignals, null, 2)}\n`, "utf8");
  } else if (operation === "verify") {
    if (args.length !== 3) throw new Error("verify requires <verification_key.json> <public.json> <proof.json>");
    const [vkeyPath, publicPath, proofPath] = args;
    const [vkey, publicSignals, proof] = await Promise.all(
      [vkeyPath, publicPath, proofPath].map(async (path) => JSON.parse(await readFile(resolve(path), "utf8"))),
    );
    verified = await groth16.verify(vkey, publicSignals, proof);
    if (!verified) throw new Error("Groth16 verification returned false");
  } else {
    throw new Error(`unknown operation: ${operation}`);
  }
} finally {
  clearInterval(sampler);
}

const elapsedMs = performance.now() - started;
sampledPeakRssMiB = Math.max(sampledPeakRssMiB, process.memoryUsage().rss / 2 ** 20);
const processMaxRssMiB = process.resourceUsage().maxRSS / 1024;
const record = {
  operation,
  elapsedMs: Number(elapsedMs.toFixed(2)),
  baselineRssMiB: Number(baselineRssMiB.toFixed(2)),
  sampledPeakRssMiB: Number(sampledPeakRssMiB.toFixed(2)),
  processMaxRssMiB: Number(processMaxRssMiB.toFixed(2)),
  rssSemantics: "Node process.resourceUsage().maxRSS, reported by Node in KiB and converted to MiB",
  ...(verified === undefined ? {} : { verified }),
};
await mkdir(dirname(metricsPath), { recursive: true });
await writeFile(metricsPath, `${JSON.stringify(record, null, 2)}\n`, "utf8");
process.stdout.write(`${JSON.stringify(record)}\n`);
// snarkjs keeps a BN254 worker pool alive after prove/verify. This helper is a
// one-operation cold-process runner, so terminate it explicitly before exit.
if (globalThis.curve_bn128) await globalThis.curve_bn128.terminate();
process.exit(0);
