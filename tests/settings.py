"""Minimal Django settings for the test suite.

The database defaults to SQLite for portability; set ``DYNAMIC_SEARCH_TEST_DB=postgres``
to run the PostgreSQL-specific and benchmark tests against a real server.
"""

from __future__ import annotations

import os

SECRET_KEY = "dynamic-search-tests"

USE_TZ = True

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "rest_framework",
    "dynamic_search",
    "tests",
]

_DB = os.environ.get("DYNAMIC_SEARCH_TEST_DB", "sqlite")

if _DB == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("PGDATABASE", "dynamic_search"),
            "USER": os.environ.get("PGUSER", "postgres"),
            "PASSWORD": os.environ.get("PGPASSWORD", "postgres"),
            "HOST": os.environ.get("PGHOST", "127.0.0.1"),
            "PORT": os.environ.get("PGPORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

UUID_REGEX = (
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _is_positive_int(value: str) -> bool:
    return value.isdigit() and int(value) > 0


DYNAMIC_SEARCH = {
    "MATCHERS": {
        "national_code": {"pattern": r"^\d{10}$", "lookup": "exact"},
        "phone_number": {"pattern": r"^09\d{9}$", "lookup": "exact"},
        "uuid": {"pattern": UUID_REGEX, "lookup": "exact"},
        # Callable matcher example.
        "id": {"pattern": _is_positive_int, "lookup": "exact"},
        "pk": {"pattern": _is_positive_int, "lookup": "exact"},
    },
    "DEFAULT_TEXT_LOOKUP": "icontains",
    "SEARCH_PARAM": "search",
    "EMPTY_ON_NO_MATCH": True,
}
