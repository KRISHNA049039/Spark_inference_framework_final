# Session Summary (last ~3 hours) + Air-Gapped Dependency Update Guide

Consolidated reference: everything fixed in this session, where the WSL2 infrastructure actually lives on disk, and — the part that generalizes beyond today — how to update dependencies on images that are **already sitting on an air-gapped system**, without rebuilding and re-transporting the whole multi-GB image every time.

---

## Part 1: Everything fixed in the last ~3 hours

### 1. Networking — Docker Desktop couldn't reach the real LAN

Full detail in `docs/WINDOWS_LAN_NETWORKING_FIX_20260921.md`. Summary:

| Problem | Fix |
|---|---|
| Docker Desktop's containers can't bind to the host's real LAN IP (sealed in a NAT'd WSL2 VM) — broke multi-machine Spark clustering entirely | Installed a real Docker Engine (Docker CE) directly inside a WSL2 Ubuntu distro, with WSL2 **mirrored networking** enabled — gives genuine physical-NIC access, unlike Docker Desktop's own VM |
| WSL2's default idle-timeout was power-cycling the *entire distro VM* every ~20s, taking Docker down with it, disguised as random container "crash-looping" | `vmIdleTimeout=-1` in `.wslconfig` |
| Even with that fixed, driving the distro through many separate one-off `wsl -d <distro> -- <cmd>` calls re-triggers a *different*, per-instance idle path | Hold one long-lived dummy session open (`wsl -d Ubuntu-22.04 -- sleep 999999`) for the duration of any real work |
| Windows silently reclassified the network adapter Private→Public after `wsl --shutdown`, silently re-blocking the exact firewall rules already opened | `Set-NetConnectionProfile -NetworkCategory Private` — **must be re-checked after every `wsl --shutdown`**, not just once |

### 2. Spark master stability

- A hostname-resolution warning (`Your hostname ... resolves to a loopback address`) appeared intermittently and correlated with startup hangs → fixed by setting `SPARK_LOCAL_HOSTNAME=<real-ip>` explicitly, bypassing the OS-dependent default lookup.
- Switched the master's startup command from the `start-master.sh && tail -f ...` wrapper to running `spark-class org.apache.spark.deploy.master.Master` directly as the container's PID 1 — removes a whole class of wrapper-script failure modes (log-glob `tail -f` issues, the NVIDIA CUDA entrypoint banner/its GPU probing logic running unnecessarily on a container that never requested `--gpus all`).

### 3. GPU / CUDA — the RTX 5060 (Blackwell) kernel mismatch

Full forensic detail in `docs/WINDOWS_LAN_NETWORKING_FIX_20260921.md`; short version:

- `deploy/Dockerfile` (and `deploy/Dockerfile.ner_translate_server`) pin `torch==2.6.0+cu126` — this was **assumed** sufficient for `sm_120` (Blackwell/RTX 5060) support per `docs/CHANGELOG_20260720.md`, but never actually tested on real Blackwell hardware until this session.
- Directly tested on the real RTX 5060: `cu126` (even the latest `torch==2.14.0+cu126`) does **not** include `sm_120` kernels — confirmed via `torch.cuda.get_arch_list()` and an actual `RuntimeError: CUDA error: no kernel image is available for execution on the device`.
- **Confirmed working fixes** (both tested with a real `x @ x` matmul on the RTX 5060, not just import-checked):
  - `torch==2.9.1+cu128` / `torchvision==0.24.1` — matches what the orphaned `Dockerfile.worker` already had pinned (that file's assumption turned out correct, unlike `deploy/Dockerfile`'s).
  - `torch==2.14.0+cu130` / matching torchvision — also confirmed working, includes `sm_120` explicitly in its arch list.
- **RTX 6000 Ada (`sm_89`) is likely fine on the existing `cu126` build already** — CUDA's binary compatibility rule (same major version, non-decreasing minor) means `sm_86`, present in the `cu126` arch list, covers `sm_89`. Not yet empirically confirmed on real Ada hardware — verify with the same one-line check before trusting it.
- **Not yet applied to source** — `deploy/Dockerfile` and `deploy/Dockerfile.ner_translate_server` still pin the broken `cu126` build. Everything validated so far was a *live patch* on running containers (`pip install torch==2.9.1 ... --index-url .../cu128`), not a rebuild. See Part 3 below for why that's actually fine for air-gapped updates specifically.

### 4. The `multi-model-inference:latest` image is stale relative to current source

Discovered by trying to actually use features the image predates:

| Missing from the running image | Needed for |
|---|---|
| `models/pipelines/` (the entire `ner_translate` pipeline) | ner_translate pipeline |
| `submit_job.py` (root script) | the RDD/UDF engine comparison |
| `inference/cluster_engine_udf.py`, `inference/predict_batch_udf.py` | the pandas-UDF execution path |
| `models/plugins/` (whole dir) | any plugin-registered model (`example_mlp`) |
| `models/plugin_loader.py` | `submit_job.py` itself (imports it directly) |
| Correct `ultralytics`/`torchvision` pins | this image had `ultralytics==8.2.0`, which forces `torch` down to `2.2.0` — the exact bug `docs/CHANGELOG_20260913.md` already fixed in source, just not in this particular built image |

All of these were patched into the **running container** via `docker cp` (they're plain files, no image layer changes needed for a live test) — not into the image itself. A real rebuild from current source would include all of this from the start.

### 5. Built the `ner_translate` waiter/kitchen architecture from scratch

Per `docs/WAITER_KITCHEN_NER_TRANSLATE_DEPLOYMENT.md`, built and validated end-to-end:

1. Wheelhouse (`deploy/scripts/build_ner_translate_wheelhouse.sh`) — 78 files.
2. `.deb` bundle (`deploy/scripts/build_ner_translate_debs.sh`) — 50 files (tesseract-ocr + language packs + poppler-utils).
3. Model weights — GLiNER (1.1GB) + NLLB-200-distilled-600M (2.4GB), downloaded per the doc's `from_pretrained().save_pretrained()` snippets.
4. `spark-lean:latest` image (879MB) and `ner-translate-server:latest` image (3.26GB) — built (well, `spark-lean` was transferred from another machine after the shared `archive.apache.org` Spark download proved slow twice; `ner-translate-server` built independently in parallel since it doesn't depend on `spark-lean`).
5. Brought the cluster up via `deploy/scripts/setup_ner_translate_server.sh` — validated the on-disk layout, started `ner-translate-master` + `ner-translate-worker` + `ner-translate-server`, all healthy on first check.
6. **Found and fixed a real gap**: `deploy/docker-compose.ner_translate_server.yml` had CUDA MPS env vars wired up for the kitchen service but **no actual GPU device reservation** — the kitchen was silently running on CPU the whole time ("No GPU detected — running on CPU." in its own logs). Added:
   ```yaml
   deploy:
     resources:
       reservations:
         devices:
           - driver: nvidia
             count: all
             capabilities: [gpu]
   ```
7. Ran the pipeline end-to-end on real sample data (6 documents: English, Hindi, Marathi, one scanned image via OCR) — correct language detection, correct NLLB translation for the two non-English docs, correct GLiNER entity extraction throughout.
8. **CPU run: 45.36s. GPU run (after applying the same `cu128` live patch to the kitchen container): 5.86s — a ~7.7x speedup**, with identical output — real confirmation the GPU fix works for this pipeline too, not just the general benchmark.

### 6. New tooling created this session

- `deploy/scripts/lan_cluster_benchmarks.sh` + `deploy/run_lan_cluster_benchmarks.ps1` — a local-cluster equivalent of `run_gpu_benchmarks.ps1`/`gpu_benchmarks.sh`, driving the same benchmark matrix (CPU baseline → GPU → hybrid → batch-size sweep → incremental) against this WSL2/Docker-CE cluster via `wsl -d <distro> -- docker exec` instead of AWS SSM, live-patching the `cu128` fix in before any GPU-mode test, and parsing results with the schema actually verified against a real results file (not guessed).
- Captured real Spark job/stage/executor statistics via `benchmark/capture_spark_stats.py` (also missing from the stale image, copied in directly — it's a stdlib-only script) against a live `cluster_benchmark.py` run on the real 2-machine cluster. Note: this script needs port 4040 (Spark's Application UI) alive, which only exists while a job is running — the `ner_translate` pipeline's driver process never opens that port at all (investigated with three different methods, inconclusive as to the exact cause but confirmed real), so stats capture only works against the general benchmark cluster's jobs, not the waiter/kitchen pipeline's.

---

## Part 2: Where the WSL2 Ubuntu distro actually lives on this system

```powershell
Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' | ForEach-Object { Get-ItemProperty $_.PSPath } | Where-Object { $_.DistributionName -like '*Ubuntu*' } | Select-Object DistributionName, BasePath
```

On this machine, that resolves to:

```
Ubuntu-22.04  →  C:\Users\pc\AppData\Local\wsl\{b63bd30e-9b0f-4b39-93bc-f22d7abf1be3}
```

Inside that folder: a single `ext4.vhdx` file (currently **64.35GB** — a dynamically-expanding virtual disk, so this reflects everything that's accumulated: Docker CE itself, `containerd`, and every image we've loaded — `multi-model-inference:latest`, `ner-translate-server:latest`, `spark-lean:latest`). This is **not** the Microsoft-Store-package location (`%LOCALAPPDATA%\Packages\CanonicalGroupLimited...`) that older/Store-installed WSL distros use — `wsl --install -d <name>` on this WSL version installs to `%LOCALAPPDATA%\wsl\<GUID>\` instead. If you're scripting against this path on another machine, look it up via the registry key above rather than assuming the path — the GUID is unique per distro instance.

This single `ext4.vhdx` is exactly what `wsl --export`/`wsl --import` operate on (see `docs/AIRGAPPED_WSL2_DOCKER_CLONE_20260921.md`) — it's the whole distro: OS, Docker CE, nvidia-container-toolkit, and (unless deliberately stripped first) every Docker image sitting inside it.

---

## Part 3: Updating dependencies on an air-gapped system's *existing* images

This is the generalizable question this session kept circling back to: given images already sitting on an air-gapped box, is it better to patch them in place or rebuild-and-retransport? **Patch in place, via pre-downloaded files — never a live `pip install --index-url ...` (that needs internet the air-gapped box doesn't have).**

### The pattern (works for any Python dependency update, not just torch)

**On an internet-connected machine:**
```bash
pip download <package>==<version> --index-url <index-url> -d ./patch-wheels
# e.g. the exact fix validated this session:
pip download torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cu128 -d ./cu128-patch
```

**Transfer** `./cu128-patch/` (a few hundred MB — the wheel files themselves, not a rebuilt image) to the air-gapped system via your normal transfer process (USB/data-diode/optical media — `docs/internet_to_airgapped_transfer.md`'s checksum workflow applies here too).

**On the air-gapped system, patch the already-loaded image's running (or freshly-started) container:**
```bash
docker exec <container> pip install --no-index --find-links=/path/to/cu128-patch torch==2.9.1 torchvision==0.24.1
```

### Why this beats rebuilding+retransporting

- The patch bundle is tens to a few hundred MB. The image it's patching is multiple GB. For a single dependency bump, moving the whole image again is pure waste.
- This is exactly the same principle this repo already uses for the `ner_translate` wheelhouse (`deploy/scripts/build_ner_translate_wheelhouse.sh` → `wheels/ner_translate/`) and for hotfixes (`deploy/apply_wheels_hotfix.sh` + `wheels-hotfix/<pipeline>/`) — this session's GPU fix is the same pattern, just applied ad hoc instead of through the repo's existing wheelhouse tooling.

### Two important gotchas learned the hard way this session

1. **Order matters if the app loads models at container startup.** `ner-translate-server`'s `CMD` runs `uvicorn`, which loads GLiNER/NLLB onto the GPU *synchronously at startup* — patching torch via `docker exec` after that already-crashed doesn't help, because the container already died before you can exec into it. Fix: start the container with an overridden idle command first (`--entrypoint sleep ... infinity`, or `docker compose run` with a benign override), apply the patch while it's idling, *then* start the real app process inside the now-patched container (`docker exec -d <container> python -m uvicorn ...`) — use `python -m uvicorn`, not bare `uvicorn`, since a fresh `pip install` can leave console-script shims off the default `$PATH` search in a `docker exec` shell.
2. **A live patch is not persistent.** `docker exec pip install` changes only the running container's writable layer. If that container is ever removed and recreated fresh from the image (`docker compose up --force-recreate`, `docker rm` + `docker run`, a host reboot without `--restart` policy, etc.), it reverts to whatever's baked into the image. Treat a live patch as a *validation step* ("does this fix actually work on this hardware?") — once confirmed, still get the fix into the actual Dockerfile source and rebuild for anything meant to survive a container recreation. This session validated the `cu128`/`cu130` fix live everywhere; the corresponding source-level fix (updating `deploy/Dockerfile`'s and `deploy/Dockerfile.ner_translate_server`'s torch pins) is still outstanding.

### Applying this to the RTX 5060 (Blackwell) fix specifically, air-gapped

If the air-gapped system's images already exist there (built or transferred earlier) and you just need the `sm_120` fix without moving those multi-GB images again:

```bash
# Internet-connected machine:
pip download torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cu128 -d ./cu128-patch
# transfer ./cu128-patch/ (few hundred MB) to the air-gapped box, then there, per image/container that needs it:
docker exec multi-model-inference-container pip install --no-index --find-links=/path/to/cu128-patch torch==2.9.1 torchvision==0.24.1
docker exec ner-translate-server-container pip install --no-index --find-links=/path/to/cu128-patch torch==2.9.1 torchvision==0.24.1
```

Remember: **skip this entirely if the air-gapped GPU is Ada (RTX 6000 Ada, `sm_89`), not Blackwell** — per Part 1 §3, the existing `cu126` build likely already covers it. Verify with the one-line check before patching anything unnecessarily.

---

## Part 4: Making all of this work on the air-gapped system, end to end

This ties Parts 1–3 together into one checklist. `docs/AIRGAPPED_WSL2_DOCKER_CLONE_20260921.md` already covers the WSL2/Docker-CE cloning mechanics in detail — this is the updated, complete version incorporating everything learned since that doc was written.

1. **Clone the WSL2 + Docker CE environment** (not rebuild from scratch) — export the bare distro (Ubuntu + Docker CE + nvidia-container-toolkit, no application images baked in) from an internet-connected machine, `wsl --import` it on the air-gapped box. See `docs/AIRGAPPED_WSL2_DOCKER_CLONE_20260921.md` for the exact commands.

2. **Set `.wslconfig` completely, including the fixes from this session** — not just mirrored networking:
   ```ini
   [wsl2]
   networkingMode=mirrored
   vmIdleTimeout=-1
   ```
   Missing `vmIdleTimeout=-1` is exactly what caused hours of apparent "random crash-looping" this session that had nothing to do with the actual application.

3. **Re-check network category and firewall rules after every `wsl --shutdown`** — not a one-time setup step. See `docs/AIRGAPPED_WSL2_DOCKER_CLONE_20260921.md` step 7 and `docs/WINDOWS_LAN_NETWORKING_FIX_20260921.md`'s second gotcha.

4. **Hold a persistent keep-alive session** (`wsl -d <distro> -- sleep 999999`) for the duration of any multi-step setup/debugging work on that distro — driving it through many separate one-off commands can itself destabilize things, independent of `vmIdleTimeout`.

5. **Load the application images** (`multi-model-inference`, `spark-lean`, `ner-translate-server`) via `docker load`, transferred separately from the bare distro export — see `docs/AIRGAPPED_WSL2_DOCKER_CLONE_20260921.md` step 5b.

6. **Check whether the GPU fix is even needed** (RTX 5070/5060/Blackwell: yes; RTX 6000 Ada: probably not) before patching anything — Part 1 §3 / Part 3 above.

7. **If needed, patch the GPU fix in via pre-downloaded wheels**, not a live internet-connected `pip install` — Part 3 above.

8. **For `ner_translate` specifically**: transfer the code tarball, weights tarball (~4.5GB, GLiNER + NLLB), and both images separately (never baked into either image) per `docs/WAITER_KITCHEN_NER_TRANSLATE_DEPLOYMENT.md`. Add the GPU device reservation to `deploy/docker-compose.ner_translate_server.yml` (Part 1 §5) if you want the kitchen to actually use the GPU — it's not there by default currently.

9. **Verify with `deploy/scripts/setup_ner_translate_server.sh`** before assuming anything's wired correctly — it validates the whole on-disk layout and both images exist, with a specific `[MISSING]` message for whatever's missing rather than a container silently starting against an empty mount.
