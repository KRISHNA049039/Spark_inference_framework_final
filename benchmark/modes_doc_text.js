// modes_doc_text.js - narrative of the execution-modes / Triton document.
// Called by build_modes_docx.js with its helpers; every number comes from
// modes_summary.json so the text stays true when the run is repeated.
const fs = require("fs");
const path = require("path");

exports.build = (c) => {
  const { H1, H2, H3, P, B, N, note, code, table, img, get, fmt, thr, mb, statRows, execTable, gantt, MODELS, S, RUN, DIAG, REPO, readT, inferStage, body } = c;
  const D = (k) => path.join(DIAG, `${k}.png`);
  const T = (model, mode) => { const s = get(model, mode); return s && !s.error ? s.throughput : null; };
  const ratio = (a, b) => (a && b ? `${fmt(a / b, 1)}x` : "n/a");
  const sumT = (s, k) => (s ? (s.tasks || []).reduce((a, t) => a + (t[k] || 0), 0) : 0);
  const loads = (s) => (s ? (s.model_loads || []).length : 0);
  const tri = (m) => (get(m, "triton_pbu") || {}).triton || {};
  const best = (m) => S.filter((s) => s.model === m && !s.error && s.throughput).sort((a, b) => b.throughput - a.throughput)[0];
  const cpuTasksInGpuMode = (s) => (s && s.partition_details ? s.partition_details.filter((p) => p.device === "cpu").length : 0);
  const nParts = (s) => (s && s.partition_details ? s.partition_details.length : 0);
  const IM = MODELS.includes("resnet18") ? "resnet18" : MODELS[0];
  const SM = MODELS.includes("ew_classifier") ? "ew_classifier" : MODELS[0];
  const res = {}; (c.RES || []).forEach((r) => { res[r.app] = r; });

  // ============================================================ title
  const { Paragraph, TextRun } = require("docx");
  body.push(new Paragraph({ spacing: { before: 1400, after: 200 }, children: [new TextRun({ text: "Spark Distributed Inference", size: 60, bold: true })] }));
  body.push(new Paragraph({ spacing: { after: 160 }, children: [new TextRun({ text: "How work is distributed across workers in every execution mode (RDD CPU / GPU / hybrid, GPU-aware scheduling, pandas UDF, predict_batch_udf, Triton), worker- and task-level statistics, and the recommended architecture with Triton Inference Server in front of the cluster", size: 26, color: "57606A" })] }));
  body.push(new Paragraph({ spacing: { after: 400 }, children: [new TextRun({ text: "Measured on a 2-node AWS cluster (m5.2xlarge CPU node + g4dn.xlarge T4 GPU node), 26 September 2026 · pytorch-spark-inference-platform", size: 20, color: "57606A" })] }));
  const { TableOfContents } = require("docx");
  body.push(new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" }));

  // ============================================================ 1 summary
  H1("1. Executive summary");
  const stageDur = (s, re) => { const st = (s && s.stages || []).filter((x) => re.test(x.kind || "")); return st.length ? st[st.length - 1].duration_ms / 1000 : null; };
  const infS = (s) => stageDur(s, /UDF|map \(Python\)/);
  const shufS = (s) => stageDur(s, /shuffle map/);
  const jobsS = (s) => (s && s.jobs || []).reduce((a, j) => a + (j.duration_ms || 0), 0) / 1000;
  const ingestS = (s) => (s ? s.wall_s - jobsS(s) : null);
  const byHost = (s) => { const o = {}; (s && s.executors || []).forEach((e) => { o[e.device] = (o[e.device] || 0) + (e.tasks || 0); }); return o; };
  const cudaInf = (s) => { const c = (s && s.partition_details || []).filter((p) => p.device === "cuda"); return c.length ? c.reduce((a, p) => a + p.inference_time_sec, 0) / c.length : null; };
  const maxUtil = Math.max(...S.filter((x) => x.run === S[0].run && x.gpu_util).map((x) => x.gpu_util.max));
  const avgUtilMax = Math.max(...S.filter((x) => x.run === S[0].run && x.gpu_util).map((x) => x.gpu_util.avg));
  const bI = best(IM), bS = best(SM);
  const hH = byHost(get(IM, "rdd_hybrid")), hA = byHost(get(IM, "rdd_gpu_aware"));
  B([
    `**Where tasks land:** with plain scheduling the 8 ${IM} tasks of rdd_hybrid split ${hH.cpu || 0} on the CPU node / ${hH.gpu || 0} on the GPU node - whichever slot frees first takes the next task. In rdd_gpu (\`gpu_only\`) ${cpuTasksInGpuMode(get(IM, "rdd_gpu"))} of ${nParts(get(IM, "rdd_gpu"))} partitions landed on the CPU node and **silently ran on CPU**. With GPU-aware scheduling (rdd_gpu_aware) all ${hA.gpu || 0} tasks ran on the GPU executor.`,
    `**The first GPU application on a node pays a warm-up:** GPU partitions of ${IM} spent ${fmt(cudaInf(get(IM, "rdd_gpu")), 1)} s in inference in rdd_gpu (the first CUDA/cuDNN convolution run on the node) but ${fmt(cudaInf(get(IM, "rdd_hybrid")), 2)} s in the next application (rdd_hybrid); the 10-model run shows the same (${fmt(cudaInf(get("platform10", "platform10_gpu")), 1)} s vs ${fmt(cudaInf(get("platform10", "platform10_hybrid")), 2)} s). That is why rdd_gpu (${thr(get(IM, "rdd_gpu"))}) looks slower than rdd_cpu (${thr(get(IM, "rdd_cpu"))}). Long-lived GPU processes (a model server) pay it once.`,
    `**End to end, the RDD engine is fastest at these data sizes:** ${IM} ${bI ? `${bI.mode} ${fmt(bI.throughput, 1)}/s` : ""}, ${SM} ${bS ? `${bS.mode} ${fmt(bS.throughput, 0)}/s` : ""}. The DataFrame-based modes (pandas UDF, native predict_batch_udf, Triton) first spend ${fmt(ingestS(get(IM, "triton_pbu")), 1)} s (${IM}) / ${fmt(ingestS(get(SM, "triton_pbu")), 1)} s (${SM}) on the driver turning numpy arrays into Python lists and shipping them, then ${fmt(shufS(get(IM, "triton_pbu")), 1)} s / ${fmt(shufS(get(SM, "triton_pbu")), 1)} s in the repartition shuffle - before any model runs.`,
    `**Inside the inference stage, Triton is fastest:** ${IM}: triton_pbu ${fmt(infS(get(IM, "triton_pbu")), 2)} s vs native_pbu_gpu ${fmt(infS(get(IM, "native_pbu_gpu")), 2)} s, udf_gpu ${fmt(infS(get(IM, "udf_gpu")), 2)} s, udf_cpu ${fmt(infS(get(IM, "udf_cpu")), 2)} s (${ratio(infS(get(IM, "native_pbu_gpu")), infS(get(IM, "triton_pbu")))} faster than in-process GPU); ${SM}: ${fmt(infS(get(SM, "triton_pbu")), 2)} s vs ${fmt(infS(get(SM, "native_pbu_gpu")), 2)} s / ${fmt(infS(get(SM, "udf_gpu")), 2)} s / ${fmt(infS(get(SM, "udf_cpu")), 2)} s. With Triton, executors on the CPU node drive the GPU too and no task builds a model.`,
    `**Model loads:** RDD engine ${loads(get(IM, "rdd_hybrid"))} loads for ${nParts(get(IM, "rdd_hybrid"))} tasks (once per task, although its docstring says once per executor); Spark's built-in predict_batch_udf and the Triton client ${loads(get(IM, "native_pbu_gpu"))} for 16 tasks (once per Python worker, then cached).`,
    `**The GPU is idle most of the time:** average SM utilisation during any run was at most ${fmt(avgUtilMax, 1)} % (peak ${fmt(maxUtil, 0)} %). These jobs are bound by Python/JVM overhead, data movement and warm-up - not by the T4.`,
    `**Triton batching:** ${SM}: ${fmt(tri(SM).requests, 0)} requests became ${fmt(tri(SM).executions, 0)} GPU executions (avg batch ${fmt(tri(SM).avg_executed_batch, 0)}, queue ${fmt(tri(SM).avg_queue_us / 1000, 1)} ms, compute ${fmt(tri(SM).avg_compute_infer_us / 1000, 1)} ms); ${IM}: ${fmt(tri(IM).requests, 0)} -> ${fmt(tri(IM).executions, 0)} (avg ${fmt(tri(IM).avg_executed_batch, 1)} images). Only 4 concurrent Spark clients sending near-full batches leave little to merge; online traffic and more executors would.`,
    "**Recommendation:** Triton Inference Server as the shared GPU tier (models resident and warm, batching across all callers, online + batch), Spark executors as lean CPU-only clients through `pyspark.ml.functions.predict_batch_udf`, and - the precondition measured here - columnar ingestion (Parquet/Arrow read by the executors) instead of driver-side Python lists, which today costs more than the inference itself. Use GPU-aware scheduling for anything that must stay in-process. Sections 12-13.",
  ]);
  table([["model", ...["rdd_cpu", "rdd_gpu", "rdd_hybrid", "rdd_gpu_aware", "udf_cpu", "udf_gpu", "native_pbu_cpu", "native_pbu_gpu", "triton_pbu"]],
    ...MODELS.map((m) => [m, ...["rdd_cpu", "rdd_gpu", "rdd_hybrid", "rdd_gpu_aware", "udf_cpu", "udf_gpu", "native_pbu_cpu", "native_pbu_gpu", "triton_pbu"].map((md) => thr(get(m, md)))])],
  [12, 11, 11, 11, 11, 11, 11, 11, 11, 11].map((x) => x * 0.91));
  P("Throughput = samples processed / wall time of the Spark job (including data ingestion, scheduling, model loading and result collection) - what a user of each mode actually experiences end to end.");
  H2("1.1 Where the time goes in the DataFrame-based modes");
  table([["model", "mode", "wall s", "driver ingestion s (wall - jobs)", "shuffle stage s", "inference stage s", "model loads"],
    ...MODELS.flatMap((m) => ["udf_cpu", "udf_gpu", "native_pbu_cpu", "native_pbu_gpu", "triton_pbu"].map((md) => { const x = get(m, md); return [m, md, fmt(x && x.wall_s, 1), fmt(ingestS(x), 1), fmt(shufS(x), 2), fmt(infS(x), 2), x ? (x.model_loads.length || "per task") : "-"]; }))],
  [14, 14, 10, 20, 14, 14, 14]);

  // ============================================================ 2 setup
  H1("2. Test cluster and method");
  img(D("current_cluster"), 980, "Figure 1 - the measured topology (editable: docs/diagrams/spark_inference_architectures.drawio, page 1)");
  table([["component", "CPU node", "GPU node"],
    ["instance", "m5.2xlarge: 8 vCPU (Xeon Platinum, AVX-512), 32 GB", "g4dn.xlarge: 4 vCPU (Xeon 8259CL), 16 GB, 1 x Tesla T4 16 GB (PCIe Gen3 x8)"],
    ["Spark roles", "master :7077, driver (spark_modes_stats.py), CPU worker -c 4 -m 12g", "GPU worker -c 4 -m 12g, advertises resource gpu:[0] via deploy/scripts/gpu_discovery.sh"],
    ["executors", "1 executor x 4 cores, spark.task.cpus=2 -> 2 task slots", "1 executor x 4 cores -> 2 task slots (GPU-aware: 0.5 GPU per task)"],
    ["other", "-", "Triton Inference Server (NGC image), model repo from benchmark/triton_export.py"],
    ["software", "multi-model-inference image: Spark 3.5.1, PyTorch 2.6.0+cu126, pyarrow, tritonclient[grpc]", "same image for the worker; Triton 2.x container for serving"]],
  [16, 42, 42]);
  H2("2.1 Workloads");
  table([["model", "input per sample", "samples", "batch size B", "partitions P", "why"],
    ["ew_classifier", "128 float32 (512 B)", "100,000", "1,024", "8", "tiny MLP: overhead-dominated, shows scheduling / serialization costs"],
    ["resnet18", "3x224x224 float32 (602 KB)", "256", "64", "8", "CNN: compute- and transfer-heavy, shows where GPUs matter"],
    ["platform10 (10 models)", "signals + images + 640x640 detections", "3,000 / 100 / 30", "256", "8", "the platform's real multi-model workload (cluster_benchmark)"]],
  [14, 18, 12, 10, 9, 37]);
  H2("2.2 Method");
  B([
    "Every mode x model runs as its **own Spark application** in a fresh Python process (benchmark/spark_modes_stats.py), so executors, event log, JVM heap and Python workers never carry over between measurements.",
    "8 partitions over 4 task slots (2 per node) = at least two scheduling waves, so the statistics show how Spark spreads tasks over both workers.",
    "Spark event logs (spark.eventLog.enabled) give per-task: executor, host, launch/finish, deserialize, run, JVM CPU, GC, shuffle and result bytes. Executor stdout/stderr (worker work dirs) give model-load events. `nvidia-smi dmon` (1 s) gives GPU utilisation; Triton's :8002 metrics are captured before and after the Triton mode.",
    "benchmark/analyze_modes_stats.py turns those into the tables and task timelines in this document.",
  ]);
  H2("2.3 Reading the statistics");
  table([["statistic", "meaning", "what a large value tells you"],
    ["deserialize", "executor time to unpack the task (closure, broadcast references)", "big closures or broadcast fetches"],
    ["run", "wall time the task thread spent, including waiting for its Python worker", "the real cost of the task"],
    ["JVM CPU", "CPU time of the JVM thread only (Python and GPU work are invisible here)", "JVM-side work: shuffle, Arrow conversion, serialization"],
    ["GC", "JVM garbage-collection pause inside the task", "memory pressure in the executor heap"],
    ["shuffle write / read (remote)", "bytes written to local shuffle files / fetched (from other nodes)", "data movement caused by repartition/joins"],
    ["results to driver", "serialized task results returned to the driver", "collect() of predictions"],
    ["model loads", "times a Python worker built the model and moved it to its device", "fixed cost repeated per task vs per worker"],
    ["task slot timeline", "one row per executor slot, one bar per task (colour = stage)", "idle slots, stragglers, waves"]],
  [16, 48, 36]);

  exports.howSpark(c);
  // ============================================================ per-mode sections
  const modeSection = (title, key, diagKey, intro, modes, extra) => {
    H1(title);
    if (diagKey) img(D(diagKey), 980);
    intro.forEach((t) => P(t));
    modes.forEach(([md, label]) => {
      H2(label);
      table(statRows(md), [22, ...MODELS.map(() => 78 / MODELS.length)]);
    });
    if (extra) extra();
  };

  modeSection("4. RDD mapPartitions: rdd_cpu, rdd_gpu, rdd_hybrid", "rdd", "mode_rdd", [
    "The platform's default engine (inference/cluster_engine.py). The driver slices the numpy arrays into P partition dicts, broadcasts the serialized state_dicts and runs `mapPartitions(process_partition)`. `device_mode` is resolved **inside each task**: cpu_only -> CPU; gpu_only and hybrid -> CUDA if that executor sees a GPU, otherwise CPU (gpu_only prints a warning, hybrid does not).",
  ], [["rdd_cpu", "4.1 rdd_cpu - statistics"], ["rdd_gpu", "4.2 rdd_gpu - statistics"], ["rdd_hybrid", "4.3 rdd_hybrid - statistics"]], () => {
    H2("4.4 Where each partition ran (from the tasks' own reports)");
    ["rdd_gpu", "rdd_hybrid"].forEach((md) => MODELS.forEach((m) => {
      const s = get(m, md); if (!s || !s.partition_details || !s.partition_details.length) return;
      H3(`${m} - ${md}`);
      table([["partition", "host", "device", "model load s", "inference s", "samples"],
        ...s.partition_details.map((p) => [p.partition_idx, p.hostname, p.device, fmt(p.model_load_time_sec, 2), fmt(p.inference_time_sec, 2), p.samples_processed])],
      [12, 26, 12, 16, 16, 18]);
    }));
    H2("4.5 Executors and task timeline - rdd_hybrid");
    MODELS.forEach((m) => { H3(m); execTable(get(m, "rdd_hybrid")); gantt(m, "rdd_hybrid", `Task slots over time - ${m} rdd_hybrid`); });
  });

  modeSection("5. GPU-aware scheduling: rdd_gpu_aware", "gpu", "mode_gpu_aware", [
    "Same engine, but the session is created with `create_cluster_session(gpu_aware_scheduling=True)`: `spark.executor.resource.gpu.amount=1`, `spark.task.resource.gpu.amount=0.5`. The GPU worker advertises its GPU through the discovery script; the CPU worker has none, so the master grants this application executors **only on the GPU node**. Every task then really runs on CUDA - at the price of using only that node's 2 slots.",
  ], [["rdd_gpu_aware", "5.1 rdd_gpu_aware - statistics"]], () => {
    code(`# worker (GPU node)\nSPARK_WORKER_OPTS="-Dspark.worker.resource.gpu.amount=1 \\\n  -Dspark.worker.resource.gpu.discoveryScript=/app/deploy/scripts/gpu_discovery.sh"\n\n# application\nspark.executor.resource.gpu.amount = 1\nspark.task.resource.gpu.amount     = 0.5   # 2 concurrent tasks share the GPU`);
    MODELS.forEach((m) => { H3(m); execTable(get(m, "rdd_gpu_aware")); gantt(m, "rdd_gpu_aware", `Task slots over time - ${m} rdd_gpu_aware`); });
  });

  modeSection("6. pandas UDF - the repo's predict_batch_udf: udf_cpu, udf_gpu", "udf", "mode_udf", [
    "`submit_job.py --engine udf` -> inference/cluster_engine_udf.py -> inference/predict_batch_udf.py. Inputs become a DataFrame of flat float arrays (`Row(input=x.reshape(-1).tolist())`), `repartition(P)`, then a scalar-iterator pandas UDF that builds the model once per task and re-chunks each Arrow batch to the model batch size. Unlike the RDD engine it returns the predictions.",
  ], [["udf_cpu", "6.1 udf_cpu - statistics"], ["udf_gpu", "6.2 udf_gpu - statistics"]], () => {
    H2("6.3 Executors and task timeline - udf_gpu");
    MODELS.forEach((m) => { H3(m); execTable(get(m, "udf_gpu")); gantt(m, "udf_gpu", `Task slots over time - ${m} udf_gpu (two stages: shuffle map, then UDF)`); });
  });

  modeSection("7. Spark's built-in predict_batch_udf: native_pbu_cpu, native_pbu_gpu", "native", "mode_native_pbu", [
    "`pyspark.ml.functions.predict_batch_udf` (Spark 3.4+) takes a `make_predict_fn` that returns a predict function. Spark caches the result per Python worker process, so with worker reuse the model is built once per worker, not once per task. It also assembles fixed-size numpy batches (`batch_size`) and reshapes flat arrays (`input_tensor_shapes`). Same DataFrame ingestion and shuffle as section 6.",
  ], [["native_pbu_cpu", "7.1 native_pbu_cpu - statistics"], ["native_pbu_gpu", "7.2 native_pbu_gpu - statistics"]], () => {
    code(`from pyspark.ml.functions import predict_batch_udf\n\ndef make_predict_fn():                      # runs once per Python worker (cached)\n    model = ResNet18Classifier(); model.load_state_dict(torch.load(io.BytesIO(bc.value)))\n    model = model.to("cuda").eval()\n    def predict(x: np.ndarray) -> np.ndarray:  # x: (B, 3, 224, 224)\n        with torch.no_grad():\n            return model(torch.from_numpy(x).cuda()).cpu().numpy()\n    return predict\n\nudf = predict_batch_udf(make_predict_fn, return_type=ArrayType(FloatType()),\n                        batch_size=64, input_tensor_shapes=[[3, 224, 224]])\ndf.select(udf("input")).collect()`);
    MODELS.forEach((m) => { H3(m); execTable(get(m, "native_pbu_gpu")); gantt(m, "native_pbu_gpu", `Task slots over time - ${m} native_pbu_gpu`); });
  });

  modeSection("8. predict_batch_udf -> Triton: triton_pbu", "triton", "mode_triton_pbu", [
    "The proposed architecture, measured: the same built-in predict_batch_udf, but `make_predict_fn` only opens a `tritonclient.grpc.InferenceServerClient` and `predict()` sends each batch to Triton. No executor loads a model or touches a GPU; executors on both nodes feed the single T4 through Triton, whose dynamic batcher merges concurrent requests from different Spark tasks.",
  ], [["triton_pbu", "8.1 triton_pbu - Spark-side statistics"]], () => {
    H2("8.2 Triton-side statistics (from :8002 metrics, delta over the job)");
    table([["metric", ...MODELS],
      ["requests / inferences / executions", ...MODELS.map((m) => { const t = tri(m); return t.requests ? `${fmt(t.requests, 0)} / ${fmt(t.inferences, 0)} / ${fmt(t.executions, 0)}` : "-"; })],
      ["avg batch sent by Spark (client)", ...MODELS.map((m) => fmt(tri(m).avg_client_batch, 1))],
      ["avg batch executed on GPU (after dynamic batching)", ...MODELS.map((m) => fmt(tri(m).avg_executed_batch, 1))],
      ["avg request latency (us)", ...MODELS.map((m) => fmt(tri(m).avg_request_us, 0))],
      ["  of which queue (us)", ...MODELS.map((m) => fmt(tri(m).avg_queue_us, 0))],
      ["  compute input / infer / output (us)", ...MODELS.map((m) => { const t = tri(m); return `${fmt(t.avg_compute_input_us, 0)} / ${fmt(t.avg_compute_infer_us, 0)} / ${fmt(t.avg_compute_output_us, 0)}`; })]],
    [36, ...MODELS.map(() => 64 / MODELS.length)]);
    const cfg = readT(path.join(RUN, "gpu_node", `${IM}.config.pbtxt`)) || readT(path.join(RUN, "gpu_node", "config.pbtxt"));
    H2("8.3 Model configuration used");
    code(cfg || "(config not captured)");
    const ver = readT(path.join(RUN, "triton_verify.txt")) || readT(path.join(RUN, "gpu_node", "triton_verify.txt"));
    const dl = (ver.match(/max \|triton - eager\| = [\d.e+-]+/g) || []).join("; ");
    P(`Correctness check (benchmark/triton_export.py --verify): ${dl || "not captured"} - Triton's GPU outputs vs eager PyTorch on CPU for the same inputs. resnet18 uses pretrained weights, so the two match to float precision; ew_classifier has no trained checkpoint and every process initialises it randomly, so the exported and the eager model differ by construction - export trained weights (weights_path) before relying on such a comparison.`);
    img(D("seq_triton"), 900, "Figure - one Spark task calling Triton, step by step");
    MODELS.forEach((m) => { H3(m); execTable(get(m, "triton_pbu")); gantt(m, "triton_pbu", `Task slots over time - ${m} triton_pbu`); });
  });

  // platform10
  H1("9. The platform's 10-model workload: platform10_cpu / _gpu / _hybrid");
  P("cluster_benchmark-equivalent run of all 10 models (5 signal MLPs, ResNet18, MobileNetV3, EfficientNet-B0, 2 YOLO-style detectors) through the RDD engine - the workload the platform exists for.");
  const pmodes = ["platform10_cpu", "platform10_gpu", "platform10_hybrid"];
  const p10 = pmodes.map((m) => get("platform10", m));
  const sum10 = (s, k) => (s ? (s.tasks || []).reduce((a, t) => a + (t[k] || 0), 0) : 0);
  table([["metric", ...pmodes],
    ["throughput", ...p10.map(thr)], ["wall s", ...p10.map((s) => (s ? fmt(s.wall_s, 2) : "-"))],
    ["tasks per worker", ...p10.map((s) => (s ? (s.executors || []).map((e) => `${e.host} (${e.device}): ${e.tasks || 0}`).join("; ") : "-"))],
    ["inference task min / median / max s", ...p10.map((s) => { if (!s) return "-"; const st = inferStage(s); return `${fmt(st.task_ms_min / 1000, 2)} / ${fmt(st.task_ms_median / 1000, 2)} / ${fmt(st.task_ms_max / 1000, 2)}`; })],
    ["sum task run s", ...p10.map((s) => fmt(sum10(s, "run_ms") / 1000, 1))],
    ["model loads (x10 models each)", ...p10.map((s) => (s ? `${(s.model_loads || []).length}` : "-"))],
    ["GPU SM util avg / max", ...p10.map((s) => (s && s.gpu_util ? `${fmt(s.gpu_util.avg, 0)} / ${fmt(s.gpu_util.max, 0)} %` : "-"))]],
  [25, 25, 25, 25]);
  p10.forEach((s, i) => { if (s) { H3(pmodes[i]); execTable(s); } });
  gantt("platform10", "platform10_hybrid", "Task slots over time - platform10_hybrid");

  // ---- supporting evidence from the single-node AWS run (aws_1node), if loaded
  const A1 = "aws_1node";
  if (S.some((x) => x.run === A1)) {
    const g1 = (m, md) => get(m, md, A1);
    const sumP = (x, k) => ((x && x.partition_details) || []).reduce((a, p) => a + (p[k] || 0), 0);
    H2("9.1 Partition scaling on one executor (single-node T4 run)");
    P("distributed_gpu.py (run_benchmark --mode distributed) with fixed data (25,170 samples, 10 models) and 2-16 partitions on one executor with 2 task slots: every extra partition adds a full 10-model load while the inference work stays the same.");
    const dm = ["dist_p2", "dist_p4", "dist_p8", "dist_p16"];
    table([["metric", "2 partitions", "4 partitions", "8 partitions", "16 partitions"],
      ["throughput", ...dm.map((m) => thr(g1("platform10_5k", m)))],
      ["waves over 2 slots", "1", "2", "4", "8"],
      ["sum model load s (tasks' reports)", ...dm.map((m) => fmt(sumP(g1("platform10_5k", m), "model_load_time_sec"), 2))],
      ["sum inference s", ...dm.map((m) => fmt(sumP(g1("platform10_5k", m), "inference_time_sec"), 2))]], [28, 18, 18, 18, 18]);
    const x = g1("platform10_3k", "rdd_gpu");
    if (x) {
      H2("9.2 Anatomy of a task (single-node T4 run, 10 models, rdd_gpu)");
      const tk = (i) => (x.tasks || []).find((t) => t.index === i);
      table([["partition", "task wall s (event log)", "model load s", "inference s", "unaccounted s (worker start, imports, broadcast, results)"],
        ...(x.partition_details || []).map((p) => { const t = tk(p.partition_idx); const w = t ? (t.finish - t.launch) / 1000 : null;
          return [p.partition_idx, fmt(w, 2), fmt(p.model_load_time_sec, 2), fmt(p.inference_time_sec, 2), w !== null ? fmt(w - p.model_load_time_sec - p.inference_time_sec, 2) : "-"]; })],
      [12, 20, 18, 18, 32]);
      note("The first task on each slot spends ~6 s outside the model code (starting the Python worker, importing torch/torchvision, deserializing the closure and fetching the ~75 MB broadcast); a second task on the warm worker takes ~1.7 s. Model loading then costs several times the GPU inference itself.");
    }
  }

  // ============================================================ 10 comparison
  H1("10. All modes side by side");
  MODELS.forEach((m) => { img(path.join(RUN, "charts", `throughput_${m}.png`), 900); img(path.join(RUN, "charts", `tasktime_${m}.png`), 900); });
  img(path.join(RUN, "charts", "loads.png"), 900);
  table([["model", "mode", "samples/s", "wall s", "jobs/stages/tasks", "tasks on CPU node / GPU node", "model loads", "shuffle MB", "results MB", "GPU SM avg %"],
    ...S.filter((s) => s.model !== "platform10").map((s) => {
      const ex = s.executors || []; const byDev = { cpu: 0, gpu: 0 }; ex.forEach((e) => { byDev[e.device === "gpu" ? "gpu" : "cpu"] += e.tasks || 0; });
      return [s.model, s.mode, s.throughput ? fmt(s.throughput, 0) : (s.error || "-"), fmt(s.wall_s, 1), `${(s.jobs || []).length}/${(s.stages || []).length}/${(s.tasks || []).length}`,
        `${byDev.cpu} / ${byDev.gpu}`, (s.model_loads || []).length || (s.mode && s.mode.startsWith("udf") ? "per task" : 0),
        mb(sumT(s, "shuffle_write_bytes")), mb(sumT(s, "result_bytes")), s.gpu_util ? fmt(s.gpu_util.avg, 0) : "-"];
    })], [11, 12, 9, 7, 10, 13, 9, 9, 9, 11]);

  // ============================================================ 11 findings
  H1("11. Findings in the current platform (with fixes)");
  table([["#", "finding", "evidence", "fix"],
    ["1", "`gpu_only` does not keep tasks on GPUs; tasks that land on a CPU worker silently run on CPU", `rdd_gpu (${IM}): ${cpuTasksInGpuMode(get(IM, "rdd_gpu"))}/${nParts(get(IM, "rdd_gpu"))} partitions on cpu`, "use gpu_aware_scheduling=True (resource profiles) or fail the task when CUDA is missing in gpu_only"],
    ["2", "process_partition() rebuilds all models for every partition (docstring says once per executor)", `rdd_hybrid (${IM}): ${loads(get(IM, "rdd_hybrid"))} loads for ${nParts(get(IM, "rdd_hybrid"))} partitions`, "cache models in a module-level dict keyed by (model, device) inside the Python worker, or move to predict_batch_udf / Triton"],
    ["3", "UDF ingestion builds Python lists of floats on the driver, then shuffles them", `${IM} udf_gpu: shuffle write ${mb(sumT(get(IM, "udf_gpu"), "shuffle_write_bytes"))} MB`, "read inputs from Parquet/Arrow (spark.read.parquet) or createDataFrame(pandas) with Arrow enabled; drop repartition when input already has P files"],
    ["4", "RDD engine returns only counts", "result bytes ~2 KB per task", "return predictions (or write them from the executor) when the job needs them"],
    ["5", "SparkInferenceClusterStack starts its CPU worker with -c 2 while sessions ask for 4-core executors", "deploy/aws-cdk/spark_cluster/spark_cluster_stack.py", "start workers with -c >= spark.executor.cores (this run used -c 4)"],
    ["6", "setup_and_run_gpu.sh builds deploy/Dockerfile without --target final (gets the torch-less lean stage)", "Dockerfile stage order", "add --target final"],
    ["7", "Every executor keeps its own copy of every model and its own CUDA context", "platform10 memory per Python worker", "serve models once per GPU (Triton) and keep executors CPU-only"]],
  [4, 34, 28, 34]);

  exports.recommended(c, () => {
    H2("12.4 Capacity planning from the measurements");
    const tI = tri(IM);
    const perExec = tI.avg_compute_infer_us && tI.avg_executed_batch ? (tI.avg_executed_batch / (tI.avg_compute_infer_us / 1e6)) : null;
    P(`For ${IM} on one T4, Triton executed batches of ${fmt(tI.avg_executed_batch, 0)} with an average compute time of ${fmt(tI.avg_compute_infer_us, 0)} us per request, i.e. roughly ${perExec ? fmt(perExec, 0) : "n/a"} images/s per model instance while busy; with 2 instances the GPU-side ceiling is about ${perExec ? fmt(2 * perExec, 0) : "n/a"} images/s (TorchScript fp32). The end-to-end Spark job reached ${thr(get(IM, "triton_pbu"))}, so the remaining gap is on the Spark side (ingestion, shuffle, Arrow conversion) - not the GPU.`);
    table([["planning quantity", "formula", "use"],
      ["GPUs needed (batch)", "peak rows/s / per-GPU sustained rows/s at target queue time", "per-GPU number from perf_analyzer or section 8.2"],
      ["Spark client concurrency", "executors x task slots (each an in-flight request stream)", "enough concurrent requests to fill Triton's preferred batch sizes"],
      ["max_queue_delay", "<= (latency SLO - compute time) / 2", "larger = bigger batches, higher latency"],
      ["Network per GPU", "rows/s x bytes/row", `${IM}: 602 KB/image -> 1,000 images/s ~ 4.8 Gbit/s; use g4dn/g5 with >= 10-25 Gbit/s or send compressed JPEG + preprocess in Triton (Python/DALI backend)`]],
    [20, 40, 40]);
    note(`Network is the hidden limit for image models: fp32 3x224x224 is 602 KB per sample. Sending encoded images (JPEG ~20-50 KB) and decoding/resizing inside Triton (DALI or Python backend) cuts the bytes on the wire 10-30x.`, "FFF8E6", "D6B656");
  });
  exports.alternatives(c);
  // ============================================================ appendix
  H1("Appendix A - task timelines for every run");
  S.forEach((s) => gantt(s.model, s.mode, `${s.model} - ${s.mode}`));
  exports.filesAppendix(c);
};


// ---------------------------------------------------------------- shared chapters
const helpers = (c) => ({ ...c, D: (k) => path.join(c.DIAG, `${k}.png`) });

exports.howSpark = (c0) => {
  const c = helpers(c0); const { H1, H2, H3, P, B, N, note, code, table, img } = c;

  // ============================================================ 3 how spark distributes
  H1("3. How Spark distributes inference across workers");
  N([
    "**Application start.** The driver registers with the master; the master starts executors on workers that have free cores/memory (standalone spreads executors over workers by default, spark.deploy.spreadOut=true). Each executor is a JVM with `spark.executor.cores` cores. With spark.task.cpus=2 a 4-core executor runs 2 tasks at a time.",
    "**Job and stages.** An action (collect) creates a job. The DAG scheduler cuts it into stages at shuffle boundaries: the RDD engine has one stage; the DataFrame/UDF engines have a shuffle-map stage (repartition) and a result stage.",
    "**Task placement.** The task scheduler offers each free slot the next pending task, preferring data locality (PROCESS_LOCAL -> NODE_LOCAL -> ANY, waiting spark.locality.wait=3 s at each level). Nothing in plain scheduling knows about GPUs: a task goes to whichever slot frees up first.",
    "**Getting code and weights to the executor.** The task carries the serialized closure; large read-only data (the model state_dicts) is a broadcast variable, fetched once per executor in 4 MB pieces by TorrentBroadcast (from the driver or from other executors that already have them).",
    "**Python side.** The executor streams the partition to a Python worker process over a local socket (pickle frames for RDDs, Arrow record batches for pandas UDFs); on Linux the worker is forked from pyspark.daemon and reused between tasks (spark.python.worker.reuse=true).",
    "**Results.** Each task returns its result bytes to the driver (small ones inline, large ones via the block manager); the driver concatenates them in collect().",
    "**Failures.** A failed task is retried up to spark.task.maxFailures=4 times, possibly on another executor; an executor loss re-runs its tasks elsewhere.",
  ]);
  note("Consequence for inference: every task pays whatever per-task setup the engine does (model construction, weight load, CUDA context, cuDNN autotune) and every executor holds its own copy of the model. The modes below differ mainly in how often that setup happens, where the tasks land, and how the data reaches the Python process.");

};

exports.recommended = (c0, capacity) => {
  const c = helpers(c0); const { H1, H2, H3, P, B, N, note, code, table, img, D } = c;
  // ============================================================ 12 recommended
  H1("12. Recommended architecture: Triton in front of the cluster");
  img(D("arch_recommended"), 980, "Figure - target architecture (editable in the .drawio file)");
  H2("12.1 Principles");
  B([
    "**Separate data parallelism from model serving.** Spark partitions, joins and writes data; Triton owns GPUs, keeps models resident, batches across callers, and serves online and batch traffic from the same deployment.",
    "**Executors become lean clients.** No torch/CUDA in the Spark image (the repo already has a `lean` Docker stage for exactly this - the waiter/kitchen split); one gRPC channel per Python worker, created in `make_predict_fn`.",
    "**Batching happens twice, deliberately.** Spark sends batches of B rows (predict_batch_udf batch_size); Triton's dynamic batcher merges concurrent batches from many tasks up to max_batch_size and preferred sizes within max_queue_delay.",
    "**One model repository, versioned.** Model CI exports TorchScript/ONNX (and TensorRT where it pays off), gates on accuracy and perf_analyzer, publishes version N+1; Triton polls or is told to load it explicitly.",
    "**Operate on queue time.** Triton's queue duration is the saturation signal: scale GPU nodes on it, and use request priorities so online traffic is served before batch.",
  ]);
  H2("12.2 Components");
  table([["component", "choice", "notes"],
    ["Inference server", "NVIDIA Triton (NGC tritonserver)", "backends: pytorch_libtorch (TorchScript, used here), onnxruntime, tensorrt, python (for pre/post-processing and pipelines via BLS)"],
    ["Model format", "TorchScript now; ONNX -> TensorRT for the CNNs/YOLO", "fp16 TensorRT engines use the T4's Tensor Cores (43.9 TFLOPS fp16 measured vs 6.95 fp32)"],
    ["Batching", "dynamic_batching { preferred_batch_size, max_queue_delay_microseconds }", "start with 1-2 ms queue delay for batch traffic; online SLOs may need a separate model config with smaller delay"],
    ["Concurrency", "instance_group { count: 2-4, kind: KIND_GPU }", "overlaps copy/compute and small kernels; watch VRAM"],
    ["Access", "internal L7 LB (Envoy / ALB with gRPC), API gateway for online", "least-request balancing; health on /v2/health/ready"],
    ["Spark client", "pyspark.ml.functions.predict_batch_udf + tritonclient.grpc", "one client per Python worker; retries with backoff; timeouts per request"],
    ["Pipelines (ner_translate)", "Triton Python backend + BLS, or keep the existing HTTP kitchen service", "OCR/translation have variable-size outputs; ensembles or BLS keep them server-side"],
    ["Model store", "S3 (cloud) / MinIO (air-gapped), versioned", "model-control-mode=explicit in production so loads are deliberate"],
    ["Observability", "Prometheus :8002 + Spark metrics -> Grafana", "nv_inference_queue_duration_us, compute_infer_duration_us, exec_count vs inference_count (achieved batch), GPU util/memory"],
    ["Scaling", "ASG / K8s HPA-KEDA on queue time and GPU util", "scale out Triton nodes independently of Spark"]],
  [16, 30, 54]);
  H2("12.3 Spark integration");
  code(`from pyspark.ml.functions import predict_batch_udf\nfrom pyspark.sql.types import ArrayType, FloatType\n\nTRITON = "triton.internal:8001"\n\ndef make_predict_fn():                                  # once per Python worker\n    import tritonclient.grpc as grpcclient\n    client = grpcclient.InferenceServerClient(url=TRITON)\n    def predict(x):                                     # x: (B, 3, 224, 224) float32\n        inp = grpcclient.InferInput("INPUT__0", list(x.shape), "FP32")\n        inp.set_data_from_numpy(x)\n        out = client.infer("resnet18", [inp], outputs=[grpcclient.InferRequestedOutput("OUTPUT__0")],\n                           client_timeout=30, priority=2)   # batch = lower priority than online\n        return out.as_numpy("OUTPUT__0")\n    return predict\n\nclassify = predict_batch_udf(make_predict_fn, return_type=ArrayType(FloatType()),\n                             batch_size=64, input_tensor_shapes=[[3, 224, 224]])\n\n(spark.read.parquet("s3://bucket/images/")            # columnar input, no driver-side lists\n      .withColumn("logits", classify("pixels"))\n      .write.parquet("s3://bucket/predictions/"))`);
  capacity();
  H2("12.5 Deployment on AWS");
  img(D("aws_topology"), 980);
  H2("12.6 Air-gapped deployment");
  img(D("airgapped_topology"), 980);
  P("Matches the repo's air-gapped process (docs/AIRGAPPED_*): build and validate in a connected enclave, transfer signed image tars + the model repository, run Triton with `--model-control-mode=explicit` and load versions only after checksum/accuracy verification. Triton's container already includes all backends, so no pip wheels are needed on the Triton side; Spark only needs `tritonclient[grpc]` added to the lean image.");
  H2("12.7 Migration plan");
  N([
    "**Stand up Triton next to the current cluster** (one GPU node), export the 10 models with benchmark/triton_export.py (extend EXPORT), verify outputs against eager PyTorch (already automated with --verify).",
    "**Switch the batch engine to predict_batch_udf + Triton** behind a flag (`--engine triton` in submit_job.py) - same inputs, same outputs, compare throughput and accuracy on real data.",
    "**Move ingestion to Parquet/Arrow** and drop the driver-side list building; keep repartition only where the input layout requires it.",
    "**Convert the heavy CNN/YOLO models to ONNX/TensorRT fp16** and enable Tensor Cores; re-tune max_batch_size and instance counts with perf_analyzer.",
    "**Add the access tier and observability** (LB, auth, Prometheus/Grafana dashboards on queue time and achieved batch size) and route online callers to the same Triton pool with higher priority.",
    "**Retire GPUs from Spark workers** (lean image, CPU-only executors, spot capacity) once all models are served by Triton; keep GPU-aware in-process mode only for models that cannot be exported.",
  ]);
  H2("12.8 Risks and mitigations");
  table([["risk", "mitigation"],
    ["Network bandwidth for large tensors", "send compressed inputs + server-side preprocessing; co-locate Triton and Spark in one AZ/placement group; shared-memory transport for sidecar deployments"],
    ["Triton becomes a single point of failure", ">= 2 nodes behind the LB, health checks, client retries with idempotent requests, circuit breaker in make_predict_fn"],
    ["Model export differences (TorchScript/ONNX)", "automated --verify against eager outputs (max abs diff) in model CI; block publish on regression"],
    ["Batch jobs starving online traffic", "request priorities, separate model configs/instances for online, rate limiter"],
    ["Version skew between jobs and models", "pin model version in the request (model_version) and record it with every prediction"]],
  [30, 70]);

};

exports.alternatives = (c0) => {
  const c = helpers(c0); const { H1, H2, H3, P, B, N, note, code, table, img, D } = c;
  // ============================================================ 13 alternatives
  H1("13. Alternative architectures");
  [["alt_sidecar", "13.1 Triton sidecar on every GPU worker"], ["alt_inprocess", "13.2 Keep in-process inference, fix its overheads"],
    ["alt_ray", "13.3 Ray Data + Ray Serve"], ["alt_k8s", "13.4 Kubernetes: Spark on K8s + KServe (Triton runtime)"],
    ["alt_queue", "13.5 Asynchronous, queue-driven inference"]].forEach(([k, t]) => { H2(t); img(D(k), 980); });
  H2("13.6 Comparison");
  table([["criterion", "Recommended: Triton tier", "Triton sidecar", "In-process (improved)", "Ray Data + Serve", "K8s + KServe", "Queue-driven"],
    ["batch throughput", "high (cross-task batching)", "high per node", "high with caching", "high", "high", "high, bursty"],
    ["online serving", "yes, same deployment", "awkward (on Spark nodes)", "no", "yes (Serve)", "yes", "async only"],
    ["GPU utilisation", "high, shared", "tied to Spark nodes", "per app, idle between jobs", "high", "high (+ scale to zero)", "high"],
    ["latency", "ms", "lowest (loopback)", "n/a (batch)", "ms", "ms", "seconds"],
    ["new infrastructure", "Triton + LB", "Triton per node", "none", "Ray cluster", "K8s platform", "broker + consumers"],
    ["operational effort", "medium", "low-medium", "low", "medium-high", "high", "medium"],
    ["air-gapped fit", "good (containers + MinIO)", "good", "best (today)", "medium", "hardest", "good"],
    ["change to Spark code", "UDF swap", "UDF swap", "engine fixes", "rewrite pipeline", "UDF swap + K8s", "producer/consumer"],
    ["choose when", "GPUs shared by batch + online, many models", "latency-critical batch on fixed GPU nodes", "no new services allowed", "team prefers Python-native end to end", "platform already on K8s", "bursty producers, results can lag"]],
  [13, 16, 13, 14, 14, 14, 16]);

};

exports.filesAppendix = (c0) => {
  const c = helpers(c0); const { H1, H2, H3, P, B, N, note, code, table, img } = c;
  H1("Appendix B - files and how to reproduce");
  table([["path", "contents"],
    ["deploy/run_aws_modes.ps1, deploy/scripts/modes_node.sh", "deploy the 2-node stack, build, start Spark + Triton, run, collect, destroy"],
    ["deploy/aws-cdk/spark_cluster/modes_cluster_stack.py", "SparkModesClusterStack (CDK)"],
    ["benchmark/spark_modes_stats.py", "runs every mode as its own Spark application"],
    ["benchmark/triton_export.py", "TorchScript model repository + --verify against eager PyTorch"],
    ["benchmark/analyze_modes_stats.py, benchmark/modes_charts.py", "statistics, task timelines, charts"],
    ["benchmark/build_modes_docx.js, benchmark/modes_doc_text.js", "this document"],
    ["docs/diagrams/build_diagrams.py -> spark_inference_architectures.drawio", "all diagrams (15 draw.io pages) + PNGs"],
    ["results/modes_20260926/aws_2node/", "event logs, executor logs, Triton metrics/configs, GPU dmon, summaries"]],
  [45, 55], [0]);
  code(`.\\deploy\\run_aws_modes.ps1                                   # ~1.5 h, ~$1.5, destroys the stack\npython benchmark/analyze_modes_stats.py results/modes_20260926/aws_2node\npython benchmark/modes_charts.py       results/modes_20260926/aws_2node\npython docs/diagrams/build_diagrams.py\nnode   benchmark/build_modes_docx.js`);
};
