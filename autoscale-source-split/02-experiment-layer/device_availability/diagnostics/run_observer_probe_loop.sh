#!/usr/bin/env bash
set -euo pipefail

URL="${1:?url required}"
OUT_CSV="${2:?output csv required}"
LABEL="${3:?label required}"
ITERATIONS="${ITERATIONS:-180}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-5}"
CONNECT_TIMEOUT_SECONDS="${CONNECT_TIMEOUT_SECONDS:-2}"
MAX_TIME_SECONDS="${MAX_TIME_SECONDS:-5}"

mkdir -p "$(dirname "${OUT_CSV}")"
echo "timestamp,label,url,http_code,curl_exit,connect_ms,starttransfer_ms,total_ms,error_class,error_text" > "${OUT_CSV}"

classify_error() {
  local curl_exit="$1"
  case "${curl_exit}" in
    0) echo "ok" ;;
    28) echo "timeout" ;;
    7) echo "connect_failed" ;;
    *) echo "curl_exit_${curl_exit}" ;;
  esac
}

for ((i=0; i<ITERATIONS; i++)); do
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  out_file="$(mktemp)"
  err_file="$(mktemp)"
  writeout_file="$(mktemp)"
  if curl -sS -o "${out_file}" \
    --connect-timeout "${CONNECT_TIMEOUT_SECONDS}" \
    --max-time "${MAX_TIME_SECONDS}" \
    -w "%{http_code},%{time_connect},%{time_starttransfer},%{time_total}" \
    "${URL}" > "${writeout_file}" 2>"${err_file}"; then
    curl_exit=0
  else
    curl_exit=$?
  fi
  writeout="$(cat "${writeout_file}" 2>/dev/null || true)"
  http_code="$(echo "${writeout}" | cut -d',' -f1)"
  connect_s="$(echo "${writeout}" | cut -d',' -f2)"
  starttransfer_s="$(echo "${writeout}" | cut -d',' -f3)"
  total_s="$(echo "${writeout}" | cut -d',' -f4)"
  error_text="$(tr '\n' ' ' < "${err_file}" | tr ',' ';')"
  error_class="$(classify_error "${curl_exit}")"
  awk \
    -v ts="${ts}" \
    -v label="${LABEL}" \
    -v url="${URL}" \
    -v code="${http_code:-0}" \
    -v exit_code="${curl_exit}" \
    -v c="${connect_s:-0}" \
    -v s="${starttransfer_s:-0}" \
    -v t="${total_s:-0}" \
    -v eclass="${error_class}" \
    -v etext="${error_text}" \
    'BEGIN { printf "%s,%s,%s,%s,%s,%.3f,%.3f,%.3f,%s,%s\n", ts, label, url, code, exit_code, c*1000, s*1000, t*1000, eclass, etext }' \
    >> "${OUT_CSV}"
  rm -f "${out_file}" "${err_file}" "${writeout_file}"
  sleep "${INTERVAL_SECONDS}"
done
