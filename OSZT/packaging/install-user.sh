#!/usr/bin/env bash
# The "just make it work" installer. No root, no systemd, no second heart -
# it installs OSZT for your own user and puts an OSZT icon in your app menu, so
# from then on you launch it by clicking it.
#
#   ./packaging/install-user.sh
#
# For the system parts (the supervisor that rolls the OS back, and the weekly
# root cleanup) run packaging/install.sh with sudo afterwards.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
config_dir="${XDG_CONFIG_HOME:-${HOME}/.config}/oszt"
apps_dir="${XDG_DATA_HOME:-${HOME}/.local/share}/applications"

if ! python3 -c 'import tkinter' 2>/dev/null; then
  echo "the toolbar needs tkinter. install it first:" >&2
  echo "  sudo dnf install python3-tkinter    # Fedora" >&2
  echo "  sudo apt install python3-tk         # Debian/Ubuntu" >&2
  exit 1
fi

mkdir -p "${config_dir}" "${apps_dir}" "${HOME}/oszt-workspace"

# Never overwrite a policy or a layout you have edited.
if [[ ! -f "${config_dir}/policy.json" ]]; then
  install -m 0644 "${repo_root}/policy.tuf-f15.json" "${config_dir}/policy.json"
  echo "policy   -> ${config_dir}/policy.json  (dry_run is ON: nothing will really happen yet)"
fi
if [[ ! -f "${config_dir}/buttons.json" ]]; then
  install -m 0644 "${repo_root}/buttons.example.json" "${config_dir}/buttons.json"
  echo "buttons  -> ${config_dir}/buttons.json  (edit this to add your own buttons)"
fi

# Installing applications is Flatpak-only and --user only, so the agent needs a
# Flathub remote in *its own* user installation. Adding it needs no root.
if command -v flatpak >/dev/null; then
  flatpak remote-add --if-not-exists --user \
    flathub https://flathub.org/repo/flathub.flatpakrepo || true
else
  echo "note: install flatpak if you want OSZT to install applications" >&2
fi

python3 -m pip install --user --upgrade "${repo_root}"

install -m 0644 "${repo_root}/packaging/oszt-toolbar.desktop" "${apps_dir}/oszt-toolbar.desktop"
if command -v update-desktop-database >/dev/null; then
  update-desktop-database "${apps_dir}" || true
fi

user_bin="$(python3 -c 'import site; print(site.USER_BASE + "/bin")')"
case ":${PATH}:" in
  *":${user_bin}:"*) ;;
  *) echo "note: add ${user_bin} to your PATH to run oszt from a terminal" ;;
esac

cat <<EOF

installed for $(whoami). OSZT is now in your application menu - click it to get
the floating buttons. From a terminal:

  ${user_bin}/oszt-toolbar
  ${user_bin}/oszt doctor

what the two buttons do:

  AI    turn Hermes on and off. Off means off: it also stops the screen watching.
  EYE   let Hermes look at the screen every 15 seconds and describe it.

it is in dry run: the buttons and the agent will report exactly what they *would*
do and change nothing. read ${config_dir}/audit.jsonl, then set
"dry_run": false in ${config_dir}/policy.json when you are ready.
EOF
