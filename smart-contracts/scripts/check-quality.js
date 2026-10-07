const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const projectDir = path.resolve(__dirname, "..");
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const npxCommand = process.platform === "win32" ? "npx.cmd" : "npx";

function runCommand(command, args, description) {
  console.log(`\n==> ${description}`);
  const useShell = process.platform === "win32" && /\.(cmd|bat)$/i.test(command);
  const result = spawnSync(command, args, {
    cwd: projectDir,
    stdio: "inherit",
    shell: useShell
  });

  if (result.status !== 0) {
    process.exit(result.status || 1);
  }
}

function ensureDependenciesInstalled() {
  const solhintBinary = path.join(projectDir, "node_modules", ".bin", process.platform === "win32" ? "solhint.cmd" : "solhint");
  if (!fs.existsSync(solhintBinary)) {
    console.error("solhint is not installed. Run npm install in smart-contracts first.");
    process.exit(1);
  }
}

function main() {
  ensureDependenciesInstalled();
  runCommand(npxCommand, ["solhint", "contracts/**/*.sol"], "Running Solidity static analysis");
  runCommand(npmCommand, ["run", "test"], "Running Hardhat tests");
  runCommand(npmCommand, ["run", "test:coverage"], "Running Hardhat coverage");
  runCommand(process.execPath, [path.join(__dirname, "check-coverage.js")], "Checking minimum coverage threshold");
}

main();