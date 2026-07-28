"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from dynamic_search.settings import reset_cache


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Ensure each test sees a freshly-built settings cache."""
    reset_cache()
    yield
    reset_cache()


@pytest.fixture()
def profiles(db):
    from tests.models import Profile

    alice = Profile.objects.create(
        national_code="1000000001",
        phone_number="09120000001",
        first_name="Alice",
        last_name="Smith",
    )
    bob = Profile.objects.create(
        national_code="1000000002",
        phone_number="09120000002",
        first_name="Bob",
        last_name="Jones",
    )
    ali = Profile.objects.create(
        national_code="1000000003",
        phone_number="09120000003",
        first_name="Ali",
        last_name="Rezai",
    )
    return {"alice": alice, "bob": bob, "ali": ali}


@pytest.fixture()
def accounts(db, profiles):
    from tests.models import Account

    return {
        "alice": Account.objects.create(
            username="alice", email="alice@example.com", user=profiles["alice"]
        ),
        "bob": Account.objects.create(
            username="bob", email="bob@example.com", user=profiles["bob"]
        ),
        "ali": Account.objects.create(
            username="ali", email="ali@example.com", user=profiles["ali"]
        ),
    }
