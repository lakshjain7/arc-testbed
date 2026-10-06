#!/usr/bin/env bash
# One-time tool install on a fresh Ubuntu (native, or Ubuntu inside WSL2 on Windows).
# Needs sudo. Safe to re-run.
#   bash setup/install-tools.sh
set -u
ARCH=$(uname -m); case "$ARCH" in x86_64) A=amd64;; aarch64) A=arm64;; *) echo "unsupported CPU: $ARCH"; exit 1;; esac
IS_WSL=0; grep -qi microsoft /proc/version 2>/dev/null && IS_WSL=1
echo "== CPU $ARCH ($A), $( [ $IS_WSL = 1 ] && echo 'Ubuntu inside WSL2' || echo 'native Linux' ), $(nproc) cores, $(free -g | awk '/^Mem:/{print $2}') GB RAM"

echo "== base packages"
sudo apt-get update -qq
sudo apt-get install -y -qq curl git python3 tmux jq rsync ca-certificates >/dev/null && echo "   ok"

echo "== Docker"
if docker info >/dev/null 2>&1; then
  echo "   Docker already works: $(docker version -f '{{.Server.Version}}')"
elif [ $IS_WSL = 1 ]; then
  cat <<'TXT'
   Docker is not reachable from this Ubuntu. On Windows:
     1. Install Docker Desktop (https://www.docker.com/products/docker-desktop/), start it.
     2. Settings -> Resources -> WSL integration -> enable this Ubuntu distro -> Apply & restart.
     3. Create C:\Users\<you>\.wslconfig (see docs/LAB-SETUP.md) so WSL gets enough memory,
        then run `wsl --shutdown` in PowerShell and reopen Ubuntu.
   Then run this script again.
TXT
  exit 1
else
  sudo apt-get install -y -qq docker.io >/dev/null
  sudo systemctl enable --now docker
  sudo usermod -aG docker "$USER"
  echo "   Docker installed. LOG OUT AND BACK IN (or run: newgrp docker) so your user can use it, then re-run this script."
  docker info >/dev/null 2>&1 || exit 1
fi

mkdir -p "$HOME/.local/bin"; export PATH="$HOME/.local/bin:$PATH"
grep -q '.local/bin' "$HOME/.bashrc" 2>/dev/null || echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"

echo "== kind v0.30.0 (its default node image is Kubernetes v1.34.0)"
[ -x "$HOME/.local/bin/kind" ] || curl -fsSLo "$HOME/.local/bin/kind" "https://kind.sigs.k8s.io/dl/v0.30.0/kind-linux-$A"
chmod +x "$HOME/.local/bin/kind"; kind version

echo "== kubectl v1.34.0"
[ -x "$HOME/.local/bin/kubectl" ] || curl -fsSLo "$HOME/.local/bin/kubectl" "https://dl.k8s.io/release/v1.34.0/bin/linux/$A/kubectl"
chmod +x "$HOME/.local/bin/kubectl"; kubectl version --client 2>/dev/null | head -1

echo "== helm"
command -v helm >/dev/null || { curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | USE_SUDO=false HELM_INSTALL_DIR="$HOME/.local/bin" bash >/dev/null; }
helm version --short

echo "== kernel settings (several kind clusters need more inotify watches; less eager swapping)"
sudo sysctl -w fs.inotify.max_user_watches=524288 fs.inotify.max_user_instances=512 vm.swappiness=10 >/dev/null && echo "   set (until reboot)"
printf 'fs.inotify.max_user_watches=524288\nfs.inotify.max_user_instances=512\nvm.swappiness=10\n' | sudo tee /etc/sysctl.d/99-arc.conf >/dev/null

echo "== checks the faults depend on"
echo "   cgroup: $(stat -fc %T /sys/fs/cgroup)   (cgroup2fs expected)"
if modinfo sch_netem >/dev/null 2>&1 || zgrep -q 'CONFIG_NET_SCH_NETEM=y' /proc/config.gz 2>/dev/null; then echo "   netem (network delay/loss faults): available"
else echo "   netem: NOT FOUND. Try: sudo modprobe sch_netem   or   sudo apt-get install linux-modules-extra-\$(uname -r)"; fi
echo "   disk free in \$HOME: $(df -h "$HOME" | awk 'NR==2{print $4}')"
echo
echo "Tools ready. Next:  bash setup/setup-cluster.sh"
