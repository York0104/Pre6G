import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
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

type Health = "healthy" | "degraded" | "offline";
type ActiveTab = "monitor" | "fan-experiment";
type FanMode =
  | "GPU_DEFAULT"
  | "FIXED_5"
  | "FIXED_15"
  | "FIXED_20"
  | "FIXED_25";

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
  time: string;
  gpu_temp: number;
  fan_pct: number;
  sm_clock: number;
  gpu_util: number;
  server_latency: number;
  e2e_latency: number;
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
  if (mode === "FIXED_5") return "FIXED_5";
  if (mode === "FIXED_15") return "FIXED_15";
  if (mode === "FIXED_20") return "FIXED_20";
  if (mode === "FIXED_25") return "FIXED_25";
  return "FIXED_25";
}

function modeFanPercent(mode: FanMode, fallbackPercent: number): number {
  if (mode === "GPU_DEFAULT") return fallbackPercent;
  if (mode === "FIXED_5") return 5;
  if (mode === "FIXED_15") return 15;
  if (mode === "FIXED_20") return 20;
  return 25;
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
}: {
  label: string;
  value: string;
  tone?: "blue" | "green" | "orange" | "gray";
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
    <div className={`rounded-2xl border bg-slate-950/70 p-4 shadow-lg ${toneClass}`}>
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 font-mono text-2xl font-semibold">{value}</div>
    </div>
  );
}

function formatMaybeMs(value?: number | null): string {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return "N/A";
  }
  return `${value.toFixed(1)} ms`;
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
          <span className="text-slate-400">GPU FB Used</span>
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
            title="GPU Framebuffer Used"
            data={history}
            unit=" MiB"
            lines={[
              { key: "gpuFbUsed", name: "GPU FB Used", stroke: "#a78bfa" },
            ]}
          />
        </div>
      </div>
    </div>
  );
}

function FanExperimentPage({
  data,
  liveCurrent,
  liveSeries,
  yoloDemo,
  yoloEvents,
  loading,
  error,
  fanControl,
  onFanModeChange,
  onStartYoloDemo,
  onStopYoloDemo,
  captureRunning,
  onStartCapture,
  onPauseCapture,
}: {
  data: FanCycleLatestResponse | null;
  liveCurrent: FanCycleCurrentMetrics | null;
  liveSeries: FanLivePoint[];
  yoloDemo: YoloDemoStatusResponse | null;
  yoloEvents: YoloDemoEvent[];
  loading: boolean;
  error: string;
  fanControl: FanControlSelection;
  onFanModeChange: (mode: FanMode) => void;
  onStartYoloDemo: () => void;
  onStopYoloDemo: () => void;
  captureRunning: boolean;
  onStartCapture: () => void;
  onPauseCapture: () => void;
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

  if (!data || data.timeseries.length === 0) {
    return (
      <section className="rounded-2xl border border-slate-800 bg-slate-950/60 p-8 text-slate-400">
        No completed fan-cycle experiment run found yet.
      </section>
    );
  }

  const { run, config, current, phase_summary } = data;
  const displayCurrent = liveCurrent || current;
  const displaySeries = liveSeries.length > 1 ? liveSeries : data.timeseries;
  const runtimeRunId = yoloDemo?.run_id || run.run_id;
  const runtimeFocusPod = yoloDemo?.focus_pod || run.focus_pod;
  const runtimeTargetUrl = yoloDemo?.target_url || run.target_url;
  const yoloDemoRunning =
    yoloDemo?.status === "running" || yoloDemo?.status === "starting";
  const latencySeries = yoloDemoRunning ? displaySeries : [];
  const activeServerLatency = yoloDemoRunning ? displayCurrent.server_latency_ms : null;
  const activeE2ELatency = yoloDemoRunning ? displayCurrent.e2e_latency_ms : null;
  const selectedFanPercent = modeFanPercent(fanControl.mode, config.fixed_fan_pct);
  const currentPhaseSummary =
    phase_summary.find(
      (item) =>
        item.cycle_index === run.current_cycle &&
        item.phase === run.current_phase,
    ) || phase_summary[phase_summary.length - 1];
  const thermalRisk =
    displayCurrent.gpu_temp_c >= config.fault_temp_target_c
      ? "Thermal target exceeded"
      : displayCurrent.gpu_temp_c > config.normal_temp_max_c
        ? "Above normal thermal band"
        : "Within expected thermal band";

  return (
    <section className="space-y-6">
      <SectionCard
        title="Fan-Cycle Experiment Console"
        action={
          <div className="rounded-full border border-sky-500/30 bg-sky-500/10 px-3 py-1 text-xs uppercase text-sky-300">
            {run.status}
          </div>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <div className="text-xs uppercase tracking-wide text-slate-500">Target Node</div>
            <div className="mt-2 text-lg font-semibold text-slate-100">{run.target_node}</div>
            <div className="mt-1 text-sm text-slate-400">Worker / {run.gpu_name}</div>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <div className="text-xs uppercase tracking-wide text-slate-500">Run Status</div>
            <div className="mt-2 text-lg font-semibold text-orange-300">{run.status}</div>
            <div className="mt-1 text-sm text-slate-400">{run.current_phase}</div>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <div className="text-xs uppercase tracking-wide text-slate-500">Current GPU Temp</div>
            <div className="mt-2 text-lg font-semibold text-orange-200">
              {displayCurrent.gpu_temp_c.toFixed(1)}°C
            </div>
            <div className="mt-1 text-sm text-slate-400">{thermalRisk}</div>
          </div>
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <div className="text-xs uppercase tracking-wide text-slate-500">Current E2E Latency</div>
            <div className="mt-2 text-lg font-semibold text-slate-100">
              {formatMaybeMs(activeE2ELatency)}
            </div>
            <div className="mt-1 text-sm text-slate-400">
              {activeServerLatency === null
                ? "YOLO demo is not running"
                : `Server ${activeServerLatency.toFixed(1)} ms`}
            </div>
          </div>
        </div>
      </SectionCard>

      <SectionCard title="Thermal State">
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <SummaryCard label="GPU Temp" value={`${displayCurrent.gpu_temp_c.toFixed(1)}°C`} tone="orange" />
          <SummaryCard label="Fan Speed" value={`${displayCurrent.fan_pct.toFixed(0)}%`} tone="gray" />
          <SummaryCard label="SM Clock" value={`${displayCurrent.sm_clock_mhz.toFixed(0)} MHz`} />
          <SummaryCard label="GPU Util" value={`${displayCurrent.gpu_util_pct.toFixed(1)}%`} tone="green" />
          <SummaryCard label="Server Latency" value={formatMaybeMs(activeServerLatency)} />
          <SummaryCard label="E2E Latency" value={formatMaybeMs(activeE2ELatency)} tone="blue" />
        </div>
        <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/70 p-4 text-xs text-slate-400">
          {captureRunning
            ? "Live refresh is enabled. These cards, charts, and YOLO demo events update every 1 second."
            : "Live refresh is paused. Resume capture to continue syncing the latest experiment result."}
        </div>
      </SectionCard>

      <div className="grid grid-cols-[minmax(320px,0.92fr)_minmax(420px,1.08fr)] items-start gap-6 overflow-x-auto">
        <div className="min-w-0 space-y-6">
          <SectionCard title="YOLO Service">
            <div className="space-y-3 text-sm text-slate-300">
              <div className="rounded-xl bg-slate-900/60 p-3">
                <div className="text-xs uppercase tracking-wide text-slate-500">Current Run</div>
                <div className="mt-1 break-all font-mono text-xs text-slate-100">{runtimeRunId}</div>
              </div>
              <div className="rounded-xl bg-slate-900/60 p-3">
                <div className="text-xs uppercase tracking-wide text-slate-500">Focus Pod</div>
                <div className="mt-1 break-all font-mono text-xs text-slate-100">{runtimeFocusPod || "N/A"}</div>
              </div>
              <div className="rounded-xl bg-slate-900/60 p-3">
                <div className="text-xs uppercase tracking-wide text-slate-500">Target URL</div>
                <div className="mt-1 break-all font-mono text-xs text-slate-100">{runtimeTargetUrl || "N/A"}</div>
              </div>
              <div className="rounded-xl bg-slate-900/60 p-3">
                <div className="text-xs uppercase tracking-wide text-slate-500">YOLO Demo Status</div>
                <div className="mt-1 flex items-center gap-2 font-semibold text-slate-100">
                  <span
                    className={`h-2.5 w-2.5 rounded-full ${
                      yoloDemoRunning ? "bg-emerald-400" : "bg-slate-500"
                    }`}
                  />
                  <span>{yoloDemoRunning ? "Running" : "Stopped"}</span>
                </div>
                <div className="mt-1 text-xs text-slate-400">
                  {yoloDemo?.message || "Start the demo to keep single-pod YOLO inference and GPU bgload running."}
                </div>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <button
                  onClick={onStartYoloDemo}
                  disabled={yoloDemoRunning}
                  className={`rounded-xl border px-3 py-2 text-sm transition ${
                    yoloDemoRunning
                      ? "border-slate-700 bg-slate-900/60 text-slate-500"
                      : "border-red-500/40 bg-red-500/15 text-red-200 hover:border-red-400"
                  }`}
                >
                  Start YOLO Demo
                </button>
                <button
                  onClick={onStopYoloDemo}
                  disabled={!yoloDemoRunning}
                  className={`rounded-xl border px-3 py-2 text-sm transition ${
                    yoloDemoRunning
                      ? "border-orange-500/40 bg-orange-500/15 text-orange-200 hover:border-orange-400"
                      : "border-slate-700 bg-slate-900/60 text-slate-500"
                  }`}
                >
                  Stop YOLO Demo
                </button>
                <button
                  onClick={onStartCapture}
                  className={`rounded-xl border px-3 py-2 text-sm transition ${
                    captureRunning
                      ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-200"
                      : "border-slate-700 bg-slate-900/60 text-slate-500 hover:border-slate-500"
                  }`}
                >
                  Start E2E Capture
                </button>
                <button
                  onClick={onPauseCapture}
                  className={`rounded-xl border px-3 py-2 text-sm transition ${
                    captureRunning
                      ? "border-slate-700 bg-slate-900/60 text-slate-500 hover:border-slate-500"
                      : "border-orange-500/40 bg-orange-500/15 text-orange-200"
                  }`}
                >
                  Pause Capture
                </button>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-xl bg-slate-900/60 p-3">
                  <div className="text-xs text-slate-500">Current p95-like Signal</div>
                  <div className="mt-1 font-mono text-xl text-slate-100">
                    {currentPhaseSummary?.server_latency_ms_p95.toFixed(0) || "0"} ms
                  </div>
                </div>
                <div className="rounded-xl bg-slate-900/60 p-3">
                  <div className="text-xs text-slate-500">Current E2E</div>
                  <div className="mt-1 font-mono text-xl text-slate-100">
                    {activeE2ELatency === null ? "N/A" : `${activeE2ELatency.toFixed(0)} ms`}
                  </div>
                </div>
              </div>
            </div>
          </SectionCard>

          <SectionCard title="Experiment Control">
            <div className="mb-4 space-y-3">
              <div className="text-xs uppercase tracking-wide text-slate-500">Fan Mode</div>
              <div className="grid gap-2 sm:grid-cols-2">
                {(
                  [
                    "GPU_DEFAULT",
                    "FIXED_5",
                    "FIXED_15",
                    "FIXED_20",
                    "FIXED_25",
                  ] as FanMode[]
                ).map((mode) => (
                  <button
                    key={mode}
                    onClick={() => onFanModeChange(mode)}
                    className={`rounded-xl border px-3 py-2 text-left text-sm transition ${
                      fanControl.mode === mode
                        ? "border-orange-500/40 bg-orange-500/15 text-orange-200"
                        : "border-slate-700 bg-slate-900/60 text-slate-300 hover:border-slate-500"
                    }`}
                  >
                    {modeLabel(mode)}
                  </button>
                ))}
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-xl bg-slate-900/60 p-3 text-sm text-slate-300">
                  Selected Mode: {modeLabel(fanControl.mode)}
                </div>
                <div className="rounded-xl bg-slate-900/60 p-3 text-sm text-slate-300">
                  Effective Fan %: {selectedFanPercent}%
                </div>
              </div>
            </div>
          </SectionCard>
        </div>

        <div className="min-w-0 space-y-6">
          <MultiLineChart
            title="GPU Temperature / Fan Speed"
            data={displaySeries}
            lines={[
              { key: "gpu_temp", name: "GPU Temp", stroke: "#f97316" },
              { key: "fan_pct", name: "Fan %", stroke: "#38bdf8" },
            ]}
            height={220}
          />
          <MultiLineChart
            title="SM Clock"
            data={displaySeries}
            lines={[
              { key: "sm_clock", name: "SM Clock", stroke: "#a78bfa" },
            ]}
            height={220}
          />
          <MultiLineChart
            title="GPU Utilization"
            data={displaySeries}
            lines={[
              { key: "gpu_util", name: "GPU Util", stroke: "#22c55e" },
            ]}
            height={220}
          />
          <MultiLineChart
            title="Server Latency"
            data={latencySeries}
            unit=" ms"
            lines={[
              { key: "server_latency", name: "Server Latency", stroke: "#f59e0b" },
            ]}
            height={220}
          />
        </div>
      </div>

      <SectionCard title="Event Timeline">
        <div className="space-y-4">
          {yoloEvents.map((event) => (
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
  const [fanLiveCurrent, setFanLiveCurrent] = useState<FanCycleCurrentMetrics | null>(null);
  const [fanLiveSeries, setFanLiveSeries] = useState<FanLivePoint[]>([]);
  const [yoloDemoStatus, setYoloDemoStatus] = useState<YoloDemoStatusResponse | null>(null);
  const [yoloDemoEvents, setYoloDemoEvents] = useState<YoloDemoEvent[]>([]);

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

  async function loadFanExperiment() {
    try {
      setFanExperimentError("");
      const data = await fetchJson<FanCycleLatestResponse>("/api/v1/experiments/fan-cycle/latest");
      setFanExperiment(data);
    } catch (e) {
      setFanExperiment(null);
      setFanExperimentError(e instanceof Error ? e.message : String(e));
    } finally {
      setFanExperimentLoading(false);
    }
  }

  async function loadFanLive() {
    const data = await fetchJson<FanCycleLiveResponse>("/api/v1/experiments/fan-cycle/live");
    setFanLiveCurrent(data.current);
    const point: FanLivePoint = {
      time: new Date(data.generated_at * 1000).toLocaleTimeString(),
      gpu_temp: data.current.gpu_temp_c,
      fan_pct: data.current.fan_pct,
      sm_clock: data.current.sm_clock_mhz,
      gpu_util: data.current.gpu_util_pct,
      server_latency: data.current.server_latency_ms,
      e2e_latency: data.current.e2e_latency_ms,
    };
    setFanLiveSeries((prev) => [...prev, point].slice(-60));
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

  async function loadAll() {
    try {
      setError("");
      await loadInventory();
      await loadStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    loadAll();
    loadFanExperiment();

    const statusTimer = window.setInterval(() => {
      loadStatus().catch((e) =>
        setError(e instanceof Error ? e.message : String(e)),
      );
    }, 3000);

    const inventoryTimer = window.setInterval(() => {
      loadInventory().catch((e) =>
        setError(e instanceof Error ? e.message : String(e)),
      );
    }, 60000);

    return () => {
      window.clearInterval(statusTimer);
      window.clearInterval(inventoryTimer);
    };
  }, []);

  useEffect(() => {
    if (!fanCaptureRunning) {
      return;
    }

    loadFanExperiment().catch((e) =>
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

    const cpuVals = nodes
      .map((n) => n.status?.cpu?.usage_percent)
      .filter((v): v is number => typeof v === "number");
    const memVals = nodes
      .map((n) => n.status?.memory?.usage_percent)
      .filter((v): v is number => typeof v === "number");

    const avgCpu =
      cpuVals.length > 0
        ? cpuVals.reduce((a, b) => a + b, 0) / cpuVals.length
        : 0;

    const avgMem =
      memVals.length > 0
        ? memVals.reduce((a, b) => a + b, 0) / memVals.length
        : 0;

    return { total, healthy, degraded, offline, avgCpu, avgMem };
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
              <SummaryCard label="Avg CPU" value={`${summary.avgCpu.toFixed(1)}%`} />
              <SummaryCard label="Avg Memory" value={`${summary.avgMem.toFixed(1)}%`} />
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

        {activeTab === "fan-experiment" && (
          <FanExperimentPage
            data={fanExperiment}
            liveCurrent={fanLiveCurrent}
            liveSeries={fanLiveSeries}
            yoloDemo={yoloDemoStatus}
            yoloEvents={yoloDemoEvents}
            loading={fanExperimentLoading}
            error={fanExperimentError}
            fanControl={fanControl}
            onFanModeChange={(mode) => {
              setFanControl({ mode });
              postJson<YoloDemoStatusResponse>(`/api/v1/experiments/yolo-demo/fan-mode/${mode}`)
                .then(setYoloDemoStatus)
                .then(() => loadYoloDemoEvents())
                .catch((e) =>
                  setFanExperimentError(e instanceof Error ? e.message : String(e)),
                );
            }}
            onStartYoloDemo={() => {
              postJson<YoloDemoStatusResponse>("/api/v1/experiments/yolo-demo/start")
                .then(setYoloDemoStatus)
                .then(() => loadYoloDemoEvents())
                .catch((e) =>
                  setFanExperimentError(e instanceof Error ? e.message : String(e)),
                );
            }}
            onStopYoloDemo={() => {
              postJson<YoloDemoStatusResponse>("/api/v1/experiments/yolo-demo/stop")
                .then(setYoloDemoStatus)
                .then(() => loadYoloDemoEvents())
                .catch((e) =>
                  setFanExperimentError(e instanceof Error ? e.message : String(e)),
                );
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
          />
        )}
      </div>
    </main>
  );
}
