const fs = require("fs");
const path = require("path");
const hre = require("hardhat");

const REPORTS_DIR = path.resolve(__dirname, "..", "reports");
const REPORT_FILE_PATH = path.join(REPORTS_DIR, "register-collection-gas-by-record-count.json");
const TOTAL_MEASUREMENTS = 150;
const MEASUREMENT_INTERVAL = 10;
const METADATA_URI = "ipfs://gas-record-count/QmUm6DpJz67YyZ7tGHSs9V8coZEDQcG46PwjiwRCdQ7uyT";

function ensureReportsDir() {
  fs.mkdirSync(REPORTS_DIR, { recursive: true });
}

function writeReport(report) {
  ensureReportsDir();
  fs.writeFileSync(REPORT_FILE_PATH, `${JSON.stringify(report, null, 2)}\n`, "utf8");
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

async function main() {
  const [signer] = await hre.ethers.getSigners();
  const factory = await hre.ethers.getContractFactory("ImageRegistry", signer);
  const contract = await factory.deploy();
  await contract.waitForDeployment();

  const contractAddress = await contract.getAddress();
  const measurements = [];

  console.log(`[local] ImageRegistry deployed: ${contractAddress}`);

  for (let registrationIndex = 0; registrationIndex < TOTAL_MEASUREMENTS; registrationIndex++) {
    const existingCollectionCountBeforeRegistration = registrationIndex;
    const transaction = await contract.registerCollection(METADATA_URI);
    const receipt = await transaction.wait();
    const collectionId = await parseCollectionId(receipt, contract.interface);
    const collectionCountAfterRegistration = registrationIndex + 1;

    if (collectionCountAfterRegistration % MEASUREMENT_INTERVAL !== 0) {
      continue;
    }

    measurements.push({
      existingCollectionCountBeforeRegistration,
      collectionCountAfterRegistration,
      metadataURI: METADATA_URI,
      metadataUriLengthBytes: Buffer.byteLength(METADATA_URI, "utf8"),
      transactionHash: receipt.hash,
      blockNumber: receipt.blockNumber,
      gasUsed: receipt.gasUsed.toString(),
      effectiveGasPriceWei: receipt.gasPrice?.toString() ?? null,
      collectionId,
    });

    console.log(
      `[local] collectionCount=${collectionCountAfterRegistration}, newCollectionId=${collectionId}, tx=${receipt.hash}, gas=${receipt.gasUsed.toString()}`
    );
  }

  const report = {
    generatedAt: new Date().toISOString(),
    network: "hardhat",
    operation: "registerCollection",
    variedField: "stored collection count",
    signer: await signer.getAddress(),
    contractAddress,
    totalMeasurements: TOTAL_MEASUREMENTS,
    measurementInterval: MEASUREMENT_INTERVAL,
    measurements,
  };

  writeReport(report);
  console.log(`Saved report to: ${REPORT_FILE_PATH}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});