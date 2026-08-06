"""Syncing preferences and action history to/from a cloud REST endpoint.

Ensures that the user can back up their facts and choices to the cloud,
restore them on any device, and delete them from the cloud completely at any time.
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from urllib.parse import urlparse
from typing import TYPE_CHECKING

from oszt.errors import CapabilityFailed, PolicyViolation
from oszt.memory import MemoryStore

if TYPE_CHECKING:  # pragma: no cover
    from oszt.broker import Context


def sync_preferences_to_cloud(
    ctx: Context, endpoint_url: str, memory_path: str = "memory.sqlite3"
) -> dict[str, object]:
    """Sync local preferences (facts) and action history to a cloud REST endpoint."""
    parsed = urlparse(endpoint_url)
    if parsed.scheme not in ("http", "https"):
        raise PolicyViolation("cloud endpoint must be http or https")
    if not parsed.hostname:
        raise PolicyViolation(f"{endpoint_url!r} has no host")
    ctx.policy.check_host(parsed.hostname)

    store = MemoryStore(memory_path)
    try:
        facts = store.search("")
        actions = store.recent_actions(limit=100)
    finally:
        store.close()

    facts_data = [
        {
            "key": f.key,
            "value": f.value,
            "kind": f.kind,
            "updated_at": f.updated_at,
        }
        for f in facts
    ]
    actions_data = [
        {
            "capability": a.capability,
            "arguments": a.arguments,
            "outcome": a.outcome,
            "created_at": a.created_at,
        }
        for a in actions
    ]

    payload = {
        "facts": facts_data,
        "actions": actions_data,
    }

    if ctx.dry_run:
        return {
            "endpoint_url": endpoint_url,
            "facts_count": len(facts_data),
            "actions_count": len(actions_data),
            "dry_run": True,
        }

    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint_url,
        data=data_bytes,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            status = response.getcode()
            body = response.read().decode("utf-8")
            if not (200 <= status < 300):
                raise CapabilityFailed(
                    f"cloud returned status {status} on sync: {body}"
                )
    except urllib.error.URLError as error:
        raise CapabilityFailed(f"cloud sync failed: {error}") from error

    return {
        "endpoint_url": endpoint_url,
        "facts_count": len(facts_data),
        "actions_count": len(actions_data),
        "status": "success",
    }


def fetch_preferences_from_cloud(
    ctx: Context, endpoint_url: str, memory_path: str = "memory.sqlite3"
) -> dict[str, object]:
    """Fetch previously stored preferences from a cloud REST endpoint and upsert them locally."""
    parsed = urlparse(endpoint_url)
    if parsed.scheme not in ("http", "https"):
        raise PolicyViolation("cloud endpoint must be http or https")
    if not parsed.hostname:
        raise PolicyViolation(f"{endpoint_url!r} has no host")
    ctx.policy.check_host(parsed.hostname)

    if ctx.dry_run:
        return {
            "endpoint_url": endpoint_url,
            "dry_run": True,
        }

    req = urllib.request.Request(
        endpoint_url,
        headers={"Accept": "application/json"},
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            status = response.getcode()
            body = response.read().decode("utf-8")
            if not (200 <= status < 300):
                raise CapabilityFailed(
                    f"cloud returned status {status} on fetch: {body}"
                )
            data = json.loads(body)
    except urllib.error.URLError as error:
        raise CapabilityFailed(f"cloud fetch failed: {error}") from error
    except json.JSONDecodeError as error:
        raise CapabilityFailed(f"invalid JSON from cloud: {error}") from error

    facts_imported = 0
    store = MemoryStore(memory_path)
    try:
        for fact in data.get("facts", []):
            store.remember(
                fact["key"], fact["value"], fact.get("kind", "fact")
            )
            facts_imported += 1
    finally:
        store.close()

    return {
        "endpoint_url": endpoint_url,
        "facts_imported": facts_imported,
        "status": "success",
    }


def delete_cloud_history(
    ctx: Context, endpoint_url: str
) -> dict[str, object]:
    """Delete all preferences and history stored on the cloud REST endpoint completely."""
    parsed = urlparse(endpoint_url)
    if parsed.scheme not in ("http", "https"):
        raise PolicyViolation("cloud endpoint must be http or https")
    if not parsed.hostname:
        raise PolicyViolation(f"{endpoint_url!r} has no host")
    ctx.policy.check_host(parsed.hostname)

    if ctx.dry_run:
        return {
            "endpoint_url": endpoint_url,
            "dry_run": True,
        }

    req = urllib.request.Request(
        endpoint_url,
        method="DELETE",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            status = response.getcode()
            body = response.read().decode("utf-8")
            if not (200 <= status < 300):
                raise CapabilityFailed(
                    f"cloud returned status {status} on delete: {body}"
                )
    except urllib.error.URLError as error:
        raise CapabilityFailed(f"cloud delete failed: {error}") from error

    return {
        "endpoint_url": endpoint_url,
        "status": "deleted",
    }
