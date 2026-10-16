# Visual Image Search in Blockchain Storage

This project combines a Polygon-based smart contract layer with an Angular client for image ownership, licensing, and auditability.

The blockchain side is built with Hardhat and Solidity and includes three contracts:
- `ImageRegistry` for registering images, collections, authors, owners, and original file hashes.
- `LicensingAndPayment` for publishing license offers, processing purchases, and confirming download access through an oracle.
- `ModelAndIndexAudit` for storing version hashes of the search model and index so the retrieval pipeline can be audited.

The frontend lives in the `client` folder and provides a full wallet-driven flow: connect MetaMask, switch to Polygon Amoy, register collections and images, configure license offers, buy licenses, confirm access, and inspect audit snapshots.

The repository now also includes a separate FastAPI image access service in `image-access-service/` that encrypts original image files before they are pinned to IPFS, validates purchases on-chain, and issues short-lived download tokens for decrypted delivery.

The repository also includes a second FastAPI service in `image-vector-service/` that bootstraps the Caltech-101 dataset into Pinata on first run, builds CNN and color-histogram features, and returns the 10 nearest images for a query image while exposing model/index audit hashes for on-chain verification.

The repository also includes a Python dataset analysis module in `dataset_analysis/` for downloading Caltech-101 and generating exploratory plots.

## Project Structure

- `smart-contracts/contracts/` Solidity smart contracts.
- `smart-contracts/scripts/deploy.js` deployment script for all contracts.
- `smart-contracts/hardhat.config.js` Hardhat configuration for local, Polygon Amoy, and Polygon mainnet networks.
- `client/` Angular application with wallet and contract integration.
- `image-access-service/` FastAPI image access service for encrypted uploads and token-based download access.
- `image-vector-service/` FastAPI visual search service backed by Pinata, CNN embeddings, color histograms, and audit hashes.

## Install Dependencies

Install backend and smart contract dependencies:

```bash
npm --prefix smart-contracts install
```

Install Angular client dependencies:

```bash
npm --prefix client install
```

Install Python dependencies for dataset analysis:

```bash
pip install kagglehub matplotlib pandas pillow numpy
```

Install Python dependencies for the image access service:

```bash
pip install -r image-access-service/requirements.txt
```

Install Python dependencies for the Pinata proxy:

```bash
pip install -r pinata-proxy/requirements.txt
```

Install Python dependencies for the image vector service:

```bash
pip install -r image-vector-service/requirements.txt
```

Recommended Windows setup with separate virtual environments:

```bash
python -m venv image-access-service/.venv
image-access-service/.venv/Scripts/python.exe -m pip install -r image-access-service/requirements.txt
image-access-service/.venv/Scripts/python.exe -m pip install -r pinata-proxy/requirements.txt

python -m venv image-vector-service/.venv
image-vector-service/.venv/Scripts/python.exe -m pip install -r image-vector-service/requirements.txt
```

The current `image-vector-service` dependency set is intended for Python 3.14.

On Windows PowerShell, use `npm.cmd` and `npx.cmd` if `npm` or `npx` are blocked by execution policy.

## Compile Contracts

```bash
npm --prefix smart-contracts run compile
```

## Deploy Contracts

Deploy to Polygon Amoy testnet:

```bash
npm --prefix smart-contracts run deploy:amoy
```

Deploy to Polygon mainnet:

```bash
npm --prefix smart-contracts run deploy:polygon
```

Prepare a demo collection, image, and license offer on Polygon Amoy:

```bash
npm.cmd --prefix smart-contracts run amoy:create-license-setup
```

Buy the prepared license on Polygon Amoy:

```bash
npm.cmd --prefix smart-contracts run amoy:buy-license
```

Measure `registerCollection` confirmation time 5 times on the local Hardhat network and then 5 times on Polygon Amoy:

```bash
npm.cmd --prefix smart-contracts run measure:register-collection-confirmation
```

The script writes raw timings to `smart-contracts/reports/register-collection-confirmation.json`.

Build the histogram from the saved timing report:

```bash
python smart-contracts/scripts/plot_register_collection_confirmation_histogram.py
```

The histogram is written to `smart-contracts/reports/register-collection-confirmation-histogram.svg` using `matplotlib`.

Measure how `registerCollection` gas usage changes on the local Hardhat network as the number of already stored collections grows:

```bash
npm.cmd --prefix smart-contracts run measure:register-collection-gas-by-record-count
```

The script repeatedly calls `registerCollection` on one local `ImageRegistry` deployment and writes raw measurements to `smart-contracts/reports/register-collection-gas-by-record-count.json`.

Measurement script:

```bash
node smart-contracts/scripts/measure-register-collection-gas-by-record-count.js
```

Build the corresponding gas-vs-record-count chart:

```bash
python smart-contracts/scripts/plot_register_collection_gas_by_record_count.py
```

The chart is written to `smart-contracts/reports/register-collection-gas-by-record-count.svg` using `matplotlib`.

Start the dedicated benchmark services in a separate terminal. This launcher follows the regular service startup flow, but redirects service state and vector index artifacts into `smart-contracts/reports/local-benchmark-runtime/` so benchmark data does not mix with the default runtime files:

```bash
./start-test-services.sh
```

On Windows PowerShell, prefer the wrapper below instead of calling the `.sh` file directly, because `.sh` file associations on Windows can detach or close immediately:

```powershell
./start-test-services.ps1
```

Then run the local end-to-end benchmark. The benchmark script starts or reuses the local Hardhat node itself, deploys fresh local contracts right before the run, writes `smart-contracts/reports/local-benchmark-stack.json`, waits for the test services, uses the real Pinata-backed upload path, and then benchmarks register-image, configure-license, buy-license, decrypt-download, and top-10 search flows for 100, 1000, and 5000 virtual users:

```bash
npm.cmd --prefix smart-contracts run benchmark:local-system-test
```

The benchmark writes deployed local contract addresses to `smart-contracts/reports/local-benchmark-stack.json` and writes its report to `smart-contracts/reports/local-system-benchmark.json`.
After each load level completes, the benchmark unpins every Pinata object it uploaded during that load level through the Pinata proxy.

Build the benchmark bottleneck chart:

```bash
python smart-contracts/scripts/plot_local_system_benchmark.py
```

The chart is written to `smart-contracts/reports/local-system-benchmark.svg` using `matplotlib`.

Run the deployment script on the local Hardhat network:

```bash
npx --prefix smart-contracts hardhat run smart-contracts/scripts/deploy.js --config smart-contracts/hardhat.config.js
```

After deployment, either copy the deployed contract addresses into `client/src/app/contracts.config.ts` or paste them into the UI fields before you interact with the contracts.

The image vector service reads `MODEL_AND_INDEX_AUDIT_ADDRESS`, `POLYGON_AMOY_RPC_URL`, and `PINATA_JWT` so it can verify its local model/index hashes against the on-chain audit contract and mirror the dataset into Pinata.

## Run the Angular Client

Start the Pinata upload proxy first:

```bash
python pinata-proxy/pinata_proxy.py
```

To start the Pinata proxy, image access service, image vector service, and Angular web client together from the repository root, run:

```bash
.\start-services.sh
```

The script expects these interpreters to exist:

```bash
image-access-service/.venv/Scripts/python.exe
image-vector-service/.venv/Scripts/python.exe
```

Equivalent direct command:

```bash
python pinata-proxy/pinata_proxy.py
```

Start the FastAPI image access service:

```bash
uvicorn main:app --app-dir image-access-service --host 0.0.0.0 --port 8000
```

Start the image vector service:

```bash
uvicorn main:app --app-dir image-vector-service --host 0.0.0.0 --port 8010
```

Start the image vector service explicitly in production mode:

```bash
python image-vector-service/main.py production
```

Run the image vector service in development mode. In this mode it does not host FastAPI at all. It rebuilds the feature index when needed, runs a deterministic grouped train/validation/test split without data leakage, tunes the baseline histogram kNN, ResNet-18 embedding kNN, and RandomForestClassifier models, writes the evaluation logs plus JSON artifacts into `image-vector-service/state/`, and then exits:

```bash
python image-vector-service/main.py development
```

On first startup, the image vector service downloads the dataset via `dataset_analysis/download_dataset.py`, uploads every dataset image to Pinata, and then builds a local feature index from those Pinata-backed images.

Start the Angular development server:

```bash
npm --prefix client start
```

Create a production build of the client:

```bash
npm --prefix client run build
```

## Generate Dataset Plots

Run the Python dataset analysis script to generate the plots:

```bash
python dataset_analysis/main.py
```

This script downloads the Caltech-101 dataset through `kagglehub` and generates exploratory charts in the `plots/` folder.

## Run Tests

Run Hardhat tests with Solidity coverage:

```bash
npm --prefix smart-contracts run test:coverage
```

Run the Solidity static analysis:

```bash
npm --prefix smart-contracts run lint:solidity
```

Run the full pre-commit quality gate locally:

```bash
npm --prefix smart-contracts run check:commit
```

The smart-contracts package installs a tracked Git pre-commit hook through `prepare`. On each commit it runs Solidity static analysis, Hardhat tests, coverage, and then fails the commit if any coverage metric drops below 85%.

Generate a bar chart from the Hardhat gas report:

```bash
python smart-contracts/scripts/plot_gas_report.py
```

The script runs `npx.cmd hardhat test`, saves the full console output to `smart-contracts/reports/hardhat-gas-report.txt`, and writes an SVG chart to `smart-contracts/reports/gas-methods-chart.svg`.

Run Angular tests:

```bash
npm --prefix client test
```

Run the image access service tests and image vector service tests in parallel on Windows PowerShell:

```powershell
$access = Start-Process -FilePath "image-access-service/.venv/Scripts/python.exe" -ArgumentList "-m", "unittest", "discover", "-s", "image-access-service/tests", "-p", "test_*.py" -NoNewWindow -PassThru; $vector = Start-Process -FilePath "image-vector-service/.venv/Scripts/python.exe" -ArgumentList "-m", "unittest", "discover", "-s", "image-vector-service/tests", "-p", "test_*.py" -NoNewWindow -PassThru; $access.WaitForExit(); $vector.WaitForExit(); if ($access.ExitCode -ne 0 -or $vector.ExitCode -ne 0) { }
```

## Useful Commands

Clean Hardhat artifacts and cache:

```bash
npm --prefix smart-contracts run clean
```

Watch Angular rebuilds during development:

```bash
npm --prefix client run watch
```

Launch the image vector service after activating its Python environment:

```bash
uvicorn main:app --app-dir image-vector-service --host 0.0.0.0 --port 8010
```

## Typical Flow

1. Deploy the contracts to Polygon Amoy or Polygon mainnet.
2. Update the contract addresses used by the Angular client.
3. Start the Pinata upload proxy.
4. Start the Angular client.
5. Connect a wallet in the browser.
6. Register a collection and select an image file.
7. Let the UI encrypt the original file through the oracle, upload the encrypted blob to IPFS, and register the metadata URI on-chain.
8. Configure a license offer.
9. Buy a license from another wallet.
10. Request an access token from the oracle so it can validate the purchase on-chain and confirm access in the contract.
11. Record model and index audit snapshots.

## Image Vector Service API

- `POST /api/vector/search`: accepts an image file and returns the nearest dataset images from Pinata; use `method=cnn` for ResNet18 embeddings or `method=histogram` for the baseline color-histogram search.
