const fs = require("fs");
const path = require("path");

const clientDir = path.resolve(__dirname, "..");
const rootDir = path.resolve(clientDir, "..");
const envPath = path.join(rootDir, ".env");
const outputPath = path.join(clientDir, "src", "app", "public-env.ts");

function parseDotEnv(filePath) {
  if (!fs.existsSync(filePath)) {
    return {};
  }

  const env = {};
  const source = fs.readFileSync(filePath, "utf8");
  for (const rawLine of source.split(/\r?\n/u)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) {
      continue;
    }

    const separatorIndex = line.indexOf("=");
    if (separatorIndex === -1) {
      continue;
    }

    const key = line.slice(0, separatorIndex).trim();
    let value = line.slice(separatorIndex + 1).trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }

    env[key] = value;
  }

  return env;
}

const env = parseDotEnv(envPath);
const polygonAmoyRpcUrl = env.POLYGON_AMOY_RPC_URL?.trim() || "https://rpc-amoy.polygon.technology";

const output = `export const PUBLIC_ENV = {
  polygonAmoyRpcUrl: '${polygonAmoyRpcUrl.replace(/'/g, "\\'")}',
} as const;
`;

fs.writeFileSync(outputPath, output, "utf8");
console.log(`Client public env written to ${path.relative(rootDir, outputPath)}`);