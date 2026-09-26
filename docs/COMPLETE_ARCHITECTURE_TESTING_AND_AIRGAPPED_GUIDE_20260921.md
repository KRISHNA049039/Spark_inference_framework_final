# Complete Architecture, Testing Guide, and Air-Gapped Deployment Reference

Consolidated end-to-end reference for this session's work: full architecture with results, how to run every execution path (RDD, pandas UDF, CUDA streams, concurrency), how to use the WSL2 Ubuntu distro, and how to run all of it air-gapped.

---

## Part 1: Complete Architecture

```
┌──────────────────────────────────── PHYSICAL LAYER ────────────────────────────────────┐
│                                                                                          │
│   MASTER MACHINE (192.168.4.104)              GPU WORKER MACHINE (192.168.4.101)        │
│   RTX 5060 (Blackwell, sm_120)                GPU (per your hardware)                   │
│                                                                                          │
│   ┌────────────────────────────┐              ┌────────────────────────────┐           │
│   │  Windows 11                │              │  Windows 11                │           │
│   │  ┌──────────────────────┐  │              │  ┌──────────────────────┐  │           │
│   │  │ WSL2 (mirrored net,  │  │   real LAN   │  │ WSL2 (mirrored net,  │  │           │
│   │  │ vmIdleTimeout=-1)    │◄─┼──────────────┼─►│ vmIdleTimeout=-1)    │  │           │
│   │  │ ┌──────────────────┐ │  │              │  │ ┌──────────────────┐ │  │           │
│   │  │ │ Ubuntu-22.04     │ │  │              │  │ │ Ubuntu-22.04     │ │  │           │
│   │  │ │ + Docker CE      │ │  │              │  │ │ + Docker CE      │ │  │           │
│   │  │ │ + nvidia-        │ │  │              │  │ │ + nvidia-        │ │  │           │
│   │  │ │   container-     │ │  │              │  │ │   container-     │ │  │           │
│   │  │ │   toolkit        │ │  │              │  │ │   toolkit        │ │  │           │
│   │  │ └──────────────────┘ │  │              │  │ └──────────────────┘ │  │           │
│   │  └──────────────────────┘  │              │  └──────────────────────┘  │           │
│   └────────────────────────────┘              └────────────────────────────┘           │
│         (NOT Docker Desktop — see docs/WINDOWS_LAN_NETWORKING_FIX_20260921.md           │
│          for why: Docker Desktop's own VM can't bind to the real LAN IP at all)         │
└──────────────────────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────── CONTAINER / APPLICATION LAYER ─────────────────────────────┐
│                                                                                          │
│  General multi-model cluster (Master)      ner_translate waiter/kitchen (Master, local) │
│  ┌──────────────────────┐                  ┌──────────┐  ┌──────────┐  ┌─────────────┐ │
│  │ spark-master          │  spark://        │ ner-      │  │ ner-      │  │ ner-        │ │
│  │ multi-model-inference │◄─192.168.4.104   │ translate-│──│ translate-│──│ translate-  │ │
│  │ :7077 / :8080         │  :7077───────┐   │ master    │  │ worker    │  │ server      │ │
│  └───────────┬───────────┘              │   │(spark-lean│  │(spark-lean│  │ (kitchen —  │ │
│              │ spark://192.168.4.104:7077  │ │ :7077/:8080)│  same img) │  │ torch/CUDA/ │ │
│              ▼                          │   └──────┬────┘  └───────────┘  │ GLiNER/NLLB)│ │
│  ┌──────────────────────┐               │          │   HTTP POST /predict └──────┬──────┘ │
│  │ spark-gpu-worker       │◄─────────────┘          └─────────────────────────────┘        │
│  │ (multi-model-inference,│                                                                 │
│  │  --gpus all)           │  ← 4 cores, 12GB, registered & ALIVE                            │
│  └────────────────────────┘                                                                │
└──────────────────────────────────────────────────────────────────────────────────────────┘

┌───────────────────────────── EXECUTION ENGINES (per job) ──────────────────────────────┐
│                                                                                          │
│  RDD engine (default)          Pandas UDF engine          CUDA Streams engine           │
│  cluster_engine.py             cluster_engine_udf.py       cuda_streams_engine.py        │
│  mapPartitions, counts only    predict_batch_udf.py        N models, N CUDA streams,     │
│  submit_job.py --engine rdd    returns real per-sample     one physical GPU, kernels     │
│                                 predictions                 interleaved concurrently      │
│                                 submit_job.py --engine udf  benchmark/run_benchmark.py    │
│                                                              --mode single_gpu            │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

### Why Docker CE-in-WSL2 instead of Docker Desktop

Docker Desktop's containers live inside a hidden, NAT'd WSL2 VM and cannot bind to the host's real LAN IP under any configuration (bridge, `--network host`, or the "Enable host networking" toggle — all tested, all failed). A real Docker Engine installed directly inside a WSL2 Ubuntu distro, with WSL2's mirrored networking mode on, behaves exactly like Docker on bare Linux — confirmed with a direct socket-bind test, not just documentation. Full diagnosis in `docs/WINDOWS_LAN_NETWORKING_FIX_20260921.md`.

---

## Part 2: Results — everything measured this session

### General benchmark suite (CPU, `multi-model-inference` on the real 2-machine cluster)

| Mode | Partitions | Samples | Throughput | Time | Result file |
|---|---|---|---|---|---|
| cpu_only | 2 | 5,190 | 490/s | 10.6s | `incremental_all_modes_20260921_122904.json` |
| cpu_only | 2 | 15,360 | 931/s | 16.5s | same file |
| cpu_only | 4 | 25,700 | 926/s | 27.8s | same file |
| gpu_only / hybrid (×6 runs) | — | — | **FAILED** | — | same file — `sm_120` CUDA kernel mismatch, root-caused and fixed later (Part 3) |

### `ner_translate` pipeline (waiter/kitchen, real GLiNER + NLLB on real sample docs)

| Run | Device | Elapsed | Entities extracted | Translation | Result file |
|---|---|---|---|---|---|
| 1 | CPU | 45.36s | 8/28/33/6/14/24 across 6 docs | hi→en, mr→en correct | `ner_translate_20260921_141603.json` |
| 2 | **GPU** (after `cu128` fix) | **5.86s** | identical | identical | `ner_translate_20260921_143218.json` |

**~7.7x speedup, identical output** — the strongest evidence this session produced that the GPU fix is real, not just "doesn't crash."

### RDD vs pandas-UDF engine (`example_mlp` plugin model, local mode)

| Engine | Samples | Throughput | Output | Result file |
|---|---|---|---|---|
| RDD (`--engine rdd`) | 2,000 | 1,455.3/s | counts only | `example_mlp_rdd_20260921_150858.json` (320B) |
| pandas UDF (`--engine udf`) | 2,000 | (same data) | **real per-sample 4-class logits** | `example_mlp_udf_20260921_150901.json` (269KB) |

The UDF engine's result file is ~840x larger for the same input — because it's the only one of the two that actually returns predictions instead of just a count. This is the documented, real capability difference between the two engines, not a bug in either.

### Spark cluster statistics (real 2-machine job, captured via `capture_spark_stats.py`)

`spark_stats_20260921_144548.json` — confirms both nodes participated in a real distributed job: executor `0` on `192.168.4.101:44755` (the actual GPU worker), driver on `192.168.4.104:44681`.

### GPU / CUDA architecture findings

| Build | `sm_120` (Blackwell/RTX 5060) support | Tested |
|---|---|---|
| `torch==2.6.0+cu126` (currently baked into `deploy/Dockerfile`) | **No** | Confirmed broken on real hardware |
| `torch==2.14.0+cu126` (latest available, same CUDA line) | **No** | Confirmed — proves it's the CUDA line, not the torch version |
| `torch==2.9.1+cu128` (matches `Dockerfile.worker`'s existing pin) | **Yes** | Confirmed working — real matmul executed |
| `torch==2.14.0+cu130` | **Yes** | Confirmed working |
| RTX 6000 Ada (`sm_89`), any of the above | Very likely yes, via CUDA's same-major-version binary compatibility rule (`sm_86` covers `sm_89`) | Not yet empirically confirmed — verify before relying on it |

---

## Part 3: How to run every test — locally and air-gapped

All commands below assume you're inside the relevant container. On the master: `docker exec -w /app spark-master bash`. Adjust `--master` for local vs. cluster execution.

### 3.1 RDD engine (default, mapPartitions-based)

```bash
python submit_job.py --model example_mlp --samples 2000 --mode cpu_only --engine rdd --master local[4]
# Or against the real cluster:
python submit_job.py --model example_mlp --samples 2000 --mode cpu_only --engine rdd --master spark://192.168.4.104:7077
```

Fastest to load, but only returns per-model sample **counts** — the model's actual output is discarded. Use this when you just need throughput numbers.

### 3.2 Pandas UDF / `predict_batch_udf` engine

These are **the same execution path**, not two separate things — `predict_batch_udf.py` is the actual Pandas UDF; `--engine udf` is how you invoke it.

```bash
python submit_job.py --model example_mlp --samples 2000 --mode cpu_only --engine udf --master local[4]
```

Loads the model once per partition (same optimization as the RDD path), but returns **real per-sample predictions** via Arrow-backed Pandas UDFs — the only one of the two engines actually useful if you need the model's output, not just a throughput count. Scope limit: only works for models with a flat vector output (classifiers/regressors like ResNet18/MobileNetV3/EfficientNet-B0) — not YOLO's variable-length detection lists, and not `models/pipelines/` (ner_translate etc.), which stay on the RDD-based `text_pipeline_engine.py` path.

### 3.3 CUDA streams (single-GPU, multi-model concurrency)

```bash
docker run --rm --gpus all multi-model-inference:latest python benchmark/run_benchmark.py --mode single_gpu
```

Not a Spark job at all — runs all 10 models on one process, one GPU, each model on its own CUDA stream so the GPU's kernel scheduler interleaves them. This is the same engine (`inference/cuda_streams_engine.py`) used internally by Modes 1/2/3 of the benchmark suite; this invocation just exercises it in isolation.

### 3.4 Concurrency test (multiple Spark jobs at once)

Per `docs/CONCURRENT_JOBS_AND_COMPLETING_THE_FRAMEWORK.md` §2 — Spark Standalone already handles this with zero code changes, just run multiple `submit_job.py` invocations backgrounded against the same master:

```bash
python submit_job.py --model example_mlp --mode hybrid --master spark://192.168.4.104:7077 &
python submit_job.py --model example_mlp --mode hybrid --master spark://192.168.4.104:7077 &
wait
```

Each becomes a separate Spark Application, scheduled by the cluster's normal resource allocation — genuinely concurrent, not simulated. For multiple processes sharing one **physical GPU** fairly (rather than the driver crudely time-slicing separate CUDA contexts), start the NVIDIA MPS daemon first: `bash deploy/scripts/start_mps.sh` (run once per GPU host, safe to re-run). `docker-compose.ner_translate_server.yml` already wires its kitchen container to this via `CUDA_MPS_PIPE_DIRECTORY`.

### 3.5 A real gotcha hit this session: the image may be stale

If any of the above fail with `ModuleNotFoundError` or a plugin silently not registering, your image may predate the file in question. This session's `multi-model-inference:latest` was missing `submit_job.py`, `models/plugin_loader.py`, `models/plugins/`, `inference/cluster_engine_udf.py`, `inference/predict_batch_udf.py`, **and** had a genuinely older `inference/cluster_engine.py` that predated the plugin-merge line (`class_map.update(get_plugin_class_map())`) — meaning plugin models like `example_mlp` silently vanished from the RDD/UDF engines' internal class map with no error, only a silent 0-samples-processed result on the RDD side and an explicit `ValueError` on the UDF side.

**Fix used this session** (fine for validation, not for anything meant to survive a container recreation): `docker cp` the current source files straight into the running container. **Proper fix**: rebuild the image from current source — none of this file-gap-patching is needed on a freshly built image.

### 3.6 Running all of this air-gapped

Nothing above needs live internet **except**:
- The CUDA fix itself (`pip install torch==2.9.1 ... --index-url ...`) — air-gapped, pre-download the wheels and `pip install --no-index --find-links=...` instead. Full pattern in `docs/SESSION_SUMMARY_AND_AIRGAPPED_UPDATE_GUIDE_20260921.md` Part 3.
- If patching a stale image's missing files (3.5 above) — these are plain source files from this repo, so just make sure your air-gapped code tarball includes current versions of `submit_job.py`, `inference/*.py`, `models/plugin_loader.py`, `models/plugins/` — or better, rebuild the image from current source in the first place and skip the patching entirely.

Everything else (`submit_job.py`, CUDA streams, concurrency via backgrounded jobs, MPS) is pure local execution against images/code already on the box — no network calls at all.

---

## Part 4: Using the WSL2 Ubuntu distro

### Basic interaction

```powershell
wsl -d Ubuntu-22.04                          # interactive shell
wsl -d Ubuntu-22.04 -- <command>             # one-off command
wsl -d Ubuntu-22.04 -- docker <args>         # run docker inside it
```

### The critical gotcha: hold a keep-alive session

Running many separate one-off `wsl -d Ubuntu-22.04 -- <command>` calls back-to-back (exactly what happens during normal debugging) re-triggers WSL2's per-instance idle-teardown path, which powers off the **entire distro VM** — taking down Docker and every container with it, disguised as random "crash-looping." This happened repeatedly this session, including twice more just now when the orchestrating session itself restarted and lost its keep-alive process.

**Before doing any real work against this distro:**
```powershell
Start-Process powershell -ArgumentList '-NoProfile','-Command','wsl -d Ubuntu-22.04 -- sleep 999999' -WindowStyle Hidden
```
Leave this running for the whole session. Verify it's actually helping by checking `docker ps` twice, 20+ seconds apart — if a container's uptime resets between checks, the keep-alive isn't in place or was lost (e.g., by a shell/session restart) and needs restarting.

### Also check after every `wsl --shutdown` (or unplanned VM restart)

```powershell
Get-NetConnectionProfile | Select-Object InterfaceAlias, NetworkCategory
# fix if "Public":
Set-NetConnectionProfile -InterfaceAlias "Ethernet" -NetworkCategory Private
```

Windows silently reclassifies the network adapter after WSL2 network churn, silently re-blocking firewall rules already opened for the Spark ports. This recurred multiple times this session.

### `.wslconfig` (at `%USERPROFILE%\.wslconfig`)

```ini
[wsl2]
networkingMode=mirrored
vmIdleTimeout=-1
```

Both lines are load-bearing — mirrored networking for real LAN access, `vmIdleTimeout=-1` to stop the whole-VM power-cycling (a *different* mechanism from the per-instance keep-alive above; you need both).

---

## Part 5: Location of the bare distro export (from this morning)

The pre-built Ubuntu + Docker CE + nvidia-container-toolkit bundle (no application images baked in — see `docs/AIRGAPPED_WSL2_DOCKER_CLONE_20260921.md` for why it's kept bare) is at:

```
C:\Users\pc\AppData\Local\Temp\claude\d--pytorch-spark-inference-platform\6d2a8e40-0868-4518-bc01-6722f7888577\scratchpad\ubuntu2204-docker-bare.tar.gz
```

**709,181,440 bytes (~709MB / ~676MiB).**

**Move this somewhere permanent before relying on it** — this path is inside a Claude Code session's temporary scratchpad directory, which is not guaranteed to survive indefinitely. Copy it to a location you control (e.g., alongside the repo, or directly to your USB transfer media) before using it for an actual air-gapped deployment.

To use it on the air-gapped machine: `wsl --import Ubuntu-22.04 C:\WSL\Ubuntu-22.04 <path-to-this-file> --version 2`, then apply the `.wslconfig` from Part 4, then load your application images separately (`docker load`) — full walkthrough in `docs/AIRGAPPED_WSL2_DOCKER_CLONE_20260921.md`.

The live WSL2 distro this file was exported from lives at:
```
C:\Users\pc\AppData\Local\wsl\{b63bd30e-9b0f-4b39-93bc-f22d7abf1be3}\ext4.vhdx
```
(64.35GB, dynamically expanding — includes the application images loaded into it, unlike the bare export above). Find this path on any machine via:
```powershell
Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' | ForEach-Object { Get-ItemProperty $_.PSPath } | Where-Object { $_.DistributionName -like '*Ubuntu*' } | Select-Object DistributionName, BasePath
```
