#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
VECTOR_MODE="${1:-production}"

if [[ "$VECTOR_MODE" != "production" && "$VECTOR_MODE" != "development" ]]; then
  echo "Usage: ./start-centralized-test-services.sh [production|development]"
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
SMART_CONTRACTS_MOCK_PYTHON_BIN="$ROOT_DIR/smart-contracts-mock/.venv/Scripts/python.exe"
PINATA_MOCK_PYTHON_BIN="$IMAGE_ACCESS_PYTHON_BIN"
RUNTIME_DIR="$ROOT_DIR/smart-contracts/reports/centralized-benchmark-runtime"
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

if [[ ! -x "$SMART_CONTRACTS_MOCK_PYTHON_BIN" ]]; then
  echo "Smart contracts mock Python interpreter not found at $SMART_CONTRACTS_MOCK_PYTHON_BIN"
  echo "Create smart-contracts-mock/.venv and install smart-contracts-mock dependencies first."
  exit 1
fi

if [[ -z "${SMART_CONTRACTS_MOCK_DATABASE_URL:-}" ]]; then
  echo "SMART_CONTRACTS_MOCK_DATABASE_URL must be set in .env before starting the centralized benchmark stack."
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
    echo "Stopping centralized benchmark stack..."
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

recreate_mock_database() {
  echo "Recreating smart-contracts-mock database..."
  env SMART_CONTRACTS_MOCK_DATABASE_URL="$SMART_CONTRACTS_MOCK_DATABASE_URL" \
    "$SMART_CONTRACTS_MOCK_PYTHON_BIN" - <<'PY'
from __future__ import annotations

import os
from urllib.parse import unquote, urlsplit

import pymysql


database_url = os.environ["SMART_CONTRACTS_MOCK_DATABASE_URL"].strip()
parts = urlsplit(database_url)

if parts.scheme != "mysql+pymysql":
    raise RuntimeError(f"Unsupported SMART_CONTRACTS_MOCK_DATABASE_URL scheme: {parts.scheme}")

database_name = parts.path.lstrip("/")
if not database_name:
    raise RuntimeError("SMART_CONTRACTS_MOCK_DATABASE_URL must include a database name.")

connection = pymysql.connect(
    host=parts.hostname or "127.0.0.1",
    port=parts.port or 3306,
    user=unquote(parts.username or ""),
    password=unquote(parts.password or ""),
    charset="utf8mb4",
    autocommit=True,
)

try:
    with connection.cursor() as cursor:
        quoted_name = f"`{database_name.replace('`', '``')}`"
        cursor.execute(f"DROP DATABASE IF EXISTS {quoted_name}")
        cursor.execute(f"CREATE DATABASE {quoted_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
finally:
    connection.close()
PY
}

PINATA_MOCK_PORT="${PINATA_MOCK_PORT:-3101}"
PINATA_MOCK_BASE_URL="http://127.0.0.1:$PINATA_MOCK_PORT"
PINATA_API_BASE_URL="$PINATA_MOCK_BASE_URL"
PINATA_GATEWAY_BASE_URL="$PINATA_MOCK_BASE_URL/ipfs"
ACCESS_BASE_URL="${BENCHMARK_ACCESS_BASE_URL:-http://127.0.0.1:8000}"
VECTOR_BASE_URL="${BENCHMARK_VECTOR_BASE_URL:-http://127.0.0.1:8010}"
CONTRACTS_MOCK_BASE_URL="${BENCHMARK_CENTRALIZED_BASE_URL:-http://127.0.0.1:8020}"

recreate_mock_database

start_service "Pinata mock" env \
  PINATA_MOCK_PORT="$PINATA_MOCK_PORT" \
  PINATA_MOCK_STATE_DIR="$PINATA_MOCK_STATE_DIR" \
  "$PINATA_MOCK_PYTHON_BIN" pinata-mock/pinata_mock.py

start_service "Pinata proxy" env \
  PINATA_API_BASE_URL="$PINATA_API_BASE_URL" \
  PINATA_GATEWAY_BASE_URL="$PINATA_GATEWAY_BASE_URL" \
  "$IMAGE_ACCESS_PYTHON_BIN" pinata-proxy/pinata_proxy.py

start_service "Smart contracts mock" env \
  SMART_CONTRACTS_MOCK_DATABASE_URL="$SMART_CONTRACTS_MOCK_DATABASE_URL" \
  SMART_CONTRACTS_MOCK_ALLOWED_ORIGINS="*" \
  "$SMART_CONTRACTS_MOCK_PYTHON_BIN" -m uvicorn main:app --app-dir smart-contracts-mock --host 127.0.0.1 --port 8020

start_service "Image access service" env \
  ORACLE_STORE_PATH="$ACCESS_STATE_PATH" \
  ORACLE_ALLOWED_ORIGINS="*" \
  ORACLE_ACCESS_TOKEN_TTL_MINUTES="${ORACLE_ACCESS_TOKEN_TTL_MINUTES:-30}" \
  ORACLE_SIGNATURE_TTL_MINUTES="${ORACLE_SIGNATURE_TTL_MINUTES:-30}" \
  PINATA_API_BASE_URL="$PINATA_API_BASE_URL" \
  PINATA_GATEWAY_BASE_URL="$PINATA_GATEWAY_BASE_URL" \
  PINATA_JWT="${PINATA_JWT:-}" \
  ORACLE_USE_CENTRALIZED_BACKEND="true" \
  CONTRACTS_MOCK_BASE_URL="$CONTRACTS_MOCK_BASE_URL" \
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
  AUDIT_PRIVATE_KEY="${AUDIT_PRIVATE_KEY:-${DEPLOYER_PRIVATE_KEY:-}}" \
  PINATA_API_BASE_URL="$PINATA_API_BASE_URL" \
  PINATA_GATEWAY_BASE_URL="$PINATA_GATEWAY_BASE_URL" \
  VECTOR_MODEL_VERSION="${VECTOR_MODEL_VERSION:-benchmark-model}" \
  VECTOR_INDEX_VERSION="${VECTOR_INDEX_VERSION:-benchmark-index}" \
  VECTOR_TEST_DATASET_ID="${VECTOR_TEST_DATASET_ID:-benchmark/dummy}" \
  VECTOR_RUNTIME_MODE="production" \
  VECTOR_SYNC_WITH_BLOCKCHAIN="false" \
  VECTOR_USE_CENTRALIZED_BACKEND="true" \
  CONTRACTS_MOCK_BASE_URL="$CONTRACTS_MOCK_BASE_URL" \
  CONTRACTS_MOCK_POLL_INTERVAL_SECONDS="${CONTRACTS_MOCK_POLL_INTERVAL_SECONDS:-1.0}" \
  VECTOR_AUDIT_SUBMITTER="${VECTOR_AUDIT_SUBMITTER:-benchmark-runner}" \
  VECTOR_RANDOM_SEED="${VECTOR_RANDOM_SEED:-42}" \
  VECTOR_TRAIN_RATIO="${VECTOR_TRAIN_RATIO:-0.7}" \
  VECTOR_VAL_RATIO="${VECTOR_VAL_RATIO:-0.15}" \
  VECTOR_TEST_RATIO="${VECTOR_TEST_RATIO:-0.15}" \
  VECTOR_DEV_DATASET_LIMIT="${VECTOR_DEV_DATASET_LIMIT:-0}" \
  "$VECTOR_PYTHON_BIN" image-vector-service/main.py "$VECTOR_MODE"

echo
echo "Image vector service mode: $VECTOR_MODE"
echo "Smart contracts mock base URL: $CONTRACTS_MOCK_BASE_URL"
echo "Pinata mock base URL: $PINATA_MOCK_BASE_URL"
echo "Isolated access state: $ACCESS_STATE_PATH"
echo "Isolated vector state dir: $VECTOR_STATE_DIR"
echo "All centralized test services are starting. Press Ctrl+C to stop them together."

wait