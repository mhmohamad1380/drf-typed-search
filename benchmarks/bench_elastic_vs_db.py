"""Benchmark: free-text search — Database (`icontains`) vs Elasticsearch path.

This measures the **end-to-end latency of the free-text branch** of
``SearchEngine`` in two configurations, against a real (in-memory SQLite)
database populated with a growing number of rows:

    A) Database backend  — no provider; the engine builds an ORM
       ``icontains`` query (``OR`` across fields, ``AND`` across terms) and the
       database scans the table.

    B) Elasticsearch path — an injected provider. Elasticsearch itself is
       replaced by a tiny in-process fake that returns a *bounded*, relevance
       ordered list of primary keys (exactly what a real cluster returns with
       ``_source=False``). The engine then re-selects those rows from the **real**
       database via ``pk__in`` + a ``Case/When`` ordering — the true DB cost of
       the ES path.

Why this comparison is fair and informative
-------------------------------------------
The Python routing cost is identical for both (same engine); the difference is
purely *what the database is asked to do*:

    * DB backend:  ``... WHERE username ILIKE '%term%' OR email ILIKE '%term%'``
      — an **unindexed sequential scan** whose cost grows with table size.
    * ES path:     ``... WHERE id IN (<= result_size pks)`` — an **indexed
      primary-key fetch** whose cost is bounded by the number of hits, *not* the
      table size.

We do NOT time the network round-trip to Elasticsearch (that is environment
specific); we isolate the part this library controls — the DB work each strategy
generates.

Reading the numbers
-------------------
Two DB engines behave very differently here:

    * On **SQLite (default, in-memory)** the ``LIKE '%term%'`` scan is executed
      in optimised C over a tiny in-memory table, so it is extremely fast and
      the ``Case/When`` re-ordering the ES path adds can actually dominate at
      small/medium sizes. Treat SQLite numbers as a *lower bound* for the DB
      scan, not as representative of production.
    * On **PostgreSQL** (run with ``DYNAMIC_SEARCH_TEST_DB=postgres``) an
      unindexed ``ILIKE '%term%'`` is a genuine sequential scan whose cost rises
      steeply with row count, while the ES path's ``pk IN (...)`` uses the
      primary-key index and stays bounded by ``RESULT_SIZE`` — which is the
      regime where the ES path pulls ahead.

The benchmark therefore reports the **DB scan cost** and the **ES DB-side cost**
separately so you can see where the crossover happens on *your* database. The
real Elasticsearch win also includes fuzzy/relevance matching a SQL ``LIKE``
cannot do at all.

Run (SQLite, quick)::


    DJANGO_SETTINGS_MODULE=tests.settings PYTHONPATH=src:. \
        python benchmarks/bench_elastic_vs_db.py

The benchmark creates and tears down its own schema in an in-memory database, so
it never touches your project data.
"""

from __future__ import annotations

import statistics
import time
from typing import Any, Callable

import django

django.setup()

from django.db import connection  # noqa: E402

from dynamic_search.config import compile_search_fields  # noqa: E402
from dynamic_search.elastic.provider import ElasticTextProvider  # noqa: E402
from dynamic_search.engine import SearchEngine  # noqa: E402
from dynamic_search.settings import ElasticIndexConfig, get_settings  # noqa: E402
from tests.models import Account, Profile  # noqa: E402

# Table sizes to sweep. Larger sizes make the DB sequential scan increasingly
# expensive while the ES path stays flat.
SIZES = [100, 1_000, 10_000, 50_000]

# Free-text query used for both strategies. Chosen so it matches a known,
# bounded number of rows (see MATCH_EVERY below).
QUERY = "findme"

# We plant the query token in 1 of every MATCH_EVERY rows, so the number of
# matching rows grows with the table but stays a small fraction — realistic for
# a selective search term.
MATCH_EVERY = 200

# Elasticsearch's `RESULT_SIZE`: the max pks a real cluster would return. The ES
# path's DB fetch is bounded by this regardless of table size.
RESULT_SIZE = 1_000

CONFIG = [
    {"field": "username", "lookup": "icontains", "matcher": None},
    {"field": "email", "lookup": "icontains", "matcher": None},
]


# --- schema + data -----------------------------------------------------------


def _create_schema() -> None:
    with connection.schema_editor() as editor:
        editor.create_model(Profile)
        editor.create_model(Account)


def _drop_schema() -> None:
    with connection.schema_editor() as editor:
        editor.delete_model(Account)
        editor.delete_model(Profile)


def _populate(n: int) -> list[int]:
    """Insert ``n`` accounts; return the pks that contain the QUERY token."""
    Account.objects.all().delete()
    Profile.objects.all().delete()

    profile = Profile.objects.create(
        national_code="1000000001",
        phone_number="09120000001",
        first_name="Bench",
        last_name="Mark",
    )

    accounts: list[Account] = []
    for i in range(n):
        if i % MATCH_EVERY == 0:
            username = f"user_{i}_{QUERY}"  # contains the search token
            email = f"{QUERY}_{i}@example.com"
        else:
            username = f"user_{i}"
            email = f"user_{i}@example.com"
        accounts.append(Account(username=username, email=email, user=profile))

    Account.objects.bulk_create(accounts, batch_size=2000)

    return list(
        Account.objects.filter(username__contains=QUERY).values_list("pk", flat=True)
    )


# --- engines -----------------------------------------------------------------


def _db_engine() -> SearchEngine:
    s = get_settings()
    return SearchEngine(compile_search_fields(CONFIG, Account), s.matchers, s)


class _FakeES:
    """Stands in for a real cluster: returns a bounded, ranked list of pks."""

    def __init__(self, pks: list[int]) -> None:
        self._hits = [{"_id": str(pk)} for pk in pks[:RESULT_SIZE]]

    def search(self, index: str, **body: Any) -> dict:
        return {"hits": {"hits": self._hits}}


def _es_engine(match_pks: list[int]) -> SearchEngine:
    import dynamic_search.elastic.provider as provider_module

    fake = _FakeES(match_pks)
    provider_module.get_client = lambda: fake  # type: ignore[assignment]

    config = ElasticIndexConfig(
        label="tests.Account",
        index_name="tests_account",
        fields=("username", "email"),
    )
    provider = ElasticTextProvider(config, result_size=RESULT_SIZE)
    s = get_settings()
    return SearchEngine(
        compile_search_fields(CONFIG, Account), s.matchers, s, text_provider=provider
    )


# --- measurement -------------------------------------------------------------


def _measure(run: Callable[[], int], iters: int) -> dict[str, float]:
    for _ in range(3):  # warm up (fills query plan / caches)
        run()
    samples: list[float] = []
    for _ in range(iters):
        t0 = time.perf_counter()
        run()
        samples.append((time.perf_counter() - t0) * 1e3)  # milliseconds
    samples.sort()
    return {
        "mean": statistics.mean(samples),
        "median": statistics.median(samples),
        "p95": samples[min(int(len(samples) * 0.95), len(samples) - 1)],
    }


def main() -> None:
    _create_schema()
    vendor = connection.vendor  # 'sqlite' or 'postgresql'
    try:
        print(
            f"db={vendor}  query={QUERY!r}  result_size(ES)={RESULT_SIZE}  "
            f"match_every={MATCH_EVERY}\n"
        )
        header = (
            f"{'rows':>8}{'matches':>9}"
            f"{'DB scan ms':>13}{'ES total ms':>13}"
            f"{'ES fetch ms':>13}{'DB/ES':>8}"
        )
        print(header)
        print("-" * len(header))

        for n in SIZES:
            match_pks = _populate(n)
            iters = 200 if n <= 10_000 else 60

            db_engine = _db_engine()
            es_engine = _es_engine(match_pks)

            def run_db() -> int:
                return len(list(db_engine.search(Account.objects.all(), QUERY).queryset))

            def run_es() -> int:
                return len(list(es_engine.search(Account.objects.all(), QUERY).queryset))

            # Isolate the ES path's DB cost *without* the Case/When ordering, to
            # show the raw indexed pk-fetch is cheap and flat; the delta vs
            # "ES total" is the price of preserving relevance order in SQL.
            def run_es_fetch_only() -> int:
                return len(list(Account.objects.filter(pk__in=match_pks)))

            # Sanity: both strategies return the same matching rows.
            db_hits = run_db()
            es_hits = run_es()
            assert db_hits == es_hits == len(match_pks), (
                f"row-count mismatch at n={n}: db={db_hits} es={es_hits} "
                f"expected={len(match_pks)}"
            )

            db = _measure(run_db, iters)
            es = _measure(run_es, iters)
            es_fetch = _measure(run_es_fetch_only, iters)
            ratio = db["median"] / es["median"] if es["median"] else float("inf")

            print(
                f"{n:>8}{len(match_pks):>9}"
                f"{db['median']:>13.3f}{es['median']:>13.3f}"
                f"{es_fetch['median']:>13.3f}{ratio:>7.2f}x"
            )

        print(
            "\nColumns:\n"
            "  DB scan ms   full DB free-text path (ILIKE '%term%' over all rows).\n"
            "  ES total ms  full ES path DB cost: pk IN (...) + Case/When ordering.\n"
            "  ES fetch ms  just the indexed pk IN (...) fetch, no ordering.\n"
            "  DB/ES        DB scan / ES total (>1 => ES path is faster).\n"
            "\nInterpretation:\n"
            f"  * On {vendor}: 'DB scan' rises with row count (sequential scan),\n"
            "    while 'ES fetch' stays low and flat (primary-key index, bounded\n"
            "    by RESULT_SIZE).\n"
            "  * 'ES total' - 'ES fetch' is the Case/When relevance-ordering cost.\n"
            "    On in-memory SQLite the raw scan is C-fast, so this ordering can\n"
            "    outweigh the scan; on PostgreSQL the scan dominates far sooner and\n"
            "    'DB/ES' climbs above 1 (ES path wins). Re-run with\n"
            "    DYNAMIC_SEARCH_TEST_DB=postgres to see that regime.\n"
            "  * Not measured: the real Elasticsearch win also includes fuzzy /\n"
            "    relevance matching that a SQL LIKE cannot do at all, at the cost\n"
            "    of a network round-trip.\n"
        )
    finally:
        _drop_schema()



if __name__ == "__main__":
    main()
