#!/usr/bin/env bash
set -euo pipefail

PATH_ONLY="${1:?path required}"
OUT_CSV="${2:?output csv required}"
LABEL="${3:?label required}"
ITERATIONS="${ITERATIONS:-180}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-5}"
NAMESPACE="${NAMESPACE:-intent-lab}"

mkdir -p "$(dirname "${OUT_CSV}")"
REMOTE_CSV="/tmp/${LABEL}_$(date +%s).csv"

kubectl -n "${NAMESPACE}" exec ds/node-sentinel -- python3 -c "
import csv, json, socket, sys, time, urllib.error, urllib.request
path = sys.argv[1]
out_csv = sys.argv[2]
label = sys.argv[3]
iterations = int(sys.argv[4])
interval = float(sys.argv[5])
url = f'http://127.0.0.1:18080{path}'
with open(out_csv, 'w', encoding='utf-8', newline='') as fh:
    writer = csv.writer(fh)
    writer.writerow(['timestamp','label','url','http_code','elapsed_ms','ok','exception_type','exception_text'])
    for _ in range(iterations):
        ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        started = time.perf_counter()
        code = 0
        ok = 0
        exc_type = ''
        exc_text = ''
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                resp.read()
                code = resp.status
                ok = 1 if code == 200 else 0
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc_type = type(exc).__name__
            exc_text = str(exc).replace(',', ';')
        except Exception as exc:
            exc_type = type(exc).__name__
            exc_text = str(exc).replace(',', ';')
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        writer.writerow([ts, label, url, code, round(elapsed_ms, 3), ok, exc_type, exc_text])
        fh.flush()
        time.sleep(interval)
" "${PATH_ONLY}" "${REMOTE_CSV}" "${LABEL}" "${ITERATIONS}" "${INTERVAL_SECONDS}"

kubectl -n "${NAMESPACE}" exec ds/node-sentinel -- cat "${REMOTE_CSV}" > "${OUT_CSV}"
kubectl -n "${NAMESPACE}" exec ds/node-sentinel -- rm -f "${REMOTE_CSV}" >/dev/null
