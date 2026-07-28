"""Installing and removing applications.

Installing is the only action where the agent chooses what code lands on the
machine, so the assertions here are mostly about what it *cannot* do: no id off
the allowlist, no remote of its own choosing, no system-wide install, no dnf.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest

from oszt.broker import Context
from oszt.capabilities import apps
from oszt.errors import CapabilityFailed, PolicyViolation
from oszt.policy import Policy
from oszt.runner import CommandResult, RecordingRunner

INSTALLABLE = ["org.mozilla.firefox", "com.valvesoftware.Steam", "org.videolan.VLC"]


class FakeFlatpak:
    """A runner that answers ``flatpak list`` with a chosen set of ids."""

    def __init__(self, installed: Sequence[str] = (), returncode: int = 0) -> None:
        self.installed = list(installed)
        self.returncode = returncode
        self.calls: list[tuple[str, ...]] = []

    def which(self, binary: str) -> str | None:
        return f"/usr/bin/{binary}"

    def __call__(self, argv: Sequence[str]) -> CommandResult:
        recorded = tuple(str(part) for part in argv)
        self.calls.append(recorded)
        if "list" in recorded:
            return CommandResult(argv=recorded, stdout="\n".join(self.installed) + "\n")
        return CommandResult(argv=recorded, returncode=self.returncode, stdout="done\n")


def _policy(tmp_path: Path, **overrides: object) -> Policy:
    data: dict[str, object] = {
        "allowed_capabilities": ["install_app", "uninstall_app", "list_installable_apps"],
        "file_roots": [str(tmp_path)],
        "trash_dir": str(tmp_path / "trash"),
        "installable_apps": INSTALLABLE,
        "dry_run": False,
    }
    data.update(overrides)
    return Policy.from_dict(data)


@pytest.fixture
def runner() -> FakeFlatpak:
    return FakeFlatpak()


@pytest.fixture
def ctx(tmp_path: Path, runner: FakeFlatpak) -> Context:
    return Context(policy=_policy(tmp_path), run=runner)


def test_installing_an_allowlisted_app_goes_to_flathub_for_this_user_only(
    ctx: Context, runner: FakeFlatpak
) -> None:
    result = apps.install_app(ctx, app_id="org.videolan.VLC")
    assert result["returncode"] == 0
    assert runner.calls[-1] == (
        "flatpak",
        "install",
        "--user",
        "--assumeyes",
        "--noninteractive",
        "flathub",
        "org.videolan.VLC",
    )


def test_an_app_that_is_not_allowlisted_is_refused(ctx: Context, runner: FakeFlatpak) -> None:
    with pytest.raises(PolicyViolation):
        apps.install_app(ctx, app_id="org.some.Miner")
    assert not any("install" in call for call in runner.calls)


def test_the_agent_cannot_choose_the_remote_or_go_system_wide(
    ctx: Context, runner: FakeFlatpak
) -> None:
    """Every install argv is fixed apart from the allowlisted id."""
    apps.install_app(ctx, app_id="org.videolan.VLC")
    argv = runner.calls[-1]
    assert argv[0] == "flatpak"          # never dnf, never rpm-ostree
    assert "--user" in argv              # never --system
    assert argv.count("flathub") == 1    # the only remote
    assert argv[-1] in INSTALLABLE


def test_installing_something_already_present_does_nothing(tmp_path: Path) -> None:
    runner = FakeFlatpak(installed=["org.videolan.VLC"])
    ctx = Context(policy=_policy(tmp_path), run=runner)
    assert apps.install_app(ctx, app_id="org.videolan.VLC") == {
        "app_id": "org.videolan.VLC",
        "already_installed": True,
    }
    assert not any("install" in call for call in runner.calls)


def test_a_failing_install_is_reported_as_a_failure(tmp_path: Path) -> None:
    ctx = Context(policy=_policy(tmp_path), run=FakeFlatpak(returncode=1))
    with pytest.raises(CapabilityFailed):
        apps.install_app(ctx, app_id="org.videolan.VLC")


def test_uninstalling_is_limited_to_what_it_was_allowed_to_install(tmp_path: Path) -> None:
    """Removing an app takes its data with it, and no trash can undo that."""
    runner = FakeFlatpak(installed=["org.videolan.VLC", "com.discordapp.Discord"])
    ctx = Context(policy=_policy(tmp_path), run=runner)

    apps.uninstall_app(ctx, app_id="org.videolan.VLC")
    assert runner.calls[-1] == (
        "flatpak",
        "uninstall",
        "--user",
        "--assumeyes",
        "--noninteractive",
        "org.videolan.VLC",
    )

    with pytest.raises(PolicyViolation):
        apps.uninstall_app(ctx, app_id="com.discordapp.Discord")


def test_uninstalling_something_absent_does_nothing(ctx: Context, runner: FakeFlatpak) -> None:
    assert apps.uninstall_app(ctx, app_id="org.videolan.VLC") == {
        "app_id": "org.videolan.VLC",
        "already_absent": True,
    }
    assert not any("uninstall" in call for call in runner.calls)


def test_listing_says_which_allowlisted_apps_are_present(tmp_path: Path) -> None:
    ctx = Context(policy=_policy(tmp_path), run=FakeFlatpak(installed=["org.mozilla.firefox"]))
    assert apps.list_installable_apps(ctx) == [
        {"app_id": "com.valvesoftware.Steam", "installed": False},
        {"app_id": "org.mozilla.firefox", "installed": True},
        {"app_id": "org.videolan.VLC", "installed": False},
    ]


def test_a_policy_with_no_installable_apps_can_install_nothing(tmp_path: Path) -> None:
    ctx = Context(policy=_policy(tmp_path, installable_apps=[]), run=FakeFlatpak())
    assert apps.list_installable_apps(ctx) == []
    with pytest.raises(PolicyViolation):
        apps.install_app(ctx, app_id="org.videolan.VLC")


def test_a_malformed_id_in_the_policy_is_refused_at_load_time(tmp_path: Path) -> None:
    for bad in ("firefox", "--system", "org.videolan.VLC; rm -rf /", "../etc/passwd"):
        with pytest.raises(PolicyViolation):
            _policy(tmp_path, installable_apps=[bad])


def test_flatpak_missing_entirely_is_a_failure_not_a_silent_success(tmp_path: Path) -> None:
    """The listing shortcut tolerates a missing flatpak; the install must not."""

    class NoFlatpak:
        def which(self, binary: str) -> str | None:
            return None

        def __call__(self, argv: Sequence[str]) -> CommandResult:
            raise CapabilityFailed("executable 'flatpak' is not installed")

    ctx = Context(policy=_policy(tmp_path), run=NoFlatpak())
    assert apps.list_installable_apps(ctx) == [
        {"app_id": app_id, "installed": False} for app_id in sorted(INSTALLABLE)
    ]
    with pytest.raises(CapabilityFailed):
        apps.install_app(ctx, app_id="org.videolan.VLC")


def test_dry_run_records_the_install_without_performing_it(tmp_path: Path) -> None:
    runner = RecordingRunner()
    ctx = Context(policy=_policy(tmp_path, dry_run=True), run=runner)
    apps.install_app(ctx, app_id="org.videolan.VLC")
    assert runner.calls[-1][:3] == ("flatpak", "install", "--user")


def test_no_capability_here_can_reach_the_package_manager() -> None:
    """dnf and rpm-ostree write to the OS, so they are not the agent's to call."""
    source = Path(apps.__file__).read_text(encoding="utf-8")
    for forbidden in ('"dnf"', '"rpm-ostree"', '"--system"', '"sudo"', '"pkexec"'):
        assert forbidden not in source
