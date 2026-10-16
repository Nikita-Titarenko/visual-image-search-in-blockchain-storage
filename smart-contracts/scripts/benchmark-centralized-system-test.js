const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
const { ethers } = require("ethers");

const ROOT_DIR = path.resolve(__dirname, "..", "..");
const SMART_CONTRACTS_DIR = path.resolve(__dirname, "..");
const REPORTS_DIR = path.resolve(SMART_CONTRACTS_DIR, "reports");
const REPORT_PATH = path.join(REPORTS_DIR, "centralized-system-benchmark.json");
const BENCHMARK_RUNTIME_DIR = path.join(REPORTS_DIR, "centralized-benchmark-runtime");
const BENCHMARK_PID_FILE_PATH = path.join(BENCHMARK_RUNTIME_DIR, "service-pids.txt");
const BENCHMARK_VECTOR_LOG_PATH = path.join(BENCHMARK_RUNTIME_DIR, "image-vector-state", "image-vector-service.log");
const TEST_SERVICES_SCRIPT_PATH = path.join(ROOT_DIR, "start-centralized-test-services.sh");
const TEST_IMAGE_PATH = path.join(SMART_CONTRACTS_DIR, "scripts", "test-images", "test-image.jpg");
const HARDHAT_MNEMONIC = "test test test test test test test test test test test junk";
const ACCESS_BASE_URL = process.env.BENCHMARK_ACCESS_BASE_URL || "http://127.0.0.1:8000";
const VECTOR_BASE_URL = process.env.BENCHMARK_VECTOR_BASE_URL || "http://127.0.0.1:8010";
const PINATA_PROXY_BASE_URL = process.env.BENCHMARK_PINATA_PROXY_BASE_URL
  || `http://127.0.0.1:${process.env.PINATA_UPLOAD_PORT?.trim() || "3001"}`;
const CENTRALIZED_BASE_URL = process.env.BENCHMARK_CENTRALIZED_BASE_URL || "http://127.0.0.1:8020";
const LOAD_LEVELS = (process.env.BENCHMARK_LOAD_LEVELS || "10,50,100")
  .split(",")
  .map((value) => Number(value.trim()))
  .filter((value) => Number.isInteger(value) && value > 0);
const SEEDED_IMAGE_COUNT = Number(process.env.BENCHMARK_SEEDED_IMAGE_COUNT || "8");
const USER_FLOW_REQUEST_TIMEOUT_MS = 80000;
const LICENSE_PRICE_WEI = 1n;

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
      "start-centralized-test-services\\.sh",
      "smart-contracts[/\\]reports[/\\]centralized-benchmark-runtime",
      "smart-contracts-mock",
      "image-vector-service[/\\]main\\.py (production|development)",
      "pinata-mock[/\\]pinata_mock\\.py",
      "pinata-proxy[/\\]pinata_proxy\\.py",
      "uvicorn main:app --app-dir image-access-service",
      "uvicorn main:app --app-dir smart-contracts-mock",
      "ORACLE_USE_CENTRALIZED_BACKEND=true",
      "VECTOR_USE_CENTRALIZED_BACKEND=true",
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
      "start-centralized-test-services.sh",
      "smart-contracts/reports/centralized-benchmark-runtime",
      "smart-contracts-mock",
      "image-vector-service/main.py (production|development)",
      "pinata-mock/pinata_mock.py",
      "pinata-proxy/pinata_proxy.py",
      "uvicorn main:app --app-dir image-access-service",
      "uvicorn main:app --app-dir smart-contracts-mock",
      "ORACLE_USE_CENTRALIZED_BACKEND=true",
      "VECTOR_USE_CENTRALIZED_BACKEND=true",
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

async function isHttpHealthy(url, timeoutMs = 1000) {
  try {
    await waitForHttpHealth(url, timeoutMs);
    return true;
  } catch {
    return false;
  }
}

async function areTestServicesHealthy() {
  const [pinataHealthy, accessHealthy, vectorHealthy, mockHealthy] = await Promise.all([
    isHttpHealthy(`${PINATA_PROXY_BASE_URL}/api/pinata/health`),
    isHttpHealthy(`${ACCESS_BASE_URL}/api/oracle/health`),
    isHttpHealthy(`${VECTOR_BASE_URL}/api/vector/health`),
    isHttpHealthy(`${CENTRALIZED_BASE_URL}/api/mock/health`),
  ]);
  return pinataHealthy && accessHealthy && vectorHealthy && mockHealthy;
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

async function fetchWithTimeout(url, options = {}, timeoutMs = USER_FLOW_REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
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

async function postJson(url, payload, timeoutMs = USER_FLOW_REQUEST_TIMEOUT_MS) {
  const response = await fetchWithTimeout(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }, timeoutMs);
  if (!response.ok) {
    throw new Error(`${url} failed with status ${response.status}: ${await response.text()}`);
  }
  return await response.json();
}

async function getJson(url, timeoutMs = USER_FLOW_REQUEST_TIMEOUT_MS) {
  const response = await fetchWithTimeout(url, {}, timeoutMs);
  if (!response.ok) {
    throw new Error(`${url} failed with status ${response.status}: ${await response.text()}`);
  }
  return await response.json();
}

async function resetCentralizedState(timeoutMs = USER_FLOW_REQUEST_TIMEOUT_MS) {
  await postJson(`${CENTRALIZED_BASE_URL}/api/mock/admin/reset`, {}, timeoutMs);
}

async function postMultipart(url, fields, file, timeoutMs = USER_FLOW_REQUEST_TIMEOUT_MS) {
  const formData = new FormData();
  for (const [key, value] of Object.entries(fields || {})) {
    formData.append(key, String(value));
  }
  formData.append(file.name, new Blob([file.bytes], { type: file.contentType }), file.fileName);
  const response = await fetchWithTimeout(url, { method: "POST", body: formData }, timeoutMs);
  if (!response.ok) {
    throw new Error(`${url} failed with status ${response.status}: ${await response.text()}`);
  }
  return await response.json();
}

function summarizeLatencies(values) {
  if (!values.length) {
    return { count: 0, avgMs: 0, p95Ms: 0, maxMs: 0 };
  }
  const sorted = [...values].sort((left, right) => left - right);
  const avgMs = sorted.reduce((sum, value) => sum + value, 0) / sorted.length;
  return {
    count: sorted.length,
    avgMs: Number(avgMs.toFixed(2)),
    p95Ms: Number(sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))].toFixed(2)),
    maxMs: Number(sorted[sorted.length - 1].toFixed(2)),
  };
}

async function timed(name, collector, action) {
  const startedAt = performance.now();
  const result = await action();
  collector[name].push(Number((performance.now() - startedAt).toFixed(2)));
  return result;
}

async function maybeTimed(name, collector, action) {
  if (!collector) {
    return await action();
  }
  return await timed(name, collector, action);
}

function buildClaimMessage(purchaseId, buyerAddress, issuedAt) {
  return `Claim encrypted image access\nPurchase ID: ${purchaseId}\nBuyer: ${buyerAddress.toLowerCase()}\nIssued At: ${issuedAt}`;
}

function trackPinataHash(pinataHashes, payload) {
  if (payload?.ipfsHash) {
    pinataHashes.add(String(payload.ipfsHash));
  }
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
    await uploadJsonToPinata(`centralized-benchmark-image-${suffix}`, {
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

  return { encryptedUpload, previewUpload, metadataDocument };
}

async function createTermsDocument(suffix, pinataHashes, timeoutMs) {
  const termsDocument = await maybeTimed("pinata/pin-json(terms-metadata)", pinataHashes?.latencyCollector, async () => (
    await uploadJsonToPinata(`centralized-benchmark-terms-${suffix}`, {
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

async function waitForDatasetSize(minimumSize, timeoutMs = 15000) {
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

async function seedImagesAndLicenses({ sellerAddress, imageBytes, minimumDatasetSize, pinataHashes }) {
  const seeded = [];
  const sharedTerms = await createTermsDocument("seeded", pinataHashes);
  for (let index = 0; index < SEEDED_IMAGE_COUNT; index++) {
    const contentHash = ethers.keccak256(ethers.toUtf8Bytes(`seeded-image-${index}-${Date.now()}`));
    const metadata = await createMetadata(ACCESS_BASE_URL, imageBytes, sellerAddress, contentHash, `seeded-${index}`, pinataHashes);
    const image = await postJson(`${CENTRALIZED_BASE_URL}/api/mock/image-registry/images`, {
      collectionId: 0,
      currentOwner: sellerAddress,
      contentHash,
      metadataURI: metadata.metadataDocument.ipfsUri,
    });
    await postJson(`${CENTRALIZED_BASE_URL}/api/mock/licensing/offers`, {
      imageId: Number(image.id),
      seller: sellerAddress,
      priceWei: Number(LICENSE_PRICE_WEI),
      termsURI: sharedTerms.ipfsUri,
      active: true,
    });
    seeded.push({ imageId: Number(image.id) });
  }
  await waitForDatasetSize(minimumDatasetSize);
  return seeded;
}

async function runVirtualUserWorkflow(context) {
  const { imageBytes, seededImages, userIndex, latencyCollector, pinataHashes } = context;
  const wallet = ethers.HDNodeWallet.fromPhrase(HARDHAT_MNEMONIC, undefined, `m/44'/60'/0'/0/${userIndex + 50}`);
  const contentHash = ethers.keccak256(ethers.toUtf8Bytes(`centralized-user-image-${userIndex}-${Date.now()}`));
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
  const [image, terms] = await Promise.all([
    timed("registerImage", latencyCollector, async () => (
      await postJson(`${CENTRALIZED_BASE_URL}/api/mock/image-registry/images`, {
        collectionId: 0,
        currentOwner: wallet.address,
        contentHash,
        metadataURI: metadata.metadataDocument.ipfsUri,
      })
    )),
    createTermsDocument(`user-${userIndex}`, trackedPinataHashes, USER_FLOW_REQUEST_TIMEOUT_MS),
  ]);

  await timed("configureLicenseOffer", latencyCollector, async () => {
    await postJson(`${CENTRALIZED_BASE_URL}/api/mock/licensing/offers`, {
      imageId: Number(image.id),
      seller: wallet.address,
      priceWei: Number(LICENSE_PRICE_WEI),
      termsURI: terms.ipfsUri,
      active: true,
    });
  });

  const seededImage = seededImages[userIndex % seededImages.length];
  const purchase = await timed("buyLicense", latencyCollector, async () => (
    await postJson(`${CENTRALIZED_BASE_URL}/api/mock/licensing/purchases`, {
      imageId: seededImage.imageId,
      buyer: wallet.address,
      paidAmount: Number(LICENSE_PRICE_WEI),
    })
  ));

  await timed("oracle/download", latencyCollector, async () => {
    const issuedAt = new Date().toISOString();
    const message = buildClaimMessage(Number(purchase.id), wallet.address, issuedAt);
    const signedMessage = await wallet.signMessage(message);
    const response = await fetchWithTimeout(`${ACCESS_BASE_URL}/api/oracle/download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        purchaseId: Number(purchase.id),
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

async function runLoadLevel(loadLevel, sharedContext) {
  const { sellerAddress, imageBytes } = sharedContext;
  await resetCentralizedState();
  const pinataHashes = new Set();
  const seededImages = await seedImagesAndLicenses({
    sellerAddress,
    imageBytes,
    minimumDatasetSize: SEEDED_IMAGE_COUNT,
    pinataHashes,
  });
  const latencyCollector = buildLatencyCollector();
  const failures = [];
  const startedAt = performance.now();
  await Promise.allSettled(
    Array.from({ length: loadLevel }, (_, userIndex) =>
      runVirtualUserWorkflow({ imageBytes, seededImages, userIndex, latencyCollector, pinataHashes }).catch((error) => {
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
  await ensureTestServicesStarted({ forceRestart: true });
  await waitForHttpHealth(`${PINATA_PROXY_BASE_URL}/api/pinata/health`);
  await waitForHttpHealth(`${ACCESS_BASE_URL}/api/oracle/health`);
  await waitForHttpHealth(`${VECTOR_BASE_URL}/api/vector/health`, 180000);
  await waitForHttpHealth(`${CENTRALIZED_BASE_URL}/api/mock/health`);

  const imageBytes = fs.readFileSync(TEST_IMAGE_PATH);
  const sellerAddress = ethers.HDNodeWallet.fromPhrase(HARDHAT_MNEMONIC).address;
  const report = {
    generatedAt: new Date().toISOString(),
    mode: "centralized-backend",
    accessBaseUrl: ACCESS_BASE_URL,
    vectorBaseUrl: VECTOR_BASE_URL,
    pinataProxyBaseUrl: PINATA_PROXY_BASE_URL,
    centralizedBaseUrl: CENTRALIZED_BASE_URL,
    seededImageCount: SEEDED_IMAGE_COUNT,
    loadLevels: [],
  };

  for (const loadLevel of LOAD_LEVELS) {
    console.log(`\n=== Running centralized benchmark for ${loadLevel} virtual users ===`);
    const result = await runLoadLevel(loadLevel, { sellerAddress, imageBytes });
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
});