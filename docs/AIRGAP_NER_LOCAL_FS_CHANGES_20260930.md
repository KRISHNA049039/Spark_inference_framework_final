# Air-Gap Update: NER Cluster with Models on the Local File System (2026-09-30)

What changed relative to `pytorch-spark-inference-platform_20260927.zip`, and how to apply it on the air-gapped system so the `ner_translate` Spark cluster runs with its models read from a local folder (`E:\ner\models\weights`) instead of HDFS.

**No Python code changed.** `models/model_store.py` already supports `file://` model locations, and `submit_pipeline_job.py` already sends absolute input paths to executors. The update is one settings file, one offline package bundle, and a one-line Dockerfile edit made on the air-gapped machine.

---

## 1. Changes compared with the 20260927 zip

| # | File / folder | Change | Needed on air-gap |
|---|---|---|---|
| 1 | `deploy/dev.env` | **New.** Compose settings: models from a local folder, no HDFS (Docker Desktop, Windows paths) | Yes |
| 1b | `deploy/dev.wsl.env` | **New.** Same settings with Linux paths, for Docker CE inside WSL2 Ubuntu (section 8) | Only if using WSL |
| 2 | `wheels/ner_translate/` (63 files, 658 MB) | **New.** Offline Python packages for the NER image (gliner, transformers 4.45.2, onnxruntime, OCR/document libraries), Linux / Python 3.11 | Yes |
| 3 | `deploy/Dockerfile.ner_translate` | **Edit on the air-gapped machine:** delete line 1 (`# syntax=docker/dockerfile:1`) | Yes |
| — | `debs/ner_translate/` (50 files) | Unchanged, already in the zip. Offline OCR system packages (tesseract, poppler) | Already there |
| — | `deploy/docker-compose.airgap_sim.yml`, all Python code | Unchanged | — |

Why the Dockerfile edit: line 1 makes `docker build` download a build helper from Docker Hub (seen in the test build log as `resolve image config for docker.io/docker/dockerfile:1`). Offline that step fails. Everything else in the file works without it on current Docker versions.

### `deploy/dev.env` contents

Recreate it by hand if it is missing. Lines starting with `#` are comments.

```ini
# This dev PC:
# MODEL_FS_DIR=D:/pytorch-spark-inference-platform_20260921/models/weights
# Air-gapped system (Docker Desktop; under WSL2 Docker CE use /mnt/e/ner/models/weights):
MODEL_FS_DIR=E:/ner/models/weights
MODEL_STORE_URI=file:///mnt/models
```

On the air-gapped system the `E:` line must be the active one (as shown above). `MODEL_FS_DIR` is the folder that directly contains the three model folders. `MODEL_STORE_URI` stays as is.

### Which parts need the wheels

Only the NER pipeline, and only while its image is being built (`docker build`). A running cluster never reads `wheels\`.

| Image / workload | Needs `wheels/ner_translate`? |
|---|---|
| `multi-model-inference` (tensor models, benchmarks, RDD/UDF engines) | No: its packages are already inside the image |
| `spark-lean` (lightweight Spark nodes for service mode) | No |
| `ner-translate-worker` (NER cluster mode, this setup) | **Yes, at build time only** (section 4, step 5) |
| `ner-translate-server` (NER service mode, the model server) | Yes, and it also needs torch 2.6.0+cu126 wheels that are **not** in this bundle, because its Dockerfile downloads torch from the internet. Not needed for this setup |
| Running cluster / submitting jobs | No |

After the image is built the folder can be deleted, but keep it (or `wheels.zip`) for rebuilds, for example when a NER package version changes.

To avoid the wheels and the build entirely, carry the finished image instead: see section 7.

---

## 2. What to carry across

| Item | Size | Check on arrival |
|---|---|---|
| `wheels.zip` (contains `wheels/ner_translate/`) | 683 MB | SHA-256 `67918767822eba037a7e937338902f6096e1b526f4b741a7b314713251c6cd63` |
| `deploy/dev.env` | < 1 KB | Contents as in section 1 |
| `deploy/dev.wsl.env` (only for WSL / Docker CE) | < 1 KB | Contents as in section 8 |
| This document | — | — |
| Model weights: `gliner-multi/`, `nllb-200-distilled-600M/`, `hf_cache/` | ~4.6 GB | All three folders present; `hf_cache` is required for offline GLiNER |

Already on the air-gapped system (not carried): the 20260927 repo and the `multi-model-inference:latest` image.

---

## 3. Prerequisite: the base image must match

The offline packages were built and tested against this `multi-model-inference:latest`:

```
ID      sha256:986e9e56cddf2340f9dd4e5af23ba03a0415f7987760d74462c0e78e47f4ad01  (built 2026-09-16)
Python  3.11.15    torch 2.6.0+cu126    numpy 2.1.3
```

Check on the air-gapped system:

```powershell
docker images --no-trunc multi-model-inference
```

Same ID: continue. Different ID: stop. The OCR packages in `debs/ner_translate/` must then be rebuilt against that image on an internet-connected machine (`deploy/scripts/build_ner_translate_debs.sh`), otherwise the build fails with `dpkg: dependency problems`.

GPU: the Ada GPU (compute capability 8.9) is supported by the image's torch 2.6.0+cu126 build. No torch update is needed.

---

## 4. Apply on the air-gapped system

Run everything in PowerShell from the **repo root**: the folder that contains `deploy\`. The prompt should end in `\pytorch-spark-inference-platform>`, not `\deploy>`.

1. **Unpack the packages** into the repo root (the zip already contains the `wheels\ner_translate\` path):
   ```powershell
   Get-FileHash wheels.zip -Algorithm SHA256     # must match section 2
   Expand-Archive wheels.zip -DestinationPath .
   (Get-ChildItem wheels\ner_translate).Count   # 63
   ```
2. **Place the settings file** at `deploy\dev.env` with the `E:` line active (section 1).
3. **Place the models** at `E:\ner\models\weights\` so that it contains `gliner-multi`, `nllb-200-distilled-600M` and `hf_cache`.
4. **Delete line 1** of `deploy\Dockerfile.ner_translate` (`# syntax=docker/dockerfile:1`) in Notepad and save.
5. **Build the NER image** (offline, once, a few minutes):
   ```powershell
   docker build -t ner-translate-worker:latest -f deploy/Dockerfile.ner_translate .
   ```
   Expected: finishes with `naming to docker.io/library/ner-translate-worker:latest`; no `dependency problems`, no `docker.io/docker/dockerfile` line.
6. **Verify the image:**
   ```powershell
   docker run --rm --entrypoint python ner-translate-worker:latest -c "import gliner, transformers, pytesseract, torch, numpy; print('OK', torch.__version__, numpy.__version__, transformers.__version__)"
   docker run --rm --entrypoint tesseract ner-translate-worker:latest --list-langs
   docker run --rm --gpus all --entrypoint python ner-translate-worker:latest -c "import torch; print(torch.cuda.get_device_name(0), torch.cuda.get_device_capability(0)); x=torch.randn(512,512,device='cuda'); print('matmul ok', (x@x).sum().item()!=0)"
   ```
   Expected: `OK 2.6.0+cu126 2.1.3 4.45.2` (torch must stay 2.6.0); a language list with `eng`, `hin`, `mar` and the other Indian languages; the Ada GPU name, `(8, 9)`, `matmul ok True`.

Steps 1–6 are one-time. Later code changes need no rebuild: the compose file mounts the code from the repo.

---

## 5. Start, run and stop the cluster

One compose file, one settings file. Ignore the other compose files for this pipeline.

```powershell
# clear leftovers from earlier HDFS tests in this window (they override dev.env)
Remove-Item Env:\MODEL_STORE_URI, Env:\MODEL_FS_DIR -ErrorAction SilentlyContinue

# start
docker compose -f deploy/docker-compose.airgap_sim.yml --env-file deploy/dev.env --profile cluster up -d

# wait for the worker: expect "aliveworkers" : 1   (UI: http://localhost:8084)
docker exec sim-ner-cluster-master curl -s http://localhost:8080/json/ | Select-String aliveworkers

# run NER on the sample documents
docker exec -w /app sim-ner-cluster-master python submit_pipeline_job.py --pipeline ner_translate --input /app/data/ner_samples --execution-mode cluster --master spark://ner-cluster-master:7077 --partitions 1 --driver-memory 1g --executor-memory 4g

# confirm models came from E: (expect: model source: model store file:///mnt/models)
docker exec sim-ner-cluster-worker bash -c "grep -rh 'model source' /opt/spark/work | tail -1"

# stop
docker compose -f deploy/docker-compose.airgap_sim.yml --profile cluster down
```

- Results are written to the repo's `results\ner_translate_<timestamp>.json`.
- `--input` is a path **inside the container**. Put your own documents in the repo's `data\<folder>` and pass `/app/data/<folder>`; never an `E:\...` path.
- The memory flags were sized for a 6 GB Docker VM. With more memory on the air-gapped system, `--executor-memory` and `--partitions` can be raised.

---

## 6. If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `couldn't find env file ... deploy\deploy\dev.env` | Command run from inside `deploy\` | `cd ..` to the repo root |
| `failed to resolve ... docker/dockerfile:1` during build | Line 1 of the Dockerfile still present | Delete it (section 4, step 4) |
| `dpkg: dependency problems` during build | Base image differs from the tested one | See section 3 |
| `No matching distribution found` during build | `wheels\ner_translate\` missing or incomplete | Re-extract `wheels.zip`, check the count is 63 |
| `pull access denied for ner-translate-worker` | Image not built yet | Section 4, step 5 |
| Log shows `model store hdfs://...` | A session variable overrode `dev.env` | Run the `Remove-Item` line, then stop and start again |
| `Repo id must be in the form ...` | `MODEL_STORE_URI` empty: `--env-file` not passed | Use the start command exactly as in section 5 |
| GLiNER: `couldn't connect to huggingface.co` | `hf_cache` folder missing from `E:\ner\models\weights` | Copy it there |
| Container killed / exit 137 while running | Docker out of memory | Stop other containers; keep `--partitions 1` and the memory flags |
| Stuck at `Stage 0: (0 + 0) / 1` | Worker not registered | Re-check `aliveworkers`; `docker logs sim-ner-cluster-worker` |

---

## 7. Alternative without wheels: carry the finished image

The NER packages (gliner, transformers, OCR) are not in `multi-model-inference`, so they must cross the air gap one way or another. Instead of the wheels plus a build (sections 4.1–4.5), you can carry the finished `ner-translate-worker` image that already contains them.

| | A. Wheels + build on air-gap (sections 4–5) | B. Carry the finished image |
|---|---|---|
| What you carry | `wheels.zip` (683 MB) | `ner-translate-worker:latest` via `docker save` (28.1 GB uncompressed; it includes the whole base image) |
| Steps on the air-gapped system | Unzip, delete Dockerfile line 1, `docker build` | `docker load` only |
| Base image ID must match (section 3) | Yes | No: the image is self-contained |
| Start / run / stop commands | Section 5 | Section 5, unchanged |
| Choose when | Base image IDs match; smallest transfer | IDs differ, or no build wanted on the air-gapped system |

The image to carry is the one on the dev PC:

```
ner-translate-worker:latest   ID 46a0d21a8364   built 2026-09-17   28.1 GB
transformers 4.45.2 · gliner 0.2.13 · onnxruntime 1.30.0   (same versions as the wheels)
```

It passed the end-to-end cluster runs on 2026-09-27, so no rebuild is needed before saving it.

**On the dev PC** (internet side):

```powershell
docker save ner-translate-worker:latest -o D:\transfer\ner-translate-worker.tar
Get-FileHash D:\transfer\ner-translate-worker.tar -Algorithm SHA256     # record for the check on arrival
```

**On the air-gapped system:**

1. Check the hash of the copied `.tar` matches the one recorded above.
2. Load the image:
   ```powershell
   docker load -i ner-translate-worker.tar
   docker images ner-translate-worker        # ID 46a0d21a8364
   ```
3. Place `deploy\dev.env` and the models as in section 4, steps 2–3. Skip steps 1, 4 and 5 (no wheels, no Dockerfile edit, no build).
4. Verify the image (section 4, step 6), then start, run and stop the cluster exactly as in section 5.

---

## 8. Running the cluster on Docker CE inside WSL2 Ubuntu

Sections 4–5 use Docker Desktop from PowerShell. The same compose file also runs on Docker CE installed inside a WSL2 Ubuntu distro. The two are **separate Docker engines**: each has its own images and containers, and where a container runs depends on where the `docker` command is typed, not on the compose file.

| Where you type `docker compose ...` | Engine | Containers live in |
|---|---|---|
| PowerShell / CMD | Docker Desktop | its hidden `docker-desktop` distro |
| Ubuntu shell (`wsl -d Ubuntu-22.04`) with Docker CE installed | Docker CE | the Ubuntu-22.04 distro |

Check which engine a shell talks to: `docker info --format "{{.Name}}"` (`docker-desktop` means Docker Desktop).

**When to use it:** on one machine Docker CE brings no advantage over Docker Desktop. It is required for a cluster across **two or more machines** (section 8.5), because only an engine inside a WSL distro with mirrored networking can use the real network card.

### 8.1 Prerequisites (verified on the dev PC)

| Check | Command (Ubuntu shell) | Expected |
|---|---|---|
| Docker CE running, own engine | `docker info --format '{{.Name}} {{.DockerRootDir}}'` | host name, `/var/lib/docker` (not `docker-desktop`) |
| Compose plugin | `docker compose version` | v2 or later |
| GPU in containers | `docker run --rm --gpus all nvidia/cuda:12.1.1-base-ubuntu22.04 nvidia-smi -L` | the GPU name |
| systemd on | `cat /etc/wsl.conf` | `systemd=true` |
| Mirrored networking | `ip -4 addr` | the machine's real LAN IP |

`C:\Users\<user>\.wslconfig` must contain:

```ini
[wsl2]
memory=6GB              # or more: shared by every WSL distro, including Docker Desktop's
networkingMode=mirrored
vmIdleTimeout=-1
```

### 8.2 Settings file: `deploy/dev.wsl.env`

Windows drives appear under `/mnt/<letter>` inside WSL, so this file uses Linux paths. Recreate it by hand if missing:

```ini
# This dev PC (models on D:):
# MODEL_FS_DIR=/mnt/d/pytorch-spark-inference-platform_20260921/models/weights
# Faster: a copy on the distro's own disk (cp -r /mnt/d/.../weights ~/ner/models/):
# MODEL_FS_DIR=/home/<user>/ner/models/weights
# Air-gapped system (models on E:):
MODEL_FS_DIR=/mnt/e/ner/models/weights
MODEL_STORE_URI=file:///mnt/models
```

On the air-gapped system the `/mnt/e` line is the active one (as shown). Reading models from `/mnt/<drive>` is slow on first load; a copy inside the distro's own disk loads much faster.

### 8.3 One-time: get the NER image into the Docker CE engine

Images loaded or built in Docker Desktop are not visible to Docker CE. Either load the image tar straight into Docker CE (section 7 route):

```bash
docker load -i /mnt/e/transfer/ner-translate-worker.tar      # or /mnt/d/... on the dev PC
docker images ner-translate-worker                           # ID 46a0d21a8364
```

or load `multi-model-inference` into Docker CE and build there with the wheels (section 4, steps 1–6, typed in the Ubuntu shell from the repo root).

Then **quit Docker Desktop** (tray icon, Quit). All WSL distros share the `.wslconfig` memory, so two engines running at once starve each other.

### 8.4 Every session: start, run, stop

```powershell
# PowerShell: keep the distro awake for the whole session (prevents the silent WSL shutdowns). Leave it running.
Start-Process powershell -ArgumentList '-NoProfile','-Command','wsl -d Ubuntu-22.04 -- sleep infinity' -WindowStyle Hidden
```

```bash
# Ubuntu shell (wsl -d Ubuntu-22.04), from the repo root
cd /mnt/e/ner/repo                     # dev PC: /mnt/c/Users/kkc24/Downloads/pytorch-spark-inference-platform_20260927/pytorch-spark-inference-platform
unset MODEL_STORE_URI MODEL_FS_DIR

# start
docker compose -f deploy/docker-compose.airgap_sim.yml --env-file deploy/dev.wsl.env --profile cluster up -d

# wait for "aliveworkers" : 1   (Spark UI in the Windows browser: http://localhost:8084)
docker exec sim-ner-cluster-master curl -s http://localhost:8080/json/ | grep aliveworkers

# run NER
docker exec -w /app sim-ner-cluster-master python submit_pipeline_job.py --pipeline ner_translate \
  --input /app/data/ner_samples --execution-mode cluster --master spark://ner-cluster-master:7077 \
  --partitions 1 --driver-memory 1g --executor-memory 4g

# confirm the model source (expect: model store file:///mnt/models)
docker exec sim-ner-cluster-worker bash -c "grep -rh 'model source' /opt/spark/work | tail -1"

# stop
docker compose -f deploy/docker-compose.airgap_sim.yml --profile cluster down
```

Differences from Docker Desktop:

| | Docker Desktop (sections 4–5) | Docker CE in WSL (this section) |
|---|---|---|
| Where commands are typed | PowerShell | Ubuntu shell |
| Settings file | `deploy/dev.env` (`E:/...`) | `deploy/dev.wsl.env` (`/mnt/e/...`) |
| Line continuation | backtick | backslash |
| Clear leftover variables | `Remove-Item Env:\MODEL_STORE_URI, Env:\MODEL_FS_DIR` | `unset MODEL_STORE_URI MODEL_FS_DIR` |
| Images | its own | its own, loaded separately (8.3) |
| Keep-alive session | not needed | **required** (8.4) |

### 8.5 Two or more machines (LAN cluster)

The compose file runs everything on one machine. Across machines, start one container per node with `docker run` and host networking, inside the Ubuntu shell of each machine. Not yet run end to end with the NER image; the networking steps below are the ones that made the 2-machine cluster work on 2026-09-21 and 2026-09-25.

**On every machine, before starting:**

1. Docker CE in Ubuntu with the checks in 8.1 passing, and `ner-translate-worker:latest` loaded (8.3).
2. The same models and documents at the **same paths** on every node: every task can land on any worker, and it opens `/mnt/models/...` and `/app/data/...` on its own disk. Copy them to each machine (or share one folder over the LAN).
3. The same repo code on every node.
4. Windows firewall, Private profile, from an **administrator** PowerShell:
   ```powershell
   New-NetFirewallRule -DisplayName "Spark Master" -Direction Inbound -LocalPort 7077,8080,4040 -Protocol TCP -Action Allow -Profile Private
   New-NetFirewallRule -DisplayName "Spark Worker" -Direction Inbound -LocalPort 8081 -Protocol TCP -Action Allow -Profile Private
   New-NetFirewallRule -DisplayName "Spark Executors" -Direction Inbound -LocalPort 30000-40000 -Protocol TCP -Action Allow -Profile Private
   ```
5. After **every** `wsl --shutdown` or reboot, check that the network is still Private (Windows can silently switch it to Public, which re-blocks the ports):
   ```powershell
   Get-NetConnectionProfile | Select-Object InterfaceAlias, NetworkCategory
   Set-NetConnectionProfile -InterfaceAlias "Ethernet" -NetworkCategory Private
   ```
6. The keep-alive session from 8.4 running.

**Start the nodes** (replace the IPs; `MASTER` is the master machine's LAN IP, `ME` the machine you are on):

```bash
MASTER=192.168.4.104; ME=192.168.4.104          # on a worker: ME=<that worker's IP>
REPO=/mnt/e/ner/repo; MODELS=/mnt/e/ner/models/weights; DATA=/mnt/e/ner/repo/data
COMMON="--network host --init -w /app -e PYTHONUNBUFFERED=1 -e MODEL_STORE_URI=file:///mnt/models
  -e SPARK_LOCAL_IP=$ME -e SPARK_LOCAL_HOSTNAME=$ME
  -v $MODELS:/mnt/models:ro -v $DATA:/app/data -v $REPO/results:/app/results
  -v $REPO/inference:/app/inference -v $REPO/models:/app/models
  -v $REPO/submit_pipeline_job.py:/app/submit_pipeline_job.py"

# master machine only
docker run -d --name ner-master $COMMON ner-translate-worker:latest \
  bash -c '$SPARK_HOME/sbin/start-master.sh -h $SPARK_LOCAL_IP && tail -f $SPARK_HOME/logs/*master*'

# every worker machine (the master machine can run one too)
docker run -d --name ner-worker $COMMON --gpus all --shm-size=4g ner-translate-worker:latest \
  bash -c "\$SPARK_HOME/sbin/start-worker.sh spark://$MASTER:7077 -c 4 -m 6g && tail -f \$SPARK_HOME/logs/*worker*"
```

**Check from the other machine** (tests on the same machine do not catch firewall problems):

```powershell
curl.exe http://<MASTER>:8080/json/          # "aliveworkers" = number of workers started
```

**Submit on the master:**

```bash
docker exec -w /app ner-master python submit_pipeline_job.py --pipeline ner_translate \
  --input /app/data/ner_samples --execution-mode cluster --master spark://$MASTER:7077 --partitions 2
```

Results are collected by the driver and land in `results/` on the master only.

**Stop:** `docker rm -f ner-worker` on each worker, then `docker rm -f ner-master` on the master.

| Symptom | Cause | Fix |
|---|---|---|
| `BindException: Cannot assign requested address` | Engine cannot use the real IP (Docker Desktop, or mirrored networking off) | Use Docker CE in Ubuntu; check `ip -4 addr` shows the LAN IP |
| Containers restart every 20–30 s with empty logs | WSL shutting the distro down as idle | `vmIdleTimeout=-1` and the keep-alive session |
| Worker registers, then disappears ~20 s later | Same as above | Same as above |
| `ping` works but port 8080 times out from the other machine | Network switched to Public | Step 5 above |
| Worker registered but tasks never finish | Executor ports 30000–40000 blocked | Step 4 above |
| Every document: `No such file or directory` on a worker | Documents not at the same path on that node | Step 2 above |
