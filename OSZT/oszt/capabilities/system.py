"""Display and audio adjustments.

Both capabilities take a percentage and clamp nothing: an out-of-range value is
a refusal, not a silent correction, so the ledger shows what the agent asked
for.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from oszt.errors import PolicyViolation

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from oszt.broker import Context

MIN_BRIGHTNESS_PERCENT = 5


def set_volume(ctx: "Context", percent: int) -> dict[str, object]:
    """Set the default audio sink volume to a percentage."""
    percent = _validate_percent(percent, minimum=0)
    ctx.run(
        ("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{percent / 100:.2f}")
    ).check()
    return {"percent": percent}


def set_brightness(ctx: "Context", percent: int) -> dict[str, object]:
    """Set display brightness to a percentage.

    Floored above zero so the agent cannot blank the screen and lock the human
    out of their own machine.
    """
    percent = _validate_percent(percent, minimum=MIN_BRIGHTNESS_PERCENT)
    ctx.run(("brightnessctl", "set", f"{percent}%")).check()
    return {"percent": percent}


def _validate_percent(percent: object, minimum: int) -> int:
    if isinstance(percent, bool) or not isinstance(percent, int):
        raise PolicyViolation(f"percent must be an integer, got {type(percent).__name__}")
    if percent < minimum or percent > 100:
        raise PolicyViolation(f"percent must be between {minimum} and 100, got {percent}")
    return percent
