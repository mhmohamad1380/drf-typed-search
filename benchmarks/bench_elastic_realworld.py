"""Real-world query-time benchmark: WITHOUT Elasticsearch vs WITH Elasticsearch.

Unlike :mod:`benchmarks.bench_elastic_vs_db` (which fakes the cluster to isolate
the DB-side cost), this benchmark talks to a **real, running Elasticsearch
cluster** and measures true end-to-end free-text query latency for both
configurations of ``SearchEngine``:

    WITHOUT ES  → ORM ``icontains`` (``OR`` across fields) over the SQL table.
    WITH ES     → real Elasticsearch ``multi_match`` query (network + Lucene),
                  then the DB re-selects the matching rows by primary key.

Both paths return a real Django ``QuerySet``; we evaluate it fully (``list()``),
so the timings include everything a real request pays: query build, DB/ES I/O,
row fetch and object construction.

Requirements
------------
* A reachable Elasticsearch cluster. Override the host with ``ES_HOST``
  (default ``http://localhost:9200``).
* The ``elasticsearch`` client: ``pip install drf-typed-search[elasticsearch]``.

The benchmark uses a **file-based SQLite** database in a temp dir (so it is
disk-backed and closer to production than ``:memory:``), creates its own schema
and ES index, and cleans both up afterwards. It never touches your project data.

Run::

    ES_HOST=http://localhost:9200 \
    DJANGO_SETTINGS_MODULE=benchmarks.bench_settings PYTHONPATH=src:. \
        python benchmarks/bench_elastic_realworld.py

If you don't have a dedicated settings module, the script configures Django
itself (see ``_configure`` below), so plain::

    PYTHONPATH=src:. python benchmarks/bench_elastic_realworld.py

works too.
"""

from __future__ import annotations

import os
import random
import statistics
import sys
import tempfile
import time
from typing import Callable

# --- Configure Django BEFORE importing anything that needs settings ----------


def _configure() -> str:
    """Configure Django with a disk-backed SQLite DB; return the db file path."""
    import django
    from django.conf import settings as dj_settings

    db_fd, db_path = tempfile.mkstemp(prefix="bench_es_", suffix=".sqlite3")
    os.close(db_fd)

    es_host = os.environ.get("ES_HOST", "http://localhost:9200")

    if not dj_settings.configured:
        dj_settings.configure(
            DEBUG=False,
            SECRET_KEY="bench",
            USE_TZ=True,
            DEFAULT_AUTO_FIELD="django.db.models.BigAutoField",
            INSTALLED_APPS=[
                "django.contrib.contenttypes",
                "django.contrib.auth",
                "dynamic_search",
                "tests",
            ],
            DATABASES={
                "default": {
                    "ENGINE": "django.db.backends.sqlite3",
                    "NAME": db_path,
                }
            },
            DYNAMIC_SEARCH={
                "MATCHERS": {
                    "id": {"pattern": lambda v: v.isdigit(), "lookup": "exact"},
                },
                "DEFAULT_TEXT_LOOKUP": "icontains",
                "TEXT_BACKEND": "elasticsearch",
                "ELASTICSEARCH": {
                    "HOSTS": [es_host],
                    "INDEX_PREFIX": "bench_",
                    "AUTO_SYNC": False,
                    "RESULT_SIZE": 1000,
                    "INDEXES": {
                        "tests.Account": {"fields": ["username", "email"]},
                    },
                },
            },
        )
    django.setup()
    return db_path


DB_PATH = _configure()

from django.db import connection  # noqa: E402

from dynamic_search.config import compile_search_fields  # noqa: E402
from dynamic_search.elastic.client import get_client  # noqa: E402
from dynamic_search.elastic.indexing import reindex_model  # noqa: E402
from dynamic_search.elastic.provider import build_text_provider  # noqa: E402
from dynamic_search.engine import SearchEngine  # noqa: E402
from dynamic_search.exceptions import ElasticsearchError  # noqa: E402
from dynamic_search.settings import get_settings  # noqa: E402
from tests.models import Account, Profile  # noqa: E402

SIZES = [1_000, 10_000, 50_000]

# Query workload: a mix of an exact term (present verbatim) and a typo'd term
# (one character off) — the typo case is where ES fuzziness beats LIKE, which
# would return zero rows for it.
FIRST_NAMES = ["john", "jane", "michael", "sarah", "david", "emily", "chris", "anna"]
LAST_NAMES = ["smith", "jones", "brown", "wilson", "taylor", "davis", "clark", "lee"]

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


def _populate(n: int, seed: int = 1234) -> None:
    """Insert ``n`` realistic accounts (``first.last<i>`` usernames + emails)."""
    rng = random.Random(seed)
    Account.objects.all().delete()
    Profile.objects.all().delete()

    profile = Profile.objects.create(
        national_code="1000000001",
        phone_number="09120000001",
        first_name="Bench",
        last_name="Mark",
    )

    batch: list[Account] = []
    for i in range(n):
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        # Whitespace-separated full name so BOTH the SQL ``icontains`` path and
        # the Elasticsearch standard analyzer see "first" and "last" as distinct,
        # searchable tokens — the canonical full-text search scenario.
        username = f"{first} {last} {i}"
        email = f"{first}.{last}.{i}@example.com"
        batch.append(Account(username=username, email=email, user=profile))
    Account.objects.bulk_create(batch, batch_size=2000)



# --- engines -----------------------------------------------------------------


def _db_engine() -> SearchEngine:
    s = get_settings()
    return SearchEngine(compile_search_fields(CONFIG, Account), s.matchers, s)


def _es_engine() -> SearchEngine:
    s = get_settings()
    provider = build_text_provider(Account)
    if provider is None:  # pragma: no cover - misconfiguration
        raise RuntimeError("No ES index configured for tests.Account")
    return SearchEngine(
        compile_search_fields(CONFIG, Account), s.matchers, s, text_provider=provider
    )


# --- measurement -------------------------------------------------------------


def _measure(run: Callable[[], int], iters: int) -> dict[str, float]:
    for _ in range(3):  # warm up
        run()
    samples: list[float] = []
    for _ in range(iters):
        t0 = time.perf_counter()
        run()
        samples.append((time.perf_counter() - t0) * 1e3)  # ms
    samples.sort()
    return {
        "median": statistics.median(samples),
        "p95": samples[min(int(len(samples) * 0.95), len(samples) - 1)],
    }


def _check_cluster() -> bool:
    try:
        client = get_client()
        return bool(client.ping())
    except ElasticsearchError:
        return False
    except Exception:
        return False


def main() -> int:
    es_host = os.environ.get("ES_HOST", "http://localhost:9200")
    if not _check_cluster():
        print(
            f"Elasticsearch is not reachable at {es_host}.\n"
            "Start a cluster (e.g. `docker run -p 9200:9200 "
            "-e discovery.type=single-node elasticsearch:8.13.0`) or set ES_HOST, "
            "then re-run. For a no-cluster comparison use "
            "benchmarks/bench_elastic_vs_db.py."
        )
        return 1

    _create_schema()
    try:
        print(f"es_host={es_host}  db=sqlite(file)  result_size={get_settings().elasticsearch.result_size}\n")

        # Two representative queries:
        #   exact  -> a term that exists verbatim (both backends find it)
        #   typo   -> one character off (LIKE finds nothing; ES fuzziness does)
        exact_term = "john smith"
        typo_term = "jonh smith"  # 'jonh' != 'john'

        header = (
            f"{'rows':>8}  {'query':<12}"
            f"{'DB ms (no ES)':>16}{'ES ms (with ES)':>18}{'ES hits':>9}{'DB hits':>9}"
        )
        print(header)
        print("-" * len(header))

        for n in SIZES:
            _populate(n)

            # Build/refresh the real ES index for this dataset.
            reindex_model("tests.Account", recreate=True)

            db_engine = _db_engine()
            es_engine = _es_engine()
            iters = 100 if n <= 10_000 else 50

            for label, term in (("exact", exact_term), ("typo", typo_term)):

                def run_db() -> int:
                    return len(
                        list(db_engine.search(Account.objects.all(), term).queryset)
                    )

                def run_es() -> int:
                    return len(
                        list(es_engine.search(Account.objects.all(), term).queryset)
                    )

                db_hits = run_db()
                es_hits = run_es()

                db = _measure(run_db, iters)
                es = _measure(run_es, iters)

                print(
                    f"{n:>8}  {label:<12}"
                    f"{db['median']:>16.3f}{es['median']:>18.3f}"
                    f"{es_hits:>9}{db_hits:>9}"
                )

        print(
            "\nNotes:\n"
            "  * DB ms  = free-text WITHOUT Elasticsearch (ORM ILIKE '%term%').\n"
            "  * ES ms  = free-text WITH Elasticsearch (real multi_match over the\n"
            "    network, then an indexed pk fetch from SQLite). Includes real\n"
            "    cluster latency.\n"
            "  * 'exact' rows both backends can find; 'typo' shows ES fuzziness\n"
            "    returning matches while the LIKE backend returns 0 hits — a\n"
            "    capability difference LIKE cannot close at any speed.\n"
            "  * On file-backed SQLite the LIKE scan is fast in C; on PostgreSQL\n"
            "    with millions of rows the unindexed ILIKE scan dominates and the\n"
            "    ES path's bounded pk fetch wins on latency as well as capability.\n"
        )
        return 0
    finally:
        # Clean up the ES index and DB.
        try:
            client = get_client()
            index_name = get_settings().elasticsearch.indexes["tests.Account"].index_name
            if client.indices.exists(index=index_name):
                client.indices.delete(index=index_name)
        except Exception:  # pragma: no cover - best-effort cleanup
            pass
        _drop_schema()
        connection.close()
        try:
            os.remove(DB_PATH)
        except OSError:  # pragma: no cover
            pass


if __name__ == "__main__":
    sys.exit(main())
