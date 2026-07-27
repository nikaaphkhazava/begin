from __future__ import annotations

import json
from pathlib import Path

import pytest

from oszt.errors import PolicyViolation
from oszt.policy import Policy


def test_check_capability_allows_listed_and_denies_everything_else(policy: Policy) -> None:
    policy.check_capability("open_app")
    with pytest.raises(PolicyViolation):
        policy.check_capability("delete_partition")


def test_command_for_app_returns_fixed_argv(policy: Policy) -> None:
    assert policy.command_for_app("firefox") == ("flatpak", "run", "org.mozilla.firefox")


def test_command_for_app_rejects_unlisted_app(policy: Policy) -> None:
    with pytest.raises(PolicyViolation):
        policy.command_for_app("gparted")


def test_relative_paths_resolve_inside_first_root(policy: Policy, sandbox: Path) -> None:
    assert policy.resolve_path("hello.txt") == sandbox / "hello.txt"


def test_dotdot_cannot_escape_the_root(policy: Policy) -> None:
    with pytest.raises(PolicyViolation):
        policy.resolve_path("../../etc/passwd")


def test_absolute_path_outside_root_is_refused(policy: Policy) -> None:
    with pytest.raises(PolicyViolation):
        policy.resolve_path("/etc/shadow")


def test_symlink_out_of_the_root_is_refused(policy: Policy, sandbox: Path) -> None:
    (sandbox / "escape").symlink_to("/etc")
    with pytest.raises(PolicyViolation):
        policy.resolve_path("escape/passwd")


def test_root_itself_is_allowed(policy: Policy, sandbox: Path) -> None:
    assert policy.resolve_path(str(sandbox)) == sandbox


def test_relative_path_without_roots_is_refused() -> None:
    with pytest.raises(PolicyViolation):
        Policy().resolve_path("anything")


def test_load_reads_json_and_defaults_to_dry_run(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({"allowed_capabilities": ["list_files"]}), encoding="utf-8")
    loaded = Policy.load(path)
    assert loaded.allowed_capabilities == frozenset({"list_files"})
    assert loaded.dry_run is True
    assert loaded.max_calls_per_minute == 60


def test_malformed_app_command_is_rejected_at_load_time() -> None:
    with pytest.raises(PolicyViolation):
        Policy.from_dict({"allowed_apps": {"firefox": "firefox"}})


def test_empty_app_command_is_rejected() -> None:
    with pytest.raises(PolicyViolation):
        Policy.from_dict({"allowed_apps": {"firefox": []}})
