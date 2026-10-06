# NER Spark Cluster on multi-model-inference + a Dependency Image (WSL2 Ubuntu, Docker CE)

How to run the `ner_translate` Spark cluster on an air-gapped system that has **only `multi-model-inference:latest`**. The NER packages arrive as a small **dependency image** (wheel files, OCR packages, pinned versions). The cluster runs on `multi-model-inference` itself: the dependency image is mounted into each container and its packages are installed when the container starts. **No new image is built.** Models are read from a local folder; no HDFS and no internet are used.

**Tested end to end on 2026-10-05:** master and worker ran on `multi-model-inference:latest` with the dependency image mounted; both installed the packages at start (about 45 s including startup), and the NER job processed 6 of 6 documents with Hindi and Marathi translated, OCR on the scanned image, and the same entity counts as the existing production image (8, 27, 33, 6, 29, 39). A restarted container skipped the install.

Sections 1–9 cover one machine, section 10 a multi-node cluster, section 11 the alternative of building a ready image once.

---

## 1. How it fits together

| Part | What it is | Where |
|---|---|---|
| `multi-model-inference:latest` | The image the cluster runs: Ubuntu 22.04, Java 17, Spark 3.5.1, Python 3.11, PyTorch 2.6.0 (CUDA 12.6) | Already on the air-gapped system |
| Dependency image | Files only, nothing runnable: Python wheels, OCR `.deb` packages, pinned `requirements.txt` | Carried across (section 3) |
| `deploy/docker-compose.airgap_sim.yml` | Cluster definition; profile `cluster` = `sim-ner-cluster-master` + `sim-ner-cluster-worker` | Repo, **unchanged** |
| `deploy/docker-compose.ner_deps.yml` | Add-on: switches the `cluster` profile to `multi-model-inference` and mounts the dependency image read-only at `/deps` | Repo, new |
| `deploy/scripts/install_ner_deps.sh` | Runs at container start: installs the OCR packages and the NER wheels offline, then Spark starts | Repo, new |
| `deploy/dev.wsl.env` | Where the models are; optionally which dependency image to use | Repo |
| Model folder | `gliner-multi`, `nllb-200-distilled-600M`, `hf_cache` (~4.6 GB) | Local disk, e.g. `E:\ner\models\weights` |

What happens when a container starts:

1. Docker starts it from `multi-model-inference:latest` and mounts the dependency image at `/deps` (read-only), the models at `/mnt/models` and the repo code at `/app`.
2. `install_ner_deps.sh` installs the OCR packages from `/deps/debs`, then the NER Python packages with `pip --no-index` (only local files, never the internet), pinned by `/deps/requirements.txt`. It finds the packages itself, whatever the layout of the dependency image (section 2.1).
3. Spark (master or worker) starts.

If the dependency image has no `debs` folder or no `requirements.txt`, the script uses the repo's `debs/ner_translate` and `models/pipelines/ner_translate/requirements.txt`. A restarted container keeps its packages and skips step 2; a recreated one (after `down` + `up`) installs again.

Unless a step says PowerShell, run every command in the **Ubuntu shell** (`wsl -d Ubuntu-22.04`) from the **repo root**, the folder that contains `deploy/`.

---

## 2. Compatibility: what must match

| Item | Required | Why |
|---|---|---|
| Base image | `multi-model-inference:latest`, ID `sha256:986e9e56cddf...` | The OCR packages and pinned versions were resolved against it |
| Python in the base | 3.11 | Wheels must be built for Python 3.11, Linux x86_64 (`cp311`, `manylinux`) |
| torch / numpy in the base | `2.6.0+cu126` / `2.1.3` | The NER packages are pinned against these; a bundle must not upgrade them |
| transformers / gliner in the bundle | `4.45.2` / `0.2.13` | Newer transformers breaks loading GLiNER's tokenizer |
| Docker Engine | 28 or newer (tested 29.5 and 29.8) | Image volumes (`type: image`) |
| Docker Compose | 2.35 or newer (tested 5.1 and 5.5) | Image volumes in compose files |
| GPU | Ada, Ampere, Turing work with the base's torch | RTX 50-series would need a different torch build |

Expected layout of the dependency image (the tested `ner-translate-deps:latest` has exactly this):

| Path in the image | Contents | Required |
|---|---|---|
| `/wheels/` | 61 wheels + 2 pure-Python source packages (odfpy, ebooklib) | The NER packages must be somewhere: `.whl` files in any folder, or installed packages (section 2.1) |
| `/debs/` | 50 Ubuntu packages: tesseract-ocr, 12 language packs, poppler-utils | No: falls back to the repo's `debs/ner_translate` |
| `/requirements.txt` | Pinned versions | No: falls back to the repo's requirements file |

### 2.1 Any dependency image layout works: automatic detection

`/deps` does not have to exist in the dependency image: it is the folder in **your** container where the whole image is attached, so a file at `/opt/x` in that image appears at `/deps/opt/x`. At every start the install script looks at what the image holds and picks the matching route by itself; nothing has to be set.

| The dependency image holds | What the script does | Tested 2026-10-05 |
|---|---|---|
| `.whl` files in `/wheels` (the `ner-translate-deps` layout) | Installs from that folder | Full NER job passed |
| `.whl` files in any other folder, e.g. a plain Ubuntu image with `/opt/ner/wheels`, no `debs`, no requirements file | Finds the folder (the one holding a `gliner` wheel); uses the repo's OCR packages and requirements | Install and imports passed |
| **No `.whl` files**: the packages pip-installed in it, e.g. a `python:3.11` image | Rebuilds wheel files offline from the installed packages (their recorded file lists and platform tags), skipping torch and CUDA libraries so the base image's torch is never replaced, then installs those | Full NER job passed, identical results |

Python's own bundled installer wheels (`ensurepip`) are ignored. The pinned, offline install is the safety net in every route: wheels built for another Python version (e.g. 3.12), another platform, or other package versions make the container stop at start with pip's message naming the package, instead of installing something untested. Neither form can supply OCR from the dependency image unless it contains `.deb` files; the repo's `debs/ner_translate` is used otherwise.

### 2.2 How the dependency image reaches your container at runtime

You need **no control over the dependency image**: it is never changed, rebuilt or run. Docker only reads its files. What you need on the air-gapped system is the image loaded (`docker load`) and its name and tag (`docker images`). Its base OS, layout, entrypoint, and whether it has a `/deps` folder do not matter: `/deps` is the folder in **your** container where its files appear, so a file at `/opt/x` in that image is seen at `/deps/opt/x`.

```
 dependency image (as received, untouched)
        |
        +-- Way 1: Docker attaches the image itself at /deps           (nothing copied)
        |
        +-- Way 2: its files exported once to a folder -> folder bind-mounted at /deps
                                          |
 your container (multi-model-inference) --+  /deps -> install_ner_deps.sh finds wheels
                                                      or installed packages -> installs -> Spark starts
```

What the kernel shows inside a running container (checked 2026-10-05 and 2026-10-06):

| Mount | Seen as | Meaning |
|---|---|---|
| `/` | `overlay (rw)` | `multi-model-inference` layers + the container's own writable layer |
| `/deps` | `overlay (ro)` (Way 1) or `bind (ro)` (Way 2) | The dependency image's files, **read-only**: writing gives `Read-only file system` |
| `/usr/local/lib/python3.11/dist-packages` | part of `/` | Where pip installs the NER packages: the container's writable layer |

What survives what:

| Action | Installed NER packages | Why |
|---|---|---|
| `docker restart`, `compose stop` + `start` | Kept, install skipped | The writable layer belongs to the container, which still exists |
| `compose down` + `up` | Installed again (~45 s) | `down` deletes the containers and their writable layers |
| A newer dependency image | Used after `down` + `up` (Way 2: export again first) | `/deps` is fixed when a container is created |
| `multi-model-inference` itself | Never changes | Image layers are read-only |

The two ways compared:

| | Way 1: image mount | Way 2: exported folder |
|---|---|---|
| Add-on compose file | `deploy/docker-compose.ner_deps.yml` | `deploy/docker-compose.ner_deps_folder.yml` |
| Setting in `dev.wsl.env` | `NER_DEPS_IMAGE=<image>:<tag>` | `NER_DEPS_FOLDER=/home/<user>/ner/deps` |
| One-time step | `docker load` | `docker load` + export (section 5.1) |
| Extra disk space | None | About the image's size again |
| Docker requirement | Engine 28+ and Compose 2.35+; Docker labels image mounts **experimental** (it prints a warning) | Any version |
| Install logic, safety checks, results | Identical | Identical |
| Tested | Full NER job, 2026-10-05 | Install from an exported folder, and cluster start with the add-on file (worker registered), 2026-10-06 |

Use Way 1 while it works on your Docker; keep Way 2 as the fallback if the image mount is ever refused (an older Docker, or a future change to the experimental feature).

---

## 3. What to carry to the air-gapped system

| Item | Size | Notes |
|---|---|---|
| Dependency image as a `.tar` | 707 MB for `ner-translate-deps.tar` | SHA-256 `df71bd36ab1a687261fdf8d53a4c2245bf94ca7d277a25964be48ffd7dc1174e` (another bundle: record its own checksum) |
| `deploy/docker-compose.ner_deps.yml` | 2 KB | New: Way 1 (image mount) |
| `deploy/docker-compose.ner_deps_folder.yml` | 2 KB | New: Way 2 (exported folder) |
| `deploy/scripts/install_ner_deps.sh` | 2 KB | New |
| `deploy/dev.wsl.env` | < 1 KB | Section 6 |
| `deploy/spark-defaults.lan.conf` | < 1 KB | Multi-node only (section 10) |
| Model folder (3 sub-folders) | ~4.6 GB | `gliner-multi`, `nllb-200-distilled-600M`, `hf_cache` |
| This document | — | — |

Already on the air-gapped system: the repo (20260927, including `debs/ner_translate`) and `multi-model-inference:latest`.

---

## 4. Prerequisites in WSL2 Ubuntu

### 4.1 Windows: `C:\Users\<user>\.wslconfig`

```ini
[wsl2]
memory=6GB              # or more; shared by every WSL distro
networkingMode=mirrored
vmIdleTimeout=-1
```

After a change: `wsl --shutdown` in PowerShell, then open the Ubuntu shell again.

### 4.2 Ubuntu checks

| Check | Command | Expected |
|---|---|---|
| Docker CE is its own engine | `docker info --format '{{.Name}} {{.DockerRootDir}}'` | host name and `/var/lib/docker`, not `docker-desktop` |
| Engine version | `docker version --format '{{.Server.Version}}'` | 28 or newer |
| Compose version | `docker compose version` | 2.35 or newer |
| Base image present and correct | `docker images --no-trunc multi-model-inference` | ID `sha256:986e9e56cddf...` |
| GPU reachable | `docker run --rm --gpus all --entrypoint nvidia-smi multi-model-inference:latest -L` | the GPU name |
| systemd on | `cat /etc/wsl.conf` | `systemd=true` |

Images live inside one engine: load everything into **Docker CE in Ubuntu**, the engine the cluster runs on. An image in Docker Desktop is not visible there.

### 4.3 Quit Docker Desktop

If it is installed, quit it (tray icon, Quit). All WSL distros share the `.wslconfig` memory.

---

## 5. Load and check the dependency image

```bash
sha256sum /mnt/e/transfer/ner-translate-deps.tar      # compare with section 3
docker load -i /mnt/e/transfer/ner-translate-deps.tar
docker images ner-translate-deps
```

Look inside (the image has no shell, so list it through a stopped container). For another bundle, replace the image name:

```bash
docker create --name deps-check ner-translate-deps:latest none
docker export deps-check | tar -tf - | grep '\.whl$' | head -3                       # where the wheels are
docker export deps-check | tar -tf - | grep -c '\.whl$'                             # 61 for ner-translate-deps
docker export deps-check | tar -tf - | grep -c '\.deb$'                             # 50 (0 = repo debs are used)
docker export deps-check | tar -xOf - requirements.txt | grep -E '^(gliner|transformers)=='
docker rm deps-check
```

Expected for `ner-translate-deps`: wheels under `wheels/`, 61 wheels, 50 `.deb` packages, `gliner==0.2.13` and `transformers==4.45.2`. For any other dependency image this check is optional: nothing has to be set, because the install script finds the wheels or the installed packages itself (section 2.1). The check only shows in advance which route it will take.

### 5.1 Way 2 only: export the dependency image to a folder (once)

Skip this for Way 1. The commands read the image without running it, so they work for any image, even one with no shell:

```bash
docker create --name depc <dependency-image>:<tag> none
mkdir -p ~/ner/deps
docker export depc | tar -x --no-same-owner -C ~/ner/deps
docker rm depc
ls ~/ner/deps                         # the image's files, e.g. wheels/ debs/ requirements.txt, or usr/ opt/ ...
```

Then set `NER_DEPS_FOLDER=/home/<user>/ner/deps` in `deploy/dev.wsl.env` (section 6). Export to the Ubuntu disk (`~/...`), not to `/mnt/e`: Windows drives cannot keep Linux permissions and links, and are much slower. After loading a newer dependency image, delete the folder and export again.

---

## 6. Settings file: `deploy/dev.wsl.env`

Windows drives appear as `/mnt/<letter>` in Ubuntu. Exactly one `MODEL_FS_DIR` line must be active:

```ini
MODEL_FS_DIR=/mnt/e/ner/models/weights
MODEL_STORE_URI=file:///mnt/models

# Way 1 (image mount): the dependency image, if not ner-translate-deps:latest
# NER_DEPS_IMAGE=<image>:<tag>
# Way 2 (exported folder, section 5.1): required for Way 2
# NER_DEPS_FOLDER=/home/<user>/ner/deps
# Optional, both ways: force one wheel folder; found automatically otherwise
# NER_WHEELS_DIR=/deps/<folder>
```

```bash
ls /mnt/e/ner/models/weights          # gliner-multi  hf_cache  nllb-200-distilled-600M
```

`hf_cache` is required: without it GLiNER tries to reach huggingface.co and fails offline. For faster loading, copy the models onto the Ubuntu disk (`mkdir -p ~/ner && cp -r /mnt/e/ner/models ~/ner/`) and set `MODEL_FS_DIR=/home/<user>/ner/models/weights`.

---

## 7. Start, run and stop the cluster

### 7.1 Every session: keep the distro awake

In **PowerShell**, once per session; leave it running:

```powershell
Start-Process powershell -ArgumentList '-NoProfile','-Command','wsl -d Ubuntu-22.04 -- sleep infinity' -WindowStyle Hidden
```

Without it WSL can shut the distro down as idle, and the containers restart with empty logs.

### 7.2 Start

```bash
cd <repo root>                         # e.g. /mnt/e/ner/repo
unset MODEL_STORE_URI MODEL_FS_DIR     # shell variables override dev.wsl.env

# Way 1 (image mount)
docker compose -f deploy/docker-compose.airgap_sim.yml -f deploy/docker-compose.ner_deps.yml \
  --env-file deploy/dev.wsl.env --profile cluster up -d

# Way 2 (exported folder, section 5.1) - instead of the command above
docker compose -f deploy/docker-compose.airgap_sim.yml -f deploy/docker-compose.ner_deps_folder.yml \
  --env-file deploy/dev.wsl.env --profile cluster up -d
```

The second `-f` is the only difference from the plain compose command; use the same pair of files for every later command (`ps`, `logs`, `down`). Expected: `sim-ner-cluster-master  Healthy`, then `sim-ner-cluster-worker  Started`, about 45 s after the command (the master installs before Spark answers its health check).

### 7.3 Check the install and the worker

```bash
docker logs sim-ner-cluster-master 2>&1 | grep install_ner_deps
docker logs sim-ner-cluster-worker 2>&1 | grep install_ner_deps
docker exec sim-ner-cluster-master curl -s http://localhost:8080/json/ | grep aliveworkers
docker inspect -f '{{.Config.Image}}' sim-ner-cluster-master sim-ner-cluster-worker
```

Expected:

```
[install_ner_deps] OCR packages from /deps/debs
[install_ner_deps] Python packages from /deps/wheels (pinned by /deps/requirements.txt)
[install_ner_deps] OK torch 2.6.0+cu126 | transformers 4.45.2 | gliner 0.2.13
"aliveworkers" : 1
multi-model-inference:latest
multi-model-inference:latest
```

The `OK` line must show these exact versions in both containers. The Spark UI is at http://localhost:8084 in the Windows browser.

### 7.4 Run the NER job

```bash
docker exec -w /app sim-ner-cluster-master python submit_pipeline_job.py --pipeline ner_translate \
  --input /app/data/ner_samples --execution-mode cluster --master spark://ner-cluster-master:7077 \
  --partitions 1 --driver-memory 1g --executor-memory 4g
```

Expected: `execution-mode=cluster -> in-process ... on spark://ner-cluster-master:7077`, then `Processed 6 document(s)` with one `lang=` line per document. The test run took 182 s: 133 s loading the models, 34 s processing.

### 7.5 Confirm models and OCR

```bash
docker exec sim-ner-cluster-worker bash -c "grep -rh 'model source' /opt/spark/work | tail -1"
docker exec sim-ner-cluster-worker tesseract --list-langs
ls -t results/ | head -3
```

Expected: `model source: model store file:///mnt/models`; 12 OCR languages (`ben eng guj hin kan mal mar osd pan tam tel urd`); a new `results/ner_translate_<timestamp>.json`.

### 7.6 Stop

```bash
docker compose -f deploy/docker-compose.airgap_sim.yml -f deploy/docker-compose.ner_deps.yml --profile cluster down          # Way 1
docker compose -f deploy/docker-compose.airgap_sim.yml -f deploy/docker-compose.ner_deps_folder.yml --profile cluster down   # Way 2
```

`down` removes the containers, so the next `up` installs again (~45 s). To pause without reinstalling, use `stop` and `start` instead of `down` and `up`.

---

## 8. Running your own documents

1. Put the documents in a folder under the repo's `data/`, e.g. `data/my_batch/`.
2. Pass the path as the container sees it: `--input /app/data/my_batch`, never a Windows `E:\...` path.
3. Give files unique names: results are keyed by file name, so same-named files in different sub-folders overwrite each other.
4. With more memory, raise `--executor-memory` (and the worker's `-m 6g` in `docker-compose.ner_deps.yml`) and `--partitions`. The values above fit a 6 GB WSL limit.

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `invalid mount config for type "image"` or `unknown volume type` | Image mounts not supported: Docker Engine older than 28 or Compose older than 2.35 | Use Way 2, the exported folder (sections 2.2 and 5.1), or the build alternative (section 11) |
| `WARNING: Image mount is an experimental feature` | Docker's label for Way 1 | Harmless; Way 2 avoids it |
| `required variable NER_DEPS_FOLDER is missing a value` | Way 2 started without the folder setting | Set `NER_DEPS_FOLDER` in `dev.wsl.env` (section 6) |
| `No such image: ner-translate-deps` at start | Dependency image not loaded in this engine | Section 5, in the Ubuntu shell |
| `ERROR: no .whl files and no installed gliner package found` in the logs | The dependency image holds neither NER wheels nor installed NER packages | Use the tested `ner-translate-deps.tar` |
| `ERROR: NER_WHEELS_DIR=... does not exist` in the logs | A wrong folder forced in `dev.wsl.env` | Remove the `NER_WHEELS_DIR` line (detection is automatic) |
| `No matching distribution found` in the logs, container exits | A package missing from the bundle, or built for another Python | The message names it; use a bundle that has it (section 12) |
| `dpkg: dependency problems` in the logs | The bundle's `.deb` files were built for another base | Remove its `debs` from use (repo `debs/ner_translate` matches this base) or rebuild the bundle |
| `OK` line shows other torch or transformers versions | The bundle upgraded packages | Use a bundle pinned as in section 2 |
| Worker never starts (`Waiting` on master) | Master still installing, or the install failed | `docker logs sim-ner-cluster-master` |
| `couldn't find env file ... deploy/deploy/dev.wsl.env` | Command run from inside `deploy/` | `cd ..` to the repo root |
| GLiNER: `couldn't connect to huggingface.co` | `hf_cache` missing from the model folder | Copy `hf_cache` there |
| Log shows `model store hdfs://...` | A shell variable overrode `dev.wsl.env` | `unset MODEL_STORE_URI MODEL_FS_DIR`, then `down` and `up` |
| `Repo id must be in the form ...` | `--env-file` not passed | Use the start command in 7.2 exactly |
| Containers restart every 20–30 s, empty logs | WSL idle shutdown | `vmIdleTimeout=-1` and the keep-alive (7.1) |
| Stuck at `Stage 0: (0 + 0) / 1` | Worker not registered | Section 7.3; `docker logs sim-ner-cluster-worker` |
| Exit code 137 / container killed | Out of memory | Quit Docker Desktop; keep `--partitions 1` and the memory flags |
| `OCI runtime exec failed: Cwd must be an absolute path` | Command typed in Git Bash on Windows | Use the Ubuntu shell (or `export MSYS_NO_PATHCONV=1`) |

---

## 10. Multi-node cluster (two or more machines on the air-gapped LAN)

The method works across machines too. The compose file runs everything on **one** machine, so across machines each node starts **one container with `docker run` and host networking**, from `multi-model-inference:latest` with the dependency image mounted, inside its WSL2 Ubuntu Docker CE.

**Status:** each part is proven: the image-mount install with `docker run` (2026-10-05, 47 s); NER cluster mode across two real machines over WSL2 Docker CE (2026-09-25); the fixed Spark ports below (2026-10-05). The combination has not yet been run together: complete the acceptance test in 10.7 first.

### 10.1 What every node needs

| Requirement | Why | How to check |
|---|---|---|
| Docker CE 28+ in WSL2 Ubuntu with mirrored networking | Real LAN IP and image volumes | `ip -4 addr` shows the LAN IP; `docker version` |
| The same base image | Packages are pinned against it | `docker images --no-trunc multi-model-inference` gives `986e9e56cddf...` everywhere |
| The **same** dependency image loaded, **master included** | Every container installs from it; the master's driver also imports the NER code | Section 5 on each node; same checksum of the `.tar` |
| Identical installed versions on every node | Different versions between driver and workers break jobs | The `OK` line in each container's log (10.6) |
| Models **and** documents at the same paths on every node | A task can run on any worker, which opens the files on its own disk | `ls` the same paths on each node |
| The same repo code, including `deploy/spark-defaults.lan.conf` and `deploy/scripts/install_ner_deps.sh` | Mounted from the repo | Same repo copy on every node |
| Firewall open, network Private, keep-alive running | Spark connects between machines in both directions | 10.2 and 7.1 |

### 10.2 Network preparation (each machine, Windows side)

From an **administrator** PowerShell, once per machine:

```powershell
New-NetFirewallRule -DisplayName "Spark Master" -Direction Inbound -LocalPort 7077,8080,4040 -Protocol TCP -Action Allow -Profile Private
New-NetFirewallRule -DisplayName "Spark Worker" -Direction Inbound -LocalPort 8081 -Protocol TCP -Action Allow -Profile Private
New-NetFirewallRule -DisplayName "Spark Executors" -Direction Inbound -LocalPort 30000-40000 -Protocol TCP -Action Allow -Profile Private
```

After **every** `wsl --shutdown` or reboot, check the network is still Private:

```powershell
Get-NetConnectionProfile | Select-Object InterfaceAlias, NetworkCategory
Set-NetConnectionProfile -InterfaceAlias "Ethernet" -NetworkCategory Private
```

Spark normally picks random ports, which no firewall rule covers. `deploy/spark-defaults.lan.conf` fixes them inside the opened range (mounted in 10.4):

| Setting | Value | Used by |
|---|---|---|
| `spark.driver.port` | 35000 | Workers connecting back to the driver on the master |
| `spark.blockManager.port` | 35100 (35101 ... if taken) | Data and result transfer between all nodes |
| `spark.port.maxRetries` | 32 | Several processes on one machine take the next free port |

### 10.3 Load the dependency image on every node

On each node: section 5 (load and check). Use the **same** `.tar` everywhere and compare its checksum. For Way 2, also export it to the same folder on every node (section 5.1) and, in `COMMON` below, replace `--mount type=image,source=$DEPS,target=/deps` with `-v $HOME/ner/deps:/deps:ro`.

### 10.4 Start the nodes

In the Ubuntu shell of **each** machine, set these first (replace the IPs and paths):

```bash
MASTER=192.168.1.10                  # LAN IP of the master machine
ME=192.168.1.10                      # LAN IP of THIS machine (on a worker: its own IP)
REPO=/mnt/e/ner/repo
MODELS=/mnt/e/ner/models/weights
DEPS=ner-translate-deps:latest       # or any other dependency image: wheels or installed packages are found automatically
COMMON="--network host --init -w /app -e PYTHONUNBUFFERED=1 -e MODEL_STORE_URI=file:///mnt/models
  -e SPARK_LOCAL_IP=$ME -e SPARK_LOCAL_HOSTNAME=$ME
  --mount type=image,source=$DEPS,target=/deps
  -v $REPO/debs/ner_translate:/deps-debs:ro
  -v $REPO/deploy/scripts/install_ner_deps.sh:/usr/local/bin/install_ner_deps.sh:ro
  -v $MODELS:/mnt/models:ro -v $REPO/data:/app/data -v $REPO/results:/app/results
  -v $REPO/inference:/app/inference -v $REPO/models:/app/models
  -v $REPO/submit_pipeline_job.py:/app/submit_pipeline_job.py
  -v $REPO/deploy/spark-defaults.lan.conf:/opt/spark/conf/spark-defaults.conf:ro"
```

On the **master** machine:

```bash
docker run -d --name ner-master $COMMON multi-model-inference:latest \
  bash -c 'bash /usr/local/bin/install_ner_deps.sh && $SPARK_HOME/sbin/start-master.sh -h $SPARK_LOCAL_IP && tail -f $SPARK_HOME/logs/*master*'
```

On **every worker** machine (the master machine can run a worker too):

```bash
docker run -d --name ner-worker $COMMON --gpus all --shm-size=4g multi-model-inference:latest \
  bash -c "bash /usr/local/bin/install_ner_deps.sh && \$SPARK_HOME/sbin/start-worker.sh spark://$MASTER:7077 -c 4 -m 6g && tail -f \$SPARK_HOME/logs/*worker*"
```

`-c 4` must stay at 4 or more (each executor asks for 4 cores). Raise `-m 6g` on machines with more RAM, with a matching `.wslconfig` `memory=`.

### 10.5 Check the cluster from another machine

From a machine **other than the master** (a test on the master itself does not exercise the firewall):

```powershell
curl.exe http://<MASTER-IP>:8080/json/
```

Expected: `"aliveworkers"` equals the number of workers started, each with its own IP. Allow about a minute after starting for the install.

### 10.6 Submit, results, stop

On each node first confirm the install: `docker logs ner-master 2>&1 | grep install_ner_deps` (or `ner-worker`) must end with the same `OK torch 2.6.0+cu126 | transformers 4.45.2 | gliner 0.2.13` line everywhere.

On the master:

```bash
docker exec -w /app ner-master python submit_pipeline_job.py --pipeline ner_translate \
  --input /app/data/ner_samples --execution-mode cluster --master spark://$MASTER:7077 \
  --partitions 2 --driver-memory 2g --executor-memory 4g
```

Use `--partitions` of at least the number of workers. Results are written to `results/` **on the master only**.

Stop: `docker rm -f ner-worker` on each worker, then `docker rm -f ner-master`. To restart, run the same `docker run` commands again (each container installs again, about a minute).

### 10.7 Acceptance test (run once before relying on the cluster)

| # | Check | Pass when |
|---|---|---|
| 1 | `OK` install line on every node (10.6) | Identical versions everywhere |
| 2 | `curl.exe http://<MASTER-IP>:8080/json/` from another machine | `aliveworkers` = number of workers |
| 3 | Sample job (10.6) | `Processed 6 document(s)`, no `ERROR` lines |
| 4 | Work ran on the workers | The job's printed `partition_details` show the **worker machines'** host names |
| 5 | Same results as one machine | Entities per document 8, 27, 33, 6, 29, 39; Hindi and Marathi `translated=True` |
| 6 | Models from the local folder | On each worker, `docker exec ner-worker grep -rh 'model source' /opt/spark/work` shows `file:///mnt/models` |
| 7 | Survives a restart | After `wsl --shutdown` on one worker: network still Private, worker started again, job passes |

### 10.8 Multi-node troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `BindException: Cannot assign requested address` | The engine cannot use the real IP (Docker Desktop, or mirrored networking off) | Docker CE in Ubuntu; `ip -4 addr` must show the LAN IP |
| `ping` works but `:8080` times out from another machine | Network switched to Public | 10.2, `Set-NetConnectionProfile` |
| Worker registers, then disappears ~20 s later | WSL idle shutdown on that worker | `vmIdleTimeout=-1` and the keep-alive on every node |
| Worker registered, but tasks never finish | Ports blocked, or `spark-defaults.lan.conf` not mounted | Firewall rules; the mount line in `COMMON` on every node |
| Executor exits with code 1 repeatedly | The driver advertises an address the worker cannot reach | `SPARK_LOCAL_IP` / `SPARK_LOCAL_HOSTNAME` = the master's LAN IP on the master |
| Container exits right after start | The install failed on that node | `docker logs ner-worker`: missing image, wrong `NER_WHEELS_DIR`, or a missing package |
| `No such file or directory` for documents on one worker | Documents not at the same path on that node | Copy the same `data/` folder to every node |
| Import or version errors on one node | A different dependency image on that node | Same `.tar` and checksum everywhere |
| `container name already in use` | Old container from a previous start | `docker rm -f ner-master` / `ner-worker`, then start again |

---

## 11. Alternative: build a ready image once

Instead of installing at every container start, the same two images can produce a ready `ner-translate-worker:latest` once (1–2 minutes); the cluster then starts without the install step. Tested 2026-10-05 with the same result.

| | Install at start (sections 6–7, main) | Ready image (this section) |
|---|---|---|
| Images on the system | `multi-model-inference` + dependency image | + `ner-translate-worker` (~0.4 GB extra) |
| Build step | None | Once, and again when the bundle changes |
| Container start | ~45 s longer after `down`/`up` (install) | Immediate |
| Compose command | Two `-f` files | The plain compose command (one `-f`) |

Build (needs BuildKit: `docker buildx version` must print a version):

```bash
docker build -t ner-translate-worker:latest -f deploy/Dockerfile.ner_translate_from_deps .
# another bundle: add --build-arg DEPS_IMAGE=<image>:<tag>   (it must have /wheels, /debs and /requirements.txt at its root)
```

Verify, then start with the plain command (no `docker-compose.ner_deps.yml`):

```bash
docker run --rm --entrypoint python ner-translate-worker:latest -c "import gliner, transformers, torch, numpy; print('OK', torch.__version__, numpy.__version__, transformers.__version__, gliner.__version__)"
docker compose -f deploy/docker-compose.airgap_sim.yml --env-file deploy/dev.wsl.env --profile cluster up -d
```

Expected: `OK 2.6.0+cu126 2.1.3 4.45.2 0.2.13`. Do not add a `# syntax=docker/dockerfile:1` line to the Dockerfile: it makes the build contact Docker Hub.

---

## 12. Internet side: how the dependency image is produced

Run on the internet-connected machine that has the same `multi-model-inference:latest`, from the repo root:

```bash
bash deploy/scripts/build_ner_translate_wheelhouse.sh      # -> wheels/ner_translate (63 files)
bash deploy/scripts/build_ner_translate_debs.sh            # -> debs/ner_translate (50 files), only if the base changed
docker build -t ner-translate-deps:latest -f deploy/Dockerfile.ner_deps .
docker save ner-translate-deps:latest -o ner-translate-deps.tar
sha256sum ner-translate-deps.tar                           # record for the check on arrival
```

Before shipping, run sections 5–7 on the internet side with the new bundle.

A dependency image from another source (for example one prepared by a colleague) works if it holds the pinned NER packages for **Linux / Python 3.11**, either as `.whl` files in any folder or installed in its Python (section 2.1): set only `NER_DEPS_IMAGE` (section 6). If its packages are for another Python version or other versions, the containers stop at start with pip naming the package; use `ner-translate-deps.tar` instead.

---

## 13. Quick reference

```bash
# once
docker load -i /mnt/e/transfer/ner-translate-deps.tar

# every session (keep-alive running in PowerShell first)
cd <repo root>; unset MODEL_STORE_URI MODEL_FS_DIR
docker compose -f deploy/docker-compose.airgap_sim.yml -f deploy/docker-compose.ner_deps.yml --env-file deploy/dev.wsl.env --profile cluster up -d
#   Way 2 instead: same command with -f deploy/docker-compose.ner_deps_folder.yml (after the one-time export, section 5.1)
docker logs sim-ner-cluster-worker 2>&1 | grep install_ner_deps
docker exec sim-ner-cluster-master curl -s http://localhost:8080/json/ | grep aliveworkers
docker exec -w /app sim-ner-cluster-master python submit_pipeline_job.py --pipeline ner_translate --input /app/data/ner_samples --execution-mode cluster --master spark://ner-cluster-master:7077 --partitions 1 --driver-memory 1g --executor-memory 4g
docker compose -f deploy/docker-compose.airgap_sim.yml -f deploy/docker-compose.ner_deps.yml --profile cluster down

# multi-node (section 10): set MASTER, ME, REPO, MODELS, DEPS, COMMON on each node first
docker run -d --name ner-master $COMMON multi-model-inference:latest bash -c 'bash /usr/local/bin/install_ner_deps.sh && $SPARK_HOME/sbin/start-master.sh -h $SPARK_LOCAL_IP && tail -f $SPARK_HOME/logs/*master*'
docker run -d --name ner-worker $COMMON --gpus all --shm-size=4g multi-model-inference:latest bash -c "bash /usr/local/bin/install_ner_deps.sh && \$SPARK_HOME/sbin/start-worker.sh spark://$MASTER:7077 -c 4 -m 6g && tail -f \$SPARK_HOME/logs/*worker*"
docker exec -w /app ner-master python submit_pipeline_job.py --pipeline ner_translate --input /app/data/ner_samples --execution-mode cluster --master spark://$MASTER:7077 --partitions 2 --driver-memory 2g --executor-memory 4g
```
