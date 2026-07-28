"""Example ``DYNAMIC_SEARCH`` settings block.

Copy the relevant parts into your project's Django settings. Note that *all*
domain-specific regexes live here — the package ships none.
"""

import re

# A compiled pattern works exactly like a raw string; compiling here means the
# regex is validated at import time and reused (no per-request compilation).
UUID_REGEX = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def is_positive_int(value: str) -> bool:
    """Example callable matcher."""
    return value.isdigit() and int(value) > 0


DYNAMIC_SEARCH = {
    "MATCHERS": {
        # Regex matchers (string form).
        "national_code": {"pattern": r"^\d{10}$", "lookup": "exact"},
        "phone_number": {"pattern": r"^09\d{9}$", "lookup": "exact"},
        # Regex matcher (compiled form).
        "uuid": {"pattern": UUID_REGEX, "lookup": "exact"},
        # Callable matcher.
        "id": {"pattern": is_positive_int, "lookup": "exact"},
        # Prefix search example (add a text_pattern_ops index for speed).
        "sku": {"pattern": r"^SKU-[A-Z0-9]+$", "lookup": "istartswith"},
    },
    "DEFAULT_TEXT_LOOKUP": "icontains",
    "SEARCH_PARAM": "search",
    "EMPTY_ON_NO_MATCH": True,
}
