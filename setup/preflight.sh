#!/usr/bin/env bash
# Is this machine able to run ARC? Checks everything, installs and changes NOTHING. No sudo needed.
# Run it first on any new machine (Ubuntu, or Ubuntu inside WSL2 on Windows):
#   bash setup/preflight.sh
# Each line ends in OK, WARN (works, but read the note) or FAIL (must be fixed first).
pass=0; warn=0; fail=0
ok()   { printf "  OK    %-26s %s\n" "$1" "$2"; pass=$((pass+1)); }
wr()   { printf "  WARN  %-26s %s\n" "$1" "$2"; warn=$((warn+1)); }
bad()  { printf "  FAIL  %-26s %s\n" "$1" "$2"; fail=$((fail+1)); }
have() { command -v "$1" >/dev/null 2>&1; }
export PATH="$HOME/.local/bin:$PATH"

echo "== the machine"
ARCH=$(uname -m)
[ "$ARCH" = x86_64 ] && ok "CPU type" "x86_64" || bad "CPU type" "$ARCH (the Train Ticket images are validated on x86_64 only)"
C=$(nproc); [ "$C" -ge 8 ] && ok "CPU cores" "$C" || wr "CPU cores" "$C (8+ recommended; episodes will be noisy)"
MEM=$(free -m | awk '/^Mem:/{print $2}'); AV=$(free -m | awk '/^Mem:/{print $7}')
if   [ "$MEM" -ge 28000 ]; then ok "memory" "$((MEM/1024)) GB total, $((AV/1024)) GB available now -> 1 cluster for sure, a 2nd if >16 GB stays free"
elif [ "$MEM" -ge 15000 ]; then ok "memory" "$((MEM/1024)) GB total, $((AV/1024)) GB available now -> 1 core cluster"
else bad "memory" "$((MEM/1024)) GB total; one cluster needs ~14 GB"; fi
[ "$AV" -ge 14000 ] || wr "memory available now" "$((AV/1024)) GB; close other programs (a cluster needs ~14 GB)"
DISK=$(df -BG --output=avail "$HOME" | tail -1 | tr -dc 0-9)
# Under WSL, $HOME sits on a virtual disk whose "free space" is only its ceiling. What can really be
# written is what is free on the Windows drive that holds it (and Docker's own disk image).
if grep -qi microsoft /proc/version 2>/dev/null && [ -d /mnt/c ]; then
  WIN=$(df -BG --output=avail /mnt/c 2>/dev/null | tail -1 | tr -dc 0-9)
  [ -n "$WIN" ] && [ "$WIN" -lt "$DISK" ] && DISK=$WIN && DISKNOTE=" (free on the Windows C: drive, which is the real limit)"
fi
[ "$DISK" -ge 90 ] && ok "disk free" "${DISK} GB${DISKNOTE:-}" || { [ "$DISK" -ge 60 ] && wr "disk free" "${DISK} GB${DISKNOTE:-} (90+ recommended: a running cluster holds ~45 GB of images)" || bad "disk free" "${DISK} GB${DISKNOTE:-} (a running cluster holds ~45 GB of images, plus Docker's cache)"; }
if grep -qi microsoft /proc/version 2>/dev/null; then
  WSL=1; ok "system" "Ubuntu inside WSL2 on Windows ($(. /etc/os-release; echo "$PRETTY_NAME"))"
  case "$PWD" in /mnt/*) bad "folder" "you are under /mnt/ (Windows disk, 10x slower). Clone the repo into ~ instead";; *) ok "folder" "inside Ubuntu's own disk";; esac
  [ "$MEM" -lt 20000 ] && wr "WSL memory limit" "WSL sees only $((MEM/1024)) GB. Set memory= in C:\\Users\\<you>\\.wslconfig (docs/LAB-SETUP.md step 1B.2)"
else
  WSL=0; ok "system" "native Linux ($(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-unknown}"))"
  have apt-get || wr "package manager" "no apt-get: install-tools.sh assumes Ubuntu/Debian; install the tools by hand"
fi
if sudo -n true 2>/dev/null; then ok "admin rights (sudo)" "yes, without password"
elif id -nG | grep -qwE 'sudo|admin|wheel'; then ok "admin rights (sudo)" "you are in the sudo group (it will ask your password)"
else bad "admin rights (sudo)" "your user is not in the sudo group: Docker cannot be installed. Ask the lab admin"; fi
have nvidia-smi && ok "GPU" "$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1) (not needed for data collection; for training later)" \
  || wr "GPU" "nvidia-smi not found (fine for data collection; needed later for training)"

echo "== kernel features the faults need"
[ "$(stat -fc %T /sys/fs/cgroup 2>/dev/null)" = cgroup2fs ] && ok "cgroup v2" "yes" || wr "cgroup v2" "not cgroup v2: the CPU-squeeze fault and CPU metrics may behave differently"
if modinfo sch_netem >/dev/null 2>&1 || zgrep -q 'CONFIG_NET_SCH_NETEM=[ym]' /proc/config.gz 2>/dev/null || lsmod | grep -q sch_netem; then ok "netem (delay/loss)" "available"
else wr "netem (delay/loss)" "not found; setup's chaos canary will give the final answer. Fix: sudo apt-get install linux-modules-extra-\$(uname -r)"; fi
W=$(cat /proc/sys/fs/inotify/max_user_watches 2>/dev/null || echo 0)
[ "$W" -ge 524288 ] && ok "inotify watches" "$W" || wr "inotify watches" "$W (install-tools.sh raises it)"

echo "== tools (install-tools.sh installs the missing ones)"
for t in git curl python3 tmux rsync; do
  v=$([ $t = tmux ] && tmux -V || $t --version 2>&1 | head -1 | cut -c1-50)
  have $t && ok "$t" "$v" || wr "$t" "missing"
done
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null || bad "python3 version" "3.8 or newer is needed"
if docker info >/dev/null 2>&1; then
  ok "docker" "works, server $(docker version -f '{{.Server.Version}}'), $(docker info -f '{{.NCPU}} CPUs / {{.MemTotal}}' | awk '{printf "%s CPUs / %.0f GB", $1, $4/1e9}')"
  DM=$(docker info -f '{{.MemTotal}}'); [ "$DM" -lt 15000000000 ] && bad "docker memory" "Docker sees less than 15 GB; raise its limit (Docker Desktop -> Resources, or .wslconfig)"
  [ "$(docker info -f '{{.CgroupVersion}}')" = 2 ] || wr "docker cgroup" "Docker uses cgroup v$(docker info -f '{{.CgroupVersion}}')"
  n=$(docker ps -q | wc -l); [ "$n" -gt 0 ] && wr "other containers" "$n running: they take memory and CPU from the cluster ($(docker ps --format '{{.Names}}' | head -4 | tr '\n' ' '))"
elif have docker; then bad "docker" "installed but not reachable: start Docker (Windows: Docker Desktop + WSL integration; Linux: sudo systemctl start docker, and your user in the docker group)"
else wr "docker" "not installed yet (install-tools.sh does it on Linux; on Windows install Docker Desktop, see docs/LAB-SETUP.md 1B)"; fi
for t in kind kubectl helm; do have $t && ok "$t" "$($t version 2>/dev/null | head -1 | cut -c1-60)" || wr "$t" "not installed yet"; done

echo "== internet (images and tools are downloaded from these)"
for u in https://ghcr.io/v2/ https://registry-1.docker.io/v2/ https://registry.k8s.io/v2/ https://github.com https://dl.k8s.io https://charts.chaos-mesh.org/index.yaml; do
  code=$(curl -s -m 12 -o /dev/null -w '%{http_code}' "$u" 2>/dev/null)
  case "$code" in 2*|3*|401|403|404) ok "${u#https://}" "reachable (HTTP $code)";; *) bad "${u#https://}" "NOT reachable (HTTP ${code:-none}): firewall or proxy? Ask the lab admin";; esac
done
[ -n "${http_proxy:-}${https_proxy:-}${HTTPS_PROXY:-}" ] && wr "proxy" "a proxy is set (${https_proxy:-${HTTPS_PROXY:-$http_proxy}}): Docker needs it configured too"
SP=$(curl -s -m 25 -o /dev/null -w '%{speed_download}' https://dl.k8s.io/release/v1.34.0/bin/linux/amd64/kubectl 2>/dev/null | cut -d. -f1)
[ -n "$SP" ] && [ "$SP" -gt 0 ] && { MB=$((SP/1048576)); [ "$SP" -ge 2000000 ] && ok "download speed" "~${MB} MB/s (12 GB of images: about $((12000/(MB>0?MB:1)/60 + 1)) min)" || wr "download speed" "$((SP/1024)) KB/s: the image download will take hours"; }

echo "== ports this cluster will use (ARC_INDEX=${ARC_INDEX:-0})"
I=${ARC_INDEX:-0}
for p in $((32677+10*I)) $((19090+I)) $((13000+I)) $((8090+I)); do
  if (exec 3<>/dev/tcp/127.0.0.1/$p) 2>/dev/null; then
    if have kind && kind get clusters 2>/dev/null | grep -q .; then wr "port $p" "in use (by an existing ARC cluster? then fine)"; else bad "port $p" "already in use by another program"; fi
  else ok "port $p" "free"; fi
done

echo
echo "RESULT: $pass OK, $warn WARN, $fail FAIL"
if [ $fail -gt 0 ]; then echo "Fix the FAIL lines first (send them to Claude if unsure). Do not continue."; exit 1; fi
echo "This machine can run ARC. Next:  bash setup/install-tools.sh   (then run this check once more)"
