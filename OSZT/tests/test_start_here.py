"""Keep the walkthrough honest.

START-HERE.txt is the one file a new user actually reads, so a command that
drifted out of the CLI, or an installer flag that got renamed, is a worse bug
there than in the code.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from oszt.cli import _build_parser

ROOT = Path(__file__).resolve().parents[1]
GUIDE = (ROOT / "START-HERE.txt").read_text()


def test_the_guide_exists_and_covers_each_step_of_the_install() -> None:
    for step in ("git clone", "install-user.sh", "oszt doctor", "dry_run"):
        assert step in GUIDE


def test_it_never_tells_you_to_sudo_the_user_installer() -> None:
    assert "sudo ./packaging/install-user.sh" not in GUIDE
    assert "sudo packaging/install-user.sh" not in GUIDE


def test_every_oszt_subcommand_it_mentions_really_exists() -> None:
    mentioned = set(re.findall(r"oszt --policy \S+policy\.json (\w+)", GUIDE))
    assert mentioned, "the guide should show some commands"
    choices = _build_parser()._subparsers._group_actions[0].choices  # type: ignore[union-attr]
    for command in mentioned:
        assert command in choices, f"START-HERE.txt mentions unknown command {command!r}"


@pytest.mark.parametrize("flag", ["--no-ollama", "--with-ollama"])
def test_the_installer_flags_it_documents_are_real(flag: str) -> None:
    assert flag in GUIDE
    assert flag in (ROOT / "packaging" / "install-user.sh").read_text()


def test_it_states_the_limits_rather_than_selling_the_project() -> None:
    for limit in ("not video", "does not restore deleted", "never been tested"):
        assert limit in GUIDE
