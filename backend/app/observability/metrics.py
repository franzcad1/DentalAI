"""In-app metrics (M1b): counters and histograms in fixed one-minute buckets.

Memory is bounded (max_buckets minutes of history). Data is lost on restart,
which the /ops page states. Labels must be fixed names or route templates,
never raw paths or ids.
"""

import threading
import time
from collections import OrderedDict, deque
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

EDGES_MS = [5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 30000]

Key = Tuple[str, Tuple[Tuple[str, str], ...]]


def _key(name: str, labels: Dict[str, Any]) -> Key:
    return (name, tuple(sorted((k, str(v)) for k, v in labels.items())))


def _matches(key: Key, flt: Dict[str, Any]) -> bool:
    labels = dict(key[1])
    return all(labels.get(k) == str(v) for k, v in flt.items())


class Metrics:
    def __init__(self, clock: Callable[[], float] = time.time,
                 bucket_s: int = 60, max_buckets: int = 360) -> None:
        self._clock = clock
        self._bucket_s = bucket_s
        self._max = max_buckets
        self._lock = threading.Lock()
        self._buckets: "OrderedDict[int, Dict[str, Dict[Key, Any]]]" = OrderedDict()
        self.errors: Deque[Dict[str, Any]] = deque(maxlen=50)
        self.started_at = clock()

    def _bucket(self) -> Dict[str, Dict[Key, Any]]:
        idx = int(self._clock() // self._bucket_s)
        b = self._buckets.get(idx)
        if b is None:
            b = {"c": {}, "h": {}}
            self._buckets[idx] = b
            while len(self._buckets) > self._max:
                self._buckets.popitem(last=False)
        return b

    def inc(self, name: str, n: int = 1, **labels: Any) -> None:
        with self._lock:
            c = self._bucket()["c"]
            k = _key(name, labels)
            c[k] = c.get(k, 0) + n

    def observe(self, name: str, value_ms: float, **labels: Any) -> None:
        with self._lock:
            h = self._bucket()["h"]
            k = _key(name, labels)
            counts = h.setdefault(k, [0] * (len(EDGES_MS) + 1))
            for i, edge in enumerate(EDGES_MS):
                if value_ms <= edge:
                    counts[i] += 1
                    break
            else:
                counts[-1] += 1

    def record_error(self, **info: Any) -> None:
        with self._lock:
            self.errors.append({"at": int(self._clock()), **info})

    def _window(self, window_s: int) -> List[Dict[str, Dict[Key, Any]]]:
        floor = int(self._clock() // self._bucket_s) - max(1, window_s // self._bucket_s) + 1
        return [b for i, b in self._buckets.items() if i >= floor]

    def count(self, name: str, window_s: int = 300, **flt: Any) -> int:
        with self._lock:
            total = 0
            for b in self._window(window_s):
                for k, v in b["c"].items():
                    if k[0] == name and _matches(k, flt):
                        total += v
            return total

    def _merged_hist(self, name: str, window_s: int, flt: Dict[str, Any]) -> List[int]:
        merged = [0] * (len(EDGES_MS) + 1)
        for b in self._window(window_s):
            for k, counts in b["h"].items():
                if k[0] == name and _matches(k, flt):
                    merged = [a + c for a, c in zip(merged, counts)]
        return merged

    def hist_count(self, name: str, window_s: int = 300, **flt: Any) -> int:
        with self._lock:
            return sum(self._merged_hist(name, window_s, flt))

    def quantile(self, name: str, q: float, window_s: int = 300, **flt: Any) -> Optional[float]:
        """Upper bucket edge (ms) containing the q-th quantile; None if no data."""
        with self._lock:
            counts = self._merged_hist(name, window_s, flt)
        total = sum(counts)
        if total == 0:
            return None
        target, cum = q * total, 0
        for i, c in enumerate(counts):
            cum += c
            if cum >= target:
                return float(EDGES_MS[i]) if i < len(EDGES_MS) else float("inf")
        return float("inf")

    def label_values(self, name: str, label: str, window_s: int = 300) -> List[str]:
        with self._lock:
            seen = set()
            for b in self._window(window_s):
                for table in (b["c"], b["h"]):
                    for k in table:
                        if k[0] == name:
                            v = dict(k[1]).get(label)
                            if v is not None:
                                seen.add(v)
            return sorted(seen)

    def summary(self, window_s: int = 300) -> Dict[str, Any]:
        routes = self.label_values("http_request_duration_ms", "route", window_s)
        return {
            "window_seconds": window_s,
            "since_start_seconds": int(self._clock() - self.started_at),
            "note": "In-memory only: resets on restart or redeploy.",
            "http": {
                "requests_by_status_class": {
                    sc: self.count("http_requests_total", window_s, status_class=sc)
                    for sc in ("2xx", "3xx", "4xx", "5xx")
                },
                "latency_ms_by_route": {
                    r: {
                        "count": self.hist_count("http_request_duration_ms", window_s, route=r),
                        "p50": self.quantile("http_request_duration_ms", 0.5, window_s, route=r),
                        "p95": self.quantile("http_request_duration_ms", 0.95, window_s, route=r),
                    }
                    for r in routes
                },
            },
            "agent": {
                "turns": {o: self.count("agent_turns_total", window_s, outcome=o)
                          for o in ("ok", "error")},
                "llm_call_p95_ms": self.quantile("agent_llm_call_duration_ms", 0.95, window_s),
                "groq_429": self.count("agent_groq_429_total", window_s),
                "tool_parse_errors": self.count("agent_tool_parse_errors_total", window_s),
                "tokens": {k: self.count("agent_tokens_total", window_s, kind=k)
                           for k in ("prompt", "completion")},
                "tool_calls": {o: self.count("agent_tool_calls_total", window_s, outcome=o)
                               for o in ("ok", "error", "unknown_tool")},
            },
            "rag": {o: self.count("rag_lookups_total", window_s, outcome=o)
                    for o in ("hit", "no_hit", "unavailable")},
            "scheduler": {o: self.count("scheduler_job_runs_total", window_s, outcome=o)
                          for o in ("ok", "error")},
            "recent_errors": list(self.errors)[-20:],
        }


metrics = Metrics()
