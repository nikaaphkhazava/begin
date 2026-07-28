"""Cleanup and duplicate hunting.

The important assertions are the refusals: no cleaner the policy has not named,
no root job from a non-root process, and no deletion of duplicates ever.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from oszt.broker import Context
from oszt.capabilities import janitor
from oszt.errors import CapabilityFailed, PolicyViolation
from oszt.policy import Policy
from oszt.runner import RecordingRunner


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "home"
    root.mkdir()
    return root


@pytest.fixture
def clean_policy(tree: Path, tmp_path: Path) -> Policy:
    return Policy.from_dict(
        {
            "allowed_capabilities": [
                "list_cleaners",
                "clean_caches",
                "find_duplicates",
                "deduplicate",
            ],
            "file_roots": [str(tree)],
            "write_roots": [str(tree)],
            "protected_paths": [],
            "trash_dir": str(tmp_path / "trash"),
            "allowed_cleaners": ["flatpak-unused", "thumbnails"],
            "dry_run": False,
        }
    )


@pytest.fixture
def ctx(clean_policy: Policy, runner: RecordingRunner) -> Context:
    return Context(policy=clean_policy, run=runner)


def test_only_allowed_cleaners_are_listed(ctx: Context) -> None:
    assert [job["name"] for job in janitor.list_cleaners(ctx)] == [
        "flatpak-unused",
        "thumbnails",
    ]


def test_running_an_allowed_cleaner_uses_a_fixed_command(
    ctx: Context, runner: RecordingRunner
) -> None:
    janitor.clean_caches(ctx, cleaner="flatpak-unused")
    assert runner.calls == [("flatpak", "uninstall", "--unused", "--assumeyes")]


def test_a_cleaner_absent_from_the_policy_is_refused(ctx: Context) -> None:
    with pytest.raises(PolicyViolation):
        janitor.clean_caches(ctx, cleaner="dnf-cache")


def test_an_invented_cleaner_is_refused(ctx: Context) -> None:
    with pytest.raises(PolicyViolation):
        janitor.clean_caches(ctx, cleaner="rm-everything")


def test_a_root_only_cleaner_is_skipped_rather_than_attempted(
    tree: Path, tmp_path: Path, runner: RecordingRunner
) -> None:
    policy = Policy.from_dict(
        {
            "allowed_capabilities": ["clean_caches"],
            "file_roots": [str(tree)],
            "allowed_cleaners": ["journal"],
            "trash_dir": str(tmp_path / "trash"),
            "dry_run": False,
        }
    )
    result = janitor.clean_caches(Context(policy=policy, run=runner), cleaner="journal")
    assert "privileged" in str(result["skipped"])
    assert runner.calls == []  # it did not even try


def test_no_cleaner_shells_out_to_a_destructive_command() -> None:
    """Deleting is done in Python against a literal path, never by rm -rf."""
    for cleaner in janitor.CLEANERS.values():
        assert bool(cleaner.argv) != bool(cleaner.directory)  # exactly one of the two
        assert cleaner.argv[:1] not in [("rm",), ("sh",), ("bash",)]
        assert not any(";" in part or "|" in part for part in cleaner.argv)


def test_a_directory_cleaner_empties_it_without_removing_it(
    ctx: Context, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "fake-home"
    thumbnails = fake_home / ".cache" / "thumbnails" / "large"
    thumbnails.mkdir(parents=True)
    (thumbnails / "a.png").write_bytes(b"0" * 100)
    monkeypatch.setenv("HOME", str(fake_home))

    result = janitor.clean_caches(ctx, cleaner="thumbnails")
    assert result["freed_bytes"] == 100
    assert (fake_home / ".cache" / "thumbnails").is_dir()  # the app still expects it
    assert not thumbnails.exists()


def test_a_directory_cleaner_in_dry_run_reports_but_deletes_nothing(
    tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "fake-home"
    thumbnails = fake_home / ".cache" / "thumbnails"
    thumbnails.mkdir(parents=True)
    (thumbnails / "a.png").write_bytes(b"0" * 50)
    monkeypatch.setenv("HOME", str(fake_home))

    policy = Policy.from_dict(
        {
            "allowed_capabilities": ["clean_caches"],
            "file_roots": [str(tree)],
            "allowed_cleaners": ["thumbnails"],
            "trash_dir": str(tmp_path / "trash"),
            "dry_run": True,
        }
    )
    result = janitor.clean_caches(
        Context(policy=policy, run=RecordingRunner()), cleaner="thumbnails"
    )
    assert result["freed_bytes"] == 50
    assert result["dry_run"] is True
    assert (thumbnails / "a.png").exists()


def test_a_cache_directory_that_does_not_exist_is_not_an_error(
    ctx: Context, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    assert "does not exist" in str(janitor.clean_caches(ctx, cleaner="thumbnails")["skipped"])


def test_duplicates_are_reported_with_the_space_they_would_free(
    ctx: Context, tree: Path
) -> None:
    payload = b"a" * (2 * 1024 * 1024)
    for name in ("one.bin", "two.bin", "three.bin"):
        (tree / name).write_bytes(payload)
    (tree / "different.bin").write_bytes(b"b" * (2 * 1024 * 1024))

    groups = janitor.find_duplicates(ctx, path=str(tree))
    assert len(groups) == 1
    assert sorted(Path(path).name for path in groups[0]["paths"]) == [
        "one.bin",
        "three.bin",
        "two.bin",
    ]
    assert groups[0]["reclaimable_bytes"] == 2 * len(payload)


def test_finding_duplicates_deletes_nothing(ctx: Context, tree: Path) -> None:
    payload = b"c" * (2 * 1024 * 1024)
    (tree / "a.bin").write_bytes(payload)
    (tree / "b.bin").write_bytes(payload)
    janitor.find_duplicates(ctx, path=str(tree))
    assert (tree / "a.bin").exists() and (tree / "b.bin").exists()


def test_files_of_the_same_size_but_different_contents_are_not_duplicates(
    ctx: Context, tree: Path
) -> None:
    (tree / "a.bin").write_bytes(b"a" * (2 * 1024 * 1024))
    (tree / "b.bin").write_bytes(b"b" * (2 * 1024 * 1024))
    assert janitor.find_duplicates(ctx, path=str(tree)) == []


def test_hunting_tiny_duplicates_is_refused(ctx: Context, tree: Path) -> None:
    with pytest.raises(CapabilityFailed):
        janitor.find_duplicates(ctx, path=str(tree), min_bytes=10)


def test_deduplicate_reclaims_space_without_deleting(
    ctx: Context, tree: Path, runner: RecordingRunner
) -> None:
    result = janitor.deduplicate(ctx, path=str(tree))
    assert runner.calls == [("duperemove", "-dr", str(tree))]
    assert result["deleted_nothing"] is True


def test_deduplicate_refuses_a_protected_directory(tree: Path, tmp_path: Path) -> None:
    policy = Policy.from_dict(
        {
            "allowed_capabilities": ["deduplicate"],
            "file_roots": ["/"],
            "write_roots": ["/"],
            "trash_dir": str(tmp_path / "trash"),
            "dry_run": False,
        }
    )
    with pytest.raises(PolicyViolation):
        janitor.deduplicate(Context(policy=policy, run=RecordingRunner()), path="/usr")
