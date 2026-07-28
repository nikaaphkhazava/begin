"""The dangerous half: writing, moving and deleting.

Every test here is really one question - can the agent reach something it should
never reach, and is a deletion always undoable?
"""

from __future__ import annotations

from pathlib import Path

import pytest

from oszt import build_broker
from oszt.broker import Broker, Context
from oszt.capabilities import filesystem
from oszt.errors import CapabilityFailed, PolicyViolation
from oszt.policy import Policy
from oszt.runner import RecordingRunner
from oszt.trash import Trash

WRITE_CAPABILITIES = [
    "write_text",
    "make_dir",
    "move_path",
    "copy_path",
    "delete_path",
    "restore_path",
    "list_trash",
    "find_files",
    "disk_usage",
]


@pytest.fixture
def home(tmp_path: Path) -> Path:
    root = tmp_path / "home"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "notes.txt").write_text("notes\n", encoding="utf-8")
    (root / ".ssh").mkdir()
    (root / ".ssh" / "id_ed25519").write_text("private key\n", encoding="utf-8")
    return root


@pytest.fixture
def write_policy(home: Path, tmp_path: Path) -> Policy:
    return Policy.from_dict(
        {
            "allowed_capabilities": WRITE_CAPABILITIES,
            "file_roots": [str(home)],
            "write_roots": [str(home)],
            "protected_paths": [str(home / ".ssh"), "/usr", "/etc"],
            "trash_dir": str(tmp_path / "trash"),
            "dry_run": False,
        }
    )


@pytest.fixture
def write_broker(write_policy: Policy, tmp_path: Path) -> Broker:
    return build_broker(write_policy, tmp_path / "audit.jsonl", runner=RecordingRunner())


@pytest.fixture
def ctx(write_policy: Policy) -> Context:
    return Context(policy=write_policy, run=RecordingRunner())


def test_writing_creates_a_file(ctx: Context, home: Path) -> None:
    filesystem.write_text(ctx, path=str(home / "new.txt"), content="hi")
    assert (home / "new.txt").read_text(encoding="utf-8") == "hi"


def test_overwriting_keeps_the_old_contents_in_the_trash(ctx: Context, home: Path) -> None:
    result = filesystem.write_text(ctx, path=str(home / "docs/notes.txt"), content="new")
    assert (home / "docs/notes.txt").read_text(encoding="utf-8") == "new"
    backup = str(result["backup"])
    assert (ctx.policy.trash_dir / backup).read_text(encoding="utf-8") == "notes\n"


def test_a_giant_write_is_refused(ctx: Context, home: Path) -> None:
    with pytest.raises(CapabilityFailed):
        filesystem.write_text(ctx, path=str(home / "big.txt"), content="x" * (9 * 1024 * 1024))


def test_deleting_is_reversible(ctx: Context, home: Path) -> None:
    target = home / "docs" / "notes.txt"
    deleted = filesystem.delete_path(ctx, path=str(target))
    assert not target.exists()
    assert deleted["reversible"] is True

    filesystem.restore_path(ctx, trash_entry=str(deleted["trash_entry"]))
    assert target.read_text(encoding="utf-8") == "notes\n"


def test_deleting_a_directory_takes_the_whole_tree_to_the_trash(
    ctx: Context, home: Path
) -> None:
    deleted = filesystem.delete_path(ctx, path=str(home / "docs"))
    assert not (home / "docs").exists()
    restored = filesystem.restore_path(ctx, trash_entry=str(deleted["trash_entry"]))
    assert (Path(str(restored["restored_to"])) / "notes.txt").exists()


def test_restore_refuses_a_path_masquerading_as_an_entry_name(ctx: Context) -> None:
    with pytest.raises(PolicyViolation):
        filesystem.restore_path(ctx, trash_entry="../../etc/passwd")


def test_restore_will_not_clobber_a_file_that_came_back(ctx: Context, home: Path) -> None:
    deleted = filesystem.delete_path(ctx, path=str(home / "docs/notes.txt"))
    (home / "docs" / "notes.txt").write_text("something else\n", encoding="utf-8")
    with pytest.raises(CapabilityFailed):
        filesystem.restore_path(ctx, trash_entry=str(deleted["trash_entry"]))


def test_the_trash_lists_what_can_still_be_undone(ctx: Context, home: Path) -> None:
    filesystem.delete_path(ctx, path=str(home / "docs/notes.txt"))
    entries = filesystem.list_trash(ctx)
    assert [entry["original_path"] for entry in entries] == [str(home / "docs/notes.txt")]


@pytest.mark.parametrize(
    "target",
    ["/usr/bin/python3", "/etc/passwd", "~/.ssh/id_ed25519"],
)
def test_protected_paths_can_never_be_deleted(ctx: Context, home: Path, target: str) -> None:
    path = target.replace("~", str(home))
    with pytest.raises(PolicyViolation):
        filesystem.delete_path(ctx, path=path)


def test_the_agents_own_keys_survive_a_symlink_into_them(ctx: Context, home: Path) -> None:
    lure = home / "docs" / "keys"
    lure.symlink_to(home / ".ssh")
    with pytest.raises(PolicyViolation):
        filesystem.delete_path(ctx, path=str(lure / "id_ed25519"))
    assert (home / ".ssh" / "id_ed25519").exists()


def test_deleting_a_symlink_removes_the_link_not_the_target(ctx: Context, home: Path) -> None:
    link = home / "docs" / "shortcut.txt"
    link.symlink_to(home / "docs" / "notes.txt")
    filesystem.delete_path(ctx, path=str(link))
    assert not link.exists()
    assert (home / "docs" / "notes.txt").exists()


def test_writing_outside_every_write_root_is_refused(ctx: Context, tmp_path: Path) -> None:
    with pytest.raises(PolicyViolation):
        filesystem.write_text(ctx, path=str(tmp_path / "elsewhere.txt"), content="no")


def test_the_trash_itself_is_protected(ctx: Context) -> None:
    with pytest.raises(PolicyViolation):
        filesystem.delete_path(ctx, path=str(ctx.policy.trash_dir))


def test_a_readable_but_unwritable_root_can_still_be_copied_from(
    home: Path, tmp_path: Path
) -> None:
    policy = Policy.from_dict(
        {
            "allowed_capabilities": ["copy_path"],
            "file_roots": [str(home)],
            "write_roots": [str(home / "docs")],
            "protected_paths": [],
            "trash_dir": str(tmp_path / "trash"),
            "dry_run": False,
        }
    )
    ctx = Context(policy=policy, run=RecordingRunner())
    filesystem.copy_path(
        ctx, source=str(home / "docs/notes.txt"), destination=str(home / "docs/copy.txt")
    )
    assert (home / "docs" / "copy.txt").read_text(encoding="utf-8") == "notes\n"


def test_moving_refuses_to_overwrite(ctx: Context, home: Path) -> None:
    (home / "docs" / "other.txt").write_text("other\n", encoding="utf-8")
    with pytest.raises(CapabilityFailed):
        filesystem.move_path(
            ctx, source=str(home / "docs/notes.txt"), destination=str(home / "docs/other.txt")
        )


def test_moving_creates_missing_parents(ctx: Context, home: Path) -> None:
    filesystem.move_path(
        ctx, source=str(home / "docs/notes.txt"), destination=str(home / "sorted/2026/notes.txt")
    )
    assert (home / "sorted" / "2026" / "notes.txt").exists()


def test_dry_run_touches_nothing(home: Path, tmp_path: Path) -> None:
    policy = Policy.from_dict(
        {
            "allowed_capabilities": WRITE_CAPABILITIES,
            "file_roots": [str(home)],
            "write_roots": [str(home)],
            "trash_dir": str(tmp_path / "trash"),
            "dry_run": True,
        }
    )
    ctx = Context(policy=policy, run=RecordingRunner())

    assert filesystem.delete_path(ctx, path=str(home / "docs/notes.txt"))["dry_run"] is True
    assert filesystem.write_text(ctx, path=str(home / "new.txt"), content="x")["dry_run"] is True
    assert filesystem.make_dir(ctx, path=str(home / "fresh"))["dry_run"] is True

    assert (home / "docs" / "notes.txt").read_text(encoding="utf-8") == "notes\n"
    assert not (home / "new.txt").exists()
    assert not (home / "fresh").exists()


def test_find_files_matches_a_glob(ctx: Context, home: Path) -> None:
    assert filesystem.find_files(ctx, pattern="*.txt", path=str(home)) == [
        str(home / "docs" / "notes.txt")
    ]


def test_find_files_caps_its_own_result_size(ctx: Context, home: Path) -> None:
    for index in range(10):
        (home / "docs" / f"file{index}.log").write_text("x", encoding="utf-8")
    assert len(filesystem.find_files(ctx, pattern="*.log", path=str(home), limit=3)) == 3
    with pytest.raises(CapabilityFailed):
        filesystem.find_files(ctx, pattern="*", path=str(home), limit=10_000)


def test_disk_usage_explains_where_the_space_went(ctx: Context, home: Path) -> None:
    (home / "big").mkdir()
    (home / "big" / "blob.bin").write_bytes(b"0" * 4096)
    usage = filesystem.disk_usage(ctx, path=str(home))
    assert usage["total_bytes"] >= 4096
    assert str(usage["largest"][0]["name"]) == "big"


def test_write_capabilities_go_through_the_policy_like_everything_else(
    write_broker: Broker, home: Path
) -> None:
    write_broker.call("write_text", path=str(home / "via-broker.txt"), content="hi")
    assert (home / "via-broker.txt").exists()
    with pytest.raises(PolicyViolation):
        write_broker.call("deduplicate", path=str(home))


def test_the_trash_refuses_to_purge_anything_recent(tmp_path: Path) -> None:
    trash = Trash(tmp_path / "trash")
    with pytest.raises(CapabilityFailed):
        trash.purge(older_than_days=0.5)


def test_purging_only_removes_expired_entries(tmp_path: Path) -> None:
    now = 1_000_000.0
    trash = Trash(tmp_path / "trash", clock=lambda: now)
    old = tmp_path / "old.txt"
    old.write_text("old\n", encoding="utf-8")
    stale = trash.put(old)

    later = Trash(tmp_path / "trash", clock=lambda: now + 40 * 86400)
    fresh_file = tmp_path / "fresh.txt"
    fresh_file.write_text("fresh\n", encoding="utf-8")
    fresh = later.put(fresh_file)

    assert later.purge(older_than_days=30) == [stale.entry]
    assert (later.directory / fresh.entry).exists()
