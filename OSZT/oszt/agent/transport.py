"""Talking to a local model over HTTP, with the standard library only.

Shared by the text model and the vision model so neither has to import the
other.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping

Transport = Callable[[str, Mapping[str, Any]], dict[str, Any]]


class AgentError(Exception):
    """The model or its transport failed."""


def http_transport(url: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """POST JSON to ``url`` and return the decoded response."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as error:
        raise AgentError(f"cannot reach the model at {url}: {error}") from error
