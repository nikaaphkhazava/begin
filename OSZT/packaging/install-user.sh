#!/usr/bin/env bash
# The "just make it work" installer. No root, no systemd, no second heart -
# it installs OSZT for your own user and puts an OSZT icon in your app menu, so
# from then on you launch it by clicking it.
#
#   ./packaging/install-user.sh                # asks before touching Ollama
#   ./packaging/install-user.sh --no-ollama    # never mention Ollama at all
#   ./packaging/install-user.sh --with-ollama  # yes to Ollama and both models
#
# For the system parts (the supervisor that rolls the OS back, and the weekly
# root cleanup) run packaging/install.sh with sudo afterwards.
set -euo pipefail

ollama_mode=ask
for argument in "$@"; do
  case "${argument}" in
    --no-ollama) ollama_mode=skip ;;
    --with-ollama) ollama_mode=yes ;;
    *) echo "unknown option: ${argument}" >&2; exit 2 ;;
  esac
done

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

# The mind is a local model, and without it the agent can hold no opinion: the
# buttons and capabilities still work, but nothing decides anything. So offer it -
# but never install it silently, and never twice: an Ollama that is already there,
# and a model already pulled, are left exactly alone.
agree() {
  case "${ollama_mode}" in
    skip) return 1 ;;
    yes) return 0 ;;
  esac
  if [[ ! -t 0 ]]; then
    echo "not a terminal, skipping: $1" >&2
    return 1
  fi
  read -r -p "$1 [y/N] " answer
  [[ ${answer} == [Yy]* ]]
}

if [[ ${ollama_mode} == skip ]]; then
  echo "skipping Ollama (--no-ollama); 'oszt doctor' will tell you what is missing"
elif command -v ollama >/dev/null; then
  echo "ollama   -> already installed, leaving it alone"
else
  echo
  echo "OSZT needs Ollama to run the AI locally (nothing is sent to a cloud)."
  if agree "install Ollama now from https://ollama.com/install.sh?"; then
    curl -fsSL https://ollama.com/install.sh | sh
  else
    echo "later: curl -fsSL https://ollama.com/install.sh | sh"
  fi
fi

if [[ ${ollama_mode} != skip ]] && command -v ollama >/dev/null; then
  have_models="$(ollama list 2>/dev/null || true)"
  for model in "qwen2.5:3b|the mind, ~2GB" "moondream|the eye that reads the screen, ~1.7GB"; do
    name="${model%%|*}"
    what="${model#*|}"
    if grep -q "^${name%%:*}" <<<"${have_models}"; then
      echo "model    -> ${name} already pulled"
    elif agree "pull ${name} (${what})?"; then
      ollama pull "${name}"
    else
      echo "later: ollama pull ${name}"
    fi
  done
fi

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

run 'oszt doctor' any time to see what is still missing, tools and models both.

every step of this, in plain language, is in ${repo_root}/START-HERE.txt
EOF
