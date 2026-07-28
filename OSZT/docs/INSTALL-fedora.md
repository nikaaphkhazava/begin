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
sudo dnf install wireplumber brightnessctl procps-ng flatpak btrfs-progs
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
flatpak install flathub org.mozilla.firefox com.discordapp.Discord \
  com.valvesoftware.Steam com.heroicgameslauncher.hgl com.usebottles.bottles
```

Soundux and `rog-control-center` come from the same COPR / Flathub; the shipped
policy expects `soundux` on `PATH`.

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
```

Do not try a 13B or larger model on this card. It will run, at a few tokens per
second, which makes the agent unusable rather than merely slow.

Voice, when you get to P4: `whisper.cpp` with `base.en` (~150MB) and Piper for
speech. Both leave enough VRAM for the model; `small` Whisper models do not.

## 5. Install OSZT

```bash
cd OSZT
python3 -m pytest            # 148 tests, no hardware needed
sudo packaging/install.sh
oszt doctor
```

`install.sh` creates the unprivileged `oszt-agent` user, `/etc/oszt/policy.json`
(copied from `policy.tuf-f15.json`, **dry run on**), the log and state
directories, and the two systemd units.

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
- **No write capabilities yet**: the broker cannot create, move or delete files.
  That is intentional until rollback is proven on your hardware.
