"""Ad-hoc micro-benchmark: routing cost with 30 regex matchers.

Measures ONLY the Python-side routing overhead this package adds per request
(compiled-regex fullmatch scans + priority-ordered plan walk). The database
win vs DRF SearchFilter is separate and dominates in practice.

Run: python benchmarks/bench_routing_30.py
"""

from __future__ import annotations

import os
import re
import sys
import time

import django
from django.conf import settings

# Configure a bare-minimum Django so importing the package (which pulls in the
# DRF backend) works without a project settings module.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
if not settings.configured:
    settings.configure(INSTALLED_APPS=[], DATABASES={}, REST_FRAMEWORK={})
    django.setup()

from dynamic_search.matchers import build_matcher  # noqa: E402



N = 30
ITERS = 1_000_000

# 30 realistic-ish anchored patterns. Only the last one matches our probe value,
# so this is the WORST case: every earlier matcher runs and fails.
patterns = {f"code_{i}": rf"^X{i}\d{{{i % 6 + 3}}}$" for i in range(N - 1)}
patterns["national_code"] = r"^\d{10}$"

# --- plan A: plain compiled-regex matchers (no pre-filters) ------------------
plain = [build_matcher(name, pat, "exact") for name, pat in patterns.items()]

# --- plan B: same, but with O(1) length/prefix pre-filters -------------------
prefiltered = [
    build_matcher(name, pat, "exact", min_len=3, max_len=12, prefix=("X" if name.startswith("code") else None))
    for name, pat in patterns.items()
]

# Worst-case probe: a 10-digit national code — must scan all 29 X-patterns first.
PROBE = "1234567890"


def route(plan, value):
    for m in plan:
        if m.matches(value):
            return m.name
    return None


def bench(plan, label):
    # correctness
    assert route(plan, PROBE) == "national_code"
    start = time.perf_counter()
    for _ in range(ITERS):
        route(plan, PROBE)
    elapsed = time.perf_counter() - start
    per_req_us = elapsed / ITERS * 1e6
    print(f"{label:28} {per_req_us:7.3f} µs/request   "
          f"({1e6 / per_req_us:,.0f} routes/sec, single core)")


if __name__ == "__main__":
    print(f"{N} matchers, worst-case probe (only the LAST matcher matches)\n")
    bench(plain, "compiled regex (no prefilter)")
    bench(prefiltered, "compiled regex + prefilter")

    # A single failed re.compile-per-request (what naive code might do) for scale.
    raw = list(patterns.values())
    start = time.perf_counter()
    loops = ITERS // 20
    for _ in range(loops):
        for p in raw:
            re.compile(p).fullmatch(PROBE)
    elapsed = time.perf_counter() - start
    print(f"\n{'NAIVE re.compile/request':28} "
          f"{elapsed / loops * 1e6:7.3f} µs/request   (what we AVOID by caching)")
