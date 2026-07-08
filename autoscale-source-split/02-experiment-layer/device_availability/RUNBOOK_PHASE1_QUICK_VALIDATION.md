# Phase 1 Quick Validation Runbook

這份 runbook 對應 `Phase 1: Quick Availability Validation`。

目的不是正式宣稱 `>=99.9%`，而是做一輪連續觀測，確認：

- `Node Ready` 是否持續為 `True`
- `healthz` 是否持續成功
- `compute-check` 是否持續 `< 2s`
- `MIX-M` 是否持續出現 `> 1s` tail latency

## Scope

目標節點：

- `icclz1`

外部 probe 來源：

- `icclz2`

目前建議 target host：

- `100.105.48.97`

## Important Note On Duration

目前 reviewed phase table 雖口語上稱為「2h quick validation」，但依實際 phase 長度相加為：

- `150 minutes`
- 也就是 `2h30m`

本 runbook 與 helper script 依照這份 phase table原樣落地，不自行壓縮時間。

## Phase Table

```text
00:00-00:20  BASELINE
00:20-00:50  CPU-M
00:50-01:00  RECOVERY-1
01:00-01:30  MEM-M
01:30-01:40  RECOVERY-2
01:40-02:10  MIX-M
02:10-02:30  FINAL-RECOVERY
```

## Stress Settings

先沿用目前已在 short smoke 驗證過的設定：

- `CPU-M`
  - `CPU_M_WORKERS=4`
- `MEM-M`
  - `MEM_M_WORKERS=1`
  - `MEM_M_BYTES=6G`
- `MIX-M`
  - `MIX_M_CPU_WORKERS=4`
  - `MIX_M_MEM_WORKERS=1`
  - `MIX_M_MEM_BYTES=6G`

## Preconditions

開始前請確認：

1. `icclz1` 已有 label `availability-test=target`
2. `intent-lab/node-sentinel-script` ConfigMap 存在
3. `node-sentinel` DaemonSet 仍在 `icclz1` 正常運作
4. `polinux/stress:latest` 已成功拉取過，或 registry 路徑可用

## One-Command Execution

```bash
cd /home/icclz2/Pre6G/autoscale-source-split
bash 02-experiment-layer/device_availability/run_phase1_quick_validation.sh
```

若要指定輸出目錄：

```bash
cd /home/icclz2/Pre6G/autoscale-source-split
OUT_DIR=02-experiment-layer/device_availability/results/phase1_quick_validation_manual \
bash 02-experiment-layer/device_availability/run_phase1_quick_validation.sh phase1_quick_validation_manual
```

## Output Artifacts

主要輸出位於：

- `availability.csv`
- `summary.json`
- `phase_timeline.jsonl`
- `current_phase.json`

## Expected Interpretation

這輪若成功，代表：

- 連續 phase 切換在 live cluster 可穩定執行
- target node 在 `CPU-M`、`MEM-M`、`MIX-M` 壓力下仍保有設備服務能力
- 可進一步根據 `compute_ms` tail 行為校正 `DEGRADED` threshold

這輪若失敗，優先看：

1. `availability.csv` 中第一筆 `DOWN` 或 `DEGRADED`
2. `phase_timeline.jsonl` 對應當時 phase
3. `kubectl get node icclz1`
4. `kubectl -n intent-lab get pods -o wide`
5. `kubectl -n intent-lab logs ds/node-sentinel --tail=100`

## Recommended Post-Run Review

至少整理：

1. 各 phase `compute_ms` mean / p95 / max
2. 是否出現 `>1s` tail latency
3. 是否有任何 `DOWN`
4. recovery phase 是否回落
