const fs = require("fs");
const path = require("path");
const hre = require("hardhat");

const STATE_FILE_PATH = path.resolve(__dirname, "amoy-license-state.json");
const TEST_IMAGE_PATH = path.resolve(__dirname, "test-images", "test-image.jpg");
const PINATA_PROXY_BASE_URL = `http://127.0.0.1:${process.env.PINATA_UPLOAD_PORT?.trim() || "3001"}`;

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

function buildContentHash(seed) {
  return hre.ethers.keccak256(hre.ethers.toUtf8Bytes(seed));
}

function hashFileContent(fileBuffer) {
  return hre.ethers.keccak256(fileBuffer);
}

function writeState(state) {
  fs.writeFileSync(STATE_FILE_PATH, `${JSON.stringify(state, null, 2)}\n`, "utf8");
  console.log("State file written:", STATE_FILE_PATH);
}

async function ensurePinataProxyIsAvailable() {
  const response = await fetch(`${PINATA_PROXY_BASE_URL}/api/pinata/health`);
  if (!response.ok) {
    throw new Error(`Pinata proxy health check failed with status ${response.status}.`);
  }
}

async function uploadImageToPinata(filePath) {
  const fileBuffer = fs.readFileSync(filePath);
  const formData = new FormData();
  formData.append(
    "file",
    new Blob([fileBuffer], { type: "image/jpeg" }),
    path.basename(filePath)
  );

  const response = await fetch(`${PINATA_PROXY_BASE_URL}/api/pinata/upload`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const payload = await response.text();
    throw new Error(`Pinata image upload failed: ${payload}`);
  }

  return await response.json();
}

async function uploadJsonToPinata(name, content) {
  const response = await fetch(`${PINATA_PROXY_BASE_URL}/api/pinata/pin-json`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ name, content }),
  });

  if (!response.ok) {
    const payload = await response.text();
    throw new Error(`Pinata JSON upload failed: ${payload}`);
  }

  return await response.json();
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

async function main() {
  requireAmoyNetwork();

  if (!fs.existsSync(TEST_IMAGE_PATH)) {
    throw new Error(`Test image not found: ${TEST_IMAGE_PATH}`);
  }

  const imageRegistryAddress = getRequiredAddress("IMAGE_REGISTRY_ADDRESS");
  const licensingAddress = getRequiredAddress("LICENSING_AND_PAYMENT_ADDRESS");
  const [creator] = await hre.ethers.getSigners();

  const imageRegistry = await hre.ethers.getContractAt("ImageRegistry", imageRegistryAddress, creator);
  const licensing = await hre.ethers.getContractAt("LicensingAndPayment", licensingAddress, creator);

  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const collectionName = `Amoy Demo Collection ${timestamp}`;
  const priceWei = hre.ethers.parseEther("0.00001");
  const testImageBuffer = fs.readFileSync(TEST_IMAGE_PATH);
  const contentHash = hashFileContent(testImageBuffer);

  const state = {
    network: hre.network.name,
    pinataProxyBaseUrl: PINATA_PROXY_BASE_URL,
    createdAt: new Date().toISOString(),
    contracts: {
      imageRegistryAddress,
      licensingAndPaymentAddress: licensingAddress,
    },
    creator: creator.address,
    collection: null,
    image: null,
    licenseOffer: null,
  };

  console.log("Network:", hre.network.name);
  console.log("Creator:", creator.address);
  console.log("ImageRegistry:", imageRegistryAddress);
  console.log("LicensingAndPayment:", licensingAddress);
  console.log("Pinata proxy:", PINATA_PROXY_BASE_URL);
  console.log("Test image:", TEST_IMAGE_PATH);
  console.log("Checking Pinata proxy health...");
  await ensurePinataProxyIsAvailable();

  console.log("Uploading collection metadata to Pinata proxy...");
  const collectionMetadata = await uploadJsonToPinata(`amoy-demo-collection-${timestamp}`, {
    name: collectionName,
    description: "Collection prepared by the Amoy setup script.",
    creatorWallet: creator.address,
    createdAt: new Date().toISOString(),
  });

  console.log("Creating collection...");
  const collectionTx = await imageRegistry.registerCollection(collectionName, collectionMetadata.ipfsUri);
  console.log("Collection tx:", collectionTx.hash);
  const collectionReceipt = await collectionTx.wait();
  const collectionId = parseEventArg(collectionReceipt, imageRegistry.interface, "CollectionRegistered", "collectionId");
  console.log("Collection created with ID:", collectionId.toString());

  state.collection = {
    id: collectionId.toString(),
    name: collectionName,
    metadataUri: collectionMetadata.ipfsUri,
    metadataGatewayUrl: collectionMetadata.gatewayUrl,
    metadataIpfsHash: collectionMetadata.ipfsHash,
    txHash: collectionTx.hash,
  };
  writeState(state);

  console.log("Uploading test image to Pinata proxy...");
  const imageAsset = await uploadImageToPinata(TEST_IMAGE_PATH);
  console.log("Uploading image metadata to Pinata proxy...");
  const imageMetadata = await uploadJsonToPinata(`amoy-demo-image-${timestamp}`, {
    name: path.basename(TEST_IMAGE_PATH),
    description: "Test image prepared by the Amoy setup script.",
    collectionId: collectionId.toString(),
    assetUri: imageAsset.ipfsUri,
    assetGatewayUrl: imageAsset.gatewayUrl,
    contentHash,
    creatorWallet: creator.address,
    uploadedAt: new Date().toISOString(),
  });

  console.log("Registering image...");
  const imageTx = await imageRegistry.registerImage(contentHash, imageMetadata.ipfsUri, collectionId);
  console.log("Image tx:", imageTx.hash);
  const imageReceipt = await imageTx.wait();
  const imageId = parseEventArg(imageReceipt, imageRegistry.interface, "ImageRegistered", "imageId");
  console.log("Image registered with ID:", imageId.toString());

  state.image = {
    id: imageId.toString(),
    filePath: TEST_IMAGE_PATH,
    metadataUri: imageMetadata.ipfsUri,
    metadataGatewayUrl: imageMetadata.gatewayUrl,
    metadataIpfsHash: imageMetadata.ipfsHash,
    assetUri: imageAsset.ipfsUri,
    assetGatewayUrl: imageAsset.gatewayUrl,
    assetIpfsHash: imageAsset.ipfsHash,
    contentHash,
    txHash: imageTx.hash,
  };
  writeState(state);

  console.log("Uploading license metadata to Pinata proxy...");
  const licenseTerms = await uploadJsonToPinata(`amoy-demo-license-${timestamp}`, {
    name: `Amoy Demo License ${timestamp}`,
    description: "License terms prepared by the Amoy setup script.",
    imageId: imageId.toString(),
    seller: creator.address,
    priceWei: priceWei.toString(),
    priceMatic: hre.ethers.formatEther(priceWei),
    active: true,
    createdAt: new Date().toISOString(),
  });

  console.log("Configuring license offer...");
  const licenseTx = await licensing.configureLicenseOffer(imageId, priceWei, licenseTerms.ipfsUri, true);
  console.log("License tx:", licenseTx.hash);
  await licenseTx.wait();

  state.licenseOffer = {
    seller: creator.address,
    priceWei: priceWei.toString(),
    priceMatic: hre.ethers.formatEther(priceWei),
    termsUri: licenseTerms.ipfsUri,
    termsGatewayUrl: licenseTerms.gatewayUrl,
    termsIpfsHash: licenseTerms.ipfsHash,
    txHash: licenseTx.hash,
    active: true,
  };
  writeState(state);

  console.log("Done. The buy script can now read this state file.");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});