# OSZT — P1: the broker

Phase 1 of the plan in [`../OSZT.txt`](../OSZT.txt): the door the AI will later
be allowed to knock on. **There is no AI in this phase on purpose.** The point
is to prove that nothing can happen to the machine except through an
allowlisted, logged, reversible path.

## The idea in one paragraph

The agent gets no shell, no filesystem handle and no subprocess access. It can
only name a capability (`open_app`, `set_volume`, …) and pass arguments. The
policy — plain JSON owned by a human — decides which capabilities exist, which
applications may be launched, and which directories are visible. Every call,
including every refusal, lands in an append-only ledger. A supervisor the agent
cannot reach snapshots the system before a batch of actions and rolls it back if
the machine is no longer healthy afterwards.

## Try it without touching your system

`dry_run: true` swaps the real command runner for a recorder, so nothing
executes:

```bash
cd OSZT
python -m pytest                                     # run the test suite
python -m oszt --policy policy.example.json tools    # what the agent would see
python -m oszt --policy policy.example.json call open_app app=firefox
python -m oszt --policy policy.example.json call open_app app=gparted   # refused
cat audit.jsonl                                      # the ledger
```

## Layout

| Module | Role |
| --- | --- |
| `oszt/policy.py` | The allowlist: capabilities, apps, filesystem roots, rate limit. Data, not code. |
| `oszt/broker.py` | The only door. Checks the policy, throttles, dispatches, logs. |
| `oszt/capabilities/` | The individual actions. Registering one does not grant it. |
| `oszt/runner.py` | Command execution. Takes argv, never a shell string. |
| `oszt/audit.py` | The append-only JSONL ledger. |
| `oszt/snapshots.py` | Btrfs snapshots and `rpm-ostree` rollback — the second heart. |
| `oszt/health.py` | Health checks and the supervisor that decides to roll back. |
| `oszt/cli.py` | Human front end for driving the broker before any model exists. |

## Design rules

- **Registering a capability is not permission.** The policy gates it, and
  forbidden capabilities are not even advertised in `tool_list()`.
- **The agent never supplies a command line.** It supplies an app *name*; the
  policy maps it to a fixed argv, which removes argument injection.
- **Paths are resolved before they are checked**, so `..` and symlinks cannot
  walk out of the allowed roots.
- **Out-of-range values are refused, not clamped**, so the ledger records what
  the agent actually asked for.
- **Brightness has a floor** — the agent cannot blank the screen and lock the
  human out.
- **No write, move or delete capability yet.** Those wait for P2, when rollback
  is proven.
- **Snapshots are not capabilities.** Only the supervisor can take or restore
  one, so the agent cannot destroy its own safety net.

## Not done yet

P2 (A/B images + watchdog integration), P3 (a local model calling `tool_list()`),
P4 (memory, voice, Arduino). Also open: pinning a Fedora version, the GPU/VRAM
budget that decides the model, and Wayland vs Xorg for input automation.
