from __future__ import annotations

import json
from pathlib import Path
from urllib.error import URLError
from unittest.mock import MagicMock, patch

import pytest

from oszt.broker import Context
from oszt.errors import CapabilityFailed, PolicyViolation
from oszt.memory import MemoryStore
from oszt.policy import Policy
from oszt.capabilities.cloud_memory import (
    sync_preferences_to_cloud,
    fetch_preferences_from_cloud,
    delete_cloud_history,
)


@pytest.fixture
def policy_allowed() -> Policy:
    return Policy.from_dict({
        "allowed_capabilities": [
            "sync_preferences_to_cloud",
            "fetch_preferences_from_cloud",
            "delete_cloud_history",
        ],
        "allowed_hosts": ["cloud.example.com"],
        "dry_run": False,
    })


@pytest.fixture
def policy_dry_run() -> Policy:
    return Policy.from_dict({
        "allowed_capabilities": [
            "sync_preferences_to_cloud",
            "fetch_preferences_from_cloud",
            "delete_cloud_history",
        ],
        "allowed_hosts": ["cloud.example.com"],
        "dry_run": True,
    })


@pytest.fixture
def mock_context(policy_allowed: Policy) -> Context:
    return Context(policy=policy_allowed, run=MagicMock())


@pytest.fixture
def mock_context_dry(policy_dry_run: Policy) -> Context:
    return Context(policy=policy_dry_run, run=MagicMock())


@pytest.fixture
def memory_db(tmp_path: Path) -> str:
    path = tmp_path / "test_memory.sqlite3"
    store = MemoryStore(path)
    store.remember("theme", "dark")
    store.remember("name", "Alice")
    store.log_action("list_files", {}, "allowed")
    store.close()
    return str(path)


def test_sync_to_cloud_success(mock_context: Context, memory_db: str) -> None:
    mock_response = MagicMock()
    mock_response.getcode.return_value = 200
    mock_response.read.return_value = b"OK"
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        result = sync_preferences_to_cloud(
            mock_context, "https://cloud.example.com/sync", memory_db
        )
        assert result["status"] == "success"
        assert result["facts_count"] == 2
        assert result["actions_count"] == 1

        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        assert req.get_method() == "POST"
        assert req.get_header("Content-type") == "application/json"
        payload = json.loads(req.data.decode("utf-8"))
        assert any(f["key"] == "theme" and f["value"] == "dark" for f in payload["facts"])


def test_sync_to_cloud_dry_run(mock_context_dry: Context, memory_db: str) -> None:
    with patch("urllib.request.urlopen") as mock_urlopen:
        result = sync_preferences_to_cloud(
            mock_context_dry, "https://cloud.example.com/sync", memory_db
        )
        assert result["dry_run"] is True
        assert result["facts_count"] == 2
        assert result["actions_count"] == 1
        mock_urlopen.assert_not_called()


def test_sync_to_cloud_host_check(mock_context: Context, memory_db: str) -> None:
    # Host not in allowed list
    with pytest.raises(PolicyViolation, match="not permitted"):
        sync_preferences_to_cloud(
            mock_context, "https://unauthorized.com/sync", memory_db
        )


def test_sync_to_cloud_scheme_check(mock_context: Context, memory_db: str) -> None:
    with pytest.raises(PolicyViolation, match="must be http or https"):
        sync_preferences_to_cloud(
            mock_context, "ftp://cloud.example.com/sync", memory_db
        )


def test_sync_to_cloud_http_error(mock_context: Context, memory_db: str) -> None:
    mock_response = MagicMock()
    mock_response.getcode.return_value = 500
    mock_response.read.return_value = b"Internal Error"
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response):
        with pytest.raises(CapabilityFailed, match="cloud returned status 500"):
            sync_preferences_to_cloud(
                mock_context, "https://cloud.example.com/sync", memory_db
            )


def test_sync_to_cloud_url_error(mock_context: Context, memory_db: str) -> None:
    with patch("urllib.request.urlopen", side_effect=URLError("connection reset")):
        with pytest.raises(CapabilityFailed, match="cloud sync failed"):
            sync_preferences_to_cloud(
                mock_context, "https://cloud.example.com/sync", memory_db
            )


def test_fetch_from_cloud_success(mock_context: Context, memory_db: str) -> None:
    cloud_payload = {
        "facts": [
            {"key": "theme", "value": "light", "kind": "fact"},
            {"key": "language", "value": "en", "kind": "fact"},
        ]
    }
    mock_response = MagicMock()
    mock_response.getcode.return_value = 200
    mock_response.read.return_value = json.dumps(cloud_payload).encode("utf-8")
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response):
        result = fetch_preferences_from_cloud(
            mock_context, "https://cloud.example.com/sync", memory_db
        )
        assert result["status"] == "success"
        assert result["facts_imported"] == 2

    # Verify memory was updated and Alice still exists
    store = MemoryStore(memory_db)
    try:
        assert store.recall("theme") == "light"
        assert store.recall("name") == "Alice"
        assert store.recall("language") == "en"
    finally:
        store.close()


def test_fetch_from_cloud_dry_run(mock_context_dry: Context, memory_db: str) -> None:
    with patch("urllib.request.urlopen") as mock_urlopen:
        result = fetch_preferences_from_cloud(
            mock_context_dry, "https://cloud.example.com/sync", memory_db
        )
        assert result["dry_run"] is True
        mock_urlopen.assert_not_called()


def test_fetch_from_cloud_invalid_json(mock_context: Context, memory_db: str) -> None:
    mock_response = MagicMock()
    mock_response.getcode.return_value = 200
    mock_response.read.return_value = b"{bad json"
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response):
        with pytest.raises(CapabilityFailed, match="invalid JSON from cloud"):
            fetch_preferences_from_cloud(
                mock_context, "https://cloud.example.com/sync", memory_db
            )


def test_delete_cloud_history_success(mock_context: Context) -> None:
    mock_response = MagicMock()
    mock_response.getcode.return_value = 200
    mock_response.read.return_value = b"Deleted"
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
        result = delete_cloud_history(mock_context, "https://cloud.example.com/sync")
        assert result["status"] == "deleted"

        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        assert req.get_method() == "DELETE"


def test_delete_cloud_history_dry_run(mock_context_dry: Context) -> None:
    with patch("urllib.request.urlopen") as mock_urlopen:
        result = delete_cloud_history(mock_context_dry, "https://cloud.example.com/sync")
        assert result["dry_run"] is True
        mock_urlopen.assert_not_called()
