const fs = require("fs");
const path = require("path");
const dotenv = require("dotenv");

const rootDir = path.resolve(__dirname, "..");
const envPath = path.join(rootDir, ".env");
const outputPath = path.join(rootDir, "client", "src", "app", "public-env.ts");

const env = dotenv.config({ path: envPath }).parsed ?? {};
const polygonAmoyRpcUrl = env.POLYGON_AMOY_RPC_URL?.trim() || "https://rpc-amoy.polygon.technology";

const output = `export const PUBLIC_ENV = {
  polygonAmoyRpcUrl: '${polygonAmoyRpcUrl.replace(/'/g, "\\'")}',
} as const;
`;

fs.writeFileSync(outputPath, output, "utf8");
console.log(`Client public env written to ${path.relative(rootDir, outputPath)}`);