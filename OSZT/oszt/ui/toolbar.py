"""The floating toolbar: two small always-on-top buttons.

Drawing only. Every decision lives in :mod:`oszt.ui.buttons`, so this file can be
dull and untested while the behaviour is covered.

    oszt-toolbar --policy ~/.config/oszt/policy.json

The window is undecorated, always on top, remembers nothing and can be dragged
anywhere by grabbing the grip on the left. Buttons are 44px - about a mouse
cursor. Right-click the grip to quit.
"""

from __future__ import annotations

import argparse
import tkinter as tk
from pathlib import Path

from oszt import build_broker
from oszt.agent import HermesAgent, OllamaClient, VisionClient, look_at_screen
from oszt.policy import Policy
from oszt.memory import MemoryStore
from oszt.ui.buttons import ToolbarController, load_buttons

BUTTON_SIZE = 44
IDLE_COLOUR = "#2b2b2b"
ACTIVE_COLOUR = "#2f7d4f"
TEXT_COLOUR = "#f2f2f2"
FEED_INTERVAL_MS = 15_000


class Toolbar:
    def __init__(self, controller: ToolbarController) -> None:
        self.controller = controller
        self.root = tk.Tk()
        self.root.title("OSZT")
        self.root.overrideredirect(True)  # no title bar: it is a palette, not a window
        self.root.attributes("-topmost", True)
        self.root.configure(bg=IDLE_COLOUR)
        self.root.geometry("+80+80")

        grip = tk.Frame(self.root, bg="#555555", width=10, height=BUTTON_SIZE)
        grip.pack(side="left", fill="y")
        grip.bind("<Button-1>", self._start_drag)
        grip.bind("<B1-Motion>", self._drag)
        grip.bind("<Button-3>", lambda _event: self.root.destroy())

        self.widgets: list[tk.Button] = []
        for index, state in enumerate(controller.state()):
            button = tk.Button(
                self.root,
                text=state.label,
                width=4,
                bg=IDLE_COLOUR,
                fg=TEXT_COLOUR,
                activebackground=ACTIVE_COLOUR,
                relief="flat",
                borderwidth=0,
                highlightthickness=0,
                command=lambda position=index: self._press(position),
            )
            button.pack(side="left", ipadx=2, ipady=6)
            self.widgets.append(button)

        self.status = tk.Label(
            self.root, text=controller.last_message, bg=IDLE_COLOUR, fg="#9a9a9a"
        )
        self.status.pack(side="left", padx=6)
        self.root.after(FEED_INTERVAL_MS, self._tick)

    def run(self) -> None:
        self.root.mainloop()

    def _press(self, index: int) -> None:
        self.status.configure(text=self.controller.press(index))
        self._repaint()

    def _tick(self) -> None:
        description = self.controller.tick()
        if description:
            self.status.configure(text=description[:80])
        self.root.after(FEED_INTERVAL_MS, self._tick)

    def _repaint(self) -> None:
        for widget, state in zip(self.widgets, self.controller.state()):
            widget.configure(bg=ACTIVE_COLOUR if state.active else IDLE_COLOUR)

    def _start_drag(self, event: "tk.Event[tk.Misc]") -> None:
        self._drag_origin = (event.x_root, event.y_root)
        self._window_origin = (self.root.winfo_x(), self.root.winfo_y())

    def _drag(self, event: "tk.Event[tk.Misc]") -> None:
        dx = event.x_root - self._drag_origin[0]
        dy = event.y_root - self._drag_origin[1]
        self.root.geometry(f"+{self._window_origin[0] + dx}+{self._window_origin[1] + dy}")


def build_controller(args: argparse.Namespace) -> ToolbarController:
    broker = build_broker(Policy.load(args.policy), args.audit)
    agent = HermesAgent(
        broker=broker,
        client=OllamaClient(model=args.model, base_url=args.ollama_url),
        memory=MemoryStore(args.memory),
    )
    vision = VisionClient(model=args.vision_model, base_url=args.ollama_url)
    return ToolbarController(
        buttons=load_buttons(args.buttons),
        run_goal=lambda goal: agent.run(goal).reply,
        call_capability=broker.call,
        look_at_screen=lambda: str(look_at_screen(broker, vision)["description"]),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="oszt-toolbar")
    default_config = Path("~/.config/oszt").expanduser()
    parser.add_argument("--policy", type=Path, default=default_config / "policy.json")
    parser.add_argument("--audit", type=Path, default=default_config / "audit.jsonl")
    parser.add_argument("--memory", type=Path, default=default_config / "memory.sqlite3")
    parser.add_argument(
        "--buttons",
        type=Path,
        default=default_config / "buttons.json",
        help="add your own buttons here; the file is JSON and needs no code changes",
    )
    parser.add_argument("--model", default="qwen2.5:3b")
    parser.add_argument("--vision-model", default="moondream")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    args = parser.parse_args(argv)

    Toolbar(build_controller(args)).run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
