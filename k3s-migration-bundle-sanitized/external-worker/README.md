# External Worker Dependencies

thermal/fan-control runner 位於 worker node，不在此主機：

```text
/home/icclz1/gpu-tempctl-lab/fan_control_lab/gpu_cycle_runner.py
```

在新 worker 執行 thermal experiments 前，需先複製或重建 worker-side 專案，並驗證：

- fan control 可用。
- background GPU heating 可用。
- `nvidia-smi` 可讀取 GPU temperature、fan speed、power、clock。
