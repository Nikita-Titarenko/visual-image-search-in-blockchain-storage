const fs = require("fs");
const path = require("path");
const hre = require("hardhat");

const REPORTS_DIR = path.resolve(__dirname, "..", "reports");
const REPORT_FILE_PATH = path.join(REPORTS_DIR, "register-collection-confirmation.json");
const DEFAULT_RUNS = 5;

function ensureReportsDir() {
  fs.mkdirSync(REPORTS_DIR, { recursive: true });
}

function writeReport(report) {
  ensureReportsDir();
  fs.writeFileSync(REPORT_FILE_PATH, `${JSON.stringify(report, null, 2)}\n`, "utf8");
}

function summarizeMeasurements(measurements) {
  const durations = measurements.map((entry) => entry.confirmationTimeMs);
  const total = durations.reduce((sum, value) => sum + value, 0);
  return {
    count: durations.length,
    minMs: Math.min(...durations),
    maxMs: Math.max(...durations),
    avgMs: Number((total / durations.length).toFixed(2)),
  };
}

async function parseCollectionId(receipt, contractInterface) {
  for (const log of receipt.logs) {
    try {
      const parsedLog = contractInterface.parseLog(log);
      if (parsedLog?.name === "CollectionRegistered") {
        return parsedLog.args.collectionId.toString();
      }
    } catch {
      continue;
    }
  }

  throw new Error(`CollectionRegistered event was not found in tx ${receipt.hash}.`);
}

async function measureRegisterCollection({ contract, provider, labelPrefix, runs, metadataUriPrefix }) {
  const measurements = [];

  for (let runNumber = 1; runNumber <= runs; runNumber++) {
    const metadataUri = `${metadataUriPrefix}/${runNumber}`;
    const submittedAtMs = Date.now();
    const tx = await contract.registerCollection(metadataUri);
    const receipt = await tx.wait();
    const confirmedAtMs = Date.now();
    const block = await provider.getBlock(receipt.blockNumber);

    measurements.push({
      run: runNumber,
      metadataURI: metadataUri,
      transactionHash: receipt.hash,
      blockNumber: receipt.blockNumber,
      gasUsed: receipt.gasUsed.toString(),
      effectiveGasPriceWei: receipt.gasPrice?.toString() ?? null,
      collectionId: await parseCollectionId(receipt, contract.interface),
      submittedAtMs,
      confirmedAtMs,
      confirmationTimeMs: confirmedAtMs - submittedAtMs,
      blockTimestamp: block ? new Date(Number(block.timestamp) * 1000).toISOString() : null,
    });

    console.log(
      `[${labelPrefix}] run ${runNumber}/${runs}: ${receipt.hash} confirmed in ${confirmedAtMs - submittedAtMs} ms`
    );
  }

  return measurements;
}

async function measureLocalNetwork(runs) {
  const [localSigner] = await hre.ethers.getSigners();
  const factory = await hre.ethers.getContractFactory("ImageRegistry", localSigner);
  const contract = await factory.deploy();
  await contract.waitForDeployment();

  const contractAddress = await contract.getAddress();
  console.log(`[local] ImageRegistry deployed: ${contractAddress}`);

  const measurements = await measureRegisterCollection({
    contract,
    provider: hre.ethers.provider,
    labelPrefix: "local",
    runs,
    metadataUriPrefix: "ipfs://local-collection",
  });

  return {
    network: "hardhat",
    rpcUrl: "in-process hardhat network",
    signer: await localSigner.getAddress(),
    contractAddress,
    deploymentMode: "fresh deploy",
    summary: summarizeMeasurements(measurements),
    measurements,
  };
}

function getRequiredEnv(name) {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`${name} is required to measure on Polygon Amoy.`);
  }
  return value;
}

async function measureAmoyNetwork(runs) {
  const rpcUrl = process.env.POLYGON_AMOY_RPC_URL?.trim() || "https://rpc-amoy.polygon.technology";
  const privateKey = getRequiredEnv("DEPLOYER_PRIVATE_KEY");
  const contractAddress = getRequiredEnv("IMAGE_REGISTRY_ADDRESS");

  if (!hre.ethers.isAddress(contractAddress)) {
    throw new Error(`IMAGE_REGISTRY_ADDRESS is not a valid address: ${contractAddress}`);
  }

  const provider = new hre.ethers.JsonRpcProvider(rpcUrl);
  const signer = new hre.ethers.Wallet(privateKey, provider);
  const artifact = await hre.artifacts.readArtifact("ImageRegistry");
  const contract = new hre.ethers.Contract(contractAddress, artifact.abi, signer);

  console.log(`[amoy] Using ImageRegistry at: ${contractAddress}`);
  console.log(`[amoy] Signer: ${signer.address}`);

  const measurements = await measureRegisterCollection({
    contract,
    provider,
    labelPrefix: "amoy",
    runs,
    metadataUriPrefix: "ipfs://amoy-collection",
  });

  return {
    network: "amoy",
    rpcUrl,
    signer: signer.address,
    contractAddress,
    deploymentMode: "existing deployment from IMAGE_REGISTRY_ADDRESS",
    summary: summarizeMeasurements(measurements),
    measurements,
  };
}

async function main() {
  const report = {
    generatedAt: new Date().toISOString(),
    operation: "registerCollection",
    runsPerNetwork: DEFAULT_RUNS,
    results: [],
  };

  report.results.push(await measureLocalNetwork(DEFAULT_RUNS));
  writeReport(report);

  report.results.push(await measureAmoyNetwork(DEFAULT_RUNS));
  writeReport(report);

  console.log(`Saved report to: ${REPORT_FILE_PATH}`);
  for (const result of report.results) {
    console.log(
      `[${result.network}] count=${result.summary.count}, min=${result.summary.minMs} ms, avg=${result.summary.avgMs} ms, max=${result.summary.maxMs} ms`
    );
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});