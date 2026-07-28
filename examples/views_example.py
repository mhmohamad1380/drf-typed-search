"""Example DRF view wiring.

Assumes the ``DYNAMIC_SEARCH`` block from ``settings_example.py`` is active.
"""

from rest_framework.viewsets import ModelViewSet

from dynamic_search import DynamicSearchBackend, concat_annotation

# from myapp.models import Account
# from myapp.serializers import AccountSerializer


class AccountViewSet(ModelViewSet):
    # queryset = Account.objects.select_related("user")
    # serializer_class = AccountSerializer
    filter_backends = [DynamicSearchBackend]

    search_fields_config = [
        # Routed by the "national_code" matcher -> user.national_code exact.
        {"field": "national_code", "join": "user"},
        # Routed by the "phone_number" matcher.
        {"field": "phone_number", "join": "user"},
        # Integer input -> primary key.
        {"field": "id"},
        # Free-text only (matcher disabled); computed full name annotation.
        {
            "field": "full_name",
            "annotate": concat_annotation(
                "full_name", ["first_name", "last_name"], join="user"
            ),
            "lookup": "icontains",
            "matcher": None,
        },
        # Free-text over username.
        {"field": "username", "lookup": "icontains", "matcher": None},
    ]
