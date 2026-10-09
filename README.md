# Visual Image Search in Blockchain Storage

This project combines a Polygon-based smart contract layer with an Angular client for image ownership, licensing, and auditability.

The blockchain side is built with Hardhat and Solidity and includes three contracts:
- `ImageRegistry` for registering images, collections, authors, owners, and original file hashes.
- `LicensingAndPayment` for publishing license offers, processing purchases, and confirming download access through an oracle.
- `ModelAndIndexAudit` for storing version hashes of the search model and index so the retrieval pipeline can be audited.

The frontend lives in the `client` folder and provides a full wallet-driven flow: connect MetaMask, switch to Polygon Amoy, register collections and images, configure license offers, buy licenses, confirm access, and inspect audit snapshots.

The repository now also includes a separate FastAPI oracle service in `oracle/` that encrypts original image files before they are pinned to IPFS, validates purchases on-chain, confirms access in `LicensingAndPayment`, and issues short-lived download tokens for decrypted delivery.

The repository also includes a second FastAPI service in `image-vector-service/` that bootstraps the Caltech-101 dataset into Pinata on first run, builds CNN and color-histogram features, and returns the 10 nearest images for a query image while exposing model/index audit hashes for on-chain verification.

The repository also includes a Python dataset analysis module in `dataset_analysis/` for downloading Caltech-101 and generating exploratory plots.

## Project Structure

- `smart-contracts/contracts/` Solidity smart contracts.
- `smart-contracts/scripts/deploy.js` deployment script for all contracts.
- `smart-contracts/hardhat.config.js` Hardhat configuration for local, Polygon Amoy, and Polygon mainnet networks.
- `client/` Angular application with wallet and contract integration.
- `oracle/` FastAPI oracle service for encrypted uploads and token-based download access.
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

Install Python dependencies for the FastAPI oracle:

```bash
pip install -r oracle/requirements.txt
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
python -m venv oracle/.venv
oracle/.venv/Scripts/python.exe -m pip install -r oracle/requirements.txt
oracle/.venv/Scripts/python.exe -m pip install -r pinata-proxy/requirements.txt

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

Run the deployment script on the local Hardhat network:

```bash
npx --prefix smart-contracts hardhat run smart-contracts/scripts/deploy.js --config smart-contracts/hardhat.config.js
```

After deployment, either copy the deployed contract addresses into `client/src/app/contracts.config.ts` or paste them into the UI fields before you interact with the contracts.

Set `ORACLE_ADDRESS` before deployment if the `LicensingAndPayment` contract should trust a dedicated oracle wallet instead of the deployer wallet.

The image vector service reads `MODEL_AND_INDEX_AUDIT_ADDRESS`, `POLYGON_AMOY_RPC_URL`, and `PINATA_JWT` so it can verify its local model/index hashes against the on-chain audit contract and mirror the dataset into Pinata.

## Run the Angular Client

Start the Pinata upload proxy first:

```bash
python pinata-proxy/pinata_proxy.py
```

To start the Pinata proxy, oracle, image vector service, and Angular web client together from the repository root, run:

```bash
.\start-services.sh
```

The script expects these interpreters to exist:

```bash
oracle/.venv/Scripts/python.exe
image-vector-service/.venv/Scripts/python.exe
```

Equivalent direct command:

```bash
python pinata-proxy/pinata_proxy.py
```

Start the FastAPI oracle service:

```bash
uvicorn oracle.main:app --host 0.0.0.0 --port 8000
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
- `GET /api/vector/audit-status`: returns the current model hash and index hash, and can optionally verify them against an on-chain `ModelAndIndexAudit` snapshot via `snapshot_id`.
- `POST /api/vector/rebuild-index`: rebuilds the local feature index from the Pinata-backed dataset mirror.
