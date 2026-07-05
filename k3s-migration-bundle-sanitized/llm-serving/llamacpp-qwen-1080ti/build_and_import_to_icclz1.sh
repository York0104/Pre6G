#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="${IMAGE_NAME:-pre6g/llamacpp-cuda118-sm61:qwen25-15b-q4km}"
LLAMA_CPP_REF="${LLAMA_CPP_REF:-b9870}"
REMOTE_SSH_TARGET="${REMOTE_SSH_TARGET:-icclz1@icclz1}"
REMOTE_IMPORT_CMD="${REMOTE_IMPORT_CMD:-sudo k3s ctr images import -}"
SKIP_BUILD="${SKIP_BUILD:-0}"

if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] docker is required to build the llama.cpp benchmark image." >&2
  exit 1
fi

if ! command -v ssh >/dev/null 2>&1; then
  echo "[ERROR] ssh is required to import the image into icclz1." >&2
  exit 1
fi

if [[ "${SKIP_BUILD}" != "1" ]]; then
  echo "[INFO] Building ${IMAGE_NAME} from ${SCRIPT_DIR}"
  docker build \
    -f "${SCRIPT_DIR}/Dockerfile.cuda118-sm61" \
    --build-arg "LLAMA_CPP_REF=${LLAMA_CPP_REF}" \
    -t "${IMAGE_NAME}" \
    "${SCRIPT_DIR}"
fi

echo "[INFO] Streaming ${IMAGE_NAME} into ${REMOTE_SSH_TARGET}"
echo "[INFO] You may be prompted for the SSH password of ${REMOTE_SSH_TARGET}."
docker save "${IMAGE_NAME}" \
  | gzip \
  | ssh "${REMOTE_SSH_TARGET}" "gunzip | ${REMOTE_IMPORT_CMD}"

echo "[OK] ${IMAGE_NAME} imported into ${REMOTE_SSH_TARGET}"
