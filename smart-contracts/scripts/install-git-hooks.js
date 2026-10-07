const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const repoRoot = path.resolve(__dirname, "..", "..");
const hookPath = path.join(repoRoot, ".githooks", "pre-commit");

function main() {
  if (!fs.existsSync(path.join(repoRoot, ".git"))) {
    console.log("Skipping Git hook installation because .git was not found.");
    return;
  }

  if (fs.existsSync(hookPath)) {
    fs.chmodSync(hookPath, 0o755);
  }

  const result = spawnSync("git", ["config", "core.hooksPath", ".githooks"], {
    cwd: repoRoot,
    stdio: "inherit",
    shell: false
  });

  if (result.status !== 0) {
    process.exit(result.status || 1);
  }
}

main();