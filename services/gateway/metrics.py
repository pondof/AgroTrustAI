"""
AgroTrust AI – Métricas Prometheus-compatible para o Gateway.

Mantém implementação interna leve (sem dependência de prometheus_client) —
expõe contadores de requests e histograma de latência via texto Prometheus.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict


class _Histogram:
    """Histograma minimalista com buckets fixos (segundos)."""

    BUCKETS_SEC: tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

    def __init__(self) -> None:
        self._counts: list[int] = [0] * len(self.BUCKETS_SEC)
        self._sum: float = 0.0
        self._observations: int = 0
        self._lock = threading.Lock()

    def observe(self, value_sec: float) -> None:
        with self._lock:
            self._sum += value_sec
            self._observations += 1
            for idx, edge in enumerate(self.BUCKETS_SEC):
                if value_sec <= edge:
                    self._counts[idx] += 1

    def render(self, name: str, labels: str) -> list[str]:
        with self._lock:
            lines: list[str] = []
            cumulative = 0
            for idx, edge in enumerate(self.BUCKETS_SEC):
                cumulative += self._counts[idx]
                lines.append(f'{name}_bucket{{le="{edge}",{labels}}} {cumulative}')
            lines.append(f'{name}_bucket{{le="+Inf",{labels}}} {self._observations}')
            lines.append(f"{name}_sum{{{labels}}} {self._sum:.6f}")
            lines.append(f"{name}_count{{{labels}}} {self._observations}")
            return lines


class GatewayMetrics:
    """Singleton de métricas. Use `metrics.observe_request(...)` em hooks HTTP."""

    def __init__(self) -> None:
        self._req_total: dict[tuple[str, str, int], int] = defaultdict(int)
        self._req_latency: dict[tuple[str, str], _Histogram] = defaultdict(_Histogram)
        self._lock = threading.Lock()

    def observe_request(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_sec: float,
    ) -> None:
        key_total = (method, path, status_code)
        key_lat = (method, path)
        with self._lock:
            self._req_total[key_total] += 1
        self._req_latency[key_lat].observe(duration_sec)

    def render_prometheus(self) -> str:
        out: list[str] = []
        out.append("# HELP gateway_requests_total Total HTTP requests.")
        out.append("# TYPE gateway_requests_total counter")
        with self._lock:
            for (method, path, code), n in self._req_total.items():
                out.append(f'gateway_requests_total{{method="{method}",path="{path}",status="{code}"}} {n}')
        out.append("# HELP gateway_request_duration_seconds Latency per request.")
        out.append("# TYPE gateway_request_duration_seconds histogram")
        for (method, path), hist in self._req_latency.items():
            labels = f'method="{method}",path="{path}"'
            out.extend(hist.render("gateway_request_duration_seconds", labels))
        return "\n".join(out) + "\n"


_metrics: GatewayMetrics | None = None


def get_metrics() -> GatewayMetrics:
    global _metrics
    if _metrics is None:
        _metrics = GatewayMetrics()
    return _metrics


class Timer:
    """Context manager para medir duração: `with Timer() as t: ... ; t.duration`."""

    def __enter__(self) -> Timer:
        self._start = time.monotonic()
        return self

    def __exit__(self, *_: object) -> None:
        self.duration = time.monotonic() - self._start
