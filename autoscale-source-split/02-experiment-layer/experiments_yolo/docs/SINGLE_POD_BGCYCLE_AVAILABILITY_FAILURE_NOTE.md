# single_pod_bgload_fan_cycle Availability Failure Note

This note records the interpretation boundary for aggressive `single_pod_bgload_fan_cycle` runs that show many request failures and Kubernetes restarts.

## Core Distinction

The intended clean thermal-performance chain is:

```text
GPU temperature rises
-> GPU clock / compute capability drops
-> YOLO inference latency rises
-> E2E latency rises
```

Some aggressive fan-cycle runs instead show:

```text
high load + low fan + background load
-> /healthz timeout
-> liveness probe marks container unhealthy
-> Kubernetes restarts the container
-> client keeps calling the same Pod IP / port
-> connection refused burst
```

These are different regimes. The first is continuous performance degradation. The second is service availability collapse with pod lifecycle intervention.

## Why This Is Not Clean Thermal-Induced Latency Degradation

- `connection refused` means the HTTP server was not listening on the target port. It is not a slow inference sample.
- Container restart makes service state discontinuous. Model loading, CUDA initialization, HTTP server startup, and readiness all restart.
- Successful request latency has selection bias during failure windows because failed requests have no valid inference latency.
- A closed-loop serial client without backoff can generate many fast failures during a short outage, inflating error row counts without representing external offered demand.
- Direct Pod IP targeting bypasses Service readiness/endpoints behavior. This is useful for single-pod lifecycle observation, but not for user-facing service availability.
- Liveness/readiness probes become an intervention loop: inference or healthz delay can trigger kubelet restart, which changes the experiment from latency degradation to orchestration recovery.
- Simultaneously high `REPEAT`, high background load, low fixed fan, and high thermal target confound thermal throttling, GPU contention, queueing/blocking, health probe timeout, and container restart.

## Reporting Rule

For such runs, report latency and availability separately:

- Success-only latency plots are valid for successful samples only.
- Failure rate, timeout/error burst, connection refused, readiness/liveness failures, and restart count must be reported as availability outcomes.
- Do not treat failed request rows as latency degradation samples.
- Do not claim a clean NVIDIA thermal throttling mechanism unless P-state, throttle reason, performance-cap reason, and continuous no-restart inference telemetry support it.

## Recommended Claim

For aggressive runs with liveness restarts and connection-refused bursts:

```text
This run is not clean evidence of thermal-induced latency degradation.
It shows that under combined thermal/load stress the service crosses into an availability failure regime,
with health probe timeouts, container restart, and connection-refused bursts.
```

Use these runs as:

```text
failure threshold / resilience experiments
```

not as:

```text
clean latency degradation experiments
```

## Follow-up Experiment Design

To study thermal-induced latency degradation more cleanly:

- Lower load so success rate stays near 100%.
- Use open-loop fixed offered rate instead of closed-loop no-backoff serial retry.
- Separate healthz/readiness from long inference paths.
- Avoid liveness restart during the measurement window, or explicitly classify restart as failure-threshold onset.
- Record GPU temperature, SM clock, power, success latency, timeout/error rate, and restart events together.
- Plot success latency and failure rate separately.
- Define the first restart/error burst as an availability failure threshold, not a latency sample.
