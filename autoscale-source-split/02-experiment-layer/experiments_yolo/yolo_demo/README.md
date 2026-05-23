# YOLO Demo

This demo project extracts the runtime parts of `single_pod_bgload_fan_cycle`
that are useful for interactive dashboard demos:

- scale the focus deploy to a single pod
- resolve `FOCUS_POD` and `TARGET_URL`
- start the closed-loop serial request client
- start the GPU background load

Fan control is intentionally separated from the auto-start flow and is exposed
through the dashboard as manual fixed fan modes only:

- `GPU_DEFAULT`
- `FIXED_5`
- `FIXED_15`
- `FIXED_20`
- `FIXED_25`

Stopping the demo shuts down the measurement client, stops the background load,
and scales the YOLO deploys back to zero replicas.
