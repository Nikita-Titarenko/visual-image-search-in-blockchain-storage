#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
VECTOR_MODE="${1:-production}"

if [[ "$VECTOR_MODE" != "production" && "$VECTOR_MODE" != "development" ]]; then
  echo "Usage: ./start-test-services.sh [production|development]"
  exit 1
fi

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

IMAGE_ACCESS_PYTHON_BIN="$ROOT_DIR/image-access-service/.venv/Scripts/python.exe"
VECTOR_PYTHON_BIN="$ROOT_DIR/image-vector-service/.venv/Scripts/python.exe"
PINATA_MOCK_PYTHON_BIN="$IMAGE_ACCESS_PYTHON_BIN"
RUNTIME_DIR="$ROOT_DIR/smart-contracts/reports/local-benchmark-runtime"
STACK_PATH="$ROOT_DIR/smart-contracts/reports/local-benchmark-stack.json"
PID_FILE="$RUNTIME_DIR/service-pids.txt"
ACCESS_STATE_PATH="$RUNTIME_DIR/image-access-state.json"
VECTOR_STATE_DIR="$RUNTIME_DIR/image-vector-state"
PINATA_MOCK_STATE_DIR="$RUNTIME_DIR/pinata-mock-state"
VECTOR_INDEX_PATH="$VECTOR_STATE_DIR/feature_index.npz"
VECTOR_DEV_INDEX_PATH="$VECTOR_STATE_DIR/development_feature_index.npz"
VECTOR_MANIFEST_PATH="$VECTOR_STATE_DIR/dataset_manifest.json"
VECTOR_AUDIT_METADATA_PATH="$VECTOR_STATE_DIR/audit_metadata.json"
VECTOR_LOG_PATH="$VECTOR_STATE_DIR/image-vector-service.log"
VECTOR_DEV_EVALUATION_PATH="$VECTOR_STATE_DIR/development_evaluation.json"
VECTOR_DEV_PLOTS_DIR="$VECTOR_STATE_DIR/development_plots"
VECTOR_FINETUNED_MODEL_PATH="$VECTOR_STATE_DIR/fine_tuned_resnet18_backbone.pt"

if [[ ! -x "$IMAGE_ACCESS_PYTHON_BIN" ]]; then
  echo "Image access service Python interpreter not found at $IMAGE_ACCESS_PYTHON_BIN"
  echo "Create image-access-service/.venv and install image-access-service and pinata-proxy dependencies first."
  exit 1
fi

if [[ ! -x "$VECTOR_PYTHON_BIN" ]]; then
  echo "Image vector service Python interpreter not found at $VECTOR_PYTHON_BIN"
  echo "Create image-vector-service/.venv and install its dependencies first."
  exit 1
fi

rm -rf "$RUNTIME_DIR"
mkdir -p "$VECTOR_STATE_DIR" "$PINATA_MOCK_STATE_DIR"
: > "$PID_FILE"

declare -a PIDS=()

cleanup() {
  local exit_code=$?

  if [[ ${#PIDS[@]} -gt 0 ]]; then
    echo
    echo "Stopping local benchmark stack..."
    for pid in "${PIDS[@]}"; do
      kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
  fi

  exit "$exit_code"
}

trap cleanup EXIT INT TERM

resolve_windows_pid() {
  local posix_pid="$1"
  local winpid_path="/proc/$posix_pid/winpid"

  if [[ -f "$winpid_path" ]]; then
    tr -d '[:space:]' < "$winpid_path"
    return
  fi

  printf '%s\n' "$posix_pid"
}

start_service() {
  local name="$1"
  shift

  echo "Starting $name..."
  "$@" &
  local pid=$!
  local windows_pid
  windows_pid="$(resolve_windows_pid "$pid")"
  PIDS+=("$pid")
  printf '%s\n' "$windows_pid" >> "$PID_FILE"
  echo "$name started with PID $pid (Windows PID $windows_pid)"
}

wait_for_file() {
  local file_path="$1"
  local label="$2"
  local timeout_seconds="${3:-180}"

  echo "Waiting for $label at $file_path..."
  node -e 'const fs = require("fs"); const filePath = process.argv[1]; const timeoutMs = Number(process.argv[2]) * 1000; const startedAt = Date.now(); (async () => { while (Date.now() - startedAt < timeoutMs) { if (fs.existsSync(filePath)) { process.exit(0); } await new Promise((resolve) => setTimeout(resolve, 1000)); } console.error(`Timed out waiting for ${filePath}`); process.exit(1); })();' "$file_path" "$timeout_seconds"
}

PINATA_MOCK_PORT="${PINATA_MOCK_PORT:-3101}"
PINATA_MOCK_BASE_URL="http://127.0.0.1:$PINATA_MOCK_PORT"
PINATA_API_BASE_URL="$PINATA_MOCK_BASE_URL"
PINATA_GATEWAY_BASE_URL="$PINATA_MOCK_BASE_URL/ipfs"

wait_for_file "$STACK_PATH" "local benchmark stack file" 180

eval "$($IMAGE_ACCESS_PYTHON_BIN - <<'PY' "$STACK_PATH"
import json
import shlex
import sys

with open(sys.argv[1], 'r', encoding='utf-8') as handle:
    payload = json.load(handle)

for key, value in {
    'LOCAL_RPC_URL': payload['hardhatRpcUrl'],
    'LOCAL_WS_URL': payload['hardhatWsUrl'],
    'ACCESS_BASE_URL': payload['accessBaseUrl'],
    'VECTOR_BASE_URL': payload['vectorBaseUrl'],
    'PINATA_PROXY_BASE_URL': payload['pinataProxyBaseUrl'],
    'IMAGE_REGISTRY_ADDRESS': payload['imageRegistryAddress'],
    'LICENSING_AND_PAYMENT_ADDRESS': payload['licensingAndPaymentAddress'],
    'MODEL_AND_INDEX_AUDIT_ADDRESS': payload['modelAndIndexAuditAddress'],
}.items():
    print(f"{key}={shlex.quote(str(value))}")
PY
)"

start_service "Pinata mock" env \
  PINATA_MOCK_PORT="$PINATA_MOCK_PORT" \
  PINATA_MOCK_STATE_DIR="$PINATA_MOCK_STATE_DIR" \
  "$PINATA_MOCK_PYTHON_BIN" pinata-mock/pinata_mock.py

start_service "Pinata proxy" env \
  PINATA_API_BASE_URL="$PINATA_API_BASE_URL" \
  PINATA_GATEWAY_BASE_URL="$PINATA_GATEWAY_BASE_URL" \
  "$IMAGE_ACCESS_PYTHON_BIN" pinata-proxy/pinata_proxy.py

start_service "Image access service" env \
  ORACLE_STORE_PATH="$ACCESS_STATE_PATH" \
  ORACLE_ALLOWED_ORIGINS="*" \
  ORACLE_ACCESS_TOKEN_TTL_MINUTES="${ORACLE_ACCESS_TOKEN_TTL_MINUTES:-30}" \
  ORACLE_SIGNATURE_TTL_MINUTES="${ORACLE_SIGNATURE_TTL_MINUTES:-30}" \
  PINATA_API_BASE_URL="$PINATA_API_BASE_URL" \
  PINATA_GATEWAY_BASE_URL="$PINATA_GATEWAY_BASE_URL" \
  POLYGON_AMOY_RPC_URL="$LOCAL_RPC_URL" \
  IMAGE_REGISTRY_ADDRESS="$IMAGE_REGISTRY_ADDRESS" \
  LICENSING_AND_PAYMENT_ADDRESS="$LICENSING_AND_PAYMENT_ADDRESS" \
  PINATA_JWT="${PINATA_JWT:-}" \
  "$IMAGE_ACCESS_PYTHON_BIN" -m uvicorn main:app --app-dir image-access-service --host 127.0.0.1 --port 8000

start_service "Image vector service" env \
  VECTOR_STATE_DIR="$VECTOR_STATE_DIR" \
  VECTOR_INDEX_PATH="$VECTOR_INDEX_PATH" \
  VECTOR_DEV_INDEX_PATH="$VECTOR_DEV_INDEX_PATH" \
  VECTOR_MANIFEST_PATH="$VECTOR_MANIFEST_PATH" \
  VECTOR_AUDIT_METADATA_PATH="$VECTOR_AUDIT_METADATA_PATH" \
  VECTOR_LOG_PATH="$VECTOR_LOG_PATH" \
  VECTOR_DEV_EVALUATION_PATH="$VECTOR_DEV_EVALUATION_PATH" \
  VECTOR_DEV_PLOTS_DIR="$VECTOR_DEV_PLOTS_DIR" \
  VECTOR_FINETUNED_MODEL_PATH="$VECTOR_FINETUNED_MODEL_PATH" \
  VECTOR_ALLOWED_ORIGINS="*" \
  VECTOR_PUBLIC_BASE_URL="$VECTOR_BASE_URL" \
  VECTOR_TOP_K_DEFAULT="10" \
  VECTOR_TOP_K_MAX="10" \
  VECTOR_BOOTSTRAP_LIMIT="${VECTOR_BOOTSTRAP_LIMIT:-0}" \
  AUDIT_SNAPSHOT_IMAGE_INTERVAL="10000" \
  POLYGON_AMOY_RPC_URL="$LOCAL_RPC_URL" \
  POLYGON_AMOY_WS_URL="$LOCAL_WS_URL" \
  IMAGE_REGISTRY_ADDRESS="$IMAGE_REGISTRY_ADDRESS" \
  MODEL_AND_INDEX_AUDIT_ADDRESS="$MODEL_AND_INDEX_AUDIT_ADDRESS" \
  AUDIT_PRIVATE_KEY="${AUDIT_PRIVATE_KEY:-${DEPLOYER_PRIVATE_KEY:-}}" \
  PINATA_API_BASE_URL="$PINATA_API_BASE_URL" \
  PINATA_GATEWAY_BASE_URL="$PINATA_GATEWAY_BASE_URL" \
  VECTOR_MODEL_VERSION="${VECTOR_MODEL_VERSION:-benchmark-model}" \
  VECTOR_INDEX_VERSION="${VECTOR_INDEX_VERSION:-benchmark-index}" \
  VECTOR_TEST_DATASET_ID="${VECTOR_TEST_DATASET_ID:-benchmark/dummy}" \
  VECTOR_RUNTIME_MODE="production" \
  VECTOR_SYNC_WITH_BLOCKCHAIN="true" \
  VECTOR_RANDOM_SEED="${VECTOR_RANDOM_SEED:-42}" \
  VECTOR_TRAIN_RATIO="${VECTOR_TRAIN_RATIO:-0.7}" \
  VECTOR_VAL_RATIO="${VECTOR_VAL_RATIO:-0.15}" \
  VECTOR_TEST_RATIO="${VECTOR_TEST_RATIO:-0.15}" \
  VECTOR_DEV_DATASET_LIMIT="${VECTOR_DEV_DATASET_LIMIT:-0}" \
  "$VECTOR_PYTHON_BIN" image-vector-service/main.py "$VECTOR_MODE"

echo
echo "Image vector service mode: $VECTOR_MODE"
echo "Contracts file: $STACK_PATH"
echo "Pinata mock base URL: $PINATA_MOCK_BASE_URL"
echo "Isolated access state: $ACCESS_STATE_PATH"
echo "Isolated vector state dir: $VECTOR_STATE_DIR"
echo "All test services are starting. Press Ctrl+C to stop them together."

wait