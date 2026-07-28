"""Seeing the screen: capture, and the vision model that turns it into words."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Mapping

import pytest

from oszt import build_broker
from oszt.agent.transport import AgentError
from oszt.agent.vision import VisionClient, look_at_screen
from oszt.broker import Broker, Context
from oszt.capabilities import screen
from oszt.errors import CapabilityFailed
from oszt.policy import Policy
from oszt.runner import RecordingRunner

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAwAB/AEBmwHqAAAAAElFTkSuQmCC"
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    return root


@pytest.fixture
def screen_policy(workspace: Path, tmp_path: Path) -> Policy:
    return Policy.from_dict(
        {
            "allowed_capabilities": ["capture_screen", "read_screenshot_base64"],
            "file_roots": [str(workspace)],
            "write_roots": [str(workspace)],
            "protected_paths": [],
            "trash_dir": str(tmp_path / "trash"),
            "dry_run": False,
        }
    )


class FakeCapture(RecordingRunner):
    """Stands in for grim: writes a real (tiny) png where it is told."""

    def __call__(self, argv):  # type: ignore[no-untyped-def]
        Path(argv[-1]).write_bytes(PNG)
        return super().__call__(argv)


def test_capture_writes_a_png_and_returns_its_path(screen_policy: Policy) -> None:
    ctx = Context(policy=screen_policy, run=FakeCapture())
    result = screen.capture_screen(ctx)
    assert Path(str(result["path"])).read_bytes() == PNG


def test_capture_prefers_wayland_then_falls_back_to_xorg(screen_policy: Policy) -> None:
    wayland = FakeCapture(installed={"grim"})
    screen.capture_screen(Context(policy=screen_policy, run=wayland))
    assert wayland.calls[0][0] == "grim"

    xorg = FakeCapture(installed={"scrot"})
    screen.capture_screen(Context(policy=screen_policy, run=xorg))
    assert xorg.calls[0][0] == "scrot"


def test_capture_refuses_when_no_screenshot_tool_exists(screen_policy: Policy) -> None:
    ctx = Context(policy=screen_policy, run=FakeCapture(installed=set()))
    with pytest.raises(CapabilityFailed) as error:
        screen.capture_screen(ctx)
    assert "grim" in str(error.value)


def test_the_model_never_chooses_the_screenshot_filename(screen_policy: Policy) -> None:
    runner = FakeCapture()
    ctx = Context(policy=screen_policy, run=runner)
    first = screen.capture_screen(ctx)["path"]
    second = screen.capture_screen(ctx)["path"]
    assert first != second
    for call in runner.calls:
        assert call[-1].endswith(".png")
        assert "screenshots" in call[-1]


def test_old_screenshots_are_pruned(screen_policy: Policy, workspace: Path) -> None:
    ctx = Context(policy=screen_policy, run=FakeCapture())
    directory = workspace / "screenshots"
    directory.mkdir()
    for index in range(30):
        (directory / f"{index:020d}.png").write_bytes(PNG)
    screen.capture_screen(ctx)
    assert len(list(directory.glob("*.png"))) == screen.MAX_KEPT_SHOTS


def test_a_capture_that_produces_no_file_is_an_error(screen_policy: Policy) -> None:
    ctx = Context(policy=screen_policy, run=RecordingRunner())  # writes nothing
    with pytest.raises(CapabilityFailed):
        screen.capture_screen(ctx)


def test_dry_run_takes_no_screenshot(workspace: Path, tmp_path: Path) -> None:
    policy = Policy.from_dict(
        {
            "allowed_capabilities": ["capture_screen"],
            "file_roots": [str(workspace)],
            "write_roots": [str(workspace)],
            "trash_dir": str(tmp_path / "trash"),
            "dry_run": True,
        }
    )
    result = screen.capture_screen(Context(policy=policy, run=RecordingRunner()))
    assert result["dry_run"] is True
    assert not (workspace / "screenshots").exists()


def test_only_png_files_can_be_read_as_screenshots(
    screen_policy: Policy, workspace: Path
) -> None:
    secret = workspace / "diary.txt"
    secret.write_text("private\n", encoding="utf-8")
    ctx = Context(policy=screen_policy, run=FakeCapture())
    with pytest.raises(CapabilityFailed):
        screen.read_screenshot_base64(ctx, path=str(secret))


def test_a_screenshot_is_read_back_as_base64(screen_policy: Policy) -> None:
    ctx = Context(policy=screen_policy, run=FakeCapture())
    path = str(screen.capture_screen(ctx)["path"])
    assert base64.b64decode(screen.read_screenshot_base64(ctx, path=path)) == PNG


def _vision(reply: object) -> VisionClient:
    def transport(url: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        transport.seen = {"url": url, "payload": payload}  # type: ignore[attr-defined]
        return {"response": reply} if reply is not None else {}

    return VisionClient(model="moondream", transport=transport)


def test_the_vision_model_is_asked_about_the_captured_image(
    screen_policy: Policy, tmp_path: Path
) -> None:
    broker = build_broker(screen_policy, tmp_path / "audit.jsonl", runner=FakeCapture())
    vision = _vision("A terminal with a failing test")
    looked = look_at_screen(broker, vision)
    assert looked["description"] == "A terminal with a failing test"
    seen = vision.transport.seen  # type: ignore[attr-defined]
    assert seen["url"].endswith("/api/generate")
    assert seen["payload"]["images"] == [base64.b64encode(PNG).decode("ascii")]


def test_looking_at_the_screen_is_audited_like_any_other_action(
    screen_policy: Policy, tmp_path: Path
) -> None:
    audit = tmp_path / "audit.jsonl"
    broker = build_broker(screen_policy, audit, runner=FakeCapture())
    look_at_screen(broker, _vision("a desktop"))
    logged = [entry["capability"] for entry in broker.audit.entries()]
    assert logged == ["capture_screen", "read_screenshot_base64"]


def test_a_malformed_vision_reply_is_an_error(
    screen_policy: Policy, tmp_path: Path
) -> None:
    broker = build_broker(screen_policy, tmp_path / "audit.jsonl", runner=FakeCapture())
    with pytest.raises(AgentError):
        look_at_screen(broker, _vision(None))


def test_looking_in_dry_run_says_so_instead_of_inventing_a_description(
    workspace: Path, tmp_path: Path
) -> None:
    policy = Policy.from_dict(
        {
            "allowed_capabilities": ["capture_screen", "read_screenshot_base64"],
            "file_roots": [str(workspace)],
            "write_roots": [str(workspace)],
            "trash_dir": str(tmp_path / "trash"),
            "dry_run": True,
        }
    )
    broker: Broker = build_broker(policy, tmp_path / "audit.jsonl")
    looked = look_at_screen(broker, _vision("should not be used"))
    assert "dry run" in str(looked["description"])
