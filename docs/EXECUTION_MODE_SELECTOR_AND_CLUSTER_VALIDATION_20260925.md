# Execution-Mode Selector + Real 2-Machine Cluster Validation (2026-09-25)

Follow-up session to `docs/COMPLETE_ARCHITECTURE_TESTING_AND_AIRGAPPED_GUIDE_20260921.md`: added an explicit user-facing execution-mode selector to `submit_pipeline_job.py`, synced the worker machine with everything needed to run every mode, and validated the full test matrix — RDD, pandas UDF, CUDA streams (distributed GPU), and `ner_translate` — on the real 2-machine cluster with the actual GPU worker doing actual GPU work.

---

## What changed in code

### `submit_pipeline_job.py` — new `--execution-mode` flag

Before this change, `submit_pipeline_job.py` only **auto-detected** whether to run a pipeline via the HTTP waiter/kitchen path (Option B, `docs/MODEL_CONTAINER_ISOLATION.md`) or in-process on the Spark cluster (Option A) — based purely on whether the manifest's `service_url` hostname happened to resolve from wherever the driver process was running. That's an implicit, network-topology-dependent decision, not something a user could deliberately choose.

Added:

```bash
python submit_pipeline_job.py --pipeline ner_translate --input <path> \
  --execution-mode {auto,service,cluster} --master <spark-url>
```

- **`service`**: force the HTTP kitchen path. Errors out clearly if the pipeline has no `service_url` in its manifest, rather than silently falling back.
- **`cluster`**: force in-process execution (`mod.load()`/`mod.run()` inside every Spark executor) on whatever cluster `--master` points at — independent of whether a kitchen server also happens to be reachable from there. This is what makes it possible to run a pipeline on the *main, bigger* Spark cluster instead of only its own small dedicated one.
- **`auto`** (default): unchanged behavior, for backward compatibility.

This is the direct answer to "give the option for the user to select methodology to run, whether they want to run in ner server or spark cluster."

---

## Getting the worker ready for all modes

The worker (`192.168.4.101`) had drifted since the last session (days had passed, its Spark registration had lapsed, and its `multi-model-inference:latest` image was exactly as stale as the master's was — see `docs/COMPLETE_ARCHITECTURE_TESTING_AND_AIRGAPPED_GUIDE_20260921.md` §3.5 for the stale-image gap list). To run every mode on the real cluster, the worker needed:

1. **`spark-gpu-worker` container reconnected** to `spark://192.168.4.104:7077`, with `--gpus all`.
2. **Same code patches as the master**: `submit_job.py`, `inference/cluster_engine.py` (the fixed version with the plugin-merge line), `inference/cluster_engine_udf.py`, `inference/predict_batch_udf.py`, `inference/text_pipeline_engine.py`, `models/plugin_loader.py`, `models/plugins/`, `models/pipelines/` (ner_translate).
3. **ner_translate's system + Python dependencies** — tesseract-ocr + language packs + poppler-utils (apt), gliner/transformers/sentencepiece/etc. (pip) — installed directly from the internet (this machine has it; see `docs/SESSION_SUMMARY_AND_AIRGAPPED_UPDATE_GUIDE_20260921.md` Part 3 for the air-gapped equivalent using pre-downloaded wheels instead).
4. **The GPU fix**: `torch==2.9.1+cu128`/`torchvision==0.24.1` (same confirmed-working pin from earlier in this session).
5. **Model weights** (GLiNER + NLLB, ~3.5GB) and **sample data** (`data/ner_samples/`) — copied directly into the container.

Transfer mechanism: small code/data as a zip, weights as a `tar.gz`, both served over plain HTTP from the master (`python3 -m http.server 8123` inside the master's WSL2 Ubuntu distro) and pulled with `curl` from the worker — same pattern established earlier this session for moving large files across the LAN, chosen specifically because it sidesteps the Windows SMB authentication issues hit earlier (`docs/LIVE_CLUSTER_TEST_20260921.md`).

A full, current copy of the repo (minus `wheels/`/`models/weights` for size, 22.5MB) was also transferred to the worker's own filesystem (`C:\spark-inference\repo`), separate from what's inside the container — useful for anything beyond just the container patches.

---

## Full real-cluster test matrix — all modes, all confirmed working

Every test below ran against `spark://192.168.4.104:7077` (the real 2-machine cluster), not `local[4]` and not a single-machine kitchen-only setup.

| Test | How to run | Result | Notes |
|---|---|---|---|
| **RDD engine** | `submit_job.py --model example_mlp --engine rdd --master spark://192.168.4.104:7077` | 5,000 samples, **1,715.7/s**, 2.9s | Counts only, no per-sample output (by design) |
| **Pandas UDF engine** | `submit_job.py --model example_mlp --engine udf --master spark://192.168.4.104:7077` | 5,000 samples, **940.4/s**, 5.3s | Returns real per-sample predictions (4-class logits) — 675KB result file vs. RDD's 320B for the identical input |
| **CUDA streams, distributed, `gpu_only`** | `cluster_benchmark.py --device-mode gpu_only --partitions 2 ...` | 5,190 samples, **466/s**, 11.1s, **device=cuda** | All 10 models including ResNet18/MobileNetV3/EfficientNet-B0/YOLOv8 — the exact models that hit the `sm_120` kernel error pre-fix |
| **CUDA streams, distributed, `hybrid`** | `cluster_benchmark.py --device-mode hybrid --partitions 4 ...` | 15,360 samples, **1,278/s**, 12.0s, **device=cuda** | |
| **`ner_translate`, cluster mode** | `submit_pipeline_job.py --pipeline ner_translate --execution-mode cluster --master spark://192.168.4.104:7077` | 6 docs, **23.8s total**, 2.7s/5.7s per partition | Both partitions ran on hostname `RAPL-DSK-158` — the **worker**, confirmed via the job's own partition-detail output, not assumed |

**How "ran on the real cluster, not simulated" was actually verified**, not just claimed:
- The job's own `--master` argument pointed at the real IP, not `local[4]`.
- Partition/executor hostnames in the result JSON matched the **worker's** hostname, not the driver's.
- Spark's REST API executor metrics (`cluster_benchmark.py`'s own capture) showed the real worker IP `192.168.4.101` with real core/task/duration numbers.
- GPU runs report `device: cuda` explicitly per partition — not inferred from absence of an error.
- Timing was consistent with the already-established GPU vs. CPU baselines (e.g., `ner_translate`'s 23.8s cluster-mode run lines up with the earlier confirmed 5.86s single-doc-batch GPU baseline, not the 45.36s CPU one), not just "didn't crash."

All result files are under `results/` — see the `_cluster_` and `_20260925_` suffixed filenames for this session's runs specifically, alongside the earlier single-machine/kitchen results from 2026-09-21 for direct comparison.

---

## Air-gapped: setting up and running every mode

Builds on `docs/AIRGAPPED_WSL2_DOCKER_CLONE_20260921.md` (the WSL2/Docker CE environment itself) and `docs/SESSION_SUMMARY_AND_AIRGAPPED_UPDATE_GUIDE_20260921.md` Part 3 (the general dependency-patch-via-pre-downloaded-wheels pattern). This section is the mode-by-mode checklist on top of those.

### Prerequisites for any mode

1. Both machines (master + worker) have the WSL2 Docker CE environment set up per `docs/AIRGAPPED_WSL2_DOCKER_CLONE_20260921.md` — mirrored networking, `vmIdleTimeout=-1`, network category checked Private after every `wsl --shutdown`.
2. Both machines have `multi-model-inference:latest` loaded (`docker load`).
3. Master's Spark container running (`start-master.sh`), worker's connected (`start-worker.sh spark://<master-ip>:7077 -c 4 -m 12g --gpus all`), confirmed via `curl http://<master-ip>:8080/json/` showing `aliveworkers >= 1`.
4. **Air-gapped GPU fix, if needed** — check whether your GPU actually needs it first (Blackwell/RTX 50-series: yes; Ada/RTX 6000 Ada: probably not, per `docs/COMPLETE_ARCHITECTURE_TESTING_AND_AIRGAPPED_GUIDE_20260921.md` Part 2). If needed: pre-download `torch==2.9.1`/`torchvision==0.24.1` from the `cu128` index on an internet-connected machine, transfer the wheel files, `pip install --no-index --find-links=...` on **both** master and worker (the worker's GPU is what actually executes the work — patching only the master does nothing for GPU-mode jobs).

### RDD engine and pandas UDF engine (`example_mlp` / any tensor-plugin model)

No extra air-gapped work beyond the prerequisites — both engines only need `models/plugin_loader.py`, `models/plugins/`, and the **current, non-stale** `inference/cluster_engine.py` present on every node that runs a task (master driver + worker executor). If your image was freshly built from current source, this is already true; if it's an older/transferred image, copy these files in (a few KB, trivially small to include in even the smallest air-gapped code transfer) — this repo has no wheelhouse dependency for either engine, they use only what's already in the base image.

```bash
python submit_job.py --model example_mlp --samples 5000 --engine rdd --master spark://<master-ip>:7077
python submit_job.py --model example_mlp --samples 5000 --engine udf --master spark://<master-ip>:7077
```

### CUDA streams, distributed (`cluster_benchmark.py --device-mode gpu_only|hybrid`)

No new dependencies beyond the GPU fix above (prerequisite #4) — this mode only exercises code and models already baked into `multi-model-inference:latest`. The only air-gapped-specific concern is making sure the GPU fix is actually installed on the **worker** (where the GPU work happens), not just the master.

```bash
docker exec spark-master bash -c "SPARK_MASTER_URL=spark://<master-ip>:7077 python benchmark/cluster_benchmark.py --device-mode gpu_only --partitions 2 --signal-samples 1000 --image-samples 50 --detection-samples 20 --batch-size 128"
docker exec spark-master bash -c "SPARK_MASTER_URL=spark://<master-ip>:7077 python benchmark/cluster_benchmark.py --device-mode hybrid --partitions 4 --signal-samples 3000 --image-samples 100 --detection-samples 30 --batch-size 256"
```

### `ner_translate` — service mode (waiter/kitchen)

Follow `docs/WAITER_KITCHEN_NER_TRANSLATE_DEPLOYMENT.md`'s existing air-gapped flow exactly — it was already designed for this: transfer `spark-lean.tar.gz` + `ner-translate-server.tar.gz` (2 images), the code tarball, and the weights tarball (~4.5GB) separately, run `deploy/scripts/setup_ner_translate_server.sh` to validate the layout before starting anything.

```bash
NER_TRANSLATE_ROOT=/opt/ner-translate docker exec ner-translate-master bash -c \
  "python submit_pipeline_job.py --pipeline ner_translate --input /app/data/ner_samples --partitions 2 --execution-mode service"
```
(`--execution-mode service` here is optional/redundant since `auto` would already pick this path inside that compose network — included for explicitness.)

**For GPU-accelerated service mode**, the compose file needs the GPU device reservation added this session (`docs/COMPLETE_ARCHITECTURE_TESTING_AND_AIRGAPPED_GUIDE_20260921.md` Part 1 §5) — it's not there by default:
```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: all
          capabilities: [gpu]
```
Plus the GPU fix patched into the `ner-translate-server` image/container the same way as everywhere else.

### `ner_translate` — cluster mode (the new capability from this session)

This is the one that needs everything from "Getting the worker ready" above, air-gapped:

1. **Code** (small): `submit_pipeline_job.py`, `inference/text_pipeline_engine.py`, `models/pipelines/` — bundle into whatever code tarball you're already transferring.
2. **System deps** (tesseract + poppler): pre-stage as `.deb` files per `docs/CHANGELOG_20260913.md`'s pattern (`apt-get download <packages> --download-only`, transfer, `dpkg -i`), or bake them into the image at build time if rebuilding from source (`deploy/Dockerfile` already does this — see its apt-get install line).
3. **Python deps** (gliner/transformers/etc.): pre-stage as wheels — this repo already has a script for exactly this, `deploy/scripts/build_ner_translate_wheelhouse.sh`, producing `wheels/ner_translate/`. Transfer that directory, install with `pip install --no-index --find-links=wheels/ner_translate -r models/pipelines/ner_translate/requirements.txt` on **every node that will execute a task** — master driver AND every worker.
4. **Model weights** (~3.5GB): transfer once, mount/copy identically onto every node — `run_text_pipeline_job()`'s in-process path calls `load()` inside every executor, so every executor needs its own access to the weights, unlike service mode where only the kitchen container needs them.
5. **GPU fix**: same as prerequisite #4 above, on the worker specifically.

```bash
docker exec -w /app spark-master python submit_pipeline_job.py --pipeline ner_translate \
  --input /app/data/ner_samples --partitions 2 \
  --execution-mode cluster --master spark://<master-ip>:7077
```

**Why cluster mode costs more to set up air-gapped than service mode**: service mode's weights/deps live in exactly one place (the kitchen container) regardless of how many Spark workers exist; cluster mode needs them replicated onto every single node that might run a task. This is the real, concrete tradeoff behind the two options `docs/MODEL_CONTAINER_ISOLATION.md` describes abstractly — cluster mode buys you the ability to use the main cluster's full worker pool (and skip the HTTP hop's latency), at the cost of N× the dependency footprint instead of 1×.
