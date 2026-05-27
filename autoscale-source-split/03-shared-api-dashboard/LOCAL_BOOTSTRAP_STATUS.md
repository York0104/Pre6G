# Local Bootstrap Status

Date: 2026-05-25
Host: `/home/icclz2/Pre6G`

## What Is Ready

- Monitoring backend is available for `iccl-cluster-z2` and `icclz3`
- Host-side monitoring endpoints are saved in:
  - [autoscale-source-split/01-monitoring-layer/monitoring-runtime.host.env](/home/icclz2/Pre6G/autoscale-source-split/01-monitoring-layer/monitoring-runtime.host.env)
- Local API launcher is prepared:
  - [autoscale-source-split/03-shared-api-dashboard/autoscale_api/run_local_api.sh](/home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/autoscale_api/run_local_api.sh)
- Local dashboard launcher is prepared:
  - [autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/run_local_dashboard.sh](/home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/run_local_dashboard.sh)
- Dashboard API base example is prepared:
  - [autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/.env.example](/home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/cluster-dashboard/.env.example)

## Current Blockers

### Python env `iccl`

Requested target env name: `iccl`

Current machine state:

- `/usr/bin/python3` exists
- `python3 -m venv iccl` fails because `ensurepip` is unavailable
- `/usr/bin/python3` also has no `pip`
- `sudo apt-get` cannot be completed in the current session because sudo password input is unavailable

Impact:

- `autoscale_api` cannot be started yet with a dedicated local env on this machine

Needed fix on the host:

1. Install Python venv tooling, e.g. `python3.12-venv`
2. Create env `iccl`
3. Install shared requirements from `autoscale-source-split/03-shared-api-dashboard/requirements.txt`

### Dashboard runtime

Current machine state:

- `node` not installed
- `npm` not installed

Impact:

- `cluster-dashboard` cannot be built or served yet on this machine

Needed fix on the host:

1. Install Node.js and npm
2. Run `run_local_dashboard.sh`

## Minimal Start Commands After Host Dependencies Exist

### API

```bash
cd /home/icclz2/Pre6G
python3 -m venv iccl
./iccl/bin/pip install -r autoscale-source-split/03-shared-api-dashboard/requirements.txt
bash autoscale-source-split/03-shared-api-dashboard/autoscale_api/run_local_api.sh
```

### Dashboard

```bash
cd /home/icclz2/Pre6G/autoscale-source-split/03-shared-api-dashboard/cluster-dashboard
cp .env.example .env
bash run_local_dashboard.sh
```

## Notes

- `run_local_api.sh` will automatically load `monitoring-runtime.host.env` if it exists.
- `run_local_dashboard.sh` intentionally stops early if `node` / `npm` are missing, so the failure mode is explicit.
- `z590-aorus-xtreme` is still not recommended as a dashboard validation target until its disk issue is resolved.
