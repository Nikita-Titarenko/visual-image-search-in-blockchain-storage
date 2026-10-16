const fs = require("fs");
const path = require("path");
const hre = require("hardhat");

const OUTPUT_PATH = path.resolve(
  process.env.BENCHMARK_STACK_PATH || path.join(__dirname, "..", "reports", "local-benchmark-stack.json")
);

function ensureOutputDir() {
  fs.mkdirSync(path.dirname(OUTPUT_PATH), { recursive: true });
}

async function main() {
  if (!["localhost", "hardhat"].includes(hre.network.name)) {
    throw new Error(`This script must run on a local Hardhat network. Current network: ${hre.network.name}`);
  }

  const [deployer] = await hre.ethers.getSigners();
  const ImageRegistry = await hre.ethers.getContractFactory("ImageRegistry");
  const LicensingAndPayment = await hre.ethers.getContractFactory("LicensingAndPayment");
  const ModelAndIndexAudit = await hre.ethers.getContractFactory("ModelAndIndexAudit");

  const imageRegistry = await ImageRegistry.deploy();
  await imageRegistry.waitForDeployment();

  const licensingAndPayment = await LicensingAndPayment.deploy(
    await imageRegistry.getAddress(),
    deployer.address
  );
  await licensingAndPayment.waitForDeployment();

  const modelAndIndexAudit = await ModelAndIndexAudit.deploy(deployer.address);
  await modelAndIndexAudit.waitForDeployment();

  const payload = {
    generatedAt: new Date().toISOString(),
    network: hre.network.name,
    deployerAddress: deployer.address,
    hardhatRpcUrl: process.env.BENCHMARK_RPC_URL || "http://127.0.0.1:8545",
    hardhatWsUrl: process.env.BENCHMARK_WS_URL || "ws://127.0.0.1:8545",
    accessBaseUrl: process.env.BENCHMARK_ACCESS_BASE_URL || "http://127.0.0.1:8000",
    vectorBaseUrl: process.env.BENCHMARK_VECTOR_BASE_URL || "http://127.0.0.1:8010",
    pinataProxyBaseUrl: process.env.BENCHMARK_PINATA_PROXY_BASE_URL || `http://127.0.0.1:${process.env.PINATA_UPLOAD_PORT?.trim() || "3001"}`,
    imageRegistryAddress: await imageRegistry.getAddress(),
    licensingAndPaymentAddress: await licensingAndPayment.getAddress(),
    modelAndIndexAuditAddress: await modelAndIndexAudit.getAddress(),
  };

  ensureOutputDir();
  fs.writeFileSync(OUTPUT_PATH, `${JSON.stringify(payload, null, 2)}\n`, "utf8");

  console.log("ImageRegistry deployed:", payload.imageRegistryAddress);
  console.log("LicensingAndPayment deployed:", payload.licensingAndPaymentAddress);
  console.log("ModelAndIndexAudit deployed:", payload.modelAndIndexAuditAddress);
  console.log("Local benchmark stack written:", OUTPUT_PATH);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});