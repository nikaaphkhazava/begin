"""Eyes: turning the screen into words.

The text model that drives the tools cannot see. A separate small vision model
looks at a screenshot and describes it, and that description is what enters the
conversation. Two consequences worth knowing:

* the capture and the read both go through the broker, so looking at your screen
  is audited like any other action;
* on 4GB of VRAM a vision model and the text model cannot both stay resident, so
  looking at the screen evicts the text model and costs a reload. It is a
  deliberate, occasional act, not a live video feed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from oszt.agent.transport import AgentError, Transport, http_transport
from oszt.broker import Broker

DEFAULT_QUESTION = (
    "Describe what is on this screen: the focused application, any visible "
    "dialog or error, and what the user appears to be doing."
)


@dataclass
class VisionClient:
    """Minimal Ollama client for a multimodal model."""

    model: str = "moondream"
    base_url: str = "http://127.0.0.1:11434"
    transport: Transport = http_transport
    options: Mapping[str, Any] = field(default_factory=lambda: {"temperature": 0.0})

    def describe(self, image_base64: str, question: str = DEFAULT_QUESTION) -> str:
        payload = {
            "model": self.model,
            "prompt": question,
            "images": [image_base64],
            "stream": False,
            "options": dict(self.options),
        }
        response = self.transport(f"{self.base_url}/api/generate", payload)
        description = response.get("response")
        if not isinstance(description, str):
            raise AgentError(f"malformed response from the vision model: {response!r}")
        return description.strip()


def look_at_screen(
    broker: Broker, vision: VisionClient, question: str = DEFAULT_QUESTION
) -> dict[str, object]:
    """Capture the screen and return a written description of it."""
    captured = broker.call("capture_screen")
    path = str(captured["path"])
    if captured.get("dry_run"):
        return {"path": path, "description": "(dry run: no screenshot was taken)"}
    image = broker.call("read_screenshot_base64", path=path)
    return {"path": path, "description": vision.describe(str(image), question)}
