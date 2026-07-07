# Device Availability Smoke Comparison

Date: `2026-07-07`

Target node:

- `icclz1`

Sentinel target:

- `http://100.105.48.97:18080`

## Runs

1. `cpu_smoke_20260707_live`
2. `mem_smoke_20260707_live`
3. `mix_smoke_20260707_live`

All three runs used:

- `5s` probe interval
- MVP `UP/DOWN` rule
- direct node probe from `icclz2`

## Availability Summary

| Run | Samples | DOWN | DEGRADED | Availability |
| --- | ---: | ---: | ---: | ---: |
| `cpu_smoke` | 28 | 0 | 0 | `100.0%` |
| `mem_smoke` | 23 | 0 | 0 | `100.0%` |
| `mix_smoke` | 23 | 0 | 1 | `100.0%` |

## Compute-Check Comparison

### `cpu_smoke`

| Phase | n | mean ms | max ms |
| --- | ---: | ---: | ---: |
| `BASELINE` | 5 | `121.899` | `163.635` |
| `CPU-M` | 11 | `228.600` | `440.834` |
| `RECOVERY-1` | 5 | `125.961` | `167.800` |

### `mem_smoke`

| Phase | n | mean ms | max ms |
| --- | ---: | ---: | ---: |
| `BASELINE` | 6 | `175.617` | `349.738` |
| `MEM-M` | 10 | `185.703` | `403.845` |
| `RECOVERY-1` | 6 | `106.051` | `198.591` |

### `mix_smoke`

| Phase | n | mean ms | max ms |
| --- | ---: | ---: | ---: |
| `BASELINE` | 5 | `209.350` | `415.363` |
| `MIX-H` | 11 | `222.282` | `1129.009` |
| `RECOVERY-1` | 5 | `99.082` | `211.191` |

## Key Observations

1. All three short smoke runs remained at `100%` availability under the MVP rule, with no `DOWN` sample observed.
2. `CPU-M` increased `compute-check` mean latency relative to its baseline, but stayed well below the `2s` failure threshold.
3. `MEM-M` produced only mild additional `compute-check` latency in this short run.
4. `MIX-H` produced the heaviest tail and one `DEGRADED` sample, with a peak `compute_ms` of `1129.009`, but still no `DOWN`.
5. Recovery phases in all three runs returned to lower latency ranges than their stress phases.

## Notes

1. Some runs contain a trailing `COMPLETE` row and one `mix_smoke` row with `phase=unknown`; these are probe/timeline boundary artifacts and are excluded from the phase comparison above.
2. This report summarizes short smoke runs only. It is evidence that the device-service path remained reachable under brief stress, not yet a formal `6h` or `24h` claim.
