# Handoff: run the lab 2-machine NER cluster test (cluster mode only)

Context for a Claude Code session running **on the lab master PC** (`RAPL-DSK-161`, LAN IP `192.168.4.104`). The previous session ran in a cloud container: it wrote and pushed the lab files, but could not run anything (no access to this PC, the LAN, the images or the model weights). **Nothing has been run yet. There are no results.**

## Goal
Test the NER pipeline in **cluster mode** (models run inside the Spark executors) across two lab machines, using **only the three images the air-gapped Ada system has**, so that a pass here gives confidence that Ada will pass too:

| Image | Role in cluster mode |
|---|---|
| `multi-model-inference:latest` | Spark master, worker and executors (has Spark + torch 2.6.0+cu126, no NER packages) |
| `ner-translate-server:latest` | **Not run.** Mounted read-only at `/deps` as the source of the NER packages: `deploy/scripts/install_ner_deps.sh` rebuilds wheels from its installed packages at container start (offline, torch skipped) and installs them into the `multi-model-inference` container |
| `spark-lean:latest` | Server mode only. **Not used now:** the user wants cluster mode only for the moment |

The user wants to be told about **every file change**. Do not modify the air-gapped files (`deploy/docker-compose.airgap_sim.yml`, `deploy/airgap_sim_tests.ps1`, the Ada images).

## Machines
| Role | Host | LAN IP | GPU |
|---|---|---|---|
| Master + worker | this PC (`RAPL-DSK-161`) | `192.168.4.104` | RTX 5060 (sm_120, Blackwell) |
| Worker | remote PC | `192.168.4.101` | RTX 5060 (same) |

Ada target GPU: sm_89. **The cu126 images have no sm_120 kernels**: `torch.cuda.is_available()` returns True on the RTX 5060, then the first CUDA op fails with "no kernel image is available". So the lab runs on **CPU** (the compose file sets `CUDA_VISIBLE_DEVICES=""` and gives no GPU). The GPU path is not exercised in the lab. Optional lab-only GPU check: `deploy/Dockerfile.lab_cu128` + `deploy/docker-compose.lab_lan.gpu.yml` (cu128 images, not Ada's).

## Repo and branch
- GitHub: `KRISHNA049039/Spark_inference_framework_final` (public), branch **`lab-lan-sm120`**.
- `D:\spark-final` (`/mnt/d/spark-final`) does **not** contain this repo's `deploy/` files. Last state: the user ran `bash deploy/lab_lan_tests.sh cluster` there and got "No such file or directory". **Find out what that folder is** (`ls`, `git remote -v`); it may hold the model weights or image tars. Recommended: a fresh clone inside Ubuntu:
  ```bash
  cd ~ && git clone -b lab-lan-sm120 https://github.com/KRISHNA049039/Spark_inference_framework_final.git
  ```
- If any repo copy was checked out from Windows git, strip CRLF before running (bash and the in-container install script break otherwise):
  `sed -i 's/\r$//' deploy/lab_lan_tests.sh deploy/scripts/install_ner_deps.sh deploy/lab_lan.env`

## Files on the branch (all new, lab only)
| File | Purpose |
|---|---|
| `deploy/docker-compose.lab_lan.yml` | Project `lab-lan`, containers `lab-*`, host networking. Profiles: `cluster-master`, `cluster-worker` (and `server-master`, `server-worker`) |
| `deploy/lab_lan.env` | `LAB_MASTER_IP=192.168.4.104`, `LAB_NODE_IP` (override to `.101` on the remote), `MODEL_FS_DIR`, image names |
| `deploy/lab_lan_tests.sh` | Runner: L01 prerequisites, then per mode: start, wait for workers, submit, check, collect, stop. `bash deploy/lab_lan_tests.sh cluster` |
| `deploy/Dockerfile.lab_cu128`, `deploy/docker-compose.lab_lan.gpu.yml` | Optional lab-only GPU run (`LAB_GPU=1`) |

Key settings: `SPARK_LOCAL_IP`/`SPARK_LOCAL_HOSTNAME` = this node's LAN IP; `deploy/spark-defaults.lan.conf` mounted (driver port 35000, block managers 35100+); `SPARK_WORKER_PORT=35200`; `MODEL_STORE_URI=file:///mnt/models` (weights from `MODEL_FS_DIR`, read-only); the pipeline forces `HF_HUB_OFFLINE=1`.

## Environment requirements (each machine)
Docker Desktop **cannot** do this: its containers cannot bind the real LAN IP (see `docs/WINDOWS_LAN_NETWORKING_FIX_20260921.md`). Required:
1. WSL2 with `networkingMode=mirrored` and `vmIdleTimeout=-1` in `C:\Users\<user>\.wslconfig`.
2. Ubuntu-22.04 distro with **Docker CE 28+** (image volumes) and nvidia-container-toolkit. Run everything in `wsl -d Ubuntu-22.04`, not cmd (in cmd, `bash` opened the `docker-desktop` distro and failed with `execvpe(/bin/bash) failed`).
3. `ip -4 addr` in Ubuntu shows the LAN IP; `docker info` shows Ubuntu, not Docker Desktop.
4. Firewall (admin PowerShell, once): TCP 7077, 8080, 4040, 8081, 30000-40000 inbound on the Private profile; network category Private (re-check after every `wsl --shutdown`).
5. Keep-alive while working: `wsl -d Ubuntu-22.04 -- sleep 999999` in a separate window.
6. The three images loaded from the **same `docker save` tars that go to Ada** (L01 prints image ids to compare with Ada).
7. Model weights folder containing `gliner-multi/`, `nllb-200-distilled-600M/`, `hf_cache/`; set `MODEL_FS_DIR` in `deploy/lab_lan.env` to its Linux path (`/mnt/d/...`). Same weights and same repo `data/` on the remote.

## Steps
1. Single machine first:
   ```bash
   LAB_EXPECT_WORKERS=1 bash deploy/lab_lan_tests.sh cluster
   ```
2. Then both machines: `bash deploy/lab_lan_tests.sh cluster` on the master. It prints the commands for the remote (`.101`), which the user runs there:
   ```bash
   docker compose -f deploy/docker-compose.lab_lan.yml --env-file deploy/lab_lan.env --profile server-worker --profile cluster-worker down
   LAB_NODE_IP=192.168.4.101 docker compose -f deploy/docker-compose.lab_lan.yml --env-file deploy/lab_lan.env --profile cluster-worker up -d
   ```
3. Manual equivalent: master `docker compose -f deploy/docker-compose.lab_lan.yml --env-file deploy/lab_lan.env --profile cluster-master --profile cluster-worker up -d`; submit with
   ```bash
   docker exec lab-cluster-master python submit_pipeline_job.py --pipeline ner_translate \
     --input /app/data/ner_samples --execution-mode cluster --master spark://192.168.4.104:7077 \
     --partitions 2 --driver-memory 2g --executor-memory 4g
   ```

## Pass criteria
- `docker logs lab-cluster-worker | grep install_ner_deps` ends with `OK torch 2.6.0+cu126 | transformers 4.45.2 | gliner 0.2.13` on every node.
- `curl http://192.168.4.104:8080/json/` **run from the remote** shows `aliveworkers` = 2.
- `Processed 6 document(s)`, no `ERROR`; `partition_details` hostnames include both machines.
- Entities per document vs the earlier GPU reference 8, 27, 33, 6, 29, 39: on CPU, small differences are possible (reported, not a failure).
- Output: `results/lab_lan_<timestamp>/` (`summary.txt`, `summary.json`, logs, result JSON).

## Not yet verified (watch for these)
- Rebuilding wheels from `ner-translate-server` (python:3.11-slim, Debian) and installing them into `multi-model-inference` (Ubuntu 22.04, deadsnakes Python 3.11) has not been run end to end. If the install fails, the container exits: check `docker logs lab-cluster-master`.
- OCR `.deb`s come from the repo's `debs/ner_translate/` (mounted at `/deps-debs`); `sample_scan6.png` needs them.

## Troubleshooting
| Symptom | Cause / fix |
|---|---|
| `BindException: Cannot assign requested address` | Docker Desktop engine or mirrored networking off |
| Remote worker never registers; ping works | Network switched to Public on either machine; firewall rules |
| Worker joins, disappears ~20 s later | WSL idle shutdown: keep-alive + `vmIdleTimeout=-1` |
| Tasks hang | Ports blocked, or `spark-defaults.lan.conf` not mounted |
| Executor exits code 1 repeatedly | Driver advertises an unreachable address: `SPARK_LOCAL_IP` on master |
| `No such file` for documents on one node | `data/` missing or different on that node |
| `$'\r': command not found` | CRLF line endings: the `sed` command above |
