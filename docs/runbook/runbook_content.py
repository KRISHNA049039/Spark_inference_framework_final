"""Content of the two NER / cluster PDFs (see build_ner_runbook_pdfs.py)."""
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _latest_ner_result():
    import glob
    import json
    files = sorted(glob.glob(os.path.join(REPO, "results", "ner_translate_2026092[7-9]_*.json")))
    if not files:
        return None, None
    d = json.load(open(files[-1], encoding="utf-8"))
    return os.path.basename(files[-1]), d


def _mbps(log):
    m = re.findall(r"fetched (\S+) -> \S+\s+([\d.]+) MB in ([\d.]+) s \((\d+) MB/s\)", log)
    return list(dict.fromkeys(m))  # the log can repeat a line (container log + test echo)


# =================================================================== PDF 1
def build_process_pdf(Doc, path, T, ev, res):
    d = Doc()
    d.story.append(__import__("reportlab.platypus", fromlist=["Spacer"]).Spacer(1, 30))
    d.P("NER Pipeline on the Spark Cluster", "title")
    d.P("The complete process from start to stop: how the models get onto the cluster (HDFS or the master's file system), "
        "how a job is submitted and distributed, what happens to every document, and how the cluster is shut down.", "sub")
    d.note("Scope: the ner_translate pipeline (OCR -> language detection -> NLLB-200 translation -> GLiNER entity extraction) "
           "running on this platform's Spark cluster, with models held in an air-gapped HDFS cluster or on the master node's file "
           "system. Everything described was executed in the simulation of section 7 (deploy/docker-compose.airgap_sim.yml, "
           "deploy/airgap_sim_tests.ps1). Operational commands are in the companion CLUSTER_RUNBOOK_MODES_AND_TESTS.pdf.")
    d.H("Contents", 3)
    for t in ["1. The big picture", "2. The components and their roles", "3. Where the models live - the model store",
              "4. The process, phase by phase (0 build ... 7 stop)", "5. What happens to one document", "6. When things go wrong",
              "7. Measured in the simulation", "8. Glossary"]:
        d.P(t, "small")
    d.brk()

    # 1
    d.H("1. The big picture")
    d.img("ner_lifecycle", "Figure 1 - the eight phases in time order", maxh=250)
    d.P("A user points `submit_pipeline_job.py` at a folder of documents. Spark splits the list of files into partitions and "
        "hands each partition to an executor on a worker node. Each partition's documents are processed by the NER pipeline - "
        "either inside a central GPU model server (the **kitchen**, service mode) or inside the executor itself (cluster mode). "
        "The per-document results flow back to the driver and are written to one JSON file. The models themselves never live "
        "in the images: they are stored once in the cluster's HDFS (or on the master's file system) and every node that needs "
        "them fetches them into its own local cache the first time.")
    d.table([["phase", "what happens", "state it leaves behind"],
             ["0 Build", "images and model weights prepared on a connected machine", "4 images, 3 model folders (4.6 GB)"],
             ["1 Transfer", "images saved as tar files, copied with the weights across the air gap, loaded", "images on every node"],
             ["2 Store models", "gliner-multi, nllb-200-distilled-600M and hf_cache put into HDFS /models/weights (or copied to the master's shared file system)", "one authoritative copy"],
             ["3 Start services", "HDFS, then the model server (fetch -> cache -> GPU), then Spark master and workers", "warm, idle cluster"],
             ["4 Submit", "driver reads the manifest, lists files, picks master and execution mode", "SparkSession"],
             ["5 Execute", "tasks run on worker slots; documents are extracted, translated, tagged", "per-partition results"],
             ["6 Collect", "results merged on the driver, written to results/ner_translate_<time>.json", "result file"],
             ["7 Stop", "SparkSession stopped; services stopped when no more jobs are expected", "HDFS + node caches kept"]],
            [22, 95, 57])

    # 2
    d.H("2. The components and their roles")
    d.table([["component", "role", "runs where (simulation)", "image"],
             ["HDFS namenode", "keeps the file-system tree (which blocks make up which model file); answers WebHDFS requests and redirects reads to a datanode", "sim-hdfs-namenode (master storage)", "apache/hadoop:3.4.1"],
             ["HDFS datanode", "stores the 128 MB blocks of the model files and streams them", "sim-hdfs-datanode", "apache/hadoop:3.4.1"],
             ["Model store (models/model_store.py)", "turns hdfs:// or file:// model locations into a local folder; downloads once per node, caches, publishes atomically", "inside the kitchen and inside executors", "(code, stdlib only)"],
             ["Model server - 'kitchen' (serve.py)", "loads GLiNER + NLLB once on the GPU, serves POST /predict {paths}", "sim-ner-translate-server", "ner-translate-server"],
             ["Spark master", "tracks workers, grants executors to the job", "sim-spark-master / sim-ner-cluster-master", "spark-lean / ner-translate-worker"],
             ["Spark driver (submit_pipeline_job.py)", "builds the job, collects results, writes the JSON", "in the master container", "same as master"],
             ["Spark worker + executor", "runs tasks: service mode - posts file paths to the kitchen; cluster mode - loads models and runs NER itself", "sim-spark-worker / sim-ner-cluster-worker", "spark-lean / ner-translate-worker"],
             ["Shared data volume", "documents to process; the same path (/app/data/...) is valid on every node", "../data mounted everywhere", "-"]],
            [34, 74, 38, 28])
    d.note("Why two execution modes? **Service mode** keeps the heavy dependencies (torch, CUDA, transformers, tesseract) and the "
           "GPU in one server; Spark nodes stay lean and the models are loaded once. **Cluster mode** needs every executor to carry "
           "the full dependency set and load the models itself (once per task), but needs no separate server.")

    # 3
    d.H("3. Where the models live - the model store")
    d.img("airgap_sim_topology", "Figure 2 - models in HDFS; the kitchen (service mode) and the executor (cluster mode) each keep a node-local cache", maxh=95)
    d.P("The pipeline's models are three folders: **gliner-multi** (GLiNER weights, 2.2 GB), **nllb-200-distilled-600M** (translation model, 2.4 GB) and **hf_cache** (4 MB: config and tokenizer of GLiNER's backbone, microsoft/mdeberta-v3-base, in Hugging Face cache layout - GLiNER looks its encoder up by that hub name, so without it GLiNER cannot load offline). A single setting, `MODEL_STORE_URI`, tells every node where the three folders are:")
    d.table([["MODEL_STORE_URI", "meaning", "what a node does"],
             ["hdfs://hdfs-namenode:8020/models/weights", "models in the cluster's HDFS (air-gapped master storage)", "downloads each model folder once via WebHDFS into MODEL_CACHE_DIR, then loads from there"],
             ["file:///mnt/models", "models on the master's file system, shared read-only with the nodes (NFS or similar)", "loads straight from the shared path - no copy"],
             ["(unset)", "models next to the code in models/weights (original behaviour)", "loads from the repository folder"]],
            [50, 58, 66], mono=(0,))
    d.img("model_fetch_sequence", "Figure 3 - one model fetch, step by step", maxh=85)
    d.B(["**WebHDFS** is HDFS's built-in HTTP interface: the namenode answers `GET /webhdfs/v1/<path>?op=OPEN` with a redirect to the datanode that holds the blocks, and the datanode streams the bytes. The node needs nothing but Python's standard library - no Hadoop client, JVM or extra packages.",
         "**Once per node.** A finished download leaves `<folder>.complete`; later loads on that node (every task in cluster mode, every restart of the kitchen) are cache hits and do not touch HDFS.",
         "**Atomic.** Files are written into a `.partial-*` folder, sizes are checked against HDFS, and the folder is renamed into place in one step - two Python workers on the same node can never read a half-written model.",
         "**Offline tolerant.** With a warm cache a node starts even while HDFS is down (test T09).",
         "**Versioning.** Put a new model version into a new HDFS folder (e.g. /models/weights/v2/...) and point MODEL_STORE_URI at it; old and new caches coexist."])

    # 4
    d.H("4. The process, phase by phase")
    d.H("Phase 0 - Build (on a connected machine)", 2)
    d.P("Build the four images, pull Hadoop, and download the three model folders from Hugging Face once:")
    d.code("docker build --target final -t multi-model-inference:latest -f deploy/Dockerfile .\n"
           "docker build --target lean   -t spark-lean:latest            -f deploy/Dockerfile .\n"
           "docker build -t ner-translate-worker:latest -f deploy/Dockerfile.ner_translate .\n"
           "docker build -t ner-translate-server:latest -f deploy/Dockerfile.ner_translate_server .\n"
           "docker pull  apache/hadoop:3.4.1\n\n"
           "python -c \"from gliner import GLiNER; GLiNER.from_pretrained('urchade/gliner_multi-v2.1').save_pretrained('models/weights/gliner-multi')\"\n"
           "python -c \"from transformers import AutoModelForSeq2SeqLM, AutoTokenizer as T; m='facebook/nllb-200-distilled-600M';\n"
           "           T.from_pretrained(m).save_pretrained('models/weights/nllb-200-distilled-600M');\n"
           "           AutoModelForSeq2SeqLM.from_pretrained(m).save_pretrained('models/weights/nllb-200-distilled-600M')\"\n"
           "# GLiNER's backbone, config + tokenizer only, in Hugging Face cache layout:\n"
           "python -c \"from huggingface_hub import snapshot_download as s; s('microsoft/mdeberta-v3-base',\n"
           "           cache_dir='models/weights/hf_cache', allow_patterns=['*.json', 'spm.model'])\"")
    d.H("Phase 1 - Transfer across the air gap", 2)
    d.P("`docker save` each image to a tar file, pack the three model folders, record SHA-256 checksums, move them on approved media, verify the checksums on the other side and `docker load` the images on every node. Code changes afterwards travel as a small bundle (the repository without weights).")
    d.H("Phase 2 - Store the models in HDFS (or on the master)", 2)
    d.code("hdfs dfs -mkdir -p /models/weights\n"
           "hdfs dfs -put gliner-multi nllb-200-distilled-600M hf_cache /models/weights/\n"
           "hdfs dfs -du -s -h /models/weights/*          # sizes must match the source folders")
    d.P("Alternative: copy the three folders to a directory on the master that every node mounts read-only (e.g. /mnt/models) and use `MODEL_STORE_URI=file:///mnt/models`.")
    d.H("Phase 3 - Start the services", 2)
    d.B(["**HDFS** first (namenode, then datanodes). Healthy when WebHDFS answers and `hdfs dfsadmin -report` shows live datanodes.",
         "**Model server (service mode).** On startup serve.py calls `pipeline.load()`: the model store resolves the three folders (download on first start, cache hit afterwards), the hf_cache entries are copied into the process's Hugging Face cache, then GLiNER is moved to the GPU in fp16, NLLB-200 (600 M parameters) in fp32, and the language identifier (py3langid) is ready. `/health` switches from 'loading' to 'ok'.",
         "**Spark master, then workers.** Each worker registers its cores and memory with the master (visible on the master UI). In cluster mode the worker node also needs the GPU and the full NER dependency set.",
         "Nothing is processed yet - the cluster is warm and idle."], numbered=True)
    d.H("Phase 4 - Submit a job", 2)
    d.code("python submit_pipeline_job.py --pipeline ner_translate --input data/ner_samples \\\n"
           "       --partitions 2 --execution-mode service --master spark://ner-translate-master:7077")
    d.B(["Look up `ner_translate` in models/pipelines/manifest.json (module, service_url, master_url).",
         "Collect the input files (a folder is walked recursively; globs are expanded).",
         "Choose the Spark master: --master, else SPARK_MASTER_URL, else the manifest's master_url if it resolves, else local[4].",
         "Choose the execution mode: **service** (HTTP to service_url), **cluster** (import the pipeline and run it in the executors) or **auto** (service if its host resolves).",
         "Create the SparkSession (driver and executor memory from the command line)."], numbered=True)
    d.H("Phase 5 - Execute", 2)
    d.img("tdd_seq_pipeline", "Figure 4 - the same job in cluster mode (a) and service mode (b)", maxh=100)
    d.P("The list of file paths is split into min(partitions, files) partitions; each becomes one task that runs on a free worker slot. "
        "**Service mode:** the task sends its paths in one `POST /predict` to the kitchen and waits for the JSON reply - the executor never touches a model. "
        "**Cluster mode:** the task calls `load()` (model store fetch or cache hit, then GLiNER + NLLB onto the executor's GPU) and `run(loaded, paths)` itself. "
        "Paths, not file contents, are sent - so every node must see the documents at the same path (the shared data volume). "
        "The driver turns every input into an absolute path first (/app/data/ner_samples/...): an executor's working directory is "
        "its Spark work folder, not the driver's, so relative paths would not resolve there.")
    d.note("Entity counts can differ by one or two between runs in different modes (e.g. sample_text1: 27 in service mode with 2 "
           "partitions, 28 in cluster mode with 1 partition). Documents are batched together for the GPU, the batch composition "
           "depends on the partitioning, and GLiNER runs in fp16 - a mention scoring right at the 0.35 threshold can fall either side.")
    d.H("Phase 6 - Collect", 2)
    name, res_json = _latest_ner_result()
    d.P("Each task yields {hostname, pid, number of paths, load seconds, run seconds, results}. The driver merges all partitions' results into one dictionary keyed by file name and writes `results/ner_translate_<timestamp>.json`:")
    if res_json:
        k, v = next(iter(res_json.get("results", {}).items()))
        ents = v.get("entities_unique", [])[:4]
        d.code(f"# {name}\n" + "\n".join([
            f'"elapsed_time": {res_json.get("elapsed_time")}, "num_files": {res_json.get("num_files")}, "num_partitions": {res_json.get("num_partitions")},',
            f'"partition_details": {res_json.get("partition_details")},',
            f'"results": {{ "{k}": {{ "language": "{v.get("language")}", "translated": {str(v.get("translated")).lower()},',
            f'    "entities_unique": {ents} ... }} ... }}']), max_lines=14)
    d.H("Phase 7 - Stop", 2)
    d.B(["The driver calls `spark.stop()` - executors and their Python workers exit; the master and workers stay up for the next job.",
         "When no more jobs are expected: stop the Spark services, the model server and HDFS (`docker compose ... down`). HDFS data and the node caches are volumes and survive; the next start is a cache hit.",
         "To change a model: upload the new version to a new HDFS folder, point MODEL_STORE_URI at it, restart the model server (and workers in cluster mode). To force a re-download delete the node's cache folder (or its .complete marker)."])

    # 5
    d.brk()
    d.H("5. What happens to one document")
    d.img("ner_document_pipeline", "Figure 5 - the stages inside process_paths_batched()", maxh=85)
    d.table([["stage", "detail (from mt_ner_all_formats.py)"],
             ["1 Extract", "chosen by file extension: text/markdown/CSV/JSON/HTML/XML, PDF (text layer; if less than 20 characters -> OCR every page at 300 dpi), DOCX, ODT, RTF, EPUB, PPTX, XLSX/XLS/ODS (all cell text), images (OCR). OCR languages: English + Marathi, Hindi, Telugu, Tamil, Kannada, Bengali, Gujarati, Punjabi, Malayalam, Urdu (packs that are not installed are dropped automatically)."],
             ["2 Preprocess", "Unicode NFC, remove non-breaking spaces / BOM, collapse whitespace and blank lines."],
             ["3 Detect language", "py3langid on the first 1,000 characters (offline)."],
             ["4 Route", "English, French, German, Spanish, Italian, Portuguese go straight to NER; languages with an NLLB code (Indic languages, Arabic, Chinese, Japanese, Korean, Russian, Persian, Turkish, Vietnamese, Thai, Indonesian) are translated first; anything else is tagged as is."],
             ["5 Translate", "NLLB-200-distilled-600M, source language -> eng_Latn, one unit per sentence or line (the Devanagari danda counts as a sentence end), split further only above 400 tokens, 8 units per batch; documents in the same language are translated together. Whole paragraphs are never sent: NLLB drops text from multi-sentence input."],
             ["6 Chunk", "split into sentences, re-join up to 1,500 characters, remember each chunk's offset; chunks from ALL documents are pooled so the GPU sees full batches."],
             ["7 NER", "GLiNER multi v2.1, zero-shot, 19 labels (person, rank, organization, military unit, weapon system, vehicle, aircraft, vessel, equipment, facility, location, coordinates, operation name, event, date, time, nationality, communication identifier, phone number), score >= 0.35, 16 chunks per batch, fp16 on GPU."],
             ["8 Phone numbers", "regex pass over the text used and, for translated documents, over the original too (digits survive translation)."],
             ["9 Result", "entities with type, score and character offsets; `entities_unique` keeps the best-scoring mention per (text, type); plus language, translated flag, text used and original text."]],
            [24, 150])

    # 6
    d.H("6. When things go wrong")
    d.table([["situation", "what happens", "what to do"],
             ["HDFS down, node cache warm", "model server / executor starts from the cache (T09)", "nothing; restart HDFS later"],
             ["HDFS down, cache empty", "load() fails: 'cannot reach WebHDFS at http://...' (ConnectionError)", "start HDFS, or use the master file-system mode"],
             ["model folder missing in HDFS", "FileNotFoundError naming the path and namenode", "hdfs dfs -put the folder; check MODEL_STORE_URI"],
             ["interrupted download", "the .partial folder is discarded; next load downloads again", "nothing"],
             ["kitchen still loading", "/health says 'loading'; /predict answers 'models still loading'", "wait for 'ok' before submitting"],
             ["unreadable / unsupported file", "that document gets {'error': ...}; the others continue", "check the error text in the result"],
             ["two inputs with the same file name", "results are keyed by file name - the second overwrites the first", "keep file names unique"],
             ["GPU or host out of memory", "model load fails (CUDA OOM / container killed)", "fewer concurrent tasks per GPU; larger node; service mode"],
             ["hf_cache missing", "GLiNER fails: 'couldn't connect to huggingface.co ... microsoft/mdeberta-v3-base'", "store hf_cache next to the two models (the pipeline warns when it is absent)"]],
            [40, 72, 62])

    # 7
    d.H("7. Measured in the simulation")
    t5 = T.get("T05", {}).get("log", "")
    fetched = _mbps(t5)
    rows = [["measurement", "value", "test"]]
    for src, mb, s, rate in fetched:
        rows.append([f"first fetch from HDFS: {src.split('/')[-1]}", f"{float(mb):,.0f} MB in {s} s ({rate} MB/s)", "T05"])
    rows += [["model server start with HDFS fetch", res("T05"), "T05"], ["model server restart (cache hit)", res("T08"), "T08"],
             ["start with HDFS down (warm cache)", res("T09"), "T09"], ["Spark job, service mode, 6 documents", res("T07"), "T07"],
             ["master file-system mode (start + job)", res("T10"), "T10"], ["cluster mode: executor fetch + load + NER", res("T11"), "T11"]]
    d.table(rows, [80, 70, 24])
    d.P("Machine: laptop, Intel i5-9300H, 8 GB RAM (6 GB given to Docker/WSL2), NVIDIA GTX 1650 4 GB, Docker Desktop on Windows 11. "
        "On a real cluster the fetch runs at the network / HDFS rate instead of the Windows file-sharing rate.", "small")

    # 8
    d.H("8. Glossary")
    d.table([["term", "meaning"],
             ["air gap", "network with no connection to the internet; software and models arrive as files"],
             ["HDFS / namenode / datanode", "Hadoop distributed file system / its metadata server / its block storage servers"],
             ["WebHDFS", "HDFS's HTTP REST API (port 9870 on the namenode, 9864 on datanodes)"],
             ["model store", "models/model_store.py - resolves hdfs:// or file:// model locations to a local folder, with a per-node cache"],
             ["kitchen / waiter", "the model server that holds the models / the lean Spark job that sends it work"],
             ["driver / executor / task / partition", "job-building process / worker-side process / one partition's work / slice of the input files"],
             ["GLiNER / NLLB / py3langid", "zero-shot entity extractor / Meta's 200-language translator / offline language identifier"]],
            [46, 128])
    d.build(path, "NER pipeline - end-to-end process")


# =================================================================== PDF 2
def build_runbook_pdf(Doc, path, T, ev, res):
    d = Doc()
    d.story.append(__import__("reportlab.platypus", fromlist=["Spacer"]).Spacer(1, 30))
    d.P("Cluster Runbook - every mode, every test", "title")
    d.P("How to run the PyTorch-Spark inference platform locally in each mode - tensor models and the NER pipeline, "
        "service and cluster execution, models from HDFS, from the master's file system or from the repository - and the "
        "complete test suite with the outputs of the last run.", "sub")
    tot = [T[k]["Result"] for k in sorted(T)]
    d.note(f"Last simulation run: {len(tot)} tests, {tot.count('PASS')} PASS, {tot.count('FAIL')} FAIL "
           f"(deploy/airgap_sim_tests.ps1, logs under results/airgap_sim_*). Companion document: NER_PIPELINE_END_TO_END_PROCESS.pdf.")
    d.H("Contents", 3)
    for t in ["1. Modes at a glance", "2. One-time preparation", "3. The air-gapped simulation environment", "4. Run everything (automated)",
              "5. Run each mode by hand", "6. Test catalogue with results", "7. Tensor-model modes and their tests",
              "8. Moving to the real air-gapped cluster", "9. Troubleshooting", "10. Teardown and restoring the laptop"]:
        d.P(t, "small")
    d.brk()

    d.H("1. Modes at a glance")
    d.table([["#", "mode", "what runs", "model source", "how to start"],
             ["A", "local single container (tensor models)", "driver + executor in one container, Spark local[2]", "repository / torchvision cache", "docker run ... python submit_job.py --master local[2]"],
             ["B", "laptop Spark cluster (tensor models)", "master + GPU worker (+ CPU workers) containers", "repository", "docker compose -f deploy/docker-compose.laptop.yml up -d"],
             ["C", "NER service mode (waiter/kitchen)", "lean Spark master + worker, GPU model server", "HDFS / master FS / repository", "airgap_sim profiles hdfs + service"],
             ["D", "NER cluster mode (in-process)", "Spark master + GPU worker carrying all NER deps", "HDFS / master FS / repository", "airgap_sim profiles hdfs + cluster"],
             ["E", "models from HDFS", "WebHDFS fetch into node caches", "hdfs://hdfs-namenode:8020/models/weights", "MODEL_STORE_URI=hdfs://..."],
             ["F", "models from the master's file system", "read-only mount on every node", "file:///mnt/models", "MODEL_STORE_URI=file:///mnt/models + MODEL_FS_DIR"],
             ["G", "models from the repository (legacy)", "models/weights next to the code", "models/weights", "MODEL_STORE_URI unset"],
             ["H", "AWS single node / 2 nodes", "g4dn (+ m5) with SSM", "S3 upload of the repo", "deploy/run_aws_campaign.ps1, deploy/run_aws_modes.ps1"]],
            [6, 34, 44, 40, 50])

    d.H("2. One-time preparation (this laptop)")
    d.table([["item", "state / command"],
             ["Docker memory", "WSL2 VM raised to 6 GB: %USERPROFILE%\\.wslconfig [wsl2] memory=6GB, then `wsl --shutdown` and restart Docker Desktop (original saved as .wslconfig.bak-20260927). The NER model server needs ~4 GB while loading."],
             ["Cassandra", "stop during NER tests: `docker stop cassandra-web-ui cassandra-database` (start again afterwards)"],
             ["images", "apache/hadoop:3.4.1, ner-translate-server:latest, spark-lean:latest, ner-translate-worker:latest, multi-model-inference:latest (all present)"],
             ["model weights (staging)", "D:\\pytorch-spark-inference-platform_20260921\\models\\weights (gliner-multi 2.2 GB, nllb-200-distilled-600M 2.4 GB, hf_cache 4 MB) - passed to the tests with -WeightsSrc"],
             ["disk", "the simulation adds ~10 GB inside Docker's disk (HDFS copy, node caches); removed with -Wipe"]],
            [30, 144])

    d.brk()
    d.H("3. The air-gapped simulation environment")
    d.img("airgap_sim_topology", "deploy/docker-compose.airgap_sim.yml", maxh=95)
    d.table([["profile", "services (container)", "host ports"],
             ["hdfs", "hdfs-namenode (sim-hdfs-namenode), hdfs-datanode (sim-hdfs-datanode)", "9870 WebHDFS / namenode UI"],
             ["service", "ner-translate-server (sim-ner-translate-server, GPU), ner-translate-master (sim-spark-master), ner-translate-worker (sim-spark-worker)", "8001 kitchen API, 8083 Spark master UI, 4043 job UI"],
             ["cluster", "ner-cluster-master (sim-ner-cluster-master), ner-cluster-worker (sim-ner-cluster-worker, GPU)", "8084 Spark master UI, 4044 job UI"]],
            [18, 110, 46])
    d.table([["variable", "meaning", "example"],
             ["MODEL_STORE_URI", "where every node loads models from", "hdfs://hdfs-namenode:8020/models/weights | file:///mnt/models | (empty)"],
             ["MODEL_FS_DIR", "host folder mounted read-only at /mnt/models (the master's shared file system)", "D:\\...\\models\\weights"],
             ["WEIGHTS_SRC", "host folder uploaded into HDFS (mounted at /staging on the namenode)", "D:\\...\\models\\weights"],
             ["MODEL_CACHE_DIR", "node-local cache (set to /model_cache, a per-node volume)", "/model_cache"],
             ["MODEL_STORE_WEBHDFS / MODEL_STORE_USER", "WebHDFS URL override / HDFS user (optional)", "http://namenode:9870 / root"]],
            [40, 76, 58], mono=(0,))

    d.H("4. Run everything (automated)")
    d.code(".\\deploy\\airgap_sim_tests.ps1                                   # T01..T12\n"
           ".\\deploy\\airgap_sim_tests.ps1 -Tests T05,T06,T07              # a subset\n"
           ".\\deploy\\airgap_sim_tests.ps1 -WeightsSrc D:\\models\\weights   # another staging folder\n"
           ".\\deploy\\airgap_sim_tests.ps1 -Tests T12 -Wipe                # teardown incl. HDFS data and caches")
    d.P("Each test prints PASS/FAIL and its evidence; full output goes to results\\airgap_sim_<timestamp>\\<test>.log with a summary.txt/json.")

    d.brk()
    d.H("5. Run each mode by hand (PowerShell, repository root)")
    d.H("5.1 HDFS up and models uploaded (modes C/D with E)", 2)
    d.code('$env:WEIGHTS_SRC = "D:\\pytorch-spark-inference-platform_20260921\\models\\weights"\n'
           "docker compose -f deploy/docker-compose.airgap_sim.yml --profile hdfs up -d\n"
           "docker exec sim-hdfs-namenode hdfs dfsadmin -report                 # Live datanodes (1)\n"
           "docker exec sim-hdfs-namenode hdfs dfs -mkdir -p /models/weights\n"
           "docker exec sim-hdfs-namenode hdfs dfs -put -f /staging/gliner-multi /staging/nllb-200-distilled-600M /staging/hf_cache /models/weights/\n"
           "docker exec sim-hdfs-namenode hdfs dfs -du -s -h /models/weights/*\n"
           "start http://localhost:9870                                            # namenode UI -> Utilities -> Browse")
    d.H("5.2 Service mode with models from HDFS (C + E)", 2)
    d.code('$env:MODEL_STORE_URI = "hdfs://hdfs-namenode:8020/models/weights"\n'
           "docker compose -f deploy/docker-compose.airgap_sim.yml --profile hdfs --profile service up -d ner-translate-server\n"
           "docker logs -f sim-ner-translate-server       # [model_store] fetched ... -> Models loaded in ... s  (Ctrl+C)\n"
           "Invoke-RestMethod http://localhost:8001/health\n"
           "docker compose -f deploy/docker-compose.airgap_sim.yml --profile hdfs --profile service up -d\n"
           "docker exec sim-spark-master python submit_pipeline_job.py --pipeline ner_translate --input data/ner_samples `\n"
           "    --partitions 2 --execution-mode service --master spark://ner-translate-master:7077 --driver-memory 1g --executor-memory 512m")
    d.H("5.3 Call the model server directly (no Spark)", 2)
    d.code("Invoke-RestMethod -Method Post -Uri http://localhost:8001/predict -ContentType application/json `\n"
           "    -Body '{\"paths\":[\"data/ner_samples/sample_text1.txt\",\"data/ner_samples/sample_scan6.png\"]}'")
    d.H("5.4 Master file-system mode (C + F)", 2)
    d.code('$env:MODEL_FS_DIR = "D:\\pytorch-spark-inference-platform_20260921\\models\\weights"\n'
           '$env:MODEL_STORE_URI = "file:///mnt/models"\n'
           "docker compose -f deploy/docker-compose.airgap_sim.yml --profile service up -d --force-recreate ner-translate-server\n"
           "docker logs sim-ner-translate-server | Select-String 'model source'    # model store file:///mnt/models")
    d.H("5.5 Cluster (in-process) mode with models from HDFS (D + E)", 2)
    d.code("docker compose -f deploy/docker-compose.airgap_sim.yml --profile service stop     # free memory for the executor\n"
           '$env:MODEL_STORE_URI = "hdfs://hdfs-namenode:8020/models/weights"\n'
           "docker compose -f deploy/docker-compose.airgap_sim.yml --profile hdfs --profile cluster up -d\n"
           "docker exec sim-ner-cluster-master python submit_pipeline_job.py --pipeline ner_translate --input data/ner_samples `\n"
           "    --partitions 1 --execution-mode cluster --master spark://ner-cluster-master:7077 --driver-memory 1g --executor-memory 4g\n"
           "docker exec sim-ner-cluster-worker bash -c \"grep -rh model_store /opt/spark/work | tail\"   # executor fetched from HDFS")
    d.H("5.6 Repository mode (G) - original behaviour", 2)
    d.P("Leave MODEL_STORE_URI empty and put the three folders in models/weights of the repository (`robocopy <src> models\\weights /E`, add `models/weights/` to .git/info/exclude). Start the service or cluster profile as above.")

    d.brk()
    d.H("6. Test catalogue with results")
    cat = [("T01", "Prerequisites", "Docker VM memory >= 5.5 GB, 4 images, weights present, CUDA visible inside containers", ["memory", "image ok", "weights ok", "GPU", "MISSING"]),
           ("T02", "HDFS up", "namenode healthy, 1 live datanode", ["Live datanodes", "not healthy"]),
           ("T03", "Upload models to HDFS", "hdfs dfs -put the three folders; HDFS byte count == local byte count (hf_cache: present - its snapshot symlinks are stored as files)", ["local .* HDFS"]),
           ("T04", "model_store over WebHDFS", "fetched file sha256 == original; second call is a cache hit; missing path -> FileNotFoundError; unknown host -> ConnectionError", ["sha256", "cache hit", "expected error"]),
           ("T05", "Kitchen with models from HDFS", "logs 'model source: model store hdfs://', '[model_store] fetched', models loaded on GPU, /health ok", ["model source", r"\[model_store\]", "Models loaded", "GPU detected"]),
           ("T06", "Direct /predict", "a text file and a scanned PNG return language + entities", ["language=", "entities="]),
           ("T07", "Spark job, service mode", "6 documents processed through the lean cluster", ["execution-mode", "Processed", "lang="]),
           ("T08", "Node cache reuse", "restart -> 2 cache hits, no download", ["model_store", "Models loaded"]),
           ("T09", "HDFS outage, warm cache", "HDFS stopped; kitchen restarts from cache and answers /predict", ["HDFS"]),
           ("T10", "Master file-system mode", "file:///mnt/models, no fetch; Spark job succeeds", ["model source", "Processed", "Models loaded", "lang="]),
           ("T11", "Cluster mode, executor fetches from HDFS", "executor log shows model_store fetch; 6 documents processed in-process", ["executor:", "Processed", "execution-mode"]),
           ("T12", "Teardown", "services stopped; volumes kept (or removed with -Wipe)", ["stopped"])]
    d.table([["test", "what it proves", "pass criteria", "result"]] + [[t, n, c, res(t)] for t, n, c, _ in cat], [12, 40, 92, 30])
    for t, n, c, pats in cat:
        d.story.append(__import__("reportlab.platypus", fromlist=["KeepTogether"]).KeepTogether([]))
        d.H(f"{t} - {n}: {res(t)}", 3)
        d.code(ev(t, pats, n=10), max_lines=12)

    d.brk()
    d.H("7. Tensor-model modes and their tests")
    d.P("The 10 built-in models and BYOM plugins use `submit_job.py` / the benchmark scripts. These were verified earlier on this laptop (Windows and WSL2 legs) and on AWS; commands and reference results:")
    d.code("# A - local single container (Linux image, GPU)\n"
           'docker run --rm --gpus all -v "${PWD}:/work" -w /work multi-model-inference:latest `\n'
           "    python submit_job.py --model example_mlp --samples 20000 --mode gpu_only --master local[2] [--engine udf]\n\n"
           "# B - laptop Spark cluster (master + GPU worker; --scale spark-cpu-worker=N adds CPU workers)\n"
           "docker compose -f deploy/docker-compose.laptop.yml up -d\n"
           "docker exec spark-master python benchmark/cluster_benchmark.py --device-mode hybrid --partitions 4 `\n"
           "    --signal-samples 3000 --image-samples 100 --detection-samples 30\n\n"
           "# benchmark phases 1-10 (logs in results/campaign_<date>/<leg>)\n"
           "docker exec -e LEG=wsl2_docker spark-master bash benchmark/run_campaign.sh\n"
           "python benchmark/summarize_campaign.py results/campaign_20260926\n\n"
           "# execution-mode statistics (RDD / pandas UDF / predict_batch_udf / Triton), analysis and charts\n"
           "python benchmark/spark_modes_stats.py --master spark://<master>:7077 --out results/modes_<date>/<run>\n"
           "python benchmark/analyze_modes_stats.py results/modes_<date>/<run>")
    d.table([["test", "reference result", "source"],
             ["example_mlp RDD / pandas UDF (AWS T4)", "3,964 / 1,774 samples/s", "results/campaign_20260926/summary.md"],
             ["10 models cpu_only / gpu_only / hybrid (AWS T4, 3k)", "904 / 1,444 / 1,449 samples/s", "same"],
             ["same GPU, WSL2 vs Windows (parallel CUDA streams)", "20,618 vs 3,797 samples/s", "same"],
             ["2-node: tasks per node, gpu_only fallback, GPU-aware", "4/4 split; 6 of 8 partitions on CPU; 8/8 on GPU", "SPARK_INFERENCE_MODES_AND_TRITON_ARCHITECTURE_20260926.docx"],
             ["Triton vs in-process GPU inference stage (ResNet18)", "3.1 s vs 7.0 s", "same"]],
            [70, 60, 44])

    d.H("8. Moving to the real air-gapped cluster")
    d.table([["step", "detail"],
             ["images", "docker save apache/hadoop:3.4.1 (3.3 GB), ner-translate-server (9.3 GB), spark-lean (2.2 GB), ner-translate-worker (28 GB, cluster mode only) -> transfer -> docker load on each node"],
             ["models", "hdfs dfs -put gliner-multi nllb-200-distilled-600M hf_cache /models/weights/ on the real cluster (or copy the three folders to the master's shared folder)"],
             ["code", "repository without weights/results; models/model_store.py + the updated pipeline.py and plugin_loader.py"],
             ["node configuration", "MODEL_STORE_URI=hdfs://<namenode>:8020/models/weights (or file:///<shared path>), MODEL_CACHE_DIR on a local disk with >= 5 GB free, MODEL_STORE_WEBHDFS if WebHDFS is not on <namenode>:9870"],
             ["network", "nodes -> namenode 9870 (WebHDFS) AND -> every datanode 9864 (reads are redirected there); Spark 7077/8080 + ephemeral ports inside the cluster; Spark nodes -> kitchen 8000"],
             ["security", "WebHDFS with simple auth (user.name) is what model_store supports; on a Kerberised HDFS use HttpFS/Knox with a service account or the master file-system mode"],
             ["verification", "run the same checks as T02-T11 on the real nodes (hdfs dfsadmin -report, hdfs dfs -du, kitchen /health, one submit_pipeline_job)"]],
            [28, 146])

    d.H("9. Troubleshooting (including what came up while building this simulation)")
    d.table([["symptom", "cause", "fix"],
             ["namenode exits: 'storage directory does not exist or is not accessible'", "volume owned by root, daemon runs as user hadoop", "user: root + dfs.namenode.name.dir on the volume (as in the compose file)"],
             ["'docker compose up -d' blocks in a PowerShell helper", "an advanced PowerShell function binds -d to -Debug", "plain function with @args (airgap_sim_tests.ps1)"],
             ["upload to HDFS is slow", "Windows -> Docker file sharing (~10-20 MB/s)", "expected on a laptop; real clusters upload from a Linux node"],
             ["kitchen restarts while loading / container killed", "Docker VM memory", "6 GB WSL2 limit, Cassandra stopped, one heavy profile at a time"],
             ["'cannot reach WebHDFS'", "HDFS down or wrong host/port", "start HDFS; check MODEL_STORE_URI / MODEL_STORE_WEBHDFS"],
             ["executor cannot open http://hdfs-datanode:9864", "datanode not reachable from the node", "open port 9864 / fix datanode hostname (dfs.datanode.hostname)"],
             ["service mode says 'no service_url'", "manifest lacks service_url", "keep ner-translate-server as the kitchen's hostname or edit the manifest"],
             ["old code runs in the container", "prebuilt images carry older code", "the simulation mounts inference/, models/ and submit_pipeline_job.py from the repository"],
             ["GLiNER: 'couldn't connect to huggingface.co ... mdeberta-v3-base'", "GLiNER's backbone config/tokenizer not in the Hugging Face cache (offline)", "put hf_cache into the model store; pipeline.load() installs it (fixed in this release - the old compose files set HF_HUB_CACHE instead)"],
             ["'Repo id must be in the form ...' naming /app/models/weights/gliner-multi", "MODEL_STORE_URI empty -> repository mode, but the repository has no weights", "set MODEL_STORE_URI before docker compose up (the test script defaults it to the HDFS store)"],
             ["'cannot stop container ... PID is zombie'", "OCR / tokenizer child processes not reaped (Python server is PID 1)", "init: true on every Python service (tini reaps them) - set in the compose file"],
             ["cluster mode: every document 'No such file or directory: data/...'", "relative input paths resolved in the executor's work folder", "fixed: submit_pipeline_job.py sends absolute paths"]],
            [52, 58, 64])

    d.H("10. Teardown and restoring the laptop")
    d.code(".\\deploy\\airgap_sim_tests.ps1 -Tests T12            # stop, keep HDFS data + caches\n"
           ".\\deploy\\airgap_sim_tests.ps1 -Tests T12 -Wipe      # stop and delete HDFS data + caches (~10 GB)\n"
           "docker start cassandra-database cassandra-web-ui\n"
           "# optional: give Windows its memory back\n"
           "Copy-Item $env:USERPROFILE\\.wslconfig.bak-20260927 $env:USERPROFILE\\.wslconfig; wsl --shutdown   # then start Docker Desktop")
    d.build(path, "Cluster runbook - modes and tests")
