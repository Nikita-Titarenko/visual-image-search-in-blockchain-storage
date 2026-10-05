#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

ORACLE_PYTHON_BIN="$ROOT_DIR/oracle/.venv/Scripts/python.exe"
VECTOR_PYTHON_BIN="$ROOT_DIR/image-vector-service/.venv/Scripts/python.exe"

if [[ ! -x "$ORACLE_PYTHON_BIN" ]]; then
  echo "Oracle Python interpreter not found at $ORACLE_PYTHON_BIN"
  echo "Create oracle/.venv and install oracle and pinata-proxy dependencies first."
  exit 1
fi

if [[ ! -x "$VECTOR_PYTHON_BIN" ]]; then
  echo "Image vector service Python interpreter not found at $VECTOR_PYTHON_BIN"
  echo "Create image-vector-service/.venv and install its dependencies first."
  exit 1
fi

if command -v npm.cmd >/dev/null 2>&1; then
  NPM_CMD=(npm.cmd)
elif command -v npm >/dev/null 2>&1; then
  NPM_CMD=(npm)
else
  echo "npm is not available in PATH."
  exit 1
fi

declare -a PIDS=()

cleanup() {
  local exit_code=$?

  if [[ ${#PIDS[@]} -gt 0 ]]; then
    echo
    echo "Stopping services..."
    for pid in "${PIDS[@]}"; do
      kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null || true
  fi

  exit "$exit_code"
}

trap cleanup EXIT INT TERM

start_service() {
  local name="$1"
  shift

  echo "Starting $name..."
  "$@" &
  local pid=$!
  PIDS+=("$pid")
  echo "$name started with PID $pid"
}

start_service "Pinata proxy" "$ORACLE_PYTHON_BIN" pinata-proxy/pinata_proxy.py
start_service "Oracle" "$ORACLE_PYTHON_BIN" -m uvicorn oracle.main:app --host 0.0.0.0 --port 8000
start_service "Image vector service" "$VECTOR_PYTHON_BIN" -m uvicorn main:app --app-dir image-vector-service --host 0.0.0.0 --port 8010
start_service "Angular web client" "${NPM_CMD[@]}" --prefix client start

echo
echo "All services are starting. Press Ctrl+C to stop them together."

wait