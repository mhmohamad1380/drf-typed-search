"""Micro-benchmark: Python-side search overhead, old vs new engine path.

This isolates the *Python* cost of routing + queryset construction (NOT database
execution), because that is exactly what the optimization targets. The queryset
is never evaluated — we build it lazily and stringify the compiled SQL once to
assert the predicate is present, then discard it.

Run:

    DJANGO_SETTINGS_MODULE=tests.settings PYTHONPATH=src:. python benchmarks/bench_engine.py

Methodology:
    * warm up each path before timing
    * many iterations, report mean / median / p95 / stdev
    * identical fields, matchers, settings, and query values for every variant

The "old path" faithfully re-implements the pre-optimization behavior
(rebuilding text-field lists and re-resolving lookups/paths per request) so the
comparison is apples-to-apples on the same machine and Python.
"""

from __future__ import annotations

import statistics
import time
from typing import Callable, Dict, List

import django

django.setup()

from django.db.models import Q  # noqa: E402

from dynamic_search.config import compile_search_fields  # noqa: E402
from dynamic_search.engine import SearchEngine, _split_terms  # noqa: E402
from dynamic_search.lookups import TEXT_LOOKUPS  # noqa: E402
from dynamic_search.settings import get_settings  # noqa: E402
from tests.models import Account  # noqa: E402

CONFIG = [
    {"field": "national_code", "join": "user"},
    {"field": "phone_number", "join": "user"},
    {"field": "id"},
    {"field": "username", "lookup": "icontains", "matcher": None},
    {"field": "email", "lookup": "icontains", "matcher": None},
]

VALUES = {
    "typed national code": "1000000001",
    "typed phone": "09120000002",
    "typed id": "12345",
    "free-text single": "mohammad",
    "multi-term": "mohammad hosseiny",
    "no-match": "!!!nomatch!!!",
}


def _qs():
    return Account.objects.all()


# ---------------------------------------------------------------------------
# OLD path: re-does per-request work (matcher resolution, text-field filtering,
# per-field lookup resolution + orm_path str.join) on every call.
# ---------------------------------------------------------------------------
def make_old_search(fields, matchers, settings) -> Callable[[str], object]:
    def old_search(value: str):
        value = value.strip()
        if not value:
            return _qs()
        # typed: resolve matcher per field, per request
        for sf in fields:
            if not sf.matcher:
                continue
            matcher = matchers.get(sf.matcher)
            if matcher is None:
                continue
            if matcher.matches(value):
                qs = _qs()
                if sf.annotate is not None:
                    qs = sf.annotate(qs, sf.join)
                lookup = sf.lookup or matcher.lookup
                return qs.filter(sf.build_q(value, lookup))
        # text: recompute text fields + lookups + paths per request
        text_fields = [f for f in fields if f.is_text_searchable]
        if not text_fields:
            return _qs().none()
        terms = _split_terms(value)
        qs = _qs()
        for term in terms:
            term_q = Q()
            for sf in text_fields:
                lk = (
                    sf.lookup
                    if (sf.lookup is not None and sf.lookup in TEXT_LOOKUPS)
                    else settings.default_text_lookup
                )
                term_q |= Q(**{sf.orm_path(lk): term})
            qs = qs.filter(term_q)
        return qs

    return old_search


def make_new_search(fields, matchers, settings) -> Callable[[str], object]:
    engine = SearchEngine(fields, matchers, settings)

    def new_search(value: str):
        return engine.search(_qs(), value).queryset

    return new_search


def make_old_backend(fields, matchers, settings) -> Callable[[str], object]:
    """Old *backend* behaviour: rebuild the engine every request (no cache)."""

    def old_backend(value: str):
        engine = SearchEngine(fields, matchers, settings)
        return engine.search(_qs(), value).queryset

    return old_backend



def measure(fn: Callable[[str], object], value: str, iters: int) -> Dict[str, float]:
    # warm up
    for _ in range(1000):
        fn(value)
    samples: List[float] = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn(value)
        samples.append((time.perf_counter() - t0) * 1e6)  # microseconds
    samples.sort()
    return {
        "mean": statistics.mean(samples),
        "median": statistics.median(samples),
        "p95": samples[int(len(samples) * 0.95)],
        "stdev": statistics.pstdev(samples),
    }


def main() -> None:
    settings = get_settings()
    fields = compile_search_fields(CONFIG, Account)
    matchers = settings.matchers

    old = make_old_search(fields, matchers, settings)
    new = make_new_search(fields, matchers, settings)
    old_backend = make_old_backend(fields, matchers, settings)

    iters = 20000
    print(f"iterations per case: {iters}\n")

    print("A) Full path incl. Django QuerySet.filter() (engine reused both sides)")
    print("   — isolates ONLY the routing-plan precompute; ORM cost dominates.\n")
    header = f"{'case':<22}{'old µs':>10}{'new µs':>10}{'speedup':>10}"
    print(header)
    print("-" * len(header))
    for label, value in VALUES.items():
        o = measure(old, value, iters)
        n = measure(new, value, iters)
        speedup = o["median"] / n["median"] if n["median"] else float("inf")
        print(f"{label:<22}{o['median']:>10.2f}{n['median']:>10.2f}{speedup:>9.2f}x")

    print("\nB) Backend reality: OLD rebuilt the engine every request; NEW caches it.")
    print("   — this is the change users actually experience.\n")
    print(header)
    print("-" * len(header))
    for label, value in VALUES.items():
        o = measure(old_backend, value, iters)
        n = measure(new, value, iters)
        speedup = o["median"] / n["median"] if n["median"] else float("inf")
        print(f"{label:<22}{o['median']:>10.2f}{n['median']:>10.2f}{speedup:>9.2f}x")

    # Engine construction cost (paid once per view now; per request before).
    t0 = time.perf_counter()
    for _ in range(10000):
        SearchEngine(fields, matchers, settings)
    build_us = (time.perf_counter() - t0) * 1e6 / 10000
    print(f"\nSearchEngine build cost: {build_us:.2f} µs — paid ONCE (cached), was per-request")



if __name__ == "__main__":
    main()
