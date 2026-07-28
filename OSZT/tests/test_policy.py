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


# --- the new half: what may be *changed*, not just read -----------------------


def _write_policy(tmp_path: Path, home: Path, **overrides: object) -> Policy:
    data: dict[str, object] = {
        "allowed_capabilities": ["write_text", "delete_path"],
        "file_roots": [str(home)],
        "write_roots": [str(home / "workspace")],
        "protected_paths": [str(home / ".ssh")],
        "trash_dir": str(tmp_path / "trash"),
        "dry_run": False,
    }
    data.update(overrides)
    return Policy.from_dict(data)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    root = tmp_path / "home"
    (root / "workspace").mkdir(parents=True)
    (root / ".ssh").mkdir()
    return root


def test_a_writable_path_resolves(tmp_path: Path, home: Path) -> None:
    policy = _write_policy(tmp_path, home)
    assert policy.resolve_writable_path(str(home / "workspace/new.txt")) == (
        home / "workspace" / "new.txt"
    )


def test_a_path_that_is_only_readable_is_not_writable(tmp_path: Path, home: Path) -> None:
    policy = _write_policy(tmp_path, home)
    policy.resolve_path(str(home / ".ssh"))  # readable
    with pytest.raises(PolicyViolation):
        policy.resolve_writable_path(str(home / "notes.txt"))


def test_protected_paths_win_even_inside_a_write_root(tmp_path: Path, home: Path) -> None:
    policy = _write_policy(
        tmp_path,
        home,
        write_roots=[str(home)],
        protected_paths=[str(home / "workspace" / "keep")],
    )
    (home / "workspace" / "keep").mkdir()
    with pytest.raises(PolicyViolation):
        policy.resolve_writable_path(str(home / "workspace/keep/file.txt"))


def test_the_default_protected_paths_cover_the_operating_system() -> None:
    policy = Policy.from_dict({"write_roots": ["/"], "dry_run": False})
    for path in ("/usr/bin/python3", "/etc/passwd", "/boot/grub2", "/ostree/repo"):
        with pytest.raises(PolicyViolation):
            policy.resolve_writable_path(path)


def test_oszt_cannot_write_to_its_own_configuration_by_default() -> None:
    policy = Policy.from_dict({"write_roots": ["~"], "dry_run": False})
    for path in ("~/.config/oszt/policy.json", "~/.local/share/oszt/audit.jsonl", "~/.ssh/id_rsa"):
        with pytest.raises(PolicyViolation):
            policy.resolve_writable_path(path)


def test_a_symlink_out_of_a_write_root_is_refused(tmp_path: Path, home: Path) -> None:
    policy = _write_policy(tmp_path, home)
    (home / "workspace" / "escape").symlink_to(home / ".ssh")
    with pytest.raises(PolicyViolation):
        policy.resolve_writable_path(str(home / "workspace/escape/id_rsa"))


def test_writing_needs_a_write_root_to_exist_at_all(tmp_path: Path, home: Path) -> None:
    policy = _write_policy(tmp_path, home, write_roots=[])
    with pytest.raises(PolicyViolation):
        policy.resolve_writable_path(str(home / "workspace/new.txt"))


def test_hosts_must_be_allowlisted(tmp_path: Path, home: Path) -> None:
    policy = _write_policy(tmp_path, home, allowed_hosts=["flathub.org"])
    policy.check_host("flathub.org")
    with pytest.raises(PolicyViolation):
        policy.check_host("evil.example.com")


def test_a_policy_with_no_hosts_can_download_nothing(tmp_path: Path, home: Path) -> None:
    with pytest.raises(PolicyViolation):
        _write_policy(tmp_path, home).check_host("flathub.org")


def test_cleaners_must_be_allowlisted(tmp_path: Path, home: Path) -> None:
    policy = _write_policy(tmp_path, home, allowed_cleaners=["journal"])
    policy.check_cleaner("journal")
    with pytest.raises(PolicyViolation):
        policy.check_cleaner("dnf-cache")


@pytest.mark.parametrize(
    "name", ["policy.example.json", "policy.tuf-f15.json", "policy.tuf-f15-open.json"]
)
def test_every_shipped_policy_loads_and_stays_in_dry_run(name: str) -> None:
    policy = Policy.load(Path(__file__).resolve().parent.parent / name)
    assert policy.dry_run is True, f"{name} must ship in dry run"
    assert policy.allowed_capabilities


@pytest.mark.parametrize("name", ["policy.tuf-f15.json", "policy.tuf-f15-open.json"])
def test_no_shipped_policy_hands_over_the_desktop_or_the_whole_disk(name: str) -> None:
    policy = Policy.load(Path(__file__).resolve().parent.parent / name)
    assert "set_gpu_mode" not in policy.allowed_capabilities
    for root in policy.write_roots:
        assert root != Path("/")
        assert Path.home() in [root, *root.parents]


@pytest.mark.parametrize("name", ["policy.tuf-f15.json", "policy.tuf-f15-open.json"])
def test_every_shipped_policy_protects_the_os_and_oszt_itself(name: str) -> None:
    policy = Policy.load(Path(__file__).resolve().parent.parent / name)
    protected = {str(path) for path in policy.protected_paths}
    for required in ("/usr", "/etc", "/boot"):
        assert required in protected
    assert str(Path("~/.config/oszt").expanduser()) in protected
    assert str(Path("~/.ssh").expanduser()) in protected


@pytest.mark.parametrize("name", ["policy.tuf-f15.json", "policy.tuf-f15-open.json"])
def test_every_capability_named_by_a_shipped_policy_actually_exists(name: str) -> None:
    from oszt.capabilities import BUILTIN_CAPABILITIES

    policy = Policy.load(Path(__file__).resolve().parent.parent / name)
    assert policy.allowed_capabilities <= set(BUILTIN_CAPABILITIES)
