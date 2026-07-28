"""Test models exercising direct fields, related fields, UUID PKs and annotations."""

from __future__ import annotations

import uuid

from django.db import models


class Profile(models.Model):
    """A related model reached through ``Account.profile`` / ``user``."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    national_code = models.CharField(max_length=10, db_index=True)
    phone_number = models.CharField(max_length=11, db_index=True)
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)

    class Meta:
        app_label = "tests"


class Account(models.Model):
    """The primary searchable model (integer PK)."""

    username = models.CharField(max_length=150, db_index=True)
    email = models.CharField(max_length=254, blank=True)
    user = models.ForeignKey(
        Profile, on_delete=models.CASCADE, related_name="accounts"
    )

    class Meta:
        app_label = "tests"
