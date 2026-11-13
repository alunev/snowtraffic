"""Only the history endpoints read query parameters.

The production nginx config caches every other /api/ path on the path alone, so a request with
made-up query args is answered from the cache instead of reaching the API. That is only correct
while those routes ignore the query string. A new query parameter on any other route needs the
nginx cache key changed in the same release; this test fails until then.
"""
import re

from fastapi.routing import APIRoute

import main

# Mirrors the nginx map: these paths are cached on the full request URI and rate-limited tightly.
ARG_READERS = re.compile(r"^/(segments|history|weather/history)")


def query_params():
    return {r.path: sorted(p.name for p in r.dependant.query_params)
            for r in main.app.routes if isinstance(r, APIRoute)}


def test_only_the_history_endpoints_take_query_params():
    params = query_params()
    readers = {path: names for path, names in params.items() if names}
    # The introspection itself must see the parameters we know exist.
    assert readers.get("/segments/{route_id}") == ["hours", "limit"]
    assert readers.get("/weather/history") == ["hours", "limit", "station_id"]
    outside = {path: names for path, names in readers.items() if not ARG_READERS.match(path)}
    assert outside == {}, f"routes outside the nginx full-URI cache key take query params: {outside}"
