"""What the floating buttons do, with no GUI attached.

The toolbar is deliberately split in two: this module holds every decision and
is fully testable, while ``toolbar.py`` only draws rectangles and forwards
clicks. Adding a button is editing a JSON file - no code changes - which is the
same principle as the policy: your control surface is data you own.

Four kinds of button:

``agent``      toggle the agent on and off (the big one)
``live_feed``  toggle periodic looking at the screen
``goal``       send one fixed instruction, e.g. "clean up my downloads folder"
``capability`` call one broker capability directly, e.g. quiet mode

A button can never invent a capability the policy has not allowed: it goes
through the same broker as everything else, and an unpermitted button reports the
refusal instead of doing anything.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from oszt.errors import OSZTError

BUTTON_KINDS = ("agent", "live_feed", "goal", "capability")

# Two buttons, roughly the size of a mouse cursor, in the order the human asked
# for: turn the AI on, turn the live feed on. Everything else is added by them.
DEFAULT_BUTTONS: tuple[dict[str, Any], ...] = (
    {"label": "AI", "kind": "agent", "tooltip": "turn Hermes on and off"},
    {"label": "EYE", "kind": "live_feed", "tooltip": "let Hermes watch the screen"},
)


@dataclass(frozen=True)
class ButtonSpec:
    label: str
    kind: str
    tooltip: str = ""
    goal: str = ""
    capability: str = ""
    arguments: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ButtonSpec":
        kind = str(data.get("kind", ""))
        if kind not in BUTTON_KINDS:
            raise ValueError(f"button kind must be one of {BUTTON_KINDS}, got {kind!r}")
        label = str(data.get("label", "")).strip()
        if not label:
            raise ValueError("every button needs a label")
        if kind == "goal" and not data.get("goal"):
            raise ValueError(f"button {label!r} is a goal button but has no goal")
        if kind == "capability" and not data.get("capability"):
            raise ValueError(f"button {label!r} is a capability button but names none")
        return cls(
            label=label,
            kind=kind,
            tooltip=str(data.get("tooltip", "")),
            goal=str(data.get("goal", "")),
            capability=str(data.get("capability", "")),
            arguments=dict(data.get("arguments", {})),
        )


def load_buttons(path: Path | str | None) -> list[ButtonSpec]:
    """Load the button layout, falling back to the two default buttons."""
    if path is None or not Path(path).expanduser().exists():
        return [ButtonSpec.from_dict(button) for button in DEFAULT_BUTTONS]
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    buttons = data["buttons"] if isinstance(data, dict) else data
    if not isinstance(buttons, list) or not buttons:
        raise ValueError("the button file must contain a non-empty list of buttons")
    return [ButtonSpec.from_dict(button) for button in buttons]


@dataclass
class ButtonState:
    """What the toolbar should render for one button."""

    label: str
    tooltip: str
    active: bool = False


@dataclass
class ToolbarController:
    """The brain behind the buttons.

    ``run_goal`` is injected rather than imported so the toolbar can be driven by
    a real Hermes agent, by a stub in the tests, or by nothing at all.
    """

    buttons: Sequence[ButtonSpec]
    run_goal: Callable[[str], str] | None = None
    call_capability: Callable[..., Any] | None = None
    look_at_screen: Callable[[], str] | None = None
    agent_on: bool = False
    live_feed_on: bool = False
    last_message: str = "idle"
    last_description: str = ""

    def state(self) -> list[ButtonState]:
        return [
            ButtonState(
                label=button.label,
                tooltip=button.tooltip or button.goal or button.capability,
                active=self._is_active(button),
            )
            for button in self.buttons
        ]

    def press(self, index: int) -> str:
        """Handle a click and return the line to show the human."""
        try:
            button = self.buttons[index]
        except IndexError:
            return self._say(f"there is no button {index}")

        if button.kind == "agent":
            self.agent_on = not self.agent_on
            if not self.agent_on:
                # Turning the AI off also stops it watching. One button, one
                # honest promise: off means off.
                self.live_feed_on = False
            return self._say("Hermes is on" if self.agent_on else "Hermes is off")

        if button.kind == "live_feed":
            if not self.agent_on and not self.live_feed_on:
                return self._say("turn Hermes on first")
            self.live_feed_on = not self.live_feed_on
            return self._say(
                "watching the screen" if self.live_feed_on else "no longer watching"
            )

        if not self.agent_on:
            return self._say("turn Hermes on first")

        if button.kind == "goal":
            if self.run_goal is None:
                return self._say("no agent is connected")
            return self._say(self._guarded(lambda: self.run_goal(button.goal)))

        if self.call_capability is None:
            return self._say("no broker is connected")
        return self._say(
            self._guarded(
                lambda: str(
                    self.call_capability(button.capability, **dict(button.arguments))
                )
            )
        )

    def tick(self) -> str | None:
        """Called on a timer while the live feed is on.

        Returns a fresh description of the screen, or ``None`` when the feed is
        off or unavailable. A "live feed" on 4GB of VRAM is a slow heartbeat, not
        video: each look reloads a model.
        """
        if not self.live_feed_on or self.look_at_screen is None:
            return None
        description = self._guarded(self.look_at_screen)
        self.last_description = description
        return description

    def _is_active(self, button: ButtonSpec) -> bool:
        if button.kind == "agent":
            return self.agent_on
        if button.kind == "live_feed":
            return self.live_feed_on
        return False

    def _guarded(self, action: Callable[[], str]) -> str:
        """Never let a refusal or a dead model close the toolbar."""
        try:
            return action()
        except OSZTError as error:
            return f"refused: {error}"
        except Exception as error:  # the model, the network, a missing tool
            return f"failed: {error}"

    def _say(self, message: str) -> str:
        self.last_message = message
        return message
