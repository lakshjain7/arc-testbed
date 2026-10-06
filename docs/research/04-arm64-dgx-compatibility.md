# 04: Can the ARC testbed move to the DGX Spark? (arm64 compatibility)

Researched 2026-09-29 using the web only (Docker Hub API, GHCR package pages, NVIDIA docs, project CI files) plus the local `infra/` scripts. Nothing was run.
Labels: **VERIFIED** means I saw it in the cited source. **BELIEVED** means an inference. **UNKNOWN** means it could not be established.

**Bottom line:** yes, but it is a port, not a copy. The DGX Spark is an **ARM64** machine. About 90% of the images already have arm64 builds, including all 22 `ghcr.io/sregym/*` images. Five infrastructure images are **amd64-only**, and the two MySQL ones are the hard part: `radondb/percona:5.7.34`, `radondb/xenon:1.1.5-helm`, `nacos/nacos-server:2.0.1`, `codewisdom/rabbitmq:3` and `codewisdom/mysqlclient:0.1`. They all ship inside the `train-ticket-deploy` image's Helm charts, so replacing them means overriding chart values or patching after install. Also, **a dataset made on the DGX cannot be mixed with laptop data**, because the CPUs differ and so do the latencies.

---

## 1. What the DGX Spark is

| Item | Value | Status / source |
|---|---|---|
| Chip | NVIDIA GB10 Grace Blackwell superchip | VERIFIED: [NVIDIA product page](https://www.nvidia.com/en-us/products/workstations/dgx-spark/) |
| CPU | **20 Arm cores: 10 Cortex-X925 (fast) + 10 Cortex-A725 (efficiency)**, Armv9.2, **aarch64/arm64** | VERIFIED: [DGX Spark hardware overview](https://docs.nvidia.com/dgx/dgx-spark/hardware.html), [porting guide overview](https://docs.nvidia.com/dgx/dgx-spark-porting-guide/overview.html) |
| GPU | Blackwell, **6,144 CUDA cores** (so the lab's "6144 CUDA cores" is correct) | VERIFIED: hardware overview |
| Memory | **128 GB LPDDR5x unified**, shared by the CPU and GPU, 273 GB/s | VERIFIED: hardware overview |
| Storage | 1 TB or 4 TB NVMe | VERIFIED: hardware overview |
| OS | **DGX OS 7, based on Ubuntu 24.04 LTS** (arm64) | VERIFIED: porting guide overview; [DGX OS 7 intro](https://docs.nvidia.com/dgx/dgx-os-7-user-guide/introduction.html) |
| Kernel | Depends on the DGX OS release: 7.2.3 → 6.11.0-1016-nvidia … 7.5.0 → 6.17.0-1014-nvidia, **7.6.0 → 7.0.0-1018-nvidia** | VERIFIED: [DGX OS 7 release notes](https://docs.nvidia.com/dgx/dgx-os-7-user-guide/release_notes.html) |
| Docker | **Docker Engine (CE) and the NVIDIA Container Toolkit ship with DGX OS** (7.6.0: Docker 29.6.2, toolkit 1.20.0) | VERIFIED: release notes |
| Docker image store | Docker 29 uses the **containerd image store by default on fresh installs** | VERIFIED: [Docker 29 release notes](https://docs.docker.com/engine/release-notes/29.md) (search-result summary) |
| cgroup | v2 (Ubuntu 24.04 default) | BELIEVED. Check with `stat -fc %T /sys/fs/cgroup` (should print `cgroup2fs`) |
| Page size | Two kernel flavours exist, `-nvidia` (4 KB pages) and `-nvidia-64k`. The release notes list `-nvidia`, so the default is believed to be 4 KB. Some software breaks on 64 KB pages. | BELIEVED: [forum: 64K → 4K for Qdrant](https://forums.developer.nvidia.com/t/how-to-switch-from-64k-page-size-back-to-4k-kernel-qdrant-compatibility-issue/364258). Check with `getconf PAGESIZE`, which should print 4096 |

**What this means for ARC**
- **The GPU does nothing for dataset generation.** RAM and CPU are what count. Because memory is unified, a GPU job run by someone else on the same box takes RAM away from our clusters. Ask for the box to ourselves while generating data.
- **Parallel clusters, rough estimate (BELIEVED):**
  - Memory: about 128 GB, minus 8–10 GB for the OS and Docker, leaves about 115 GB. At about 14 GB per cluster plus a 20% margin (about 17 GB), that is **about 6 clusters**.
  - CPU: 20 cores at 2–4 cores per cluster in steady state gives 5–10. But a restart action cold-starts a JVM (140–165 s of heavy CPU on the laptop), and half the cores are slower efficiency cores.
  - **Plan for 4 parallel clusters and measure before going to 5–6.** At 4 in parallel, the ~400 h serial run becomes about 100 h (~4 days).
- **Clusters on one box interfere with each other.** A CPU spike in cluster A adds latency in cluster B, which is noise in ΔSLO. Two mitigations:
  - Give each cluster its own cores: `docker update --cpuset-cpus=…` on its kind node containers (BELIEVED to work, not tested).
  - Record which cores each cluster used, since the X925 and A725 cores differ in speed. Keep all clusters on the same core type, or record it as a covariate.
- **Do not mix laptop episodes and DGX episodes in one dataset.** The CPUs and latencies differ. Generate the whole dataset on the DGX, and treat laptop runs as pilots only.

---

## 2. Image-by-image arm64 check

YES means a `linux/arm64` build exists for this exact tag. `unknown/unknown` entries on GHCR are buildx attestation manifests and are harmless.

| Image (exact tag) | arm64? | Evidence | Replacement if NO |
|---|---|---|---|
| `busybox:1.32` | **YES** (VERIFIED) | [Hub API](https://hub.docker.com/v2/repositories/library/busybox/tags/1.32): arm64 v8 | – |
| `busybox:1.36` | **YES** (VERIFIED) | [Hub API](https://hub.docker.com/v2/repositories/library/busybox/tags/1.36) | – |
| `curlimages/curl:8.10.1` | **YES** (VERIFIED) | [Hub API](https://hub.docker.com/v2/repositories/curlimages/curl/tags/8.10.1) | – |
| `codewisdom/mysqlclient:0.1` | **NO** (VERIFIED: amd64 only, 2022) | [Hub API](https://hub.docker.com/v2/repositories/codewisdom/mysqlclient/tags/0.1) | Nacos init container with a **built-in** script and schema; the chart passes no command, only `envFrom` the secret ([chart](https://raw.githubusercontent.com/xlab-uiuc/train-ticket/master/deployment/kubernetes-manifests/quickstart-k8s/charts/nacos/templates/statefulset.yaml)). Rebuild it: on the laptop, copy out its entrypoint and SQL (`docker create` + `docker cp`, or read `docker history`), then build `FROM mysql:8.0`, which has arm64 and a `mysql` client. Stopgap: it runs once and is never timed, so running it under QEMU is acceptable (see §3). |
| `codewisdom/rabbitmq:3` | **NO** (VERIFIED: amd64 only, 2022) | [Hub API](https://hub.docker.com/v2/repositories/codewisdom/rabbitmq/tags/3) | **`rabbitmq:3`** or `rabbitmq:3-management`. The official image has arm64 (VERIFIED, [Hub API](https://hub.docker.com/v2/repositories/library/rabbitmq/tags/3)). A drop-in replacement is BELIEVED (only AMQP 5672 is used), but check the chart for custom env or config. |
| `kindest/kindnetd:v20250512-df8de77b` | **YES** (VERIFIED) | [Hub API](https://hub.docker.com/v2/repositories/kindest/kindnetd/tags/v20250512-df8de77b) | – |
| `kindest/local-path-provisioner:v20250214-acbabc1a` | **YES** (VERIFIED) | [Hub API](https://hub.docker.com/v2/repositories/kindest/local-path-provisioner/tags/v20250214-acbabc1a) | – |
| `kindest/node:v1.34.0` | **YES** (VERIFIED) | [Hub API](https://hub.docker.com/v2/repositories/kindest/node/tags/v1.34.0): amd64 + arm64. kind ships a `kind-linux-arm64` binary ([quick start](https://kind.sigs.k8s.io/docs/user/quick-start/)). | – |
| `ghcr.io/chaos-mesh/chaos-daemon:v2.6.3` | **YES** (VERIFIED) | [GHCR versions](https://github.com/chaos-mesh/chaos-mesh/pkgs/container/chaos-daemon/versions?filters%5Bversion_type%5D=tagged&page=2): `v2.6.3`, `v2.6.3-arm64`, `v2.6.3-amd64`. [CI at v2.6.3](https://raw.githubusercontent.com/chaos-mesh/chaos-mesh/v2.6.3/.github/workflows/upload_image.yml) builds `[amd64, arm64]` and merges them into one manifest. | – |
| `ghcr.io/chaos-mesh/chaos-mesh:v2.6.3` | **YES** (VERIFIED) | [GHCR versions](https://github.com/chaos-mesh/chaos-mesh/pkgs/container/chaos-mesh/versions?filters%5Bversion_type%5D=tagged&page=2): `v2.6.3-arm64` present | – |
| `ghcr.io/chaos-mesh/chaos-dashboard:v2.6.3` (optional) | **YES** (BELIEVED) | Same CI job builds it for arm64. The GHCR page was not checked. | – |
| `ghcr.io/chaos-mesh/chaos-coredns:v0.2.6` (optional) | **YES** (VERIFIED) | [GHCR versions](https://github.com/chaos-mesh/chaos-mesh/pkgs/container/chaos-coredns/versions?filters%5Bversion_type%5D=tagged): `v0.2.6-arm64` present | – |
| `ghcr.io/open-feature/flagd:v0.11.1` | **YES** (VERIFIED from CI config, not from the registry) | [release workflow at tag `flagd/v0.11.1`](https://raw.githubusercontent.com/open-feature/flagd/flagd/v0.11.1/.github/workflows/release-please.yaml): `platforms: linux/amd64,linux/arm64` | – |
| `ghcr.io/sregym/ts-*-service:latest` (20 services) + `ts-ui-dashboard:latest` | **YES** (VERIFIED for 7 sampled: auth, station, inside-payment, order, gateway, verification-code, ui-dashboard. BELIEVED for the other 14, which were published in the same batch 7 months ago) | e.g. [ts-auth-service](https://github.com/orgs/SREGym/packages/container/package/ts-auth-service): only one tag, `latest`, with `linux/amd64` + `linux/arm64`. Base image `eclipse-temurin:8-jre` ([Dockerfile](https://raw.githubusercontent.com/xlab-uiuc/train-ticket/master/ts-auth-service/Dockerfile)) has arm64 ([Hub API](https://hub.docker.com/v2/repositories/library/eclipse-temurin/tags/8-jre)). This matches what the laptop saw (RUNBOOK §"Multi-platform images"). | – |
| `ghcr.io/sregym/train-ticket-deploy:latest` | **YES, probably** (VERIFIED on the GHCR version page, but a source disagrees) | [version page for `latest`](https://github.com/orgs/SREGym/packages/container/train-ticket-deploy/724861663?tag=latest) lists linux/amd64 + linux/arm64. [SREGym issue #1001](https://github.com/SREGym/SREGym/issues/1001) (2026-09-04) says this image is amd64-only. [#584](https://github.com/SREGym/SREGym/issues/584) showed that for the older `:jaeger` tag. There is also a `20260911-multiarch` tag with arm64. **Confirm with `docker manifest inspect` on the DGX.** | If `latest` fails, use `:20260911-multiarch` (arm64 VERIFIED). Note that its charts may still reference the amd64-only images below. |
| `grafana/grafana:10.0.1` | **YES** (VERIFIED) | [Hub API](https://hub.docker.com/v2/repositories/grafana/grafana/tags/10.0.1) | – |
| `nacos/nacos-server:2.0.1` | **NO** (VERIFIED: amd64 only) | [Hub API](https://hub.docker.com/v2/repositories/nacos/nacos-server/tags/2.0.1). `v2.0.1-slim` does not exist. `v2.0.3` and **`v2.0.4` (non-slim) are also amd64-only** ([v2.0.4](https://hub.docker.com/v2/repositories/nacos/nacos-server/tags/v2.0.4)). | **`nacos/nacos-server:v2.0.4-slim`** has amd64 + arm64 (VERIFIED, [Hub API](https://hub.docker.com/v2/repositories/nacos/nacos-server/tags/v2.0.4-slim)). It is the closest patch release, and the MySQL schema is BELIEVED to be the same as 2.0.1. Newer tags with arm64 (VERIFIED): v2.1.0, v2.1.x-slim, v2.2.x-slim, v2.5.x. The services use nacos-client 2.2.0 (RUNBOOK), so `v2.2.3-slim` is a reasonable second choice, but 2.2 changed the schema: the init SQL would need updating. |
| `otel/opentelemetry-collector-contrib:0.111.0` | **YES** (VERIFIED) | [Hub API](https://hub.docker.com/v2/repositories/otel/opentelemetry-collector-contrib/tags/0.111.0) | – |
| `prom/node-exporter:latest` | **YES** (VERIFIED) | [Hub API](https://hub.docker.com/v2/repositories/prom/node-exporter/tags/latest) | Pin a version instead of `latest`, for reproducibility. |
| `prom/prometheus:v2.46.0` | **YES** (VERIFIED) | [Hub API](https://hub.docker.com/v2/repositories/prom/prometheus/tags/v2.46.0) | – |
| `radondb/percona:5.7.34` | **NO** (VERIFIED: amd64 only, 2021) | [Hub API](https://hub.docker.com/v2/repositories/radondb/percona/tags/5.7.34). Official `mysql:5.7` is also amd64-only ([Hub API](https://hub.docker.com/v2/repositories/library/mysql/tags/5.7)), and so is every `percona/percona-server:5.7*` tag ([Hub API](https://hub.docker.com/v2/repositories/percona/percona-server/tags/?page_size=100&name=5.7)). | See §3, blocker 1. Candidates with arm64 (all VERIFIED): **`radondb/percona-server:5.7.34`** (same vendor and same MySQL version, amd64 + arm64, [Hub API](https://hub.docker.com/v2/repositories/radondb/percona-server/tags/?page_size=50)); `ddev/mysql:5.7.42` (dev-oriented); `mysql:8.0` ([Hub API](https://hub.docker.com/v2/repositories/library/mysql/tags/8.0)). |
| `radondb/xenon:1.1.5-helm` | **NO** (VERIFIED: amd64 only) | [Hub API](https://hub.docker.com/v2/repositories/radondb/xenon/tags/?page_size=50). Only xenon v2.3.0, v2.4.0 and v3.0.0 have arm64, and those were built for the RadonDB *operator*, not the old Helm chart. | Rebuild it: the Dockerfile is only `golang:1.13-buster` → `alpine:3.13`, both multi-arch ([Dockerfile](https://raw.githubusercontent.com/radondb/radondb-mysql-kubernetes/v1.1.0/dockerfile/xenon/Dockerfile)). A native `docker build` on the DGX should work (BELIEVED; the branch/tag for "1.1.5-helm" is UNKNOWN). Or drop xenon entirely (§3). |
| `registry.k8s.io` kube-apiserver / controller-manager / scheduler / proxy v1.34.0 | **YES** (VERIFIED) | [k8s download page](https://kubernetes.io/releases/download/): "All container images are available for multiple architectures" (amd64, arm, arm64, ppc64le, s390x) | – (already inside the kindest/node image) |
| `coredns v1.12.1`, `etcd 3.6.4-0`, `pause:3.10` | **YES** (BELIEVED) | The arm64 `kindest/node:v1.34.0` has to contain arm64 builds of these, and they come preloaded in the node image | – |
| `registry.k8s.io/kube-state-metrics/kube-state-metrics:v2.10.1` | **YES** (VERIFIED from build config) | [Makefile at v2.10.1](https://raw.githubusercontent.com/kubernetes/kube-state-metrics/v2.10.1/Makefile): `ALL_ARCH = amd64 arm arm64 ppc64le s390x`, pushed as one manifest | – |
| OpenTelemetry Java agent v2.31.1 (jar) | **N/A: works on any architecture** (BELIEVED) | A jar is Java bytecode and does not depend on the CPU | – |
| Java 8 JRE base (`eclipse-temurin:8-jre`) | **YES** (VERIFIED) | [Hub API](https://hub.docker.com/v2/repositories/library/eclipse-temurin/tags/8-jre) | – |
| (not running) `prom/mysqld-exporter:v0.12.1` | not checked | Metrics are disabled in the MySQL chart ([values](https://raw.githubusercontent.com/xlab-uiuc/train-ticket/master/deployment/kubernetes-manifests/quickstart-k8s/charts/mysql/values.yaml)) | – |

**Chaos Mesh on arm64:**
- arm64 builds have existed since v2.1, and TimeChaos gained AArch64 support in v2.3.0 (VERIFIED via [search summary of CHANGELOG / release v2.3.0](https://github.com/chaos-mesh/chaos-mesh/releases/tag/v2.3.0)).
- The chaos-daemon settings for kind (`runtime=containerd`, `socketPath=/run/containerd/containerd.sock`) are the same on arm64, because kind nodes are identical (BELIEVED).
- NetworkChaos needs the host kernel's `sch_netem` module. Whether the DGX `-nvidia` kernel ships it is **UNKNOWN**. Check with `modinfo sch_netem` on the DGX before relying on network-delay faults. On Ubuntu cloud-style kernels it is sometimes only in `linux-modules-extra-*`.

---

## 3. Blockers, most severe first

1. **MySQL (`radondb/percona:5.7.34` + `radondb/xenon:1.1.5-helm`) has no arm64 build. It sits in the request path, so emulation is not acceptable.** Options, best first:
   - **(a) Swap the MySQL image, rebuild xenon.** Set the chart's MySQL image to `radondb/percona-server:5.7.34` (arm64, same 5.7.34) and build `xenon:1.1.5-helm` for arm64 from the RadonDB Dockerfile. This keeps the current 3-copy + xenon setup and all the RUNBOOK knowledge (semi-sync fix and so on). Risk (UNKNOWN): `percona-server` was built for the RadonDB operator, so its entrypoint or config paths may differ from `radondb/percona`. It needs a trial.
   - **(b) Replace xenon with a plain single-instance MySQL StatefulSet** per database, with Services named exactly `tsdb-mysql-leader` and `nacosdb-mysql-leader`. The services and Nacos find the database by those names ([deploy utils](https://raw.githubusercontent.com/FudanSELab/train-ticket/master/hack/deploy/utils.sh)). Image: `radondb/percona-server:5.7.34` or `ddev/mysql:5.7` to keep 5.7 behaviour, or `mysql:8.0`. This removes the semi-sync problems entirely. The cost is losing the 3-copy decision from the RUNBOOK, which matters only if MySQL pods become fault targets.
   - **If you choose MySQL 8.0:** the services use Spring Boot 2.3.12, which manages Connector/J **8.0.25** ([Boot 2.3.12 dependency versions](https://docs.spring.io/spring-boot/docs/2.3.12.RELEASE/reference/html/appendix-dependency-versions.html)). That driver supports MySQL 8's `caching_sha2_password` (BELIEVED). To stay safe, start `mysql:8.0` with `--default-authentication-plugin=mysql_native_password`, since the scripts already create users `IDENTIFIED WITH mysql_native_password`. Pin **8.0**, not 8.4 or 9.x, where that plugin is off by default or removed. Other risks are UNKNOWN: new MySQL 8 reserved words used in Hibernate-generated table or column names, and Nacos 2.0.x's bundled driver. Test login, search and booking.
2. **Nacos 2.0.1 is amd64-only.** Use `nacos/nacos-server:v2.0.4-slim` (VERIFIED arm64). The environment variables are the same as the non-slim image (BELIEVED). Re-apply the standalone mode and heap settings from the RUNBOOK.
3. **The two `codewisdom` images are amd64-only.** RabbitMQ: use `rabbitmq:3`. mysqlclient: rebuild it (or run it under QEMU, since it is a one-shot init container).
4. **All of the above are set inside `train-ticket-deploy`'s built-in charts.** The top-level chart only launches a Job ([values.yaml](https://raw.githubusercontent.com/xlab-uiuc/train-ticket/master/values.yaml)), and that Job runs `helm install` for nacosdb, nacos, rabbitmq and tsdb. The overrides therefore have to go in either by building our own `train-ticket-deploy` image with edited `values.yaml` files (cleanest and reproducible), or by patching the StatefulSets and Deployments after the Job runs (fragile). Also check whether `:20260911-multiarch` already swapped these images (UNKNOWN; I could not read the image contents).
5. **`train-ticket-deploy:latest` arm64 status is disputed** (see the table). Settle it with `docker manifest inspect ghcr.io/sregym/train-ticket-deploy:latest` on the DGX.
6. **`sch_netem` on the DGX kernel is UNKNOWN.** It matters for NetworkChaos delay and loss faults.
7. **Measurement validity.**
   - Heterogeneous cores and several clusters sharing one box add latency noise; see the mitigations in §1.
   - QEMU is not a way around blockers 1–2: it runs roughly 5–10× slower on compute-heavy work (Docker's own docs say "much slower than native", [Docker multi-platform docs](https://docs.docker.com/build/building/multi-platform/); one benchmark measured about 85% slower, [QEMUUserModeBenchmark](https://github.com/ostrich/QEMUUserModeBenchmark)). Under QEMU, JVM JIT and MySQL would dominate every latency number and make ΔSLO meaningless.
   - QEMU is acceptable only for untimed one-shot pods such as the mysqlclient init container. It needs `docker run --privileged --rm tonistiigi/binfmt --install amd64` on the host (VERIFIED command from the Docker docs). binfmt_misc is shared kernel-wide, so kind nodes should pick it up (BELIEVED). Without it, you get `exec format error` (VERIFIED in issue #1001).

---

## 4. Migration checklist (script changes)

**On the DGX, before anything else**
- [ ] `uname -m` should print `aarch64`.
- [ ] `getconf PAGESIZE` should print 4096.
- [ ] `stat -fc %T /sys/fs/cgroup` should print `cgroup2fs`.
- [ ] `modinfo sch_netem` should succeed.
- [ ] `docker info`: check the Docker version and storage (containerd store, under `/var/lib/containerd`).
- [ ] Add your user to the `docker` group (`usermod -aG docker $USER`).
- [ ] Raise the inotify limits for multiple kind clusters: `fs.inotify.max_user_watches=524288`, `fs.inotify.max_user_instances=512` ([kind known issues](https://kind.sigs.k8s.io/docs/user/known-issues/)).
- [ ] Install the **arm64** builds of `kind`, `kubectl` and `helm` (e.g. `kind-linux-arm64`).
- [ ] For every image in `images-needed.txt`, run `docker manifest inspect <img> | grep arm64`. This confirms the table above in about 1 minute.

**`preload-images.sh`**
- [ ] Line 19: `docker pull --platform linux/amd64` → **`linux/arm64`** (or `$(docker version -f '{{.Server.Arch}}')`).
- [ ] Line 24: `docker save --platform linux/amd64` → **`linux/arm64`**. The multi-platform workaround is still needed with the containerd image store.
- [ ] `kind load image-archive --name arc` and the node names `arc-control-plane`, `arc-worker`, `arc-worker2` are hard-coded. Make the cluster name a parameter (`CLUSTER=${1:-arc}`) so each parallel cluster can be preloaded.
- [ ] `images-needed.txt`: replace the 5 amd64-only images with the replacements from §2.

**`kind-cluster.yaml` / `01-cluster-up.sh`**
- [ ] `name: arc` → one name per cluster (arc1…arcN), and `CTX=kind-$CLUSTER` everywhere (including `02-deploy-trainticket.sh`).
- [ ] `extraPortMappings` 32677/30005 must be **different for each cluster**, or removed (the harness uses port-forward anyway). Otherwise the second cluster fails to start.
- [ ] Remove the WSL memory check (`TOTAL_MB -lt 15000`); it assumes WSL. Replace it with a free-memory check per cluster.
- [ ] Pin `kindest/node:v1.34.0` by the **multi-arch index digest**, not a per-arch digest.

**Train Ticket deploy**
- [ ] Build `ghcr.io/<team>/train-ticket-deploy:arm64` (multi-arch with `docker buildx build --platform linux/amd64,linux/arm64`) with edited chart values: MySQL image (blocker 1), xenon (rebuilt) or no xenon, `nacos/nacos-server:v2.0.4-slim`, `rabbitmq:3`, and the rebuilt mysqlclient. Point `values.yaml` `job.image` at it and set `imagePullPolicy: IfNotPresent`.
- [ ] Re-run the RUNBOOK steps: Nacos standalone, heap caps, semi-sync (only if xenon is kept), `scale-to-core.sh`, CPU limit of 2, reseed.
- [ ] `telemetry-3.sh`: copying the jar with `docker cp` works as-is (the jar does not depend on the CPU).
- [ ] Chaos Mesh: `helm install … --version 2.6.3 --set chaosDaemon.runtime=containerd --set chaosDaemon.socketPath=/run/containerd/containerd.sock`, same as on x86.

**Validity**
- [ ] Re-run the warm-up and step tests (`step-test.sh`) on the DGX. The safe req/s and the warm-up time will differ from the laptop.
- [ ] Run 1 cluster, then 2, then 4, and compare noise-episode ΔSLO across counts to see how much the clusters interfere.
- [ ] Record the host (`dgx`), the cluster count and the CPU set in each episode's `meta.json`.
