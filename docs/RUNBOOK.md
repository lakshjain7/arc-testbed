# ARC infra runbook — Train Ticket on kind (WSL2)

> **Read this first (2026-10-07).** This runbook was written while building the first cluster on the laptop.
> It is the record of every failure met and its fix. Paths such as `~/arc/infra/NN-*.sh` are the original
> numbered laptop scripts; the same fixes now live in `setup/setup-cluster.sh` (one stage per topic) and
> in `ops/`. For a new machine follow [LAB-SETUP.md](LAB-SETUP.md); come here when a stage fails.

State as of 2026-09-28 (after a full rebuild): **32 pods, all Ready: 21 core services, 3-copy MySQL and Nacos, RabbitMQ, flagd, plus Prometheus/Grafana in kube-system. Login, search and booking verified end to end, with the order confirmed in the database. About 2.2 GB of memory free.** Not yet redone on the new cluster: the OTel collector and agents, the Grafana dashboard (saved in `archive-before-rebuild/grafana-dashboard.json`), and Chaos Mesh. All images for those are already loaded on the nodes.
Everything below was learned by hitting the failure first. Working scripts are in `infra/wsl-scripts/` (copied from `~/arc/infra` inside Ubuntu).

## Pods stuck at `ContainerCreating` with no IP: it is almost always an image download

**Learned the hard way on 2026-09-28, after two days of chasing the wrong cause.**

The symptom looks like broken pod networking: the pod is `ContainerCreating`, shows no IP, `PodReadyToStartContainers: False`. It usually isn't. Check the pod's events first. If the last event is `Pulling image ...` with no `Pulled` after it, the pod is waiting for a download. Kubelet does not refresh the pod's status (including its IP) while it waits, even though the network sandbox was already created successfully (`journalctl -u containerd` on the node shows `RunPodSandbox ... returns sandbox id`).

Why downloads are the problem on this laptop:
- Pulls from inside the kind nodes run at **~200 KB/s**. Each Train Ticket image is ~150 MB.
- Kubelet's default is **one download at a time per node**, so one big image blocks every other pod on that node, even a 1 MB busybox.
- Each of the 3 nodes downloads every image separately.

The decisive test (30 seconds): run a pod whose image is already on the node, with `--image-pull-policy=Never`. If it is `Running` with an IP in seconds, networking is fine and the problem is the download queue.

**The fix, now part of the setup:**
1. `kind-cluster.yaml` sets `serializeImagePulls: false` and `maxParallelImagePulls: 3`.
2. **Never let the nodes download images themselves.** Run `preload-images.sh` before starting services. It downloads each image once through Docker Desktop (**~2 MB/s, about 10x faster** than the in-node path), then copies it into all nodes with no network. The full set of 33 images took 46 minutes the first time.
3. Docker Desktop keeps those images, so after `kind delete cluster` + recreate, re-running `preload-images.sh` only does the local copy and takes minutes.
4. **Multi-platform images** (the `ts-*` images are amd64+arm64) break plain `kind load docker-image` with `ctr: content digest ... not found`, because it imports all platforms but only amd64 was downloaded. Use `docker save --platform linux/amd64 <img> -o x.tar && kind load image-archive x.tar` (the script does this).

**Do not rebuild the cluster to fix stuck pods.** `kind delete cluster` throws away every image the nodes downloaded. The original deploy took ~23 hours largely because of this, and a rebuild on 2026-09-28 cost another ~1.5 hours of downloads. Things ruled out along the way, so they don't get re-investigated: containerd or kubelet being stuck, node memory, CNI (kindnet) and kube-proxy, pod-start concurrency, and clock skew (the 3.5 h difference between WSL and Windows is only a timezone display difference, and UTC matches).

**Still unexplained:** on the old cluster, `kubectl port-forward` once failed with `Authorization error (user=kube-apiserver-kubelet-client, verb=create, resource=nodes, subresource=proxy)`. This has not been seen on the new cluster. If it comes back, investigate it on its own; don't assume it's part of the image problem.

## Warm-up, and what a 504 does and doesn't mean (2026-09-28)

- **The first request through freshly started services is very slow.** Measured on the same search: 60+ s the first time (the UI's nginx gave up with `504`), 30 s the second, 0.9 s the third. Every Java service in the chain initialises lazily on its first call. **The harness must send warm-up requests after any restart before it starts measuring a baseline**, or the baseline is really measuring cold start.
- **A 504 from the UI is not a failed request.** A booking that returned 504 still completed in the backend: the order was in the database, and it showed up twice after a retry. So a client-side error and the server-side outcome can differ. ΔSLO should be measured from both service-side telemetry and the client, not the client alone.

## MySQL at 3 copies, Nacos at 1 standalone copy (decision, 2026-09-28)

**MySQL (`nacosdb`, `tsdb`): keep 3 copies.** After the rebuild both are healthy: one leader, two followers, and live replication streams on the leader ("Master has sent all binlog to slave"). Semi-sync works because real followers acknowledge writes. Every MySQL problem on 2026-09-25/27 (leader never elected, writes blocked on semi-sync) came from squeezing these down to 1 copy, and none of it applies at 3. That matters once Chaos Mesh starts killing pods.

**Nacos: 1 copy, `MODE=standalone`.** At 3 copies, Nacos 2.0.1's registry replication did not stay consistent. After a rolling restart the copies knew 7, 7 and 20 services, and even after restarting the stale copies from a healthy peer they settled at 8, 8 and 20 (log: `DistroClientDataProcessor has not finished initial step`). An inconsistent registry means random `503`s depending on which copy answers a lookup, which would silently pollute every experiment. With one copy the registry is consistent by construction. All 20 services re-registered in 40 s. Trade-off: Nacos is a single point of failure. That's fine because it's infrastructure, not a fault target, in v1. (The services use nacos-client 2.2.0 against server 2.0.1, which may be part of why replication misbehaves.)

**Nacos memory:** the image defaults to `-Xms1g -Xmx1g` in cluster mode, about 1.5 GB RSS per copy. We now set `JVM_XMS=256m JVM_XMX=512m JVM_XMN=128m` on the StatefulSet. Garbage collection stays healthy at ~200 MB heap in use.

**Memory, measured 2026-09-28 (WSL available):** 2.0 GB with 21 services and 3-copy Nacos, 3.9 GB after the Nacos heap cap, **5.7 GB with standalone Nacos**. Measuring note: right after a StatefulSet pod restarts, Prometheus briefly adds the old container's memory to the new pod of the same name. Trust `free -m` inside WSL, or re-measure after ~5 minutes.

**After Nacos restarts, allow ~40–60 s for services to re-register** before measuring anything. Search returned `503` for about 60 s after the rolling restart and then recovered on its own.

## MySQL OOMKilled in a loop on a fresh cluster: the open-files limit (lab machine, 2026-10-10)

**Symptom.** During stage `deploy`, `nacosdb-mysql-0` (or `tsdb-mysql-*`) restarts again and again with exit
code 137 (OOMKilled) and an **empty log**; the deploy job never finishes. 20 restarts in 28 minutes on the lab machine.

**Cause.** With a recent Docker Desktop (4.94), containerd inside the kind nodes runs with `LimitNOFILE=infinity`
and the host allows 2^31 open files, so every container sees an open-files limit of about 2 billion. MySQL 5.7
sizes internal tables from that limit and asks for far more memory than the pod may use. (The link to MySQL's
sizing is inferred from the fix working; no MySQL log line was captured. It did not happen with Docker Desktop
4.55 on the laptop.)

**Fix.** Cap the limit on every node, then recreate the pod. `setup/setup-cluster.sh` now does this in stage
`cluster`, before anything is deployed; on an existing cluster:
```bash
for n in $(kind get nodes --name arc); do
  docker exec $n sh -c 'mkdir -p /etc/systemd/system/containerd.service.d && printf "[Service]\nLimitNOFILE=1048576\n" > /etc/systemd/system/containerd.service.d/10-nofile.conf && systemctl daemon-reload && systemctl restart containerd'
done
kubectl --context kind-arc -n train-ticket delete pod nacosdb-mysql-0     # only new containers get the new limit
```
The pod was healthy 65 seconds later. Check a container's limit with `kubectl exec <pod> -- sh -c 'ulimit -n'`.

## Never restart many services at once on this box

**Confirmed twice on 2026-09-27, with data, not a guess.** Restarting more than ~3-4 heavy Java services simultaneously does not "just take longer" — it causes a genuine, self-sustaining crash loop that does NOT resolve by waiting. What happens: every JVM tries to register with the single-node Nacos at once, Nacos can't keep up, registration fails, the app throws a fatal startup exception and the container dies, kubelet restarts it, and it hits the same overloaded Nacos again. Watched restart counts climb from 11 to 53 over 15 minutes of pure waiting with zero improvement in readiness — passive waiting made it worse, not better, because the same services kept recreating the overload.

**What actually works** (`staggered-restart.sh`): scale everything to 0 first (lets Nacos's retry queue drain), then bring services back in batches of 3, polling every 15s, and do not start the next batch until the current one is fully `1/1`. This worked cleanly on the first attempt. Also true for image pulls, database restarts, and the telemetry rollout below — anything that touches more than a few JVMs at once on this laptop.

## Adding tracing / telemetry (OpenTelemetry)

Train Ticket ships no tracing by default. Added via `otel-collector.yaml` (a Deployment + Service in the `train-ticket` namespace: OTLP receiver → `servicegraph` + `spanmetrics` connectors → Prometheus exporter on `:8889`) plus `telemetry-3.sh` / `telemetry-rest.sh` (batches of 3), which patch each app Deployment with:
- a read-only `hostPath` mount of `/opt/otel`, where `opentelemetry-javaagent.jar` (v2.31.1, Java 8+ compatible) was copied onto each kind node with `docker cp`. No download at pod start. (The first version used an initContainer that downloaded the jar, which was slow on this network.)
- `JAVA_TOOL_OPTIONS=-javaagent:/otel/opentelemetry-javaagent.jar`
- `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318` — **use the :4318 (HTTP) port, not :4317 (gRPC).** The Java agent defaults to `http/protobuf`; pointing it at the gRPC port produces a silent `Failed to export spans` loop with no other symptom.

The collector's metrics port is annotated `prometheus.io/scrape: "true"`, so the **existing** Prometheus (in kube-system) picks it up automatically — no second Prometheus needed. Verified with real traffic: a login + search produced a real row in `traces_service_graph_request_total`, queryable from the existing Prometheus, no manual wiring required beyond the annotation.

**The agent's bytecode instrumentation is real added CPU cost at startup**, and it compounds badly under the contention rule above — one pilot pod took 68s just from "agent loaded" to the first Spring Boot log line (versus ~5s normally). This is why rolling it out to all 19 services at once caused the crash loop: OTel overhead plus 17 simultaneous cold starts plus 17 simultaneous Nacos registrations, all on one box.

### Full rollout in batches of 3 (2026-09-28): what happened and why it's OK

Even in batches of 3, services restarted 1–4 times each and the app returned `502` for a while. **Cause, from the crash logs:** every crash was `exit 1` with `NacosException: Client not connected, current status:STARTING`. The Nacos client inside each service opens a connection to Nacos and gives it only a few seconds. With the agent slowing startup (**85 s to start, 119 s of JVM time**, against a ~60 s readiness delay), plus other JVMs starting and the databases briefly missing their 1 s health pings, the connection wasn't up in time. Spring aborted and the container exited. **It was not memory** (no OOMKilled) and **not probe kills** (there is no liveness probe; the readiness probe only marks a pod not-ready, it never kills it).

Unlike the 17-at-once case, this **settled on its own in ~20 min**: restarts stopped at 1–4 instead of climbing to 53. Batching kept the overload bounded. After settling:
- 20/20 services have the agent, all `1/1`
- first searches after settling: 60 s timeout, 60 s timeout, 45 s, 1.7 s, then under 1 s (the warm-up rule again)
- 2 bookings on a warm system: both `200 Success`, orders table went 8 → 10, exactly +2, no duplicates
- service graph: **40 edges (25 service→service, 15 service→database)**, up from 33 before the rebuild. New ones include `ts-security-service → ts-order-other-service` and `ts-notification-service → unknown`, the uninstrumented RabbitMQ side.
- memory: pods 12.2 GB working set, **WSL available 3.8 GB**. That is the budget left for Chaos Mesh and the load generator.

### Load generator, and the CPU cap it exposed (2026-09-29)

`~/arc/loadgen/loadgen.py` (standard-library Python, open-loop Poisson arrivals). Mix: search 55 / order list 15 / book 20 / pay 10. It logs every request to `~/arc/data/loadgen/run-*/requests.jsonl` and writes `status.json`, which the viewer shows. `analyze.py` summarises a run, and `step-test.sh "1 2 3" 180` finds a safe rate.

- **At 1 req/s almost everything timed out at first.** Every service was capped at **500m CPU**. One search alone took 2–2.7 s because travel was throttled 45% of the time. Raising the cap to 2 cores cut that to 0.7–1.1 s. `cpu-resize.sh 2 all` does it **in place, with no restart** (Kubernetes ≥ 1.33). `persist-cpu-limit.sh 2 2` then writes it into the Deployments, in batches of 2 with a free-memory guard, so a restarted pod keeps it. That matters: otherwise a "restart" action would also silently cut the service back to half a core.
- **Ruled out:** garbage collection, measured at ~0% of JVM CPU from per-thread `/proc` times (`gc-share.sh`, `top-threads.sh`).
- **Results with 2 cores:** 2 req/s gave 100% success on search, order view and booking. 3 req/s gave 97%, and every failure was the generator's own double-payment bug, since fixed. **Use 2 req/s for episodes.**
- **Warm-up again:** the first ~50 s after any restart or idle period time out while the JIT compiles (the busiest thread is `C2 CompilerThread`).
- **Overload symptom seen once:** at load average 18 with ~300 MB free, `ts-order-service` briefly vanished from Nacos ("No servers available"). It re-registered on its own. Keep an eye on free memory; `nacos-health.sh` checks every service.

### Collector pushed span metrics only every 60 s (fixed 2026-09-29)

Measured: `traces_span_metrics_*` changed only every **60 s** and `traces_service_graph_*` every **15 s** (connector default `metrics_flush_interval`). A 30 s B1 window could then contain no update at all, and the exporter's first test run had empty rps/latency for the first 95 s. Both connectors are now set to `metrics_flush_interval: 5s`. The latency buckets also stopped at 5 s, so p95 could never exceed 5000 ms and every slower request was capped there. Buckets now reach 30 s. `apply-collector.sh` applies the config and restarts only the collector, rolling back if it doesn't start.

### Episode exporter

`~/arc/harness/export_episode.py --id EP --b0 S E --b1 S E --m S E` writes `~/arc/data/raw/EP/`: `services.csv.gz` (per service per 5 s: rps, errors, p50/p95/p99, CPU, memory, throttling, restarts, ready), `edges.csv.gz`, `client.csv.gz` (load-generator requests), `events.json` and `meta.json`. Every row is labelled with its window (B0/B1/M/-). A 3-minute test run came to about 10 KB, so 3,000 episodes is roughly 30–50 MB.

### Episode runner, labels, and the warm-up drift (2026-09-29)

- `run_episode.py` runs a whole episode: health gate → steady-state gate → B0 120 s → fault → delay → B1 (last 30 s) → action → 5 s grace → M 120 s → export → health gate. It uses a load generator that is already running if it finds one (`status.json` updated within the last 10 s), otherwise it starts its own. For now it supports only `--fault none` and the actions `noop` / `restart-pod`.
- `compute_labels.py <episode dir>` writes `labels_v0.json` with, per service: Δerror, p95 ratio (M vs B1, 50 ms floor, clipped at 10), seconds worse, longest run worse, and harm (>30 s run).
- **Found a second collector scrape gap.** The collector is scraped by the `kubernetes-pods` job, not `kubernetes-service-endpoints`, and that job was still at 15 s. `prom-scrape-pods-5s.sh` fixes it; counters now change every 5 s (verified). The exporter's lookback windows are 20 s (traces) and 45 s (cAdvisor) so each window always holds at least 2 scrapes.
- **Removed unused scrape jobs** `kubernetes-apiservers` (~22,800 series) and `kubernetes-nodes-kubelet` (~6,100) to save Prometheus memory (`prom-drop-unused-jobs.sh`).
- **Warm-up drift:** after ~40 min idle the services were cold again (B0 p95 11 s vs M 0.4 s). Even after passing the steady-state gate, the first noise episode showed every service getting 25–80% *faster* from B1 to M, which would make every action look beneficial. Fix under test: keep a load generator running continuously (`loadgen.py --rate 2`, never stopped between episodes) and let it settle for several minutes before the first episode. Swap may contribute (swappiness 60); lowering it needs sudo, so it's the user's call.
- **After a full restart of all services**, do not jump straight to 2 req/s: it piles up on cold JVMs (90% timeouts). `warmup.sh` ramps 0.3 → 0.6 → 1.0 req/s (100% success).

### Database growth and the pilot's fault/action smoke tests (2026-09-30)

- **The database grows under load and slows everything down.** After 18 h at 2 req/s there were 14,372 orders and ~7,100 payment rows. Order-list p95 went from ~100 ms to 1,479 ms and booking p95 from ~250 to 1,768 ms, because the order list returns every order of the test account. `harness/reset-data.sh` deletes the load account's orders older than 10 min, plus orphaned payments, **on the MySQL leader** (`mysql-leader.sh`; replicas are read-only, so a delete on `tsdb-mysql-0` silently does nothing). `run_episode.py` runs it at the start of every episode. The load generator now pays only orders seen in the last 5 min.
- **Smoke tests** (`harness/smoke_tests.py`):
  1. **Chaos Mesh StressChaos is unusable on kind + cgroup v2.** The stress processes ran outside the target container: the target was never throttled, the host went to load 25, and every service timed out. **Replaced by `cpu-squeeze`**: an in-place CPU-limit cut to ¼ of recent use (min 25m), which throttled seat 100% with no effect on other services.
  2. **NetworkPolicy quarantine blocked nothing** (0 failed searches): callers keep their open keep-alive connections. **Replaced by `drain`** (Nacos `enabled=false`), which works (0 → 34 → 0 failed searches). A disabled instance is **hidden** from Nacos' list API, so re-enabling must use the address saved at drain time. The first version reported success without doing anything and left station disabled; `infra/nacos-set-enabled.sh` fixes it by hand.
  3. **A Chaos Mesh fault does not follow a restarted pod.** After restart-pod, the delay fault was not on the new seat pod, so a restart "cures" network faults. The harness records `fault_on_new_pod`.
  4. Blackhole on station: search failures during the fault, healthy again 125 s after removal. ✔
  5. Scale-up 1→2→1 keeps the original warm pod. ✔
  6. **In-place resize must use the default (strategic merge) patch.** `--type=merge` replaces the whole resources block and is rejected ("limits cannot be removed"). A CPU limit below the request is invalid, so lower the request too.
- **Sustained overload after a heavy fault.** After the host-wide stress, search p50 stayed at 6–7 s for several minutes after the fault was removed, then drained on its own. The steady-state gate (p95 < 3 s, no failures, 3 checks) keeps the next episode from starting too early.

### Website bookings always ordered food (Train Ticket UI bug, patched 2026-09-29)

The booking page (`assets/js/client_ticket_book.js`, not `js/flowPreserve.js`) sent `foodType=1` on **every** booking. Two reasons: `client_ticket_book.html` pre-fills `<p id="sub_foodType">Station Food Stores</p>`, so the "was food chosen?" text check is never empty, and it tests `indexOf("Train")` as a boolean, where -1 (not found) counts as true. With `ts-food-service` scaled to 0, every website booking saved the order and *then* failed with HTTP 500 at the food step. `fix-ui-food.sh` patches the running nginx pod so food is sent only when "Need Food" is ticked. **The patch is lost if the ui-dashboard pod restarts; re-run the script.** The load generator and `demo.sh` never used the page, so they were never affected.

### Prometheus scrape interval and retention (fixed 2026-09-28)

The bundled Prometheus config had **no `global:` block, so it scraped every 1 minute**. A 30 s B1 window then contains 0 or 1 samples, and the live graph lagged by a minute or more: a booking showed only `gateway → auth` at first. `prom-scrape-fast.sh` sets 15 s globally and **5 s for the annotated-services job** (the OTel collector's service graph + span metrics), then hot-reloads via `/-/reload` (about 30 s for the ConfigMap to reach the pod). The original config is saved in `archive/prometheus-config.before.json`.

Also note: Prometheus storage is an **`emptyDir` with 24 h retention**. A Prometheus pod restart loses all history. The harness must export each episode's B0/B1/M data to files when the episode ends, and never rely on Prometheus as the dataset store.

**Rule:** after any change that restarts JVMs, wait until restart counts stop rising and every pod is `1/1`, then send warm-up traffic. Only then measure. A `502` in the first minutes after a rollout is expected; it only means "still starting".

## What is running
- kind cluster `arc`: 1 control-plane + 2 workers, Kubernetes v1.34. WSL2 is capped at 17 GB in `C:\Users\<you>\.wslconfig`.
- App: the `xlab-uiuc/train-ticket` Helm chart (images `ghcr.io/sregym/ts-*`). UI at `http://localhost:32677`.
- Infra in namespace `train-ticket`: `nacos-0` (standalone), `nacosdb-mysql-0`, `tsdb-mysql-0`, `rabbitmq`, `flagd`.
- Metrics: Prometheus and Grafana live in **kube-system** (Prometheus NodePort 30003, Grafana 31000). They give per-pod CPU, memory and restart counts only.
- **Not present:** tracing, request-level metrics, a service graph. SkyWalking is commented out of the fork's deploy script.
- Running set (24 pods): the search, book and pay path. Scaled to 0 on purpose: admin-*, food*, consign*, delivery, rebook, cancel, travel2, order-other, preserve-other, route-plan, travel-plan, ticket-office, station-food, train-food, voucher, wait-order, avatar, news, execute, assurance.

## Rebuild order (what it should have been)
1. `wsl --shutdown`, then `free -g` inside Ubuntu must show about 16-17 GB. Stop anything else heavy first (Hadoop containers were eating RAM).
2. `01-cluster-up.sh` (uses `kind-cluster.yaml`).
3. `preload-images.sh` (see the section above). It downloads every image once through Docker Desktop and copies it into all nodes. Don't let the nodes download images themselves. Their path is ~10x slower and has flaky DNS. **Do not run the old `fix-dns.sh`.** Besides the DNS change it restarts containerd and force-deletes every pod in the namespace. It caused a large outage on 2026-09-27.
4. `02-deploy-trainticket.sh`. The chart only creates an in-cluster Job, and that Job does the real work (helm installs nacosdb, nacos, rabbitmq, tsdb).
5. **Correct the high-availability defaults straight away.** These were not scripted as one unit, so do them by hand in this order:
   - MySQL (`nacosdb`, `tsdb`): the chart says never to change `replicaCount` after creation. Install with `--set replicaCount=1` (a top-level key) from the start.
   - **Nacos: the key is `nacos.replicaCount`, not `replicaCount`.** The wrong key silently does nothing and the StatefulSet stays at 3.
   - Nacos env is hardcoded in the chart template. Set `MODE=standalone`, `SPRING_DATASOURCE_PLATFORM=mysql`, `NACOS_REPLICAS=1` and `NACOS_SERVERS` to nacos-0 only. Cluster mode with a single node never finishes starting (`[DISTRO-INIT] waiting server list init...`, and the API returns 503).
   - **Turn semi-sync off on both MySQL leaders** (`fix-semisync.sh`): `SET GLOBAL rpl_semi_sync_master_enabled=OFF` plus `xenoncli raft disablechecksemisync`. Otherwise every write blocks in state "Waiting for semi-sync ACK from slave", because there is no follower. Reads still work, which is why it looks like a silent hang.
   - **This does not survive a MySQL pod restart, and a Kubernetes `postStart` hook cannot fix it either — tried and proven not to work on 2026-09-27.** xenon re-enables semi-sync on its own after becoming leader, not just once at boot, so a one-time startup hook loses the race. Two real restart tests confirmed this (semi-sync came back ON both times, even with the hook in place). **Do not spend more time trying to patch this at the Kubernetes layer.** Instead: run `fix-semisync.sh` by hand whenever `health.sh` reports `semi-sync ... =1`, and build the same check into the harness's per-episode health gate (see `harness/MEASUREMENT-SPEC.md`) so it repairs itself before every episode rather than being assumed.
   - **`fix-semisync.sh` wipes the Nacos schema as a side effect** (it drops and reimports it to unstick a hung import). After running it, restart every app service so they re-register: `for s in <all 19 ts-* app deployments>; do kubectl rollout restart deploy/$s; done`, then wait up to ~8 min (19 JVMs cold-starting together on this box) and re-verify with a login + search, not just `kubectl get pods`.
6. After any database wipe, restart every DB-backed service (`reseed.sh`). They only create tables and seed data at startup.
7. Scale the non-core services to 0 (`scale-to-core.sh`).

## Facts to reuse
- Login: `POST /api/v1/users/login` with `{"username":"fdse_microservice","password":"111111"}`. The response has `data.token` (send it as a Bearer token).
- Trip search: `POST /api/v1/travelservice/trips/left` with `{"startPlace":"shanghai","endPlace":"suzhou","departureTime":"YYYY-MM-DD"}`. The field names are `startPlace` and `endPlace`, and station names are lowercase with no spaces. The `train-ticket-auto-query` repo uses different names and spelling, so adapt it.
- **JVM cold start is about 140-165 s per service** on this laptop (log line: `Started GatewayApplication in 163 seconds`). The first request after start takes about 9 s, later ones about 0.1 s. The harness needs a warm-up gate, and a restart action takes about 2.5 minutes to recover, not seconds.
- For a stuck pod, read `kubectl describe` events and `kubectl logs` first. A log that goes silent right after a Hibernate dialect line means a blocked database write.

## Tooling gotchas (Windows, Git Bash, WSL)
- Inline `wsl -- bash -lc '...$VAR...'` mangles quoting and variables. Write a script file and run it instead.
- Git Bash rewrites `/home/...` arguments into `C:/Program Files/Git/...`. Prefix the command with `MSYS_NO_PATHCONV=1`.
- Run `cd /c` before `wsl`, because the app's scratch folder does not exist inside WSL.
- `wsl -d Ubuntu` can hang while still reporting "Running". Run `wsl --shutdown` and retry.
- A StatefulSet rollout does not replace a pod that is not Ready. Delete the pod yourself.
- WSL does not hand memory back to Windows when containers stop. Judge headroom with `free -g` inside WSL.
