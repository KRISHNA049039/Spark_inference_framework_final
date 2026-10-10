# Ada runbook: NER pipeline in Spark cluster mode (air-gapped)

Step-by-step procedure to run the `ner_translate` pipeline in **cluster mode** (GLiNER + NLLB load inside the Spark executors) on the air-gapped Ada system, using only:

| Image | Role |
|---|---|
| `multi-model-inference:latest` | Spark master, worker, driver and executors (Spark + torch) |
| `ner-translate-server:latest` | **Not run.** Mounted read-only at `/deps`; `deploy/scripts/install_ner_deps.sh` rebuilds wheels from its installed packages at container start (offline, torch skipped) and installs them |

`spark-lean:latest` is only for server mode and is not used here.

Each step below was run on the lab master PC `RAPL-DSK-161` on 2026-10-10; the "Lab result" lines are what it printed. Section 9 lists what is still open.

---

## 0. What to carry into Ada

| Item | Check on Ada |
|---|---|
| `multi-model-inference` image tar (`docker save`) | `sha256sum` of the tar = the value recorded on the internet side; after load, image id = the one in step 3 |
| `ner-translate-server` image tar | same |
| The repo, branch `lab-lan-sm120` (at least `deploy/`, `data/`, `models/`, `inference/`, `debs/ner_translate/`, `submit_pipeline_job.py`) | Same copy on **every** node |
| Model weights folder with `gliner-multi/`, `nllb-200-distilled-600M/`, `hf_cache/` (~4.6 GB) | Same contents at the same path on **every** node |

Record checksums before transfer (internet side):

```bash
docker save multi-model-inference:latest -o multi-model-inference.tar
docker save ner-translate-server:latest  -o ner-translate-server.tar
sha256sum *.tar > images.sha256
tar czf models-weights.tar.gz -C <weights dir> gliner-multi nllb-200-distilled-600M hf_cache
sha256sum models-weights.tar.gz >> images.sha256
```

---

## 1. Windows side, every node (once)

`C:\Users\<user>\.wslconfig`:

```ini
[wsl2]
networkingMode=mirrored
vmIdleTimeout=-1
memory=12GB
```

Then `wsl --shutdown`. Docker Desktop must be **quit**: its engine cannot bind the real LAN IP.

Firewall, from an **administrator** PowerShell (once per machine):

```powershell
New-NetFirewallRule -DisplayName "Spark Master"    -Direction Inbound -LocalPort 7077,8080,4040 -Protocol TCP -Action Allow -Profile Private
New-NetFirewallRule -DisplayName "Spark Worker"    -Direction Inbound -LocalPort 8081 -Protocol TCP -Action Allow -Profile Private
New-NetFirewallRule -DisplayName "Spark Executors" -Direction Inbound -LocalPort 30000-40000 -Protocol TCP -Action Allow -Profile Private
```

After **every** reboot or `wsl --shutdown`:

```powershell
Get-NetConnectionProfile | Select-Object InterfaceAlias, NetworkCategory
Set-NetConnectionProfile -InterfaceAlias "Ethernet" -NetworkCategory Private
```

Keep-alive, every session (leave this window open):

```powershell
wsl -d Ubuntu-22.04 -- sleep 999999
```

Lab result: `.wslconfig` had `networkingMode=mirrored`, `vmIdleTimeout=-1`.

---

## 2. Ubuntu shell checks, every node

Open the shell with `wsl -d Ubuntu-22.04` (not plain `bash` from cmd: that can open the `docker-desktop` distro).

```bash
ip -4 addr | grep inet                                        # must show this node's LAN IP
docker info --format '{{.Name}} | {{.OperatingSystem}}'       # host name | Ubuntu 22.04, NOT docker-desktop
docker version --format '{{.Server.Version}}'                 # 28 or newer
docker compose version                                        # 2.35 or newer
```

If `docker` says `permission denied ... docker.sock`, the user is not in the `docker` group. Either prefix commands with `sudo`, or once:

```bash
sudo usermod -aG docker $USER      # then close and reopen the Ubuntu shell
```

Nothing else may hold ports 7077 / 8080 (an old Spark master container, for example):

```bash
ss -ltnp | grep -E ':(7077|8080)\b'      # must print nothing
docker ps --format '{{.Names}} {{.Image}} {{.Status}}'
docker stop <old-container>              # if one holds the ports (docker start <name> brings it back)
```

Lab result: LAN IP `192.168.4.104` visible, Docker CE 29.8.1 on Ubuntu 22.04.5. User `pc` was not in the `docker` group (commands were run as root). An old container `spark-master` (restart policy `unless-stopped`) held 7077/8080 and was stopped.

---

## 3. Load and verify the images, every node

```bash
sha256sum -c images.sha256
docker load -i multi-model-inference.tar
docker load -i ner-translate-server.tar
docker image inspect -f '{{.Id}}' multi-model-inference:latest ner-translate-server:latest
```

Check torch inside each image (must be the build Ada's GPU needs):

```bash
for i in multi-model-inference:latest ner-translate-server:latest; do
  docker run --rm --network none --entrypoint python $i -c \
    'import torch,sys; print(sys.version.split()[0], torch.__version__, torch.version.cuda)'
done
```

Expected per the air-gap docs: `multi-model-inference` id `sha256:986e9e56cddf...`, Python 3.11, **torch 2.6.0+cu126**.

Lab result (**mismatch, see section 9**):

| Image | Id | Python | torch |
|---|---|---|---|
| `multi-model-inference:latest` | `sha256:d26b4e5e51d7a996717f98f4646b2707c927c10cd3cd607579a84014c98e4688` (built 2026-07-20) | 3.11.15 | 2.2.0+cu121 |
| `ner-translate-server:latest` | `sha256:85d2d052ea13c3543d327c5c9607c5437f089dc26ecc616bece4878bfd765486` | 3.11.16 | 2.6.0+cu126 |
| `spark-lean:latest` (not used) | `sha256:29a195a86a9ff07d5e17482e2182be750965f437586353247b3dbc9d513cd96b` | | |

---

## 4. Repo and settings, every node

```bash
cd <repo root>                     # the folder that contains deploy/, data/, models/
ls deploy/lab_lan_tests.sh deploy/docker-compose.lab_lan.yml deploy/scripts/install_ner_deps.sh
```

If the repo was checked out or copied from Windows, strip CR line endings (`$'\r': command not found` otherwise):

```bash
sed -i 's/\r$//' deploy/lab_lan_tests.sh deploy/scripts/install_ner_deps.sh deploy/lab_lan.env deploy/spark-defaults.lan.conf
```

Edit `deploy/lab_lan.env`:

| Variable | Set to |
|---|---|
| `LAB_MASTER_IP` | master node's LAN IP (from `ip -4 addr` on the master) |
| `LAB_NODE_IP` | this node's LAN IP (on the master: same as `LAB_MASTER_IP`) |
| `MODEL_FS_DIR` | Linux path of the weights folder, e.g. `/mnt/e/ner/models/weights` |

`deploy/lab_lan_tests.sh` re-reads this file itself, so a value exported in the shell does **not** override `MODEL_FS_DIR` for the runner: edit the file. (For plain `docker compose`, an exported variable does win, which is how `LAB_NODE_IP` is set on the workers.)

Verify the weights:

```bash
. deploy/lab_lan.env; ls $MODEL_FS_DIR      # gliner-multi  hf_cache  nllb-200-distilled-600M
```

Lab result: the repo is at `D:\spark-final\Spark_inference_framework_final` (one level below `D:\spark-final`, which is why running from `D:\spark-final` gave "No such file or directory"). The lab scripts had LF endings already. `MODEL_FS_DIR` was changed to `/mnt/d/pytorch-spark-inference-platform/models/weights`. That folder has no `hf_cache/`; an empty one was created so the prerequisite check passes, and GLiNER was confirmed to load offline (`--network none`, `HF_HUB_OFFLINE=1`) from `gliner-multi/` alone. Ada should still get the real `hf_cache/` from the bill of materials.

---

## 5. Single node first (master only)

On the master, from the repo root:

```bash
LAB_EXPECT_WORKERS=1 bash deploy/lab_lan_tests.sh cluster
```

What it does: L01 prerequisites (Docker, LAN IP, image ids, weights), then starts `lab-cluster-master` and `lab-cluster-worker` (compose profiles `cluster-master`, `cluster-worker`), waits for the worker, runs `install_ner_deps.sh` in each container, submits the 6 sample documents, checks the result, saves logs, and stops the containers.

Lab result (`results/lab_lan_20261010_195605/`), about 2 min end to end:

```
[install_ner_deps] OCR packages from /deps-debs
[install_ner_deps] no .whl files; rebuilding wheels from the packages installed in /deps/usr/local/lib/python3.11/site-packages
[install_ner_deps] rebuilt 63 wheels; not taken: nvidia-* (13), torch, torchvision, triton
[install_ner_deps] OK torch 2.2.0+cu121 | transformers 4.45.2 | gliner 0.2.13
L01  PASS  prerequisites
L02  PASS  cluster: 6/6 docs, errors=0, hosts=['RAPL-DSK-161'], entities=[8, 28, 33, 6, 29, 39], elapsed=66.8s
```

| Document | Language | Entities (lab, CPU) | GPU reference |
|---|---|---|---|
| sample_scan6.png (OCR) | en | 8 | 8 |
| sample_text1.txt | en | 28 | 27 |
| sample_text2.txt | en | 33 | 33 |
| sample_text3.txt | en | 6 | 6 |
| sample_text4.txt | hi | 29 | 29 |
| sample_text5.txt | mr | 39 | 39 |

One extra entity in `sample_text1.txt` on CPU: within the expected CPU/GPU variation.

---

## 6. Two (or more) nodes

### 6.1 Start the run on the master

```bash
bash deploy/lab_lan_tests.sh cluster          # LAB_REMOTE_IP=<worker IP> if not 192.168.4.101
```

It starts the master + local worker, then prints the command for the remote node and waits (up to 15 min) for it to register.

### 6.2 On each other node, from its repo root

```bash
docker compose -f deploy/docker-compose.lab_lan.yml --env-file deploy/lab_lan.env --profile server-worker --profile cluster-worker down
LAB_NODE_IP=<this node's IP> docker compose -f deploy/docker-compose.lab_lan.yml --env-file deploy/lab_lan.env --profile cluster-worker up -d
docker logs -f lab-cluster-worker 2>&1 | grep install_ner_deps      # wait for the OK line, Ctrl+C
```

### 6.3 Check from a node other than the master

```bash
curl -s http://<MASTER-IP>:8080/json/ | python3 -c "import json,sys; d=json.load(sys.stdin); print('aliveworkers', d['aliveworkers'], [w['host'] for w in d['workers'] if w['state']=='ALIVE'])"
```

(PowerShell: `curl.exe http://<MASTER-IP>:8080/json/`.) Must show every worker.

### 6.4 After the run, on each other node

```bash
docker compose -f deploy/docker-compose.lab_lan.yml --env-file deploy/lab_lan.env --profile cluster-worker down
```

Lab result: not run yet (needs the remote PC `192.168.4.101`).

---

## 7. Manual equivalent (no runner script)

Master:

```bash
docker compose -f deploy/docker-compose.lab_lan.yml --env-file deploy/lab_lan.env --profile cluster-master --profile cluster-worker up -d
docker logs lab-cluster-master 2>&1 | grep install_ner_deps     # OK line
docker exec -w /app lab-cluster-master python submit_pipeline_job.py --pipeline ner_translate \
  --input /app/data/ner_samples --execution-mode cluster --master spark://<MASTER-IP>:7077 \
  --partitions 2 --driver-memory 2g --executor-memory 4g
```

Use `--partitions` at least equal to the number of workers. Results land in `results/ner_translate_<timestamp>.json` on the master.

Stop: `... --profile cluster-master --profile cluster-worker down` on the master, `... --profile cluster-worker down` on the others.

**GPU on Ada:** `docker-compose.lab_lan.yml` hides the GPU (`CUDA_VISIBLE_DEVICES=""`, no device reservation), because the lab RTX 5060s (sm_120) have no kernels in the cu126 images. That is the same CPU code path on Ada and is a valid first acceptance run. To use Ada's sm_89 GPU, start the workers with `docker run ... --gpus all` as in `docs/NER_CLUSTER_FROM_DEPS_IMAGE_WSL_20261005.md` section 10.4, with `DEPS=ner-translate-server:latest`. Do **not** use `docker-compose.lab_lan.gpu.yml` on Ada: it swaps in lab-only cu128 images.

---

## 8. Pass criteria

| # | Check | Pass when |
|---|---|---|
| 1 | `docker logs lab-cluster-worker 2>&1 \| grep install_ner_deps` on every node | Same `OK torch ... \| transformers 4.45.2 \| gliner 0.2.13` line everywhere |
| 2 | Step 6.3 from a non-master node | `aliveworkers` = number of nodes |
| 3 | Runner output | `Processed 6 document(s)`, no `ERROR`, `PASS` |
| 4 | `partition_details` hostnames | Include every node |
| 5 | Entities per document | 8, 27, 33, 6, 29, 39 (±1 on CPU is acceptable, report it) |
| 6 | Output | `results/lab_lan_<timestamp>/summary.txt`, `summary.json`, logs, result JSON |

---

## 9. Open items found in the lab (2026-10-10)

1. **Base image mismatch.** The lab's `multi-model-inference:latest` is `d26b4e5e51d7...` with torch **2.2.0+cu121**; the air-gap docs expect `986e9e56cddf...` with torch **2.6.0+cu126**. The lab pass therefore used a different base image than Ada. Re-run steps 3 and 5 after loading the exact `multi-model-inference` tar that goes to Ada (no such tar was found on the lab PC).
2. **`hf_cache/` missing in the lab weights.** Not needed by gliner 0.2.13 for this model (verified offline), but the documented Ada set includes it.
3. **Two-node run** (section 6) still to do.

---

## 10. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `permission denied ... docker.sock` | User not in `docker` group: `sudo`, or step 2 |
| L01 `MISSING weights: ...` though the folder exists elsewhere | `MODEL_FS_DIR` in `deploy/lab_lan.env` (exported shell value is ignored by the runner) |
| Port 7077/8080 already in use | Old Spark container: `docker ps`, `docker stop <name>` |
| `BindException: Cannot assign requested address` | Docker Desktop engine, or mirrored networking off |
| Remote worker never registers; ping works | Network switched to Public; firewall rules |
| Worker joins, disappears ~20 s later | WSL idle shutdown: keep-alive + `vmIdleTimeout=-1` |
| Tasks hang | Ports blocked, or `spark-defaults.lan.conf` not mounted |
| Executor exits code 1 repeatedly | `SPARK_LOCAL_IP` on the master is not its LAN IP |
| Container exits right after start | `install_ner_deps.sh` failed: `docker logs lab-cluster-master` |
| `No such file` for documents on one node | `data/` missing or different on that node |
| `$'\r': command not found` | CRLF: the `sed` in step 4 |
| `No such file or directory` for `deploy/lab_lan_tests.sh` | Not in the repo root (the folder containing `deploy/`) |
