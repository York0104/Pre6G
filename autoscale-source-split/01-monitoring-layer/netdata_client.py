import os
import time
import re
import urllib.request
from typing import Dict, List, Tuple, Optional

class NetdataClient:
    """
    以 Netdata /api/v1/allmetrics?format=prometheus 拉 cadvisor 指標：
      - CPU: counter (seconds_total) -> 用差分/dt 算 cores_used
      - MEM: gauge (bytes) -> 直接取
    並且嚴格只取「pod slice」行，避免 container scope 造成 double count：
      - namespace != "[none]"
      - pod       != "[none]"
      - id endswith ".slice"
      - 排除 id endswith ".scope"
    """

    def __init__(self, base_url: Optional[str] = None, timeout_s: int = 5):
        self.base_url = base_url or os.getenv("NETDATA_URL", "http://netdata.netdata.svc:19999")
        self.timeout_s = timeout_s
        self._prev: Dict[str, Tuple[float, float]] = {}

    def _http_get(self, path: str) -> str:
        url = self.base_url.rstrip("/") + path
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def fetch_allmetrics_prom(self) -> str:
        return self._http_get("/api/v1/allmetrics?format=prometheus")

    @staticmethod
    def _parse_prometheus_text(text: str, metric_name: str) -> List[Tuple[Dict[str, str], float]]:
        out: List[Tuple[Dict[str, str], float]] = []
        # metric{...} value [timestamp]
        pat = re.compile(rf'^{re.escape(metric_name)}(\{{.*\}})?\s+([-+]?\d+(\.\d+)?([eE][-+]?\d+)?)')
        label_pat = re.compile(r'(\w+)="((?:\\.|[^"\\])*)"')

        for line in text.splitlines():
            if not line or line[0] == "#":
                continue
            m = pat.match(line)
            if not m:
                continue

            label_blob = m.group(1)
            val = float(m.group(2))
            labels: Dict[str, str] = {}

            if label_blob:
                inner = label_blob[1:-1]
                for km in label_pat.finditer(inner):
                    k = km.group(1)
                    v = km.group(2)
                    # unescape \" etc
                    v = bytes(v, "utf-8").decode("unicode_escape")
                    labels[k] = v

            out.append((labels, val))
        return out

    @staticmethod
    def _is_pod_slice(labels: Dict[str, str]) -> bool:
        ns = labels.get("namespace")
        pod = labels.get("pod")
        cid = labels.get("id", "")

        if ns in (None, "", "[none]"):
            return False
        if pod in (None, "", "[none]"):
            return False

        # 只保留 pod slice（.slice），排除 container scope（.scope）
        if cid.endswith(".scope"):
            return False
        if not cid.endswith(".slice"):
            return False

        return True

    def _rate(self, key: str, current_value: float, now_ts: float) -> Optional[float]:
        prev = self._prev.get(key)
        self._prev[key] = (now_ts, current_value)

        if not prev:
            return None
        prev_ts, prev_val = prev
        dt = now_ts - prev_ts
        if dt <= 0:
            return None
        dv = current_value - prev_val
        if dv < 0:
            # counter reset
            return None
        return dv / dt

    # ===== Public APIs for aggregator =====

    def pod_cpu_cores(self, prom_text: str, metric_cpu_counter: str, namespace: str, pod: str) -> Optional[float]:
        """
        回傳某 pod 的 CPU 使用 cores（約 1s rate），單位 core
        只取 pod slice 行（避免 double count）。
        """
        now = time.time()
        samples = self._parse_prometheus_text(prom_text, metric_cpu_counter)

        for labels, counter_seconds in samples:
            if not self._is_pod_slice(labels):
                continue
            if labels.get("namespace") != namespace:
                continue
            if labels.get("pod") != pod:
                continue

            # 以 pod slice id 當 key（穩定）
            key = f"cpu::{namespace}::{pod}::{labels.get('id','')}"
            r = self._rate(key, counter_seconds, now)
            return r  # 單一 pod slice 行，直接回傳

        return None

    def pod_mem_bytes(self, prom_text: str, metric_mem_gauge: str, namespace: str, pod: str) -> Optional[int]:
        """
        回傳某 pod 的 working set bytes（gauge），只取 pod slice 行。
        """
        samples = self._parse_prometheus_text(prom_text, metric_mem_gauge)

        for labels, val in samples:
            if not self._is_pod_slice(labels):
                continue
            if labels.get("namespace") != namespace:
                continue
            if labels.get("pod") != pod:
                continue
            return int(val)

        return None

    def namespace_cpu_cores(self, prom_text: str, metric_cpu_counter: str, namespace: str) -> Optional[float]:
        """
        namespace CPU = 其下所有 pod slice cores sum。
        第一次呼叫可能因 rate 尚未 warm up 而 None；第二秒起會有值。
        """
        now = time.time()
        samples = self._parse_prometheus_text(prom_text, metric_cpu_counter)

        total = 0.0
        hit = False
        for labels, counter_seconds in samples:
            if not self._is_pod_slice(labels):
                continue
            if labels.get("namespace") != namespace:
                continue

            pod = labels.get("pod", "")
            key = f"ns_cpu::{namespace}::{pod}::{labels.get('id','')}"
            r = self._rate(key, counter_seconds, now)
            if r is None:
                continue
            hit = True
            total += r

        return total if hit else None

    def namespace_mem_bytes(self, prom_text: str, metric_mem_gauge: str, namespace: str) -> Optional[int]:
        """
        namespace MEM = 其下所有 pod slice working set sum。
        """
        samples = self._parse_prometheus_text(prom_text, metric_mem_gauge)

        total = 0.0
        hit = False
        for labels, val in samples:
            if not self._is_pod_slice(labels):
                continue
            if labels.get("namespace") != namespace:
                continue
            hit = True
            total += val

        return int(total) if hit else None
