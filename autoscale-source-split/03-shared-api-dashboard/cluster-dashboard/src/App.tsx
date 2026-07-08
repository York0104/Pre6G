import { useEffect, useMemo, useRef, useState } from "react";
import {
  CartesianGrid,
  Label,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type DashboardRuntimeConfig = {
  apiBase?: string;
  apiToken?: string;
};

declare global {
  interface Window {
    __PRE6G_DASHBOARD_CONFIG__?: DashboardRuntimeConfig;
  }
}

function getRuntimeConfig(): DashboardRuntimeConfig {
  return window.__PRE6G_DASHBOARD_CONFIG__ || {};
}

const runtimeConfig = getRuntimeConfig();
const API_BASE =
  runtimeConfig.apiBase?.trim() ||
  import.meta.env.VITE_AUTOSCALE_API_BASE ||
  "http://127.0.0.1:8000";
const API_TOKEN =
  runtimeConfig.apiToken?.trim() ||
  import.meta.env.VITE_AUTOSCALE_API_TOKEN?.trim() ||
  "";
const API_TOKEN_PLACEHOLDER = "replace-with-issued-token";

function isDashboardTokenMissing(): boolean {
  return !API_TOKEN || API_TOKEN === API_TOKEN_PLACEHOLDER;
}

type NodeInventory = {
  node_name: string;
  role: string;
  k8s_ip: string;
  os?: {
    image?: string;
    kernel_version?: string;
    container_runtime?: string;
  };
  cpu?: {
    model_name?: string | null;
    vendor?: string | null;
    cores_total?: number;
  };
  memory?: {
    total_memory?: string;
  };
  gpu?: {
    has_gpu?: boolean;
    count?: number;
    models?: string[];
    memory?: string | null;
  };
};

type NodeStatus = {
  node_name: string;
  k8s_ip: string;
  sources?: {
    node_metrics?: string;
    gpu_metrics?: string;
  };
  cpu?: {
    usage_percent?: number | null;
    used_cores?: number | null;
  };
  memory?: {
    usage_percent?: number | null;
    working_set_mib?: number | null;
  };
  disk?: {
    root_usage_percent?: number | null;
  };
  gpu?: {
    status?: string;
    count?: number | null;
    fb_used_mib?: number | null;
  };
};

type NodeListResponse = {
  schema: string;
  ts: number;
  count: number;
  nodes: NodeInventory[];
};

type NodeStatusListResponse = {
  schema: string;
  ts: number;
  count: number;
  nodes: NodeStatus[];
};

type WorkloadListItem = {
  namespace: string;
  workload: string;
  runtime: string;
  model_name?: string | null;
  runtime_image?: string | null;
  runtime_version?: string | null;
  nodes: string[];
  status: "ready" | "not_ready" | "metrics_unavailable" | string;
  desired_replicas: number;
  ready_replicas: number;
  generation_tokens_per_second?: number | null;
  prompt_tokens_per_second?: number | null;
  waiting_requests?: number | null;
  kv_cache_usage_percent_max?: number | null;
};

type WorkloadListResponse = {
  schema: string;
  ts: number;
  freshness_seconds: number;
  query_window_seconds: number;
  count: number;
  workloads: WorkloadListItem[];
};

type WorkloadIdentity = {
  namespace: string;
  workload: string;
  runtime: string;
  model_name?: string | null;
  served_model_id?: string | null;
  runtime_image?: string | null;
  runtime_version?: string | null;
};

type WorkloadReplicaSummary = {
  desired: number;
  ready: number;
  metrics_available: number;
  metrics_unavailable: number;
};

type WorkloadReplicaStatus = {
  pod: string;
  node_name: string;
  status: "ready" | "not_ready" | "metrics_unavailable" | string;
  owner_resolution: string;
  pod_phase?: string | null;
  ready_condition?: boolean | null;
  metrics_observed_ts?: number | null;
  metrics_freshness_seconds?: number | null;
  generation_tokens_per_second?: number | null;
  prompt_tokens_per_second?: number | null;
  waiting_requests?: number | null;
  kv_cache_usage_percent?: number | null;
};

type WorkloadAggregateMetrics = {
  generation_tokens_per_second?: number | null;
  prompt_tokens_per_second?: number | null;
  waiting_requests?: number | null;
  kv_cache_usage_percent_max?: number | null;
};

type WorkloadStatusResponse = {
  schema: string;
  ts: number;
  freshness_seconds: number;
  query_window_seconds: number;
  metrics_observed_ts?: number | null;
  scrape_source: string;
  status: "ready" | "not_ready" | "metrics_unavailable" | string;
  identity: WorkloadIdentity;
  replica_summary: WorkloadReplicaSummary;
  replicas: WorkloadReplicaStatus[];
  aggregate: WorkloadAggregateMetrics;
};

type LlmInferenceRequest = {
  namespace: string;
  workload: string;
  prompt: string;
  max_tokens: number;
  temperature: number;
};

type LlmInferenceResponse = {
  schema: string;
  ts: number;
  namespace: string;
  workload: string;
  target_service: string;
  model?: string | null;
  http_status: number;
  latency_seconds: number;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  total_tokens?: number | null;
  finish_reason?: string | null;
  response_text?: string | null;
};

type LlmBenchmarkRunRequest = {
  namespace: string;
  workload: string;
  profile_id: string;
};

type LlamacppOfflineBenchmarkRunRequest = {
  profile: string;
};

type LlmSmokeBenchmarkResponse = {
  schema: string;
  ts: number;
  run_id: string;
  namespace: string;
  workload: string;
  profile: string;
  profile_id?: string | null;
  request_count: number;
  max_tokens: number;
  temperature: number;
  concurrency?: number | null;
  status: string;
  completed_requests: number;
  failed_requests: number;
  run_elapsed_seconds?: number | null;
  request_throughput_rps?: number | null;
  aggregate_prompt_tps?: number | null;
  aggregate_generation_tps?: number | null;
  aggregate_total_tps?: number | null;
  latency_p50_seconds?: number | null;
  latency_p95_seconds?: number | null;
  mean_latency_seconds?: number | null;
  mean_prompt_tokens?: number | null;
  mean_completion_tokens?: number | null;
  mean_total_tokens?: number | null;
  mean_ttft_seconds?: number | null;
  p95_ttft_seconds?: number | null;
  mean_tpot_seconds?: number | null;
  p95_tpot_seconds?: number | null;
  mean_itl_seconds?: number | null;
  p95_itl_seconds?: number | null;
};

type LlmBenchmarkProgressBucket = {
  second: number;
  completed_requests: number;
  failed_requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
};

type LlmBenchmarkProgressSnapshot = {
  elapsed_seconds: number;
  completed_requests: number;
  failed_requests: number;
  prompt_tokens_so_far: number;
  completion_tokens_so_far: number;
  total_tokens_so_far: number;
  current_request_throughput_rps: number;
  current_prompt_tps: number;
  current_generation_tps: number;
  current_total_tps: number;
  buckets: LlmBenchmarkProgressBucket[];
};

type LlmBenchmarkRunStartResponse = {
  schema: string;
  ts: number;
  run_id: string;
  namespace: string;
  workload: string;
  profile: string;
  profile_id: string;
  status: string;
};

type LlmBenchmarkRunStatusResponse = {
  schema: string;
  ts: number;
  run_id: string;
  namespace: string;
  workload: string;
  profile: string;
  profile_id: string;
  status: string;
  request_count: number;
  concurrency: number;
  max_tokens: number;
  temperature: number;
  started_ts: number;
  finished_ts?: number | null;
  progress: LlmBenchmarkProgressSnapshot;
  result?: LlmSmokeBenchmarkResponse | null;
  error?: string | null;
};

type LlmBenchmarkRunCancelResponse = {
  schema: string;
  ts: number;
  run_id: string;
  status: string;
};

type LlmRunHistoryItem = {
  ts: number;
  event_type: string;
  runtime?: string | null;
  benchmark_mode?: string | null;
  namespace: string;
  workload: string;
  status: string;
  run_id?: string | null;
  profile?: string | null;
  profile_id?: string | null;
  model?: string | null;
  latency_seconds?: number | null;
  prompt_char_count?: number | null;
  prompt_sha256?: string | null;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  total_tokens?: number | null;
  finish_reason?: string | null;
  request_count?: number | null;
  concurrency?: number | null;
  completed_requests?: number | null;
  failed_requests?: number | null;
  run_elapsed_seconds?: number | null;
  request_throughput_rps?: number | null;
  aggregate_prompt_tps?: number | null;
  aggregate_generation_tps?: number | null;
  aggregate_total_tps?: number | null;
  latency_p50_seconds?: number | null;
  latency_p95_seconds?: number | null;
  mean_latency_seconds?: number | null;
  mean_prompt_tokens?: number | null;
  mean_completion_tokens?: number | null;
  mean_total_tokens?: number | null;
  mean_ttft_seconds?: number | null;
  p95_ttft_seconds?: number | null;
  mean_tpot_seconds?: number | null;
  p95_tpot_seconds?: number | null;
  mean_itl_seconds?: number | null;
  p95_itl_seconds?: number | null;
  prompt_tps_mean?: number | null;
  prompt_tps_stddev?: number | null;
  generation_tps_mean?: number | null;
  generation_tps_stddev?: number | null;
  prompt_generation_tps_mean?: number | null;
  prompt_generation_tps_stddev?: number | null;
  duration_seconds?: number | null;
  observed_at_ts?: number | null;
  gpu_contended?: boolean | null;
  error_summary?: string | null;
};

type LlmRunHistoryResponse = {
  schema: string;
  ts: number;
  count: number;
  items: LlmRunHistoryItem[];
};

const BENCHMARK_PROFILES = [
  {
    id: "smoke",
    label: "Smoke",
    promptSource: "vLLM random synthetic dataset",
    maxTokens: 64,
    temperature: 0.0,
    concurrency: 1,
    requestCount: 20,
  },
  {
    id: "continuous",
    label: "Continuous",
    promptSource: "vLLM random synthetic dataset",
    maxTokens: 128,
    temperature: 0.0,
    concurrency: 8,
    requestCount: 50,
  },
] as const;

type LlamacppOfflineBenchmarkProfile = {
  profile_id: string;
  display_name: string;
  description: string;
  runtime: string;
  benchmark_mode: string;
  n_prompt: number;
  n_gen: number;
  n_depth: number;
  batch_size: number;
  ubatch_size: number;
  repetitions: number;
  flash_attention: string;
  gpu_layers: number;
};

type LlamacppOfflineBenchmarkProfilesResponse = {
  schema: string;
  ts: number;
  runtime: string;
  benchmark_mode: string;
  profiles: LlamacppOfflineBenchmarkProfile[];
};

type LlamacppOfflineGpuProcess = {
  pid?: number | null;
  process_name?: string | null;
  used_memory?: string | null;
};

type LlamacppOfflineRuntimeOverview = {
  runtime: string;
  benchmark_mode: string;
  runtime_image?: string | null;
  runtime_image_tag?: string | null;
  llama_cpp_ref?: string | null;
  llama_cpp_commit?: string | null;
  cuda_version?: string | null;
  gpu_model?: string | null;
  gpu_arch?: string | null;
  gpu_resource_request?: string | null;
  namespace: string;
  target_pod: string;
  node_name?: string | null;
  model_name?: string | null;
  model_source?: string | null;
  gguf_filename?: string | null;
  gguf_path?: string | null;
  gguf_sha256?: string | null;
  quantization?: string | null;
  gpu_layers?: string | null;
};

type LlamacppOfflineBenchmarkResult = {
  schema: string;
  ts: number;
  run_id: string;
  runtime: string;
  benchmark_mode: string;
  profile: string;
  profile_id: string;
  status: string;
  namespace: string;
  target_pod: string;
  node_name?: string | null;
  runtime_overview: LlamacppOfflineRuntimeOverview;
  observed_at_ts?: number | null;
  started_at_ts?: number | null;
  completed_at_ts?: number | null;
  duration_seconds?: number | null;
  prompt_tps_mean?: number | null;
  prompt_tps_stddev?: number | null;
  generation_tps_mean?: number | null;
  generation_tps_stddev?: number | null;
  prompt_generation_tps_mean?: number | null;
  prompt_generation_tps_stddev?: number | null;
  waiting_requests?: number | null;
  kv_cache_usage_percent?: number | null;
  n_prompt: number;
  n_gen: number;
  n_depth: number;
  batch_size: number;
  ubatch_size: number;
  n_gpu_layers: number;
  repetitions: number;
  flash_attention: string;
  gpu_processes_before: LlamacppOfflineGpuProcess[];
  gpu_process_count_before: number;
  gpu_contended: boolean;
  gpu_preflight_status: string;
  preflight_warning?: string | null;
  error_summary?: string | null;
};

type LlamacppOfflineBenchmarkProgressBucket = {
  step: number;
  elapsed_seconds: number;
  duration_seconds: number;
  prompt_tps?: number | null;
  generation_tps?: number | null;
  prompt_generation_tps?: number | null;
};

type LlamacppOfflineBenchmarkLiveBucket = {
  sample: number;
  elapsed_seconds: number;
  phase?: string | null;
  prompt_tps?: number | null;
  generation_tps?: number | null;
  prompt_generation_tps?: number | null;
};

type LlamacppOfflineBenchmarkProgressSnapshot = {
  elapsed_seconds: number;
  completed_steps: number;
  total_steps: number;
  current_prompt_tps?: number | null;
  current_generation_tps?: number | null;
  current_prompt_generation_tps?: number | null;
  latest_completed_step_prompt_tps?: number | null;
  latest_completed_step_generation_tps?: number | null;
  latest_completed_step_prompt_generation_tps?: number | null;
  mean_prompt_tps?: number | null;
  mean_generation_tps?: number | null;
  mean_prompt_generation_tps?: number | null;
  current_phase?: string | null;
  current_phase_detail?: string | null;
  live_sample_count?: number;
  live_buckets?: LlamacppOfflineBenchmarkLiveBucket[];
  buckets: LlamacppOfflineBenchmarkProgressBucket[];
};

type LlamacppOfflineBenchmarkRunStateResponse = {
  schema: string;
  ts: number;
  run_id: string;
  runtime: string;
  benchmark_mode: string;
  profile: string;
  profile_id: string;
  status: string;
  namespace: string;
  target_pod: string;
  node_name?: string | null;
  started_at_ts?: number | null;
  completed_at_ts?: number | null;
  progress?: LlamacppOfflineBenchmarkProgressSnapshot | null;
  result?: LlamacppOfflineBenchmarkResult | null;
  error?: string | null;
};

type LlamacppOfflineBenchmarkRunStartResponse = {
  schema: string;
  ts: number;
  run_id: string;
  runtime: string;
  benchmark_mode: string;
  profile: string;
  profile_id: string;
  status: string;
  namespace: string;
  target_pod: string;
};

type LlamacppOfflineBenchmarkRunCancelResponse = {
  schema: string;
  ts: number;
  run_id: string;
  status: string;
};

type Health = "healthy" | "degraded" | "offline";
type ActiveTab = "monitor" | "fan-experiment" | "llm-serving";
type FanMode =
  | "GPU_DEFAULT"
  | "FIXED_0"
  | "FIXED_5"
  | "FIXED_15"
  | "FIXED_20"
  | "FIXED_25"
  | "GPU_MAX";

type NodeView = {
  inventory: NodeInventory;
  status?: NodeStatus;
  health: Health;
};

type HistoryPoint = {
  ts: number;
  time: string;
  cpu: number;
  memory: number;
  disk: number;
  gpuFbUsed: number;
};

type ChartPoint = {
  time: string;
  [key: string]: number | string;
};

type ExperimentSeriesPoint = {
  time: string;
  phase: string;
  gpu_temp: number;
  fan_pct: number;
  sm_clock: number;
  gpu_util: number;
  server_latency: number;
  e2e_latency: number;
};

type ExperimentEvent = {
  time: string;
  level: "info" | "warn" | "critical";
  phase: string;
  event: string;
  detail: string;
  message: string;
};

type FanCycleCommandPreview = {
  smoke_test: string;
  full_experiment: string;
};

type FanControlSelection = {
  mode: FanMode;
};

type TimeWindow = "last-60s" | "last-5m" | "whole-run";

type FanCycleRunInfo = {
  run_id: string;
  status: string;
  target_node: string;
  gpu_name: string;
  workload: string;
  cycles: number;
  current_cycle: number;
  current_phase: string;
  elapsed_seconds: number;
  focus_pod: string;
  target_url: string;
};

type FanCycleConfig = {
  normal_hold_seconds: number;
  fault_hold_seconds: number;
  recovery_stable_seconds: number;
  recovery_max_seconds: number;
  fixed_fan_pct: number;
  normal_temp_min_c: number;
  normal_temp_max_c: number;
  fault_temp_target_c: number;
  bg_size: number;
  bg_duty: number;
  bg_period_ms: number;
};

type FanCycleCurrentMetrics = {
  gpu_temp_c: number;
  fan_pct: number;
  sm_clock_mhz: number;
  gpu_util_pct: number;
  server_latency_ms: number;
  e2e_latency_ms: number;
};

type FanCyclePhaseSummary = {
  cycle_index: number;
  phase: string;
  gpu_temp_c_mean: number;
  gpu_temp_c_p95: number;
  gpu_fan_pct_mean: number;
  gpu_util_pct_mean: number;
  gpu_clock_mhz_mean: number;
  server_latency_ms_p95: number;
  e2e_latency_ms_p95: number;
};

type FanCycleLatestResponse = {
  schema_name: string;
  generated_at: number;
  run: FanCycleRunInfo;
  config: FanCycleConfig;
  current: FanCycleCurrentMetrics;
  command_preview: FanCycleCommandPreview;
  phase_summary: FanCyclePhaseSummary[];
  timeseries: ExperimentSeriesPoint[];
  events: ExperimentEvent[];
};

type FanCycleLiveResponse = {
  schema_name: string;
  generated_at: number;
  run: FanCycleRunInfo;
  current: FanCycleCurrentMetrics;
};

type FanCycleExecutionStatusResponse = {
  schema_name: string;
  generated_at: number;
  status: "idle" | "starting" | "running" | "stopping" | "stopped" | "error";
  run_id: string;
  pid: number;
  started_at: number;
  result_run_dir: string;
  stdout_log: string;
  stderr_log: string;
  namespace: string;
  focus_deploy: string;
  bg_deploy: string;
  node_name: string;
  message: string;
  last_exit_code?: number | null;
};

type YoloDemoStatusResponse = {
  schema_name: string;
  generated_at: number;
  status: "idle" | "starting" | "running" | "stopping" | "stopped" | "error";
  run_id: string;
  namespace: string;
  focus_deploy: string;
  bg_deploy: string;
  focus_pod: string;
  target_url: string;
  target_mode: string;
  node_name: string;
  measurement_pid: number;
  bgload_pid: number;
  fan_mode: FanMode;
  fan_control_available: boolean;
  fan_control_message: string;
  started_at: number;
  message: string;
};

type YoloDemoEvent = {
  time: string;
  level: "info" | "warn" | "critical";
  event: string;
  message: string;
};

type YoloDemoEventsResponse = {
  schema_name: string;
  generated_at: number;
  events: YoloDemoEvent[];
};

type FanLivePoint = {
  ts: number;
  time: string;
  phase: string;
  gpu_temp: number;
  fan_pct: number;
  sm_clock: number;
  gpu_util: number;
  server_latency: number;
  e2e_latency: number;
};

type ThermalDemoStep = {
  key: "baseline" | "fault_fan" | "thermal_rise" | "clock_drop" | "recovery";
  label: string;
  detail: string;
  state: "done" | "active" | "pending";
};

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: API_TOKEN
      ? {
          Authorization: `Bearer ${API_TOKEN}`,
        }
      : undefined,
  });
  if (!res.ok) {
    if (res.status === 401 && isDashboardTokenMissing()) {
      console.warn(
        "autoscale_api returned 401 while VITE_AUTOSCALE_API_TOKEN is missing or still uses the example value.",
      );
      throw new Error(
        "401 Unauthorized: set VITE_AUTOSCALE_API_TOKEN in cluster-dashboard/.env to the issued AutoScale API token.",
      );
    }
    throw new Error(`${res.status} ${res.statusText}`);
  }
  return res.json();
}

async function postJsonBody<T>(path: string, body: unknown, method = "POST"): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {}),
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const payload = await res.json();
      if (payload?.detail) {
        detail = `${res.status} ${payload.detail}`;
      }
    } catch {
      // Keep fallback status text when the response body is not JSON.
    }
    throw new Error(detail);
  }
  return res.json();
}

function isNotFoundError(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  return error.message.startsWith("404 ");
}

function clampPercent(v?: number | null): number {
  if (v === undefined || v === null || Number.isNaN(v)) return 0;
  return Math.max(0, Math.min(100, v));
}

function isExternalRole(role?: string): boolean {
  if (!role) return false;
  return role !== "control-plane" && role !== "worker";
}

function getHealth(inventory: NodeInventory, status?: NodeStatus): Health {
  if (!status) return "offline";

  const hasAnyTelemetry =
    status.cpu?.usage_percent !== undefined &&
    status.cpu?.usage_percent !== null ||
    status.memory?.usage_percent !== undefined &&
    status.memory?.usage_percent !== null ||
    status.disk?.root_usage_percent !== undefined &&
    status.disk?.root_usage_percent !== null;

  const cpu = clampPercent(status.cpu?.usage_percent);
  const mem = clampPercent(status.memory?.usage_percent);
  const disk = clampPercent(status.disk?.root_usage_percent);
  const gpuStatus = status.gpu?.status?.toLowerCase() || "";
  const nodeSource = status.sources?.node_metrics?.toLowerCase() || "";
  const externalNode = isExternalRole(inventory.role);

  if (
    externalNode &&
    (
      !hasAnyTelemetry ||
      nodeSource === "error" ||
      gpuStatus.includes("metrics_error") ||
      gpuStatus.includes("error")
    )
  ) {
    return "offline";
  }

  if (
    !hasAnyTelemetry ||
    nodeSource === "error" ||
    gpuStatus.includes("metrics_error") ||
    gpuStatus.includes("error") ||
    cpu >= 90 ||
    mem >= 90 ||
    disk >= 90
  ) {
    return "degraded";
  }

  return "healthy";
}

function hasUsableNodeMetric(status: NodeStatus | undefined, metric: "cpu" | "memory"): boolean {
  if (!status) return false;
  const nodeSource = status.sources?.node_metrics?.toLowerCase() || "";
  if (nodeSource === "error") return false;
  if (metric === "cpu") {
    return status.cpu?.usage_percent !== undefined && status.cpu?.usage_percent !== null;
  }
  return status.memory?.usage_percent !== undefined && status.memory?.usage_percent !== null;
}

function healthClass(health: Health): string {
  if (health === "healthy") return "border-emerald-500/50 text-emerald-300";
  if (health === "degraded") return "border-orange-500/60 text-orange-300";
  return "border-slate-500/60 text-slate-400";
}

function healthDot(health: Health): string {
  if (health === "healthy") return "bg-emerald-400";
  if (health === "degraded") return "bg-orange-400";
  return "bg-slate-500";
}

function eventTone(level: ExperimentEvent["level"]): string {
  if (level === "critical") return "text-red-300";
  if (level === "warn") return "text-orange-300";
  return "text-sky-300";
}

function eventDot(level: ExperimentEvent["level"]): string {
  if (level === "critical") return "bg-red-400";
  if (level === "warn") return "bg-orange-400";
  return "bg-sky-400";
}

function modeLabel(mode: FanMode): string {
  if (mode === "GPU_DEFAULT") return "GPU_DEFAULT";
  if (mode === "FIXED_0") return "GPU_FAULT_0";
  if (mode === "FIXED_5") return "GPU_Fault_5";
  if (mode === "FIXED_15") return "GPU_Fault_15";
  if (mode === "FIXED_20") return "GPU_Fault_20";
  if (mode === "FIXED_25") return "GPU_Fault_25";
  if (mode === "GPU_MAX") return "GPU_Cool_Max";
  return "GPU_Cool_Max";
}

function modeFanPercent(mode: FanMode, fallbackPercent: number): number {
  if (mode === "GPU_DEFAULT") return fallbackPercent;
  if (mode === "FIXED_0") return 0;
  if (mode === "FIXED_5") return 5;
  if (mode === "FIXED_15") return 15;
  if (mode === "FIXED_20") return 20;
  if (mode === "GPU_MAX") return 100;
  return 25;
}

function phaseBadgeClass(state: ThermalDemoStep["state"]): string {
  if (state === "done") return "border-emerald-500/40 bg-emerald-500/10 text-emerald-200";
  if (state === "active") return "border-orange-500/40 bg-orange-500/10 text-orange-200";
  return "border-slate-700 bg-slate-900/60 text-slate-400";
}

function displayFanModeLabel(mode: FanMode): string {
  if (mode === "GPU_DEFAULT") return "Auto Cooling";
  if (mode === "FIXED_0") return "Fixed 0%";
  if (mode === "GPU_MAX") return "Max Cooling";
  return modeLabel(mode);
}

function formatObservedTimestamp(ts?: number | null): string {
  if (!ts) return "N/A";
  return new Date(ts * 1000).toLocaleString();
}

function formatReadyCondition(value?: boolean | null): string {
  if (value === undefined || value === null) return "Unknown";
  return value ? "True" : "False";
}

function runtimeBadge(runtime?: string | null): string {
  if (runtime === "llamacpp") return "llama.cpp";
  if (runtime === "vllm") return "vLLM";
  return runtime || "runtime";
}

function isOfflineHistoryEvent(item: LlmRunHistoryItem): boolean {
  return (
    item.event_type === "offline_throughput_benchmark" ||
    item.event_type === "llamacpp_offline_benchmark"
  );
}

function offlineProfileRunMode(profile?: LlamacppOfflineBenchmarkProfile | null): string {
  if (!profile) return "N/A";
  if (profile.profile_id === "pascal-continuous") {
    return "Repeated offline benchmark with live progress";
  }
  return "Fixed repetition-count benchmark";
}

function observationLine(label: string, value: string) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="text-slate-400">{label}</div>
      <div className="text-right font-mono text-slate-200">{value}</div>
    </div>
  );
}

function MetricBar({
  label,
  value,
  suffix = "%",
}: {
  label: string;
  value?: number | null;
  suffix?: string;
}) {
  const p = clampPercent(value);

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-400">{label}</span>
        <span className="font-mono text-slate-200">
          {value === undefined || value === null ? "N/A" : `${p.toFixed(1)}${suffix}`}
        </span>
      </div>
      <div className="h-2 rounded-full bg-slate-800">
        <div
          className={`h-2 rounded-full ${
            p >= 90 ? "bg-orange-500" : p >= 75 ? "bg-yellow-500" : "bg-sky-500"
          }`}
          style={{ width: `${p}%` }}
        />
      </div>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  tone = "blue",
  compact = false,
}: {
  label: string;
  value: string;
  tone?: "blue" | "green" | "orange" | "gray";
  compact?: boolean;
}) {
  const toneClass =
    tone === "green"
      ? "text-emerald-300 border-emerald-500/30"
      : tone === "orange"
        ? "text-orange-300 border-orange-500/30"
        : tone === "gray"
          ? "text-slate-300 border-slate-600/40"
          : "text-sky-300 border-sky-500/30";

  return (
    <div
      className={`rounded-2xl border bg-slate-950/70 shadow-lg ${toneClass} ${
        compact ? "p-3" : "p-4"
      }`}
    >
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-2 font-mono font-semibold ${compact ? "text-xl" : "text-2xl"}`}>{value}</div>
    </div>
  );
}

function SectionCard({
  title,
  children,
  action,
}: {
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5 shadow-lg">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-sky-300">
          {title}
        </h3>
        {action}
      </div>
      {children}
    </div>
  );
}

function NodeCard({
  node,
  selected,
  onClick,
}: {
  node: NodeView;
  selected: boolean;
  onClick: () => void;
}) {
  const inv = node.inventory;
  const st = node.status;
  const gpuModel = inv.gpu?.models?.[0] || "No GPU / Unknown";
  const cpuName =
    inv.cpu?.model_name ||
    `${inv.cpu?.vendor || "CPU"} / ${inv.cpu?.cores_total || "-"} cores`;

  return (
    <button
      onClick={onClick}
      className={`rounded-2xl border bg-slate-950/70 p-4 text-left shadow-lg transition hover:border-sky-400/70 hover:bg-slate-900/80 ${
        selected ? "border-sky-400" : healthClass(node.health)
      }`}
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="text-base font-semibold text-slate-100">
            {inv.node_name}
          </div>
          <div className="mt-1 text-xs text-slate-400">
            {inv.role} / {inv.k8s_ip}
          </div>
        </div>

        <div className="flex items-center gap-2 rounded-full border border-slate-700 px-2 py-1 text-xs uppercase">
          <span className={`h-2 w-2 rounded-full ${healthDot(node.health)}`} />
          <span className={healthClass(node.health)}>{node.health}</span>
        </div>
      </div>

      <div className="mb-4 space-y-1 text-xs text-slate-400">
        <div>CPU: {cpuName}</div>
        <div>GPU: {gpuModel}</div>
      </div>

      <div className="space-y-3">
        <MetricBar label="CPU" value={st?.cpu?.usage_percent} />
        <MetricBar label="Memory" value={st?.memory?.usage_percent} />
        <MetricBar label="Disk" value={st?.disk?.root_usage_percent} />

        <div className="flex items-center justify-between text-xs">
          <span className="text-slate-400">GPU VRAM Used</span>
          <span className="font-mono text-slate-200">
            {st?.gpu?.fb_used_mib !== undefined && st?.gpu?.fb_used_mib !== null
              ? `${st.gpu.fb_used_mib.toFixed(0)} MiB`
              : "N/A"}
          </span>
        </div>
      </div>
    </button>
  );
}

function MultiLineChart({
  title,
  data,
  lines,
  unit,
  xKey = "time",
  height = 180,
  yDomain,
}: {
  title: string;
  data: ChartPoint[];
  lines: {
    key: string;
    name: string;
    stroke: string;
  }[];
  unit?: string;
  xKey?: string;
  height?: number;
  yDomain?: [number | "auto", number | "auto"];
}) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-sky-300">{title}</h3>
        <span className="text-xs text-slate-500">Last {data.length} samples</span>
      </div>

      <div style={{ height }}>
        {data.length < 2 ? (
          <div className="flex h-full items-center justify-center text-sm text-slate-500">
            Waiting for samples...
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis
                dataKey={xKey}
                tick={{ fill: "#94a3b8", fontSize: 10 }}
                minTickGap={24}
              />
              <YAxis
                tick={{ fill: "#94a3b8", fontSize: 10 }}
                width={42}
                domain={yDomain}
              />
              <Tooltip
                contentStyle={{
                  background: "#020617",
                  border: "1px solid #334155",
                  borderRadius: "8px",
                  color: "#e5e7eb",
                }}
                formatter={(value, name) => [
                  `${Number(value ?? 0).toFixed(1)}${unit || ""}`,
                  name,
                ]}
              />
              {lines.map((line) => (
                <Line
                  key={line.key}
                  type="monotone"
                  dataKey={line.key}
                  name={line.name}
                  stroke={line.stroke}
                  dot={false}
                  strokeWidth={2}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}

function NodeDetail({
  node,
  history,
}: {
  node?: NodeView;
  history: HistoryPoint[];
}) {
  if (!node) {
    return (
      <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-6 text-slate-400">
        Select a node to view details.
      </div>
    );
  }

  const inv = node.inventory;
  const st = node.status;
  const cpuName =
    inv.cpu?.model_name ||
    `${inv.cpu?.vendor || "CPU"} / ${inv.cpu?.cores_total || "-"} cores`;

  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-6 shadow-lg">
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-slate-100">
            Selected Node Detail
          </h2>
          <p className="mt-1 text-sm text-slate-400">
            {inv.node_name} / {inv.role} / {inv.k8s_ip}
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-full border border-slate-700 px-3 py-1 text-sm uppercase">
          <span className={`h-2 w-2 rounded-full ${healthDot(node.health)}`} />
          <span className={healthClass(node.health)}>{node.health}</span>
        </div>
      </div>

      <div className="grid gap-4">
        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          <h3 className="mb-3 text-sm font-semibold text-sky-300">Basic Info</h3>
          <div className="space-y-2 text-sm text-slate-300">
            <div>OS: {inv.os?.image || "N/A"}</div>
            <div>Kernel: {inv.os?.kernel_version || "N/A"}</div>
            <div>Runtime: {inv.os?.container_runtime || "N/A"}</div>
            <div>CPU: {cpuName}</div>
            <div>Memory: {inv.memory?.total_memory || "N/A"}</div>
            <div>GPU: {inv.gpu?.models?.join(", ") || "N/A"}</div>
          </div>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          <h3 className="mb-3 text-sm font-semibold text-sky-300">Resource Metrics</h3>
          <div className="space-y-4">
            <MetricBar label="CPU Usage" value={st?.cpu?.usage_percent} />
            <MetricBar label="Memory Usage" value={st?.memory?.usage_percent} />
            <MetricBar label="Disk Root Usage" value={st?.disk?.root_usage_percent} />
          </div>
        </div>
        <div className="grid gap-4">
          <MultiLineChart
            title="CPU / Memory / Disk Usage"
            data={history}
            unit="%"
            lines={[
              { key: "cpu", name: "CPU", stroke: "#38bdf8" },
              { key: "memory", name: "Memory", stroke: "#22c55e" },
              { key: "disk", name: "Disk", stroke: "#facc15" },
            ]}
          />

          <MultiLineChart
            title="GPU VRAM Used"
            data={history}
            unit=" MiB"
            lines={[
              { key: "gpuFbUsed", name: "GPU VRAM Used", stroke: "#a78bfa" },
            ]}
          />
        </div>
      </div>
    </div>
  );
}

function LlmServingLabPage({
  workloads,
  workloadDetails,
  onRefreshWorkloads,
}: {
  workloads: WorkloadListItem[];
  workloadDetails: Record<string, WorkloadStatusResponse>;
  onRefreshWorkloads: () => Promise<void>;
}) {
  const [prompt, setPrompt] = useState("Explain CPU, RAM, and GPU VRAM in three bullet points.");
  const [maxTokens, setMaxTokens] = useState(128);
  const [temperature, setTemperature] = useState(0);
  const [inferenceLoading, setInferenceLoading] = useState(false);
  const [inferenceError, setInferenceError] = useState("");
  const [inferenceResult, setInferenceResult] = useState<LlmInferenceResponse | null>(null);
  const [inferenceStartedAt, setInferenceStartedAt] = useState<number | null>(null);
  const [smokeLoading, setSmokeLoading] = useState(false);
  const [smokeError, setSmokeError] = useState("");
  const [smokeResult, setSmokeResult] = useState<LlmSmokeBenchmarkResponse | null>(null);
  const [activeBenchmarkRun, setActiveBenchmarkRun] = useState<LlmBenchmarkRunStatusResponse | null>(null);
  const [activeBenchmarkRunId, setActiveBenchmarkRunId] = useState("");
  const [benchmarkProfileId, setBenchmarkProfileId] = useState<(typeof BENCHMARK_PROFILES)[number]["id"]>("smoke");
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [runHistory, setRunHistory] = useState<LlmRunHistoryItem[]>([]);
  const [historyFilter, setHistoryFilter] = useState<"all" | "inference" | "serving" | "offline">("all");
  const sortedWorkloads = [...workloads].sort((a, b) => {
    const left = `${a.namespace}/${a.workload}`;
    const right = `${b.namespace}/${b.workload}`;
    return left.localeCompare(right);
  });

  const primaryWorkload = sortedWorkloads[0] || null;
  const primaryKey = primaryWorkload
    ? `${primaryWorkload.namespace}/${primaryWorkload.workload}`
    : "";
  const primaryDetail = primaryKey ? workloadDetails[primaryKey] || null : null;
  const selectedBenchmarkProfile =
    BENCHMARK_PROFILES.find((profile) => profile.id === benchmarkProfileId) || BENCHMARK_PROFILES[0];
  const shouldHideContinuousPercentiles = smokeResult?.profile_id === "continuous";
  const filteredRunHistory = runHistory.filter((item) => {
    if (historyFilter === "all") return true;
    if (historyFilter === "inference") {
      return item.event_type === "single_inference";
    }
    if (historyFilter === "serving") {
      return item.event_type === "serving_benchmark" || item.event_type === "controlled_batch";
    }
    return (
      item.event_type === "offline_throughput_benchmark" ||
      item.event_type === "llamacpp_offline_benchmark"
    );
  });
  const visibleRunHistory = filteredRunHistory.slice(0, 5);
  const historySummary = {
    total: visibleRunHistory.length,
    inferenceCount: filteredRunHistory.filter((item) => item.event_type === "single_inference").length,
    benchmarkCount: filteredRunHistory.filter((item) => item.event_type !== "single_inference").length,
  };

  async function runInference() {
    if (!primaryWorkload) return;
    setInferenceLoading(true);
    setInferenceError("");
    setInferenceResult(null);
    setInferenceStartedAt(Date.now());
    onRefreshWorkloads().catch(() => undefined);
    try {
      const response = await postJsonBody<LlmInferenceResponse>(
        "/api/v1/llm-lab/inference",
        {
          namespace: primaryWorkload.namespace,
          workload: primaryWorkload.workload,
          prompt,
          max_tokens: maxTokens,
          temperature,
        } satisfies LlmInferenceRequest,
      );
      setInferenceResult(response);
      await onRefreshWorkloads();
      await loadRunHistory(primaryWorkload.namespace);
    } catch (error) {
      setInferenceError(error instanceof Error ? error.message : String(error));
    } finally {
      setInferenceLoading(false);
    }
  }

  async function loadBenchmarkRun(runId: string) {
    const response = await fetchJson<LlmBenchmarkRunStatusResponse>(
      `/api/v1/llm-lab/benchmarks/runs/${encodeURIComponent(runId)}`,
    );
    setActiveBenchmarkRun(response);
    if (response.result) {
      setSmokeResult(response.result);
    }
    if (response.status !== "queued" && response.status !== "running" && response.status !== "cancelling") {
      setActiveBenchmarkRunId("");
      await loadRunHistory(response.namespace);
    }
    return response;
  }

  async function runSmokeBenchmark() {
    if (!primaryWorkload) return;
    setSmokeLoading(true);
    setSmokeError("");
    setSmokeResult(null);
    setActiveBenchmarkRun(null);
    try {
      const response = await postJsonBody<LlmBenchmarkRunStartResponse>(
        "/api/v1/llm-lab/benchmarks/runs",
        {
          namespace: primaryWorkload.namespace,
          workload: primaryWorkload.workload,
          profile_id: benchmarkProfileId,
        } satisfies LlmBenchmarkRunRequest,
      );
      setActiveBenchmarkRunId(response.run_id);
      await loadBenchmarkRun(response.run_id);
    } catch (error) {
      setSmokeError(error instanceof Error ? error.message : String(error));
    } finally {
      setSmokeLoading(false);
    }
  }

  async function cancelBenchmarkRun() {
    if (!activeBenchmarkRunId) return;
    setSmokeError("");
    try {
      await postJsonBody<LlmBenchmarkRunCancelResponse>(
        `/api/v1/llm-lab/benchmarks/runs/${encodeURIComponent(activeBenchmarkRunId)}/cancel`,
        {},
      );
      await loadBenchmarkRun(activeBenchmarkRunId);
    } catch (error) {
      setSmokeError(error instanceof Error ? error.message : String(error));
    }
  }

  async function loadRunHistory(namespace?: string, workload?: string) {
    setHistoryLoading(true);
    setHistoryError("");
    try {
      const params = new URLSearchParams();
      if (namespace) params.set("namespace", namespace);
      if (workload) params.set("workload", workload);
      params.set("limit", "5");
      const response = await fetchJson<LlmRunHistoryResponse>(
        `/api/v1/llm-lab/history?${params.toString()}`,
      );
      setRunHistory(response.items || []);
    } catch (error) {
      setHistoryError(error instanceof Error ? error.message : String(error));
    } finally {
      setHistoryLoading(false);
    }
  }

  useEffect(() => {
    if (!primaryWorkload) {
      loadRunHistory().catch(() => undefined);
      return;
    }
    loadRunHistory(primaryWorkload.namespace).catch(() => undefined);
  }, [primaryKey]);

  useEffect(() => {
    if (!activeBenchmarkRunId) return;
    const timer = window.setInterval(() => {
      loadBenchmarkRun(activeBenchmarkRunId).catch(() => undefined);
    }, 2000);
    loadBenchmarkRun(activeBenchmarkRunId).catch(() => undefined);
    return () => window.clearInterval(timer);
  }, [activeBenchmarkRunId]);

  return (
    <section className="space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-100">LLM Serving Lab</h2>
        <p className="mt-1 text-sm text-slate-400">
          Runtime observation and controlled benchmarking across vLLM serving and llama.cpp offline execution
        </p>
        {sortedWorkloads.length > 1 && primaryWorkload && (
          <div className="mt-4 rounded-xl border border-amber-500/30 bg-amber-950/20 p-3 text-sm text-amber-100">
            Multiple vLLM workloads detected; showing{" "}
            <span className="font-mono">
              {primaryWorkload.namespace}/{primaryWorkload.workload}
            </span>
            .
          </div>
        )}
      </div>

      <div className="space-y-2">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-sky-200">
            Observation
          </h3>
          <p className="mt-1 text-sm text-slate-400">
            Runtime and Kubernetes observation for the active vLLM serving workload.
          </p>
        </div>
      </div>

      {primaryWorkload && (
        <div className="space-y-4">
          <SectionCard title="Replica / Kubernetes Observation">
            {!primaryDetail ? (
              <div className="rounded-xl border border-dashed border-slate-700 bg-slate-950/40 p-4 text-sm text-slate-400">
                No replica detail available.
              </div>
            ) : (
              <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/45">
                <table className="min-w-full text-sm">
                  <thead className="bg-slate-950/60 text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-3 py-3 text-left font-medium">Pod</th>
                      <th className="px-3 py-3 text-left font-medium">Node</th>
                      <th className="px-3 py-3 text-left font-medium">Phase</th>
                      <th className="px-3 py-3 text-left font-medium">Ready</th>
                    </tr>
                  </thead>
                  <tbody>
                    {primaryDetail.replicas.map((replica) => (
                      <tr
                        key={`${primaryDetail.identity.namespace}/${primaryDetail.identity.workload}/${replica.pod}`}
                        className="border-t border-slate-800 text-slate-200"
                      >
                        <td className="px-3 py-3 font-mono text-xs">{replica.pod}</td>
                        <td className="px-3 py-3">{replica.node_name || "N/A"}</td>
                        <td className="px-3 py-3">{replica.pod_phase || "Unknown"}</td>
                        <td className="px-3 py-3">{formatReadyCondition(replica.ready_condition)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </SectionCard>
        </div>
      )}

      {primaryWorkload && (
        <div className="space-y-2 pt-2">
          <div>
            <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-emerald-200">
              Tasks & Runs
            </h3>
            <p className="mt-1 text-sm text-slate-400">
              Controlled requests and recent runtime records for this vLLM workload.
            </p>
          </div>
        </div>
      )}

      {primaryWorkload && (
        <SectionCard title="Single Inference">
          <div className="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
            <div className="space-y-4">
              <label className="block text-sm text-slate-300">
                <div className="mb-2 text-xs uppercase tracking-wide text-slate-500">
                  Prompt
                </div>
                <textarea
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  rows={7}
                  maxLength={8192}
                  className="w-full rounded-xl border border-slate-700 bg-slate-950/70 px-3 py-3 text-sm text-slate-100 outline-none transition focus:border-sky-500/60"
                />
              </label>

              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block text-sm text-slate-300">
                  <div className="mb-2 text-xs uppercase tracking-wide text-slate-500">
                    Max Output Tokens
                  </div>
                  <input
                    type="number"
                    min={1}
                    max={512}
                    value={maxTokens}
                    onChange={(event) => setMaxTokens(Number(event.target.value) || 1)}
                    className="w-full rounded-xl border border-slate-700 bg-slate-950/70 px-3 py-2.5 text-sm text-slate-100 outline-none transition focus:border-sky-500/60"
                  />
                </label>

                <label className="block text-sm text-slate-300">
                  <div className="mb-2 text-xs uppercase tracking-wide text-slate-500">
                    Temperature
                  </div>
                  <input
                    type="number"
                    min={0}
                    max={2}
                    step={0.1}
                    value={temperature}
                    onChange={(event) => setTemperature(Number(event.target.value) || 0)}
                    className="w-full rounded-xl border border-slate-700 bg-slate-950/70 px-3 py-2.5 text-sm text-slate-100 outline-none transition focus:border-sky-500/60"
                  />
                </label>
              </div>

              <div className="flex items-center gap-3">
                <button
                  onClick={() => {
                    runInference().catch(() => undefined);
                  }}
                  disabled={
                    inferenceLoading ||
                    !primaryDetail ||
                    primaryDetail.replica_summary.ready <= 0 ||
                    prompt.trim().length === 0
                  }
                  className={`rounded-xl border px-4 py-2.5 text-sm font-medium transition ${
                    inferenceLoading
                      ? "border-slate-700 bg-slate-900/60 text-slate-500"
                      : "border-sky-500/40 bg-sky-500/15 text-sky-100 hover:border-sky-400"
                  }`}
                >
                  {inferenceLoading ? "Running..." : "Run Inference"}
                </button>
                <div className="text-xs text-slate-500">
                  Sends one controlled request through `autoscale_api`.
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900/45 p-4 text-sm">
              {inferenceLoading ? (
                <div className="rounded-xl border border-sky-500/30 bg-sky-950/20 p-4 text-sky-100">
                  <div className="font-medium">Inference request in progress</div>
                  <div className="mt-2 text-sm text-sky-200/80">
                    Request sent through `autoscale_api`. The result panel will refresh when the response returns.
                  </div>
                  <div className="mt-3 text-xs text-sky-200/70">
                    Started: {inferenceStartedAt ? new Date(inferenceStartedAt).toLocaleTimeString() : "now"}
                  </div>
                </div>
              ) : !inferenceResult && !inferenceError ? (
                <div className="text-slate-400">
                  Run a single inference request to capture token usage, latency,
                  and finish reason.
                </div>
              ) : inferenceError ? (
                <div className="rounded-xl border border-red-500/30 bg-red-950/20 p-3 text-red-200">
                  {inferenceError}
                </div>
              ) : (
                <div className="space-y-4">
                  <div className="space-y-2">
                    {observationLine("HTTP Status", String(inferenceResult?.http_status ?? "N/A"))}
                    {observationLine(
                      "Prompt Tokens",
                      inferenceResult?.prompt_tokens?.toString() || "N/A",
                    )}
                    {observationLine(
                      "Completion Tokens",
                      inferenceResult?.completion_tokens?.toString() || "N/A",
                    )}
                    {observationLine(
                      "Total Tokens",
                      inferenceResult?.total_tokens?.toString() || "N/A",
                    )}
                    {observationLine(
                      "End-to-End Time",
                      inferenceResult ? `${inferenceResult.latency_seconds.toFixed(3)} sec` : "N/A",
                    )}
                    {observationLine(
                      "Finish Reason",
                      inferenceResult?.finish_reason || "N/A",
                    )}
                    {observationLine(
                      "Target Service",
                      inferenceResult?.target_service || "N/A",
                    )}
                  </div>

                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                    <div className="mb-2 text-xs uppercase tracking-wide text-slate-500">
                      Response Text
                    </div>
                    <div className="whitespace-pre-wrap text-sm text-slate-200">
                      {inferenceResult?.response_text || "N/A"}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </SectionCard>
      )}

      {primaryWorkload && (
        <SectionCard title="Serving Benchmark">
          <div className="grid gap-6 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
            <div className="space-y-4">
              <label className="block text-sm text-slate-300">
                <div className="mb-2 text-xs uppercase tracking-wide text-slate-500">
                  Benchmark Profile
                </div>
                <select
                  value={benchmarkProfileId}
                  onChange={(event) =>
                    setBenchmarkProfileId(
                      event.target.value as (typeof BENCHMARK_PROFILES)[number]["id"],
                    )
                  }
                  className="w-full rounded-xl border border-slate-700 bg-slate-950/70 px-3 py-2.5 text-sm text-slate-100 outline-none transition focus:border-sky-500/60"
                >
                  {BENCHMARK_PROFILES.map((profile) => (
                    <option key={profile.id} value={profile.id}>
                      {profile.label}
                    </option>
                  ))}
                </select>
              </label>

              <div className="rounded-xl border border-slate-800 bg-slate-900/45 p-4 text-sm">
                <div className="mb-3 text-xs uppercase tracking-wide text-slate-500">
                  Selected Profile
                </div>
                <div className="space-y-2">
                  {observationLine("Profile", selectedBenchmarkProfile.label)}
                  {observationLine("Benchmark Engine", "vllm bench serve")}
                  {observationLine("Prompt Source", selectedBenchmarkProfile.promptSource)}
                  {observationLine("Max Output Tokens", String(selectedBenchmarkProfile.maxTokens))}
                  {observationLine("Temperature", selectedBenchmarkProfile.temperature.toFixed(1))}
                  {observationLine("Concurrency", String(selectedBenchmarkProfile.concurrency))}
                  {observationLine("Request Count", String(selectedBenchmarkProfile.requestCount))}
                  {selectedBenchmarkProfile.id === "continuous"
                    ? observationLine("Run Mode", "Runs until Stop or 30 min safety limit")
                    : observationLine("Run Mode", "Fixed request-count benchmark")}
                </div>
              </div>

              <button
                onClick={() => {
                  runSmokeBenchmark().catch(() => undefined);
                }}
                disabled={
                  smokeLoading ||
                  !!activeBenchmarkRunId ||
                  !primaryDetail ||
                  primaryDetail.replica_summary.ready <= 0
                }
                className={`rounded-xl border px-4 py-2.5 text-sm font-medium transition ${
                  smokeLoading
                    ? "border-slate-700 bg-slate-900/60 text-slate-500"
                    : "border-emerald-500/40 bg-emerald-500/15 text-emerald-100 hover:border-emerald-400"
                }`}
              >
                {smokeLoading ? "Running Benchmark..." : "Start Benchmark"}
              </button>
              {activeBenchmarkRunId ? (
                <button
                  onClick={() => {
                    cancelBenchmarkRun().catch(() => undefined);
                  }}
                  className="ml-3 rounded-xl border border-rose-500/40 bg-rose-500/10 px-4 py-2.5 text-sm font-medium text-rose-100 transition hover:border-rose-400"
                >
                  Cancel Run
                </button>
              ) : null}
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900/45 p-4 text-sm">
              {!activeBenchmarkRun && !smokeResult && !smokeError ? (
                <div className="text-slate-400">
                  Runs the official `vllm bench serve` benchmark against this live serving endpoint.
                </div>
              ) : smokeError ? (
                <div className="rounded-xl border border-red-500/30 bg-red-950/20 p-3 text-red-200">
                  {smokeError}
                </div>
              ) : (
                <div className="space-y-4">
                  {activeBenchmarkRun ? (
                    <div className="rounded-xl border border-slate-800 bg-slate-950/55 p-4">
                      <div className="mb-3 text-xs uppercase tracking-wide text-slate-500">
                        Live Benchmark Progress
                      </div>
                      <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                        <SummaryCard
                          label="Status"
                          value={activeBenchmarkRun.status}
                          tone={
                            activeBenchmarkRun.status === "running"
                              ? "green"
                              : activeBenchmarkRun.status === "cancelled"
                                ? "orange"
                                : "blue"
                          }
                        />
                        <SummaryCard
                          label="Current Prompt-only TPS"
                          value={`${activeBenchmarkRun.progress.current_prompt_tps.toFixed(1)} tok/s`}
                          tone="blue"
                        />
                        <SummaryCard
                          label="Current Generation-only TPS"
                          value={`${activeBenchmarkRun.progress.current_generation_tps.toFixed(1)} tok/s`}
                          tone="blue"
                        />
                        <SummaryCard
                          label="Current Total TPS"
                          value={`${activeBenchmarkRun.progress.current_total_tps.toFixed(1)} tok/s`}
                          tone="green"
                        />
                      </div>
                      <div className="space-y-2">
                        {observationLine("Active Run ID", activeBenchmarkRun.run_id)}
                        {observationLine(
                          "Elapsed",
                          `${activeBenchmarkRun.progress.elapsed_seconds.toFixed(1)} sec`,
                        )}
                        {observationLine(
                          "Completed Requests",
                          activeBenchmarkRun.progress.completed_requests.toString(),
                        )}
                        {observationLine(
                          "Failed Requests",
                          activeBenchmarkRun.progress.failed_requests.toString(),
                        )}
                        {observationLine(
                          "Prompt Tokens So Far",
                          activeBenchmarkRun.progress.prompt_tokens_so_far.toFixed(1),
                        )}
                        {observationLine(
                          "Completion Tokens So Far",
                          activeBenchmarkRun.progress.completion_tokens_so_far.toFixed(1),
                        )}
                        {observationLine(
                          "Total Tokens So Far",
                          activeBenchmarkRun.progress.total_tokens_so_far.toFixed(1),
                        )}
                        {observationLine(
                          "Current Request Throughput",
                          `${activeBenchmarkRun.progress.current_request_throughput_rps.toFixed(2)} req/s`,
                        )}
                      </div>
                      <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                        <div className="mb-3 text-sm font-medium text-slate-200">Per-Second Token Throughput</div>
                        <div className="h-64">
                        <ResponsiveContainer width="100%" height="100%">
                          <LineChart data={activeBenchmarkRun.progress.buckets}>
                            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                            <XAxis dataKey="second" tick={{ fill: "#94a3b8", fontSize: 12 }}>
                              <Label
                                value="Elapsed Time (sec)"
                                position="insideBottom"
                                offset={-4}
                                fill="#94a3b8"
                                fontSize={12}
                              />
                            </XAxis>
                            <YAxis tick={{ fill: "#94a3b8", fontSize: 12 }}>
                              <Label
                                value="Throughput (tokens/s)"
                                angle={-90}
                                position="insideLeft"
                                fill="#94a3b8"
                                fontSize={12}
                                style={{ textAnchor: "middle" }}
                              />
                            </YAxis>
                            <Tooltip />
                            <Line
                              type="monotone"
                              dataKey="prompt_tokens"
                              stroke="#38bdf8"
                              strokeWidth={2}
                              dot={false}
                              name="Prompt Tokens/s"
                            />
                            <Line
                              type="monotone"
                              dataKey="completion_tokens"
                              stroke="#34d399"
                              strokeWidth={2}
                              dot={false}
                              name="Completion Tokens/s"
                            />
                            <Line
                              type="monotone"
                              dataKey="total_tokens"
                              stroke="#f59e0b"
                              strokeWidth={2}
                              dot={false}
                              name="Total Tokens/s"
                            />
                          </LineChart>
                        </ResponsiveContainer>
                      </div>
                      </div>
                    </div>
                  ) : null}

                  {activeBenchmarkRun &&
                  ["queued", "running", "cancelling"].includes(activeBenchmarkRun.status) &&
                  !smokeResult ? (
                    <div className="rounded-xl border border-amber-500/30 bg-amber-950/20 p-4 text-amber-100">
                      <div className="text-sm font-medium">
                        Final Summary available after stop/completion
                      </div>
                      <div className="mt-2 text-sm text-amber-200/80">
                        This section is populated when the benchmark reaches a terminal state
                        (`succeeded`, `cancelled`, or `failed`).
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {observationLine("Profile", smokeResult?.profile || "N/A")}
                      {observationLine("Run ID", smokeResult?.run_id || "N/A")}
                      {observationLine("Status", smokeResult?.status || "N/A")}
                      {observationLine(
                        "Completed Requests",
                        smokeResult?.completed_requests?.toString() || "0",
                      )}
                      {observationLine(
                        "Failed Requests",
                        smokeResult?.failed_requests?.toString() || "0",
                      )}
                      {observationLine(
                        "Concurrency",
                        smokeResult?.concurrency?.toString() || "N/A",
                      )}
                      {observationLine(
                        "Run Elapsed",
                        smokeResult?.run_elapsed_seconds !== undefined &&
                          smokeResult?.run_elapsed_seconds !== null
                          ? `${smokeResult.run_elapsed_seconds.toFixed(3)} sec`
                          : "N/A",
                      )}
                      {observationLine(
                        "Request Throughput",
                        smokeResult?.request_throughput_rps !== undefined &&
                          smokeResult?.request_throughput_rps !== null
                          ? `${smokeResult.request_throughput_rps.toFixed(3)} req/s`
                          : "N/A",
                      )}
                      {observationLine(
                        "Aggregate Prompt Throughput",
                        smokeResult?.aggregate_prompt_tps !== undefined &&
                          smokeResult?.aggregate_prompt_tps !== null
                          ? `${smokeResult.aggregate_prompt_tps.toFixed(3)} tok/s`
                          : "N/A",
                      )}
                      {observationLine(
                        "Aggregate Generation Throughput",
                        smokeResult?.aggregate_generation_tps !== undefined &&
                          smokeResult?.aggregate_generation_tps !== null
                          ? `${smokeResult.aggregate_generation_tps.toFixed(3)} tok/s`
                          : "N/A",
                      )}
                      {observationLine(
                        "Aggregate Total Throughput",
                        smokeResult?.aggregate_total_tps !== undefined &&
                          smokeResult?.aggregate_total_tps !== null
                          ? `${smokeResult.aggregate_total_tps.toFixed(3)} tok/s`
                          : "N/A",
                      )}
                      {!shouldHideContinuousPercentiles &&
                        observationLine(
                          "Latency P50",
                          smokeResult?.latency_p50_seconds !== undefined &&
                            smokeResult?.latency_p50_seconds !== null
                            ? `${smokeResult.latency_p50_seconds.toFixed(3)} sec`
                            : "N/A",
                        )}
                      {!shouldHideContinuousPercentiles &&
                        observationLine(
                          "Latency P95",
                          smokeResult?.latency_p95_seconds !== undefined &&
                            smokeResult?.latency_p95_seconds !== null
                            ? `${smokeResult.latency_p95_seconds.toFixed(3)} sec`
                            : "N/A",
                        )}
                      {observationLine(
                        "Mean Latency",
                        smokeResult?.mean_latency_seconds !== undefined &&
                          smokeResult?.mean_latency_seconds !== null
                          ? `${smokeResult.mean_latency_seconds.toFixed(3)} sec`
                          : "N/A",
                      )}
                      {observationLine(
                        "Mean Prompt Tokens",
                        smokeResult?.mean_prompt_tokens?.toFixed(1) || "N/A",
                      )}
                      {observationLine(
                        "Mean Completion Tokens",
                        smokeResult?.mean_completion_tokens?.toFixed(1) || "N/A",
                      )}
                      {observationLine(
                        "Mean Total Tokens",
                        smokeResult?.mean_total_tokens?.toFixed(1) || "N/A",
                      )}
                      {observationLine(
                        "Mean TTFT",
                        smokeResult?.mean_ttft_seconds !== undefined &&
                          smokeResult?.mean_ttft_seconds !== null
                          ? `${smokeResult.mean_ttft_seconds.toFixed(3)} sec`
                          : "N/A",
                      )}
                      {!shouldHideContinuousPercentiles &&
                        observationLine(
                          "P95 TTFT",
                          smokeResult?.p95_ttft_seconds !== undefined &&
                            smokeResult?.p95_ttft_seconds !== null
                            ? `${smokeResult.p95_ttft_seconds.toFixed(3)} sec`
                            : "N/A",
                        )}
                      {observationLine(
                        "Mean TPOT",
                        smokeResult?.mean_tpot_seconds !== undefined &&
                          smokeResult?.mean_tpot_seconds !== null
                          ? `${smokeResult.mean_tpot_seconds.toFixed(4)} sec`
                          : "N/A",
                      )}
                      {!shouldHideContinuousPercentiles &&
                        observationLine(
                          "P95 TPOT",
                          smokeResult?.p95_tpot_seconds !== undefined &&
                            smokeResult?.p95_tpot_seconds !== null
                            ? `${smokeResult.p95_tpot_seconds.toFixed(4)} sec`
                            : "N/A",
                        )}
                      {observationLine(
                        "Mean ITL",
                        smokeResult?.mean_itl_seconds !== undefined &&
                          smokeResult?.mean_itl_seconds !== null
                          ? `${smokeResult.mean_itl_seconds.toFixed(4)} sec`
                          : "N/A",
                      )}
                      {!shouldHideContinuousPercentiles &&
                        observationLine(
                          "P95 ITL",
                          smokeResult?.p95_itl_seconds !== undefined &&
                            smokeResult?.p95_itl_seconds !== null
                            ? `${smokeResult.p95_itl_seconds.toFixed(4)} sec`
                            : "N/A",
                        )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </SectionCard>
      )}

      {primaryWorkload && (
        <SectionCard title="Recent Runtime History">
          <div className="mb-4 text-sm text-slate-400">
            Unified recent records for single inference, vLLM serving benchmarks, and llama.cpp offline benchmarks.
          </div>
          <div className="mb-4 grid gap-4 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)]">
            <div className="grid gap-3 sm:grid-cols-3">
              <SummaryCard label="Visible Entries" value={historySummary.total.toString()} tone="blue" />
              <SummaryCard label="Inferences" value={historySummary.inferenceCount.toString()} tone="green" />
              <SummaryCard label="Benchmarks" value={historySummary.benchmarkCount.toString()} tone="orange" />
            </div>
            <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/45 p-3">
              {[
                { id: "all", label: "All Events" },
                { id: "inference", label: "Inference" },
                { id: "serving", label: "Serving" },
                { id: "offline", label: "Offline" },
              ].map((option) => (
                <button
                  key={option.id}
                  onClick={() => setHistoryFilter(option.id as "all" | "inference" | "serving" | "offline")}
                  className={`rounded-full border px-3 py-1.5 text-xs transition ${
                    historyFilter === option.id
                      ? "border-sky-500/40 bg-sky-500/20 text-sky-200"
                      : "border-slate-700 bg-slate-950/60 text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>

          {historyLoading && runHistory.length === 0 ? (
            <div className="text-sm text-slate-400">Loading run history...</div>
          ) : historyError ? (
            <div className="rounded-xl border border-red-500/30 bg-red-950/20 p-3 text-red-200">
              {historyError}
            </div>
          ) : visibleRunHistory.length === 0 ? (
            <div className="text-sm text-slate-400">
              No history entries match the current filter.
            </div>
          ) : (
            <div className="space-y-3">
              {visibleRunHistory.map((item) => (
                <div
                  key={`${item.ts}-${item.event_type}-${item.run_id || item.prompt_sha256 || "entry"}`}
                  className="rounded-xl border border-slate-800 bg-slate-900/45 p-4 text-sm"
                >
                  {(() => {
                    const isInference = item.event_type === "single_inference";
                    const isOffline = isOfflineHistoryEvent(item);
                    return (
                      <>
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <span
                        className={`rounded-full border px-2 py-0.5 text-[11px] uppercase tracking-wide ${
                          isInference
                            ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
                            : "border-orange-500/30 bg-orange-500/10 text-orange-200"
                        }`}
                      >
                        {isInference ? "Inference" : "Benchmark"}
                      </span>
                      <span className="rounded-full border border-slate-700 bg-slate-950/60 px-2 py-0.5 text-[11px] uppercase tracking-wide text-slate-300">
                        {runtimeBadge(item.runtime)}
                      </span>
                      <div className="font-medium text-slate-100">
                        {isInference
                          ? "Single Inference"
                          : item.profile || "Benchmark"}
                      </div>
                    </div>
                    <div className="text-xs text-slate-500">
                      {new Date(item.ts * 1000).toLocaleString()}
                    </div>
                  </div>
                  <div className="mb-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                    <div className="rounded-lg border border-slate-800 bg-slate-950/55 px-3 py-2">
                      <div className="text-[11px] uppercase tracking-wide text-slate-500">Status</div>
                      <div className="mt-1 text-sm text-slate-100">{item.status}</div>
                    </div>
                    <div className="rounded-lg border border-slate-800 bg-slate-950/55 px-3 py-2">
                      <div className="text-[11px] uppercase tracking-wide text-slate-500">
                        {isInference
                          ? "Latency"
                          : isOffline
                            ? "Prompt TPS"
                            : "Mean Latency"}
                      </div>
                      <div className="mt-1 text-sm text-slate-100">
                        {isInference
                          ? item.latency_seconds !== undefined && item.latency_seconds !== null
                            ? `${item.latency_seconds.toFixed(3)} sec`
                            : "N/A"
                          : isOffline
                            ? item.prompt_tps_mean !== undefined && item.prompt_tps_mean !== null
                              ? `${item.prompt_tps_mean.toFixed(3)} tok/s`
                              : "N/A"
                            : item.mean_latency_seconds !== undefined && item.mean_latency_seconds !== null
                            ? `${item.mean_latency_seconds.toFixed(3)} sec`
                            : "N/A"}
                      </div>
                    </div>
                    <div className="rounded-lg border border-slate-800 bg-slate-950/55 px-3 py-2">
                      <div className="text-[11px] uppercase tracking-wide text-slate-500">
                        {isInference
                          ? "Tokens"
                          : isOffline
                            ? "Generation TPS"
                            : "Requests"}
                      </div>
                      <div className="mt-1 text-sm text-slate-100">
                        {isInference
                          ? `${item.total_tokens ?? "N/A"} total`
                          : isOffline
                            ? item.generation_tps_mean !== undefined && item.generation_tps_mean !== null
                              ? `${item.generation_tps_mean.toFixed(3)} tok/s`
                              : "N/A"
                            : `${item.completed_requests ?? 0}/${item.request_count ?? 0}`}
                      </div>
                    </div>
                    <div className="rounded-lg border border-slate-800 bg-slate-950/55 px-3 py-2">
                      <div className="text-[11px] uppercase tracking-wide text-slate-500">
                        {isInference
                          ? "Finish Reason"
                          : isOffline
                            ? "GPU Preflight"
                            : "Profile"}
                      </div>
                      <div className="mt-1 text-sm text-slate-100">
                        {isInference
                          ? item.finish_reason || "N/A"
                          : isOffline
                            ? item.gpu_contended === null || item.gpu_contended === undefined
                              ? "N/A"
                              : item.gpu_contended
                                ? "Contended"
                                : "Idle"
                            : item.profile || "N/A"}
                      </div>
                    </div>
                  </div>
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="space-y-2">
                      {observationLine("Workload", `${item.namespace}/${item.workload}`)}
                      {item.run_id ? observationLine("Run ID", item.run_id) : null}
                      {isInference
                        ? observationLine(
                            "Latency",
                            item.latency_seconds !== undefined && item.latency_seconds !== null
                              ? `${item.latency_seconds.toFixed(3)} sec`
                              : "N/A",
                          )
                        : isOffline
                          ? observationLine(
                              "Observed At",
                              item.observed_at_ts ? formatObservedTimestamp(item.observed_at_ts) : "N/A",
                            )
                          : observationLine(
                            "Profile ID",
                            item.profile_id || "N/A",
                          )}
                    </div>
                    <div className="space-y-2">
                      {isInference ? (
                        <>
                          {observationLine(
                            "Prompt Chars",
                            item.prompt_char_count?.toString() || "N/A",
                          )}
                          {observationLine(
                            "Prompt SHA-256",
                            item.prompt_sha256 || "N/A",
                          )}
                          {observationLine("Prompt Tokens", item.prompt_tokens?.toString() || "N/A")}
                          {observationLine("Completion Tokens", item.completion_tokens?.toString() || "N/A")}
                          {observationLine("Finish Reason", item.finish_reason || "N/A")}
                        </>
                      ) : isOffline ? (
                        <>
                          {observationLine(
                            "End-to-End PG TPS",
                            item.prompt_generation_tps_mean !== undefined &&
                              item.prompt_generation_tps_mean !== null
                              ? `${item.prompt_generation_tps_mean.toFixed(3)} tok/s`
                              : "N/A",
                          )}
                          {observationLine(
                            "Run Duration",
                            item.duration_seconds !== undefined && item.duration_seconds !== null
                              ? `${item.duration_seconds.toFixed(3)} sec`
                              : "N/A",
                          )}
                          {observationLine(
                            "Prompt TPS Stddev",
                            item.prompt_tps_stddev !== undefined && item.prompt_tps_stddev !== null
                              ? `${item.prompt_tps_stddev.toFixed(3)} tok/s`
                              : "N/A",
                          )}
                          {observationLine(
                            "Generation TPS Stddev",
                            item.generation_tps_stddev !== undefined && item.generation_tps_stddev !== null
                              ? `${item.generation_tps_stddev.toFixed(3)} tok/s`
                              : "N/A",
                          )}
                        </>
                      ) : (
                        <>
                          {observationLine(
                            "Completed / Failed",
                            `${item.completed_requests ?? 0} / ${item.failed_requests ?? 0}`,
                          )}
                          {observationLine(
                            "Concurrency",
                            item.concurrency?.toString() || "N/A",
                          )}
                          {observationLine(
                            "Elapsed",
                            item.run_elapsed_seconds !== undefined &&
                              item.run_elapsed_seconds !== null
                              ? `${item.run_elapsed_seconds.toFixed(3)} sec`
                              : "N/A",
                          )}
                          {observationLine(
                            "Request Throughput",
                            item.request_throughput_rps !== undefined &&
                              item.request_throughput_rps !== null
                              ? `${item.request_throughput_rps.toFixed(3)} req/s`
                              : "N/A",
                          )}
                          {observationLine(
                            "Prompt Throughput",
                            item.aggregate_prompt_tps !== undefined &&
                              item.aggregate_prompt_tps !== null
                              ? `${item.aggregate_prompt_tps.toFixed(3)} tok/s`
                              : "N/A",
                          )}
                          {observationLine(
                            "Generation Throughput",
                            item.aggregate_generation_tps !== undefined &&
                              item.aggregate_generation_tps !== null
                              ? `${item.aggregate_generation_tps.toFixed(3)} tok/s`
                              : "N/A",
                          )}
                          {observationLine(
                            "Total Throughput",
                            item.aggregate_total_tps !== undefined &&
                              item.aggregate_total_tps !== null
                              ? `${item.aggregate_total_tps.toFixed(3)} tok/s`
                              : "N/A",
                          )}
                          {observationLine(
                            "Latency P50 / P95",
                            item.latency_p50_seconds !== undefined &&
                              item.latency_p50_seconds !== null &&
                              item.latency_p95_seconds !== undefined &&
                              item.latency_p95_seconds !== null
                              ? `${item.latency_p50_seconds.toFixed(3)} / ${item.latency_p95_seconds.toFixed(3)} sec`
                              : "N/A",
                          )}
                          {observationLine(
                            "Mean Prompt Tokens",
                            item.mean_prompt_tokens !== undefined && item.mean_prompt_tokens !== null
                              ? item.mean_prompt_tokens.toFixed(1)
                              : "N/A",
                          )}
                          {observationLine(
                            "Mean Completion Tokens",
                            item.mean_completion_tokens !== undefined &&
                              item.mean_completion_tokens !== null
                              ? item.mean_completion_tokens.toFixed(1)
                              : "N/A",
                          )}
                          {observationLine(
                            "Mean Total Tokens",
                            item.mean_total_tokens !== undefined && item.mean_total_tokens !== null
                              ? item.mean_total_tokens.toFixed(1)
                              : "N/A",
                          )}
                        </>
                      )}
                    </div>
                  </div>
                      </>
                    );
                  })()}
                </div>
              ))}
            </div>
          )}
        </SectionCard>
      )}
    </section>
  );
}

function OfflineHardwareBenchmarkSection({
  fanControlMode,
  fanControlAvailable,
  fanCycleRunning,
  onFanModeChange,
}: {
  fanControlMode: FanMode;
  fanControlAvailable: boolean;
  fanCycleRunning: boolean;
  onFanModeChange: (mode: FanMode) => void;
}) {
  const [offlineLoading, setOfflineLoading] = useState(false);
  const [offlineError, setOfflineError] = useState("");
  const [offlineProfiles, setOfflineProfiles] = useState<LlamacppOfflineBenchmarkProfile[]>([]);
  const [offlineLatestRun, setOfflineLatestRun] = useState<LlamacppOfflineBenchmarkRunStateResponse | null>(null);
  const [offlineActiveRunId, setOfflineActiveRunId] = useState("");
  const [offlineProfileId, setOfflineProfileId] = useState("pascal-smoke");

  const selectedOfflineProfile =
    offlineProfiles.find((profile) => profile.profile_id === offlineProfileId) || offlineProfiles[0] || null;
  const offlineLatestResult = offlineLatestRun?.result || null;
  const offlineRunInProgress =
    offlineLatestRun?.status === "queued" ||
    offlineLatestRun?.status === "running" ||
    offlineLatestRun?.status === "cancelling";

  async function loadOfflineProfiles() {
    const response = await fetchJson<LlamacppOfflineBenchmarkProfilesResponse>(
      "/api/v1/llm-lab/llamacpp/offline-benchmark/profiles",
    );
    setOfflineProfiles(response.profiles || []);
    if (!offlineProfileId && response.profiles?.[0]?.profile_id) {
      setOfflineProfileId(response.profiles[0].profile_id);
    }
  }

  async function loadOfflineLatestRun() {
    const response = await fetchJson<LlamacppOfflineBenchmarkRunStateResponse>(
      "/api/v1/llm-lab/llamacpp/offline-benchmark/runs/latest",
    );
    setOfflineLatestRun(response);
    if (response.status === "queued" || response.status === "running" || response.status === "cancelling") {
      setOfflineActiveRunId(response.run_id);
    } else if (offlineActiveRunId === response.run_id) {
      setOfflineActiveRunId("");
    }
    return response;
  }

  async function loadOfflineRun(runId: string) {
    const response = await fetchJson<LlamacppOfflineBenchmarkRunStateResponse>(
      `/api/v1/llm-lab/llamacpp/offline-benchmark/runs/${encodeURIComponent(runId)}`,
    );
    setOfflineLatestRun(response);
    if (response.status !== "queued" && response.status !== "running" && response.status !== "cancelling") {
      setOfflineActiveRunId("");
    }
    return response;
  }

  async function startOfflineThroughputBenchmark() {
    if (!selectedOfflineProfile) return;
    setOfflineLoading(true);
    setOfflineError("");
    try {
      const response = await postJsonBody<LlamacppOfflineBenchmarkRunStartResponse>(
        "/api/v1/llm-lab/llamacpp/offline-benchmark/runs",
        {
          profile: selectedOfflineProfile.profile_id,
        } satisfies LlamacppOfflineBenchmarkRunRequest,
      );
      setOfflineActiveRunId(response.run_id);
      await loadOfflineRun(response.run_id);
    } catch (error) {
      setOfflineError(error instanceof Error ? error.message : "Failed to run offline hardware benchmark.");
    } finally {
      setOfflineLoading(false);
    }
  }

  async function cancelOfflineThroughputBenchmark() {
    if (!offlineActiveRunId) return;
    setOfflineError("");
    try {
      await postJsonBody<LlamacppOfflineBenchmarkRunCancelResponse>(
        `/api/v1/llm-lab/llamacpp/offline-benchmark/runs/${encodeURIComponent(offlineActiveRunId)}/cancel`,
        {},
      );
      await loadOfflineRun(offlineActiveRunId);
    } catch (error) {
      setOfflineError(error instanceof Error ? error.message : "Failed to cancel offline benchmark.");
    }
  }

  useEffect(() => {
    loadOfflineProfiles().catch((error) => {
      setOfflineError(error instanceof Error ? error.message : String(error));
    });
    loadOfflineLatestRun().catch((error) => {
      if (!isNotFoundError(error)) {
        setOfflineError(error instanceof Error ? error.message : String(error));
      }
    });
  }, []);

  useEffect(() => {
    if (!offlineActiveRunId) return;
    const timer = window.setInterval(() => {
      loadOfflineRun(offlineActiveRunId).catch((error) => {
        setOfflineError(error instanceof Error ? error.message : String(error));
      });
    }, 2000);
    return () => window.clearInterval(timer);
  }, [offlineActiveRunId]);

  return (
    <SectionCard title="Offline Hardware Benchmark">
      <div className="mb-4">
        <div className="text-sm text-slate-300">llama.cpp · GTX 1080 Ti · Pascal SM61</div>
        <div className="mt-1 text-sm text-slate-400">Model: Gemma 4 E2B it · Q4_K_M</div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.82fr)_minmax(0,1.18fr)]">
        <div className="space-y-4">
          <label className="block text-sm text-slate-300">
            <span className="mb-2 block text-xs font-medium uppercase tracking-wide text-slate-400">
              Fixed Benchmark Profile
            </span>
            <select
              value={selectedOfflineProfile?.profile_id || ""}
              onChange={(event) => setOfflineProfileId(event.target.value)}
              disabled={offlineLoading || !!offlineActiveRunId}
              className="w-full rounded-xl border border-slate-700 bg-slate-950/70 px-4 py-3 text-sm text-slate-100 outline-none transition focus:border-sky-500/60 disabled:cursor-not-allowed disabled:text-slate-500"
            >
              {offlineProfiles.map((profile) => (
                <option key={profile.profile_id} value={profile.profile_id}>
                  {profile.display_name}
                </option>
              ))}
            </select>
          </label>

          <div className="rounded-xl border border-slate-800 bg-slate-900/45 p-4 text-sm">
            <div className="mb-3 text-xs font-medium uppercase tracking-wide text-slate-400">
              Selected Profile
            </div>
            <div className="space-y-2">
              {observationLine("Profile", selectedOfflineProfile?.display_name || "N/A")}
              {observationLine("Benchmark Engine", "llama-bench")}
              {observationLine("Prompt Tokens", selectedOfflineProfile ? String(selectedOfflineProfile.n_prompt) : "N/A")}
              {observationLine("Generation Tokens", selectedOfflineProfile ? String(selectedOfflineProfile.n_gen) : "N/A")}
              {observationLine("Context Depth", selectedOfflineProfile ? String(selectedOfflineProfile.n_depth) : "N/A")}
              {observationLine("Batch Size", selectedOfflineProfile ? String(selectedOfflineProfile.batch_size) : "N/A")}
              {observationLine(
                "Repetitions",
                selectedOfflineProfile
                  ? selectedOfflineProfile.profile_id === "pascal-continuous"
                    ? "Until cancel"
                    : String(selectedOfflineProfile.repetitions)
                  : "N/A",
              )}
              {observationLine("Run Mode", offlineProfileRunMode(selectedOfflineProfile))}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => {
                startOfflineThroughputBenchmark().catch(() => undefined);
              }}
              disabled={offlineLoading || !!offlineActiveRunId || !selectedOfflineProfile}
              className={`inline-flex items-center rounded-full border px-5 py-2.5 text-sm font-medium transition ${
                offlineLoading || !!offlineActiveRunId || !selectedOfflineProfile
                  ? "cursor-not-allowed border-slate-700 bg-slate-900/60 text-slate-500"
                  : "border-fuchsia-500/40 bg-fuchsia-500/15 text-fuchsia-100 hover:border-fuchsia-400"
              }`}
            >
              {offlineLoading || !!offlineActiveRunId ? "Running Offline Benchmark..." : "Run Offline Benchmark"}
            </button>
            {offlineActiveRunId && (offlineLatestRun?.profile_id || offlineProfileId) === "pascal-continuous" ? (
              <button
                type="button"
                onClick={() => {
                  cancelOfflineThroughputBenchmark().catch(() => undefined);
                }}
                className="inline-flex items-center rounded-full border border-rose-500/40 bg-rose-500/10 px-5 py-2.5 text-sm font-medium text-rose-100 transition hover:border-rose-400"
              >
                Cancel Run
              </button>
            ) : null}
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/45 p-4 text-sm">
            <div className="mb-3 text-xs font-medium uppercase tracking-wide text-slate-400">
              Throughput Definitions
            </div>

            <div className="space-y-4 text-slate-300">
              <div>
                <div className="text-sm font-semibold text-sky-200">
                  PROMPT PROCESSING (pp)
                </div>
                <div className="mt-1 text-sm text-slate-400">
                  Measures batch prefill throughput while input prompt tokens are processed into the model context / KV cache.
                </div>
                <div className="mt-2 font-mono text-sm text-slate-100">
                  TPS<sub>pp</sub> = N<sub>prompt</sub> / T<sub>pp</sub>
                </div>
              </div>

              <div>
                <div className="text-sm font-semibold text-emerald-200">
                  TEXT GENERATION (tg)
                </div>
                <div className="mt-1 text-sm text-slate-400">
                  Measures autoregressive decode throughput while output tokens are generated one by one.
                </div>
                <div className="mt-2 font-mono text-sm text-slate-100">
                  TPS<sub>tg</sub> = N<sub>generation</sub> / T<sub>tg</sub>
                </div>
              </div>
            </div>
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/45 p-4 text-sm">
            <div className="mb-3 text-xs font-medium uppercase tracking-wide text-slate-400">
              Cooling Shortcuts
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <button
                type="button"
                onClick={() => onFanModeChange("GPU_DEFAULT")}
                disabled={fanCycleRunning}
                className={`rounded-xl border px-4 py-3 text-left text-sm transition ${
                  fanControlMode === "GPU_DEFAULT"
                    ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-100"
                    : fanCycleRunning
                      ? "border-slate-700 bg-slate-900/60 text-slate-500"
                      : "border-slate-700 bg-slate-950/60 text-slate-200 hover:border-emerald-400/50"
                }`}
              >
                <div className="font-medium">Auto Cooling</div>
                <div className="mt-1 text-xs text-slate-400">
                  Same control path as Engineering Controls.
                </div>
              </button>

              <button
                type="button"
                onClick={() => onFanModeChange("FIXED_0")}
                disabled={fanCycleRunning || !fanControlAvailable}
                className={`rounded-xl border px-4 py-3 text-left text-sm transition ${
                  fanControlMode === "FIXED_0"
                    ? "border-orange-500/40 bg-orange-500/15 text-orange-100"
                    : fanCycleRunning || !fanControlAvailable
                      ? "border-slate-700 bg-slate-900/60 text-slate-500"
                      : "border-slate-700 bg-slate-950/60 text-slate-200 hover:border-orange-400/50"
                }`}
              >
                <div className="font-medium">Fixed 0%</div>
                <div className="mt-1 text-xs text-slate-400">
                  Mirrors Cooling Mode → Fixed 0%.
                </div>
              </button>
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border border-slate-800 bg-slate-900/45 p-4 text-sm">
            {!offlineLatestRun && !offlineError ? (
              <div className="text-slate-400">
                Runs fixed `llama-bench` Pascal SM61 profiles on the dedicated GTX 1080 Ti target pod.
              </div>
            ) : offlineError ? (
              <div className="rounded-xl border border-amber-500/30 bg-amber-950/20 p-3 text-amber-100">
                {offlineError}
              </div>
            ) : (
              <div className="space-y-4">
                {offlineLatestRun?.progress ? (
                  <div className="rounded-xl border border-slate-800 bg-slate-950/55 p-4">
                    <div className="mb-3 text-xs uppercase tracking-wide text-slate-500">
                      Live Run Progress
                    </div>
                    <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                      <SummaryCard
                        label="Status"
                        value={offlineLatestRun.status}
                        tone={
                          offlineLatestRun.status === "running"
                            ? "green"
                            : offlineLatestRun.status === "cancelling"
                              ? "orange"
                              : "blue"
                        }
                      />
                      <SummaryCard
                        label="Prompt-only TPS"
                        value={
                          offlineLatestRun.progress.latest_completed_step_prompt_tps !== undefined &&
                          offlineLatestRun.progress.latest_completed_step_prompt_tps !== null
                            ? `${offlineLatestRun.progress.latest_completed_step_prompt_tps.toFixed(1)} tok/s`
                            : "N/A"
                        }
                        tone="blue"
                      />
                      <SummaryCard
                        label="Generation-only TPS"
                        value={
                          offlineLatestRun.progress.latest_completed_step_generation_tps !== undefined &&
                          offlineLatestRun.progress.latest_completed_step_generation_tps !== null
                            ? `${offlineLatestRun.progress.latest_completed_step_generation_tps.toFixed(1)} tok/s`
                            : "N/A"
                        }
                        tone="blue"
                      />
                    </div>
                    <div className="space-y-2">
                      {observationLine("Active Run ID", offlineLatestRun.run_id)}
                      {observationLine("Elapsed", `${offlineLatestRun.progress.elapsed_seconds.toFixed(1)} sec`)}
                      {observationLine(
                        "Completed Steps",
                        offlineLatestRun.progress.total_steps > 0
                          ? `${offlineLatestRun.progress.completed_steps}/${offlineLatestRun.progress.total_steps}`
                          : `${offlineLatestRun.progress.completed_steps} / Until cancel`,
                      )}
                      {observationLine(
                        "Mean Prompt-only TPS",
                        offlineLatestRun.progress.mean_prompt_tps !== undefined &&
                          offlineLatestRun.progress.mean_prompt_tps !== null
                          ? `${offlineLatestRun.progress.mean_prompt_tps.toFixed(1)} tok/s`
                          : "N/A",
                      )}
                      {observationLine(
                        "Mean Generation-only TPS",
                        offlineLatestRun.progress.mean_generation_tps !== undefined &&
                          offlineLatestRun.progress.mean_generation_tps !== null
                          ? `${offlineLatestRun.progress.mean_generation_tps.toFixed(1)} tok/s`
                          : "N/A",
                      )}
                    </div>
                    <div className="mt-4 grid gap-4">
                      <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                        <div className="mb-3 text-sm font-medium text-slate-200">
                          Completed-Step Prompt-only TPS
                        </div>
                        <div className="h-64">
                          <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={offlineLatestRun.progress.buckets}>
                              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                              <XAxis dataKey="step" tick={{ fill: "#94a3b8", fontSize: 12 }}>
                                <Label
                                  value="Completed Benchmark Step"
                                  position="insideBottom"
                                  offset={-4}
                                  fill="#94a3b8"
                                  fontSize={12}
                                />
                              </XAxis>
                              <YAxis tick={{ fill: "#94a3b8", fontSize: 12 }}>
                                <Label
                                  value="Throughput (tokens/s)"
                                  angle={-90}
                                  position="insideLeft"
                                  fill="#94a3b8"
                                  fontSize={12}
                                  style={{ textAnchor: "middle" }}
                                />
                              </YAxis>
                              <Tooltip />
                              <Line type="monotone" dataKey="prompt_tps" stroke="#38bdf8" strokeWidth={2} dot={false} name="Prompt-only TPS" />
                            </LineChart>
                          </ResponsiveContainer>
                        </div>
                      </div>

                      <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-3">
                        <div className="mb-3 text-sm font-medium text-slate-200">
                          Completed-Step Generation-only TPS
                        </div>
                        <div className="h-64">
                          <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={offlineLatestRun.progress.buckets}>
                              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                              <XAxis dataKey="step" tick={{ fill: "#94a3b8", fontSize: 12 }}>
                                <Label
                                  value="Completed Benchmark Step"
                                  position="insideBottom"
                                  offset={-4}
                                  fill="#94a3b8"
                                  fontSize={12}
                                />
                              </XAxis>
                              <YAxis tick={{ fill: "#94a3b8", fontSize: 12 }}>
                                <Label
                                  value="Throughput (tokens/s)"
                                  angle={-90}
                                  position="insideLeft"
                                  fill="#94a3b8"
                                  fontSize={12}
                                  style={{ textAnchor: "middle" }}
                                />
                              </YAxis>
                              <Tooltip />
                              <Line type="monotone" dataKey="generation_tps" stroke="#34d399" strokeWidth={2} dot={false} name="Generation-only TPS" />
                            </LineChart>
                          </ResponsiveContainer>
                        </div>
                      </div>
                    </div>
                  </div>
                ) : null}

                {!offlineRunInProgress && offlineLatestResult?.preflight_warning ? (
                  <div className="rounded-xl border border-amber-500/30 bg-amber-950/20 p-3 text-amber-100">
                    {offlineLatestResult.preflight_warning}
                  </div>
                ) : null}
              </div>
            )}
          </div>
        </div>
      </div>
    </SectionCard>
  );
}

function FanExperimentPage({
  data,
  execution,
  liveCurrent,
  liveSeries,
  yoloDemo,
  yoloEvents,
  loading,
  error,
  fanControl,
  onFanModeChange,
  onStartThermalDemo,
  onRestoreAutoCooling,
  onStartYoloDemo,
  onStopYoloDemo,
  captureRunning,
  onStartCapture,
  onPauseCapture,
  demoWorkflowBusy,
  yoloControlBusy,
}: {
  data: FanCycleLatestResponse | null;
  execution: FanCycleExecutionStatusResponse | null;
  liveCurrent: FanCycleCurrentMetrics | null;
  liveSeries: FanLivePoint[];
  yoloDemo: YoloDemoStatusResponse | null;
  yoloEvents: YoloDemoEvent[];
  loading: boolean;
  error: string;
  fanControl: FanControlSelection;
  onFanModeChange: (mode: FanMode) => void;
  onStartThermalDemo: () => void;
  onRestoreAutoCooling: () => void;
  onStartYoloDemo: () => void;
  onStopYoloDemo: () => void;
  captureRunning: boolean;
  onStartCapture: () => void;
  onPauseCapture: () => void;
  demoWorkflowBusy: boolean;
  yoloControlBusy: boolean;
}) {
  if (loading) {
    return (
      <section className="rounded-2xl border border-slate-800 bg-slate-950/60 p-8 text-slate-400">
        Loading latest fan-cycle experiment result...
      </section>
    );
  }

  if (error) {
    return (
      <section className="rounded-2xl border border-red-500/30 bg-red-950/20 p-8 text-red-200">
        Failed to load fan-cycle experiment result: {error}
      </section>
    );
  }

  const hasHistoricalData = Boolean(data && data.timeseries.length > 0);
  const config = data?.config;
  const current = data?.current;
  const phaseSummary = data?.phase_summary || [];
  const [timeWindow, setTimeWindow] = useState<TimeWindow>("last-60s");
  const liveChartsRef = useRef<HTMLDivElement | null>(null);
  const yoloDemoRunning =
    yoloDemo?.status === "running" || yoloDemo?.status === "starting";
  const yoloDemoActuallyRunning = yoloDemo?.status === "running";
  const yoloDemoStarting = yoloDemo?.status === "starting";
  const fanControlAvailable = yoloDemo?.fan_control_available ?? true;
  const fanControlMessage =
    yoloDemo?.fan_control_message || "Fixed fan override is available.";
  const fanCycleRunning =
    execution?.status === "running" ||
    execution?.status === "starting" ||
    execution?.status === "stopping";
  const displayCurrent = liveCurrent || (fanCycleRunning ? current : null) || {
    gpu_temp_c: 0,
    fan_pct: 0,
    sm_clock_mhz: 0,
    gpu_util_pct: 0,
    server_latency_ms: 0,
    e2e_latency_ms: 0,
  };
  const displaySeries = liveSeries.length > 0 ? liveSeries : data?.timeseries || [];
  const selectedFanPercent = modeFanPercent(fanControl.mode, config?.fixed_fan_pct || 5);
  const actualFanPercent = displayCurrent.fan_pct;
  const requestedFanLabel =
    fanControl.mode === "GPU_DEFAULT" ? "Auto / GPU Default" : `${selectedFanPercent}%`;
  const manualCoolingOverrideActive = fanControl.mode !== "GPU_DEFAULT";
  const fanOverrideNotHonored =
    manualCoolingOverrideActive &&
    Math.abs(actualFanPercent - selectedFanPercent) >= 3;
  const fanOverrideVerified = manualCoolingOverrideActive && !fanOverrideNotHonored;
  const engineeringModeActive = fanCycleRunning || manualCoolingOverrideActive;
  const externalGpuLoadDetected = !yoloDemoRunning && displayCurrent.gpu_util_pct >= 20;
  const chartEmptyText = fanCycleRunning
    ? "Experiment is running. Charts will populate after live samples or the first completed run appear."
    : "No completed fan-cycle experiment run found yet.";
  const wholeRunSeries = data?.timeseries || [];
  const last60Series = (displaySeries as FanLivePoint[]).slice(-60);
  const last5mSeries = (displaySeries as FanLivePoint[]).slice(-300);
  const activeSeries =
    timeWindow === "whole-run"
      ? wholeRunSeries.length > 0
        ? wholeRunSeries
        : displaySeries
      : timeWindow === "last-5m"
        ? last5mSeries
        : last60Series;
  const latencySeries = yoloDemoRunning
    ? (
        timeWindow === "whole-run"
          ? activeSeries
          : activeSeries.filter(
              (point) => Number(point.server_latency) > 0 || Number(point.e2e_latency) > 0,
            )
      )
    : [];
  const baselineSeries =
    wholeRunSeries.filter((point) => point.phase === "normal_hold").slice(0, 120) ||
    [];
  const baselineWindow = baselineSeries.length > 0 ? baselineSeries : [];
  const baselineAvailable = baselineWindow.length > 0;
  const baseline = baselineAvailable
    ? {
        gpu_temp: baselineWindow.reduce((sum, point) => sum + point.gpu_temp, 0) / baselineWindow.length,
        sm_clock: baselineWindow.reduce((sum, point) => sum + point.sm_clock, 0) / baselineWindow.length,
        server_latency: baselineWindow.reduce((sum, point) => sum + point.server_latency, 0) / baselineWindow.length,
        e2e_latency: baselineWindow.reduce((sum, point) => sum + point.e2e_latency, 0) / baselineWindow.length,
      }
    : null;
  const deltaTemp = baseline ? displayCurrent.gpu_temp_c - baseline.gpu_temp : null;
  const deltaClock = baseline ? displayCurrent.sm_clock_mhz - baseline.sm_clock : null;
  const phaseHistorySeen =
    new Set(phaseSummary.map((item) => item.phase));
  const recoveryEligible =
    phaseHistorySeen.has("fault_hold") ||
    phaseHistorySeen.has("recovery_wait") ||
    manualCoolingOverrideActive;
  const faultCoolingApplied = manualCoolingOverrideActive && yoloDemoRunning;
  const thermalTargetReached =
    Boolean(config) &&
    displayCurrent.gpu_temp_c >= (config?.fault_temp_target_c || 85) &&
    displayCurrent.gpu_util_pct >= 20;
  const clockDropObserved = deltaClock !== null && deltaClock <= -150;
  const recoveryStable =
    recoveryEligible &&
    fanControl.mode === "GPU_DEFAULT" &&
    yoloDemoRunning &&
    deltaTemp !== null &&
    deltaClock !== null &&
    deltaTemp <= 2 &&
    deltaClock >= -100;
  const phaseSteps: ThermalDemoStep[] = [
    {
      key: "baseline",
      label: "Baseline",
      detail: yoloDemoRunning
        ? manualCoolingOverrideActive
          ? "Baseline ended after manual cooling override"
          : "YOLO steady-state with auto cooling"
        : "Start YOLO demo workload",
      state:
        !yoloDemoRunning
          ? "active"
          : manualCoolingOverrideActive
            ? "done"
            : "done",
    },
    {
      key: "fault_fan",
      label: "Reduced Cooling",
      detail: `Requested ${requestedFanLabel}`,
      state:
        fanOverrideVerified
          ? "done"
          : faultCoolingApplied
            ? "active"
            : "pending",
    },
    {
      key: "thermal_rise",
      label: "Thermal Rise",
      detail: config ? `Target > ${config.fault_temp_target_c.toFixed(0)}°C` : "Observe GPU temp climb",
      state:
        thermalTargetReached
          ? "done"
          : faultCoolingApplied
            ? "active"
            : "pending",
    },
    {
      key: "clock_drop",
      label: "Clock Response",
      detail: "Observe whether SM clock decreases under sustained thermal stress",
      state:
        clockDropObserved
          ? "done"
          : faultCoolingApplied && thermalTargetReached
            ? "active"
            : "pending",
    },
    {
      key: "recovery",
      label: "Recovery",
      detail: "Restore GPU_DEFAULT and watch latency recover",
      state:
        recoveryStable
          ? "done"
          : recoveryEligible && fanControl.mode === "GPU_DEFAULT" && yoloDemoRunning
            ? "active"
            : "pending",
    },
  ];

  const nextActionText = !yoloDemoRunning
    ? "Start YOLO workload to establish a thermal baseline."
    : !manualCoolingOverrideActive && !recoveryEligible
      ? "Use Engineering Controls or Start Live Thermal Demo to reduce cooling and induce thermal stress."
      : manualCoolingOverrideActive && !thermalTargetReached
        ? "Hold reduced cooling and watch GPU temperature rise toward the configured fault target."
        : manualCoolingOverrideActive && !clockDropObserved
          ? "Continue thermal stress and observe whether SM clock decreases."
          : manualCoolingOverrideActive
            ? "Restore Auto Cooling to begin recovery."
            : recoveryEligible && !recoveryStable
              ? "Keep auto cooling enabled and observe recovery until temperature and clock stabilize."
              : "Thermal workflow is currently aligned with the observed state.";

  const stepperActiveStep =
    phaseSteps.find((step) => step.state === "active") ||
    [...phaseSteps].reverse().find((step) => step.state === "done") ||
    phaseSteps[0];

  async function handleStartLiveThermalDemo() {
    await onStartThermalDemo();
    window.setTimeout(() => {
      liveChartsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 150);
  }

  return (
    <section className="space-y-6">
      {false ? (
        <>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={handleStartLiveThermalDemo}
              disabled={demoWorkflowBusy || !fanControlAvailable || fanCycleRunning}
              className={`rounded-xl border px-4 py-2 text-sm transition ${
                demoWorkflowBusy || !fanControlAvailable || fanCycleRunning
                  ? "border-slate-700 bg-slate-900/60 text-slate-500"
                  : "border-red-500/40 bg-red-500/15 text-red-100 hover:border-red-400"
              }`}
            >
              Start Live Thermal Demo
            </button>
            <button
              onClick={onRestoreAutoCooling}
              disabled={demoWorkflowBusy}
              className={`rounded-xl border px-4 py-2 text-sm transition ${
                demoWorkflowBusy
                  ? "border-slate-700 bg-slate-900/60 text-slate-500"
                  : "border-emerald-500/40 bg-emerald-500/15 text-emerald-100 hover:border-emerald-400"
              }`}
            >
              Restore Auto Cooling
            </button>
          </div>

          {(engineeringModeActive || externalGpuLoadDetected) && (
            <div
              className={`rounded-xl border p-4 text-sm ${
                manualCoolingOverrideActive || fanCycleRunning
                  ? "border-amber-500/40 bg-amber-500/10 text-amber-200"
                  : "border-orange-500/40 bg-orange-500/10 text-orange-200"
              }`}
            >
              {manualCoolingOverrideActive
                ? "Manual cooling override is active. Demo Flow is being interpreted from the current operator-selected thermal state."
                : fanCycleRunning
                  ? "Thermal experiment runner is active. Demo Flow reflects the active workflow state until the run stops."
                  : "External GPU load detected while the YOLO demo workload is stopped. Baseline and thermal interpretation may be contaminated."}
            </div>
          )}
        </>
      ) : null}

      <SectionCard title="Demo Flow">
        <div className="space-y-3">
          <div className="grid gap-2 md:grid-cols-5">
            {phaseSteps.map((step) => (
              <div
                key={step.key}
                className={`rounded-xl border p-3 shadow-sm ${phaseBadgeClass(step.state)}`}
              >
                <div className="text-[10px] uppercase tracking-[0.16em] opacity-70">
                  {step.state === "active" ? "Active" : step.state === "done" ? "Done" : "Pending"}
                </div>
                <div className="mt-2 text-[13px] font-semibold">{step.label}</div>
                <div className="mt-1.5 text-[11px] leading-4.5 opacity-90">{step.detail}</div>
              </div>
            ))}
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-300">
            <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Active Step</div>
            <div className="mt-2 text-base font-semibold text-slate-100">{stepperActiveStep.label}</div>
            <div className="mt-1 text-xs text-slate-400">{stepperActiveStep.detail}</div>
            <div className="mt-3 rounded-xl border border-slate-800 bg-slate-900/60 p-3 text-xs text-slate-300">
              Next Action: {nextActionText}
            </div>
          </div>
        </div>
      </SectionCard>

      <div ref={liveChartsRef} className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          {(
            [
              ["last-60s", "Last 60s"],
              ["last-5m", "5 min"],
              ["whole-run", "Whole Run"],
            ] as [TimeWindow, string][]
          ).map(([windowKey, label]) => (
            <button
              key={windowKey}
              onClick={() => setTimeWindow(windowKey)}
              className={`rounded-full border px-3 py-1 text-xs transition ${
                timeWindow === windowKey
                  ? "border-sky-500/40 bg-sky-500/15 text-sky-200"
                  : "border-slate-700 bg-slate-900/60 text-slate-400 hover:border-slate-500"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        {hasHistoricalData || displaySeries.length > 0 ? (
          <div className="grid gap-4 xl:grid-cols-2">
            <MultiLineChart
              title="GPU Temperature / Fan Speed"
              data={activeSeries}
              lines={[
                { key: "gpu_temp", name: "GPU Temp", stroke: "#f97316" },
                { key: "fan_pct", name: "Fan %", stroke: "#38bdf8" },
              ]}
              height={220}
            />
            <MultiLineChart
              title="SM Clock"
              data={activeSeries}
              lines={[{ key: "sm_clock", name: "SM Clock", stroke: "#a78bfa" }]}
              height={220}
            />
            <MultiLineChart
              title="E2E / Server Latency"
              data={latencySeries}
              unit=" ms"
              lines={[
                { key: "e2e_latency", name: "E2E Latency", stroke: "#38bdf8" },
                { key: "server_latency", name: "Server Latency", stroke: "#f59e0b" },
              ]}
              height={220}
            />
            <MultiLineChart
              title="GPU Utilization"
              data={activeSeries}
              lines={[{ key: "gpu_util", name: "GPU Util", stroke: "#22c55e" }]}
              yDomain={[0, 100]}
              height={220}
            />
          </div>
        ) : (
          <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-8 text-sm text-slate-400">
            {chartEmptyText}
          </div>
        )}
      </div>

      <OfflineHardwareBenchmarkSection
        fanControlMode={fanControl.mode}
        fanControlAvailable={fanControlAvailable}
        fanCycleRunning={fanCycleRunning}
        onFanModeChange={onFanModeChange}
      />

      <SectionCard title="Engineering Controls">
            <div className="space-y-3 text-sm text-slate-300">
              <div className="rounded-2xl border border-slate-800 bg-slate-900/40 px-4 py-4 space-y-4">
              <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-200">
                Replay mode, manual YOLO workload control, manual cooling overrides, and live-view toggles live here.
                These controls are for engineering use and can invalidate the formal live thermal demo state. The focus YOLO pod is kept warm between runs to reduce restart latency.
              </div>
              <div className="rounded-xl bg-slate-900/60 p-3">
                <div className="text-xs uppercase tracking-wide text-slate-500">YOLO Workload Status</div>
                <div className="mt-1 flex items-center gap-2 font-semibold text-slate-100">
                  <span
                    className={`h-2.5 w-2.5 rounded-full ${
                      yoloDemoActuallyRunning ? "bg-emerald-400" : yoloDemoStarting ? "bg-amber-400" : "bg-slate-500"
                    }`}
                  />
                  <span>{yoloDemoActuallyRunning ? "Running" : yoloDemoStarting ? "Starting" : "Stopped"}</span>
                </div>
                <div className="mt-1 text-xs text-slate-400">
                  {yoloDemo?.message || "Start the demo to run measurement and GPU bgload against the warm single-pod YOLO target."}
                </div>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <button
                  onClick={onStartYoloDemo}
                  disabled={yoloDemoRunning || fanCycleRunning || yoloControlBusy}
                  className={`rounded-xl border px-3 py-2 text-sm transition ${
                    yoloDemoRunning || fanCycleRunning || yoloControlBusy
                      ? "border-slate-700 bg-slate-900/60 text-slate-500"
                      : "border-red-500/40 bg-red-500/15 text-red-200 hover:border-red-400"
                  }`}
                >
                  {yoloControlBusy ? "Starting YOLO Workload..." : "Start YOLO Workload"}
                </button>
                <button
                  onClick={onStopYoloDemo}
                  disabled={!yoloDemoActuallyRunning || fanCycleRunning || yoloControlBusy}
                  className={`rounded-xl border px-3 py-2 text-sm transition ${
                    yoloDemoActuallyRunning && !fanCycleRunning && !yoloControlBusy
                      ? "border-orange-500/40 bg-orange-500/15 text-orange-200 hover:border-orange-400"
                      : "border-slate-700 bg-slate-900/60 text-slate-500"
                  }`}
                >
                  {yoloControlBusy ? "Stopping YOLO Workload..." : "Stop YOLO Workload"}
                </button>
                <button
                  onClick={onStartCapture}
                  className={`rounded-xl border px-3 py-2 text-sm transition ${
                    captureRunning
                      ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-200"
                      : "border-slate-700 bg-slate-900/60 text-slate-500 hover:border-slate-500"
                  }`}
                >
                  Resume Live View
                </button>
                <button
                  onClick={onPauseCapture}
                  className={`rounded-xl border px-3 py-2 text-sm transition ${
                    captureRunning
                      ? "border-slate-700 bg-slate-900/60 text-slate-500 hover:border-slate-500"
                      : "border-orange-500/40 bg-orange-500/15 text-orange-200"
                  }`}
                >
                  Pause Live View
                </button>
              </div>
              <div className="text-xs uppercase tracking-wide text-slate-500">Cooling Mode</div>
              {!fanControlAvailable && (
                <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-200">
                  {fanControlMessage}
                </div>
              )}
              <div className="grid gap-2 sm:grid-cols-2">
                {(
                  [
                    "GPU_DEFAULT",
                    "FIXED_0",
                    "FIXED_5",
                    "FIXED_15",
                    "FIXED_20",
                    "FIXED_25",
                    "GPU_MAX",
                  ] as FanMode[]
                ).map((mode) => (
                  <button
                    key={mode}
                    onClick={() => onFanModeChange(mode)}
                    disabled={fanCycleRunning || (mode !== "GPU_DEFAULT" && !fanControlAvailable)}
                    className={`rounded-xl border px-3 py-2 text-left text-sm transition ${
                      fanControl.mode === mode
                        ? "border-orange-500/40 bg-orange-500/15 text-orange-200"
                        : fanCycleRunning || (mode !== "GPU_DEFAULT" && !fanControlAvailable)
                          ? "border-slate-700 bg-slate-900/60 text-slate-600"
                          : "border-slate-700 bg-slate-900/60 text-slate-300 hover:border-slate-500"
                    }`}
                  >
                    {displayFanModeLabel(mode)}
                  </button>
                ))}
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-xl bg-slate-900/60 p-3 text-sm text-slate-300">
                  Selected Mode: {displayFanModeLabel(fanControl.mode)}
                </div>
                <div className="rounded-xl bg-slate-900/60 p-3 text-sm text-slate-300">
                  Requested Fan %: {requestedFanLabel}
                </div>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div
                  className={`rounded-xl border p-3 text-sm ${
                    fanOverrideNotHonored
                      ? "border-amber-500/40 bg-amber-500/10 text-amber-200"
                      : "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
                  }`}
                >
                  {fanOverrideNotHonored
                    ? "fan override not honored"
                    : "fan override matches requested value"}
                </div>
              </div>
              </div>
            </div>
      </SectionCard>

      <SectionCard title="Event Timeline">
        <div className="space-y-4">
          {yoloEvents.slice(-10).map((event) => (
            <div key={`${event.time}-${event.message}`} className="flex gap-3">
              <div className={`mt-1 h-2.5 w-2.5 rounded-full ${eventDot(event.level)}`} />
              <div>
                <div className="font-mono text-xs text-slate-500">{event.time.split("T").pop()}</div>
                <div className={`mt-1 text-sm ${eventTone(event.level)}`}>{event.message}</div>
              </div>
            </div>
          ))}
          {yoloEvents.length === 0 && (
            <div className="text-sm text-slate-500">No YOLO demo events yet.</div>
          )}
        </div>
      </SectionCard>
    </section>
  );
}

export default function App() {
  const [inventory, setInventory] = useState<NodeInventory[]>([]);
  const [statuses, setStatuses] = useState<NodeStatus[]>([]);
  const [workloads, setWorkloads] = useState<WorkloadListItem[]>([]);
  const [workloadDetails, setWorkloadDetails] = useState<
    Record<string, WorkloadStatusResponse>
  >({});
  const [selectedNode, setSelectedNode] = useState<string>("");
  const [lastUpdated, setLastUpdated] = useState<string>("-");
  const [error, setError] = useState<string>("");
  const [activeTab, setActiveTab] = useState<ActiveTab>("monitor");
  const [historyByNode, setHistoryByNode] = useState<Record<string, HistoryPoint[]>>({});
  const [fanControl, setFanControl] = useState<FanControlSelection>({
    mode: "FIXED_5",
  });
  const [fanExperiment, setFanExperiment] = useState<FanCycleLatestResponse | null>(null);
  const [fanExperimentLoading, setFanExperimentLoading] = useState(true);
  const [fanExperimentError, setFanExperimentError] = useState("");
  const [fanCaptureRunning, setFanCaptureRunning] = useState(true);
  const [fanExecutionStatus, setFanExecutionStatus] = useState<FanCycleExecutionStatusResponse | null>(null);
  const [fanLiveCurrent, setFanLiveCurrent] = useState<FanCycleCurrentMetrics | null>(null);
  const [fanLiveSeries, setFanLiveSeries] = useState<FanLivePoint[]>([]);
  const [yoloDemoStatus, setYoloDemoStatus] = useState<YoloDemoStatusResponse | null>(null);
  const [yoloDemoEvents, setYoloDemoEvents] = useState<YoloDemoEvent[]>([]);
  const [demoWorkflowBusy, setDemoWorkflowBusy] = useState(false);
  const [yoloControlBusy, setYoloControlBusy] = useState(false);

  async function loadInventory() {
    const data = await fetchJson<NodeListResponse>("/api/v1/nodes");
    setInventory(data.nodes || []);
    if (!selectedNode && data.nodes?.length > 0) {
      setSelectedNode(data.nodes[0].node_name);
    }
  }

  async function loadStatus() {
    const data = await fetchJson<NodeStatusListResponse>("/api/v1/nodes/status");
    setStatuses(data.nodes || []);
    setLastUpdated(new Date().toLocaleTimeString());
  }

  async function loadWorkloads() {
    try {
      const data = await fetchJson<WorkloadListResponse>("/api/v1/workloads");
      const items = [...(data.workloads || [])].sort((a, b) =>
        `${a.namespace}/${a.workload}`.localeCompare(`${b.namespace}/${b.workload}`),
      );
      setWorkloads(items);

      if (items.length === 0) {
        setWorkloadDetails({});
        return;
      }

      const detailEntries = await Promise.all(
        items.map(async (item) => {
          const key = `${item.namespace}/${item.workload}`;
          try {
            const detail = await fetchJson<WorkloadStatusResponse>(
              `/api/v1/workloads/${encodeURIComponent(item.namespace)}/${encodeURIComponent(item.workload)}/status`,
            );
            return [key, detail] as const;
          } catch (e) {
            if (isNotFoundError(e)) {
              return null;
            }
            throw e;
          }
        }),
      );

      setWorkloadDetails(
        Object.fromEntries(detailEntries.filter((entry): entry is readonly [string, WorkloadStatusResponse] => entry !== null)),
      );
    } catch (e) {
      if (isNotFoundError(e)) {
        setWorkloads([]);
        setWorkloadDetails({});
        return;
      }
      throw e;
    }
  }

  async function loadFanExperiment() {
    try {
      setFanExperimentError("");
      const data = await fetchJson<FanCycleLatestResponse>("/api/v1/experiments/fan-cycle/latest");
      setFanExperiment(data);
    } catch (e) {
      setFanExperiment(null);
      if (!isNotFoundError(e)) {
        setFanExperimentError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setFanExperimentLoading(false);
    }
  }

  async function loadFanLive() {
    try {
      const data = await fetchJson<FanCycleLiveResponse>("/api/v1/experiments/fan-cycle/live");
      setFanLiveCurrent(data.current);
      const point: FanLivePoint = {
        ts: data.generated_at * 1000,
        time: new Date(data.generated_at * 1000).toLocaleTimeString(),
        phase: data.run.current_phase || "live_demo",
        gpu_temp: data.current.gpu_temp_c,
        fan_pct: data.current.fan_pct,
        sm_clock: data.current.sm_clock_mhz,
        gpu_util: data.current.gpu_util_pct,
        server_latency: data.current.server_latency_ms,
        e2e_latency: data.current.e2e_latency_ms,
      };
      setFanLiveSeries((prev) => [...prev, point].slice(-60));
    } catch (e) {
      if (!isNotFoundError(e)) {
        throw e;
      }
    }
  }

  async function loadFanExecutionStatus() {
    const data = await fetchJson<FanCycleExecutionStatusResponse>("/api/v1/experiments/fan-cycle/status");
    setFanExecutionStatus(data);
  }

  async function loadYoloDemoStatus() {
    const data = await fetchJson<YoloDemoStatusResponse>("/api/v1/experiments/yolo-demo/status");
    setYoloDemoStatus(data);
    if (data.fan_mode && data.fan_mode !== fanControl.mode) {
      setFanControl({ mode: data.fan_mode });
    }
  }

  async function loadYoloDemoEvents() {
    const data = await fetchJson<YoloDemoEventsResponse>("/api/v1/experiments/yolo-demo/events");
    setYoloDemoEvents(data.events || []);
  }

  async function postJson<T>(path: string, method = "POST"): Promise<T> {
    const res = await fetch(`${API_BASE}${path}`, {
      method,
      headers: API_TOKEN
        ? {
            Authorization: `Bearer ${API_TOKEN}`,
          }
        : undefined,
    });
    if (!res.ok) {
      if (res.status === 401 && isDashboardTokenMissing()) {
        console.warn(
          "autoscale_api returned 401 while VITE_AUTOSCALE_API_TOKEN is missing or still uses the example value.",
        );
        throw new Error(
          "401 Unauthorized: set VITE_AUTOSCALE_API_TOKEN in cluster-dashboard/.env to the issued AutoScale API token.",
        );
      }
      throw new Error(`${res.status} ${res.statusText}`);
    }
    return res.json();
  }

  async function runThermalDemoWorkflow() {
    setDemoWorkflowBusy(true);
    try {
      setFanExperimentError("");
      setFanCaptureRunning(true);
      let nextStatus = yoloDemoStatus;
      if (!nextStatus || (nextStatus.status !== "running" && nextStatus.status !== "starting")) {
        nextStatus = await postJson<YoloDemoStatusResponse>("/api/v1/experiments/yolo-demo/start");
        setYoloDemoStatus(nextStatus);
      }
      const fixedStatus = await postJson<YoloDemoStatusResponse>("/api/v1/experiments/yolo-demo/fan-mode/FIXED_20");
      setYoloDemoStatus(fixedStatus);
      setFanControl({ mode: "FIXED_20" });
      await loadYoloDemoEvents();
      await loadFanLive();
      await loadFanExecutionStatus();
    } catch (e) {
      setFanExperimentError(e instanceof Error ? e.message : String(e));
    } finally {
      setDemoWorkflowBusy(false);
    }
  }

  async function restoreAutoCoolingWorkflow() {
    setDemoWorkflowBusy(true);
    try {
      setFanExperimentError("");
      const status = await postJson<YoloDemoStatusResponse>("/api/v1/experiments/yolo-demo/fan-mode/GPU_DEFAULT");
      setYoloDemoStatus(status);
      setFanControl({ mode: "GPU_DEFAULT" });
      await loadYoloDemoEvents();
      await loadFanLive();
    } catch (e) {
      setFanExperimentError(e instanceof Error ? e.message : String(e));
    } finally {
      setDemoWorkflowBusy(false);
    }
  }

  async function loadAll() {
    try {
      setError("");
      await loadInventory();
      await loadStatus();
      await loadWorkloads();
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    loadAll();
    loadFanExperiment();

    const statusTimer = window.setInterval(() => {
      const tasks =
        activeTab === "llm-serving"
          ? [loadStatus()]
          : [loadStatus(), loadWorkloads()];
      Promise.all(tasks)
        .then(() => setError(""))
        .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    }, 3000);

    const inventoryTimer = window.setInterval(() => {
      loadInventory()
        .then(() => setError(""))
        .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    }, 60000);

    return () => {
      window.clearInterval(statusTimer);
      window.clearInterval(inventoryTimer);
    };
  }, [activeTab]);

  useEffect(() => {
    if (activeTab !== "llm-serving") {
      return;
    }

    loadWorkloads().catch((e) => setError(e instanceof Error ? e.message : String(e)));
    const workloadTimer = window.setInterval(() => {
      loadWorkloads()
        .then(() => setError(""))
        .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    }, 1000);

    return () => {
      window.clearInterval(workloadTimer);
    };
  }, [activeTab]);

  useEffect(() => {
    if (!fanCaptureRunning) {
      return;
    }

    loadFanExperiment().catch((e) =>
      setFanExperimentError(e instanceof Error ? e.message : String(e)),
    );
    loadFanExecutionStatus().catch((e) =>
      setFanExperimentError(e instanceof Error ? e.message : String(e)),
    );
    loadFanLive().catch((e) =>
      setFanExperimentError(e instanceof Error ? e.message : String(e)),
    );
    loadYoloDemoStatus().catch((e) =>
      setFanExperimentError(e instanceof Error ? e.message : String(e)),
    );
    loadYoloDemoEvents().catch((e) =>
      setFanExperimentError(e instanceof Error ? e.message : String(e)),
    );

    const fanExperimentTimer = window.setInterval(() => {
      loadFanExperiment().catch((e) =>
        setFanExperimentError(e instanceof Error ? e.message : String(e)),
      );
      loadFanExecutionStatus().catch((e) =>
        setFanExperimentError(e instanceof Error ? e.message : String(e)),
      );
      loadFanLive().catch((e) =>
        setFanExperimentError(e instanceof Error ? e.message : String(e)),
      );
      loadYoloDemoStatus().catch((e) =>
        setFanExperimentError(e instanceof Error ? e.message : String(e)),
      );
      loadYoloDemoEvents().catch((e) =>
        setFanExperimentError(e instanceof Error ? e.message : String(e)),
      );
    }, 1000);

    return () => {
      window.clearInterval(fanExperimentTimer);
    };
  }, [fanCaptureRunning]);

  const nodes: NodeView[] = useMemo(() => {
    const statusMap = new Map(statuses.map((s) => [s.node_name, s]));

    return inventory.map((inv) => {
      const status = statusMap.get(inv.node_name);
      return {
        inventory: inv,
        status,
        health: getHealth(inv, status),
      };
    });
  }, [inventory, statuses]);

  const selected = nodes.find((n) => n.inventory.node_name === selectedNode);

  useEffect(() => {
    if (!selectedNode) return;

    const st = statuses.find((s) => s.node_name === selectedNode);
    if (!st) return;

    const now = new Date();

    const point: HistoryPoint = {
      ts: now.getTime(),
      time: now.toLocaleTimeString(),
      cpu: clampPercent(st.cpu?.usage_percent),
      memory: clampPercent(st.memory?.usage_percent),
      disk: clampPercent(st.disk?.root_usage_percent),
      gpuFbUsed: st.gpu?.fb_used_mib || 0,
    };

    setHistoryByNode((prev) => {
      const oldPoints = prev[selectedNode] || [];
      const nextPoints = [...oldPoints, point].slice(-60);

      return {
        ...prev,
        [selectedNode]: nextPoints,
      };
    });
  }, [statuses, selectedNode]);

  const summary = useMemo(() => {
    const total = nodes.length;
    const healthy = nodes.filter((n) => n.health === "healthy").length;
    const degraded = nodes.filter((n) => n.health === "degraded").length;
    const offline = nodes.filter((n) => n.health === "offline").length;

    const highestCpuNode = nodes
      .filter((n) => hasUsableNodeMetric(n.status, "cpu"))
      .reduce<NodeView | null>((best, node) => {
        if (!best) return node;
        return (node.status?.cpu?.usage_percent || 0) > (best.status?.cpu?.usage_percent || 0)
          ? node
          : best;
      }, null);

    const highestMemoryNode = nodes
      .filter((n) => hasUsableNodeMetric(n.status, "memory"))
      .reduce<NodeView | null>((best, node) => {
        if (!best) return node;
        return (node.status?.memory?.usage_percent || 0) > (best.status?.memory?.usage_percent || 0)
          ? node
          : best;
      }, null);

    return { total, healthy, degraded, offline, highestCpuNode, highestMemoryNode };
  }, [nodes]);

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,#0f172a,#020617_55%)] p-6 text-slate-100">
      <div className="mx-auto max-w-[1500px] space-y-6">
        <header className="rounded-2xl border border-slate-800 bg-slate-950/80 p-5 shadow-lg">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <h1 className="text-2xl font-bold tracking-tight">
                Pre6G Cluster Monitoring Dashboard
              </h1>
              <p className="mt-1 text-sm text-slate-400">
                Cluster runtime view plus thermal degradation experiment console
              </p>
            </div>

            <div className="flex items-center gap-3 text-sm">
              <div className="rounded-full border border-emerald-500/40 px-3 py-1 text-emerald-300">
                Live
              </div>
              <div className="rounded-full border border-slate-700 px-3 py-1 text-slate-300">
                Refresh 3s
              </div>
              <div className="rounded-full border border-slate-700 px-3 py-1 font-mono text-slate-300">
                {lastUpdated}
              </div>
            </div>
          </div>

          <div className="mt-5 flex gap-2 rounded-2xl border border-slate-800 bg-slate-950/70 p-2">
            <button
              onClick={() => setActiveTab("monitor")}
              className={`rounded-xl border px-4 py-2 text-sm transition ${
                activeTab === "monitor"
                  ? "border-sky-500/40 bg-sky-500/20 text-sky-300"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              Cluster Monitor
            </button>
            <button
              onClick={() => setActiveTab("fan-experiment")}
              className={`rounded-xl border px-4 py-2 text-sm transition ${
                activeTab === "fan-experiment"
                  ? "border-orange-500/40 bg-orange-500/20 text-orange-300"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              Fan-Cycle Experiment
            </button>
            <button
              onClick={() => setActiveTab("llm-serving")}
              className={`rounded-xl border px-4 py-2 text-sm transition ${
                activeTab === "llm-serving"
                  ? "border-sky-500/40 bg-sky-500/20 text-sky-300"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              LLM Serving Lab
            </button>
          </div>

          {isDashboardTokenMissing() && (
            <div className="mt-4 rounded-lg border border-amber-500/40 bg-amber-950/40 p-3 text-sm text-amber-200">
              Dashboard auth notice: if autoscale_api has token auth enabled, set
              <span className="mx-1 font-mono">VITE_AUTOSCALE_API_TOKEN</span>
              in
              <span className="mx-1 font-mono">cluster-dashboard/.env</span>
              before starting the frontend.
            </div>
          )}

          {error && (
            <div className="mt-4 rounded-lg border border-red-500/40 bg-red-950/40 p-3 text-sm text-red-200">
              API Error: {error}
            </div>
          )}
        </header>

        {activeTab === "monitor" && (
          <>
            <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-6">
              <SummaryCard label="Total Nodes" value={summary.total.toString()} />
              <SummaryCard label="Healthy" value={summary.healthy.toString()} tone="green" />
              <SummaryCard label="Degraded" value={summary.degraded.toString()} tone="orange" />
              <SummaryCard label="Offline" value={summary.offline.toString()} tone="gray" />
              <SummaryCard
                label="Highest CPU Node"
                value={
                  summary.highestCpuNode
                    ? `${summary.highestCpuNode.inventory.node_name} · ${(summary.highestCpuNode.status?.cpu?.usage_percent || 0).toFixed(1)}%`
                    : "N/A"
                }
              />
              <SummaryCard
                label="Highest Memory Node"
                value={
                  summary.highestMemoryNode
                    ? `${summary.highestMemoryNode.inventory.node_name} · ${(summary.highestMemoryNode.status?.memory?.usage_percent || 0).toFixed(1)}%`
                    : "N/A"
                }
              />
            </section>

            <section className="grid gap-6 xl:grid-cols-[minmax(0,1.7fr)_520px]">
              <div className="rounded-2xl border border-slate-800 bg-slate-950/50 p-5">
                <div className="mb-4 flex items-center justify-between">
                  <div>
                    <h2 className="text-lg font-semibold">Cluster Nodes</h2>
                    <p className="text-sm text-slate-400">
                      Click a node card to inspect runtime metrics.
                    </p>
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  {nodes.map((node) => (
                    <NodeCard
                      key={node.inventory.node_name}
                      node={node}
                      selected={selectedNode === node.inventory.node_name}
                      onClick={() => setSelectedNode(node.inventory.node_name)}
                    />
                  ))}
                </div>
              </div>

              <aside className="xl:sticky xl:top-6 xl:self-start">
                <NodeDetail
                  node={selected}
                  history={selectedNode ? historyByNode[selectedNode] || [] : []}
                />
              </aside>
            </section>
          </>
        )}

        {activeTab === "llm-serving" && (
          <LlmServingLabPage
            workloads={workloads}
            workloadDetails={workloadDetails}
            onRefreshWorkloads={loadWorkloads}
          />
        )}

        {activeTab === "fan-experiment" && (
          <FanExperimentPage
            data={fanExperiment}
            execution={fanExecutionStatus}
            liveCurrent={fanLiveCurrent}
            liveSeries={fanLiveSeries}
            yoloDemo={yoloDemoStatus}
            yoloEvents={yoloDemoEvents}
            loading={fanExperimentLoading}
            error={fanExperimentError}
            fanControl={fanControl}
            onFanModeChange={(mode) => {
              const previousMode = fanControl.mode;
              setFanControl({ mode });
              postJson<YoloDemoStatusResponse>(`/api/v1/experiments/yolo-demo/fan-mode/${mode}`)
                .then(setYoloDemoStatus)
                .then(() => loadYoloDemoEvents())
                .catch((e) => {
                  setFanControl({ mode: previousMode });
                  setFanExperimentError(e instanceof Error ? e.message : String(e)),
                  loadYoloDemoStatus().catch(() => undefined);
                });
            }}
            onStartThermalDemo={() => {
              runThermalDemoWorkflow().catch(() => undefined);
            }}
            onRestoreAutoCooling={() => {
              restoreAutoCoolingWorkflow().catch(() => undefined);
            }}
            onStartYoloDemo={() => {
              setYoloControlBusy(true);
              setFanExperimentError("");
              setFanLiveCurrent(null);
              setFanLiveSeries([]);
              setYoloDemoStatus((prev) => ({
                schema_name: prev?.schema_name || "pre6g.experiments.yolo_demo.status.v1",
                generated_at: Math.floor(Date.now() / 1000),
                status: "starting",
                run_id: prev?.run_id || "",
                namespace: prev?.namespace || "intent-lab",
                focus_deploy: prev?.focus_deploy || "yolo26n-focus",
                bg_deploy: prev?.bg_deploy || "yolo26n-bg-1",
                focus_pod: "",
                target_url: "",
                target_mode: prev?.target_mode || "",
                node_name: prev?.node_name || "icclz1",
                measurement_pid: 0,
                bgload_pid: 0,
                fan_mode: prev?.fan_mode || fanControl.mode,
                fan_control_available: prev?.fan_control_available ?? true,
                fan_control_message: prev?.fan_control_message || "Fixed fan override is available.",
                started_at: Math.floor(Date.now() / 1000),
                message: "Preparing YOLO demo workload",
              }));
              postJson<YoloDemoStatusResponse>("/api/v1/experiments/yolo-demo/start")
                .then(async (status) => {
                  setYoloDemoStatus(status);
                  await loadYoloDemoStatus();
                  await loadYoloDemoEvents();
                  await loadFanLive();
                })
                .catch((e) =>
                  setFanExperimentError(e instanceof Error ? e.message : String(e)),
                )
                .finally(() => {
                  setYoloControlBusy(false);
                });
            }}
            onStopYoloDemo={() => {
              setYoloControlBusy(true);
              postJson<YoloDemoStatusResponse>("/api/v1/experiments/yolo-demo/stop")
                .then(async (status) => {
                  setYoloDemoStatus(status);
                  setFanLiveCurrent(null);
                  setFanLiveSeries([]);
                  await loadYoloDemoEvents();
                })
                .catch((e) =>
                  setFanExperimentError(e instanceof Error ? e.message : String(e)),
                )
                .finally(() => {
                  setYoloControlBusy(false);
                });
            }}
            captureRunning={fanCaptureRunning}
            onStartCapture={() => {
              setFanExperimentLoading(true);
              setFanCaptureRunning(true);
              setYoloDemoEvents((prev) => [
                ...prev,
                {
                  time: new Date().toISOString(),
                  level: "info" as const,
                  event: "capture_resumed",
                  message: "Resumed live capture updates",
                },
              ].slice(-50));
            }}
            onPauseCapture={() => {
              setFanCaptureRunning(false);
              setYoloDemoEvents((prev) => [
                ...prev,
                {
                  time: new Date().toISOString(),
                  level: "warn" as const,
                  event: "capture_paused",
                  message: "Paused live capture updates",
                },
              ].slice(-50));
            }}
            demoWorkflowBusy={demoWorkflowBusy}
            yoloControlBusy={yoloControlBusy}
          />
        )}
      </div>
    </main>
  );
}
