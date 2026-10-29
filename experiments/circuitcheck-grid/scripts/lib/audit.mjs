import { createHash } from "node:crypto";
import { readdir, readFile, stat, writeFile } from "node:fs/promises";
import { relative, resolve } from "node:path";

export function json(value) {
  return `${JSON.stringify(value, (_, nested) => (
    typeof nested === "bigint" ? nested.toString() : nested
  ), 2)}\n`;
}

export async function writeJson(path, value) {
  await writeFile(path, json(value), "utf8");
}

export async function sha256(path) {
  return createHash("sha256").update(await readFile(path)).digest("hex");
}

export function sha256Text(value) {
  return createHash("sha256").update(value).digest("hex");
}

export function median(values) {
  if (values.length === 0) throw new Error("cannot compute median of an empty list");
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2;
}

export function mean(values) {
  if (values.length === 0) throw new Error("cannot compute mean of an empty list");
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

export function sampleStandardDeviation(values) {
  if (values.length < 2) throw new Error("sample standard deviation requires at least two values");
  const average = mean(values);
  const squaredError = values.reduce((sum, value) => sum + (value - average) ** 2, 0);
  return Math.sqrt(squaredError / (values.length - 1));
}

export function csv(rows) {
  return `${rows.map((row) => row.map((value) => {
    const rendered = value == null ? "" : String(value);
    return /[",\n]/.test(rendered) ? `"${rendered.replaceAll('"', '""')}"` : rendered;
  }).join(",")).join("\n")}\n`;
}

export async function filesUnder(directory) {
  const entries = (await readdir(directory, { withFileTypes: true }))
    .filter((entry) => !entry.name.startsWith("._") && entry.name !== ".DS_Store");
  const nested = await Promise.all(entries.map(async (entry) => {
    const path = resolve(directory, entry.name);
    if (entry.isDirectory()) return filesUnder(path);
    return entry.isFile() ? [path] : [];
  }));
  return nested.flat().sort();
}

export async function fileRecord(root, path, classification) {
  const info = await stat(path);
  return {
    classification,
    path: relative(root, path),
    bytes: info.size,
    sha256: await sha256(path),
  };
}

export function parseR1csInfo(output) {
  const constraints = Number(output.match(/# of Constraints:\s+(\d+)/)?.[1]);
  if (!Number.isInteger(constraints)) throw new Error(`cannot parse r1cs constraints from:\n${output}`);
  return constraints;
}

export function receiptRecord(transaction, receipt) {
  return {
    transactionHash: receipt.hash,
    blockNumber: receipt.blockNumber,
    blockHash: receipt.blockHash,
    status: Number(receipt.status),
    gasUsed: Number(receipt.gasUsed),
    cumulativeGasUsed: Number(receipt.cumulativeGasUsed),
    contractAddress: receipt.contractAddress,
    from: receipt.from,
    to: receipt.to,
    transactionType: receipt.type,
    transactionDataSha256: sha256Text(transaction.data ?? "0x"),
    transactionDataBytes: Math.max(0, ((transaction.data ?? "0x").length - 2) / 2),
  };
}
