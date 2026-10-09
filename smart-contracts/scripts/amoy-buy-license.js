const fs = require("fs");
const path = require("path");
const hre = require("hardhat");

const STATE_FILE_PATH = path.resolve(__dirname, "amoy-license-state.json");

function normalizePrivateKey(privateKey, envName) {
  if (!privateKey) {
    throw new Error(`${envName} is required in .env`);
  }

  return privateKey.startsWith("0x") ? privateKey : `0x${privateKey}`;
}

function requireAmoyNetwork() {
  if (hre.network.name !== "amoy") {
    throw new Error(`This script must be run with --network amoy. Current network: ${hre.network.name}`);
  }
}

function getRequiredAddress(envName) {
  const value = process.env[envName]?.trim();
  if (!value) {
    throw new Error(`${envName} is required in .env`);
  }
  if (!hre.ethers.isAddress(value)) {
    throw new Error(`${envName} is not a valid address: ${value}`);
  }
  return value;
}

function getBuyerPrivateKey() {
  const selectedKey = process.env.DEPLOYER_PRIVATE_KEY?.trim();

  return normalizePrivateKey(selectedKey, "DEPLOYER_PRIVATE_KEY");
}

function parseEventArg(receipt, contractInterface, eventName, argName) {
  for (const log of receipt.logs) {
    try {
      const parsed = contractInterface.parseLog(log);
      if (parsed?.name === eventName) {
        return parsed.args[argName];
      }
    } catch {
      continue;
    }
  }

  throw new Error(`Unable to parse ${eventName}.${argName} from transaction logs.`);
}

function readStateFile() {
  if (!fs.existsSync(STATE_FILE_PATH)) {
    throw new Error(`State file not found: ${STATE_FILE_PATH}. Run amoy-create-license-setup.js first.`);
  }

  return JSON.parse(fs.readFileSync(STATE_FILE_PATH, "utf8"));
}

async function main() {
  requireAmoyNetwork();

  const state = readStateFile();
  const imageRegistryAddress = getRequiredAddress("IMAGE_REGISTRY_ADDRESS");
  const licensingAddress = getRequiredAddress("LICENSING_AND_PAYMENT_ADDRESS");

  if (state.contracts?.imageRegistryAddress?.toLowerCase() !== imageRegistryAddress.toLowerCase()) {
    throw new Error("IMAGE_REGISTRY_ADDRESS in .env does not match the saved state file.");
  }
  if (state.contracts?.licensingAndPaymentAddress?.toLowerCase() !== licensingAddress.toLowerCase()) {
    throw new Error("LICENSING_AND_PAYMENT_ADDRESS in .env does not match the saved state file.");
  }

  const buyer = new hre.ethers.Wallet(getBuyerPrivateKey(), hre.ethers.provider);
  const licensing = await hre.ethers.getContractAt("LicensingAndPayment", licensingAddress, buyer);

  const imageId = BigInt(state.image.id);
  const priceWei = BigInt(state.licenseOffer.priceWei);

  if (buyer.address.toLowerCase() !== state.licenseOffer.seller.toLowerCase()) {
    throw new Error("DEPLOYER_PRIVATE_KEY must match the seller saved in the state file.");
  }

  console.log("Network:", hre.network.name);
  console.log("Buyer:", buyer.address);
  console.log("Seller:", buyer.address);
  console.log("LicensingAndPayment:", licensingAddress);
  console.log("Image ID:", imageId.toString());
  console.log("Price (wei):", priceWei.toString());
  console.log("Buying license...");

  const buyTx = await licensing.buyLicense(imageId, { value: priceWei });
  console.log("Buy tx:", buyTx.hash);
  const buyReceipt = await buyTx.wait();
  const purchaseId = parseEventArg(buyReceipt, licensing.interface, "LicensePurchased", "purchaseId");
  console.log("Purchase completed with ID:", purchaseId.toString());

  console.log("Withdrawing seller proceeds...");
  const withdrawTx = await licensing.withdrawPayments();
  console.log("Withdraw tx:", withdrawTx.hash);
  await withdrawTx.wait();
  console.log("Withdrawal completed.");

  state.purchase = {
    id: purchaseId.toString(),
    buyer: buyer.address,
    seller: buyer.address,
    imageId: imageId.toString(),
    priceWei: priceWei.toString(),
    txHash: buyTx.hash,
    purchasedAt: new Date().toISOString(),
  };

  state.withdrawal = {
    seller: buyer.address,
    amountWei: priceWei.toString(),
    txHash: withdrawTx.hash,
    withdrawnAt: new Date().toISOString(),
  };

  fs.writeFileSync(STATE_FILE_PATH, `${JSON.stringify(state, null, 2)}\n`, "utf8");
  console.log("State file updated:", STATE_FILE_PATH);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});