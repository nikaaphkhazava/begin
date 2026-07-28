# OSZT

An AI-operated computer where the AI cannot break the machine — not because it
is trusted, but because it is architecturally unable to. Plan:
[`../OSZT.txt`](../OSZT.txt). Hardware-specific setup for the target laptop
(ASUS TUF Gaming F15, RTX 3050):
[`docs/INSTALL-fedora.md`](docs/INSTALL-fedora.md).

## The idea in one paragraph

The agent gets no shell, no filesystem handle and no subprocess access. It can
only name a capability (`open_app`, `set_power_profile`, …) and pass arguments.
The policy — plain JSON owned by a human — decides which capabilities exist,
which applications may launch, and which directories are visible. Every call,
including every refusal, lands in an append-only ledger. A supervisor the agent
cannot reach polls the health checks, pings the systemd watchdog, and boots the
other system image when the machine stops being usable.

## Try it without touching your system

`dry_run: true` swaps the real command runner for a recorder, so nothing
executes:

```bash
cd OSZT
python -m pytest                                          # 148 tests, no hardware needed
python -m oszt doctor                                     # what this machine is missing
python -m oszt --policy policy.tuf-f15.json tools         # what the agent would see
python -m oszt --policy policy.tuf-f15.json call set_power_profile profile=Quiet
python -m oszt --policy policy.tuf-f15.json call set_gpu_mode mode=Integrated   # refused
cat audit.jsonl                                           # the ledger
```

With Ollama running (`ollama pull qwen2.5:3b`):

```bash
python -m oszt --policy policy.tuf-f15.json agent "put the laptop in quiet mode"
```

## Layout

| Module | Role |
| --- | --- |
| `oszt/policy.py` | The allowlist: capabilities, apps, filesystem roots, rate limit. Data, not code. |
| `oszt/broker.py` | The only door. Checks the policy, throttles, dispatches, logs, publishes the tool schema. |
| `oszt/capabilities/` | The individual actions: apps, files, audio/display, ASUS hardware, GPU telemetry. |
| `oszt/agent/hermes.py` | The mind: a bounded loop over a local Ollama model that can only call tools. |
| `oszt/memory.py` | Long term memory in SQLite: facts plus action history. |
| `oszt/runner.py` | Command execution. Takes argv, never a shell string. |
| `oszt/audit.py` | The append-only JSONL ledger. |
| `oszt/snapshots.py` | Btrfs snapshots and `rpm-ostree` rollback — the second heart. |
| `oszt/health.py` | Health checks and the batch supervisor. |
| `oszt/supervisor.py` | The daemon that polls health and triggers rollback. |
| `oszt/watchdog.py` | `sd_notify` heartbeats to systemd. |
| `oszt/preflight.py` | `doctor`: which system tools are missing, and the command to install each. |
| `packaging/` | systemd units and the Fedora installer. |

## Design rules

- **Registering a capability is not permission.** The policy gates it, and
  forbidden capabilities are not advertised in `tool_list()` at all — so the
  model never learns they exist.
- **The agent never supplies a command line.** It supplies an app *name*; the
  policy maps it to a fixed argv, which removes argument injection.
- **Paths are resolved before they are checked**, so `..` and symlinks cannot
  walk out of the allowed roots.
- **Out-of-range values are refused, not clamped**, so the ledger records what
  the agent actually asked for.
- **Refusals are fed back to the model as tool results**, not raised. Hitting the
  wall is a normal observation it can explain to you, not a crash.
- **The loop is step-bounded.** A confused model burns steps, not the machine.
- **Dangerous-but-legitimate actions are registered and unlisted.**
  `set_gpu_mode` ends the desktop session, so no shipped policy includes it.
- **Brightness has a floor and charge limit has a floor** — the agent cannot
  blank the screen or fake a dead battery and lock the human out.
- **Snapshots are not capabilities.** Only the supervisor takes or restores one,
  so the agent cannot destroy its own safety net.
- **The agent unit has no `NOTIFY_SOCKET`**, so it cannot forge the supervisor's
  heartbeat. It also has no `CapabilityBoundingSet`, `ProtectSystem=strict`, and
  `IPAddressAllow=localhost` only.
- **No write, move or delete capability yet.** Those wait until rollback is
  proven on real hardware.

## Where this is in the plan

Done: P1 (broker, ledger, policy), the snapshot/rollback and watchdog machinery
of P2, P3 (local model driving the broker), and the memory half of P4.

Not done: proving rollback on real hardware twenty times over (the actual point
of P2), voice, Arduino, the approved-skill library, and any GUI automation —
which needs the Wayland-versus-Xorg decision in `docs/INSTALL-fedora.md` first.
