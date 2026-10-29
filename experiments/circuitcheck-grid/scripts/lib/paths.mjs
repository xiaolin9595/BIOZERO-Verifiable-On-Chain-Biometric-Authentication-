import { resolve } from "node:path";
import { ROOT, circuitName } from "../config.mjs";

export function pathsFor(dimension) {
  const name = circuitName(dimension);
  const circuitBuild = resolve(ROOT, "build", "circuits", name);
  const provingBuild = resolve(ROOT, "build", "proving", name);
  return {
    name,
    source: resolve(ROOT, "circuits", `${name}.circom`),
    input: resolve(ROOT, "inputs", "generated", `${name}.json`),
    circuitBuild,
    r1cs: resolve(circuitBuild, `${name}.r1cs`),
    wasm: resolve(circuitBuild, `${name}_js`, `${name}.wasm`),
    sym: resolve(circuitBuild, `${name}.sym`),
    provingBuild,
    zkey0: resolve(provingBuild, `${name}_0000.zkey`),
    zkey: resolve(provingBuild, `${name}_benchmark_final.zkey`),
    vkey: resolve(provingBuild, "verification_key.json"),
    verifier: resolve(ROOT, "contracts", "generated", `Groth16Verifier${dimension}.sol`),
  };
}
