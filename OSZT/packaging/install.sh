#!/usr/bin/env bash
# Install OSZT on Fedora: unprivileged agent user, directories, systemd units.
# Run from the OSZT directory: sudo packaging/install.sh
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "run with sudo" >&2
  exit 1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The agent's own user, with no login shell and no groups that grant hardware
# access beyond what the broker needs.
if ! id oszt-agent &>/dev/null; then
  useradd --system --home-dir /var/lib/oszt --shell /sbin/nologin oszt-agent
fi

install -d -m 0755 /etc/oszt
install -d -m 0750 -o oszt-agent -g oszt-agent /var/lib/oszt
install -d -m 0750 -o oszt-agent -g oszt-agent /var/log/oszt
install -d -m 0755 /var/lib/oszt/snapshots

if [[ ! -f /etc/oszt/policy.json ]]; then
  install -m 0644 "${repo_root}/policy.tuf-f15.json" /etc/oszt/policy.json
  echo "installed default policy to /etc/oszt/policy.json (dry_run is on)"
fi

python3 -m pip install --prefix /usr "${repo_root}"

install -m 0644 "${repo_root}"/packaging/systemd/*.service /etc/systemd/system/
install -m 0644 "${repo_root}"/packaging/systemd/*.timer /etc/systemd/system/
install -m 0644 "${repo_root}/packaging/oszt-toolbar.desktop" /usr/share/applications/
systemctl daemon-reload

cat <<'EOF'

installed. next steps:

  oszt doctor                                   # what is still missing
  systemctl enable --now oszt-supervisor        # the smoke alarm
  systemctl enable --now oszt-janitor.timer     # the weekly cleanup
  sudo -u oszt-agent oszt --policy /etc/oszt/policy.json tools

for the clickable version, run this as your normal user (not root):

  packaging/install-user.sh                     # adds OSZT to your app menu

the agent runs on demand, per goal:

  systemctl start 'oszt-agent@put the laptop in quiet mode'

flip dry_run to false in /etc/oszt/policy.json only after watching a dry run.
EOF
