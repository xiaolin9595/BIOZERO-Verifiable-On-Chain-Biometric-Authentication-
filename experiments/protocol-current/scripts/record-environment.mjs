import { execFileSync } from "node:child_process";
import { arch, cpus, hostname, platform, release, totalmem } from "node:os";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const results = resolve(root, "results");
mkdirSync(results, { recursive: true });
const command = (file, args) => execFileSync(file, args, { cwd: root, encoding: "utf8" }).trim();
const hostPlatform = platform();
const hostArch = arch();
const record = {
  generatedAt: new Date().toISOString(),
  cwd: root,
  host: { hostname: hostname(), platform: hostPlatform, release: release(), arch: hostArch, cpu: cpus()[0]?.model, logicalProcessors: cpus().length, totalMemoryGiB: Number((totalmem() / 2 ** 30).toFixed(2)) },
  toolchain: {
    node: process.version,
    npm: command("npm", ["--version"]),
    circom: command(process.execPath, [resolve(root, "node_modules", "circom2", "cli.js"), "--version"]).split("\n"),
    snarkjs: "0.7.6",
    solc: command(process.execPath, ["-e", "console.log(require('solc').version())"]),
    ganache: "7.9.2",
    ethers: "5.8.0",
  },
  notes: [
    `Node ${process.version}; the historical Windows run used v24.19.0.`,
    hostPlatform === "darwin" && hostArch === "arm64"
      ? "Ganache reports native uWS unavailable on darwin-arm64 and falls back to pure NodeJS; EVM gas is unaffected."
      : `Measurements were recorded on ${hostPlatform}-${hostArch}; see the benchmark logs for runtime warnings.`,
    "All zkeys are fresh local benchmark-only keys and must never be deployed.",
  ],
};
writeFileSync(resolve(results, "environment.json"), `${JSON.stringify(record, null, 2)}\n`, "utf8");
