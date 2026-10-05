const hre = require("hardhat");
const { verifyOnExplorer } = require("./verify-utils");

function getConfiguredAddress(envName) {
  const value = process.env[envName]?.trim();
  if (!value) {
    return "";
  }

  if (!hre.ethers.isAddress(value)) {
    throw new Error(`${envName} is set but is not a valid address: ${value}`);
  }

  return value;
}

function getOracleAddress(deployerAddress) {
  const configuredOracleAddress = getConfiguredAddress("ORACLE_ADDRESS");
  if (configuredOracleAddress) {
    return configuredOracleAddress;
  }

  const oraclePrivateKey = process.env.ORACLE_PRIVATE_KEY?.trim();
  if (oraclePrivateKey) {
    const normalizedPrivateKey = oraclePrivateKey.startsWith("0x") ? oraclePrivateKey : `0x${oraclePrivateKey}`;
    return new hre.ethers.Wallet(normalizedPrivateKey).address;
  }

  return deployerAddress;
}

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  const oracleAddress = getOracleAddress(deployer.address);

  const configuredImageRegistryAddress = getConfiguredAddress("IMAGE_REGISTRY_ADDRESS");
  const configuredLicensingAddress = getConfiguredAddress("LICENSING_AND_PAYMENT_ADDRESS");
  const configuredAuditAddress = getConfiguredAddress("MODEL_AND_INDEX_AUDIT_ADDRESS");

  let imageRegistryAddress = configuredImageRegistryAddress;
  let licensingAndPaymentAddress = configuredLicensingAddress;
  let modelAndIndexAuditAddress = configuredAuditAddress;

  if (imageRegistryAddress) {
    console.log("ImageRegistry already configured in .env:", imageRegistryAddress);
  } else {
    const ImageRegistry = await hre.ethers.getContractFactory("ImageRegistry");
    const imageRegistry = await ImageRegistry.deploy(deployer.address);
    await imageRegistry.waitForDeployment();
    imageRegistryAddress = await imageRegistry.getAddress();
    console.log("ImageRegistry deployed:", imageRegistryAddress);
  }

  if (licensingAndPaymentAddress) {
    console.log("LicensingAndPayment already configured in .env:", licensingAndPaymentAddress);
  } else {
    const LicensingAndPayment = await hre.ethers.getContractFactory("LicensingAndPayment");
    const licensingAndPayment = await LicensingAndPayment.deploy(
      imageRegistryAddress,
      deployer.address,
      oracleAddress
    );
    await licensingAndPayment.waitForDeployment();
    licensingAndPaymentAddress = await licensingAndPayment.getAddress();
    console.log("LicensingAndPayment deployed:", licensingAndPaymentAddress);
  }

  if (modelAndIndexAuditAddress) {
    console.log("ModelAndIndexAudit already configured in .env:", modelAndIndexAuditAddress);
  } else {
    const ModelAndIndexAudit = await hre.ethers.getContractFactory("ModelAndIndexAudit");
    const modelAndIndexAudit = await ModelAndIndexAudit.deploy(deployer.address);
    await modelAndIndexAudit.waitForDeployment();
    modelAndIndexAuditAddress = await modelAndIndexAudit.getAddress();
    console.log("ModelAndIndexAudit deployed:", modelAndIndexAuditAddress);
  }

  await verifyOnExplorer({
    address: imageRegistryAddress,
    constructorArgs: [deployer.address],
    label: "ImageRegistry",
    contract: "contracts/ImageRegistry.sol:ImageRegistry",
  });

  await verifyOnExplorer({
    address: licensingAndPaymentAddress,
    constructorArgs: [imageRegistryAddress, deployer.address, oracleAddress],
    label: "LicensingAndPayment",
    contract: "contracts/LicensingAndPayment.sol:LicensingAndPayment",
  });

  await verifyOnExplorer({
    address: modelAndIndexAuditAddress,
    constructorArgs: [deployer.address],
    label: "ModelAndIndexAudit",
    contract: "contracts/ModelAndIndexAudit.sol:ModelAndIndexAudit",
  });

  console.log("Final addresses:");
  console.log("ImageRegistry:", imageRegistryAddress);
  console.log("LicensingAndPayment:", licensingAndPaymentAddress);
  console.log("ModelAndIndexAudit:", modelAndIndexAuditAddress);
  console.log("Oracle:", oracleAddress);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});const hre = require("hardhat");
const { verifyOnExplorer } = require("./verify-utils");

function getConfiguredAddress(envName) {
  const value = process.env[envName]?.trim();
  if (!value) {
    return "";
  }

  if (!hre.ethers.isAddress(value)) {
    throw new Error(`${envName} is set but is not a valid address: ${value}`);
  }

  return value;
}

function getOracleAddress(deployerAddress) {
  const configuredOracleAddress = getConfiguredAddress("ORACLE_ADDRESS");
  if (configuredOracleAddress) {
    return configuredOracleAddress;
  }

  const oraclePrivateKey = process.env.ORACLE_PRIVATE_KEY?.trim();
  if (oraclePrivateKey) {
    const normalizedPrivateKey = oraclePrivateKey.startsWith("0x") ? oraclePrivateKey : `0x${oraclePrivateKey}`;
    return new hre.ethers.Wallet(normalizedPrivateKey).address;
  }

  return deployerAddress;
}

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  const oracleAddress = getOracleAddress(deployer.address);

  const configuredImageRegistryAddress = getConfiguredAddress("IMAGE_REGISTRY_ADDRESS");
  const configuredLicensingAddress = getConfiguredAddress("LICENSING_AND_PAYMENT_ADDRESS");
  const configuredAuditAddress = getConfiguredAddress("MODEL_AND_INDEX_AUDIT_ADDRESS");

  let imageRegistryAddress = configuredImageRegistryAddress;
  let licensingAndPaymentAddress = configuredLicensingAddress;
  let modelAndIndexAuditAddress = configuredAuditAddress;

  if (imageRegistryAddress) {
    console.log("ImageRegistry already configured in .env:", imageRegistryAddress);
  } else {
    const ImageRegistry = await hre.ethers.getContractFactory("ImageRegistry");
    const imageRegistry = await ImageRegistry.deploy(deployer.address);
    await imageRegistry.waitForDeployment();
    imageRegistryAddress = await imageRegistry.getAddress();
    console.log("ImageRegistry deployed:", imageRegistryAddress);
  }

  if (licensingAndPaymentAddress) {
    console.log("LicensingAndPayment already configured in .env:", licensingAndPaymentAddress);
  } else {
    const LicensingAndPayment = await hre.ethers.getContractFactory("LicensingAndPayment");
    const licensingAndPayment = await LicensingAndPayment.deploy(
      imageRegistryAddress,
      deployer.address,
      oracleAddress
    );
    await licensingAndPayment.waitForDeployment();
    licensingAndPaymentAddress = await licensingAndPayment.getAddress();
    console.log("LicensingAndPayment deployed:", licensingAndPaymentAddress);
  }

  if (modelAndIndexAuditAddress) {
    console.log("ModelAndIndexAudit already configured in .env:", modelAndIndexAuditAddress);
  } else {
    const ModelAndIndexAudit = await hre.ethers.getContractFactory("ModelAndIndexAudit");
    const modelAndIndexAudit = await ModelAndIndexAudit.deploy(deployer.address);
    await modelAndIndexAudit.waitForDeployment();
    modelAndIndexAuditAddress = await modelAndIndexAudit.getAddress();
    console.log("ModelAndIndexAudit deployed:", modelAndIndexAuditAddress);
  }

  await verifyOnExplorer({
    address: imageRegistryAddress,
    constructorArgs: [deployer.address],
    label: "ImageRegistry",
    contract: "contracts/ImageRegistry.sol:ImageRegistry",
  });

  await verifyOnExplorer({
    address: licensingAndPaymentAddress,
    constructorArgs: [imageRegistryAddress, deployer.address, oracleAddress],
    label: "LicensingAndPayment",
    contract: "contracts/LicensingAndPayment.sol:LicensingAndPayment",
  });

  await verifyOnExplorer({
    address: modelAndIndexAuditAddress,
    constructorArgs: [deployer.address],
    label: "ModelAndIndexAudit",
    contract: "contracts/ModelAndIndexAudit.sol:ModelAndIndexAudit",
  });

  console.log("Final addresses:");
  console.log("ImageRegistry:", imageRegistryAddress);
  console.log("LicensingAndPayment:", licensingAndPaymentAddress);
  console.log("ModelAndIndexAudit:", modelAndIndexAuditAddress);
  console.log("Oracle:", oracleAddress);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});