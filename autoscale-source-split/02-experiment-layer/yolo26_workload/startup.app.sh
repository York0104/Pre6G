#!/usr/bin/env bash
set -euo pipefail

exec python3 -m uvicorn app:app --host 0.0.0.0 --port 18080

