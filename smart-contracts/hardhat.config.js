const path = require("path");
const { task } = require("hardhat/config");

require("@nomicfoundation/hardhat-toolbox");
require("solidity-coverage");
require("dotenv").config({ path: path.resolve(__dirname, "..", ".env") });

task("test")
  .addFlag("coverage", "Run tests with solidity coverage")
  .setAction(async (taskArgs, hre, runSuper) => {
    if (taskArgs.coverage) {
      const coverageArgs = Array.isArray(taskArgs.testFiles) && taskArgs.testFiles.length > 0
        ? { testfiles: taskArgs.testFiles.join(",") }
        : {};
      return hre.run("coverage", coverageArgs);
    }

    return runSuper(taskArgs);
  });

const privateKey = process.env.DEPLOYER_PRIVATE_KEY;
const explorerApiKey = process.env.ETHERSCAN_API_KEY || process.env.POLYGONSCAN_API_KEY || "";

module.exports = {
  solidity: {
    version: "0.8.24",
    settings: {
      optimizer: {
        enabled: true,
        runs: 200
      }
    }
  },
  networks: {
    hardhat: {},
    amoy: {
      url: process.env.POLYGON_AMOY_RPC_URL || "https://rpc-amoy.polygon.technology",
      accounts: privateKey ? [privateKey] : []
    },
    polygon: {
      url: process.env.POLYGON_RPC_URL || "https://polygon-rpc.com",
      accounts: privateKey ? [privateKey] : []
    }
  },
  etherscan: {
    apiKey: explorerApiKey
  }
};