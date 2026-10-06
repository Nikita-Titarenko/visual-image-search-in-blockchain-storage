const hre = require("hardhat");

const MAX_VERIFY_ATTEMPTS = 4;
const VERIFY_RETRY_DELAY_MS = 15_000;

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function isAlreadyVerified(message) {
  return /already verified/i.test(message);
}

function isRetryableVerificationError(message) {
  return [
    /pending/i,
    /try again/i,
    /wait/i,
    /429/i,
    /5\d\d/i,
    /temporar/i,
    /unable to locate contractcode/i,
    /contract code.*not found/i,
    /unable to locate.*contract/i,
    /does not have bytecode/i,
  ].some((pattern) => pattern.test(message));
}

async function verifyOnExplorer({ address, constructorArgs, label, contract }) {
  if (["hardhat", "localhost"].includes(hre.network.name)) {
    console.log(`Skipping verification for ${label}: unsupported network ${hre.network.name}.`);
    return false;
  }

  const explorerApiKey = process.env.ETHERSCAN_API_KEY || process.env.POLYGONSCAN_API_KEY;
  if (!explorerApiKey) {
    console.log(`Skipping verification for ${label}: ETHERSCAN_API_KEY or POLYGONSCAN_API_KEY is not set.`);
    return false;
  }

  for (let attempt = 1; attempt <= MAX_VERIFY_ATTEMPTS; attempt += 1) {
    try {
      await hre.run("verify:verify", {
        address,
        constructorArguments: constructorArgs,
        contract,
      });

      console.log(`${label} verified: ${address}`);
      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);

      if (isAlreadyVerified(message)) {
        console.log(`${label} already verified: ${address}`);
        return true;
      }

      if (attempt < MAX_VERIFY_ATTEMPTS && isRetryableVerificationError(message)) {
        console.log(`Verification attempt ${attempt} for ${label} failed: ${message}`);
        console.log(`Retrying in ${VERIFY_RETRY_DELAY_MS / 1000} seconds...`);
        await delay(VERIFY_RETRY_DELAY_MS);
        continue;
      }

      throw new Error(`Failed to verify ${label} at ${address}: ${message}`);
    }
  }

  return false;
}

module.exports = {
  verifyOnExplorer,
};