// build_tdd_docx.js - Technical Design Document (Word, A4 landscape) for the
// PyTorch-Spark inference platform: architecture, component design, request
// traces with exact file:line references, extension recipes, configuration,
// debugging, testing, API reference and the complete source code.
//
// Inputs: docs/tdd/api.json (python docs/tdd/extract_api.py), the repository
// sources, docs/diagrams/png/*.png. Needs the `docx` npm package.
//   node docs/tdd/build_tdd_docx.js [out.docx]
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType, Table, TableRow, TableCell, WidthType,
  ShadingType, BorderStyle, LevelFormat, TableOfContents, Footer, Header, PageNumber, ImageRun, PageOrientation,
} = require("docx");

const REPO = path.join(__dirname, "..", "..");
const OUT = process.argv[2] || path.join(REPO, "docs", "TDD_PYTORCH_SPARK_INFERENCE_PLATFORM.docx");
const API = JSON.parse(fs.readFileSync(path.join(__dirname, "api.json"), "utf8"));
const F = Object.fromEntries(API.files.map((f) => [f.path, f]));
const DIAG = path.join(REPO, "docs", "diagrams", "png");
const src = (p) => fs.readFileSync(path.join(REPO, p), "utf8").replace(/\r\n/g, "\n");

const PW = 16838, PH = 11906, M = 850, CW = PW - 2 * M;
const MONO = "Consolas", BODY = "Arial", ACCENT = "0B5CAD";
const WARN = [];

// ------------------------------------------------------------------ references
function fnLine(p, name) {
  const f = F[p]; if (!f) { WARN.push(`no file ${p}`); return "?"; }
  for (const fn of f.functions || []) { if (fn.name === name) return fn.line; for (const n of fn.nested || []) if (n.name === name) return n.line; }
  for (const c of f.classes || []) { if (c.name === name) return c.line; for (const m of c.methods) if (m.name === name) return m.line; }
  WARN.push(`no symbol ${p}:${name}`); return "?";
}
function lineOf(p, snippet, from = 1) {
  const lines = src(p).split("\n");
  for (let i = from - 1; i < lines.length; i++) if (lines[i].includes(snippet)) return i + 1;
  WARN.push(`no snippet in ${p}: ${snippet}`); return "?";
}
const R = (p, name) => `${p}:${fnLine(p, name)}`;          // file:line of a function
const L = (p, snip, from) => `${p}:${lineOf(p, snip, from)}`; // file:line of a snippet

// ------------------------------------------------------------------ docx helpers
function runs(text, base = {}) {
  const out = []; const re = /(\*\*[^*]+\*\*|`[^`]+`)/g; let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...base }));
    const t = m[0];
    out.push(t.startsWith("**") ? new TextRun({ text: t.slice(2, -2), bold: true, ...base })
      : new TextRun({ text: t.slice(1, -1), font: MONO, size: 17, ...base }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...base }));
  return out;
}
const body = [];
const H1 = (t, br = true) => body.push(new Paragraph({ heading: HeadingLevel.HEADING_1, pageBreakBefore: br, children: [new TextRun(t)] }));
const H2 = (t) => body.push(new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] }));
const H3 = (t) => body.push(new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(t)] }));
const P = (t) => body.push(new Paragraph({ spacing: { after: 110 }, children: runs(t) }));
const B = (items) => items.forEach((t) => body.push(new Paragraph({ numbering: { reference: "bullets", level: 0 }, spacing: { after: 50 }, children: runs(t) })));
let numInstance = 0;  // each numbered list restarts at 1
const N = (items, ref = "numbers") => { numInstance++; const inst = numInstance;
  items.forEach((t) => body.push(new Paragraph({ numbering: { reference: ref, level: 0, instance: inst }, spacing: { after: 50 }, children: runs(t) }))); };
function note(t, fill = "EAF3FD", bar = ACCENT) {
  body.push(new Paragraph({ shading: { type: ShadingType.CLEAR, color: "auto", fill }, border: { left: { style: BorderStyle.SINGLE, size: 18, color: bar, space: 6 } },
    spacing: { before: 80, after: 160 }, indent: { left: 160, right: 120 }, children: runs(t) }));
}
const warnNote = (t) => note(t, "FFF4E5", "D97706");
function code(text, opts = {}) {
  const lines = String(text).replace(/\t/g, "    ").replace(/\r\n/g, "\n").split("\n");
  if (lines.length && lines[lines.length - 1] === "") lines.pop();
  const num = opts.numbers; const size = opts.size || 15;
  lines.forEach((l, i) => body.push(new Paragraph({ shading: { type: ShadingType.CLEAR, color: "auto", fill: "F3F5F8" },
    spacing: { before: i === 0 ? 50 : 0, after: i === lines.length - 1 ? 130 : 0, line: 228 }, indent: { left: 100, right: 100 },
    children: num ? [new TextRun({ text: String(i + 1).padStart(5, " ") + "  ", font: MONO, size, color: "8A94A3" }), new TextRun({ text: l || " ", font: MONO, size })]
      : [new TextRun({ text: l || " ", font: MONO, size })] })));
}
const bd = { style: BorderStyle.SINGLE, size: 4, color: "C9D1D9" };
function table(rows, pct, mono = [], fs_ = 17) {
  const w = pct.map((p) => Math.floor((CW * p) / 100)); const tot = w.reduce((a, b) => a + b, 0);
  body.push(new Table({ width: { size: tot, type: WidthType.DXA }, columnWidths: w, rows: rows.map((r, ri) => new TableRow({
    tableHeader: ri === 0, cantSplit: false, children: r.map((c, ci) => new TableCell({ borders: { top: bd, bottom: bd, left: bd, right: bd },
      width: { size: w[ci], type: WidthType.DXA }, margins: { top: 35, bottom: 35, left: 70, right: 70 },
      shading: ri === 0 ? { type: ShadingType.CLEAR, color: "auto", fill: "E4E9F0" } : (ri % 2 === 0 ? { type: ShadingType.CLEAR, color: "auto", fill: "FAFBFC" } : undefined),
      children: [new Paragraph({ children: ri === 0 ? [new TextRun({ text: String(c), bold: true, size: fs_ })]
        : mono.includes(ci) ? [new TextRun({ text: String(c), font: MONO, size: fs_ - 2 })] : runs(String(c), { size: fs_ }) })] })) })) }));
  body.push(new Paragraph({ spacing: { after: 90 }, children: [] }));
}
function pngSize(p) { const b = fs.readFileSync(p); return [b.readUInt32BE(16), b.readUInt32BE(20)]; }
function img(key, cap, maxW = 980) {
  const p = path.join(DIAG, `${key}.png`); if (!fs.existsSync(p)) { WARN.push(`missing diagram ${key}`); return; }
  const [w, h] = pngSize(p); let W = Math.min(maxW, w / 2), Hh = (h * W) / w; if (Hh > 455) { Hh = 455; W = (w * Hh) / h; }
  body.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 60, after: 40 }, children: [new ImageRun({ type: "png", data: fs.readFileSync(p),
    transformation: { width: Math.round(W), height: Math.round(Hh) }, altText: { title: key, description: cap || key, name: key } })] }));
  if (cap) body.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 150 }, children: [new TextRun({ text: cap, italics: true, size: 16, color: "57606A" })] }));
}
const fileDoc = (p) => (F[p] && F[p].doc) || "";

// ================================================================== CONTENT
body.push(new Paragraph({ spacing: { before: 1100, after: 200 }, children: [new TextRun({ text: "Technical Design Document", size: 60, bold: true })] }));
body.push(new Paragraph({ spacing: { after: 120 }, children: [new TextRun({ text: "PyTorch-Spark Multi-Model Inference Platform", size: 36, color: ACCENT, bold: true })] }));
body.push(new Paragraph({ spacing: { after: 300 }, children: [new TextRun({ text: "Architecture, component design, request-to-response traces, extension guide, configuration, debugging, testing, API reference and complete source code", size: 24, color: "57606A" })] }));
const tot = API.files.reduce((a, f) => a + f.lines, 0);
const byCat = {}; API.files.forEach((f) => { byCat[f.category] = byCat[f.category] || [0, 0]; byCat[f.category][0]++; byCat[f.category][1] += f.lines; });
table([["item", "value"],
  ["Document", "Technical Design Document (TDD), version 1.0, 26 September 2026"],
  ["System", "pytorch-spark-inference-platform (Spark 3.5.1, PyTorch 2.6 cu126 in the platform image; Python 3.11)"],
  ["Audience", "Developers adding models, pipelines and engines (sections 4-9); architects and reviewers (sections 2, 3, 10, 11)"],
  ["Source baseline", `${API.files.length} files, ${tot.toLocaleString()} lines: ` + Object.entries(byCat).map(([k, v]) => `${k} ${v[0]} files / ${v[1].toLocaleString()} lines`).join("; ")],
  ["Generated from", "docs/tdd/extract_api.py (AST of every module) + docs/tdd/build_tdd_docx.js; every file:line reference is resolved from the source at build time"],
  ["Diagrams", "docs/diagrams/spark_inference_architectures.drawio (editable, 20 pages) - regenerate with python docs/diagrams/build_diagrams.py"],
  ["Related documents", "docs/SPARK_INFERENCE_MODES_AND_TRITON_ARCHITECTURE_20260926.docx (execution modes, statistics, Triton), docs/LOWLEVEL_EXECUTION_GUIDE_20260926.pdf (hardware level), docs/BRING_YOUR_OWN_MODEL.md, docs/MODEL_CONTAINER_ISOLATION.md, docs/AIRGAPPED_*.md"]],
[18, 82]);
body.push(new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" }));

// ------------------------------------------------------------------ 1
H1("1. Introduction");
H2("1.1 Purpose and scope");
P("This document describes how the platform is built and how to work on it: the architecture and its runtime topologies, the design of every module, exactly which code runs - file by file, line by line - from the moment a job is submitted until its results are written, how to add models, pipelines, engines and deployments, how to configure, debug and test it, and the complete source code for reference.");
H2("1.2 How to read it");
table([["if you are...", "read"],
  ["an architect / reviewer", "2 (overview), 3 (architecture), 10 (non-functional, known issues), 11 (roadmap)"],
  ["adding a model or pipeline", "6.1-6.3 (recipes), 5 (traces), 7 (configuration), 9 (tests)"],
  ["changing an engine", "4.2 (engine designs), 5 (traces), 6.4, 8 (debugging), 9"],
  ["operating / debugging a cluster", "3.4 (deployments), 7, 8"],
  ["looking something up", "Appendix A (API), B (files), C (source with line numbers), D (glossary)"]], [30, 70]);
H2("1.3 Conventions");
B(["`path/to/file.py:123` - a file and line in this repository (also printed with line numbers in Appendix C).",
  "**Driver** = the Python process that builds the job; **executor** = Spark JVM on a worker; **Python worker** = the Python process an executor starts for Python code; **task** = one partition's work.",
  "**P** = number of partitions, **B** = batch size, **device_mode** = cpu_only | gpu_only | hybrid."]);

// ------------------------------------------------------------------ 2
H1("2. System overview");
H2("2.1 What the platform does");
P("The platform runs many PyTorch models over large batches of sensor data (EW signals, images, detection frames) and documents, on a Spark cluster whose workers may or may not have GPUs - on Windows or Linux, on AWS or air-gapped LANs. It ships 10 built-in models, lets users bring their own tensor models (BYOM plugins) and multi-model file pipelines (ner_translate: OCR -> language id -> NLLB translation -> GLiNER NER), and offers several execution modes so the same models can run on a single GPU, split across GPU/CPU, or distributed over the cluster.");
H2("2.2 Capabilities");
table([["capability", "how", "code"],
  ["10 built-in models", "ModelRegistry with metadata (input shape, category, memory estimate)", "models/__init__.py, models/model_registry.py"],
  ["Bring-your-own tensor model", "drop a module + manifest entry; no framework edits", "models/plugin_loader.py, models/plugins/"],
  ["File pipelines", "load()/run(paths) contract, in-process or behind an HTTP 'kitchen'", "models/pipelines/, inference/text_pipeline_engine.py"],
  ["Distributed inference", "Spark mapPartitions (RDD) or pandas UDF engines, per-task device resolution", "inference/cluster_engine.py, cluster_engine_udf.py, predict_batch_udf.py"],
  ["Single-GPU / hybrid", "CUDA streams per model; memory-aware GPU/CPU placement", "inference/single_gpu.py, cuda_streams_engine.py, hybrid_cpu_gpu.py, gpu_memory_manager.py"],
  ["Benchmarks", "10 test phases, campaign runner, statistics", "benchmark/"],
  ["Deployment", "Docker images, compose clusters, AWS CDK stacks, Windows LAN scripts, air-gapped bundles", "deploy/"],
  ["Monitoring", "CloudWatch publishers for Spark, GPU and benchmark metrics", "monitoring/"]], [22, 45, 33]);
H2("2.3 Design principles (as implemented)");
B(["**Weights travel, classes are rebuilt.** The driver serializes `state_dict`s and broadcasts them; executors rebuild each model from its class name (`_get_class_map()`) and load the bytes - no pickled nn.Modules.",
  "**Device is decided where the code runs.** Every task checks `torch.cuda.is_available()` itself; the driver never assumes what an executor has.",
  "**New behaviour is opt-in.** New engines and modes are flags (`--engine udf`, `--execution-mode`, `gpu_aware_scheduling=True`) that leave the default path unchanged.",
  "**Heavy dependencies stay out of Spark where possible.** `create_cluster_session` imports without torch (`from __future__ import annotations`), so the lean image can drive jobs; pipelines can run behind a model server (waiter/kitchen).",
  "**Air-gapped first.** Every image and dependency has an offline path (wheelhouses, .deb bundles, docker save tars)."]);
H2("2.4 Execution modes at a glance");
table([["mode", "entry point", "engine", "where models live", "returns", "use it for"],
  ["single_gpu", "run_benchmark.py --mode single_gpu", "single_gpu.py + CUDAStreamsEngine", "one process, all models on one GPU", "counts + latency", "one GPU workstation; highest throughput per GPU"],
  ["hybrid (in-process)", "run_benchmark.py --mode hybrid", "hybrid_cpu_gpu.py + GPUMemoryManager", "GPU until VRAM budget, rest on CPU threads", "counts", "limited VRAM"],
  ["distributed (Mode 1)", "run_benchmark.py --mode distributed", "distributed_gpu.py", "every task rebuilds all models", "counts + per-model stats", "benchmarks"],
  ["cluster RDD", "submit_job.py / cluster_benchmark.py", "cluster_engine.run_cluster_inference", "every task rebuilds its models", "counts + partition details", "BYOM tensor models on a cluster"],
  ["cluster pandas UDF", "submit_job.py --engine udf", "cluster_engine_udf + predict_batch_udf", "per task, inside the UDF", "per-sample predictions", "when predictions are needed"],
  ["pipeline (cluster)", "submit_pipeline_job.py --execution-mode cluster", "text_pipeline_engine.run_text_pipeline_job", "per task (load())", "per-document results", "pipelines with deps on every executor"],
  ["pipeline (service)", "submit_pipeline_job.py --execution-mode service", "text_pipeline_engine.run_text_pipeline_job_via_service", "once, in the kitchen server", "per-document results", "lean Spark image + GPU model server"]],
[13, 19, 19, 17, 12, 20]);

// ------------------------------------------------------------------ 3
H1("3. Architecture");
H2("3.1 Code architecture");
img("tdd_module_map", "Figure 3.1 - packages and call relationships");
table([["package", "responsibility", "depends on"],
  ["entry points (repo root, benchmark/)", "parse CLI, prepare inputs, choose engine, write results", "inference, models, data"],
  ["inference/", "execution engines: Spark sessions, distributed runners, single-GPU and hybrid runners", "models (class map), torch, pyspark"],
  ["models/", "model classes, registry, BYOM plugins, file pipelines (+ kitchen server)", "torch, torchvision, ultralytics (optional), pipeline deps"],
  ["data/", "deterministic synthetic inputs (signals, images, detection frames)", "numpy"],
  ["monitoring/", "CloudWatch publishers (Spark REST, nvidia-smi, benchmark results)", "boto3, urllib"],
  ["deploy/", "Dockerfiles, compose files, AWS CDK stacks, PowerShell/bash operations scripts", "Docker, AWS CDK, Spark scripts"],
  ["benchmark/ (+ docs/ generators)", "benchmarks, campaign runner, statistics, document generators", "everything above"]], [22, 50, 28]);
H2("3.2 Runtime view");
img("current_cluster", "Figure 3.2 - processes at runtime on a CPU node + GPU node cluster");
P("Per job: one driver Python process (+ its JVM via Py4J), one executor JVM per worker (4 cores, spark.task.cpus=2 -> 2 concurrent tasks), and one Python worker per concurrent task (forked from pyspark.daemon on Linux, spawned on Windows). Models are materialised inside Python workers; the GPU is shared by every Python worker on that node.");
H2("3.3 Container images");
table([["image (tag)", "built from", "contains", "used by"],
  ["multi-model-inference:latest", "deploy/Dockerfile target `final` (spark-base + torch 2.6 cu126 + requirements.txt + source + torchvision weights)", "Spark 3.5.1, Java 17, Python 3.11, torch, torchvision, pyarrow, pandas, ultralytics", "master, workers, drivers for tensor models; all benchmarks"],
  ["spark-lean:latest", "deploy/Dockerfile target `lean` (spark-base + pyspark + requests only)", "no torch / CUDA", "waiter side of the waiter/kitchen split (ner_translate service mode)"],
  ["ner-translate-worker", "deploy/Dockerfile.ner_translate (FROM multi-model-inference + offline wheelhouse + tesseract/poppler .debs)", "pipeline deps for in-process (cluster) mode", "ner_translate cluster mode"],
  ["ner-translate-server", "deploy/Dockerfile.ner_translate_server (python:3.11-slim + torch + pipeline deps)", "FastAPI/uvicorn kitchen, port 8000", "ner_translate service mode"],
  ["Dockerfile.worker (cpu / gpu targets)", "Dockerfile.worker", "standalone worker images (python 3.14 slim / CUDA 12.8 runtime)", "alternative worker builds"]], [18, 34, 26, 22]);
warnNote("`deploy/Dockerfile`'s LAST stage is `lean`, so `docker build -f deploy/Dockerfile .` without `--target final` produces the torch-less image. Always pass `--target final` for multi-model-inference (deploy/scripts/setup_and_run_gpu.sh still omits it).");
H2("3.4 Deployment topologies");
table([["topology", "files", "notes"],
  ["Local single container", "docker run multi-model-inference + SPARK_MASTER_URL=local[N]", "fastest dev loop; what the WSL2 campaign used"],
  ["Compose cluster (Docker Desktop)", "deploy/docker-compose.cluster.yml (+ .linux.yml), docker-compose.laptop.yml", "master + CPU/GPU workers on one host; laptop file is sized for 4 GB Docker VMs"],
  ["ner_translate clusters", "deploy/docker-compose.ner_translate.yml, docker-compose.ner_translate_server.yml", "dedicated master/workers; server file adds the kitchen and runs Spark on spark-lean"],
  ["Windows LAN cluster", "deploy/start_cluster.ps1, stop_cluster.ps1, deploy_to_cluster.ps1, run_lan_cluster_benchmarks.ps1, docs/WINDOWS_*.md", "WSL2 mirrored networking, see docs/WINDOWS_LAN_NETWORKING_FIX_20260921.md"],
  ["AWS single GPU", "deploy/aws-cdk GpuBenchmarkStack + deploy/run_gpu_cdk.ps1 / run_aws_campaign.ps1", "g4dn.xlarge, DL AMI, SSM, S3 artifacts"],
  ["AWS 2-node", "SparkModesClusterStack + deploy/run_aws_modes.ps1 + scripts/modes_node.sh", "m5 CPU node + g4dn GPU node + Triton"],
  ["AWS full cluster / Windows cluster", "SparkInferenceClusterStack, WindowsSparkClusterStack", "Amazon Linux / Windows Server variants with CloudWatch dashboard"],
  ["Air-gapped 5-node", "docs/AIRGAPPED_5NODE_DEPLOYMENT.md, scripts/build_ner_translate_{wheelhouse,debs}.sh, apply_wheels_hotfix.sh", "images and dependencies moved as files"]], [18, 44, 38]);
img("aws_topology", "Figure 3.3 - recommended AWS topology (target state with Triton)");
H2("3.5 Data contracts");
table([["object", "shape / schema", "produced by", "consumed by"],
  ["model input", "numpy float32 (N, *input_shape): signals (N,128), images (N,3,224,224), detections (N,3,640,640)", "data/*_generator.py, np.load(--input)", "engines"],
  ["data dict", "{model_name: ndarray}", "generate_mixed_data(), submit_job", "run_cluster_inference, run_*"],
  ["partition element (RDD)", "(partition_idx, {model_name: ndarray slice})", "run_cluster_inference / run_distributed_gpu_inference", "process_partition / infer_on_partition"],
  ["partition detail", "{partition_idx, executor_id, hostname, device, cuda_available, model_load_time_sec, inference_time_sec, total_task_time_sec, samples_processed, per_model_processed, batch_size}", "process_partition()", "cluster_benchmark report, results JSON"],
  ["engine result", "{mode, device_mode, elapsed_time, total_samples_processed, total_throughput, per_model_processed, num_partitions, num_models, batch_size, partition_details, spark_ui_stats, timestamp} (+ predictions for UDF)", "run_cluster_inference(_udf)", "submit_job, cluster_benchmark"],
  ["pipeline result", "{elapsed_time, num_files, num_partitions, partition_details[{hostname,pid,num_paths,load_time_sec,run_time_sec}], results{basename: {language, translated, entities_unique, ...}}}", "text_pipeline_engine", "submit_pipeline_job"],
  ["plugin manifest", "{name: {module, class_name, input_shape, weights_path?, output_desc?, category?, estimated_memory_mb?}}", "models/plugins/manifest.json", "plugin_loader"],
  ["pipeline manifest", "{name: {module, description?, weights?, requirements_file?, master_url?, service_url?}}", "models/pipelines/manifest.json", "submit_pipeline_job"],
  ["results files", "results/<model>_<ts>.json, results/<pipeline>_<ts>.json, results_<run>_*.json, report_*.md, cluster_benchmark_*.json", "entry points", "people, pull_results.ps1, publishers"]], [14, 46, 20, 20]);

// ------------------------------------------------------------------ 4 component design
H1("4. Component design");
P("For every module: its responsibility, public API (from the source), design decisions and invariants a maintainer must preserve, and known pitfalls. The complete API of every module - including private helpers - is in Appendix A.");
const DESIGN = {
  "submit_job.py": ["BYOM CLI for tensor models.",
    `Flow: registry + plugins (${L("submit_job.py", "registry = get_default_registry()")}) -> input from --input .npy or random data shaped by the registered input_shape (${L("submit_job.py", "np.random.randn(n, *info.input_shape)")}) -> model loaded once on CPU in the driver (${L("submit_job.py", "registry.load_model(args.model")}) -> Spark session named byom-<model> -> engine chosen by --engine -> summary without partition_details/spark_ui_stats -> results/<model>_<ts>.json and, if ARTIFACTS_BUCKET is set, S3 (${R("submit_job.py", "_write_results")}).`,
    "Invariant: inputs are float32 and batch-first; --mode is passed to the engine as device_mode; the Spark session is always stopped (try/finally)."],
  "submit_pipeline_job.py": ["CLI for file pipelines (manifest entries in models/pipelines/manifest.json).",
    `Master URL precedence (${R("submit_pipeline_job.py", "_resolve_master_url")}): --master > SPARK_MASTER_URL / SPARK_MASTER > manifest master_url if its host resolves > local[4]. Execution mode: service (HTTP kitchen, requires service_url), cluster (in-process load()/run()), auto (service if its host resolves).`,
    `The pipeline module is imported only in cluster mode (${L("submit_pipeline_job.py", "mod = importlib.import_module")}) so the lean image can run service mode without torch. _host_resolvable() restores the process-wide socket timeout it sets (${L("submit_pipeline_job.py", "socket.setdefaulttimeout(previous_timeout)")}) - leaving it set made Py4J time out during SparkContext start.`],
  "inference/cluster_engine.py": ["Spark session factory used by every cluster path, and the RDD (mapPartitions) inference engine.",
    `create_cluster_session (${R("inference/cluster_engine.py", "create_cluster_session")}) sets driver/executor memory, executor cores 4, spark.task.cpus 2, rpc.message.maxSize 512 MB, driver.maxResultSize 4g, network timeout 600 s, Python worker reuse, JVM add-opens; for non-local masters it adds executorEnv PYTHONPATH=/app..., CUDA_VISIBLE_DEVICES=0 and, when gpu_aware_scheduling=True, GPU resource requests (1 per executor, 0.5 per task).`,
    `run_cluster_inference (${R("inference/cluster_engine.py", "run_cluster_inference")}): state_dicts -> sc.broadcast (${L("inference/cluster_engine.py", "bc_model_bytes = sc.broadcast")}); data sliced into P dicts (last one takes the remainder); process_partition resolves the device per task, rebuilds each model from _get_class_map() and loads the broadcast bytes (${L("inference/cluster_engine.py", "model.load_state_dict(torch.load(buf")}), runs batches of B and yields timings + counts; the driver aggregates and snapshots the Spark REST API on localhost:4040.`,
    "Important: despite the docstring ('loads models ONCE per executor'), models are rebuilt for every partition (measured: 2.2 s cold, 0.6 s warm per task for 10 models). Outputs are discarded - only counts are returned. `from __future__ import annotations` must stay: it lets the lean image import create_cluster_session without torch."],
  "inference/cluster_engine_udf.py": ["pandas-UDF engine with the same signature and result keys as run_cluster_inference (drop-in for submit_job --engine udf).",
    `Builds a DataFrame of flat float lists with an explicit schema (${L("inference/cluster_engine_udf.py", "schema = StructType")}) - schema inference over nested lists hung in testing - repartitions it (a shuffle), applies predict_batch_udf and collects predictions.`,
    "Returns per-sample predictions (results['predictions']); partition_details is empty. One DataFrame + one Spark job pair per model."],
  "inference/predict_batch_udf.py": ["Scalar-iterator pandas UDF factory (the repo's own; distinct from pyspark.ml.functions.predict_batch_udf).",
    `The model is built once per task inside _predict (${R("inference/predict_batch_udf.py", "_predict")}), each Arrow batch is re-chunked to inference_batch_size, malformed rows become None (skip-and-log).`,
    "Must NOT use `from __future__ import annotations`: pandas_udf inspects the Iterator[pd.Series] annotations at definition time. Returns ArrayType(FloatType) - fixed-size outputs only (not YOLO lists)."],
  "inference/text_pipeline_engine.py": ["Engine for file pipelines (load()/run(paths) contract).",
    `run_text_pipeline_job (${R("inference/text_pipeline_engine.py", "run_text_pipeline_job")}) parallelizes file paths into min(P, files) partitions; each task calls load() then run(loaded, paths); results are merged into one dict. run_text_pipeline_job_via_service (${R("inference/text_pipeline_engine.py", "run_text_pipeline_job_via_service")}) instead POSTs the paths to <service_url>/predict (requests imported inside the closure) with a 600 s timeout.`,
    "Paths are sent, not contents: the kitchen must see the same mounted path. Results are keyed by file basename - two inputs with the same name overwrite each other in the merged dict."],
  "inference/distributed_gpu.py": ["Mode 1 of run_benchmark.py (the original distributed engine).",
    `create_spark_session (${R("inference/distributed_gpu.py", "create_spark_session")}) - like create_cluster_session with executorEnv SPARK_EXECUTOR_GPU; run_distributed_gpu_inference (${R("inference/distributed_gpu.py", "run_distributed_gpu_inference")}) embeds each partition's data in one RDD element and uses rdd.map(infer_on_partition) (${L("inference/distributed_gpu.py", "data_rdd.map(infer_on_partition)")}); each element rebuilds all models and runs them on CUDA streams when available (run_models_on_streams).`,
    "Superseded by cluster_engine for user jobs; kept for the benchmark phases."],
  "inference/single_gpu.py": ["Mode 2: all models on one GPU, one CUDA stream per model.",
    `run_single_gpu_inference (${R("inference/single_gpu.py", "run_single_gpu_inference")}) moves models to the device, warms up 3 times, then for each batch index launches every model's batch through CUDAStreamsEngine.infer_all_parallel.`,
    "Falls back to CPU if CUDA is missing. Reports avg and p99 batch latency."],
  "inference/cuda_streams_engine.py": ["Launch N models concurrently on one GPU.",
    `Each GPU model gets its own torch.cuda.Stream; infer_all_parallel (${R("inference/cuda_streams_engine.py", "infer_all_parallel")}) enqueues every model on its stream (non_blocking copies), runs CPU models on a thread pool, then synchronizes once.`,
    "Inputs are pageable tensors; pinning them would let copies overlap compute (see the low-level guide)."],
  "inference/hybrid_cpu_gpu.py": ["Mode 3: memory-aware split.",
    `run_hybrid_inference (${R("inference/hybrid_cpu_gpu.py", "run_hybrid_inference")}) asks GPUMemoryManager for a placement (priority order within the VRAM budget), runs GPU models via CUDAStreamsEngine and CPU models on a ThreadPoolExecutor.`, ""],
  "inference/gpu_memory_manager.py": ["VRAM budget planner.",
    `GPUMemoryManager (${R("inference/gpu_memory_manager.py", "GPUMemoryManager")}) reads every GPU's total memory, reserves reserve_mb (default 500) for the CUDA context, and plan_placement assigns models (by priority) to the first GPU with room, else CPU.`,
    "Uses the registry's estimated_memory_mb - estimates, not measurements."],
  "models/__init__.py": ["Registers the 10 built-in models (metadata only) in get_default_registry().", "", ""],
  "models/model_registry.py": ["ModelRegistry: name -> ModelInfo(class, input_shape, output_desc, category, estimated_memory_mb).",
    "load_model caches ONE instance per name and moves it with .to(device) - callers share that instance. serialize_model/deserialize_model use state_dict bytes (weights_only=True on load).", ""],
  "models/model_store.py": ["Model store: resolves where model weights live - a local path, file:// (a file system on the master shared with the nodes) or hdfs:// (an air-gapped HDFS cluster, read through WebHDFS with the standard library only) - into a local folder.",
    `resolve() (${R("models/model_store.py", "resolve")}) returns local paths as-is; for hdfs:// it walks the tree with GETFILESTATUS/LISTSTATUS and streams every file with op=OPEN (namenode redirects to a datanode) into MODEL_CACHE_DIR (${R("models/model_store.py", "_fetch_hdfs")}). Downloads go to a .partial-* folder, sizes are checked against HDFS, the folder is renamed into place and a .complete marker written - so concurrent Python workers on a node never see half a model and later loads are cache hits, even while HDFS is down.`,
    "Configured by MODEL_STORE_URI (unset = original repository paths), MODEL_CACHE_DIR, MODEL_STORE_WEBHDFS, MODEL_STORE_USER. Supports simple (user.name) WebHDFS auth only - for Kerberised HDFS use HttpFS/Knox or the file:// mode. Used by models/pipelines/ner_translate/pipeline.py (gliner-multi, nllb-200-distilled-600M, hf_cache) and by plugin_loader for weights_path URIs."],
  "models/plugin_loader.py": ["BYOM glue: imports each manifest module, registers it, optionally loads weights_path into the registry's cached instance.",
    "Weights reach executors because the driver serializes that loaded instance's state_dict; get_plugin_class_map() lets executors rebuild the class by name.", ""],
  "models/pipelines/ner_translate/pipeline.py": ["Pipeline contract adapter: load() -> resolve the three model folders (model store or models/weights), install GLiNER's backbone hub cache (hf_cache), mt_ner_all_formats.load_models(); run(loaded, paths, labels) -> process_paths_batched().",
    "hf_cache holds microsoft/mdeberta-v3-base's config + tokenizer in Hugging Face cache layout; GLiNER resolves its encoder by that hub name, so offline it must be in the process's hub cache - _install_hf_cache copies it there because the cache location is fixed at transformers import time.", ""],
  "models/pipelines/ner_translate/serve.py": ["FastAPI kitchen: loads the pipeline once at startup; GET /health; POST /predict {paths, labels} -> {basename: result}.",
    "No authentication and no request size limits - keep it on a private network (see 10.3).", ""],
  "models/pipelines/ner_translate/mt_ner_all_formats.py": ["The document pipeline: extract text from 20+ formats (OCR for images/scanned PDFs), detect language (py3langid), translate non-English chunks with NLLB-200, extract entities with GLiNER, add regex phone numbers, dedupe, batch across documents.",
    "Offline by design: weights under models/weights/, TRANSFORMERS_OFFLINE / HF_HUB_OFFLINE honoured; OCR languages auto-filtered to installed tesseract packs.", ""],
  "monitoring/cloudwatch_publisher.py": ["CloudWatchPublisher: dimensions (InstanceId via IMDSv2, NodeRole, extras) + put_metric/put_metrics.", "", ""],
};
const groups = [["4.1 Entry points", ["submit_job.py", "submit_pipeline_job.py"]],
  ["4.2 Execution engines (inference/)", F ? API.files.filter((f) => f.path.startsWith("inference/") && f.path !== "inference/__init__.py").map((f) => f.path) : []],
  ["4.3 Model layer (models/)", API.files.filter((f) => f.path.startsWith("models/") && f.ext === ".py" && !f.path.endsWith("__init__.py") || f.path === "models/__init__.py").map((f) => f.path)],
  ["4.4 Data generators (data/)", API.files.filter((f) => f.path.startsWith("data/") && f.ext === ".py" && !f.path.endsWith("__init__.py")).map((f) => f.path)],
  ["4.5 Monitoring (monitoring/)", API.files.filter((f) => f.path.startsWith("monitoring/") && !f.path.endsWith("__init__.py")).map((f) => f.path)]];
groups.forEach(([title, paths]) => {
  H2(title);
  paths.forEach((p) => {
    const f = F[p]; if (!f) return;
    H3(`${p}  (${f.lines} lines)`);
    const d = DESIGN[p];
    P(`**Responsibility.** ${d ? d[0] : fileDoc(p)}`);
    if (d && d[1]) P(`**Design.** ${d[1]}`);
    if (d && d[2]) P(`**Invariants / pitfalls.** ${d[2]}`);
    const api = [];
    (f.classes || []).forEach((c) => { api.push([`class ${c.name}(${c.bases.join(", ")})`, c.line, c.doc.slice(0, 160)]);
      c.methods.filter((m) => !m.name.startsWith("_") || m.name === "__init__").forEach((m) => api.push([`  .${m.name}${m.sig}`, m.line, m.doc.slice(0, 140)])); });
    (f.functions || []).filter((fn) => !fn.name.startsWith("_") || ["_get_class_map", "_serialize_model"].includes(fn.name)).forEach((fn) => api.push([`${fn.name}${fn.sig}`, fn.line, fn.doc.slice(0, 160)]));
    if (api.length) table([["public API", "line", "summary"], ...api], [46, 6, 48], [0]);
    if ((f.imports || []).length) P(`**Imports from the platform:** ${[...new Set(f.imports)].join(", ")}`);
  });
});
H2("4.6 Built-in models");
table([["name", "class (file)", "input", "output", "category", "est. MB"],
  ["ew_classifier", "EWSignalClassifier (models/ew_signal_model.py)", "(128,)", "8-class logits", "signal", "50"],
  ["signal_denoiser", "SignalDenoiser (models/signal_models.py)", "(128,)", "128-d denoised signal (autoencoder)", "signal", "100"],
  ["threat_prioritizer", "ThreatPrioritizer (models/signal_models.py)", "(128,)", "scalar priority (multi-head attention)", "signal", "350"],
  ["rf_fingerprinter", "RFFingerprinter (models/signal_models.py)", "(128,)", "32-d embedding (1-D CNN)", "signal", "120"],
  ["anomaly_detector", "AnomalyDetector (models/signal_models.py)", "(128,)", "scalar reconstruction error (VAE)", "signal", "100"],
  ["resnet18 / mobilenetv3 / efficientnet_b0", "torchvision wrappers (models/image_models.py)", "(3,224,224)", "1000 logits", "image_classification", "300 / 150 / 200"],
  ["yolov8_nano / yolov8_small", "YOLOv8Wrapper (models/yolo_model.py)", "(3,640,640)", "ultralytics: detection count per image; fallback CNN: 400 values", "object_detection", "200 / 400"]],
[18, 30, 9, 23, 12, 8]);
P("Pretrained torchvision weights are downloaded into the image at build time (deploy/Dockerfile) so executors do not reach the internet; without them the wrappers fall back to random initialisation (image_models.py try/except).");

// ------------------------------------------------------------------ 5 traces
H1("5. Request-to-response traces");
P("Each trace lists every step with the exact source line, the data at that point, and where to look when it goes wrong. Step numbers match the sequence diagrams.");
const traceTable = (rows) => table([["#", "where", "what happens", "data / state", "observe / debug"], ...rows], [4, 25, 31, 20, 20], [1], 16);
H2("5.1 submit_job.py --engine rdd (BYOM model on a cluster)");
img("tdd_seq_submit_rdd", "Figure 5.1 - one BYOM job end to end");
traceTable([
  ["1", R("submit_job.py", "main"), "parse --model/--input/--samples/--mode/--partitions/--batch-size/--master/--engine", "argparse Namespace", "`--help`; bad model -> SystemExit listing registered names"],
  ["2", L("submit_job.py", "registry = get_default_registry()"), "built-in registry + register_plugins() from models/plugins/manifest.json", "ModelRegistry with 10 + plugins", "ImportError here = plugin module path wrong"],
  ["3", L("submit_job.py", "if args.input:"), "load .npy (cast float32) or generate np.random.randn(n, *input_shape)", "ndarray (N, *input_shape)", "shape mismatch surfaces later as a forward() error in the executor log"],
  ["4", L("submit_job.py", "model = registry.load_model(args.model"), "instantiate + eval on CPU in the driver (weights_path loaded by the plugin loader)", "nn.Module", "driver memory"],
  ["5", R("inference/cluster_engine.py", "create_cluster_session"), "SparkSession: master = arg > SPARK_MASTER_URL/SPARK_MASTER > local[4]; configs; GPU resources if requested", "SparkSession 'byom-<model>'", "Spark UI :4040; master UI :8080 shows the app and granted cores"],
  ["6", R("inference/cluster_engine.py", "run_cluster_inference"), "entry of the RDD engine", "data {name: array}, models {name: module}", ""],
  ["7", L("inference/cluster_engine.py", "model_bytes_map = {name: _serialize_model(m)"), "torch.save(state_dict) per model -> sc.broadcast; broadcast B and device_mode too", "bytes (~45 MB ResNet18)", "event log: task deserialize time; executor fetches broadcast pieces"],
  ["8", L("inference/cluster_engine.py", "for i in range(num_partitions):"), "slice every array into P chunks (last takes the remainder), parallelize P (i, chunk_dict) elements", "P RDD elements", "partition sizes = N / P"],
  ["9", L("inference/cluster_engine.py", "partition_results = data_rdd.mapPartitions(process_partition).collect()"), "one job, one stage, P tasks scheduled onto free executor slots", "tasks", "Spark UI Stages tab; event log TaskStart/TaskEnd"],
  ["10", R("inference/cluster_engine.py", "process_partition"), "Python worker receives the pickled partition; sys.path gets /app entries", "partition iterator", "executor stderr: Python tracebacks"],
  ["11", L("inference/cluster_engine.py", "if mode == \"gpu_only\":"), "device per task: cpu_only -> cpu; gpu_only/hybrid -> cuda if available (gpu_only warns on fallback)", "device", "'[WARN] gpu_only mode but CUDA not available' in executor stdout"],
  ["12", L("inference/cluster_engine.py", "model_load_start = time.time()"), "rebuild each model class from _get_class_map(), load_state_dict(broadcast bytes), .to(device) - per task", "loaded_models", "'[Executor] host=... model_load_time=...' line in executor stderr"],
  ["13", L("inference/cluster_engine.py", "for start in range(0, n_samples, bs):"), "for each model, batches of B: from_numpy -> .to(device) (pageable H2D) -> forward", "outputs discarded, counts kept", "nvidia-smi on the worker; torch.profiler"],
  ["14", L("inference/cluster_engine.py", "yield {"), "per-partition dict: host, device, load/infer seconds, counts", "dict (~2 KB)", "results JSON partition_details"],
  ["15-16", L("inference/cluster_engine.py", "for pr in partition_results:"), "driver aggregates per-model counts, throughput = samples / wall", "result dict", ""],
  ["17", R("inference/cluster_engine.py", "_capture_spark_ui_stats"), "snapshot of jobs/stages/executors from localhost:4040 (only if the driver's UI is there)", "spark_ui_stats", "empty dict when 4040 is not local"],
  ["18", R("submit_job.py", "_write_results"), "print summary, write results/<model>_<ts>.json, upload to S3 if ARTIFACTS_BUCKET", "file", "results/"]]);
H2("5.2 submit_job.py --engine udf");
img("mode_udf", "Figure 5.2 - pandas UDF engine");
traceTable([
  ["1-5", "same as 5.1", "", "", ""],
  ["6", R("inference/cluster_engine_udf.py", "run_cluster_inference_udf"), "per model: serialize weights, pick requested device (cpu_only -> cpu, else cuda)", "", ""],
  ["7", L("inference/cluster_engine_udf.py", "rows = [Row(input=row.reshape(-1).tolist()) for row in arr]"), "each sample becomes a Python list of floats on the driver", "N Row objects (memory!)", "driver RSS; slow for images"],
  ["8", L("inference/cluster_engine_udf.py", "df = spark.createDataFrame(rows, schema=schema).repartition(num_partitions)"), "DataFrame with explicit schema; repartition = shuffle stage", "DataFrame", "event log: stage with shuffle write bytes"],
  ["9", L("inference/cluster_engine_udf.py", "result_df = df.select(udf(df.input)"), "Arrow batches (maxRecordsPerBatch 10,000) to each Python worker", "Arrow record batches", "stage 2 tasks"],
  ["10", R("inference/predict_batch_udf.py", "_predict"), "per task: build model, load weights, resolve device; per Arrow batch: rows -> np.stack -> chunks of B -> model -> .tolist()", "pd.Series of lists", "'predict_batch_udf: skipping malformed row' warnings"],
  ["11", L("inference/cluster_engine_udf.py", "collected = result_df.collect()"), "predictions back to the driver", "list of rows", "task result size in the event log"],
  ["12", L("inference/cluster_engine_udf.py", "return {"), "same keys as the RDD engine + predictions", "", ""]]);
H2("5.3 submit_pipeline_job.py (cluster and service execution)");
img("tdd_seq_pipeline", "Figure 5.3 - pipeline job, in-process vs kitchen");
traceTable([
  ["1", L("submit_pipeline_job.py", "manifest = _load_manifest()"), "manifest lookup, collect input files (dir, glob or file)", "paths", "'Unknown pipeline' / 'No input files found'"],
  ["2", L("submit_pipeline_job.py", "master_url = _resolve_master_url("), "master precedence; session with --driver-memory/--executor-memory", "SparkSession 'pipeline-<name>'", ""],
  ["3", L("submit_pipeline_job.py", "if args.execution_mode == \"service\":"), "choose service / cluster / auto", "use_service", "'[submit_pipeline_job] execution-mode=... ->' line"],
  ["4a", R("inference/text_pipeline_engine.py", "run_text_pipeline_job"), "cluster: parallelize paths into min(P, files) partitions; per task load() then run()", "", "load_time_sec in partition_details"],
  ["5a", R("models/pipelines/ner_translate/pipeline.py", "load"), "GLiNER + NLLB + language id loaded in every task", "loaded dict", "executor stderr, GPU memory"],
  ["6a", R("models/pipelines/ner_translate/mt_ner_all_formats.py", "process_paths_batched"), "extract -> language -> translate -> NER -> dedupe, batched across documents", "{basename: result}", "per-file 'error' entries"],
  ["4b", R("inference/text_pipeline_engine.py", "run_text_pipeline_job_via_service"), "service: each task POSTs {paths, labels} to <service_url>/predict (600 s timeout)", "HTTP request", "requests exceptions in executor stderr"],
  ["5b", R("models/pipelines/ner_translate/serve.py", "predict"), "kitchen runs pipeline.run() with models loaded once at startup", "JSON", "docker logs ner-translate-server"],
  ["7", L("submit_pipeline_job.py", "summary = {k: v for k, v in result.items() if k != \"results\"}"), "print summary + per-document line; write results/<pipeline>_<ts>.json (UTF-8)", "file", "results/"]]);
H2("5.4 run_benchmark.py --mode single_gpu | hybrid | distributed");
traceTable([
  ["1", R("benchmark/run_benchmark.py", "main"), "registry.load_all(cpu), generate_mixed_data(signals, images, detections)", "10 models, data dict", "RUN_NAME env names the output files"],
  ["2", R("benchmark/run_benchmark.py", "run_mode_single_gpu"), "run_single_gpu_inference: models to GPU, 3 warm-ups, batch loop over CUDA streams", "", "avg / p99 batch latency"],
  ["3", R("benchmark/run_benchmark.py", "run_mode_hybrid"), "run_hybrid_inference: GPUMemoryManager placement, streams + CPU thread pool", "gpu_models / cpu_models", "placement printed"],
  ["4", R("benchmark/run_benchmark.py", "run_mode_distributed"), "create_spark_session(num_cores='4') + run_distributed_gpu_inference (rdd.map per partition element)", "", "'EXECUTOR / WORKER DETAIL' table"],
  ["5", R("benchmark/run_benchmark.py", "generate_report"), "markdown report + raw JSON under results/", "files", "results/report_*.md, results_*.json"]]);
H2("5.5 Where the time goes (measured)");
table([["hop", "typical cost (T4 node, 10 models)", "source"],
  ["Spark application start + executor launch", "3-6 s", "event log app start -> first task"],
  ["first task on a Python worker: worker start, imports, broadcast fetch", "~5.5 s", "event-log task time minus the task's own report"],
  ["model build + load per task", "2.2 s cold / 0.6 s warm", "[Executor] lines"],
  ["inference per partition (GPU)", "0.04-0.54 s", "partition_details"],
  ["same 10 models in one process (single_gpu)", "58,842 samples/s", "svs_single_gpu"]], [45, 25, 30]);

// ------------------------------------------------------------------ 6 extending
H1("6. Extending the framework");
img("tdd_plugin_flow", "Figure 6.1 - extension points");
H2("6.1 Add a tensor model (BYOM plugin) - no framework edits");
N(["Create `models/plugins/my_model.py` with an `nn.Module` whose `__init__` takes no required arguments and whose `forward(x)` is batch-first and returns a tensor.",
  "Add an entry to `models/plugins/manifest.json` (fields below). `module` must be importable from the repo root on every node (the image copies the repo to /app; compose files mount models/).",
  "Optional trained weights: set `weights_path` to a state_dict file readable by the driver; the driver loads it and broadcasts the weights.",
  "Run locally: `python submit_job.py --model my_model --samples 2000 --mode cpu_only --master local[2]`, then on the cluster with `--mode hybrid --partitions <2 x slots>`.",
  "Add a unit test (9.2) and, for Triton serving, an entry in benchmark/triton_export.py EXPORT."], "numbers");
code(`# models/plugins/my_model.py
import torch.nn as nn

class MyModel(nn.Module):
    def __init__(self, input_dim=64, num_classes=4):   # no required args
        super().__init__()
        self.net = nn.Sequential(nn.Linear(input_dim, 128), nn.ReLU(), nn.Linear(128, num_classes))

    def forward(self, x):                              # x: (batch, 64) float32
        return self.net(x)`);
code(`// models/plugins/manifest.json
{
  "my_model": {
    "module": "models.plugins.my_model",
    "class_name": "MyModel",
    "input_shape": [64],
    "weights_path": "models/weights/my_model.pt",
    "output_desc": "4-class logits",
    "category": "custom",
    "estimated_memory_mb": 10
  }
}`);
table([["field", "required", "meaning"],
  ["module / class_name", "yes", "import path and class; executors rebuild the class from these"],
  ["input_shape", "yes", "per-sample shape; used for random inputs and by the UDF engine to reshape rows"],
  ["weights_path", "no", "state_dict loaded in the driver, then broadcast"],
  ["output_desc, category, estimated_memory_mb", "no", "documentation and GPU budget planning (hybrid mode)"]], [25, 10, 65]);
H2("6.2 Add a built-in model");
N([`Implement the class under models/ (same contract as a plugin).`,
  `Register it in get_default_registry() (${R("models/__init__.py", "get_default_registry")}).`,
  `Add it to the executor class map in _get_class_map() (${R("inference/cluster_engine.py", "_get_class_map")}) - otherwise executors silently skip it (the loader only loads names present in the class map).`,
  "If run_benchmark / distributed_gpu should include it, extend the data generator (data/image_generator.generate_mixed_data) with an input array under the model's name.",
  "Rebuild the image if weights must be baked in (deploy/Dockerfile) for air-gapped executors."]);
H2("6.3 Add a file pipeline");
N(["Create `models/pipelines/<name>/pipeline.py` exposing `load()` (returns any state) and `run(loaded, paths, **kwargs)` returning `{basename: result}`.",
  "Declare `models/pipelines/<name>/requirements.txt` for its own dependencies - never add them to the root requirements.txt (docs/MODEL_CONTAINER_ISOLATION.md).",
  "Add a manifest entry in `models/pipelines/manifest.json`: module (required), master_url (dedicated cluster, optional), service_url (kitchen, optional).",
  "In-process execution: build an image FROM multi-model-inference with those deps (pattern: deploy/Dockerfile.ner_translate; offline: scripts/build_ner_translate_wheelhouse.sh and build_ner_translate_debs.sh).",
  "Service execution: add serve.py (copy ner_translate/serve.py - load once at startup, POST /predict), an image (Dockerfile.ner_translate_server pattern) and a compose service; Spark then runs on spark-lean.",
  "Run: `python submit_pipeline_job.py --pipeline <name> --input <dir> --execution-mode cluster|service --master <url>`."]);
code(`# models/pipelines/my_pipeline/pipeline.py
def load():
    from transformers import pipeline as hf_pipeline          # heavy deps imported here
    return {"clf": hf_pipeline("text-classification", model="models/weights/my-clf")}

def run(loaded, paths, **kwargs):
    import os
    out = {}
    for p in paths:
        text = open(p, encoding="utf-8", errors="replace").read()
        out[os.path.basename(p)] = {"label": loaded["clf"](text[:2000])[0]}
    return out`);
H2("6.4 Add an execution engine");
N(["Create `inference/<engine>.py` with `run_<engine>(spark, data, models, num_partitions, batch_size, device_mode) -> dict` returning at least the keys of run_cluster_inference (mode, device_mode, elapsed_time, total_samples_processed, total_throughput, per_model_processed, num_partitions, num_models, batch_size, partition_details, spark_ui_stats, timestamp) so submit_job and reports work unchanged.",
  "Rebuild models on executors from `_get_class_map()` + broadcast state_dict bytes (never pickle modules); resolve the device inside the task.",
  "Wire it into submit_job.py `--engine` choices; keep the default engine unchanged.",
  "Add it to benchmark/spark_modes_stats.py so its job/stage/task statistics are measured like the others."]);
H2("6.5 Serve a model through Triton");
N(["Add the model to EXPORT in benchmark/triton_export.py (sample shape, max_batch_size, preferred batch sizes).",
  "`python benchmark/triton_export.py --out <model_repository>` then start tritonserver with that repository.",
  "`python benchmark/triton_export.py --verify <host>:8001` compares Triton outputs with eager PyTorch.",
  "Call it from Spark with pyspark.ml.functions.predict_batch_udf and a tritonclient gRPC client (see spark_modes_stats.triton_pbu)."]);
H2("6.6 Store models in HDFS or on the master's file system (air-gapped)");
N(["Upload once: `hdfs dfs -put gliner-multi nllb-200-distilled-600M hf_cache /models/weights/` (or copy the folders to a directory every node mounts read-only).",
  "Set `MODEL_STORE_URI=hdfs://<namenode>:8020/models/weights` (or `file:///<shared dir>`) on the model server and on every Spark worker; optionally `MODEL_CACHE_DIR` on a local disk with >= 5 GB free.",
  "Nodes need WebHDFS access to the namenode (9870) and every datanode (9864).",
  "For a plugin, set its manifest `weights_path` to an hdfs:// or file:// URI - plugin_loader resolves it through the model store.",
  "Simulate and test on one machine: deploy/docker-compose.airgap_sim.yml + deploy/airgap_sim_tests.ps1 (docs/CLUSTER_RUNBOOK_MODES_AND_TESTS.pdf)."]);
H2("6.7 Add a benchmark phase, a metric or a deployment");
B(["**Benchmark phase:** add a `run <name> <script> <args>` line to benchmark/run_campaign.sh; summarize_campaign.py parses status and throughput from its log automatically when it prints 'Total Throughput' or a JSON with total_throughput.",
  "**Metric:** use CloudWatchPublisher(namespace, node_role).put_metric(name, value, unit) (monitoring/cloudwatch_publisher.py); follow gpu_metrics_publisher.py for a polling loop.",
  "**Deployment:** new compose file -> reuse the x-app anchor pattern of deploy/docker-compose.laptop.yml; new AWS stack -> copy spark_cluster/modes_cluster_stack.py (DL AMI, SSM, self-referencing security group) and register it in deploy/aws-cdk/app.py."]);

// ------------------------------------------------------------------ 7 configuration
H1("7. Configuration reference");
H2("7.1 Environment variables");
const envs = {};
API.files.forEach((f) => (f.env || []).forEach((e) => { envs[e.name] = envs[e.name] || []; envs[e.name].push(`${f.path}:${e.line}`); }));
const ENVDOC = { MODEL_STORE_URI: "where models are loaded from: hdfs://<namenode>:8020/<dir>, file:///<shared dir> or unset (repository)", MODEL_CACHE_DIR: "node-local cache for models fetched from HDFS", MODEL_STORE_WEBHDFS: "WebHDFS base URL override", MODEL_STORE_USER: "HDFS user for WebHDFS", SPARK_MASTER_URL: "Spark master URL for sessions (else local[N])", SPARK_MASTER: "fallback name for the master URL", ARTIFACTS_BUCKET: "S3 bucket for results upload / pulls (AWS nodes)", FORCE_DEVICE: "quick_compare: force cpu/cuda", RUN_NAME: "prefix for run_benchmark output files", TRANSFORMERS_OFFLINE: "offline Hugging Face loading (ner_translate)", HF_HUB_OFFLINE: "offline Hugging Face hub", AWS_REGION: "region for CloudWatch/S3 clients", CDK_DEFAULT_ACCOUNT: "CDK account fallback", HOSTNAME: "node name in metrics" };
const extra = [["PYSPARK_PYTHON / PYSPARK_DRIVER_PYTHON", "Python executable for workers / driver (set in the images)", "deploy/Dockerfile"],
  ["PYSPARK_SUBMIT_ARGS", "extra spark-submit --conf options (e.g. event logs) before the JVM starts", "benchmark/run_campaign.sh, spark_modes_stats.py"],
  ["CUDA_VISIBLE_DEVICES / NVIDIA_VISIBLE_DEVICES", "GPU visibility; empty = CPU-only worker (compose CPU workers)", "compose files, create_cluster_session executorEnv"],
  ["SPARK_LOCAL_IP", "address Spark binds/advertises (multi-node with host networking)", "deploy/scripts/modes_node.sh"],
  ["SPARK_WORKER_OPTS", "worker resources, e.g. GPU amount + discovery script", "deploy/scripts/modes_node.sh"]];
table([["variable", "meaning", "read at"], ...Object.entries(envs).map(([k, v]) => [k, ENVDOC[k] || "", [...new Set(v)].join(", ")]), ...extra], [22, 38, 40], [0]);
H2("7.2 Spark configuration set in code");
table([["setting", "create_cluster_session", "create_spark_session (distributed_gpu)", "why"],
  ["spark.driver.memory / executor.memory", "6g / 4g (arguments)", "6g / 4g", "driver holds all input data; executors hold models"],
  ["spark.executor.cores / spark.task.cpus", "4 / 2", "4 / 2", "2 concurrent tasks per executor (each task uses multi-threaded torch)"],
  ["spark.rpc.message.maxSize", "512 MB", "512 MB", "partitions are embedded in task payloads"],
  ["spark.driver.maxResultSize", "4g", "4g", "collect() of results / predictions"],
  ["spark.network.timeout / executor.heartbeatInterval", "600 s / 120 s", "600 s / 120 s", "long model loads without false executor loss"],
  ["spark.python.worker.reuse / .memory", "true / 4g", "true / 4g", "keep Python workers (and imports) between tasks"],
  ["executorEnv PYTHONPATH, CUDA_VISIBLE_DEVICES=0, LD_LIBRARY_PATH", "non-local masters", "non-local masters", "executors import /app code and see GPU 0"],
  ["executor/task GPU resources", "gpu_aware_scheduling=True: 1 / 0.5 + discovery script", "-", "place tasks only on GPU executors"]], [24, 24, 22, 30]);
H2("7.3 Command-line reference (generated)");
API.files.filter((f) => (f.cli || []).length).forEach((f) => {
  H3(f.path);
  table([["option", "default", "choices / type", "help"], ...f.cli.map((c) => [c.opts.join(", "), c.default || (c.required ? "required" : ""),
    [c.choices, c.type, c.action].filter(Boolean).join(" "), (c.help || "").slice(0, 220)])], [18, 12, 18, 52], [0, 1, 2], 15);
});

// ------------------------------------------------------------------ 8 debugging
H1("8. Debugging and tracing");
img("tdd_observability", "Figure 8.1 - where every signal lives");
H2("8.1 Trace one job end to end");
N(["Driver console: the app name (`byom-<model>`, `pipeline-<name>`, `ClusterBench_*`) and any Python exception with the failing task's traceback.",
  "Spark UI (`http://<driver>:4040`) -> Jobs -> the job -> Stages -> Tasks: executor, host, duration, GC, shuffle, errors. Master UI (`:8080`) shows which workers granted executors.",
  "Executor logs: `/opt/spark/work/<app-id>/<executor-id>/stderr` on the worker (docker exec into the worker container). Look for `[Executor] host=... device=... model_load_time=...` (RDD engine) or `[MODEL_LOAD]` (spark_modes_stats) and Python tracebacks.",
  "Correlate: the task's host + launch time -> the executor -> the Python worker pid in its log line -> the partition_details entry in results/*.json (same hostname, device, timings).",
  "Persist everything: run with `PYSPARK_SUBMIT_ARGS=\"--conf spark.eventLog.enabled=true --conf spark.eventLog.dir=file:///path pyspark-shell\"` (Linux) and turn the logs into tables and task timelines with `python benchmark/analyze_modes_stats.py <dir>`."]);
H2("8.2 Debugging techniques");
table([["goal", "technique"],
  ["reproduce an executor failure on your machine", "same command with `--master local[2]` (with spark.task.cpus=2 this runs exactly one task at a time; executor code runs in a local Python worker and logs to the console; local[1] is rejected because a task needs 2 cores)"],
  ["step through executor code", "process_partition is a closure inside run_cluster_inference (it captures the broadcasts), so either run the job with local[2] and a tiny input and add prints/breakpoints (debugpy.listen + wait_for_client inside the function), or temporarily lift its body into a module-level function taking (iterator, model_bytes_map, batch_size, mode) and call it in a notebook"],
  ["see what data reaches a task", "print shapes/dtypes at the start of process_partition / run(); on clusters they land in executor stderr"],
  ["CUDA errors with confusing stack traces", "`CUDA_LAUNCH_BLOCKING=1` (synchronous launches -> error at the real line); `torch.cuda.memory_summary()`"],
  ["GPU utilisation / memory over time", "`nvidia-smi dmon -s pucm -d 1` on the worker; torch.profiler + Chrome trace (benchmark/lowlevel_trace.py kernels section)"],
  ["slow jobs", "event-log task time vs the task's own load/infer report: the gap is worker start, imports, broadcast and scheduling (5.5)"],
  ["HTTP kitchen", "`curl <service_url>/health`; `docker logs ner-translate-server`; call POST /predict with one path"],
  ["hardware-level behaviour", "benchmark/lowlevel_trace.py (ISA, PCIe, kernels, SASS, Spark wire formats)"]], [28, 72]);
H2("8.3 Troubleshooting matrix");
table([["symptom", "cause", "fix"],
  ["DefaultCPUAllocator: not enough memory", "too many concurrent Python workers each holding all models", "fewer slots (local[2] / lower executor cores), fewer partitions, bigger node"],
  ["'The paging file is too small' (Windows), JVM hs_err files", "Windows commit limit exhausted", "close memory hogs, raise pagefile, fewer concurrent tasks"],
  ["HADOOP_HOME and hadoop.home.dir are unset (Windows)", "event logs / Hadoop FS without winutils.exe", "do not enable event logs on Windows, or install winutils"],
  ["CUDA error: out of memory / unknown error", "VRAM or host RAM during CUDA JIT; context poisoned afterwards", "smaller batch, fewer concurrent tasks per GPU, restart the worker"],
  ["no kernel image is available (sm_120 etc.)", "torch wheel lacks the GPU's architecture", "use a wheel built for it (e.g. torch 2.9.1 cu128 for Blackwell), see docs/COMPLETE_ARCHITECTURE_TESTING_AND_AIRGAPPED_GUIDE_20260921.md"],
  ["job waits forever, 'Initial job has not accepted any resources'", "workers advertise fewer cores/memory than spark.executor.cores/memory", "start workers with -c >= 4 and -m >= 4g"],
  ["gpu_only results look like CPU speed", "tasks landed on executors without a GPU and fell back to CPU", "gpu_aware_scheduling=True or separate GPU-only cluster"],
  ["Stage stuck at (0 + N) / M, Docker API 500", "executors OOM-killed inside the Docker/WSL VM", "raise VM memory or run one container with local[2]"],
  ["torch not found when running service mode", "pipeline module imported on the lean image", "use --execution-mode service; the module is only imported in cluster mode"],
  ["Py4J 'timed out' during SparkContext start", "process-wide socket default timeout left set", "keep _host_resolvable()'s restore; avoid socket.setdefaulttimeout elsewhere"],
  ["pandas_udf UNSUPPORTED_SIGNATURE", "`from __future__ import annotations` in the UDF module", "keep real annotations in predict_batch_udf.py"],
  ["createDataFrame hangs on nested lists", "schema inference over nested Python lists", "flatten + explicit schema (as cluster_engine_udf does)"],
  ["image built without torch", "docker build without --target final", "`docker build --target final -f deploy/Dockerfile .`"],
  ["scripts fail with $'\\r' errors", "CRLF line endings from Windows", "`sed -i 's/\\r$//' script.sh` (modes_node.sh does this)"],
  ["two documents 'disappear' from pipeline results", "same basename in different folders overwrite each other", "unique file names or key results by full path"],
  ["GLiNER: couldn't connect to huggingface.co ... mdeberta-v3-base", "GLiNER's backbone not in the offline HF cache", "keep hf_cache next to the model folders (pipeline.load() installs it)"],
  ["cannot reach WebHDFS / not found in HDFS", "HDFS down, wrong MODEL_STORE_URI, or folder not uploaded", "check hdfs dfs -ls, the URI and ports 9870/9864; a warm node cache still works"],
  ["cannot stop container: PID is zombie", "child processes not reaped when Python is PID 1", "init: true in compose"]], [26, 36, 38]);

// ------------------------------------------------------------------ 9 testing
H1("9. Testing strategy");
H2("9.1 Current state");
P("The repository has no automated unit tests; validation has been done with benchmark campaigns (benchmark/run_campaign.sh), live cluster tests (docs/LIVE_CLUSTER_TEST_20260921.md, docs/TESTING_BEFORE_EXPORT.md) and the statistics tools. The pyramid below adds fast tests that run without a cluster or GPU, then contract, integration and performance tests.");
table([["level", "what", "runs where", "time"],
  ["unit", "registry, plugin loader, manifests, row conversion, engines with local[2] and tiny models", "any laptop, CI, no GPU", "< 1 min"],
  ["contract", "every plugin / pipeline in the manifests loads and returns the declared shape", "CI (CPU)", "minutes"],
  ["integration", "docker compose laptop cluster: submit_job rdd/udf, submit_pipeline_job service/cluster", "Docker host", "10-20 min"],
  ["GPU", "gpu_only / hybrid on a GPU worker, Triton export --verify", "GPU runner", "10 min"],
  ["performance", "run_campaign.sh + summarize_campaign.py, spark_modes_stats.py + analyze", "cluster / AWS", "1-2 h"]], [12, 50, 22, 16]);
H2("9.2 Example tests (pytest)");
code(`# tests/test_models.py
import torch, pytest
from models import get_default_registry
from models.plugin_loader import register_plugins, get_plugin_class_map
from inference.cluster_engine import _get_class_map

def test_every_registered_model_is_in_the_executor_class_map():
    reg = get_default_registry(); register_plugins(reg)
    assert set(reg.list_models()) <= set(_get_class_map())      # else executors skip it

@pytest.mark.parametrize("name", ["ew_classifier", "signal_denoiser", "threat_prioritizer",
                                  "rf_fingerprinter", "anomaly_detector", "example_mlp"])
def test_forward_is_batch_first(name):
    reg = get_default_registry(); register_plugins(reg)
    info = reg.get_info(name)
    y = reg.load_model(name)(torch.randn(3, *info.input_shape))
    assert y.shape[0] == 3

def test_state_dict_round_trip():
    reg = get_default_registry()
    m = reg.load_model("ew_classifier")
    m2 = reg.deserialize_model("ew_classifier", reg.serialize_model("ew_classifier"))
    x = torch.randn(4, 128)
    assert torch.allclose(m(x), m2(x))`);
code(`# tests/test_engines.py  (Spark local mode, CPU only; local[2] because spark.task.cpus=2)
import numpy as np, pytest
from inference.cluster_engine import create_cluster_session, run_cluster_inference
from inference.predict_batch_udf import _row_to_array
from inference.text_pipeline_engine import run_text_pipeline_job
from models import get_default_registry

@pytest.fixture(scope="module")
def spark():
    s = create_cluster_session(app_name="tests", master_url="local[2]", driver_memory="1g", executor_memory="1g")
    yield s; s.stop()

def test_rdd_engine_counts_every_sample(spark):
    reg = get_default_registry()
    data = {"ew_classifier": np.random.randn(1000, 128).astype("float32")}
    r = run_cluster_inference(spark, data, {"ew_classifier": reg.load_model("ew_classifier")},
                              num_partitions=3, batch_size=128, device_mode="cpu_only")
    assert r["total_samples_processed"] == 1000
    assert {p["device"] for p in r["partition_details"]} == {"cpu"}

def test_row_to_array_rejects_bad_rows():
    assert _row_to_array([0.0] * 5, 6, (6,)) is None
    assert _row_to_array([0.0] * 6, 6, (2, 3)).shape == (2, 3)

def test_text_pipeline_contract(spark, tmp_path):
    for i in range(3): (tmp_path / f"d{i}.txt").write_text("x" * i)
    load = lambda: {"ok": True}
    run = lambda loaded, paths: {p.split("/")[-1].split("\\\\")[-1]: {"n": len(open(p).read())} for p in paths}
    r = run_text_pipeline_job(spark, [str(p) for p in tmp_path.iterdir()], load, run, num_partitions=2)
    assert len(r["results"]) == 3`);
H2("9.3 Quality gates for a change");
B(["Unit + contract tests green; new model/pipeline has its own test.",
  "`python submit_job.py --model <m> --samples 2000 --master local[2]` (and `--engine udf`) succeed.",
  "Cluster run on the laptop compose file or AWS stack; statistics compared with the previous run (spark_modes_stats + analyze_modes_stats).",
  "For GPU paths: gpu_only run shows device=cuda in every partition detail.",
  "Air-gapped: new dependencies added to the pipeline's wheelhouse / .deb scripts, not fetched at runtime."]);

// ------------------------------------------------------------------ 10 NFR
H1("10. Non-functional design, known issues and technical debt");
H2("10.1 Performance characteristics");
B(["Per-task fixed cost dominates small and medium jobs: worker start + imports + broadcast (~5 s cold) and model rebuild (0.6-2.2 s per task for 10 models) vs 0.04-0.5 s of GPU inference per partition (SPARK_INFERENCE_MODES_AND_TRITON_ARCHITECTURE document).",
  "One process with CUDA streams reaches ~13x the throughput of the Spark engines on the same T4: keep models resident (worker cache, Spark's predict_batch_udf, or Triton).",
  "Windows hosts pay per-task Python process creation and higher CUDA launch latency (WDDM); Linux/WSL2 is preferred for workers."]);
H2("10.2 Scalability and reliability");
B(["Horizontal: add workers; tasks spread over free slots; partitions = 1-2 x total slots for the in-process engines.",
  "Memory: every concurrent Python worker holds all its models + a CUDA context; size slots by host RAM and VRAM, not cores.",
  "Failures: Spark retries tasks (spark.task.maxFailures=4); results are only written after collect() succeeds - partial results are not persisted."]);
H2("10.3 Security");
B(["The ner_translate kitchen exposes unauthenticated HTTP; keep it on a private network or front it with an authenticating proxy.",
  "Spark standalone has no authentication by default; enable spark.authenticate or restrict networks (the AWS modes stack allows only intra-cluster traffic).",
  "Model weights are loaded with `weights_only=True` in the engines; keep it for untrusted weight files.",
  "AWS scripts use SSM (no SSH) and S3 with block-public-access; the account in use is a root login - use an IAM role for automation."]);
H2("10.4 Known issues and technical debt");
table([["#", "issue", "impact", "remedy"],
  ["1", "cluster_engine.process_partition rebuilds models per partition (docstring says per executor)", "fixed cost x partitions", "module-level cache keyed by (model, device) in the Python worker"],
  ["2", "gpu_only silently falls back to CPU on executors without GPUs", "misleading results", "GPU-aware scheduling or fail fast"],
  ["3", "RDD engine discards model outputs", "no predictions from the default engine", "return or write outputs"],
  ["4", "UDF engine builds Python lists on the driver + shuffles", "driver memory, extra stage", "Parquet/Arrow input"],
  ["5", "pipeline results keyed by basename", "silent overwrites", "key by relative path"],
  ["6", "deploy/Dockerfile default target is lean; setup_and_run_gpu.sh omits --target final", "torch-less image", "add --target final"],
  ["7", "SparkInferenceClusterStack starts its CPU worker with -c 2 (< executor cores 4)", "CPU worker never used", "-c 4"],
  ["8", "no automated tests", "regressions caught late", "section 9"]], [4, 40, 22, 34]);

// ------------------------------------------------------------------ 11 roadmap
H1("11. Roadmap");
N(["Model cache in Python workers for the RDD engine (smallest change, largest win for in-process modes).",
  "Engine using pyspark.ml.functions.predict_batch_udf (cached per worker) as the default UDF path.",
  "Triton Inference Server as the shared GPU tier; Spark executors as lean gRPC clients (design in the modes/Triton document).",
  "Columnar inputs (Parquet/Arrow) instead of driver-side Python lists.",
  "pytest suite and CI (section 9)."]);

// ------------------------------------------------------------------ appendices
H1("Appendix A - API reference (every module)");
API.files.filter((f) => f.ext === ".py").forEach((f) => {
  H3(`${f.path}  -  ${f.category}, ${f.lines} lines`);
  if (f.doc) P(f.doc.slice(0, 600));
  const rows = [];
  (f.classes || []).forEach((c) => { rows.push([`class ${c.name}`, c.line, c.doc.slice(0, 200)]);
    c.methods.forEach((m) => rows.push([`  .${m.name}${m.sig}`, m.line, m.doc.slice(0, 160)])); });
  (f.functions || []).forEach((fn) => { rows.push([`${fn.name}${fn.sig}`, fn.line, fn.doc.slice(0, 200)]);
    (fn.nested || []).forEach((n) => rows.push([`  (nested) ${n.name}`, n.line, ""])); });
  if (rows.length) table([["symbol", "line", "docstring (first paragraph)"], ...rows], [48, 5, 47], [0], 15);
});
H1("Appendix B - file inventory");
table([["path", "category", "lines", "description"], ...API.files.map((f) => [f.path, f.category, f.lines, (f.doc || "").slice(0, 150)])], [34, 10, 6, 50], [0], 15);
H1("Appendix C - complete source code");
P("Every file of the repository's code (framework, deployment, benchmarks and tooling), with line numbers matching the file:line references in this document. Excluded: model weights, wheelhouses, .deb bundles, result files, sample data and generated artefacts.");
const ORDER = ["framework", "deployment", "benchmark", "tooling", "other"];
ORDER.forEach((cat) => {
  const files = API.files.filter((f) => f.category === cat);
  if (!files.length) return;
  H2(`C.${ORDER.indexOf(cat) + 1} ${cat} (${files.length} files)`);
  files.forEach((f) => { H3(`${f.path}  (${f.lines} lines)`); code(src(f.path), { numbers: true, size: 13 }); });
});
H1("Appendix D - glossary");
table([["term", "meaning"],
  ["BYOM", "bring your own model: a tensor-model plugin declared in models/plugins/manifest.json"],
  ["broadcast", "read-only value shipped once per executor (TorrentBroadcast); here: serialized state_dicts"],
  ["device_mode", "cpu_only | gpu_only | hybrid, resolved per task"],
  ["driver / executor / Python worker", "job-building process / Spark JVM on a worker / Python process running a task's Python code"],
  ["kitchen / waiter", "model server holding the models (kitchen) and the lean Spark job calling it over HTTP (waiter)"],
  ["partition / task / slot", "slice of data / its unit of work / capacity for one concurrent task (cores / task.cpus)"],
  ["pipeline", "multi-model file-in/results-out plugin with load()/run()"],
  ["predict_batch_udf", "the repo's pandas UDF (inference/predict_batch_udf.py) or Spark's built-in pyspark.ml.functions.predict_batch_udf"],
  ["Triton", "NVIDIA Triton Inference Server (dynamic batching, model repository, gRPC/HTTP)"]], [22, 78]);

// ------------------------------------------------------------------ document
const doc = new Document({
  creator: "pytorch-spark-inference-platform", title: "Technical Design Document - PyTorch-Spark Inference Platform",
  styles: { default: { document: { run: { font: BODY, size: 19 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 32, bold: true, font: BODY, color: "1B1F24" }, paragraph: { spacing: { before: 120, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 25, bold: true, font: BODY, color: ACCENT }, paragraph: { spacing: { before: 220, after: 110 }, outlineLevel: 1, keepNext: true } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true, run: { size: 20, bold: true, font: BODY, color: "1B1F24" }, paragraph: { spacing: { before: 150, after: 60 }, outlineLevel: 2, keepNext: true } }] },
  numbering: { config: [
    { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 500, hanging: 260 } } } }] },
    { reference: "numbers", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 500, hanging: 300 } } } }] }] },
  sections: [{ properties: { page: { size: { width: PH, height: PW, orientation: PageOrientation.LANDSCAPE }, margin: { top: M, bottom: M, left: M, right: M } } },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "TDD - PyTorch-Spark Inference Platform - v1.0", size: 15, color: "8A94A3" })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ children: [PageNumber.CURRENT], size: 15, color: "57606A" })] })] }) },
    children: body }],
});
Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(OUT, buf);
  console.log("wrote", OUT, buf.length, "bytes;", body.length, "blocks");
  if (WARN.length) console.log("WARNINGS:\n  " + [...new Set(WARN)].join("\n  "));
});
