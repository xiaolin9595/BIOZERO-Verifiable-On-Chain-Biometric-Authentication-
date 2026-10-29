import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { buildPoseidon } from "circomlibjs";
import { PACK_SIZE, ROOT, selectedDimensions } from "./config.mjs";
import { sha256, writeJson } from "./lib/audit.mjs";
import { pathsFor } from "./lib/paths.mjs";

const FORMAT_VERSION = 1n;
const DST_ENROLL = 1n;
const DST_PROBE = 2n;
const dimensions = selectedDimensions();
const poseidon = await buildPoseidon();

function deterministicVectors(dimension) {
  const enrollment = Array.from({ length: dimension }, (_, index) => (
    BigInt(10_000 + ((index * 257) % 30_000))
  ));
  const probe = enrollment.map((value, index) => value + BigInt((index % 5) - 2));
  return { enrollment, probe };
}

function squaredDistance(left, right) {
  return left.reduce((sum, value, index) => {
    const difference = value - right[index];
    return sum + difference * difference;
  }, 0n);
}

function pack(values) {
  const blocks = [];
  for (let start = 0; start < values.length; start += PACK_SIZE) {
    let packed = 0n;
    for (let offset = 0; offset < PACK_SIZE; offset += 1) {
      const value = values[start + offset] ?? 0n;
      if (value < 0n || value > 65_535n) throw new Error(`coordinate ${start + offset} outside uint16`);
      packed += value << BigInt(16 * offset);
    }
    blocks.push(packed);
  }
  if (blocks.length % 2 !== 0) blocks.push(0n);
  return blocks;
}

function commitment({ roleTag, policyDigest, contextDigest, dimension, salt, values }) {
  let chain = poseidon([roleTag, FORMAT_VERSION, policyDigest, contextDigest, BigInt(dimension), salt]);
  const blocks = pack(values);
  for (let index = 0; index < blocks.length; index += 2) {
    chain = poseidon([chain, blocks[index], blocks[index + 1]]);
  }
  return BigInt(poseidon.F.toObject(chain));
}

await mkdir(resolve(ROOT, "inputs", "generated"), { recursive: true });
const records = [];
for (const dimension of dimensions) {
  const policyDigest = 9_876_543_210_123_456_789n + BigInt(dimension);
  const ctxHash = 12_345_678_900_987_654_321n + BigInt(dimension);
  const rEnroll = 11_111_111_111_111_111_111n + BigInt(dimension);
  const rProbe = 22_222_222_222_222_222_222n + BigInt(dimension);
  const { enrollment, probe } = deterministicVectors(dimension);
  const distance = squaredDistance(enrollment, probe);
  const input = {
    cEnroll: commitment({ roleTag: DST_ENROLL, policyDigest, contextDigest: 0n, dimension, salt: rEnroll, values: enrollment }),
    cProbe: commitment({ roleTag: DST_PROBE, policyDigest, contextDigest: ctxHash, dimension, salt: rProbe, values: probe }),
    policyDigest,
    ctxHash,
    epsilon: distance + 16n,
    rEnroll,
    rProbe,
    enrollment,
    probe,
  };
  const path = pathsFor(dimension).input;
  await writeJson(path, input);
  records.push({ dimension, path: `inputs/generated/auth_distance_${dimension}.json`, distance: distance.toString(), sha256: await sha256(path) });
  process.stdout.write(`[inputs] N=${dimension} distance=${distance}\n`);
}
await writeJson(resolve(ROOT, "results", "inputs.json"), {
  generatedAt: new Date().toISOString(),
  dimensions,
  deterministicVectorRule: "enrollment[i]=10000+(257*i mod 30000); probe[i]=enrollment[i]+(i mod 5)-2",
  records,
});
if (globalThis.curve_bn128) await globalThis.curve_bn128.terminate();
