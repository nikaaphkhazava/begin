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

## Install it and click it

```bash
sudo dnf install python3-tkinter        # the toolbar needs it
./packaging/install-user.sh             # no root: adds OSZT to your app menu
```

OSZT then appears in the application menu. Launching it gives a small
always-on-top strip of buttons, each about the size of a mouse cursor:

| Button | What it does |
| --- | --- |
| **AI** | Turn Hermes on and off. Off also stops it watching the screen. |
| **EYE** | Look at the screen every 15 seconds and describe it. |

Add your own buttons by editing `~/.config/oszt/buttons.json` — no code changes.
A button is a goal ("clean up my downloads") or a single capability (quiet fans);
either way it goes through the same policy and ledger as everything else, so a
button the policy forbids reports the refusal and does nothing. See
[`buttons.example.json`](buttons.example.json).

The system half — the supervisor that rolls the OS back, and the weekly root
cleanup timer — is `sudo packaging/install.sh`.

## Try it without touching your system

`dry_run: true` swaps the real command runner for a recorder, so nothing
executes. Every shipped policy ships with it on:

```bash
cd OSZT
python -m pytest                                          # 285 tests, no hardware needed
python -m oszt doctor                                     # what this machine is missing
python -m oszt --policy policy.tuf-f15.json tools         # what the agent would see
python -m oszt --policy policy.tuf-f15.json call set_power_profile profile=Quiet
python -m oszt --policy policy.tuf-f15.json call set_gpu_mode mode=Integrated   # refused
python -m oszt --policy policy.tuf-f15.json call disk_usage path=~   # where the space went
python -m oszt --policy policy.tuf-f15.json apps                    # installable apps
python -m oszt --policy policy.tuf-f15.json apps install org.videolan.VLC
python -m oszt --policy policy.tuf-f15.json clean                   # the cleanup jobs
python -m oszt --policy policy.tuf-f15.json trash                   # undoable deletions
cat audit.jsonl                                           # the ledger
```

With Ollama running (`ollama pull qwen2.5:3b && ollama pull moondream`):

```bash
python -m oszt --policy policy.tuf-f15.json agent "put the laptop in quiet mode"
python -m oszt --policy policy.tuf-f15.json see        # describe the screen once
python -m oszt --policy policy.tuf-f15.json agent --see "why is my laptop slow?"
```

## How much control the agent has

Everything a policy lists, and nothing else. Two policies ship:

- `policy.tuf-f15.json` — reads all of `~`, changes only `~/oszt-workspace`.
  Start here.
- `policy.tuf-f15-open.json` — the 99.9% version: changes anything in `~`.

The 0.1% neither can reach, ever:

- the operating system: `/usr`, `/etc`, `/boot`, `/var`, `/ostree`, `/sysroot`, …
- OSZT itself: its policy, its ledger, its memory, its trash
- your keys: `~/.ssh`, `~/.gnupg`, `~/.pki`, the keyrings
- the second heart: snapshots and rollback are not capabilities at all

**Deleting is a move, not a shred.** `delete_path` moves the target into
`~/.local/share/oszt-trash` with a manifest and hands back an undo token;
`restore_path` puts it back. The trash is itself protected, so the agent cannot
empty it — only the weekly root timer expires entries older than 30 days.

**Downloads are leashed:** HTTPS only, to an allowlisted host, plain filename, a
size cap, and the execute bits are stripped afterwards. Nothing it downloads can
be run by it.

**Installing applications is Flatpak-only and `--user` only.** That is what keeps
it inside the boundary: apps, runtimes and game data land in
`~/.local/share/flatpak`, so installing software never writes to the OS and never
needs root. Flathub is the only remote, fixed in code rather than chosen by the
agent, and the app must be on the policy's `installable_apps` list *by exact id* —
so "install something to play music" cannot become "install anything". `dnf` and
`rpm-ostree` are not reachable at all: system packages stay a human action.
`uninstall_app` is limited to that same list, because removing an app takes its
data with it and no trash can undo that — it can only remove what it could add.

**Duplicates are reported, never deleted.** On Btrfs, `deduplicate` runs
`duperemove`, which frees the space while both copies keep existing.

**Seeing the screen is a slow heartbeat, not video.** Each look is a screenshot
plus a vision model, both audited. On 4GB of VRAM the text model and the vision
model cannot stay resident together, so expect a look every ten-odd seconds —
enough for "what is on screen", not enough to watch you type.

## Layout

| Module | Role |
| --- | --- |
| `oszt/policy.py` | The allowlist: capabilities, apps, filesystem roots, rate limit. Data, not code. |
| `oszt/broker.py` | The only door. Checks the policy, throttles, dispatches, logs, publishes the tool schema. |
| `oszt/capabilities/` | The individual actions: apps, files, audio/display, ASUS hardware, GPU telemetry. |
| `oszt/capabilities/apps.py` | Launch, close, and install/remove allowlisted Flatpak apps (`--user` only). |
| `oszt/capabilities/filesystem.py` | Write, move, copy, delete-to-trash, restore, search, disk usage. |
| `oszt/capabilities/janitor.py` | Named cleanup jobs, duplicate reporting, Btrfs dedupe. |
| `oszt/capabilities/net.py` | Downloads: allowlisted host, size cap, never executable. |
| `oszt/capabilities/screen.py` | Screenshots, and reading one back for a vision model. |
| `oszt/trash.py` | The undo layer under every deletion. |
| `oszt/agent/vision.py` | The eye: a local vision model that turns a screenshot into words. |
| `oszt/ui/buttons.py` | What the floating buttons do. All the behaviour, no GUI. |
| `oszt/ui/toolbar.py` | The floating always-on-top buttons themselves (tkinter). |
| `oszt/janitor_cli.py` | The weekly root cleanup and the only thing that purges trash. |
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
- **Deletion is reversible or it does not happen.** Overwriting a file trashes
  the old contents first. The trash is protected from the agent, and only the
  root timer purges it.
- **Installing is `--user` Flatpak from a fixed remote, off an id allowlist.** The
  one action that decides what code runs on the machine is the narrowest one.
- **Cleanup is named jobs, not file judgement.** A 3B model is fine at "run the
  cleanup"; it is not trustworthy at "this file looks useless". Cache directories
  are emptied in Python against hard-coded paths, so there is no `rm -rf` argv
  for a bug or a prompt injection to extend.
- **Root work stays root's.** Privileged cleaners are skipped, not attempted,
  when not running as root; the agent cannot acquire root by asking nicely.
- **The toolbar is data.** Buttons live in JSON, and a button cannot invent a
  capability the policy withholds.
- **Not proven on hardware yet.** Rollback has been tested in logic, not by
  wrecking a real Fedora install twenty times. Keep `dry_run: true` until you
  have read a session's ledger, and back your files up: an OS rollback restores
  the system, never your documents.

## Where this is in the plan

Done: P1 (broker, ledger, policy), the snapshot/rollback and watchdog machinery
of P2, P3 (local model driving the broker), the memory half of P4, and the broad
automation layer: files, cleanup, downloads, screen vision and the toolbar.

Not done: proving rollback on real hardware twenty times over (the actual point
of P2), voice, Arduino, the approved-skill library, and GUI automation — clicking
and typing on your behalf, which needs the Wayland-versus-Xorg decision in
`docs/INSTALL-fedora.md` first. Seeing the screen works; acting on it by mouse
does not yet.
