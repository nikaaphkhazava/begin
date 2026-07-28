"""The floating buttons.

The GUI is untested on purpose; all the behaviour lives in the controller, so
these tests are what actually guarantee the two buttons behave.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from oszt.errors import PolicyViolation
from oszt.ui.buttons import ButtonSpec, ToolbarController, load_buttons


def _controller(**kwargs: object) -> ToolbarController:
    buttons = [
        ButtonSpec(label="AI", kind="agent"),
        ButtonSpec(label="EYE", kind="live_feed"),
        ButtonSpec(label="CLN", kind="goal", goal="clean up"),
        ButtonSpec(
            label="QT",
            kind="capability",
            capability="set_power_profile",
            arguments={"profile": "Quiet"},
        ),
    ]
    return ToolbarController(buttons=buttons, **kwargs)  # type: ignore[arg-type]


def test_the_default_layout_is_the_two_buttons_that_were_asked_for() -> None:
    buttons = load_buttons(None)
    assert [(button.label, button.kind) for button in buttons] == [
        ("AI", "agent"),
        ("EYE", "live_feed"),
    ]


def test_a_missing_button_file_falls_back_to_the_defaults(tmp_path: Path) -> None:
    assert len(load_buttons(tmp_path / "absent.json")) == 2


def test_buttons_can_be_added_without_touching_code(tmp_path: Path) -> None:
    path = tmp_path / "buttons.json"
    path.write_text(
        json.dumps(
            {
                "buttons": [
                    {"label": "AI", "kind": "agent"},
                    {"label": "NIGHT", "kind": "goal", "goal": "dim the screen"},
                ]
            }
        ),
        encoding="utf-8",
    )
    buttons = load_buttons(path)
    assert buttons[1].label == "NIGHT"
    assert buttons[1].goal == "dim the screen"


def test_the_shipped_example_layout_is_valid() -> None:
    example = Path(__file__).resolve().parent.parent / "buttons.example.json"
    labels = [button.label for button in load_buttons(example)]
    assert labels[:2] == ["AI", "EYE"]


@pytest.mark.parametrize(
    "button",
    [
        {"label": "X", "kind": "nonsense"},
        {"label": "", "kind": "agent"},
        {"label": "G", "kind": "goal"},  # no goal
        {"label": "C", "kind": "capability"},  # no capability
    ],
)
def test_a_broken_button_definition_is_rejected_loudly(button: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        ButtonSpec.from_dict(button)


def test_the_ai_button_toggles() -> None:
    controller = _controller()
    assert controller.agent_on is False
    assert "on" in controller.press(0)
    assert controller.agent_on is True
    assert "off" in controller.press(0)
    assert controller.agent_on is False


def test_turning_the_ai_off_also_stops_it_watching() -> None:
    controller = _controller()
    controller.press(0)  # ai on
    controller.press(1)  # feed on
    assert controller.live_feed_on is True
    controller.press(0)  # ai off
    assert controller.live_feed_on is False


def test_the_eye_button_does_nothing_until_the_ai_is_on() -> None:
    controller = _controller()
    assert "turn Hermes on first" in controller.press(1)
    assert controller.live_feed_on is False


def test_the_active_state_is_what_the_toolbar_paints() -> None:
    controller = _controller()
    controller.press(0)
    controller.press(1)
    states = {state.label: state.active for state in controller.state()}
    assert states == {"AI": True, "EYE": True, "CLN": False, "QT": False}


def test_a_goal_button_sends_its_instruction_to_the_agent() -> None:
    sent: list[str] = []
    controller = _controller(run_goal=lambda goal: sent.append(goal) or "done")
    controller.press(0)
    assert controller.press(2) == "done"
    assert sent == ["clean up"]


def test_a_capability_button_calls_the_broker_with_fixed_arguments() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def call(capability: str, **arguments: object) -> str:
        calls.append((capability, arguments))
        return "ok"

    controller = _controller(call_capability=call)
    controller.press(0)
    controller.press(3)
    assert calls == [("set_power_profile", {"profile": "Quiet"})]


def test_buttons_do_nothing_while_the_ai_is_off() -> None:
    calls: list[str] = []
    controller = _controller(
        run_goal=lambda goal: calls.append(goal) or "done",
        call_capability=lambda capability, **_: calls.append(capability) or "ok",
    )
    assert "turn Hermes on first" in controller.press(2)
    assert "turn Hermes on first" in controller.press(3)
    assert calls == []


def test_a_refused_button_reports_the_refusal_instead_of_crashing() -> None:
    def call(capability: str, **_: object) -> str:
        raise PolicyViolation(f"capability {capability!r} is not permitted by the policy")

    controller = _controller(call_capability=call)
    controller.press(0)
    assert controller.press(3).startswith("refused:")


def test_a_dead_model_does_not_take_the_toolbar_with_it() -> None:
    def explode(_goal: str) -> str:
        raise OSError("connection refused")

    controller = _controller(run_goal=explode)
    controller.press(0)
    assert controller.press(2).startswith("failed:")


def test_pressing_a_button_that_does_not_exist_is_survivable() -> None:
    assert "no button" in _controller().press(99)


def test_the_live_feed_only_looks_while_it_is_on() -> None:
    looks: list[int] = []
    controller = _controller(look_at_screen=lambda: looks.append(1) or "a desktop")

    assert controller.tick() is None  # feed off
    controller.press(0)
    controller.press(1)
    assert controller.tick() == "a desktop"
    assert controller.last_description == "a desktop"

    controller.press(1)  # feed off again
    assert controller.tick() is None
    assert len(looks) == 1


def test_a_feed_that_cannot_see_reports_it_rather_than_looping_on_errors() -> None:
    def blind() -> str:
        raise OSError("no screenshot tool")

    controller = _controller(look_at_screen=blind)
    controller.press(0)
    controller.press(1)
    assert str(controller.tick()).startswith("failed:")
    assert controller.live_feed_on is True  # still on; the human decides


def test_a_button_with_no_agent_wired_up_says_so() -> None:
    controller = _controller()
    controller.press(0)
    assert "no agent" in controller.press(2)
    assert "no broker" in controller.press(3)
