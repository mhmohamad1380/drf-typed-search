# Usage

Add `DynamicSearchBackend` to a view's `filter_backends` and declare
`search_fields_config`. That's the entire public surface a view needs.

```python
from rest_framework.viewsets import ModelViewSet
from dynamic_search import DynamicSearchBackend

class UserViewSet(ModelViewSet):
    queryset = Account.objects.all()
    serializer_class = AccountSerializer
    filter_backends = [DynamicSearchBackend]

    search_fields_config = [
        {"field": "national_code", "join": "user"},
        {"field": "phone_number", "join": "user"},
        {"field": "id"},
        {"field": "full_name", "join": "user", "lookup": "icontains"},
    ]
```

## The `search_fields_config` reference

| Key | Type | Description |
|---|---|---|
| `field` | `str` (required) | Model field, related field, or annotation alias. |
| `join` | `str` | Relation prefix, e.g. `"user"` or `"loan__user"`. |
| `lookup` | `str` | Override lookup (routing or free-text). |
| `matcher` | `str \| None` | Matcher name; defaults to `field`; `None` disables routing. |
| `annotate` | `(qs, prefix) -> qs` | Add a computed annotation before filtering. |
| `queryset_builder` | `(qs, value) -> qs` | Fully custom filtering (trigram, full-text, …). |
| `text` | `bool` | Force into the free-text fallback. |

### Supported lookups

`exact`, `iexact`, `contains`, `icontains`, `startswith`, `istartswith`,
`endswith`, `iendswith`.

## How a field is bound to a matcher

Each config entry is bound to a matcher named after its `field` by default. So
`{"field": "national_code", ...}` is routed by the `national_code` matcher
automatically. Override with `"matcher": "some_name"`, or disable typed routing
for a field with `"matcher": None` (it then only participates in free-text).

## Search flow

For every request:

1. Read the cached matcher registry.
2. For each declared field (priority-ordered), test its bound matcher against
   the whole value.
3. First match wins → build one precise, index-friendly filter.
4. Otherwise → DRF-style free-text search (**AND across terms, OR across
   fields**, quoted phrases supported).
5. If there are no text fields and nothing matched → `none()` (configurable).

The winning field name(s) are written to `view.search_field` for
paginators/logging.

## Reading the result

`DynamicSearchBackend` sets `view.search_field` to the comma-joined names of the
fields that were actually searched (or `None`). Handy for custom paginators,
logging, or analytics:

```python
def paginate_queryset(self, queryset, request, view=None):
    if view is not None and view.search_field:
        # e.g. log which typed route was taken
        ...
    return super().paginate_queryset(queryset, request, view)
```

## Using the engine directly

The routing engine is framework-agnostic and can be used outside a DRF view:

```python
from dynamic_search import SearchEngine, compile_search_fields, get_settings

settings = get_settings()
fields = compile_search_fields(
    [{"field": "national_code", "join": "user"}, {"field": "id"}],
    Account,
)
engine = SearchEngine(fields, settings.matchers, settings)

result = engine.search(Account.objects.all(), "1000000001")
print(result.strategy)  # "typed"
print(result.matcher)   # "national_code"
list(result.queryset)
```
