"""
build_airgap_deps_pdf.py - docs/AIRGAP_DEPENDENCIES_AND_VERSIONS.pdf

What has to be carried into the air gap, the exact versions (read from the built
images by collect_inventory.py -> inventory.json), and how dependencies are managed
and updated on both sides of the gap.

    python docs/airgap/collect_inventory.py        # refresh the inventory first
    python docs/airgap/build_airgap_deps_pdf.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "docs", "runbook"))

from reportlab.platypus import Spacer  # noqa: E402

from build_ner_runbook_pdfs import S as STY, Doc  # noqa: E402

STY["note"].spaceBefore = STY["warn"].spaceBefore = 12
STY["h1"].keepWithNext = 1
OUT = os.path.join(REPO, "docs", "AIRGAP_DEPENDENCIES_AND_VERSIONS.pdf")
INV = json.load(open(os.path.join(HERE, "inventory.json"), encoding="utf-8"))
IMG = INV["images"]
MMI, LEAN, WRK, SRV, HDP = ("multi-model-inference:latest", "spark-lean:latest", "ner-translate-worker:latest",
                            "ner-translate-server:latest", "apache/hadoop:3.4.1")


def norm(name):
    return name.lower().replace("_", "-")


PIP = {k: {norm(n): v for n, v in i.get("pip", {}).items()} for k, i in IMG.items()}


def gb(n):
    return f"{n / 1e9:,.2f} GB"


def pv(image, pkg):
    return PIP.get(image, {}).get(norm(pkg), "-")


def short(s, n=60):
    return s if len(s) <= n else s[:n - 3] + "..."


d = Doc()
d.story.append(Spacer(1, 26))
d.P("Air-Gap Dependencies: What to Carry, Versions, and Dependency Management", "title")
d.P("Everything the platform needs on the far side of the air gap - host software, container images, model weights, offline build "
    "bundles and code - with the exact versions inside every image, and how those versions are controlled and updated.", "sub")
d.note(f"Versions are read from the built images themselves (docs/airgap/collect_inventory.py, collected {INV['collected']}), "
       "not from requirement files: requirement files say what was asked for, the images show what was actually installed. "
       "The same script writes docs/airgap/AIRGAP_BILL_OF_MATERIALS.csv (one row per shipped component) - run it again before "
       "every transfer, and inside the gap to prove the images arrived unchanged. This document supersedes docs/air_gapped_dep.md, "
       "which still describes CUDA 12.1, PyTorch 2.2 and a 4 GB image.")
d.P("**Contents**", "h3")
for i, t in enumerate(["What to carry - the checklist", "What each node needs", "Platform versions per image", "Python packages and why they are pinned",
                       "System packages (.deb bundle)", "Model weights", "Version compatibility rules", "Dependency management",
                       "Packaging, transfer and verification", "Risks found in this inventory", "Appendix A - every Python package per image",
                       "Appendix B - .deb bundle", "Appendix C - model file checksums"], 1):
    d.P(f"{i}. {t}", "small")
d.brk()

# ================================================================== 1
d.H("1. What to carry - the checklist")
w = INV["weights"]
wsize = {f: sum(x["bytes"] for x in w if x["file"].startswith(f)) for f in ("gliner-multi", "nllb-200-distilled-600M", "hf_cache")}
d.table([["#", "item", "form", "size", "needed on", "changes when"],
         ["1", "Host software: Docker Engine + Compose v2 plugin, NVIDIA driver, NVIDIA Container Toolkit", "OS packages / installers (installed "
          "before the gap, or carried as .deb / .rpm / .run)", "varies", "every node (driver + toolkit: GPU nodes)", "rarely"],
         ["2", f"spark-lean image", "docker save .tar.gz", gb(IMG[LEAN]["size_bytes"]), "Spark nodes, service mode", "Spark / Python change"],
         ["3", "ner-translate-server image (the kitchen)", "docker save .tar.gz", gb(IMG[SRV]["size_bytes"]), "GPU model-server node", "any kitchen dependency change"],
         ["4", "ner-translate-worker image", "docker save .tar.gz", gb(IMG[WRK]["size_bytes"]), "Spark nodes, cluster mode", "NER dependency change (or rebuild inside, row 8)"],
         ["5", "multi-model-inference image", "docker save .tar.gz", gb(IMG[MMI]["size_bytes"]), "tensor-model nodes; the base for rebuilding row 4 inside the gap", "torch / CUDA / core change"],
         ["6", "apache/hadoop:3.4.1 image", "docker save .tar.gz", gb(IMG[HDP]["size_bytes"]), "HDFS nodes (unless an HDFS cluster exists)", "rarely"],
         ["7", "Model weights: gliner-multi, nllb-200-distilled-600M, hf_cache", "folders -> HDFS /models/weights or the master's shared folder",
          f"{gb(sum(wsize.values()))} (gliner {gb(wsize['gliner-multi'])})", "HDFS / master once; node caches fill themselves", "new model version"],
         ["8", "Offline build bundles: wheels/ner_translate (pip wheelhouse), debs/ner_translate (50 .deb files)", "folders",
          "wheelhouse several GB (includes a transitively pulled torch / CUDA wheel set); debs 23 MB", "the build host inside the gap", "NER requirements / apt list change"],
         ["9", "Platform code: the repository without weights, wheels, debs", "tar.gz", "a few MB", "every node (mounted) or the build host", "every code change"],
         ["10", "YOLO weights yolov8n.pt / yolov8s.pt - only if the YOLO models are used", "files next to the code or at weights_path", "6 MB / 22 MB",
          "tensor-model nodes", "rarely"],
         ["11", "Checksums (SHA256SUMS) + AIRGAP_BILL_OF_MATERIALS.csv", "text files", "KB", "the receiving side", "every transfer"],
         ["12", "Optional: Triton image, the Django backend's Python packages (Django >= 4.2, Celery)", "image / wheelhouse", "-", "if used", "-"]],
        [6, 50, 36, 24, 34, 24])
d.P("Image sizes are the images' content size (docker image inspect; close to `docker save` output before gzip). `docker images` on "
    "the laptop reports the unpacked size on disk, which is larger: 27.7 / 2.2 / 28.1 / 9.3 / 3.3 GB. ner-translate-worker is built "
    "on multi-model-inference, so saving both in **one** `docker save` stores the shared layers once.", "small")
d.note("**Two gaps in what the repository ships today.** (1) wheels/ner_translate is empty in this checkout: the wheelhouse the "
       "images were built from lives on the build host only. Archive it with every release, or the worker image cannot be rebuilt "
       "inside the gap. (2) No image contains the YOLO weights. Offline, `yolov8_nano` / `yolov8_small` try to download "
       "yolov8n.pt / yolov8s.pt, fail, and **silently** fall back to a stand-in CNN that returns meaningless boxes. Carry the .pt "
       "files and pass weights_path, or leave the YOLO models out.", warn=True)

# ================================================================== 2
d.H("2. What each node needs")
d.table([["node role", "images", "host software", "data / models", "notes"],
         ["Spark master + driver (service mode)", "spark-lean", "Docker", "shared data mount", "the driver never imports torch"],
         ["Spark worker (service mode)", "spark-lean", "Docker", "shared data mount", "executors only POST file paths"],
         ["GPU model server (kitchen)", "ner-translate-server", "Docker, NVIDIA driver, Container Toolkit", "shared data mount; model cache disk >= 5 GB",
          "fetches models from HDFS on first start"],
         ["Spark master / worker (cluster mode)", "ner-translate-worker", "Docker (+ NVIDIA stack on GPU workers)", "shared data; model cache per node",
          "every executor loads the models"],
         ["tensor-model cluster", "multi-model-inference", "Docker (+ NVIDIA stack on GPU workers)", "optional YOLO weights", "torchvision weights are baked in"],
         ["HDFS namenode / datanodes", "apache/hadoop:3.4.1", "Docker", "the model weights (put once)", "or use an existing HDFS"],
         ["build host inside the gap (optional)", "multi-model-inference (base)", "Docker with BuildKit", "wheelhouse, .deb bundle, code",
          "rebuilds ner-translate-worker offline"],
         ["backend (Django gateway)", "none", "Python >= 3.10, Django >= 4.2, docker CLI or ssh client", "shared data mount", "see integrations/django/README.md"]],
        [36, 30, 40, 38, 30])

# ================================================================== 3
d.H("3. Platform versions per image")
rows = [["", "multi-model-inference", "spark-lean", "ner-translate-worker", "ner-translate-server", "apache/hadoop"]]
for label, key in (("OS", "os"), ("Python", "python"), ("Java", "java"), ("Spark", "spark"), ("Hadoop", "hadoop"),
                   ("torch / CUDA / cuDNN", "torch"), ("tesseract", "tesseract"), ("OCR languages", "tesslangs")):
    row = [label]
    for k in (MMI, LEAN, WRK, SRV, HDP):
        v = IMG[k].get(key, "") or "-"
        if "not found" in v:
            v = "-"
        v = v.replace("openjdk version ", "OpenJDK ").replace("(git revision fd86f85e181) built for Hadoop 3.3.4", "(Hadoop 3.3.4 client)")
        if key == "torch" and v != "-":
            t, c, n = v.split()
            v = f"{t} / {c} / {int(n) // 10000}.{int(n) // 100 % 100}.{int(n) % 100}"
        if key == "python" and "Python 2" in v:
            v = "2.7 (system only)"
        row.append(short(v, 64))
    rows.append(row)
rows.append(["pip packages / dpkg packages"] + [f"{len(IMG[k].get('pip', {}))} / {IMG[k].get('dpkg') or '-'}" for k in (MMI, LEAN, WRK, SRV, HDP)])
rows.append(["image ID (short)"] + [IMG[k]["id"][7:19] for k in (MMI, LEAN, WRK, SRV, HDP)])
rows.append(["built"] + [IMG[k]["created"][:10] for k in (MMI, LEAN, WRK, SRV, HDP)])
d.table(rows, [30, 30, 28, 30, 30, 26])
d.P("GPU code in the torch build of all three torch images: sm_50, sm_60, sm_70, sm_75, sm_80, sm_86, sm_90 (Maxwell to Hopper; the "
    "laptop's GTX 1650 is sm_75, a T4 sm_75, an A100 sm_80, an H100 sm_90). There is no sm_100 / sm_120: Blackwell GPUs such as the "
    "RTX 50 series need a torch build for CUDA 12.8 or later. glibc: 2.35 in the Ubuntu images, 2.36 in the kitchen (Debian 12). All "
    "images are linux/amd64.", "small")
d.P(f"Build host used for this inventory: Docker {INV['host'].get('docker')}, Compose {INV['host'].get('compose')}, GPU / driver "
    f"{INV['host'].get('nvidia')}.", "small")

# ================================================================== 4
d.H("4. Python packages and why they are pinned")
key_pkgs = [("pyspark", "must equal the Spark version (3.5.1) on every node"), ("py4j", "ships with pyspark 3.5.1"),
            ("torch", "cu126 wheel from download.pytorch.org, installed by the Dockerfile (not requirements.txt)"),
            ("torchvision", "installed together with torch; pinning it in requirements.txt once downgraded torch to 2.2"),
            ("numpy", "2.x; core requirements pin 2.1.3 - the kitchen resolves it unpinned (see section 10)"),
            ("pandas", "core, for Spark / Arrow"), ("pyarrow", "18.1.0; imported before torch in the NER module (OpenMP/MKL clash)"),
            ("transformers", "4.45.2: 4.57.x breaks loading the GLiNER tokenizer (list vs dict special tokens)"),
            ("tokenizers", "transitive, follows transformers"), ("gliner", "0.2.13, developed against transformers 4.45"),
            ("sentencepiece", "0.2.2: the first with a manylinux_2_28 wheel"), ("tiktoken", "0.12.0: same wheel-tag reason; tokenizer conversion needs it or protobuf"),
            ("protobuf", "5.29.3: needed to convert GLiNER's tokenizer"), ("onnxruntime", "1.30.0: older (1.16) crashes with numpy 2 (ABI)"),
            ("huggingface-hub", "transitive (gliner / transformers); hf-xet forced into the wheelhouse"), ("safetensors", "transitive; GLiNER loads model.safetensors"),
            ("py3langid", "0.4.0, needs numpy >= 2"), ("pillow", "11.0.0 pinned by NER (the base resolves 12.x, the NER install downgrades it)"),
            ("pytesseract", "0.3.13 - calls the tesseract binary"), ("pypdf", "5.1.0"), ("pdf2image", "1.17.0 - needs poppler-utils"),
            ("fastapi", "0.121.2 - the kitchen"), ("uvicorn", "0.38.0 - the kitchen"), ("requests", "the lean executors' HTTP client"),
            ("ultralytics", "8.3.40 - YOLO; pulls opencv-python and scipy unpinned"), ("opencv-python", "transitive via ultralytics (unpinned)"),
            ("nvidia-cudnn-cu12", "CUDA runtime libraries arrive as pip packages with torch"), ("nvidia-cublas-cu12", "same"),
            ("triton", "OpenAI Triton compiler used by torch, not the Triton server"), ("boto3", "S3 upload of results on AWS only")]
rows = [["package", "multi-model-inference", "spark-lean", "ner-translate-worker", "ner-translate-server", "why this version / note"]]
for p, why in key_pkgs:
    rows.append([p, pv(MMI, p), pv(LEAN, p), pv(WRK, p), pv(SRV, p), why])
d.table(rows, [24, 22, 16, 22, 22, 68], mono=(1, 2, 3, 4))
d.P("Where the pins live: requirements.txt (core, installed in the base image), models/pipelines/ner_translate/requirements.txt (the "
    "pipeline's own, installed in both NER images), and the Dockerfiles (torch, torchvision, pyspark and requests for the lean image). "
    "The full list of every package in every image is Appendix A.", "small")

# ================================================================== 5
d.H("5. System packages (.deb bundle)")
d.P(f"debs/ner_translate holds {len(INV['debs'])} .deb files (23 MB): tesseract-ocr 4.1.1, 12 language data packages "
    "(the 11 OCR languages + osd), poppler-utils 22.02 and their full dependency closure, downloaded **from inside "
    "multi-model-inference:latest** so each version matches what is already installed in that image (a fresh ubuntu:22.04 once "
    "resolved a newer libgomp1 than the image's gcc-12-base and dpkg refused to configure it). Appendix B lists every package and version.")
d.P("The kitchen image does not use this bundle: it installs tesseract 5.3.0 and poppler from Debian 12's apt repositories at build "
    "time (see section 10).", "small")

# ================================================================== 6
d.H("6. Model weights")
big = [x for x in w if x["bytes"] > 1_000_000]
rows = [["file", "size", "SHA-256 (first 16)", "needed?"]]
for x in big:
    need = "no - GLiNER loads model.safetensors" if x["file"].endswith("gliner-multi/pytorch_model.bin") else "yes"
    rows.append([x["file"].replace("models--microsoft--mdeberta-v3-base/blobs/", "mdeberta blobs/")[:70], f"{x['bytes'] / 1e6:,.1f} MB", x["sha256"][:16], need])
d.table(rows, [88, 20, 34, 32], mono=(0, 2))
small = [x for x in w if x["bytes"] <= 1_000_000]
d.P(f"Plus {len(small)} small files (configs, tokenizer files, the Hugging Face cache's refs and symlinks). Full checksums: Appendix C.", "small")
d.table([["model", "source (Hugging Face)", "used by", "licence (check the model card)"],
         ["gliner-multi", "urchade/gliner_multi-v2.1", "entity extraction", "Apache-2.0 per its model card"],
         ["nllb-200-distilled-600M", "facebook/nllb-200-distilled-600M", "translation to English", "CC-BY-NC-4.0 - non-commercial; clear it for your use"],
         ["hf_cache", "microsoft/mdeberta-v3-base, snapshot a0484667... (config + tokenizer only)", "GLiNER's backbone definition", "MIT"],
         ["torchvision checkpoints (baked in the image)", "resnet18-f37072fd, mobilenet_v3_small-047dcff4, efficientnet_b0_rwightman-7f5810bc", "image models", "BSD-3 (torchvision)"],
         ["yolov8n.pt / yolov8s.pt (not shipped)", "Ultralytics", "YOLO models", "AGPL-3.0 (Ultralytics) - check before shipping"]],
        [34, 60, 30, 50])
d.P("Where they go: once into HDFS (`hdfs dfs -put gliner-multi nllb-200-distilled-600M hf_cache /models/weights/`) or the master's "
    "shared folder; nodes fetch them into their local cache on first use (models/model_store.py). A new model version goes into a new "
    "HDFS folder and MODEL_STORE_URI points at it - old and new caches coexist.", "small")

# ================================================================== 7
d.H("7. Version compatibility rules")
d.table([["must match", "rule", "what breaks otherwise"],
         ["NVIDIA driver vs CUDA runtime (12.6)", ">= 525.60.13 works through CUDA 12 minor-version compatibility; >= 560.28 is the native 12.6 requirement (recommended)",
          "torch.cuda.is_available() False / CUDA init errors"],
         ["GPU compute capability", "sm_50-sm_90 (section 3)", "'no kernel image is available for execution on the device'"],
         ["Python minor version, driver = executors", "3.11 everywhere (the images guarantee it)", "PYTHON_VERSION_MISMATCH - seen on a Windows host with 3.12 + 3.10"],
         ["pyspark = Spark", "3.5.1 on the driver and in every executor image", "Py4J / protocol errors"],
         ["Java for Spark", "17 (images); Spark 3.5 supports 8 / 11 / 17", "JVM start failures"],
         ["torch = torchvision pair", "2.6.0 + 0.21.0, both cu126", "import errors / silent torch downgrade"],
         ["transformers vs gliner", "4.45.2 with gliner 0.2.13", "GLiNER tokenizer load fails ('list' object has no attribute 'keys')"],
         ["numpy 2 ABI", "onnxruntime >= 1.17 (1.30.0), pyarrow 18, py3langid 0.4", "'_ARRAY_API not found' at import"],
         ["wheel platform tags", "manylinux2014 / manylinux_2_28 wheels need glibc >= 2.17 / 2.28 (images have 2.35 / 2.36)", "pip: no matching distribution (offline)"],
         ["driver and all workers, same wheels", "identical images, or identical wheels-hotfix contents on every node", "different results or unpickling errors between driver and executors"],
         ["kitchen vs worker (NER)", "same model files; OCR differs today (tesseract 5.3 vs 4.1)", "different OCR text for scanned documents between modes"]],
        [42, 74, 58])

# ================================================================== 8
d.brk()
d.H("8. Dependency management")
d.H("8.1 Who owns which dependency", 2)
d.img("docker_image_tree", "Figure 1 - image layering: each layer owns its own dependencies", maxh=86)
d.B(["**requirements.txt** - the core set for every tensor model (pyspark, numpy, pandas, pyarrow, ultralytics, ...). Installed only "
     "in the base image. Pipelines never add to it: one pipeline's dependency once silently changed a version every other model relied on.",
     "**models/pipelines/<name>/requirements.txt** - one pipeline's own packages, installed in that pipeline's images only. It must not "
     "re-pin what the base provides (torch, numpy, pandas), except where the kitchen, which has no base, needs it listed.",
     "**The Dockerfiles** - torch / torchvision (from the CUDA wheel index), Java, Spark, OS packages.",
     "**Model weights** - never in an image (except the three small torchvision checkpoints): they live in the model store."])
d.H("8.2 Building offline-capable images", 2)
d.table([["step", "command / mechanism", "why"],
         ["1 wheelhouse", "bash deploy/scripts/build_ner_translate_wheelhouse.sh -> wheels/ner_translate",
          "pip download for the container (--platform manylinux2014_x86_64 and manylinux_2_28_x86_64, --python-version 311, --only-binary), "
          "sdist-only odfpy / ebooklib downloaded separately, their real deps (defusedxml, lxml, six) and hf-xet forced in - the "
          "environment markers are evaluated for the build host, not the container"],
         ["2 .deb bundle", "bash deploy/scripts/build_ner_translate_debs.sh -> debs/ner_translate",
          "apt --download-only inside multi-model-inference itself, so versions match the installed base"],
         ["3 build", "docker build -t ner-translate-worker:latest -f deploy/Dockerfile.ner_translate .",
          "pip install --no-index --find-links (fails loudly if a pin is missing) and dpkg -i twice; both bundles bind-mounted, never COPY'd, "
          "so they are not shipped as image layers"],
         ["4 inventory", "python docs/airgap/collect_inventory.py", "records what the images really contain (this document)"]],
        [22, 64, 88])
d.H("8.3 What can be rebuilt inside the gap", 2)
d.table([["image", "rebuild inside the gap?", "what it needs"],
         ["ner-translate-worker", "yes", "multi-model-inference already loaded + wheels/ner_translate + debs/ner_translate + code"],
         ["multi-model-inference, spark-lean", "no", "ubuntu:22.04, the deadsnakes PPA, apt, the Spark tarball from archive.apache.org, "
          "download.pytorch.org and PyPI - rebuild outside and carry the image"],
         ["ner-translate-server", "no", "Debian apt mirrors and download.pytorch.org at build time; no hotfix hook - carry a new image for any change"],
         ["apache/hadoop", "no (pulled)", "carry the image"]], [36, 34, 104])
d.H("8.4 Updating inside the gap - what to carry for each kind of change", 2)
d.table([["change", "carry", "then"],
         ["platform code (inference/, models/, submit_*.py)", "code tar.gz (MB)", "extract to the mounted folder on every node; restart containers"],
         ["new model version", "the model folder", "hdfs dfs -put to a new folder; point MODEL_STORE_URI at it"],
         ["one NER Python package (urgent)", "the .whl files", "wheels-hotfix/ner_translate on every node, restart (worker image only)"],
         ["NER Python packages (planned)", "new wheelhouse", "rebuild ner-translate-worker offline (8.2 step 3)"],
         ["OCR / system packages for the worker", "new .deb bundle", "rebuild ner-translate-worker offline"],
         ["kitchen dependencies", "new ner-translate-server image", "docker load on the GPU node"],
         ["torch / CUDA / Python / Java / Spark / core packages", "new images", "docker load on every node; rebuild the worker FROM the new base"]],
        [52, 40, 82])
d.P("wheels-hotfix: deploy/apply_wheels_hotfix.sh runs at start in the ner-translate-worker containers and installs any .whl in the "
    "/wheels-hotfix mount. It is for one urgent fix without a rebuild. The same wheels must be on every node, because a driver and "
    "executors with different package versions is a real failure mode. Fold the fix into the wheelhouse at the next release.", "small")
d.H("8.5 Recommended: lock the transitive versions", 2)
d.P("Direct dependencies are pinned, but their dependencies are resolved at build time and drift between builds. This inventory "
    "shows it: numpy is 2.1.3 in the worker but 2.4.6 in the kitchen; ultralytics pulls opencv-python and scipy unpinned. To make a "
    "rebuild reproduce exactly what was tested, freeze each tested image and build with the result as a constraints file:")
d.code("docker run --rm --entrypoint python3 ner-translate-server:latest -m pip freeze \\\n"
       "    > constraints/ner-translate-server.txt\n"
       "docker run --rm --entrypoint python3 multi-model-inference:latest -m pip freeze \\\n"
       "    > constraints/multi-model-inference.txt\n"
       "# in the Dockerfiles / wheelhouse script:  pip install ... -c constraints/<image>.txt\n"
       "# and pin numpy==2.1.3 in models/pipelines/ner_translate/requirements.txt so both NER images agree")

# ================================================================== 9
d.H("9. Packaging, transfer and verification")
d.code("# ---- outside (connected build host) ----\n"
       "python docs/airgap/collect_inventory.py                               # inventory.json + BILL_OF_MATERIALS.csv\n"
       "# one save for both torch images: their shared layers are stored once\n"
       "docker save multi-model-inference:latest ner-translate-worker:latest | gzip > spark-torch-images.tar.gz\n"
       "docker save spark-lean:latest            | gzip > spark-lean.tar.gz\n"
       "docker save ner-translate-server:latest  | gzip > ner-translate-server.tar.gz\n"
       "docker save apache/hadoop:3.4.1          | gzip > hadoop.tar.gz\n"
       "tar czf models-weights.tar.gz -C <weights dir> gliner-multi nllb-200-distilled-600M hf_cache\n"
       "tar czf build-bundles.tar.gz wheels/ner_translate debs/ner_translate\n"
       "tar czf platform-code.tar.gz --exclude=models/weights --exclude=wheels --exclude=debs \\\n"
       "        --exclude=results --exclude=.git .\n"
       "sha256sum *.tar.gz docs/airgap/AIRGAP_BILL_OF_MATERIALS.csv > SHA256SUMS\n\n"
       "# ---- inside ----\n"
       "sha256sum -c SHA256SUMS                                  # every file intact\n"
       "for f in *images*.tar.gz spark-lean.tar.gz ner-translate-server.tar.gz hadoop.tar.gz; do docker load -i $f; done\n"
       "docker image inspect --format '{{.Id}}' spark-lean:latest   # = the ID in the bill of materials\n"
       "python docs/airgap/collect_inventory.py --no-hash        # diff inventory.json against the one carried in")
d.table([["check inside the gap", "command", "expected"],
         ["GPU reachable from containers", "docker run --rm --gpus all --entrypoint nvidia-smi ner-translate-server:latest", "the GPU and driver listed"],
         ["torch + CUDA", "docker run --rm --gpus all --entrypoint python3 ner-translate-server:latest -c \"import torch;print(torch.cuda.is_available())\"", "True"],
         ["NER packages", "... -c \"import gliner, transformers;print(gliner.__version__, transformers.__version__)\"", "0.2.13 4.45.2"],
         ["OCR languages", "docker run --rm --entrypoint tesseract ner-translate-server:latest --list-langs", "12 entries (11 + osd)"],
         ["Spark", "docker run --rm spark-lean:latest cat /opt/spark/RELEASE", "Spark 3.5.1"],
         ["models in HDFS", "hdfs dfs -du -s -h /models/weights/*", "sizes as in section 6"],
         ["end to end", ".\\deploy\\airgap_sim_tests.ps1 (simulation) or one submit_pipeline_job.py run", "all tests PASS / 6 documents processed"]],
        [36, 94, 44], mono=(1,))

# ================================================================== 10
d.H("10. Risks found in this inventory")
d.table([["risk", "evidence", "recommendation"],
         ["NER images disagree on numpy", f"worker {pv(WRK, 'numpy')}, kitchen {pv(SRV, 'numpy')}", "pin numpy==2.1.3 in the NER requirements; constraints files (8.5)"],
         ["OCR engine differs between modes", f"worker tesseract {IMG[WRK].get('tesseract', '').split()[-1]}, kitchen {IMG[SRV].get('tesseract', '').split()[-1]}",
          "build the kitchen from the same Ubuntu base + .deb bundle, or accept and document the difference"],
         ["kitchen image cannot be rebuilt offline, has no hotfix hook", "Dockerfile.ner_translate_server: apt + download.pytorch.org at build",
          "base it on a local image + wheelhouse like the worker, or plan to carry a new image per change"],
         ["wheelhouse not archived with the code", "wheels/ner_translate empty in this checkout", "archive wheels/ + debs/ with each release"],
         ["YOLO weights missing", "no image contains yolov8n.pt / yolov8s.pt; silent fallback CNN", "carry the .pt files or exclude the YOLO models"],
         ["unpinned transitive dependencies", f"opencv-python {pv(MMI, 'opencv-python')}, scipy {pv(MMI, 'scipy')} via ultralytics", "constraints files (8.5)"],
         ["plain docker build gives the wrong image", "Dockerfile default target is lean", "build with --target final (see DOCKER_CONTAINERS_AND_COMPOSE.pdf)"],
         ["1.2 GB of unused weights", "gliner-multi/pytorch_model.bin never read", "leave it out of HDFS and the transfer"],
         ["licences", "NLLB-200 is CC-BY-NC-4.0; Ultralytics is AGPL-3.0", "clear with your legal / security team before deployment"],
         ["no Blackwell support", "torch arch list ends at sm_90", "choose sm_90-or-older GPUs, or rebuild with a CUDA 12.8+ torch"]],
        [44, 62, 68])

# ================================================================== appendices
d.brk()
d.H("Appendix A - every Python package per image")


def pkg_table(pkgs, cols=3):
    items = [f"{n}=={v}" for n, v in sorted(pkgs.items())]
    rows = [[""] * cols]
    per = (len(items) + cols - 1) // cols
    for r in range(per):
        rows.append([items[c * per + r] if c * per + r < len(items) else "" for c in range(cols)])
    rows[0] = ["package==version"] + [""] * (cols - 1)
    d.table(rows, [174 / cols] * cols, mono=tuple(range(cols)))


for title, image, only_new in ((f"multi-model-inference ({len(PIP[MMI])} packages)", MMI, False),
                               (f"spark-lean ({len(PIP[LEAN])} packages)", LEAN, False),
                               ("ner-translate-worker - packages added or changed on top of multi-model-inference", WRK, True),
                               (f"ner-translate-server ({len(PIP[SRV])} packages)", SRV, False)):
    d.H(title, 2)
    pk = PIP[image]
    if only_new:
        pk = {n: v for n, v in pk.items() if PIP[MMI].get(n) != v}
    pkg_table(pk)

d.H("Appendix B - .deb bundle (debs/ner_translate)")
debs = [(x.split("_")[0], x.split("_")[1].replace("%3a", ":")) for x in INV["debs"]]
rows = [["package", "version", "package", "version"]]
half = (len(debs) + 1) // 2
for i in range(half):
    a = debs[i]
    b = debs[i + half] if i + half < len(debs) else ("", "")
    rows.append([a[0], a[1], b[0], b[1]])
d.table(rows, [40, 47, 40, 47], mono=(0, 1, 2, 3))

d.H("Appendix C - model file checksums")
def shortpath(f):
    f = f.replace("hf_cache/models--microsoft--mdeberta-v3-base/", "hf_cache/<mdeberta>/")
    for rev in ("a0484667b22365f84929a935b5e50a51f71f159d",):
        f = f.replace(rev, "a0484667..")
    parts = f.split("/")
    return "/".join(p if len(p) <= 24 else p[:12] + ".." + p[-8:] for p in parts)


rows = [["file", "bytes", "SHA-256"]]
for x in w:
    if x.get("symlink"):
        rows.append([shortpath(x["file"]), "symlink", "points to one of the blobs (Hugging Face cache layout)"])
    elif x["bytes"] == 0:
        rows.append([shortpath(x["file"]), "0", "empty marker file (lock / no-exist entry)"])
    else:
        rows.append([shortpath(x["file"]), f"{x['bytes']:,}", x["sha256"]])
d.table(rows, [58, 20, 96], mono=(0, 2))
d.P(f"Weights folder hashed: {INV['weights_root']}. Verify on the far side with `sha256sum` against these values or the bill of materials.", "small")

d.build(OUT, "Air-gap dependencies and versions")
