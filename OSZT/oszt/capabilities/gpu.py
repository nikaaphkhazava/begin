"""Read-only NVIDIA telemetry.

The agent needs this to reason about whether it can load a model or launch a
game. Nothing here changes GPU state: clocks, power limits and persistence mode
are not exposed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from oszt.errors import CapabilityFailed

if TYPE_CHECKING:  # pragma: no cover - import cycle guard
    from oszt.broker import Context

_FIELDS = ("name", "memory.total", "memory.used", "temperature.gpu", "utilization.gpu")


def gpu_status(ctx: "Context") -> dict[str, object]:
    """Report GPU model, VRAM use, temperature and utilisation."""
    result = ctx.run(
        (
            "nvidia-smi",
            f"--query-gpu={','.join(_FIELDS)}",
            "--format=csv,noheader,nounits",
        )
    ).check()
    line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    parts = [part.strip() for part in line.split(",")]
    if len(parts) != len(_FIELDS):
        raise CapabilityFailed(f"could not parse nvidia-smi output: {line!r}")

    name, total, used, temperature, utilisation = parts
    return {
        "name": name,
        "vram_total_mib": int(total),
        "vram_used_mib": int(used),
        "vram_free_mib": int(total) - int(used),
        "temperature_c": int(temperature),
        "utilisation_percent": int(utilisation),
    }
