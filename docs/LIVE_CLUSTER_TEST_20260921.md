# Live 2-Node Cluster Test — 2026-09-21

Working notes for the in-progress test of this framework across a real Windows LAN cluster (not a doc walkthrough — a log of what's actually been done this session).

---

## Goal

Run the full benchmark suite (`cluster_benchmark.py --incremental` — 3 device modes × 3 load levels = 9 runs) across a real 2-machine Spark cluster on the local LAN, following `docs/WINDOWS_CLUSTER_SETUP.md`.

## Topology

| Role | Machine | IP | GPU |
|------|---------|----|----|
| Master (this machine) | — | `192.168.4.104` (Ethernet) | NVIDIA RTX 5060, 8GB |
| GPU Worker | second machine | `192.168.4.101` | NVIDIA GPU (confirmed present) |

Image name: `multi-model-inference:latest` (built from `deploy/Dockerfile`, the `final` stage — Ubuntu 22.04 + Java 17 + Spark 3.5.1 + PyTorch 2.6.0/cu126 + project code + pretrained weights).

---

## What's been done so far

1. **Explored the repo** — this is a PyTorch + Spark distributed inference platform (`inference/`, `models/`, `benchmark/`, `deploy/`) with docs for both AWS CDK deployment and a manual Windows LAN cluster (`docs/CLUSTER_SETUP_GUIDE.md`, `docs/WINDOWS_CLUSTER_SETUP.md`, `docs/BENCHMARK_TESTS.md`).
   - Note: this working copy is missing dotfiles (no `.dockerignore`/`.git`, just `dockerignore`/`docker`) — looks like a transfer stripped leading dots. Didn't block anything since the build context is tiny (~1.5MB source).

2. **Started Docker Desktop** on the master (it wasn't running) and confirmed the daemon came up.

3. **Kicked off `docker build`** on the master directly from the Dockerfile. It progressed through the Ubuntu base + apt packages (Python 3.11, Java 17, ~68s) but then stalled silently for 15+ minutes on `wget`-ing the Spark 3.5.1 tarball from `archive.apache.org`, which is known to throttle archived-release downloads.

4. **Worker built independently** — rather than wait, the project source (~470KB zip) was handed to the worker machine via a Windows SMB share (`New-SmbShare "SparkProject"` on the master, pointing at the session scratchpad), and the worker ran the identical `docker build` command itself. It succeeded and already has `multi-model-inference:latest` loaded.

5. **Firewall rules opened on the master** (Private profile, via elevated PowerShell, run by the user):
   - `7077, 8080, 4040` (Spark Master RPC/UI/App UI)
   - `8081` (Spark Worker UI)
   - `30000-40000` (executor/shuffle range)
   - `8123` (ad-hoc file transfer)

6. **Cancelled the master's stalled build** once the worker's success confirmed the image works — no point re-downloading the same slow tarball twice. Decided to copy the worker's already-built image to the master over LAN instead of rebuilding.

7. **SMB transfer attempt failed** — tried pushing the worker's `docker save`d tar (`multi-model-inference.tar`) into the master's SMB share. Hit `net use` **System Error 86** (network password incorrect) — likely the master's local Windows account either has no password (blocked by Windows' default "no blank-password network logons" policy) or the exact username guess (`pc`) needs double-checking. Didn't chase this further since a simpler path was available.

8. **Switched to plain HTTP transfer** — no Windows auth needed:
   - Worker runs an ad-hoc `System.Net.HttpListener` PowerShell one-liner (admin required for `.Start()`), serving `C:\spark-inference\multi-model-inference.tar` on `http://192.168.4.101:8123/multi-model-inference.tar`.
   - Master pulls it via `Invoke-WebRequest` into the session scratchpad.
   - **In progress at time of writing** — several GB, streaming steadily over LAN (was at ~4.3GB and climbing on the last check).

## Still to do

1. Finish the HTTP download → `docker load` the tar on the master.
2. Start `spark-master` container on the master:
   ```powershell
   docker run -d --name spark-master -p 7077:7077 -p 8080:8080 -p 4040:4040 `
     multi-model-inference:latest bash -c "start-master.sh -h 192.168.4.104 && tail -f /opt/spark/logs/*master*"
   ```
3. Start `spark-gpu-worker` container on the worker (192.168.4.101), pointing at the master:
   ```powershell
   docker run -d --name spark-gpu-worker -p 8081:8081 --gpus all --shm-size=4g `
     -e SPARK_WORKER_HOST=192.168.4.101 multi-model-inference:latest `
     bash -c "SPARK_LOCAL_IP=192.168.4.101 start-worker.sh spark://192.168.4.104:7077 -c 4 -m 12g && tail -f /opt/spark/logs/*worker*"
   ```
4. Verify both nodes registered via `http://192.168.4.104:8080` or the JSON REST endpoint (`aliveworkers` count).
5. Run the full incremental suite from inside `spark-master`:
   ```powershell
   docker exec -it spark-master bash -c "SPARK_MASTER_URL=spark://192.168.4.104:7077 python benchmark/cluster_benchmark.py --incremental"
   ```
   → 9 runs: `{cpu_only, gpu_only, hybrid} × {small, medium, large}` loads.
6. Pull results (`incremental_all_modes_<timestamp>.json`) and summarize throughput/latency findings.
7. **Cleanup afterward**: consider reverting the `SparkProject` SMB share (`Remove-SmbShare`) and the firewall rules opened purely for this test, if not needed long-term.

## Gotchas hit (for next time)

- `archive.apache.org` is slow/throttled for the Spark tarball — building on a second machine independently (or caching the tarball) avoids waiting twice.
- `New-NetFirewallRule` / `New-SmbShare` / `HttpListener.Start()` all require an elevated (Admin) PowerShell — this session's tools run unprivileged, so every one of these had to be handed to the user to run manually.
- SMB share-level permissions (`Grant-SmbShareAccess`) don't override NTFS folder ACLs or Windows' blank-password network-logon restriction — plain HTTP via `HttpListener` sidesteps Windows auth entirely for LAN transfers like this.
