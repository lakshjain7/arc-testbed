# Lab machine: from nothing to collecting data

Machine: Intel i9 (20 cores), 32 GB RAM, 1 TB disk, NVIDIA A4000, reached over remote desktop.
The GPU is not used for data collection (only later, for training). Nothing here needs ARM changes.

Rule for the whole guide: **run one step, read its last lines, then the next.** Every script prints
what it did and stops with a clear message when something is wrong.

---

## 0. Before you start (5 minutes)

Find out two things about the machine:

| question | how | why it matters |
|---|---|---|
| Windows or Ubuntu? | look at the desktop | decides step 1A or 1B |
| Do we have admin / sudo? | Ubuntu: `sudo -v`. Windows: can you install programs? | Docker cannot be installed without it |

Also ask whether the machine will be **left on, not rebooted, not used by others** for the days the
run takes. Someone else starting a heavy job mid-run shows up in our data as fake "damage".

---

## 1A. If the machine runs Ubuntu (best case)

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/lakshjain7/arc-testbed.git ~/arc-testbed
cd ~/arc-testbed
bash setup/install-tools.sh
```

The first time, it installs Docker and tells you to log out and back in. Do that, then run
`bash setup/install-tools.sh` again; it must end with every line saying `ok`.

Go to step 2.

## 1B. If the machine runs Windows

Everything runs inside Ubuntu-on-Windows (WSL2), exactly as on the laptop.

1. **PowerShell as Administrator:**
   ```powershell
   wsl --install -d Ubuntu
   ```
   Reboot when asked, open "Ubuntu" from the Start menu, choose a username and password.

2. **Give WSL enough memory.** Create the file `C:\Users\<you>\.wslconfig` with exactly:
   ```ini
   [wsl2]
   memory=26GB
   processors=18
   swap=8GB
   ```
   Then in PowerShell: `wsl --shutdown`, and open Ubuntu again.

3. **Install Docker Desktop** (docker.com), start it, then
   Settings -> Resources -> WSL integration -> switch on "Ubuntu" -> Apply & restart.
   Settings -> General -> switch **off** "Resource Saver" (it pauses the cluster when idle).

4. **Stop Windows from sleeping:** Settings -> System -> Power -> Sleep: Never. Sleep breaks Docker
   (it did on the laptop, twice).

5. Inside Ubuntu:
   ```bash
   sudo apt-get update && sudo apt-get install -y git
   git clone https://github.com/lakshjain7/arc-testbed.git ~/arc-testbed
   cd ~/arc-testbed
   bash setup/install-tools.sh
   ```
   It must end with every line saying `ok`.

Keep the repository and the data **inside Ubuntu** (`~/...`), never under `/mnt/c/` (10x slower).

---

## 2. Build the cluster (1-2 hours, mostly downloading ~12 GB of images)

Start it inside tmux so a dropped remote-desktop connection does not kill it:

```bash
tmux new -s setup
cd ~/arc-testbed
bash setup/setup-cluster.sh
```

Leave tmux with **Ctrl+B then D** (the job keeps running). Come back with `tmux attach -t setup`.

It runs nine stages and names each one as it starts:
`cluster -> images -> deploy -> tame -> instrument -> bringup -> prometheus -> chaos -> verify`.

If a stage fails: read the message, fix, and continue from that stage, for example
`bash setup/setup-cluster.sh --from bringup`. Nothing has to be rebuilt from the start.

It is finished when it prints **"Cluster arc is up"** and a real booking has gone through.
Open http://localhost:32677 in the machine's browser (user `fdse_microservice`, password `111111`)
to see the website.

### Core 20 services or all 45?

Use the default (**core, 20 services**) for the first dataset. Reasons:

- The simulated users only search, book, pay and list orders. That path touches the 20 core services.
  The other 25 would run but receive no traffic, so they add memory use and no information.
- Core needs ~14 GB. All 45 need ~26 GB, which leaves no room for a second cluster.
- Two core clusters collect data twice as fast. That is worth more than idle services.

All 45 (`PROFILE=full bash setup/setup-cluster.sh`) becomes useful only after the load generator
learns more user flows (cancel, rebook, food, consign). That is a later extension, not day 1.

---

## 3. Find the load this machine can carry (15 minutes)

```bash
bash loadgen/step-test.sh "2 4 6" 180
```

For each rate it prints success %, latency, and which services are CPU-throttled. Pick the highest
rate that is ~100% successful with steady latency, and **use two thirds of it** (faults need room to
show damage). On the laptop that was 2 requests/s. Suppose the answer here is 4:

```bash
export ARC_RATE=4          # put this line in ~/.bashrc as well
```

More load = more requests per episode = smaller effects become measurable. This is the main thing
the bigger machine buys us.

---

## 4. Calibrate (about 3.5 hours, unattended)

```bash
bash run/start-campaign.sh calibrate
```

Runs 20 episodes with no fault and no action, to learn what "normal wobble" looks like on this
machine. At the end it prints a table; the last line must show a held-out false-harm rate near 0%.

Watch: `bash run/start-campaign.sh attach` (leave with Ctrl+B then D). Progress: `bash run/status.sh`.

---

## 5. Collect the dataset (days, unattended)

```bash
export ARC_BACKUP=/mnt/c/Users/<you>/OneDrive/ARC-data     # Windows; or a second disk on Ubuntu
export ARC_SYNC=1                                          # copy there every 25 episodes
bash run/start-campaign.sh campaign 700
```

- About 10 minutes per episode, so ~140 episodes per day per cluster. 700 is about 5 days.
- It **resumes**: after a reboot or a stop, the same command continues with the next unfinished episode.
- Stop cleanly with `bash run/start-campaign.sh stop` (never just close the window mid-episode;
  if that happens anyway, run `bash ops/cleanup.sh`).

### A second cluster (only if memory allows)

After the first cluster has been collecting for an hour:

```bash
free -g        # look at the "available" column
```

If more than **16 GB** is available, build and start a second one:

```bash
ARC_CLUSTER=arc2 ARC_INDEX=1 bash setup/setup-cluster.sh
ARC_CLUSTER=arc2 ARC_INDEX=1 bash run/start-campaign.sh campaign 700
```

On 32 GB under Windows this will probably **not** fit (Windows itself takes 4-6 GB). On Ubuntu it
probably will. If in doubt, stay with one: a cluster short of memory produces bad data, and bad data
is worse than less data.

---

## 6. Every day (2 minutes)

```bash
bash run/status.sh
```

Healthy looks like: runner RUNNING, load "failed 0-2%", episodes going up by ~6 per hour, discards
below ~10%, memory available above 3000 MB, disk not filling.

Look at the data itself: `~/arc-data/index/episodes.csv` (rebuilt by `bash run/sync-data.sh`), or the
copy in the backup folder, opens in Excel.

---

## 7. When something goes wrong

| what you see | what to do |
|---|---|
| Machine or Docker restarted | `bash ops/recover-after-restart.sh`, then `bash loadgen/warmup.sh`, then start the campaign again (it resumes) |
| `status.sh` says runner not running | read the last lines of `~/arc-data/arc/logs/campaign.log`; start the campaign again |
| Log says "STOPPING: 3 repairs did not fix the cluster" | `bash ops/health.sh` and read what is not ready; [RUNBOOK.md](RUNBOOK.md) has each known cause |
| Many episodes `discarded` | `bash run/status.sh` shows the reasons. "low_memory": too many clusters. "fault not verified": `bash setup/chaos-canary.sh` |
| Website gives errors after a stop | `bash ops/cleanup.sh` (a fault or a drained service was left behind) |
| Docker Desktop: "unexpected error", stuck starting | click **Quit**, never "Reset to factory defaults" (that deletes the cluster). Then `wsl --shutdown` in PowerShell and start Docker Desktop again |
| Image downloads fail inside the cluster | `ARC_FIX_DNS=1 bash setup/setup-cluster.sh --from images` |
| Disk filling | `docker system df`; the data itself is small (~1 MB per episode) |
| Want to start one cluster over | `kind delete cluster --name arc`, then `bash setup/setup-cluster.sh` (data in `~/arc-data` is kept) |

---

## 8. When the run is finished

```bash
bash run/sync-data.sh --tar
```

writes one `arc-data-<machine>-<date>.tar.gz` (a few hundred MB for 1,400 episodes). Copy it off the
machine. That file plus this repository is everything needed to train and to reproduce.

To free the machine: `kind delete cluster --name arc` (and `arc2`). Uninstalling Docker is optional.

---

## What was changed after the laptop pilot, and why

| pilot (laptop) | now | why |
|---|---|---|
| delay 300 ms, CPU squeezed to 1/4, blackhole | delay 50 / 100 ms, loss 5 / 15 %, CPU to 1/2 and ~1/3 | 18 of 46 pilot episodes were already fully broken before the action, so the action's effect could not be seen |
| one level per fault | two levels per fault | the model should learn that the same action costs more in a worse incident |
| 1 no-op per block | 2 no-ops per block of 7 (29%) | the no-op is the reference every action is compared with |
| yes/no "harmed" per service was the main label | sizes (`y_mean`, `y_peak`, `y_excess`, `t_recover`) are the main labels; yes/no kept as a secondary | the sizes separated actions clearly in the pilot, the yes/no did not |
| episodes that ended unhealthy were thrown away | kept, with `healthy_after` and `recovery_after_s` recorded | "this action left the system broken" is exactly what ARC must learn |
| one cluster, fixed ports and paths | any number of clusters, each with own ports, data, plan | scale |
