# Running OSZT on an ASUS TUF Gaming F15 (RTX 3050)

Concrete setup for the target machine. Work through it in order; `oszt doctor`
tells you what is still missing at any point.

## 0. Which Fedora

Plain **Fedora Workstation** works for everything except the second heart.
**Fedora Silverblue** (Atomic) gives you A/B system images and
`rpm-ostree rollback` for free, which is the whole safety story. If you are
willing to reinstall once, do it now on Silverblue rather than rebuilding
rollback by hand later.

`oszt doctor` marks `rpm-ostree` optional for exactly this reason: everything
else runs on Workstation, but the automatic rollback does not.

## 1. Drivers and RPM Fusion

```bash
sudo dnf install \
  https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm \
  https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm
sudo dnf install akmod-nvidia xorg-x11-drv-nvidia-cuda
```

Reboot, then confirm the module built: `nvidia-smi` must print your RTX 3050.
On Silverblue use `rpm-ostree install` instead of `dnf install`, and reboot.

Secure Boot note: akmod-nvidia modules are unsigned by default. Either enroll
your own MOK or turn Secure Boot off, otherwise the driver silently fails to
load and `gpu_status` will keep refusing.

## 2. ASUS hardware (the Armoury Crate replacement)

```bash
sudo dnf copr enable lukenukem/asus-linux
sudo dnf install asusctl supergfxctl
sudo systemctl enable --now asusd supergfxd
```

Check it: `asusctl profile --profile-get` and `supergfxctl --get`. Keep the
laptop in **Hybrid** graphics mode - `Integrated` saves battery but the dGPU
disappears, and `AsusMuxDgpu` needs a reboot each way.

## 3. The rest of the tools

```bash
sudo dnf install wireplumber brightnessctl procps-ng flatpak btrfs-progs \
  curl duperemove python3-tkinter grim
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install flathub org.mozilla.firefox com.discordapp.Discord \
  com.valvesoftware.Steam com.heroicgameslauncher.hgl com.usebottles.bottles
```

Soundux and `rog-control-center` come from the same COPR / Flathub; the shipped
policy expects `soundux` on `PATH`.

What the newer tools are for: `curl` downloads, `duperemove` reclaims duplicate
space without deleting anything, `python3-tkinter` draws the floating buttons,
`grim` takes the screenshots the agent looks at. On an Xorg session install
`scrot` instead of `grim` - OSZT picks whichever it finds.

## 4. The model

The RTX 3050 Laptop card has **4GB of VRAM**, which is the binding constraint on
this whole project. Realistic options:

| Model | Fits in 4GB | Tool calling |
| --- | --- | --- |
| `qwen2.5:3b` (default) | yes, fully on GPU | reliable enough for this tool set |
| `llama3.2:3b` | yes | reliable, slightly weaker at multi-step plans |
| `qwen2.5:7b-instruct-q4_K_M` | no - partially on CPU | noticeably better, several times slower |

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:3b
ollama pull moondream        # the eye: ~1.7GB, only loaded when it looks
```

Sight costs a second model. `moondream` is the smallest useful one; `llava:7b` is
better and does not fit beside the text model on 4GB. Because both cannot stay
resident, each look evicts the other model and takes a few seconds - which is why
the live feed is a heartbeat every 15 seconds rather than video.

Do not try a 13B or larger model on this card. It will run, at a few tokens per
second, which makes the agent unusable rather than merely slow.

Voice, when you get to P4: `whisper.cpp` with `base.en` (~150MB) and Piper for
speech. Both leave enough VRAM for the model; `small` Whisper models do not.

## 5. Install OSZT

```bash
cd OSZT
python3 -m pytest             # 285 tests, no hardware needed
./packaging/install-user.sh   # your user: the toolbar, in your app menu
sudo packaging/install.sh     # the system: supervisor and weekly janitor
oszt doctor
```

`install-user.sh` writes `~/.config/oszt/policy.json` and
`~/.config/oszt/buttons.json`, installs the package for your user, and adds OSZT
to the application menu, so from then on you click an icon rather than typing.

`install.sh` creates the unprivileged `oszt-agent` user, `/etc/oszt/policy.json`
(copied from `policy.tuf-f15.json`, **dry run on**), the log and state
directories, and the systemd units.

## 5b. The buttons

```bash
oszt-toolbar     # or click OSZT in the app menu
```

Two buttons, mouse-cursor sized, always on top, draggable by the grip on the
left, right-click the grip to quit:

- **AI** turns Hermes on and off. Off also stops it watching the screen.
- **EYE** turns the live feed on: a look at the screen every 15 seconds.

More buttons go in `~/.config/oszt/buttons.json` - a goal button sends one fixed
instruction, a capability button calls one action directly. See
`buttons.example.json`. A button cannot exceed the policy: if the policy withholds
the capability, the button says `refused:` and nothing happens.

Autostart it at login, once you trust it:

```bash
mkdir -p ~/.config/autostart
cp /usr/share/applications/oszt-toolbar.desktop ~/.config/autostart/
```

## 5c. Letting it install apps and games

`install-user.sh` adds the Flathub remote to your *user* Flatpak installation,
which is where every install the agent makes goes:

```bash
oszt --policy ~/.config/oszt/policy.json apps                          # what it may install
oszt --policy ~/.config/oszt/policy.json apps install org.videolan.VLC
oszt --policy ~/.config/oszt/policy.json apps remove org.videolan.VLC
```

Why this does not endanger the OS: `flatpak install --user` puts the application,
its runtime and its data in `~/.local/share/flatpak`, and Steam games and Heroic
libraries live in your home too. So the agent can furnish the machine without ever
writing to `/usr`. System RPMs - drivers, kernel modules, `asusctl` - are the
exception and stay yours: on Silverblue they need `rpm-ostree` and a reboot, which
is exactly the protection we want.

To let it install something new, add the exact Flathub id to `installable_apps` in
`~/.config/oszt/policy.json`. Find ids at flathub.org, or:

```bash
flatpak search obs
```

Disk space is still one disk: home and the OS usually share the partition, so a
100GB game fills the same drive the system lives on. `oszt ... call disk_usage
path=~` is how you see where it went.

## 6. Watch it in dry run first

```bash
oszt --policy /etc/oszt/policy.json tools
oszt --policy /etc/oszt/policy.json call set_power_profile profile=Quiet
oszt --policy /etc/oszt/policy.json call set_gpu_mode mode=Integrated   # refused
tail -f /var/log/oszt/audit.jsonl
```

Nothing above touches the hardware while `dry_run` is true - the commands are
recorded, not executed. Read the ledger, confirm the argv is what you expect,
then set `"dry_run": false`.

## 7. Turn on the smoke alarm

```bash
sudo systemctl enable --now oszt-supervisor
systemctl status oszt-supervisor
sudo systemctl enable --now oszt-janitor.timer   # weekly cleanup, runs as root
systemctl list-timers oszt-janitor.timer
```

The janitor is also the only thing that empties the trash, and only entries older
than 30 days. Deleting through the agent is undoable until then:

```bash
oszt --policy ~/.config/oszt/policy.json trash
oszt --policy ~/.config/oszt/policy.json call restore_path trash_entry=<name>
```

Then give the agent a goal:

```bash
oszt --policy /etc/oszt/policy.json agent "put the laptop in quiet mode and dim the screen"
```

## 8. Before you trust it

Break it on purpose, twenty times, and confirm recovery each time: kill `asusd`,
mask `pipewire`, set brightness to 5%, fill the disk. `oszt --policy ... health`
must report the failure, and the supervisor must roll back after three
consecutive bad polls. Only then is P5 (bare metal, unattended) reasonable.

## Known limits on this hardware

- **Wayland**: GNOME on Wayland blocks synthetic input, so there is no
  click-and-type capability yet. `ydotool` needs a uinput group and a running
  daemon; an Xorg session is the simpler path if you want the agent to drive
  GUIs.
- **4GB VRAM**: a model and a game cannot share the card. Expect to stop the
  agent before gaming, or accept swapping.
- **Writing is on, but scoped.** The default policy changes only
  `~/oszt-workspace`. `policy.tuf-f15-open.json` widens that to all of `~`; it
  still cannot touch the OS, OSZT's own files, or your keys. Back your documents
  up before switching: rolling the OS back does not bring deleted files back, the
  30-day trash does.
- **Seeing is not touching.** The agent can describe the screen but cannot click
  or type on it, for the Wayland reason above.
- **It can install apps, not system packages.** Flatpak `--user` from Flathub,
  off an id allowlist. `dnf` and `rpm-ostree` are unreachable, so drivers and
  kernel modules remain your job.
- **Privileged cleanup is not the agent's.** `journal`, `dnf-cache` and
  `coredumps` are skipped when not root; they belong to the weekly timer.
