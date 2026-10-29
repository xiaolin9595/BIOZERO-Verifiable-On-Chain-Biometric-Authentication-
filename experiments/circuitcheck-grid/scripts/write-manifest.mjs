import { execFileSync } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { ROOT, DIMENSIONS } from "./config.mjs";
import { csv, fileRecord, filesUnder, writeJson } from "./lib/audit.mjs";

async function packageVersion(name) {
  const packageJson = JSON.parse(await readFile(resolve(ROOT, "node_modules", name, "package.json"), "utf8"));
  return packageJson.version;
}

function git(args) {
  try {
    return execFileSync("git", args, { cwd: ROOT, encoding: "utf8" }).trim();
  } catch {
    return null;
  }
}

const records = [];
async function addDirectory(directory, classification, filter = () => true) {
  for (const path of await filesUnder(directory)) {
    if (filter(path)) records.push(await fileRecord(ROOT, path, classification));
  }
}

await addDirectory(resolve(ROOT, "circuits"), "entry-source");
await addDirectory(resolve(ROOT, "scripts"), "driver-source");
for (const path of ["package.json", "package-lock.json", "README.md", ".gitignore"]) {
  records.push(await fileRecord(ROOT, resolve(ROOT, path), "experiment-source"));
}
await addDirectory(resolve(ROOT, "inputs"), "generated-input");
await addDirectory(resolve(ROOT, "contracts", "generated"), "generated-verifier");
await addDirectory(resolve(ROOT, "build"), "generated-build-artifact");
await addDirectory(resolve(ROOT, "logs"), "raw-log");
await addDirectory(resolve(ROOT, "results"), "result-or-raw-sample", (path) => ![
  resolve(ROOT, "results", "manifest.json"),
  resolve(ROOT, "results", "manifest.csv"),
].includes(path));
records.sort((left, right) => left.path.localeCompare(right.path));

const manifest = {
  schemaVersion: 1,
  generatedAt: new Date().toISOString(),
  experiment: "BioZERO CircuitCheck seven-size fresh reconstruction",
  warning: "Fresh local single-party benchmark keys; never use in production.",
  dimensions: DIMENSIONS,
  git: {
    commit: git(["rev-parse", "HEAD"]),
    worktreeStatus: git(["status", "--short", "--", "."]),
  },
  toolchain: {
    node: process.version,
    npm: execFileSync("npm", ["--version"], { cwd: ROOT, encoding: "utf8" }).trim(),
    circom2Package: await packageVersion("circom2"),
    circomlib: await packageVersion("circomlib"),
    circomlibjs: await packageVersion("circomlibjs"),
    snarkjs: await packageVersion("snarkjs"),
    solcJs: await packageVersion("solc"),
    ganache: await packageVersion("ganache"),
    ethers: await packageVersion("ethers"),
  },
  protocol: {
    proofWarmups: 1,
    proofMeasuredRuns: 10,
    gasWarmupTransactions: 1,
    gasMeasuredTransactions: 5,
    optimizerRuns: 200,
    evmVersion: "shanghai",
    eip170RuntimeLimitBytes: 24_576,
  },
  files: records,
};
await writeJson(resolve(ROOT, "results", "manifest.json"), manifest);
await writeFile(resolve(ROOT, "results", "manifest.csv"), csv([
  ["classification", "path", "bytes", "sha256"],
  ...records.map((record) => [record.classification, record.path, record.bytes, record.sha256]),
]), "utf8");
const totalBytes = records.reduce((sum, record) => sum + record.bytes, 0);
process.stdout.write(`[manifest] ${records.length} files, ${totalBytes} bytes hashed\n`);
