"""``manage.py reindex_search`` — (re)build Elasticsearch indexes.

Examples::

    # Reindex every configured model
    python manage.py reindex_search

    # Reindex specific models, recreating the indexes first
    python manage.py reindex_search blog.Article shop.Product --recreate

The command is a thin CLI wrapper over
:func:`dynamic_search.elastic.indexing.reindex_model`; all heavy lifting (index
creation, bulk indexing, refresh) lives there so it can also be driven from a
Celery task or a data migration.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from ...settings import get_settings


class Command(BaseCommand):
    help = "(Re)index configured models into Elasticsearch."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "labels",
            nargs="*",
            metavar="app_label.ModelName",
            help=(
                "Specific models to reindex. Defaults to every model in "
                "DYNAMIC_SEARCH['ELASTICSEARCH']['INDEXES']."
            ),
        )
        parser.add_argument(
            "--recreate",
            action="store_true",
            help="Delete and recreate each index before indexing (purges stale docs).",
        )
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=500,
            help="Number of documents per bulk request (default: 500).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        # Imported here so the command module is importable even when the
        # optional 'elasticsearch' package is absent (Django loads all commands).
        try:
            from ...elastic.indexing import reindex_model
        except ImportError as exc:  # pragma: no cover - dependency missing
            raise CommandError(
                "The 'elasticsearch' package is required. "
                "Install it with: pip install drf-typed-search[elasticsearch]"
            ) from exc

        configured = list(get_settings().elasticsearch.indexes)
        if not configured:
            raise CommandError(
                "No indexes configured. Add models to "
                "DYNAMIC_SEARCH['ELASTICSEARCH']['INDEXES']."
            )

        labels = options["labels"] or configured
        unknown = [label for label in labels if label not in configured]
        if unknown:
            raise CommandError(
                f"Not configured for indexing: {', '.join(unknown)}. "
                f"Configured: {', '.join(configured)}."
            )

        recreate = options["recreate"]
        chunk_size = options["chunk_size"]

        total = 0
        for label in labels:
            self.stdout.write(f"Indexing {label} ...", ending=" ")
            try:
                count = reindex_model(
                    label, recreate=recreate, chunk_size=chunk_size
                )
            except Exception as exc:  # surface a clean CLI error
                raise CommandError(f"Failed to reindex {label}: {exc}") from exc
            total += count
            self.stdout.write(self.style.SUCCESS(f"{count} documents"))

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Indexed {total} document(s) across {len(labels)} model(s)."
            )
        )
