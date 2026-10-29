#!/usr/bin/env node

import fs from "node:fs";

const [csvPath, jsonPath] = process.argv.slice(2);
if (!csvPath || !jsonPath) {
  throw new Error("usage: records_to_json.mjs RAW_CSV RAW_JSON");
}

const lines = fs.readFileSync(csvPath, "utf8").trim().split(/\r?\n/);
const headers = lines.shift().split(",");
const numeric = new Set([
  "dimension",
  "attempt",
  "measured_round",
  "witness_wall_ms",
  "prove_wall_ms",
  "witness_bytes",
  "proof_bytes",
]);
const rows = lines.filter(Boolean).map((line) => {
  const values = line.split(",");
  return Object.fromEntries(
    headers.map((header, index) => [
      header,
      numeric.has(header) ? Number(values[index]) : values[index],
    ]),
  );
});
fs.writeFileSync(jsonPath, `${JSON.stringify(rows, null, 2)}\n`);

