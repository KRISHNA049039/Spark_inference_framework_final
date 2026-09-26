// modes_doc_text_interim.js - document text built from the data available
// BEFORE the 2-node AWS run: the single-node AWS campaign (T4, re-shaped by
// modes_from_campaign.py into results/modes_20260926/aws_1node), the local
// functional run of every engine (local_dry) and the Windows/WSL2/AWS campaign
// summaries. Shared chapters come from modes_doc_text.js.
//   node benchmark/build_modes_docx.js results/modes_20260926/aws_1node,results/modes_20260926/local_dry <out> modes_doc_text_interim.js
const fs = require("fs");
const path = require("path");
const shared = require("./modes_doc_text.js");

exports.build = (c) => {
  const { H1, H2, H3, P, B, N, note, code, table, img, get, fmt, thr, mb, statRows, execTable, gantt, S, DIAG, REPO, readT, inferStage, body } = c;
  const D = (k) => path.join(DIAG, `${k}.png`);
  const A = "aws_1node", L = "local_dry";
  const g = (m, md) => get(m, md, A);
  const sumT = (s, k) => (s ? (s.tasks || []).reduce((a, t) => a + (t[k] || 0), 0) : 0);
  const parts = (s) => (s && s.partition_details) || [];
  const sumP = (s, k) => parts(s).reduce((a, p) => a + (p[k] || 0), 0);
  const camp = JSON.parse(readT(path.join(REPO, "results", "campaign_20260926", "summary.json")) || "{}");
  const cthr = (leg, test, key) => { const r = (camp[leg] || []).find((x) => x.test === test); if (!r) return null; const t = r.throughput || {}; return key ? t[key] : Object.values(t).slice(-1)[0]; };
  const lowAws = JSON.parse(readT(path.join(REPO, "results", "campaign_20260926", "aws_g4dn", "lowlevel", "lowlevel.json")) || "{}");
  const exportRep = JSON.parse(readT(path.join(REPO, "results", "modes_20260926", "triton_export_local", "export_report.json")) || "{}");
  const p3g = g("platform10_3k", "rdd_gpu"), p3c = g("platform10_3k", "rdd_cpu"), p3h = g("platform10_3k", "rdd_hybrid");
  const loadS = sumP(p3g, "model_load_time_sec"), infS = sumP(p3g, "inference_time_sec");
  const p16 = g("platform10_5k", "dist_p16");
  const svsT4 = cthr("aws_g4dn", "svs_single_gpu", "single_gpu_parallel_streams");
  const bestSparkT4 = cthr("aws_g4dn", "p1_dist_large");
  const mlpR = g("example_mlp", "rdd_cpu"), mlpU = g("example_mlp", "udf_cpu");

  // ============================================================ title
  const { Paragraph, TextRun, TableOfContents } = require("docx");
  body.push(new Paragraph({ spacing: { before: 1300, after: 200 }, children: [new TextRun({ text: "Spark Distributed Inference", size: 60, bold: true })] }));
  body.push(new Paragraph({ spacing: { after: 160 }, children: [new TextRun({ text: "How Spark distributes inference in every execution mode, worker- and task-level statistics, and the recommended architecture with Triton Inference Server in front of the cluster", size: 26, color: "57606A" })] }));
  body.push(new Paragraph({ spacing: { after: 200 }, children: [new TextRun({ text: "Edition 1 (26 September 2026): measured on AWS g4dn.xlarge (Tesla T4, Spark master + worker containers) and a Windows/WSL2 laptop; the 2-node CPU+GPU cluster run with Triton is prepared and will extend sections 7-9.", size: 20, color: "57606A" })] }));
  note("Status of the evidence: RDD engine (cpu_only / gpu_only / hybrid), the older distributed_gpu engine and the repo's pandas UDF are measured on AWS with Spark event logs and executor logs. Spark's built-in predict_batch_udf is measured functionally (local run: stages, tasks, model loads). GPU-aware scheduling, cross-worker placement and Triton throughput need the 2-node run (deploy/run_aws_modes.ps1); those sections describe the design and what will be measured.", "FFF8E6", "D6B656");
  body.push(new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" }));

  // ============================================================ 1 summary
  H1("1. Executive summary");
  B([
    `**GPU vs CPU executors, 10-model workload (T4 node):** rdd_gpu ${thr(p3g)} vs rdd_cpu ${thr(p3c)} (${fmt(p3g.throughput / p3c.throughput, 1)}x); hybrid ${thr(p3h)} = gpu on a single GPU node, because hybrid only differs when some executors lack a GPU.`,
    `**Model loading dominates GPU tasks:** in rdd_gpu the 4 tasks spent ${fmt(loadS, 2)} s building and loading models vs ${fmt(infS, 2)} s running inference (${fmt(loadS / infS, 1)}x). Each Python worker pays ~2.2 s on its first task (CUDA context + model construction) and ~0.6 s on every later task, because cluster_engine.process_partition() rebuilds the models for every partition.`,
    `**More partitions = more model loads:** with the distributed_gpu engine, 16 partitions took ${fmt(p16 ? p16.wall_s : null, 1)} s vs ${fmt(g("platform10_5k", "dist_p4").wall_s, 1)} s with 4 (throughput ${thr(p16)} vs ${thr(g("platform10_5k", "dist_p4"))}): per-task inference fell to ~0.04 s while each task still loads 10 models (~0.6 s).`,
    `**Spark is far from the GPU's capability:** the same T4 serves the 10 models at ${fmt(svsT4, 0)} samples/s from one process with CUDA streams, vs ${fmt(bestSparkT4, 0)} samples/s for the best Spark distributed run (${fmt(svsT4 / bestSparkT4, 0)}x gap) - the gap is per-task setup, serialization and Python/JVM hand-offs, not compute.`,
    `**pandas UDF vs RDD (example_mlp, 20k samples):** RDD ${thr(mlpR)} vs pandas UDF ${thr(mlpU)}. The UDF job has 2 stages (a repartition shuffle writing ${mb(sumT(mlpU, "shuffle_write_bytes"))} MB, then the UDF) and returns real predictions (${mb(sumT(mlpU, "result_bytes"))} MB of results vs ${mb(sumT(mlpR, "result_bytes"))} MB of counts).`,
    `**Spark's built-in predict_batch_udf caches the model per Python worker:** in the local functional run it loaded the model ${(get("ew_classifier", "native_pbu_gpu", L) || {}).model_loads ? get("ew_classifier", "native_pbu_gpu", L).model_loads.length : "?"} time(s) for ${(get("ew_classifier", "native_pbu_gpu", L) || { tasks: [] }).tasks.length} tasks, vs ${(get("ew_classifier", "rdd_cpu", L) || { model_loads: [] }).model_loads.length} loads for ${(get("ew_classifier", "rdd_cpu", L) || { tasks: [] }).tasks.length} tasks on the RDD engine.`,
    "**Recommendation:** Triton Inference Server as a shared GPU tier in front of the cluster (models loaded once per GPU, dynamic batching across Spark tasks and online callers), Spark executors as lean CPU-only clients through `pyspark.ml.functions.predict_batch_udf`, columnar (Parquet/Arrow) inputs, GPU-aware scheduling only where in-process inference must stay. Details in section 12, alternatives in section 13.",
  ]);

  // ============================================================ 2 setup
  H1("2. Where the numbers come from");
  table([["source", "cluster", "what it provides"],
    ["AWS g4dn.xlarge campaign (results/campaign_20260926/aws_g4dn)", "Spark standalone: master container + GPU-worker container on one g4dn.xlarge (4 vCPU, 16 GB, Tesla T4); 1 executor, 4 cores, spark.task.cpus=2 -> 2 task slots",
      "32 Spark event logs (per job/stage/task), executor stdout/stderr with each Python worker's model-load events, per-partition device and timings, T4 low-level trace"],
    ["Laptop Windows 11 and WSL2 campaigns", "Spark local[2] (1 concurrent task) on i5-9300H + GTX 1650", "the same engines on a small machine; Windows vs Linux process model"],
    ["Local functional run (results/modes_20260926/local_dry)", "Spark local[2] in the platform image", "every engine incl. Spark's native predict_batch_udf: stages, tasks, shuffle, model-load counts (tiny data - structure, not speed)"],
    ["Triton export check (results/modes_20260926/triton_export_local)", "PyTorch 2.14 on the laptop", "TorchScript export of resnet18 / ew_classifier, traced vs eager max abs diff, generated config.pbtxt"],
    ["Prepared, not yet run: 2-node AWS (deploy/run_aws_modes.ps1)", "m5.2xlarge CPU worker + g4dn.xlarge GPU worker + Triton", "cross-worker placement, gpu_only fallback, GPU-aware scheduling, native predict_batch_udf and Triton at scale"]],
  [22, 38, 40]);
  img(D("current_cluster"), 980, "Figure 1 - platform topology (the 2-node layout prepared for the next run; the AWS numbers in this edition come from both roles running on the GPU node)");
  H2("2.1 Workloads measured");
  table([["label", "models", "samples", "partitions", "batch", "engine"],
    ["platform10_1k / _3k", "all 10 (5 signal MLPs, ResNet18, MobileNetV3, EfficientNet-B0, 2 YOLO-style)", "5,190 / 15,360", "2 / 4", "256", "cluster_engine (RDD), cluster_benchmark.py"],
    ["platform10_5k (dist_pN)", "all 10", "25,170", "2, 4, 8, 16", "64", "distributed_gpu (RDD), run_benchmark.py --mode distributed"],
    ["example_mlp", "1 plugin MLP (64 -> 4)", "20,000", "4", "256", "submit_job.py --engine rdd / udf"],
    ["local functional", "ew_classifier, resnet18", "2,000 / 5", "4", "1,024 / 64", "rdd, repo UDF, native predict_batch_udf"]],
  [16, 34, 12, 11, 8, 19]);
  H2("2.2 Reading the statistics");
  table([["statistic", "meaning"],
    ["deserialize / run / JVM CPU / GC", "executor time to unpack the task / wall time of the task thread / CPU of the JVM thread only (Python and GPU work are invisible to it) / JVM garbage collection"],
    ["shuffle write / read", "bytes written to and fetched from shuffle files (repartition)"],
    ["model loads", "each '[Executor] ... model_load_time' line a Python worker printed (RDD engine), or each make_predict_fn call (predict_batch_udf)"],
    ["partition details", "what each task reported about itself: device actually used, model-load seconds, inference seconds"],
    ["task slot timeline", "one row per executor slot, one bar per task (colour = stage)"]],
  [22, 78]);

  shared.howSpark(c);

  // ============================================================ 4 RDD engine
  H1("4. RDD engine (cluster_engine.py): cpu_only / gpu_only / hybrid");
  img(D("mode_rdd"), 980);
  P("The platform's default distributed path. The driver slices the numpy arrays into P partition dicts, broadcasts the models' state_dicts, and runs `mapPartitions(process_partition)`. Each task resolves its device itself: cpu_only -> CPU; gpu_only and hybrid -> CUDA when that executor sees a GPU, otherwise CPU.");
  H2("4.1 Statistics - 10-model workload");
  ["rdd_cpu", "rdd_gpu", "rdd_hybrid"].forEach((md) => { H3(md); table(statRows(md, ["platform10_1k", "platform10_3k"], A), [22, 39, 39]); });
  H2("4.2 What each task did (platform10_3k)");
  ["rdd_cpu", "rdd_gpu"].forEach((md) => {
    const s = g("platform10_3k", md); if (!s) return;
    H3(md);
    const loads = s.model_loads || [];
    const tk = (idx) => (s.tasks || []).find((t) => t.index === idx);
    table([["partition", "device", "task wall s (event log)", "model load s (task's report)", "inference s (task's report)", "unaccounted s (worker start, imports, broadcast, results)", "Python worker pid"],
      ...parts(s).map((p, i) => { const t = tk(p.partition_idx); const wall = t ? (t.finish - t.launch) / 1000 : null;
        return [p.partition_idx, p.device, fmt(wall, 2), fmt(p.model_load_time_sec, 2), fmt(p.inference_time_sec, 2),
          wall !== null ? fmt(wall - p.model_load_time_sec - p.inference_time_sec, 2) : "-", loads[i] ? `${loads[i].pid}` : "-"]; })],
    [9, 9, 15, 17, 16, 22, 12]);
  });
  note(`Where a task's time goes: the first task on each slot runs ~8 s in the event log, but only ~2.7 s of that is inside process_partition() (model load + inference). The rest is starting the Python worker, importing torch/torchvision, deserializing the closure and fetching the ~75 MB broadcast of state_dicts. Second-wave tasks reuse the warm worker and finish in ~1.7 s.`);
  note(`Two Python workers (two pids) served the 4 tasks - one per task slot. Each loaded all 10 models on its first task (~2.2 s on GPU, ~1.9 s on CPU) and again on its second (~0.6 s: imports and CUDA context are already warm, but the models are rebuilt). On GPU the model loads (${fmt(loadS, 2)} s in total) cost ${fmt(loadS / infS, 1)}x the inference (${fmt(infS, 2)} s).`);
  H2("4.3 Executor and task timeline");
  execTable(p3h);
  gantt("platform10_3k", "rdd_hybrid", "Task slots over time - platform10_3k rdd_hybrid (2 slots, 2 waves)", A);

  // ============================================================ 5 distributed_gpu partitions
  H1("5. Partition scaling on one executor (distributed_gpu.py)");
  P("run_benchmark.py's distributed mode (inference/distributed_gpu.py) uses the same pattern. Holding data fixed (25,170 samples) and raising the partition count shows how tasks are spread in waves over the executor's 2 slots and what each extra task costs.");
  table([["metric", "2 partitions", "4 partitions", "8 partitions", "16 partitions"],
    ["throughput", ...["dist_p2", "dist_p4", "dist_p8", "dist_p16"].map((m) => thr(g("platform10_5k", m)))],
    ["wall s", ...["dist_p2", "dist_p4", "dist_p8", "dist_p16"].map((m) => fmt(g("platform10_5k", m).wall_s, 2))],
    ["waves over 2 slots", "1", "2", "4", "8"],
    ["inference task min / median / max s", ...["dist_p2", "dist_p4", "dist_p8", "dist_p16"].map((m) => { const st = inferStage(g("platform10_5k", m)); return `${fmt(st.task_ms_min / 1000, 2)} / ${fmt(st.task_ms_median / 1000, 2)} / ${fmt(st.task_ms_max / 1000, 2)}`; })],
    ["sum model load s (tasks' own reports)", ...["dist_p2", "dist_p4", "dist_p8", "dist_p16"].map((m) => fmt(sumP(g("platform10_5k", m), "model_load_time_sec"), 2))],
    ["sum inference s", ...["dist_p2", "dist_p4", "dist_p8", "dist_p16"].map((m) => fmt(sumP(g("platform10_5k", m), "inference_time_sec"), 2))],
    ["sum deserialize s", ...["dist_p2", "dist_p4", "dist_p8", "dist_p16"].map((m) => fmt(sumT(g("platform10_5k", m), "deser_ms") / 1000, 2))]],
  [28, 18, 18, 18, 18]);
  note("Beyond 2 partitions per slot, total inference work barely changes (it is the same data) but every extra task adds a full 10-model load, so throughput falls. Rule of thumb for this engine: partitions = task slots x 1-2, and cache models in the Python worker (section 11).");
  gantt("platform10_5k", "dist_p8", "Task slots over time - 8 partitions on 2 slots (4 waves)", A);
  gantt("platform10_5k", "dist_p16", "Task slots over time - 16 partitions on 2 slots (8 waves)", A);

  // ============================================================ 6 UDF
  H1("6. pandas UDF - the repo's predict_batch_udf (submit_job.py --engine udf)");
  img(D("mode_udf"), 980);
  P("inference/cluster_engine_udf.py builds a DataFrame of flat float arrays (`Row(input=x.reshape(-1).tolist())`), repartitions it, and applies inference/predict_batch_udf.py - a scalar-iterator pandas UDF that builds the model once per task and re-chunks each Arrow batch to the model batch size. It returns predictions; the RDD engine returns counts.");
  H2("6.1 RDD vs pandas UDF on the same model and data (example_mlp, 20,000 samples, T4 node)");
  const eng = ["rdd_cpu", "rdd_gpu", "udf_cpu", "udf_gpu"].map((m) => g("example_mlp", m));
  table([["metric", "rdd_cpu", "rdd_gpu", "udf_cpu", "udf_gpu"],
    ["throughput", ...eng.map(thr)], ["wall s", ...eng.map((s) => fmt(s.wall_s, 2))],
    ["jobs / stages / tasks", ...eng.map((s) => `${s.jobs.length} / ${s.stages.length} / ${s.tasks.length}`)],
    ["stages", ...eng.map((s) => s.stages.map((x) => `s${x.id}: ${x.kind} (${x.tasks})`).join("; "))],
    ["sum run / JVM CPU s", ...eng.map((s) => `${fmt(sumT(s, "run_ms") / 1000, 2)} / ${fmt(sumT(s, "cpu_ms") / 1000, 2)}`)],
    ["shuffle write / read MB", ...eng.map((s) => `${mb(sumT(s, "shuffle_write_bytes"))} / ${mb(sumT(s, "shuffle_read_bytes"))}`)],
    ["results to driver MB", ...eng.map((s) => mb(sumT(s, "result_bytes")))],
    ["model loads", ...eng.map((s) => (s.model_loads.length ? `${s.model_loads.length} (${[...new Set(s.model_loads.map((l) => l.pid))].length} Python workers)` : "once per task (by code)"))]],
  [20, 20, 20, 20, 20]);
  P(`The UDF job does more JVM work (JVM CPU ${fmt(sumT(g("example_mlp", "udf_cpu"), "cpu_ms") / 1000, 2)} s vs ${fmt(sumT(g("example_mlp", "rdd_cpu"), "cpu_ms") / 1000, 2)} s: Arrow conversion, shuffle) and has a shuffle-map stage before the inference stage. For a 64-float MLP the model is trivial, so ingestion and the extra stage decide the throughput; GPU vs CPU makes no difference.`);
  gantt("example_mlp", "udf_gpu", "Task slots over time - example_mlp udf_gpu (stage 0: shuffle map, stage 2: UDF)", A);
  gantt("example_mlp", "rdd_gpu", "Task slots over time - example_mlp rdd_gpu (single stage)", A);

  // ============================================================ 7 native predict_batch_udf
  H1("7. Spark's built-in predict_batch_udf (pyspark.ml.functions)");
  img(D("mode_native_pbu"), 980);
  P("Spark 3.4+ ships `predict_batch_udf(make_predict_fn, return_type, batch_size, input_tensor_shapes)`. `make_predict_fn` runs once per Python worker process and its result is cached, so with worker reuse (spark.python.worker.reuse=true, set by this platform) the model is built once per worker rather than once per task; Spark also assembles exact batches of `batch_size` and reshapes flat arrays to the tensor shape.");
  code(`from pyspark.ml.functions import predict_batch_udf\n\ndef make_predict_fn():                      # once per Python worker (cached)\n    model = EWSignalClassifier(); model.load_state_dict(torch.load(io.BytesIO(bc.value)))\n    model = model.to("cuda").eval()\n    def predict(x: np.ndarray) -> np.ndarray:  # x: (B, 128)\n        with torch.no_grad():\n            return model(torch.from_numpy(x).cuda()).cpu().numpy()\n    return predict\n\nudf = predict_batch_udf(make_predict_fn, return_type=ArrayType(FloatType()),\n                        batch_size=1024, input_tensor_shapes=[[128]])`);
  H2("7.1 Functional comparison of the three engines (local run, same data)");
  const ll = ["rdd_cpu", "udf_gpu", "native_pbu_gpu"].map((m) => get("ew_classifier", m, L));
  table([["metric", "RDD (cluster_engine)", "repo pandas UDF", "native predict_batch_udf"],
    ["jobs / stages / tasks", ...ll.map((s) => (s ? `${s.jobs.length} / ${s.stages.length} / ${s.tasks.length}` : "-"))],
    ["stages", ...ll.map((s) => (s ? s.stages.map((x) => `${x.kind} (${x.tasks})`).join("; ") : "-"))],
    ["model loads", ...ll.map((s, i) => (s ? (i === 1 ? "once per task (by code)" : `${s.model_loads.length} for ${s.tasks.filter((t) => true).length} tasks`) : "-"))],
    ["returns", "counts", "predictions", "predictions"]],
  [22, 26, 26, 26]);
  note("Structure is what this run shows (tiny data: 2,000 signals on local[2]); throughput at scale is measured in the 2-node run.", "FFF8E6", "D6B656");

  // ============================================================ 8 GPU-aware
  H1("8. GPU-aware scheduling (resource profiles)");
  img(D("mode_gpu_aware"), 980);
  P("Plain scheduling places tasks wherever a slot is free. With `gpu_only`, a task that lands on an executor without a GPU silently falls back to CPU (cluster_engine.process_partition prints a warning; hybrid does not). Spark's resource scheduling fixes placement: the GPU worker advertises its GPU through a discovery script and the application asks for one GPU per executor, so executors - and therefore tasks - only start where a GPU exists. On the single-GPU-node run this cannot show a difference (every executor has the GPU); the 2-node run measures both behaviours.");
  code(`# GPU worker\nSPARK_WORKER_OPTS="-Dspark.worker.resource.gpu.amount=1 \\\n  -Dspark.worker.resource.gpu.discoveryScript=/app/deploy/scripts/gpu_discovery.sh"\n\n# application (inference/cluster_engine.py create_cluster_session(gpu_aware_scheduling=True))\nspark.executor.resource.gpu.amount = 1\nspark.task.resource.gpu.amount     = 0.5    # 2 concurrent tasks share one GPU`);

  // ============================================================ 9 Triton
  H1("9. Triton-backed predict_batch_udf");
  img(D("mode_triton_pbu"), 980);
  P("The executors only open a gRPC client in `make_predict_fn` and send batches to Triton, which keeps each model resident on the GPU and merges concurrent requests from different Spark tasks with its dynamic batcher. Executors on CPU-only nodes can then use the GPU too, and no task ever builds a model.");
  H2("9.1 Model export (verified)");
  table([["model", "TorchScript size", "max |traced - eager|", "output dims"],
    ...Object.entries(exportRep).map(([m, r]) => [m, `${fmt(r.bytes / 1e6, 1)} MB`, r.trace_max_abs_diff, JSON.stringify(r.output_dims)])],
  [25, 25, 25, 25]);
  code(readT(path.join(REPO, "results", "modes_20260926", "triton_export_local", "resnet18.config.pbtxt")));
  img(D("seq_triton"), 900, "One Spark task calling Triton, step by step");
  H2("9.2 Sizing from what the T4 already showed");
  const bus = lowAws.bus || {};
  table([["measurement on the T4 node", "value", "meaning for a Triton tier"],
    ["10 models from one process, parallel CUDA streams", `${fmt(svsT4, 0)} samples/s`, "upper bound per T4 when models stay resident - what Triton approaches with enough concurrent requests"],
    ["best Spark distributed run (in-process)", `${fmt(bestSparkT4, 0)} samples/s`, "current platform on the same GPU"],
    ["FP32 / FP16 GEMM", `${fmt((bus.gemm_tflops || {})["torch.float32"], 2)} / ${fmt((bus.gemm_tflops || {})["torch.float16"], 2)} TFLOPS`, "fp16 TensorRT engines use Tensor Cores (6x fp32 here)"],
    ["host -> GPU pinned (PCIe Gen3 x8)", `${fmt(((bus.copies || [])[5] || {}).h2d_pinned, 2)} GB/s`, "ResNet18 fp32 input 602 KB -> ~10,000 images/s max over PCIe"],
    ["kernel launch (Linux)", `${fmt(bus.launch_enqueue_us, 1)} us`, "per-request overhead is small next to batching gains"]],
  [30, 20, 50]);

  // ============================================================ 10 cross-env
  H1("10. The same engines on three environments");
  const legs = [["windows", "Windows 11 (laptop, local[2])"], ["wsl2_docker", "WSL2 Linux (laptop, local[2])"], ["aws_g4dn", "AWS T4 (master + worker)"]];
  const tests = [["eng_rdd_cpu_only", "example_mlp RDD cpu"], ["eng_rdd_gpu_only", "example_mlp RDD gpu"], ["eng_udf_cpu_only", "example_mlp pandas UDF cpu"], ["eng_udf_gpu_only", "example_mlp pandas UDF gpu"],
    ["p7_cpu_only_medium", "10 models cpu_only (3k)"], ["p7_gpu_only_medium", "10 models gpu_only (3k)"], ["p7_hybrid_medium", "10 models hybrid (3k)"],
    ["p1_dist_large", "10 models distributed_gpu (10k)"], ["svs_single_gpu", "no Spark: single GPU, CUDA streams"]];
  table([["workload", ...legs.map((l) => l[1])],
    ...tests.map(([t, lab]) => [lab, ...legs.map(([leg]) => { const v = t === "svs_single_gpu" ? cthr(leg, t, "single_gpu_parallel_streams") : cthr(leg, t); return v ? `${fmt(v, 0)}/s` : "failed"; })])],
  [31, 23, 23, 23]);
  P("Windows spawns a new Python process per task (no fork) and pays ~86 us per CUDA launch (WDDM); the laptop's 8 GB RAM makes the in-process distributed modes memory-bound (see the campaign report). The AWS numbers are the reference for everything else in this document.");

  // ============================================================ 11 findings
  H1("11. Findings in the current platform (with fixes)");
  table([["#", "finding", "evidence", "fix"],
    ["1", "process_partition() rebuilds all models for every partition (its docstring says once per executor)", `platform10_3k rdd_gpu: ${fmt(loadS, 2)} s of model loads vs ${fmt(infS, 2)} s inference; 2 Python workers, 4 loads`, "cache models in a module-level dict keyed by (model, device) in the Python worker, or use predict_batch_udf / Triton"],
    ["2", "More partitions multiply model loads", `16 partitions: ${thr(p16)} vs 4: ${thr(g("platform10_5k", "dist_p4"))}`, "partitions = slots x 1-2 for in-process engines; with Triton, partition freely"],
    ["3", "`gpu_only` silently falls back to CPU on executors without a GPU", "cluster_engine.process_partition (code); measured in the 2-node run", "gpu_aware_scheduling=True, or fail fast in gpu_only"],
    ["4", "UDF ingestion builds Python float lists on the driver, then shuffles them", `example_mlp udf: shuffle write ${mb(sumT(mlpU, "shuffle_write_bytes"))} MB, extra stage`, "spark.read.parquet / createDataFrame(pandas) with Arrow; drop repartition when input already has P files"],
    ["5", "RDD engine returns counts, not predictions", `${mb(sumT(mlpR, "result_bytes"))} MB results for 20k samples`, "return or write predictions from the executor"],
    ["6", "Every executor process holds all models + a CUDA context", "2 Python workers x 10 models on one T4", "serve models once per GPU (Triton), executors CPU-only"],
    ["7", "SparkInferenceClusterStack CPU worker -c 2 vs 4-core executors; setup_and_run_gpu.sh builds the lean stage", "deploy/aws-cdk/spark_cluster/spark_cluster_stack.py, deploy/Dockerfile", "-c >= spark.executor.cores; docker build --target final"]],
  [4, 32, 32, 32]);

  shared.recommended(c, () => {
    H2("12.4 Capacity planning from the measurements");
    P(`On the T4 the platform's 10 models run at ${fmt(svsT4, 0)} samples/s when they stay resident in one process with parallel CUDA streams, against ${fmt(bestSparkT4, 0)} samples/s through Spark's in-process engines. A Triton tier keeps the models resident and batches across all Spark tasks, so its per-GPU ceiling is of the order of the first number; the 2-node run measures the achieved batch size, queue time and end-to-end throughput for resnet18 and ew_classifier.`);
    table([["planning quantity", "formula", "use"],
      ["GPUs needed (batch)", "peak rows/s / per-GPU sustained rows/s at the target queue time", "per-GPU figure from perf_analyzer or the 2-node run"],
      ["Spark client concurrency", "executors x task slots", "enough in-flight requests to fill Triton's preferred batch sizes"],
      ["max_queue_delay", "<= (latency SLO - compute time) / 2", "larger = bigger batches, higher latency"],
      ["Network per GPU", "rows/s x bytes/row", "resnet18 fp32: 602 KB/image -> 1,000 images/s ~ 4.8 Gbit/s; send JPEG + preprocess in Triton to cut 10-30x"]],
    [20, 40, 40]);
  });
  shared.alternatives(c);

  // ============================================================ 14 next run
  H1("14. What the 2-node run adds");
  table([["question", "how it is measured", "command"],
    ["How are tasks spread across a CPU worker and a GPU worker?", "event log: tasks per executor/host; task timelines", ".\\deploy\\run_aws_modes.ps1"],
    ["Does gpu_only fall back to CPU on the CPU worker?", "per-partition device reports in rdd_gpu", "same"],
    ["Does GPU-aware scheduling keep every task on the GPU?", "rdd_gpu_aware: executors only on the GPU node", "same"],
    ["Native predict_batch_udf at scale", "native_pbu_cpu/gpu with 100k signals / 256 images", "same"],
    ["Triton in front of Spark", "triton_pbu: end-to-end throughput, achieved batch, queue vs compute us, GPU util", "same"]],
  [30, 45, 25]);
  P("The run takes ~1.5 h (~$1.5) and destroys its stack. Afterwards `node benchmark/build_modes_docx.js` regenerates this document with the full 2-node statistics (modes_doc_text.js).");

  H1("Appendix A - task timelines");
  S.filter((s) => s.run === A).forEach((s) => gantt(s.model, s.mode, `${s.model} - ${s.mode}`, A));
  shared.filesAppendix(c);
};
