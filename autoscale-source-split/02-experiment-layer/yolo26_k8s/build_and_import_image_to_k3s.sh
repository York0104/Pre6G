#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_TAGS_STR="${IMAGE_TAGS:-0.1 0.5}"
CTR_IMPORT_CMD="${CTR_IMPORT_CMD:-sudo k3s ctr images import}"

if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] docker is required to build the YOLO26 image." >&2
  exit 1
fi

for tag in ${IMAGE_TAGS_STR}; do
  image="local/yolo26n:${tag}"
  echo "[INFO] Building ${image} from ${SCRIPT_DIR}"
  docker build -t "${image}" "${SCRIPT_DIR}"

  tmp_tar="$(mktemp /tmp/yolo26n_${tag//./_}.XXXXXX.tar)"
  cleanup() { rm -f "${tmp_tar}"; }
  trap cleanup EXIT

  echo "[INFO] Saving ${image} to ${tmp_tar}"
  docker save -o "${tmp_tar}" "${image}"

  echo "[INFO] Importing ${image} into k3s containerd"
  ${CTR_IMPORT_CMD} "${tmp_tar}"
  cleanup
  trap - EXIT
done

echo "[OK] YOLO26 images imported into k3s."
