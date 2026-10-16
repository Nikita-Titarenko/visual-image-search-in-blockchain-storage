const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
const { ethers, NonceManager } = require("ethers");

const ROOT_DIR = path.resolve(__dirname, "..", "..");
const SMART_CONTRACTS_DIR = path.resolve(__dirname, "..");
const REPORTS_DIR = path.resolve(SMART_CONTRACTS_DIR, "reports");
const REPORT_PATH = path.join(REPORTS_DIR, "local-system-benchmark.json");
const BENCHMARK_RUNTIME_DIR = path.join(REPORTS_DIR, "local-benchmark-runtime");
const BENCHMARK_PID_FILE_PATH = path.join(BENCHMARK_RUNTIME_DIR, "service-pids.txt");
const BENCHMARK_VECTOR_LOG_PATH = path.join(BENCHMARK_RUNTIME_DIR, "image-vector-state", "image-vector-service.log");
const STACK_PATH = path.resolve(process.env.BENCHMARK_STACK_PATH || path.join(REPORTS_DIR, "local-benchmark-stack.json"));
const TEST_SERVICES_SCRIPT_PATH = path.join(ROOT_DIR, "start-test-services.sh");
const TEST_IMAGE_PATH = path.join(SMART_CONTRACTS_DIR, "scripts", "test-images", "test-image.jpg");
const HARDHAT_MNEMONIC = "test test test test test test test test test test test junk";
const HARDHAT_HTTP_URL = process.env.BENCHMARK_RPC_URL || "http://127.0.0.1:8545";
const HARDHAT_WS_URL = process.env.BENCHMARK_WS_URL || "ws://127.0.0.1:8545";
const ACCESS_BASE_URL = process.env.BENCHMARK_ACCESS_BASE_URL || "http://127.0.0.1:8000";
const VECTOR_BASE_URL = process.env.BENCHMARK_VECTOR_BASE_URL || "http://127.0.0.1:8010";
const PINATA_PROXY_BASE_URL = process.env.BENCHMARK_PINATA_PROXY_BASE_URL
  || `http://127.0.0.1:${process.env.PINATA_UPLOAD_PORT?.trim() || "3001"}`;
const HARDHAT_CMD = path.join(
  SMART_CONTRACTS_DIR,
  "node_modules",
  ".bin",
  process.platform === "win32" ? "hardhat.cmd" : "hardhat"
);
const USE_SHELL_FOR_HARDHAT = process.platform === "win32";
const LOAD_LEVELS = (process.env.BENCHMARK_LOAD_LEVELS || "10,50,100")
  .split(",")
  .map((value) => Number(value.trim()))
  .filter((value) => Number.isInteger(value) && value > 0);
const SEEDED_IMAGE_COUNT = Number(process.env.BENCHMARK_SEEDED_IMAGE_COUNT || "8");
const USER_FLOW_REQUEST_TIMEOUT_MS = 80000;
const LICENSE_PRICE_WEI = 1n;

let managedHardhatChild = null;
let managedTestServicesChild = null;

function ensureReportsDir() {
  fs.mkdirSync(REPORTS_DIR, { recursive: true });
}

function writeReport(report) {
  ensureReportsDir();
  fs.writeFileSync(REPORT_PATH, `${JSON.stringify(report, null, 2)}\n`, "utf8");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchWithTimeout(url, options = {}, timeoutMs = USER_FLOW_REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal,
    });
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(`${url} timed out after ${timeoutMs}ms`);
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }
}

async function waitForHttpHealth(url, timeoutMs = 120000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    try {
      const response = await fetch(url);
      if (response.ok) {
        return;
      }
    } catch {
      // ignore until timeout
    }
    await sleep(1000);
  }

  throw new Error(`Timed out waiting for health endpoint: ${url}`);
}

async function isHttpHealthy(url, timeoutMs = 1000) {
  try {
    await waitForHttpHealth(url, timeoutMs);
    return true;
  } catch {
    return false;
  }
}

async function waitForRpcReady(provider, timeoutMs = 120000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    try {
      await provider.getBlockNumber();
      return;
    } catch {
      // ignore until timeout
    }
    await sleep(1000);
  }

  throw new Error(`Timed out waiting for JSON-RPC endpoint: ${HARDHAT_HTTP_URL}`);
}

async function isRpcReady(provider, timeoutMs = 1000) {
  try {
    await waitForRpcReady(provider, timeoutMs);
    return true;
  } catch {
    return false;
  }
}

function killManagedHardhat() {
  return terminateManagedChild(managedHardhatChild).finally(() => {
    managedHardhatChild = null;
  });
}

function killManagedTestServices() {
  return terminateManagedChild(managedTestServicesChild).finally(() => {
    managedTestServicesChild = null;
  });
}

async function terminateManagedChild(child) {
  if (!child || child.killed) {
    return;
  }

  if (process.platform === "win32") {
    await new Promise((resolve) => {
      const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
        stdio: "ignore",
        shell: false,
        windowsHide: false,
      });

      killer.on("error", () => resolve());
      killer.on("exit", () => resolve());
    });
    return;
  }

  await new Promise((resolve) => {
    child.once("exit", () => resolve());
    try {
      child.kill("SIGTERM");
    } catch {
      resolve();
    }
  });
}

async function runProcess(command, args, options = {}) {
  await new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: options.env,
      stdio: options.stdio || "inherit",
      shell: options.shell ?? false,
      windowsHide: false,
    });

    child.on("error", reject);
    child.on("exit", (code, signal) => {
      if (code === 0) {
        resolve();
        return;
      }

      reject(new Error(`${command} ${args.join(" ")} failed with code ${code ?? "null"} signal ${signal ?? "null"}`));
    });
  });
}

async function ensureLocalBenchmarkChain() {
  if (!fs.existsSync(HARDHAT_CMD)) {
    throw new Error(`Local Hardhat launcher not found at ${HARDHAT_CMD}. Run npm.cmd --prefix smart-contracts install first.`);
  }

  const provider = new ethers.JsonRpcProvider(HARDHAT_HTTP_URL);
  const rpcReady = await isRpcReady(provider);

  if (!rpcReady) {
    managedHardhatChild = spawn(HARDHAT_CMD, ["node", "--hostname", "127.0.0.1"], {
      cwd: SMART_CONTRACTS_DIR,
      env: process.env,
      stdio: "inherit",
      shell: USE_SHELL_FOR_HARDHAT,
      windowsHide: false,
    });
    managedHardhatChild.on("exit", () => {
      managedHardhatChild = null;
    });
    await waitForRpcReady(provider);
  }

  await runProcess(
    HARDHAT_CMD,
    ["run", "scripts/deploy-local-benchmark-stack.js", "--network", "localhost", "--config", path.join(SMART_CONTRACTS_DIR, "hardhat.config.js")],
    {
      cwd: SMART_CONTRACTS_DIR,
      env: {
        ...process.env,
        BENCHMARK_STACK_PATH: STACK_PATH,
        BENCHMARK_RPC_URL: HARDHAT_HTTP_URL,
        BENCHMARK_WS_URL: HARDHAT_WS_URL,
        BENCHMARK_ACCESS_BASE_URL: ACCESS_BASE_URL,
        BENCHMARK_VECTOR_BASE_URL: VECTOR_BASE_URL,
        BENCHMARK_PINATA_PROXY_BASE_URL: PINATA_PROXY_BASE_URL,
      },
      shell: USE_SHELL_FOR_HARDHAT,
    }
  );
}

function resolveBashCommand() {
  if (process.platform !== "win32") {
    return "bash";
  }

  const candidates = [
    process.env.GIT_BASH_PATH,
    "C:\\Program Files\\Git\\bin\\bash.exe",
    "C:\\Program Files\\Git\\usr\\bin\\bash.exe",
  ].filter(Boolean);

  const resolved = candidates.find((candidate) => fs.existsSync(candidate));
  return resolved || "bash";
}

async function runProcessAllowingNonZero(command, args, options = {}) {
  await new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd: options.cwd,
      env: options.env,
      stdio: options.stdio || "ignore",
      shell: options.shell ?? false,
      windowsHide: false,
    });

    child.on("error", () => resolve());
    child.on("exit", () => resolve());
  });
}

function readRecordedBenchmarkServicePids() {
  if (!fs.existsSync(BENCHMARK_PID_FILE_PATH)) {
    return [];
  }

  const raw = fs.readFileSync(BENCHMARK_PID_FILE_PATH, "utf8");
  return [...new Set(
    raw
      .split(/\r?\n/u)
      .map((value) => Number.parseInt(value.trim(), 10))
      .filter((value) => Number.isInteger(value) && value > 0)
  )];
}

async function terminatePid(pid) {
  if (!Number.isInteger(pid) || pid <= 0) {
    return;
  }

  if (process.platform === "win32") {
    await runProcessAllowingNonZero("taskkill", ["/PID", String(pid), "/T", "/F"], {
      stdio: "ignore",
      shell: false,
    });
    return;
  }

  await runProcessAllowingNonZero("kill", ["-TERM", String(pid)]);
}

async function stopRecordedBenchmarkServices() {
  const pids = readRecordedBenchmarkServicePids();
  for (const pid of pids) {
    await terminatePid(pid);
  }
}

async function stopExistingBenchmarkServices() {
  await stopRecordedBenchmarkServices();

  if (process.platform === "win32") {
    const benchmarkServicePattern = [
      "start-test-services\\.sh",
      "smart-contracts[/\\]reports[/\\]local-benchmark-runtime",
      "image-vector-service[/\\]main\\.py (production|development)",
      "pinata-mock[/\\]pinata_mock\\.py",
      "pinata-proxy[/\\]pinata_proxy\\.py",
      "uvicorn main:app --app-dir image-access-service",
      "PINATA_MOCK_PORT=3101",
      "PINATA_API_BASE_URL=http://127\\.0\\.0\\.1:3101",
      "VECTOR_SYNC_WITH_BLOCKCHAIN=false",
    ].join("|");

    await runProcessAllowingNonZero(
      "powershell.exe",
      [
        "-NoProfile",
        "-Command",
        "$pattern = $args[0]; Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match $pattern } | ForEach-Object { taskkill /PID $_.ProcessId /T /F | Out-Null }",
        benchmarkServicePattern,
      ],
      { shell: false }
    );
    return;
  }

  await runProcessAllowingNonZero("pkill", [
    "-f",
    [
      "start-test-services.sh",
      "smart-contracts/reports/local-benchmark-runtime",
      "image-vector-service/main.py (production|development)",
      "pinata-mock/pinata_mock.py",
      "pinata-proxy/pinata_proxy.py",
      "uvicorn main:app --app-dir image-access-service",
      "PINATA_MOCK_PORT=3101",
      "VECTOR_SYNC_WITH_BLOCKCHAIN=false",
    ].join("|"),
  ]);
}

async function waitForFileUnlock(filePath, timeoutMs = 5000) {
  if (!fs.existsSync(filePath)) {
    return;
  }

  const directory = path.dirname(filePath);
  const probePath = path.join(directory, `${path.basename(filePath)}.unlock-probe`);
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    if (!fs.existsSync(filePath)) {
      return;
    }

    try {
      fs.renameSync(filePath, probePath);
      fs.renameSync(probePath, filePath);
      return;
    } catch {
      try {
        if (fs.existsSync(probePath) && !fs.existsSync(filePath)) {
          fs.renameSync(probePath, filePath);
        }
      } catch {
        // ignore and retry until timeout
      }
      await sleep(250);
    }
  }
}

async function areTestServicesHealthy() {
  const [pinataHealthy, accessHealthy, vectorHealthy] = await Promise.all([
    isHttpHealthy(`${PINATA_PROXY_BASE_URL}/api/pinata/health`),
    isHttpHealthy(`${ACCESS_BASE_URL}/api/oracle/health`),
    isHttpHealthy(`${VECTOR_BASE_URL}/api/vector/health`),
  ]);
  return pinataHealthy && accessHealthy && vectorHealthy;
}

async function ensureTestServicesStarted({ forceRestart = false } = {}) {
  if (!fs.existsSync(TEST_SERVICES_SCRIPT_PATH)) {
    throw new Error(`Missing test services launcher: ${TEST_SERVICES_SCRIPT_PATH}`);
  }

  if (!forceRestart && await areTestServicesHealthy()) {
    return;
  }

  await killManagedTestServices();
  await stopExistingBenchmarkServices();
  await sleep(1000);

  const bashCommand = resolveBashCommand();
  managedTestServicesChild = spawn(bashCommand, [TEST_SERVICES_SCRIPT_PATH], {
    cwd: ROOT_DIR,
    env: process.env,
    stdio: "inherit",
    shell: false,
    windowsHide: false,
  });
  managedTestServicesChild.on("exit", () => {
    managedTestServicesChild = null;
  });
}

async function postMultipart(url, fields, fileField, timeoutMs) {
  const formData = new FormData();
  for (const [key, value] of Object.entries(fields || {})) {
    formData.append(key, value);
  }
  if (fileField) {
    formData.append(fileField.name, new Blob([fileField.bytes], { type: fileField.contentType }), fileField.fileName);
  }

  const response = timeoutMs
    ? await fetchWithTimeout(url, {
      method: "POST",
      body: formData,
    }, timeoutMs)
    : await fetch(url, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    throw new Error(`${url} failed with status ${response.status}: ${await response.text()}`);
  }
  return await response.json();
}

async function postJson(url, payload, timeoutMs) {
  const requestOptions = {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  };
  const response = timeoutMs
    ? await fetchWithTimeout(url, requestOptions, timeoutMs)
    : await fetch(url, requestOptions);
  if (!response.ok) {
    throw new Error(`${url} failed with status ${response.status}: ${await response.text()}`);
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return await response.json();
  }
  return await response.arrayBuffer();
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${url} failed with status ${response.status}: ${await response.text()}`);
  }
  return await response.json();
}

function buildClaimMessage(purchaseId, buyerAddress, issuedAt) {
  return [
    "Claim encrypted image access",
    `Purchase ID: ${purchaseId}`,
    `Buyer: ${buyerAddress.toLowerCase()}`,
    `Issued At: ${issuedAt}`,
  ].join("\n");
}

function percentile(values, ratio) {
  if (values.length === 0) {
    return 0;
  }
  const sorted = [...values].sort((left, right) => left - right);
  const index = Math.min(sorted.length - 1, Math.ceil(sorted.length * ratio) - 1);
  return sorted[index];
}

function summarizeLatencies(values) {
  if (values.length === 0) {
    return { count: 0, avgMs: 0, p95Ms: 0, minMs: 0, maxMs: 0 };
  }
  const total = values.reduce((sum, value) => sum + value, 0);
  return {
    count: values.length,
    avgMs: Number((total / values.length).toFixed(2)),
    p95Ms: percentile(values, 0.95),
    minMs: Math.min(...values),
    maxMs: Math.max(...values),
  };
}

async function timed(operationName, collector, callback) {
  const startedAt = performance.now();
  const result = await callback();
  const durationMs = Math.round(performance.now() - startedAt);
  collector[operationName].push(durationMs);
  return result;
}

async function maybeTimed(operationName, collector, callback) {
  if (!collector || !operationName) {
    return await callback();
  }
  return await timed(operationName, collector, callback);
}

function loadArtifact(contractName) {
  const artifactPath = path.join(
    SMART_CONTRACTS_DIR,
    "artifacts",
    "contracts",
    `${contractName}.sol`,
    `${contractName}.json`
  );
  return JSON.parse(fs.readFileSync(artifactPath, "utf8"));
}

function loadStackConfig() {
  if (!fs.existsSync(STACK_PATH)) {
    throw new Error(`Missing local benchmark stack file: ${STACK_PATH}.`);
  }

  const payload = JSON.parse(fs.readFileSync(STACK_PATH, "utf8"));
  const requiredAddresses = [
    ["imageRegistryAddress", payload.imageRegistryAddress],
    ["licensingAndPaymentAddress", payload.licensingAndPaymentAddress],
    ["modelAndIndexAuditAddress", payload.modelAndIndexAuditAddress],
  ];
  for (const [label, value] of requiredAddresses) {
    if (!ethers.isAddress(value)) {
      throw new Error(`Invalid ${label} in ${STACK_PATH}: ${value}`);
    }
  }
  return payload;
}

async function ensureCodeAtAddress(provider, address, label) {
  const bytecode = await provider.getCode(address);
  if (!bytecode || bytecode === "0x") {
    throw new Error(`No contract code found for ${label} at ${address}. Restart the local benchmark stack.`);
  }
}

function connectContracts(provider, stackConfig) {
  const deployerWallet = ethers.HDNodeWallet.fromPhrase(HARDHAT_MNEMONIC).connect(provider);
  const deployer = new NonceManager(deployerWallet);
  const registryArtifact = loadArtifact("ImageRegistry");
  const licensingArtifact = loadArtifact("LicensingAndPayment");

  const registry = new ethers.Contract(stackConfig.imageRegistryAddress, registryArtifact.abi, provider);
  const licensing = new ethers.Contract(stackConfig.licensingAndPaymentAddress, licensingArtifact.abi, provider);

  return {
    deployer,
    deployerAddress: deployerWallet.address,
    registry,
    licensing,
  };
}

async function setBalance(provider, address, etherAmount) {
  const hexBalance = ethers.toBeHex(ethers.parseEther(etherAmount));
  await provider.send("hardhat_setBalance", [address, hexBalance]);
}

function parseEventArg(receipt, contractInterface, eventName, argName) {
  for (const log of receipt.logs) {
    try {
      const parsed = contractInterface.parseLog(log);
      if (parsed?.name === eventName) {
        return parsed.args[argName];
      }
    } catch {
      // ignore unrelated logs
    }
  }

  throw new Error(`Unable to parse ${eventName}.${argName} from transaction logs.`);
}

async function uploadFileToPinata(fileName, bytes, contentType, timeoutMs) {
  return await postMultipart(
    `${PINATA_PROXY_BASE_URL}/api/pinata/upload`,
    {},
    { name: "file", fileName, bytes, contentType },
    timeoutMs
  );
}

async function uploadJsonToPinata(name, content, timeoutMs) {
  return await postJson(`${PINATA_PROXY_BASE_URL}/api/pinata/pin-json`, { name, content }, timeoutMs);
}

function trackPinataHash(pinataHashes, payload) {
  if (payload?.ipfsHash) {
    pinataHashes.add(String(payload.ipfsHash));
  }
}

async function createMetadata(accessBaseUrl, imageBytes, ownerAddress, contentHash, suffix, pinataHashes, timeoutMs) {
  const [encryptedUpload, previewUpload] = await Promise.all([
    maybeTimed("oracle/encrypt-upload", pinataHashes?.latencyCollector, async () => (
      await postMultipart(
        `${accessBaseUrl}/api/oracle/encrypt-upload`,
        { contentHash },
        { name: "file", fileName: `asset-${suffix}.jpg`, bytes: imageBytes, contentType: "image/jpeg" },
        timeoutMs
      )
    )),
    maybeTimed("pinata/upload", pinataHashes?.latencyCollector, async () => (
      await uploadFileToPinata(`preview-${suffix}.jpg`, imageBytes, "image/jpeg", timeoutMs)
    )),
  ]);
  trackPinataHash(pinataHashes, encryptedUpload);
  trackPinataHash(pinataHashes, previewUpload);

  const metadataDocument = await maybeTimed("pinata/pin-json(image-metadata)", pinataHashes?.latencyCollector, async () => (
    await uploadJsonToPinata(`benchmark-image-${suffix}`, {
      name: `Image ${suffix}`,
      creatorWallet: ownerAddress,
      collectionId: "0",
      previewUri: previewUpload.ipfsUri,
      previewGatewayUrl: previewUpload.gatewayUrl,
      assetUri: encryptedUpload.ipfsUri,
      assetGatewayUrl: encryptedUpload.gatewayUrl,
      encryptedGatewayUrl: encryptedUpload.gatewayUrl,
      contentHash,
      createdAt: new Date().toISOString(),
    }, timeoutMs)
  ));
  trackPinataHash(pinataHashes, metadataDocument);

  return {
    encryptedUpload,
    previewUpload,
    metadataDocument,
  };
}

async function createTermsDocument(suffix, pinataHashes, timeoutMs) {
  const termsDocument = await maybeTimed("pinata/pin-json(terms-metadata)", pinataHashes?.latencyCollector, async () => (
    await uploadJsonToPinata(`benchmark-terms-${suffix}`, {
      type: "license-terms",
      scope: "benchmark",
      active: true,
      createdAt: new Date().toISOString(),
    }, timeoutMs)
  ));
  trackPinataHash(pinataHashes, termsDocument);
  return termsDocument;
}

async function getVectorDatasetSize() {
  const payload = await getJson(`${VECTOR_BASE_URL}/api/vector/health`);
  return Number(payload.datasetSize || 0);
}

async function waitForDatasetSize(minimumSize, timeoutMs = 10000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    const datasetSize = await getVectorDatasetSize();
    if (datasetSize >= minimumSize) {
      return datasetSize;
    }
    await sleep(1000);
  }

  throw new Error(`Timed out waiting for vector dataset size to reach ${minimumSize}.`);
}

async function seedImagesAndLicenses({ registry, licensing, seller, sellerAddress, imageBytes, minimumDatasetSize, pinataHashes }) {
  const seeded = [];
  const sharedTerms = await createTermsDocument("seeded", pinataHashes);

  for (let index = 0; index < SEEDED_IMAGE_COUNT; index++) {
    const contentHash = ethers.keccak256(ethers.toUtf8Bytes(`seeded-image-${index}-${Date.now()}`));
    const metadata = await createMetadata(ACCESS_BASE_URL, imageBytes, sellerAddress, contentHash, `seeded-${index}`, pinataHashes);
    const registerTx = await registry.connect(seller).registerImage(contentHash, metadata.metadataDocument.ipfsUri, 0n);
    const registerReceipt = await registerTx.wait();
    const imageId = parseEventArg(registerReceipt, registry.interface, "ImageRegistered", "imageId");

    const licenseTx = await licensing.connect(seller).configureLicenseOffer(imageId, LICENSE_PRICE_WEI, sharedTerms.ipfsUri, true);
    await licenseTx.wait();
    seeded.push({ imageId });
  }

  await waitForDatasetSize(minimumDatasetSize);
  return seeded;
}

async function runVirtualUserWorkflow(context) {
  const {
    provider,
    registry,
    licensing,
    imageBytes,
    seededImages,
    userIndex,
    latencyCollector,
    pinataHashes,
  } = context;

  const wallet = ethers.HDNodeWallet.fromPhrase(
    HARDHAT_MNEMONIC,
    undefined,
    `m/44'/60'/0'/0/${userIndex + 50}`
  ).connect(provider);
  const managedWallet = new NonceManager(wallet);
  await setBalance(provider, wallet.address, "1000");

  const contentHash = ethers.keccak256(ethers.toUtf8Bytes(`user-image-${userIndex}-${Date.now()}`));
  const trackedPinataHashes = Object.assign(pinataHashes, { latencyCollector });
  const metadata = await createMetadata(
    ACCESS_BASE_URL,
    imageBytes,
    wallet.address,
    contentHash,
    `user-${userIndex}`,
    trackedPinataHashes,
    USER_FLOW_REQUEST_TIMEOUT_MS
  );

  const [imageId, terms] = await Promise.all([
    timed("registerImage", latencyCollector, async () => {
      const tx = await registry.connect(managedWallet).registerImage(contentHash, metadata.metadataDocument.ipfsUri, 0n);
      const receipt = await tx.wait();
      return parseEventArg(receipt, registry.interface, "ImageRegistered", "imageId");
    }),
    createTermsDocument(`user-${userIndex}`, trackedPinataHashes, USER_FLOW_REQUEST_TIMEOUT_MS),
  ]);

  await timed("configureLicenseOffer", latencyCollector, async () => {
    const tx = await licensing.connect(managedWallet).configureLicenseOffer(imageId, LICENSE_PRICE_WEI, terms.ipfsUri, true);
    await tx.wait();
  });

  const seededImage = seededImages[userIndex % seededImages.length];
  const purchaseId = await timed("buyLicense", latencyCollector, async () => {
    const tx = await licensing.connect(managedWallet).buyLicense(seededImage.imageId, { value: LICENSE_PRICE_WEI });
    const receipt = await tx.wait();
    return parseEventArg(receipt, licensing.interface, "LicensePurchased", "purchaseId");
  });

  await timed("oracle/download", latencyCollector, async () => {
    const issuedAt = new Date().toISOString();
    const message = buildClaimMessage(Number(purchaseId), wallet.address, issuedAt);
    const signedMessage = await wallet.signMessage(message);
    const response = await fetchWithTimeout(`${ACCESS_BASE_URL}/api/oracle/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        purchaseId: Number(purchaseId),
        buyerAddress: wallet.address,
        signedMessage,
        issuedAt,
      }),
    }, USER_FLOW_REQUEST_TIMEOUT_MS);
    if (!response.ok) {
      throw new Error(`download failed with status ${response.status}: ${await response.text()}`);
    }
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.length === 0) {
      throw new Error("download returned an empty payload");
    }
  });

  await timed("vector/search?top_k=10", latencyCollector, async () => {
    const formData = new FormData();
    formData.append("file", new Blob([imageBytes], { type: "image/jpeg" }), `query-${userIndex}.jpg`);
    const response = await fetchWithTimeout(`${VECTOR_BASE_URL}/api/vector/search?top_k=10`, {
      method: "POST",
      body: formData,
    }, USER_FLOW_REQUEST_TIMEOUT_MS);
    if (!response.ok) {
      throw new Error(`search failed with status ${response.status}: ${await response.text()}`);
    }
    const payload = await response.json();
    if (!Array.isArray(payload.results) || payload.results.length === 0) {
      throw new Error("search returned no results");
    }
  });
}

function buildLatencyCollector() {
  return {
    "oracle/encrypt-upload": [],
    "pinata/upload": [],
    "pinata/pin-json(image-metadata)": [],
    registerImage: [],
    "pinata/pin-json(terms-metadata)": [],
    configureLicenseOffer: [],
    buyLicense: [],
    "oracle/download": [],
    "vector/search?top_k=10": [],
  };
}

function summarizeLoad(loadLevel, latencyCollector, durationMs, failures) {
  const operations = Object.fromEntries(
    Object.entries(latencyCollector).map(([name, values]) => [name, summarizeLatencies(values)])
  );
  const completedUsers = latencyCollector["vector/search?top_k=10"].length;
  const bottleneck = Object.entries(operations)
    .sort((left, right) => right[1].avgMs - left[1].avgMs)[0]?.[0] || "unknown";

  return {
    users: loadLevel,
    durationMs,
    completedUsers,
    failedUsers: failures.length,
    throughputUsersPerSecond: Number((completedUsers / (durationMs / 1000)).toFixed(2)),
    bottleneckOperation: bottleneck,
    operations,
    failures,
  };
}

async function runLoadLevel(loadLevel, sharedContext) {
  const { provider, contracts, imageBytes } = sharedContext;
  const baselineDatasetSize = await getVectorDatasetSize();
  const pinataHashes = new Set();

  const seededImages = await seedImagesAndLicenses({
    registry: contracts.registry,
    licensing: contracts.licensing,
    seller: contracts.deployer,
    sellerAddress: contracts.deployerAddress,
    imageBytes,
    minimumDatasetSize: baselineDatasetSize + SEEDED_IMAGE_COUNT,
    pinataHashes,
  });

  const latencyCollector = buildLatencyCollector();
  const failures = [];
  const startedAt = performance.now();
  await Promise.allSettled(
    Array.from({ length: loadLevel }, (_, userIndex) =>
      runVirtualUserWorkflow({
        provider,
        registry: contracts.registry,
        licensing: contracts.licensing,
        imageBytes,
        seededImages,
        userIndex,
        latencyCollector,
        pinataHashes,
      }).catch((error) => {
        failures.push({ userIndex, message: error instanceof Error ? error.message : String(error) });
      })
    )
  );
  const durationMs = Math.round(performance.now() - startedAt);
  return summarizeLoad(loadLevel, latencyCollector, durationMs, failures);
}

async function main() {
  if (!fs.existsSync(TEST_IMAGE_PATH)) {
    throw new Error(`Missing benchmark image: ${TEST_IMAGE_PATH}`);
  }

  await ensureLocalBenchmarkChain();
  await ensureTestServicesStarted({ forceRestart: true });
  const stackConfig = loadStackConfig();
  const provider = new ethers.JsonRpcProvider(HARDHAT_HTTP_URL);
  await waitForRpcReady(provider);
  await waitForHttpHealth(`${PINATA_PROXY_BASE_URL}/api/pinata/health`);
  await waitForHttpHealth(`${ACCESS_BASE_URL}/api/oracle/health`);
  await waitForHttpHealth(`${VECTOR_BASE_URL}/api/vector/health`, 180000);
  await ensureCodeAtAddress(provider, stackConfig.imageRegistryAddress, "ImageRegistry");
  await ensureCodeAtAddress(provider, stackConfig.licensingAndPaymentAddress, "LicensingAndPayment");
  await ensureCodeAtAddress(provider, stackConfig.modelAndIndexAuditAddress, "ModelAndIndexAudit");

  const contracts = connectContracts(provider, stackConfig);
  const imageBytes = fs.readFileSync(TEST_IMAGE_PATH);
  const report = {
    generatedAt: new Date().toISOString(),
    mode: "local-hardhat",
    accessBaseUrl: ACCESS_BASE_URL,
    vectorBaseUrl: VECTOR_BASE_URL,
    pinataProxyBaseUrl: PINATA_PROXY_BASE_URL,
    hardhatRpcUrl: HARDHAT_HTTP_URL,
    stackPath: STACK_PATH,
    seededImageCount: SEEDED_IMAGE_COUNT,
    loadLevels: [],
  };

  for (const loadLevel of LOAD_LEVELS) {
    console.log(`\n=== Running local benchmark for ${loadLevel} virtual users ===`);
    const result = await runLoadLevel(loadLevel, { provider, contracts, imageBytes });
    report.loadLevels.push(result);
    writeReport(report);
  }

  writeReport(report);
  console.log(`Saved benchmark report to: ${REPORT_PATH}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
}).finally(async () => {
  await killManagedTestServices();
  await stopExistingBenchmarkServices();
  await waitForFileUnlock(BENCHMARK_VECTOR_LOG_PATH);
  await killManagedHardhat();
});