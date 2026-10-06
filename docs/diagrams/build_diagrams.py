"""
build_diagrams.py - all architecture / flow diagrams for the Spark inference
modes + Triton architecture document.

  python docs/diagrams/build_diagrams.py [out_dir]
Writes <out_dir>/spark_inference_architectures.drawio (one page per diagram,
editable in draw.io / app.diagrams.net) and <out_dir>/png/<key>.png.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from diagram_engine import Diagram, write_drawio  # noqa: E402

D = []


# ============================================================ 1 current topology
def d_current():
    g = Diagram("current_cluster", "1. Current platform: Spark standalone cluster doing in-process inference",
                "Measured topology: CPU node (master + driver + CPU worker) and GPU node (GPU worker + Triton), AWS us-east-1, one subnet")
    g.container("cpu", 0, 0, 560, 610, "*CPU node - m5.2xlarge (8 vCPU, 32 GB)")
    g.container("gpun", 620, 0, 560, 610, "*GPU node - g4dn.xlarge (4 vCPU, 16 GB, Tesla T4)")
    g.box("drv", 20, 40, 250, 64, "*Driver (Python)\nspark_modes_stats.py / submit_job.py\nbuilds data, broadcasts weights", "driver")
    g.box("djvm", 20, 150, 250, 90, "*Driver JVM (SparkContext)\nDAGScheduler -> stages\nTaskScheduler -> task slots\nBlockManager: broadcast pieces", "spark")
    g.box("mst", 300, 40, 240, 64, "*Spark Master :7077\nregisters workers, grants\nexecutors to applications", "spark")
    g.box("cw", 300, 150, 240, 50, "*CPU Worker daemon\n-c 4 -m 12g", "spark")
    g.box("ce", 300, 240, 240, 70, "*Executor JVM (CPU)\n4 cores / spark.task.cpus=2\n= 2 task slots", "spark")
    g.box("cp1", 300, 360, 115, 110, "*Python worker\nforked by\npyspark.daemon\nmodels on CPU\n(oneDNN AVX-512)", "python", font=11)
    g.box("cp2", 425, 360, 115, 110, "*Python worker\n2nd task slot\n(same, reused\nacross tasks)", "python", font=11)
    g.box("res", 20, 300, 200, 70, "*Results\ncounts (RDD) or predictions\n(UDF) -> collect() to driver", "storage", shape="cyl")
    g.box("ev", 20, 420, 200, 60, "*Event log + REST :4040\nper job / stage / task metrics", "storage", shape="cyl")
    g.box("gw", 660, 150, 240, 60, "*GPU Worker daemon\n-c 4 -m 12g\nresource gpu:[0] (discovery script)", "spark", font=11)
    g.box("ge", 660, 240, 240, 70, "*Executor JVM (GPU)\n2 task slots\n(GPU-aware: 0.5 GPU per task)", "spark")
    g.box("gp1", 660, 360, 115, 110, "*Python worker\nmodels on cuda\ncudaMemcpy +\nkernels", "python", font=11)
    g.box("gp2", 785, 360, 115, 110, "*Python worker\n2nd slot\nshares the GPU", "python", font=11)
    g.box("t4", 660, 510, 240, 80, "*NVIDIA T4 (sm_75)\n40 SMs, 2,560 FP32 lanes,\n320 Tensor Cores, 16 GB GDDR6", "gpu")
    g.box("trt", 930, 240, 230, 110, "*Triton Inference Server\n:8000 HTTP  :8001 gRPC\n:8002 Prometheus metrics\ndynamic batcher, 2 instances\nper model on the T4", "triton")
    g.box("repo", 930, 400, 230, 60, "*Model repository\nresnet18/1/model.pt (TorchScript)\new_classifier/1/model.pt", "storage", shape="cyl", font=11)
    g.edge("drv", "djvm", "Py4J (TCP)")
    g.edge("djvm", "mst", "register app,\nrequest executors", exit=(1, 0.2), entry=(0, 0.8))
    g.edge("mst", "cw", "launch executor")
    g.edge("mst", "gw", "launch executor", exit=(1, 0.5), entry=(0.5, 0), points=[(780, 72)])
    g.edge("cw", "ce", "spawns")
    g.edge("gw", "ge", "spawns")
    g.edge("djvm", "ce", "tasks (RPC)\n+ broadcast", exit=(1, 0.95), entry=(0, 0.5), points=[(285, 235.5), (285, 275)])
    g.edge("djvm", "ge", "tasks + broadcast pieces over the VPC network", exit=(0.9, 1), entry=(0, 0.75),
           points=[(245, 240), (245, 585), (600, 585), (600, 292.5)])
    g.edge("ce", "cp1", "socket\npickle/Arrow", exit=(0.25, 1), entry=(0.5, 0))
    g.edge("ce", "cp2", "", exit=(0.75, 1), entry=(0.5, 0))
    g.edge("ge", "gp1", "socket", exit=(0.25, 1), entry=(0.5, 0))
    g.edge("ge", "gp2", "", exit=(0.75, 1), entry=(0.5, 0))
    g.edge("gp1", "t4", "PCIe Gen3 x8", exit=(0.5, 1), entry=(0.25, 0))
    g.edge("gp2", "t4", "", exit=(0.5, 1), entry=(0.75, 0))
    g.edge("trt", "t4", "", exit=(0, 0.8), entry=(1, 0.5), points=[(915, 328), (915, 550)])
    g.edge("repo", "trt", "load", dashed=True)
    g.edge("djvm", "res", "", dashed=True, exit=(0.3, 1), entry=(0.5, 0))
    g.edge("djvm", "ev", "", dashed=True, exit=(0, 0.5), entry=(0, 0.5), points=[(10, 195), (10, 450)])
    D.append(g)


d_current()


# ============================================================ swimlane helper
LANES = [("Driver (Python)", "driver"), ("Driver JVM", "spark"), ("Executor JVM (on a worker)", "spark"),
         ("Python worker process", "python"), ("Device (CPU cores / GPU)", "gpu")]
LANE_H, LANE_GAP, LANE_W = 104, 8, 1400


def lanes(g, labels=LANES):
    ys = {}
    for i, (lab, _) in enumerate(labels):
        y = i * (LANE_H + LANE_GAP)
        g.container(f"lane{i}", 0, y, LANE_W, LANE_H, "*" + lab)
        ys[i] = y + 26
    return ys


def step(g, cid, lane_y, col, label, style, w=210, h=70, x0=12, colw=228, font=11):
    return g.box(cid, x0 + col * colw, lane_y, w, h, label, style, font=font)


# ============================================================ 2 RDD mapPartitions
def d_rdd():
    g = Diagram("mode_rdd", "2. Mode: RDD mapPartitions (rdd_cpu / rdd_gpu / rdd_hybrid, platform10_*)",
                "inference/cluster_engine.py run_cluster_inference(): 1 job, 1 stage, 1 task per partition; counts returned")
    y = lanes(g)
    step(g, "gen", y[0], 0, "*1. Generate numpy data\nsignals (N,128) / images (N,3,224,224)", "driver")
    step(g, "split", y[0], 1, "*2. Split into P partition dicts\n{model: array slice} x P", "driver")
    step(g, "ser", y[0], 2, "*3. torch.save(state_dict) x models\nsc.broadcast(bytes)", "driver")
    step(g, "agg", y[0], 5, "*9. Aggregate counts\nthroughput = samples / wall", "driver")
    step(g, "par", y[1], 1, "*sc.parallelize(P)\npickled to temp file,\nJVM reads -> ParallelCollectionRDD", "spark")
    step(g, "job", y[1], 2, "*Job 0 -> Stage 0 (P tasks)\nDAGScheduler; TaskScheduler fills\nfree slots (locality PROCESS_LOCAL)", "spark")
    step(g, "col", y[1], 5, "*collect(): result bytes from\nevery task (~2 KB each)", "spark")
    step(g, "tdes", y[2], 2, "*Task: deserialize closure\n+ fetch broadcast pieces\n(TorrentBroadcast, 4 MB blocks)", "spark")
    step(g, "prun", y[2], 3, "*PythonRunner\nstreams partition bytes to\nthe Python worker socket", "spark")
    step(g, "tres", y[2], 5, "*Task result -> driver\n(DirectTaskResult)", "spark")
    step(g, "load", y[3], 3, "*process_partition(): build 10 (or 1)\nmodels, load_state_dict, .to(device)\n= once per TASK / partition", "bad")
    step(g, "loop", y[3], 4, "*for model, for batch of B:\ntorch.from_numpy -> .to(device)\n-> model(x) (output discarded)", "python")
    step(g, "yld", y[3], 5, "*yield {partition, host, device,\nload s, infer s, counts}", "python")
    step(g, "h2d", y[4], 3, "*cpu_only: oneDNN / MKL\nAVX2 / AVX-512 kernels", "gpu")
    step(g, "krn", y[4], 4, "*gpu: H2D copy (pageable,\nPCIe) + cuDNN/cuBLAS kernels", "gpu")
    for a, b in [("gen", "split"), ("split", "ser"), ("ser", "job"), ("split", "par"), ("par", "job"), ("job", "tdes"),
                 ("tdes", "prun"), ("prun", "load"), ("load", "loop"), ("loop", "krn"), ("loop", "yld"), ("yld", "tres"),
                 ("tres", "col"), ("col", "agg")]:
        g.edge(a, b)
    g.edge("load", "h2d", "cpu_only", dashed=True)
    g.box("n1", 1430, 26, 260, 300, "*What the statistics show\n\n- 1 job, 1 stage, P tasks\n- no shuffle\n- model load repeats per task: "
          "P loads, even with python worker reuse (the function body re-runs for every partition)\n- rdd_gpu on a mixed cluster: tasks that land on "
          "the CPU worker silently run on CPU (fallback)\n- JVM CPU time ~ 0: the work is in Python / GPU", "note", font=11)
    D.append(g)


# ============================================================ 3 repo pandas UDF
def d_udf():
    g = Diagram("mode_udf", "3. Mode: pandas UDF - the repo's predict_batch_udf (udf_cpu / udf_gpu)",
                "inference/cluster_engine_udf.py + inference/predict_batch_udf.py: DataFrame of flat float arrays, Arrow to Python, predictions returned")
    y = lanes(g)
    step(g, "gen", y[0], 0, "*1. Generate numpy data", "driver")
    step(g, "rows", y[0], 1, "*2. Row(input=x.reshape(-1).tolist())\none Python float object per value\n(150,528 per image)", "bad")
    step(g, "cdf", y[0], 2, "*3. createDataFrame(rows, schema)\n.repartition(P)\n.select(udf(input)).collect()", "driver")
    step(g, "preds", y[0], 5, "*9. predictions list per sample\n(real outputs, unlike RDD)", "driver")
    step(g, "s0", y[1], 2, "*Stage A: parallelize rows ->\nExchange RoundRobinPartitioning(P)\n(shuffle WRITE)", "spark")
    step(g, "s1", y[1], 3, "*Stage B (P tasks): shuffle READ ->\nArrowEvalPython -> collect\n(AQE may coalesce partitions)", "spark")
    step(g, "col", y[1], 5, "*collect(): predictions\n(output rows) to driver", "spark")
    step(g, "shw", y[2], 2, "*Shuffle files on local disk,\nserved by BlockManager to\nreducers on any node", "spark")
    step(g, "arr", y[2], 3, "*Rows -> Arrow record batches\n(maxRecordsPerBatch 10,000)\nstreamed to Python", "spark")
    step(g, "tres", y[2], 5, "*Arrow batches of results\nback to the JVM", "spark")
    step(g, "load", y[3], 3, "*_predict(): model_class() +\nload_state_dict + .to(device)\nonce per TASK", "bad")
    step(g, "loop", y[3], 4, "*per Arrow batch: np.stack ->\nre-chunk to B -> model(x)\n-> .tolist() per row", "python")
    step(g, "yld", y[3], 5, "*yield pd.Series(list of\nfloat lists)", "python")
    step(g, "krn", y[4], 4, "*H2D + kernels (GPU)\nor oneDNN (CPU)", "gpu")
    for a, b in [("gen", "rows"), ("rows", "cdf"), ("cdf", "s0"), ("s0", "shw"), ("s0", "s1"), ("s1", "arr"),
                 ("arr", "load"), ("load", "loop"), ("loop", "krn"), ("loop", "yld"), ("yld", "tres"), ("tres", "col"),
                 ("col", "preds")]:
        g.edge(a, b)
    g.edge("shw", "arr", "shuffle fetch\n(local / remote)", dashed=True)
    g.box("n1", 1430, 26, 260, 300, "*What the statistics show\n\n- 2 stages (+ a shuffle): extra "
          "write/read of every input byte\n- driver builds Python lists: ingestion dominates for images\n- model load once per task\n"
          "- per-sample predictions are returned (bigger results)\n- device resolved per task: gpu_only on the CPU worker runs on CPU",
          "note", font=11)
    D.append(g)


# ============================================================ 4 native predict_batch_udf
def d_native():
    g = Diagram("mode_native_pbu", "4. Mode: Spark's built-in pyspark.ml.functions.predict_batch_udf (native_pbu_cpu / _gpu)",
                "Same DataFrame + Arrow path as the pandas UDF; the model is cached per Python worker process and batched for you")
    y = lanes(g)
    step(g, "gen", y[0], 0, "*1. Generate data + broadcast\nstate_dict bytes", "driver")
    step(g, "cdf", y[0], 1, "*2. Same input DataFrame\n(flat arrays, repartition P)", "driver")
    step(g, "mk", y[0], 2, "*3. predict_batch_udf(make_predict_fn,\nreturn_type, batch_size=B,\ninput_tensor_shapes=[shape])", "driver")
    step(g, "preds", y[0], 5, "*predictions per sample", "driver")
    step(g, "s0", y[1], 2, "*Stage A: shuffle write\n(repartition)", "spark")
    step(g, "s1", y[1], 3, "*Stage B: shuffle read ->\nArrowEvalPython (P tasks)", "spark")
    step(g, "col", y[1], 5, "*collect()", "spark")
    step(g, "arr", y[2], 3, "*Arrow batches -> Python", "spark")
    step(g, "tres", y[2], 5, "*results -> driver", "spark")
    step(g, "cache", y[3], 2, "*make_predict_fn() runs ONCE per\nPython worker (cached by UDF id);\nlater tasks on the same worker reuse it", "good")
    step(g, "bat", y[3], 3, "*Spark concatenates rows into\nnumpy batches of exactly B,\nreshaped to input_tensor_shapes", "good")
    step(g, "pred", y[3], 4, "*predict(np) -> torch ->\nmodel -> numpy", "python")
    step(g, "yld", y[3], 5, "*outputs -> Arrow", "python")
    step(g, "krn", y[4], 4, "*H2D + kernels (GPU)\nor oneDNN (CPU)", "gpu")
    for a, b in [("gen", "cdf"), ("cdf", "mk"), ("mk", "s0"), ("s0", "s1"), ("s1", "arr"), ("arr", "bat"), ("cache", "pred"),
                 ("bat", "pred"), ("pred", "krn"), ("pred", "yld"), ("yld", "tres"), ("tres", "col"), ("col", "preds")]:
        g.edge(a, b)
    g.box("n1", 1430, 26, 260, 300, "*Why it differs from the repo UDF\n\n- model loads = number of Python "
          "workers, not number of tasks (needs spark.python.worker.reuse=true, set by the platform)\n- batching and reshaping are "
          "built in (no manual re-chunk)\n- same shuffle + Arrow ingestion cost\n- available since Spark 3.4 (image has 3.5.1)",
          "note", font=11)
    D.append(g)


# ============================================================ 5 GPU-aware scheduling
def d_gpu_aware():
    g = Diagram("mode_gpu_aware", "5. Where tasks land: plain scheduling vs Spark GPU-aware scheduling",
                "rdd_gpu (left) vs rdd_gpu_aware (right) on the same heterogeneous cluster")
    for off, title, aware in [(0, "*Plain: device_mode=gpu_only, no resource request", False),
                              (660, "*GPU-aware: executor.resource.gpu.amount=1, task.resource.gpu.amount=0.5", True)]:
        g.container(f"p{off}", off, 0, 620, 470, title)
        g.box(f"m{off}", off + 200, 40, 220, 60, "*Spark Master\nmatches executor requests\nto worker resources", "spark")
        g.box(f"cw{off}", off + 20, 160, 260, 70, "*CPU worker (4 cores)\nresources: none", "spark")
        g.box(f"gw{off}", off + 340, 160, 260, 70, "*GPU worker (4 cores)\nresources: gpu [0]\n(discovery script)", "spark")
        if aware:
            g.box(f"ce{off}", off + 20, 280, 260, 80, "*no executor granted\n(cannot satisfy gpu=1)\n-> idle", "white")
            g.box(f"ge{off}", off + 340, 280, 260, 80, "*Executor: 2 slots,\neach task gets 0.5 GPU\n(spark.task.resource.gpu.amount)", "good")
            g.box(f"r{off}", off + 20, 390, 580, 60, "*All P tasks run on the GPU executor -> every task really uses cuda;\n"
                  "throughput limited to the GPU node's slots", "good")
        else:
            g.box(f"ce{off}", off + 20, 280, 260, 80, "*Executor: 2 slots\ntorch.cuda.is_available()=False\n-> falls back to CPU", "bad")
            g.box(f"ge{off}", off + 340, 280, 260, 80, "*Executor: 2 slots\nruns on cuda", "python")
            g.box(f"r{off}", off + 20, 390, 580, 60, "*Tasks split across both executors: 'gpu_only' results mix CPU and GPU\n"
                  "timings; the slowest (CPU) tasks decide the stage time", "bad")
        g.edge(f"m{off}", f"cw{off}", "grant?" if aware else "grant", exit=(0.2, 1), entry=(0.5, 0))
        g.edge(f"m{off}", f"gw{off}", "grant", exit=(0.8, 1), entry=(0.5, 0))
        g.edge(f"cw{off}", f"ce{off}", "", dashed=aware)
        g.edge(f"gw{off}", f"ge{off}", "")
    D.append(g)


# ============================================================ 6 Triton-backed predict_batch_udf
def d_triton_mode():
    g = Diagram("mode_triton_pbu", "6. Mode: predict_batch_udf -> Triton (triton_pbu) - Spark as a client of a GPU inference service",
                "Executors on BOTH nodes do only I/O; every forward pass runs inside Triton on the T4, batched across tasks")
    g.container("cpu", 0, 0, 470, 500, "*CPU node")
    g.container("gpun", 520, 0, 900, 500, "*GPU node")
    g.box("drv", 20, 40, 200, 60, "*Driver\ninput DataFrame, collect()", "driver")
    g.box("ce", 20, 150, 430, 60, "*Executor (CPU worker) - 2 task slots, no model, no GPU", "spark")
    g.box("c1", 20, 250, 205, 110, "*Python worker\nmake_predict_fn():\ngrpc InferenceServerClient\n(once per worker)", "python", font=11)
    g.box("c2", 245, 250, 205, 110, "*Python worker\npredict(batch of B)\n-> client.infer()", "python", font=11)
    g.box("ge", 540, 150, 380, 60, "*Executor (GPU worker) - 2 task slots, also only clients", "spark")
    g.box("g1", 540, 250, 180, 110, "*Python worker\ngRPC client", "python", font=11)
    g.box("g2", 740, 250, 180, 110, "*Python worker\ngRPC client", "python", font=11)
    g.container("tri", 960, 40, 440, 440, "*Triton Inference Server")
    g.box("fe", 980, 80, 400, 50, "*gRPC / HTTP frontend  :8001 / :8000", "triton")
    g.box("q", 980, 160, 400, 80, "*Per-model scheduler: dynamic batcher\nmerges concurrent requests up to max_batch_size\n(preferred sizes, max_queue_delay 2 ms)", "triton", font=11)
    g.box("i1", 980, 270, 190, 60, "*instance 1\n(CUDA stream)", "triton")
    g.box("i2", 1190, 270, 190, 60, "*instance 2\n(CUDA stream)", "triton")
    g.box("t4", 980, 360, 400, 50, "*Tesla T4 - models resident in VRAM (loaded once)", "gpu")
    g.box("mt", 980, 420, 400, 44, "*:8002 metrics: queue us, compute us, exec count", "storage", font=11)
    g.edge("drv", "ce", "tasks")
    g.edge("drv", "ge", "tasks", exit=(1, 0.5), entry=(0.3, 0), points=[(654, 70)])
    g.edge("ce", "c1", "", exit=(0.25, 1), entry=(0.5, 0))
    g.edge("ce", "c2", "", exit=(0.75, 1), entry=(0.5, 0))
    g.edge("ge", "g1", "", exit=(0.25, 1), entry=(0.5, 0))
    g.edge("ge", "g2", "", exit=(0.75, 1), entry=(0.5, 0))
    for c in ("c1", "c2"):
        g.edge(c, "fe", "", exit=(0.5, 1), entry=(0, 0.5), points=[(122 if c == "c1" else 347, 430), (950, 430), (950, 105)],
               color="#7b4f9d")
    g.edge("g1", "fe", "gRPC infer (B samples)", exit=(0.5, 1), entry=(0, 0.6), points=[(630, 400), (940, 400), (940, 110)], color="#7b4f9d")
    g.edge("g2", "fe", "", exit=(1, 0.3), entry=(0, 0.7), points=[(930, 283), (930, 115)], color="#7b4f9d")
    g.edge("fe", "q", "")
    g.edge("q", "i1", "")
    g.edge("q", "i2", "")
    g.edge("i1", "t4", "")
    g.edge("i2", "t4", "")
    D.append(g)


# ============================================================ 7 recommended architecture
def d_recommended():
    g = Diagram("arch_recommended", "7. Recommended: Triton in front of the cluster (online + batch share one GPU inference tier)",
                "Spark keeps what it is good at (partitioned data movement, joins, writes); GPUs live behind Triton with models resident and batching across callers")
    g.container("cons", 0, 0, 250, 520, "*Consumers")
    g.box("apps", 20, 40, 210, 70, "*Online apps / APIs\n(interactive, p99 SLO)", "client")
    g.box("spk", 20, 230, 210, 150, "*Spark batch cluster\n(lean CPU image, no torch/CUDA)\ninput -> predict_batch_udf\n(Triton gRPC client)\n-> joins / writes", "spark")
    g.box("pipe", 20, 130, 210, 70, "*Pipelines\n(ner_translate: OCR + NER + MT)", "client")
    g.box("lake", 20, 420, 210, 80, "*Data: S3 / HDFS / Cassandra\n(inputs & predictions)", "storage", shape="cyl")
    g.container("edge", 290, 0, 230, 520, "*Access tier")
    g.box("gw", 310, 40, 190, 80, "*API gateway / Ingress\nauth (mTLS/JWT), quotas,\nrequest logging", "infra")
    g.box("lb", 310, 190, 190, 90, "*gRPC-aware L7 LB\n(Envoy / ALB / NLB)\nleast-request,\nper-model routing", "infra")
    g.box("pri", 310, 320, 190, 70, "*Priority / QoS\nonline = high, batch = low\n(Triton priority levels)", "note", font=11)
    g.container("pool", 560, 0, 500, 520, "*GPU inference tier - N x Triton (ASG or K8s Deployment)")
    for i, yy in enumerate((40, 190, 340)):
        g.box(f"t{i}", 580, yy, 460, 120, f"*Triton node {i + 1} (g4dn / g5 / L4 ...)\ndynamic batcher + 2-4 instances per model,\n"
              "TensorRT / ONNX / TorchScript backends,\nensembles + Python backend (BLS) for pipelines,\n"
              "response cache, rate limiter", "triton", font=11)
    g.container("plat", 1100, 0, 300, 520, "*Model + ops platform")
    g.box("repo", 1120, 40, 260, 80, "*Model repository\nS3 / MinIO, versioned\n(config.pbtxt + weights)", "storage", shape="cyl")
    g.box("ci", 1120, 150, 260, 100, "*Model CI\nexport (TorchScript/ONNX/TRT),\nperf_analyzer + accuracy gate,\npublish version N+1", "good", font=11)
    g.box("obs", 1120, 280, 260, 90, "*Observability\nPrometheus scrapes :8002 + Spark\nGrafana: queue/compute us, batch,\nGPU util; alerts", "infra", font=11)
    g.box("as", 1120, 400, 260, 90, "*Autoscaler\nscale on queue time / GPU util\n(KEDA / HPA / ASG policy)", "infra", font=11)
    g.edge("apps", "gw", "gRPC / HTTP")
    g.edge("spk", "lb", "gRPC, batch B,\nlow priority", exit=(1, 0.1), entry=(0, 0.6), points=[(290, 245), (290, 244)])
    g.edge("pipe", "gw", "", exit=(1, 0.5), entry=(0, 0.8), points=[(270, 165), (270, 104)])
    g.edge("gw", "lb", "")
    for i, yy in enumerate((100, 250, 400)):
        g.edge("lb", f"t{i}", "", exit=(1, 0.5), entry=(0, 0.5), points=[(530, 235), (530, yy)])
    g.edge("repo", "t0", "poll / load", dashed=True, exit=(0, 0.5), entry=(1, 0.3))
    g.edge("ci", "repo", "publish", exit=(0.5, 0), entry=(0.5, 1))
    g.edge("t1", "obs", "metrics", dashed=True, exit=(1, 0.6), entry=(0, 0.5))
    g.edge("obs", "as", "")
    g.edge("as", "t2", "scale", dashed=True, exit=(0, 0.5), entry=(1, 0.6))
    g.edge("spk", "lake", "read / write", exit=(0.5, 1), entry=(0.5, 0), points=[], both=True)
    D.append(g)


# ============================================================ 8 alt: sidecar
def d_alt_sidecar():
    g = Diagram("alt_sidecar", "8. Alternative A: Triton sidecar on every GPU worker (co-located)",
                "Executors call Triton on localhost; no network hop for tensors, but GPU capacity is tied to Spark worker count")
    for i, x in enumerate((0, 460)):
        g.container(f"n{i}", x, 0, 420, 330, f"*GPU worker node {i + 1}")
        g.box(f"e{i}", x + 20, 40, 380, 60, "*Spark executor (Python workers, no model)", "spark")
        g.box(f"t{i}", x + 20, 150, 380, 80, "*Triton (localhost :8001)\nmodels resident, dynamic batching\nacross this node's tasks only", "triton")
        g.box(f"g{i}", x + 20, 260, 380, 50, "*GPU", "gpu")
        g.edge(f"e{i}", f"t{i}", "gRPC over loopback / shared memory")
        g.edge(f"t{i}", f"g{i}", "")
    g.box("drv", 940, 40, 260, 70, "*Spark driver + master", "driver")
    g.box("pro", 940, 140, 260, 180, "*+ lowest latency, no LB\n+ Triton system shared memory\n  avoids tensor copies\n- batching only within a node\n"
          "- GPUs idle when Spark is idle\n- online traffic must also land\n  on Spark nodes", "note", font=11)
    g.edge("drv", "e1", "tasks", exit=(0, 0.5), entry=(1, 0.5))
    D.append(g)


# ============================================================ 9 alt: improved in-process
def d_alt_inprocess():
    g = Diagram("alt_inprocess", "9. Alternative B: keep in-process inference, fix its overheads",
                "No new service: GPU-aware scheduling + native predict_batch_udf caching + pinned memory + Arrow ingestion")
    g.box("drv", 0, 40, 260, 100, "*Driver\ninput as Parquet / Arrow\n(no Python row lists)", "driver")
    g.box("sch", 320, 40, 300, 100, "*Resource profiles (stage-level scheduling)\nGPU stage: gpu.amount=1, task 0.25\nCPU stage: pre/post-processing", "spark", font=11)
    g.box("ge", 680, 20, 300, 140, "*GPU executors\nnative predict_batch_udf:\nmodel cached per worker,\nbatch_size B, pinned memory,\nCUDA streams / fp16", "good", font=11)
    g.box("ce", 680, 190, 300, 90, "*CPU executors\nETL, feature prep, joins\n(no models)", "spark")
    g.box("pro", 1040, 20, 260, 260, "*+ zero new infrastructure\n+ data locality with Spark\n+ works air-gapped today\n- model memory per executor\n"
          "- GPUs allocated per Spark app\n  (idle between jobs)\n- no online serving path\n- one model version per job", "note", font=11)
    g.edge("drv", "sch", "")
    g.edge("sch", "ge", "GPU stage")
    g.edge("sch", "ce", "CPU stage", exit=(0.5, 1), entry=(0, 0.5), points=[(470, 235)])
    D.append(g)


# ============================================================ 10 alt: Ray
def d_alt_ray():
    g = Diagram("alt_ray", "10. Alternative C: Ray Data (batch) + Ray Serve (online)",
                "Python-native actors hold models on GPUs; batch and online share one Ray cluster")
    g.box("src", 0, 60, 220, 80, "*Sources\nParquet / S3 / Kafka", "storage", shape="cyl")
    g.container("rc", 260, 0, 760, 330, "*Ray cluster (head + CPU and GPU workers)")
    g.box("rd", 280, 40, 330, 110, "*Ray Data pipeline\nread -> map_batches(Preprocess, CPU)\n-> map_batches(ModelActor, num_gpus=1,\n"
          "concurrency=N) -> write", "python", font=11)
    g.box("act", 660, 40, 340, 110, "*GPU actor pool\nmodel loaded once per actor,\nstreaming execution, backpressure,\nautoscaling actors", "good", font=11)
    g.box("rs", 280, 190, 330, 110, "*Ray Serve deployments\nHTTP/gRPC ingress, @serve.batch,\nmodel composition (pipelines)", "python", font=11)
    g.box("gpu", 660, 190, 340, 110, "*GPUs (fractional num_gpus\nallows sharing)", "gpu")
    g.box("pro", 1060, 20, 260, 300, "*+ one framework for batch + online\n+ Python-native (fits torch code)\n+ fine-grained GPU sharing\n"
          "- replaces Spark for this workload\n- new cluster to operate\n- less mature than Triton for\n  multi-framework serving", "note", font=11)
    g.edge("src", "rd", "")
    g.edge("rd", "act", "")
    g.edge("act", "gpu", "")
    g.edge("rs", "gpu", "")
    D.append(g)


# ============================================================ 11 alt: Kubernetes
def d_alt_k8s():
    g = Diagram("alt_k8s", "11. Alternative D: Kubernetes - Spark on K8s + KServe with the Triton runtime",
                "Everything is a pod; GPU nodes are shared by scheduling, scaling is declarative")
    g.container("k", 0, 0, 1060, 360, "*Kubernetes cluster (EKS / on-prem), NVIDIA GPU operator")
    g.box("so", 20, 40, 300, 90, "*Spark operator\nSparkApplication CRD\ndriver + executor pods (CPU pool)", "spark", font=11)
    g.box("ks", 380, 40, 300, 90, "*KServe InferenceService\nruntime: tritonserver\nstorageUri: s3://models/...", "triton", font=11)
    g.box("sc", 740, 40, 300, 90, "*Autoscaling\nKnative / HPA / KEDA on\nconcurrency or queue time", "infra", font=11)
    g.box("cpu", 20, 190, 300, 70, "*CPU node pool (spot)", "spark")
    g.box("gp", 380, 190, 300, 70, "*GPU node pool\n(time-slicing or MIG to share)", "gpu")
    g.box("ig", 740, 190, 300, 70, "*Ingress / service mesh\n(Istio / Envoy), mTLS", "infra")
    g.box("pv", 20, 290, 1020, 50, "*Shared: model store (S3/MinIO), Prometheus + Grafana, image registry (air-gapped: Harbor)", "storage")
    g.box("pro", 1100, 0, 250, 360, "*+ one scheduler for data + serving\n+ scale-to-zero, canary /\n  A-B model rollout built in\n"
          "+ standard for platform teams\n- biggest operational lift\n- K8s + GPU operator expertise\n- air-gapped K8s is work", "note", font=11)
    g.edge("so", "ks", "gRPC\n(predict_batch_udf)")
    g.edge("so", "cpu", "")
    g.edge("ks", "gp", "")
    g.edge("sc", "ks", "", exit=(0, 0.5), entry=(1, 0.5))
    g.edge("ig", "ks", "", exit=(0, 0.3), entry=(1, 0.9), points=[(720, 211), (720, 121)])
    D.append(g)


# ============================================================ 12 alt: async queue
def d_alt_queue():
    g = Diagram("alt_queue", "12. Alternative E: asynchronous, queue-driven inference",
                "Producers publish work; GPU consumers pull at their own pace; results land in a store")
    g.box("p1", 0, 30, 220, 60, "*Sensors / apps", "client")
    g.box("p2", 0, 120, 220, 60, "*Spark jobs (enqueue\npartitions as messages)", "spark")
    g.box("k", 280, 60, 260, 100, "*Kafka / SQS / Redis Streams\nrequests topic\n(partitioned by model)", "storage", shape="cyl")
    g.box("c", 600, 30, 300, 160, "*Consumer group on GPU nodes\npull N messages -> one batch\n-> Triton (localhost)\nor in-process model\ncommit offsets after write", "triton", font=11)
    g.box("r", 960, 60, 240, 100, "*Results topic / Cassandra\n(predictions + lineage)", "storage", shape="cyl")
    g.box("pro", 0, 230, 1200, 70, "*+ absorbs bursts, natural backpressure, retries/DLQ, decouples producers from GPU capacity   "
          "- adds latency (seconds), ordering/idempotency to design, another system to run", "note", font=11)
    g.edge("p1", "k", "")
    g.edge("p2", "k", "")
    g.edge("k", "c", "consume")
    g.edge("c", "r", "produce")
    D.append(g)


# ============================================================ 13 AWS topology
def d_aws():
    g = Diagram("aws_topology", "13. Recommended deployment on AWS",
                "Private subnets, NLB/ALB in front of an Auto Scaling group of Triton GPU nodes; Spark (EMR or self-managed) as a client")
    g.container("vpc", 0, 0, 1320, 520, "*VPC (2-3 AZs)")
    g.container("pub", 20, 40, 260, 460, "*Public subnets")
    g.box("alb", 40, 80, 220, 70, "*ALB (HTTP/2, gRPC)\nWAF, TLS termination", "infra")
    g.box("nat", 40, 200, 220, 60, "*NAT GW / VPC endpoints\n(S3, ECR, CloudWatch)", "infra")
    g.container("pa", 310, 40, 520, 460, "*Private subnets - inference tier")
    g.box("nlb", 330, 80, 480, 60, "*Internal NLB / ALB target group (gRPC health: /v2/health/ready)", "infra")
    for i, x in enumerate((330, 490, 650)):
        g.box(f"t{i}", x, 180, 150, 120, f"*g4dn/g5 #{i + 1}\nTriton container\n(ECS/EKS/ASG)\nIMDSv2, SSM", "triton", font=11)
    g.box("asg", 330, 330, 480, 60, "*Auto Scaling group: target tracking on Triton queue time (custom metric)", "infra", font=11)
    g.box("cw", 330, 420, 480, 60, "*CloudWatch / Managed Prometheus + Grafana (metrics :8002, logs)", "infra", font=11)
    g.container("pb", 860, 40, 440, 460, "*Private subnets - data tier")
    g.box("emr", 880, 80, 400, 110, "*EMR / Spark on EC2 (CPU, spot)\nlean image: pyspark + tritonclient\npredict_batch_udf -> internal NLB", "spark", font=11)
    g.box("s3", 880, 230, 190, 90, "*S3 model repo\n(versioned, KMS)", "storage", shape="cyl")
    g.box("data", 1090, 230, 190, 90, "*S3 / Cassandra\ninputs + outputs", "storage", shape="cyl")
    g.box("ci", 880, 360, 400, 110, "*CodePipeline / GitHub Actions\nexport -> perf_analyzer -> accuracy gate\n-> publish model version -> rolling reload", "good", font=11)
    g.edge("alb", "nlb", "", exit=(1, 0.5), entry=(0, 0.5))
    g.edge("nlb", "t0", "")
    g.edge("nlb", "t1", "")
    g.edge("nlb", "t2", "")
    g.edge("emr", "nlb", "gRPC", exit=(0, 0.4), entry=(1, 0.5))
    g.edge("s3", "t2", "load", dashed=True, exit=(0, 0.5), entry=(1, 0.6))
    g.edge("ci", "s3", "", exit=(0.2, 0), entry=(0.5, 1))
    g.edge("emr", "data", "", exit=(0.8, 1), entry=(0.5, 0), both=True)
    D.append(g)


# ============================================================ 14 air-gapped topology
def d_airgapped():
    g = Diagram("airgapped_topology", "14. Air-gapped / on-prem variant (matches docs/AIRGAPPED_*)",
                "No internet: images, wheels and model versions arrive through a controlled transfer; everything else is identical")
    g.container("in", 0, 0, 300, 400, "*Connected build enclave")
    g.box("b1", 20, 40, 260, 80, "*Build images: tritonserver,\nspark-lean + tritonclient", "client")
    g.box("b2", 20, 150, 260, 80, "*Export + validate models\n(perf_analyzer, accuracy)", "good")
    g.box("b3", 20, 260, 260, 100, "*Bundle: docker save tars,\nmodel repo tar, wheels,\nchecksums + signatures", "storage", shape="cyl")
    g.box("x", 340, 150, 160, 100, "*Transfer\n(data diode /\nmedia, scanned)", "note")
    g.container("ag", 540, 0, 780, 400, "*Air-gapped network")
    g.box("reg", 560, 40, 230, 70, "*Harbor / local registry", "infra")
    g.box("mio", 560, 140, 230, 80, "*MinIO model repository\n(S3 API, versioned)", "storage", shape="cyl")
    g.box("prm", 560, 260, 230, 80, "*Prometheus + Grafana", "infra")
    g.box("tri", 840, 40, 460, 120, "*Triton GPU servers (bare metal / VMs)\nmodel-control-mode=explicit:\nload/unload via API after verification", "triton", font=11)
    g.box("spk", 840, 200, 460, 80, "*Spark cluster (existing 5-node LAN setup)\nCPU executors -> Triton gRPC", "spark", font=11)
    g.box("cas", 840, 310, 460, 60, "*Cassandra / HDFS (inputs, predictions)", "storage", shape="cyl")
    g.edge("b1", "b2", "")
    g.edge("b2", "b3", "")
    g.edge("b3", "x", "", exit=(1, 0.5), entry=(0, 0.8))
    g.edge("x", "reg", "", exit=(1, 0.3), entry=(0, 0.5))
    g.edge("x", "mio", "")
    g.edge("mio", "tri", "load", dashed=True, exit=(1, 0.3), entry=(0, 0.8))
    g.edge("reg", "tri", "pull", dashed=True)
    g.edge("spk", "tri", "gRPC", exit=(0.5, 0), entry=(0.5, 1))
    g.edge("spk", "cas", "", exit=(0.5, 1), entry=(0.5, 0))
    g.edge("tri", "prm", "metrics", dashed=True, exit=(0, 0.85), entry=(1, 0.5), points=[(815, 142), (815, 300)])
    D.append(g)


# ============================================================ 15 sequence
def d_sequence():
    g = Diagram("seq_triton", "15. One Spark task calling Triton - step by step",
                "numbers are the order of events; the dynamic batcher is where requests from different tasks meet")
    cols = [("Spark task\n(executor JVM)", "spark"), ("Python worker\npredict_batch_udf", "python"), ("gRPC client", "python"),
            ("Triton frontend", "triton"), ("Dynamic batcher", "triton"), ("Model instance\n(GPU)", "gpu")]
    for i, (lab, st) in enumerate(cols):
        g.box(f"h{i}", i * 210, 0, 180, 50, "*" + lab, st)
        g.box(f"l{i}", i * 210 + 88, 60, 4, 520, "", "white")
    msgs = [(0, 1, "1. Arrow batch of rows"), (1, 1, "2. first call: make_predict_fn() -> client (cached)"),
            (1, 2, "3. rows -> np array (B, 3,224,224)"), (2, 3, "4. InferRequest (protobuf, B x 602 KB)"),
            (3, 4, "5. enqueue; wait <= max_queue_delay"), (4, 5, "6. merged batch (e.g. 4 requests = 256)"),
            (5, 4, "7. OUTPUT__0 (256 x 1000)"), (4, 3, "8. split per request"), (3, 2, "9. InferResponse"),
            (2, 1, "10. np array (B, 1000)"), (1, 0, "11. Arrow result batch")]
    for k, (a, b, lab) in enumerate(msgs):
        y = 90 + k * 44
        xa, xb = a * 210 + 90, b * 210 + 90
        if a == b:
            g.box(f"m{k}", xa + 6, y - 12, 330, 26, lab, "note", font=10)
            continue
        g.box(f"pa{k}", xa - 1, y, 2, 2, "", "white")
        g.box(f"pb{k}", xb - 1, y, 2, 2, "", "white")
        g.edge(f"pa{k}", f"pb{k}", lab, exit=(0.5, 0.5), entry=(0.5, 0.5), color="#7b4f9d" if a > 1 or b > 1 else "#333333",
               dashed=b < a)
    D.append(g)


# ============================================================ TDD: sequence helper
def sequence(g, cols, msgs, colw=210, top=60, step=40):
    for i, (lab, st) in enumerate(cols):
        g.box(f"h{i}", i * colw, 0, colw - 30, 50, "*" + lab, st, font=11)
        g.box(f"l{i}", i * colw + (colw - 30) / 2 - 2, top, 4, step * len(msgs) + 30, "", "white")
    for k, (a, b, lab) in enumerate(msgs):
        y = top + 24 + k * step
        xa, xb = a * colw + (colw - 30) / 2, b * colw + (colw - 30) / 2
        if a == b:
            g.box(f"m{k}", xa + 6, y - 13, colw * 1.6, 26, lab, "note", font=10)
            continue
        g.box(f"pa{k}", xa - 1, y, 2, 2, "", "white")
        g.box(f"pb{k}", xb - 1, y, 2, 2, "", "white")
        g.edge(f"pa{k}", f"pb{k}", lab, exit=(0.5, 0.5), entry=(0.5, 0.5), dashed=b < a,
               color="#333333" if b > a else "#57606a")


# ============================================================ 16 module map
def d_module_map():
    g = Diagram("tdd_module_map", "16. Code architecture: packages, modules and who calls whom",
                "Arrows = imports / calls. Framework modules in solid boxes; CLI entry points on the left")
    g.container("cli", 0, 0, 250, 610, "*Entry points (CLI)")
    g.box("sj", 20, 40, 210, 60, "*submit_job.py\nBYOM tensor model -> Spark", "driver", font=11)
    g.box("spj", 20, 120, 210, 60, "*submit_pipeline_job.py\nfile pipelines (ner_translate)", "driver", font=11)
    g.box("rb", 20, 200, 210, 60, "*benchmark/run_benchmark.py\n3 modes, 10 models", "driver", font=11)
    g.box("cb", 20, 280, 210, 60, "*benchmark/cluster_benchmark.py\ncpu/gpu/hybrid on a cluster", "driver", font=11)
    g.box("sv", 20, 360, 210, 60, "*benchmark/spark_vs_single_gpu.py\n+ quick_compare, incremental", "driver", font=11)
    g.box("srv", 20, 450, 210, 70, "*serve.py (uvicorn)\nner_translate 'kitchen'\nPOST /predict", "triton", font=11)
    g.box("tool", 20, 540, 210, 55, "*tooling: run_campaign.sh,\nlowlevel_trace, spark_modes_stats", "white", font=10)
    g.container("inf", 290, 0, 520, 610, "*inference/ - execution engines")
    g.box("ce", 310, 40, 230, 90, "*cluster_engine.py\ncreate_cluster_session()\nrun_cluster_inference()\n_get_class_map()", "spark", font=11)
    g.box("ceu", 560, 40, 230, 90, "*cluster_engine_udf.py\nrun_cluster_inference_udf()", "spark", font=11)
    g.box("pbu", 560, 150, 230, 60, "*predict_batch_udf.py\npandas scalar-iterator UDF", "python", font=11)
    g.box("tpe", 310, 150, 230, 90, "*text_pipeline_engine.py\nrun_text_pipeline_job()\n..._via_service() (HTTP)", "spark", font=11)
    g.box("dg", 310, 260, 230, 80, "*distributed_gpu.py\ncreate_spark_session()\nrun_distributed_gpu_inference()", "spark", font=11)
    g.box("sg", 310, 370, 230, 60, "*single_gpu.py\nrun_single_gpu_inference()", "gpu", font=11)
    g.box("hy", 560, 370, 230, 60, "*hybrid_cpu_gpu.py\nrun_hybrid_inference()", "gpu", font=11)
    g.box("cs", 310, 460, 230, 60, "*cuda_streams_engine.py\nCUDAStreamsEngine", "gpu", font=11)
    g.box("gm", 560, 460, 230, 60, "*gpu_memory_manager.py\nGPUMemoryManager", "gpu", font=11)
    g.container("mod", 850, 0, 520, 420, "*models/ - model layer")
    g.box("reg", 870, 40, 230, 80, "*__init__.get_default_registry()\nmodel_registry.ModelRegistry\n(10 built-ins, metadata)", "python", font=11)
    g.box("pl", 1120, 40, 230, 80, "*plugin_loader.py\nregister_plugins()\nget_plugin_class_map()", "python", font=11)
    g.box("bi", 870, 150, 230, 110, "*built-in classes\new_signal_model, signal_models,\nimage_models (torchvision),\nyolo_model (ultralytics or\nfallback CNN)", "python", font=11)
    g.box("pg", 1120, 150, 230, 60, "*plugins/manifest.json\n+ example_model.py", "storage", font=11)
    g.box("pp", 1120, 230, 230, 170, "*pipelines/manifest.json\nner_translate/\n  pipeline.py load()/run()\n  mt_ner_all_formats.py\n  (OCR, NLLB, GLiNER)\n  serve.py (FastAPI)\n  requirements.txt", "storage", font=11)
    g.box("wt", 870, 290, 230, 60, "*models/weights/ (not in git)\nGLiNER, NLLB checkpoints", "storage", shape="cyl", font=11)
    g.container("oth", 850, 440, 520, 170, "*data/ + monitoring/")
    g.box("dt", 870, 480, 230, 110, "*data/\nsignal_generator.py\nimage_generator.py\ngenerate_mixed_data()", "white", font=11)
    g.box("mo", 1120, 480, 230, 110, "*monitoring/\ncloudwatch_publisher\ngpu / spark / benchmark\nmetrics publishers", "infra", font=11)
    for a, b in [("sj", "ce"), ("spj", "tpe"), ("rb", "dg"), ("cb", "ce")]:
        g.edge(a, b, "")
    g.edge("sj", "ceu", "--engine udf", exit=(1, 0.2), entry=(0.5, 0), points=[(270, 52), (270, -14), (675, -14)])
    g.edge("spj", "srv", "", dashed=True, exit=(0, 0.5), entry=(0, 0.5), points=[(8, 150), (8, 485)])
    g.edge("tpe", "srv", "HTTP", dashed=True, exit=(0, 0.9), entry=(1, 0.5), points=[(270, 231), (270, 485)], label_seg=2)
    g.edge("rb", "sg", "", exit=(1, 0.8), entry=(0, 0.5), points=[(280, 248), (280, 400)])
    g.edge("rb", "hy", "", exit=(1, 0.95), entry=(0.5, 0), points=[(275, 257), (275, 355), (675, 355)])
    g.edge("ceu", "pbu", "")
    g.edge("sg", "cs", "")
    g.edge("hy", "cs", "", exit=(0, 0.8), entry=(1, 0.3))
    g.edge("hy", "gm", "")
    g.edge("ce", "reg", "class map (_get_class_map)", exit=(0.8, 0), entry=(0.5, 0), points=[(494, -32), (985, -32)])
    g.edge("reg", "pl", "")
    g.edge("reg", "bi", "")
    g.edge("pl", "pg", "")
    D.append(g)


# ============================================================ 17 trace: submit_job rdd
def d_seq_submit():
    g = Diagram("tdd_seq_submit_rdd", "17. Request -> response: submit_job.py --engine rdd",
                "Every hop of one BYOM job; dashed = returns. Line references in the TDD, section 5.1")
    cols = [("CLI\nsubmit_job.main()", "driver"), ("Model layer\nregistry / plugins", "python"), ("cluster_engine\n(driver side)", "spark"),
            ("Driver JVM\n(Py4J, DAGScheduler)", "spark"), ("Executor JVM\n(worker node)", "spark"), ("Python worker\nprocess_partition()", "python"),
            ("Device\nCPU / CUDA", "gpu")]
    msgs = [(0, 1, "1 get_default_registry() + register_plugins()"), (0, 0, "2 load .npy or np.random.randn(n, *input_shape)"),
            (0, 1, "3 registry.load_model(name, 'cpu')"), (0, 2, "4 create_cluster_session(app, master)"), (2, 3, "5 SparkSession (Py4J)"),
            (0, 2, "6 run_cluster_inference(spark, data, models, P, B, mode)"), (2, 2, "7 torch.save(state_dict) -> sc.broadcast; slice P chunks"),
            (2, 3, "8 parallelize(P).mapPartitions(fn).collect()"), (3, 4, "9 P tasks (closure + partition)"), (4, 5, "10 socket: pickled partition"),
            (5, 5, "11 device = cpu | cuda (per task); build + load models"), (5, 6, "12 from_numpy().to(device); model(x)"),
            (6, 5, "13 outputs (discarded, counted)"), (5, 4, "14 yield {host, device, load s, infer s, counts}"),
            (4, 3, "15 task result"), (3, 2, "16 collect() -> partition_results"), (2, 0, "17 {throughput, per_model, details}"),
            (0, 0, "18 print summary; results/<model>_<ts>.json (+ S3 if ARTIFACTS_BUCKET)")]
    sequence(g, cols, msgs, colw=200, step=38)
    D.append(g)


# ============================================================ 18 trace: pipeline service vs cluster
def d_seq_pipeline():
    g = Diagram("tdd_seq_pipeline", "18. Request -> response: submit_pipeline_job.py (cluster vs service execution)",
                "Same partitioning; the difference is where load()/run() executes")
    cols = [("CLI\nsubmit_pipeline_job", "driver"), ("text_pipeline_engine\n(driver)", "spark"), ("Spark executor\nPython worker", "python"),
            ("Kitchen: serve.py\n(FastAPI, GPU)", "triton"), ("pipeline.py /\nmt_ner_all_formats", "python")]
    msgs = [(0, 0, "1 manifest lookup; collect files; resolve master (CLI > env > manifest > local[4])"),
            (0, 0, "2 execution-mode: service | cluster | auto (service host resolvable?)"),
            (0, 1, "3a cluster: run_text_pipeline_job(spark, paths, mod.load, mod.run)"), (1, 2, "4a parallelize(paths, min(P, n)).mapPartitions"),
            (2, 4, "5a load() per task: GLiNER + NLLB + LID"), (4, 2, "6a run(loaded, paths) -> {file: result}"),
            (0, 1, "3b service: run_text_pipeline_job_via_service(spark, paths, url)"), (1, 2, "4b mapPartitions (lean image, requests only)"),
            (2, 3, "5b POST /predict {paths, labels}"), (3, 4, "6b pipeline.run(loaded once at startup)"), (4, 3, "7b results"),
            (3, 2, "8b JSON {file: result}"), (2, 1, "9 yield per-partition results"), (1, 0, "10 merged results + partition details"),
            (0, 0, "11 results/<pipeline>_<ts>.json (entities, language, translation)")]
    sequence(g, cols, msgs, colw=260, step=38)
    D.append(g)


# ============================================================ 19 plugin extension flow
def d_plugin_flow():
    g = Diagram("tdd_plugin_flow", "19. Extension points: where new code plugs in",
                "Tensor models (BYOM plugins), file pipelines, engines, Triton models - each needs only the files listed")
    g.box("p1", 0, 0, 300, 150, "*A. Tensor model plugin (BYOM)\n1 models/plugins/my_model.py\n   class MyModel(nn.Module), no-arg __init__\n"
          "2 models/plugins/manifest.json entry\n   module, class_name, input_shape, weights_path\n3 python submit_job.py --model my_model", "good", font=11)
    g.box("p2", 330, 0, 300, 150, "*B. File pipeline\n1 models/pipelines/<name>/pipeline.py\n   load() -> state; run(state, paths) -> dict\n"
          "2 models/pipelines/manifest.json\n   module, service_url?, master_url?\n3 requirements.txt + Dockerfile.<name>\n4 optional serve.py (kitchen)", "good", font=11)
    g.box("p3", 660, 0, 300, 150, "*C. Execution engine\n1 inference/my_engine.py\n   run_...(spark, data, models, P, B,\n   device_mode) -> same keys as\n   run_cluster_inference()\n2 add to submit_job --engine", "good", font=11)
    g.box("p4", 990, 0, 300, 150, "*D. Triton-served model\n1 add to EXPORT in\n   benchmark/triton_export.py\n2 export -> model repo\n3 --verify vs eager\n4 client via predict_batch_udf", "good", font=11)
    g.box("r", 0, 210, 630, 70, "*ModelRegistry (models/__init__.py + plugin_loader.register_plugins)\nname -> class, input_shape, category, est. memory", "python")
    g.box("cm", 660, 210, 300, 70, "*cluster_engine._get_class_map()\nbuilt-ins + get_plugin_class_map()", "spark")
    g.box("pm", 330, 310, 300, 60, "*text_pipeline_engine\n(cluster or via_service)", "spark")
    g.box("ex", 660, 310, 630, 60, "*Spark executors (Python workers): rebuild class by name, load broadcast weights", "spark")
    g.edge("p1", "r", "")
    g.edge("p1", "cm", "", exit=(0.8, 1), entry=(0, 0.5), points=[(240, 190), (645, 190), (645, 245)])
    g.edge("p2", "pm", "", exit=(0.5, 1), entry=(0.5, 0), points=[(480, 290)])
    g.edge("p3", "cm", "")
    g.edge("cm", "ex", "")
    g.edge("r", "cm", "")
    g.edge("p4", "ex", "gRPC from UDF", exit=(0.5, 1), entry=(0.9, 0))
    D.append(g)


# ============================================================ 20 observability map
def d_observability():
    g = Diagram("tdd_observability", "20. Debugging and tracing: where every signal lives",
                "Follow a request by app id -> job -> stage -> task -> executor -> Python worker pid -> partition details")
    g.box("drv", 0, 0, 260, 110, "*Driver console\n[submit_pipeline_job] mode line,\nresult summary JSON,\nPython tracebacks of failed tasks", "driver", font=11)
    g.box("res", 0, 140, 260, 90, "*results/*.json\nper-run summary, partition_details,\nspark_ui_stats (REST snapshot)", "storage", shape="cyl", font=11)
    g.box("ui", 300, 0, 260, 110, "*Spark UIs\nmaster :8080 (workers, apps)\napplication :4040 (jobs, stages,\ntasks, executors, SQL plans)", "spark", font=11)
    g.box("rest", 300, 140, 260, 90, "*REST /api/v1/applications/...\njobs, stages, executors\n(capture_spark_stats.py)", "spark", font=11)
    g.box("ev", 300, 260, 260, 80, "*Event logs (spark.eventLog.enabled)\none JSON line per task\n-> analyze_modes_stats.py", "storage", shape="cyl", font=11)
    g.box("ex", 600, 0, 280, 110, "*Executor logs\n/opt/spark/work/<app>/<exec>/stderr\n[Executor] host, pid, device,\nmodel_load_time; Python errors", "python", font=11)
    g.box("wl", 600, 140, 280, 90, "*Master / worker daemon logs\n/opt/spark/logs/*master*, *worker*\n(registration, executor launch)", "spark", font=11)
    g.box("gpu", 920, 0, 280, 110, "*GPU\nnvidia-smi / dmon, torch.profiler\n(benchmark/lowlevel_trace.py),\nCUDA_LAUNCH_BLOCKING=1", "gpu", font=11)
    g.box("cw", 920, 140, 280, 90, "*CloudWatch (AWS)\nmonitoring/*_publisher.py\nSparkInference/{Spark,GPU,Benchmark}", "infra", font=11)
    g.box("kit", 600, 260, 280, 80, "*Kitchen / Triton logs\ndocker logs ner-translate-server\nTriton :8002 metrics", "triton", font=11)
    g.edge("drv", "res", "writes")
    g.edge("ui", "rest", "same data")
    g.edge("rest", "ev", "persisted", dashed=True)
    g.edge("ex", "wl", "", dashed=True)
    D.append(g)


# ============================================================ 21 air-gap simulation topology
def d_airgap_sim():
    g = Diagram("airgap_sim_topology", "21. Air-gapped cluster simulation: models in HDFS, nodes fetch into a local cache",
                "deploy/docker-compose.airgap_sim.yml - profiles hdfs / service / cluster; MODEL_STORE_URI selects where models come from")
    g.container("hd", 0, 0, 330, 360, "*HDFS (profile: hdfs) - 'master storage'")
    g.box("nn", 20, 40, 290, 80, "*hdfs-namenode :8020 RPC, :9870 WebHDFS\nfile system metadata: /models/weights/...\nredirects reads to the datanode", "storage", font=11)
    g.box("dn", 20, 150, 290, 70, "*hdfs-datanode :9866 data, :9864 HTTP\nstores the blocks (128 MB each)", "storage", font=11)
    g.box("st", 20, 250, 290, 90, "*Upload once (T03)\nhdfs dfs -put gliner-multi\n  nllb-200-distilled-600M hf_cache\n  /models/weights/   (4.6 GB)", "note", font=11)
    g.container("sv", 370, 0, 460, 360, "*Service mode (profile: service)")
    g.box("kit", 390, 40, 420, 110, "*ner-translate-server  (the 'kitchen', GPU)\nload(): model_store.resolve(MODEL_STORE_URI/<model>)\n -> WebHDFS download into kitchen-cache (once)\n -> GLiNER + NLLB loaded on the GPU, POST /predict", "triton", font=11)
    g.box("smw", 390, 180, 200, 80, "*ner-translate-master\nlean Spark master + driver", "spark", font=11)
    g.box("sww", 610, 180, 200, 80, "*ner-translate-worker\nlean executor: POST paths", "spark", font=11)
    g.box("kc", 390, 290, 420, 50, "*kitchen-cache volume = that node's local disk (/model_cache)", "storage", shape="cyl", font=11)
    g.container("cl", 870, 0, 460, 360, "*Cluster mode (profile: cluster)")
    g.box("cm", 890, 40, 200, 80, "*ner-cluster-master\nSpark master + driver", "spark", font=11)
    g.box("cw", 1110, 40, 200, 110, "*ner-cluster-worker (GPU)\nexecutor: load() per task\n-> model_store fetch\n-> NER in-process", "python", font=11)
    g.box("wc", 890, 180, 420, 50, "*worker-cache volume = worker node's local disk", "storage", shape="cyl", font=11)
    g.box("fs", 890, 260, 420, 80, "*Alternative source: master file system\nMODEL_STORE_URI=file:///mnt/models (MODEL_FS_DIR mounted\nread-only on every node) - no copy, no HDFS", "note", font=11)
    g.box("data", 370, 390, 960, 50, "*Shared data volume ../data -> /app/data on every node: the same file paths are valid for Spark and the kitchen", "white", font=11)
    g.edge("nn", "dn", "block locations")
    g.edge("st", "dn", "", dashed=True, exit=(0.5, 0), entry=(0.5, 1))
    g.edge("kit", "nn", "WebHDFS GET (op=OPEN)", exit=(0, 0.3), entry=(1, 0.5), color="#7b4f9d")
    g.edge("cw", "nn", "WebHDFS GET", exit=(0.5, 0), entry=(0.5, 0), points=[(1210, -18), (165, -18)], color="#7b4f9d")
    g.edge("kit", "kc", "cache", dashed=True, exit=(0, 0.9), entry=(0, 0.5), points=[(380, 139), (380, 315)])
    g.edge("sww", "kit", "HTTP POST /predict", exit=(0.5, 0), entry=(0.8, 1))
    g.edge("smw", "sww", "tasks")
    g.edge("cm", "cw", "tasks")
    g.edge("cw", "wc", "cache", dashed=True, exit=(0.5, 1), entry=(0.8, 0))
    D.append(g)


# ============================================================ 22 model fetch sequence
def d_model_fetch():
    g = Diagram("model_fetch_sequence", "22. How a node gets a model from HDFS (models/model_store.py)",
                "WebHDFS = HDFS's HTTP API; only the Python standard library is needed on the node")
    cols = [("pipeline.load()", "python"), ("model_store.resolve()", "python"), ("node cache\n/model_cache", "storage"),
            ("namenode :9870", "storage"), ("datanode :9864", "storage")]
    msgs = [(0, 1, "1 resolve(MODEL_STORE_URI + '/gliner-multi')"), (1, 2, "2 <dir>.complete marker present?"),
            (2, 1, "3a yes -> 'cache hit', return local dir (works even if HDFS is down)"),
            (1, 3, "3b no -> GETFILESTATUS / LISTSTATUS (walk the tree)"), (1, 3, "4 per file: GET ?op=OPEN"),
            (3, 1, "5 HTTP 307 redirect to the datanode holding the blocks"), (1, 4, "6 follow redirect, stream bytes (8 MB chunks)"),
            (4, 1, "7 file bytes"), (1, 2, "8 write into .partial-*/, check size == HDFS length"),
            (1, 2, "9 os.replace(.partial -> final) + write .complete (atomic publish)"), (1, 0, "10 local path -> from_pretrained(local path)")]
    sequence(g, cols, msgs, colw=260, step=40)
    D.append(g)


# ============================================================ 23 NER document pipeline
def d_ner_pipeline():
    g = Diagram("ner_document_pipeline", "23. What happens to every document (models/pipelines/ner_translate/mt_ner_all_formats.py)",
                "process_paths_batched(): extract -> detect -> route -> translate (batched per language) -> NER (batched across documents) -> merge")
    g.box("in", 0, 40, 170, 90, "*Input file\ntxt md csv json html\npdf docx odt rtf epub\npptx xlsx xls ods\npng jpg tif ...", "client", font=10)
    g.box("ex", 200, 40, 190, 90, "*1 extract_text()\nby extension; PDF text\nlayer, else OCR 300 dpi\n(tesseract, 11 Indic+EN\nlanguages)", "python", font=10)
    g.box("pp", 420, 40, 160, 90, "*2 preprocess()\nNFC normalise,\nstrip BOM / nbsp,\ncollapse spaces", "python", font=10)
    g.box("li", 610, 40, 170, 90, "*3 detect_language()\npy3langid on the\nfirst 1,000 chars", "python", font=10)
    g.box("ro", 810, 40, 190, 90, "*4 route\nen fr de es it pt -> direct\nhi mr te ta kn bn gu pa ml\nur ar zh ja ko ru ... -> translate", "note", font=10)
    g.box("tr", 810, 180, 190, 110, "*5 translate (NLLB-200)\none unit per sentence / line\n(danda-aware), grouped by\nsource language, batch 8,\n<=400 tokens -> English", "gpu", font=10)
    g.box("ch", 580, 180, 200, 110, "*6 chunk_text()\nsentence split, <=1,500\nchars, keep offsets;\nchunks of ALL documents\npooled together", "python", font=10)
    g.box("ne", 350, 180, 200, 110, "*7 GLiNER NER (fp16)\nzero-shot, 19 labels\n(person, rank, unit,\nweapon, location ...),\nthreshold 0.35, batch 16", "gpu", font=10)
    g.box("ph", 120, 180, 200, 110, "*8 regex phone numbers\non translated AND\noriginal text (digits\nsurvive translation)", "python", font=10)
    g.box("out", 0, 330, 1000, 70, "*9 per document: {path, language, translated, text_used, original_text, entities_all, entities_unique (deduped by text+type, best score)} - keyed by file name", "good", font=11)
    for a, b in [("in", "ex"), ("ex", "pp"), ("pp", "li"), ("li", "ro")]:
        g.edge(a, b, "")
    g.edge("ro", "tr", "translate path")
    g.edge("ro", "ch", "direct path", exit=(0.1, 1), entry=(1, 0.2), points=[(829, 150), (800, 150), (800, 202)])
    g.edge("tr", "ch", "English text")
    g.edge("ch", "ne", "")
    g.edge("ne", "ph", "")
    g.edge("ph", "out", "", exit=(0.5, 1), entry=(0.22, 0))
    D.append(g)


# ============================================================ 24 lifecycle
def d_lifecycle():
    g = Diagram("ner_lifecycle", "24. NER on the cluster - complete lifecycle from build to shutdown",
                "Left to right, top to bottom in time; each phase lists what runs and what state it leaves behind")
    phases = [("0 Build (connected)", "images: spark-lean,\nner-translate-server,\nner-translate-worker,\napache/hadoop; weights\nfrom Hugging Face", "client"),
              ("1 Transfer", "docker save tars +\nweights + code bundle\n-> media / diode ->\ndocker load; checksums", "note"),
              ("2 Store models", "hdfs dfs -put gliner-multi,\nnllb-600M, hf_cache\n-> /models/weights\n(or copy to master FS)", "storage"),
              ("3 Start services", "HDFS; kitchen: fetch\nmodels -> cache -> GPU;\nSpark master + workers\nregister", "triton"),
              ("4 Submit", "submit_pipeline_job:\nmanifest, files, master,\nexecution mode ->\nSparkSession", "driver"),
              ("5 Execute", "P tasks on worker slots;\nservice: POST /predict\ncluster: load() + run()\nin the executor", "spark"),
              ("6 Collect", "per-partition results\n-> driver merges ->\nresults/ner_translate_\n<ts>.json", "good"),
              ("7 Stop", "spark.stop(); compose\ndown (caches + HDFS\nkept); new model version\n= new HDFS dir", "bad")]
    for i, (t, d, st) in enumerate(phases):  # two rows of four
        x, y = (i % 4) * 240, (i // 4) * 240
        g.box(f"p{i}", x, y, 200, 40, "*" + t, st, font=12)
        g.box(f"d{i}", x, y + 60, 200, 110, d, "white", font=11)
        g.edge(f"p{i}", f"d{i}", "")
        if i == 4:
            g.edge("p3", "p4", "", exit=(1, 0.5), entry=(0.5, 0), points=[(920, 20), (920, 205), (100, 205)])
        elif i:
            g.edge(f"p{i - 1}", f"p{i}", "")
    D.append(g)


# ============================================================ 25 data movement paths
def d_data_paths():
    g = Diagram("ner_data_paths", "25. NER on Spark - every data movement path",
                "(n) = path number in the text. Service mode: the kitchen reads the documents; cluster mode: the Python worker does (the primed paths)")
    g.container("st", 0, 0, 300, 720, "*Storage (outside Spark)")
    g.box("data", 20, 40, 260, 100, "*Shared data volume\n/app/data/ner_samples/*\nhost folder here; NFS on a real cluster\nsame absolute path on every node", "storage", font=11)
    g.box("hdfs", 20, 400, 260, 110, "*HDFS /models/weights\ngliner-multi 2.3 GB\nnllb-200-distilled-600M 2.5 GB\nhf_cache 4 MB\nnamenode :9870 / datanode :9864", "storage", font=11)
    g.box("res", 20, 600, 260, 80, "*Results volume\n/app/results/\nner_translate_<ts>.json", "storage", shape="cyl", font=11)
    g.container("mn", 340, 0, 330, 720, "*Master node (the driver runs here)")
    g.box("cli", 360, 40, 290, 70, "*Driver Python\npython submit_pipeline_job.py\n-> text_pipeline_engine", "driver", font=11)
    g.box("djvm", 360, 170, 290, 110, "*Driver JVM (SparkSubmit via Py4J)\nSparkContext, DAGScheduler,\nTaskScheduler, BlockManager,\nevent log writer", "spark", font=11)
    g.box("sm", 360, 340, 290, 60, "*Spark Master :7077\nworkers, cores, executors", "spark", font=11)
    g.box("nt", 360, 590, 290, 110, "What travels through Spark: file names\n(~40-70 bytes each), the pickled\nclosure, broadcast settings and the\nresult dicts. Document bytes never do.", "note", font=11)
    g.container("wn", 710, 0, 330, 720, "*Worker node")
    g.box("wd", 730, 40, 290, 55, "*Worker daemon\n-c 4 -m 2g (service) / 6g (cluster)", "spark", font=11)
    g.box("exe", 730, 150, 290, 110, "*Executor JVM\nCoarseGrainedExecutorBackend\n4 cores / spark.task.cpus 2 = 2 slots\nTaskRunner threads", "spark", font=11)
    g.box("pyw", 730, 320, 290, 100, "*Python worker (one per running task)\nforked by pyspark.daemon\nruns process_partition()\ncluster mode: reads the documents (8')", "python", font=11)
    g.box("wc", 730, 470, 135, 60, "*/model_cache\n(cluster mode)", "storage", shape="cyl", font=10)
    g.box("wg", 885, 470, 135, 60, "*GPU\n(cluster mode)", "gpu", font=10)
    g.container("kn", 1080, 0, 330, 720, "*Model server node (service mode)")
    g.box("k", 1100, 150, 290, 110, "*Kitchen: uvicorn + FastAPI\nPOST /predict (thread pool)\nGLiNER + NLLB loaded once\nat startup", "triton", font=11)
    g.box("kc", 1100, 320, 135, 70, "*/model_cache\nkitchen-cache", "storage", shape="cyl", font=10)
    g.box("kg", 1255, 320, 135, 70, "*GPU GTX 1650\n4 GB VRAM", "gpu", font=10)
    g.edge("cli", "data", "(3) list names", exit=(0, 0.5), entry=(1, 0.35))
    g.edge("data", "k", "(8) document bytes read by the kitchen (service mode)", dashed=True, exit=(0.94, 0), entry=(0.93, 0),
           points=[(264.4, -22), (1370, -22)], label_seg=1)
    g.edge("cli", "djvm", "(4) Py4J: pickled\npaths + closure", exit=(0.3, 1), entry=(0.3, 0))
    g.edge("djvm", "cli", "(9c) local socket", dashed=True, exit=(0.75, 0), entry=(0.75, 1))
    g.edge("djvm", "sm", "(10) register app", dashed=True)
    g.edge("sm", "wd", "(10)", dashed=True, exit=(1, 0.3), entry=(0, 0.5), points=[(680, 358), (680, 67)], label_seg=2)
    g.edge("wd", "exe", "spawns")
    g.edge("djvm", "exe", "(5) LaunchTask + taskBinary", exit=(1, 0.5), entry=(0, 0.68))
    g.edge("exe", "djvm", "(9b) StatusUpdate + result bytes", dashed=True, exit=(0, 0.9), entry=(1, 0.72))
    g.edge("exe", "pyw", "(6) local socket\nframed pickle", both=True)
    g.edge("pyw", "k", "(7) POST /predict {paths}\n<- JSON results", both=True, exit=(1, 0.5), entry=(0, 0.77), points=[(1060, 370), (1060, 235)])
    g.edge("kc", "k", "(2) load", exit=(0.5, 0), entry=(0.25, 1))
    g.edge("k", "kg", "PCIe", exit=(0.75, 1), entry=(0.5, 0))
    g.edge("hdfs", "kc", "(1) WebHDFS GET, once per node", exit=(1, 0.5), entry=(0.5, 1), points=[(700, 455), (1167, 455)], label_seg=0)
    g.edge("hdfs", "wc", "(1') WebHDFS (cluster mode)", exit=(1, 0.909), entry=(0, 0.5))
    g.edge("wc", "pyw", "(2')", exit=(0.5, 0), entry=(0.23, 1))
    g.edge("pyw", "wg", "PCIe", exit=(0.8, 1), entry=(0.5, 0))
    g.edge("cli", "res", "(9d) results JSON", exit=(0, 0.85), entry=(1, 0.5), points=[(325, 99.5), (325, 640)], label_seg=1)
    D.append(g)


# ============================================================ 26 Spark call sequence
def d_spark_sequence():
    g = Diagram("ner_spark_sequence", "26. One NER job through Spark - process by process (service mode)",
                "Solid = request / call, dashed = reply. Cluster mode replaces steps 13-15 by load() + run() inside the Python worker")
    cols = [("Driver Python\nsubmit_pipeline_job", "driver"), ("Driver JVM\nSparkContext", "spark"), ("Spark master\n+ worker daemon", "spark"),
            ("Executor JVM", "spark"), ("Python worker\n(pyspark.daemon)", "python"), ("Kitchen\nFastAPI + GPU", "triton")]
    msgs = [(0, 0, "1 argparse, manifest, list data/ner_samples -> 6 absolute paths"),
            (0, 1, "2 Py4J: launch SparkSubmit JVM, new SparkContext"),
            (1, 2, "3 RegisterApplication (RPC :7077)"),
            (2, 3, "4 LaunchExecutor -> worker forks the executor JVM"),
            (3, 1, "5 RegisterExecutor (4 cores)"),
            (0, 1, "6 parallelize: 2 pickled batches of 3 paths"),
            (0, 1, "7 mapPartitions().collect(): pickled closure"),
            (1, 1, "8 DAGScheduler: 1 job, 1 ResultStage, 2 tasks; taskBinary broadcast"),
            (1, 3, "9 LaunchTask x2 (task + its path batch)"),
            (3, 1, "10 fetch taskBinary + broadcast blocks"),
            (3, 4, "11 get worker from daemon; write header, closure, paths"),
            (4, 4, "12 unpickle closure; process_partition(iterator of 3 paths)"),
            (4, 5, "13 POST /predict {paths: 3 absolute paths}"),
            (5, 5, "14 read files, OCR, language id, NLLB, GLiNER on the GPU"),
            (5, 4, "15 200 OK, JSON {file: result}"),
            (4, 3, "16 pickled dict + timing + END_OF_STREAM"),
            (3, 1, "17 StatusUpdate FINISHED + DirectTaskResult"),
            (1, 1, "18 both tasks done -> job done; results in partition order"),
            (1, 0, "19 collectAndServe: local socket, 2 dicts"),
            (0, 0, "20 merge by file name, write results/ner_translate_<ts>.json"),
            (0, 1, "21 spark.stop(): executor killed, app FINISHED")]
    sequence(g, cols, msgs, colw=235, step=34)
    D.append(g)


# ============================================================ 27 tensor path inside the model process
def d_tensor_path():
    g = Diagram("ner_tensor_path", "27. Inside the model process - from file bytes to entities",
                "Top row runs on CPU cores, bottom row on the GPU; every crossing is a PCIe copy (the kitchen, or the Python worker in cluster mode)")
    g.container("cpu", 0, 0, 1400, 200, "*CPU (Python process)")
    g.container("gpu", 0, 300, 1400, 170, "*GPU (CUDA kernels, weights resident in VRAM)")
    cpu = [("f", "*1 File bytes\nopen()/read from the\nshared volume\n(page cache)", "storage"),
           ("x", "*2 extract_text\n.txt: decode UTF-8\n.png: Pillow decode ->\ntesseract subprocess", "python"),
           ("p", "*3 preprocess + LID\nNFC, whitespace\npy3langid on first\n1,000 chars", "python"),
           ("t", "*4 NLLB tokenizer\nSentencePiece ->\nint64 ids [B, T]\n(B <= 8, T <= 400)", "python"),
           ("d", "*6 decode ids\n-> English text\nchunk_text <= 1,500\nchars per chunk", "python"),
           ("gt", "*7 GLiNER prep\nwords + 19 label\nprompts -> DeBERTa\ntokenizer ids", "python"),
           ("o", "*9 postprocess\nthreshold 0.35, offsets,\ndedupe, phone regex\n-> dict -> JSON", "python")]
    for i, (cid, lab, st) in enumerate(cpu):
        g.box(cid, 15 + i * 198, 50, 178, 130, lab, st, font=11)
    g.box("ne", 610, 340, 330, 110, "*5 NLLB-200 600M (fp32)\nencoder once per batch, then the decoder\nruns one step per output token (KV cache)\nuntil EOS / 400 tokens", "gpu", font=11)
    g.box("ge", 1000, 340, 380, 110, "*8 GLiNER (fp16)\nmDeBERTa-v3 encoder over words + labels\nspan representations x label embeddings\n-> sigmoid scores per (span, label)", "gpu", font=11)
    for a, b in (("f", "x"), ("x", "p"), ("p", "t"), ("d", "gt")):
        g.edge(a, b, "")
    g.edge("p", "gt", "English / well-supported:\nno translation", dashed=True, exit=(0.5, 0), entry=(0.5, 0),
           points=[(501, 32), (1104, 32)], label_seg=1)
    g.edge("t", "ne", "H2D ids", exit=(0.5, 1), entry=(0.2, 0))
    g.edge("ne", "d", "D2H ids", dashed=True, exit=(0.8, 0), entry=(0.5, 1))
    g.edge("gt", "ge", "H2D ids + masks", exit=(0.5, 1), entry=(0.3, 0))
    g.edge("ge", "o", "D2H spans + scores", dashed=True, exit=(0.8, 0), entry=(0.5, 1))
    D.append(g)


# ============================================================ 28 image family tree
def d_image_tree():
    g = Diagram("docker_image_tree", "28. Docker images - what is built from what",
                "Three Dockerfiles, four images; arrows = FROM / build target. Sizes as listed by docker images on the laptop")
    g.box("ubu", 0, 40, 220, 60, "*ubuntu:22.04\n(pulled)", "client", font=11)
    g.box("base", 280, 25, 300, 90, "*stage spark-base  (deploy/Dockerfile)\nPython 3.11, Java 17, Spark 3.5.1\nno torch, no CUDA", "spark", font=11)
    g.box("final", 660, 0, 330, 115, "*multi-model-inference:latest\n--target final (default)  27.7 GB\ntorch 2.6 cu126 + requirements.txt,\nplatform code, torchvision weights", "gpu", font=11)
    g.box("lean", 660, 165, 330, 95, "*spark-lean:latest\n--target lean  2.2 GB\npyspark + requests + platform code\nno torch: talks to a model server", "spark", font=11)
    g.box("worker", 1070, 0, 330, 115, "*ner-translate-worker:latest\ndeploy/Dockerfile.ner_translate  28.1 GB\nFROM multi-model-inference + tesseract\n/poppler (.deb bundle) + NER wheelhouse", "gpu", font=11)
    g.box("py", 0, 335, 220, 60, "*python:3.11-slim-bookworm\n(pulled)", "client", font=11)
    g.box("server", 660, 310, 330, 115, "*ner-translate-server:latest\ndeploy/Dockerfile.ner_translate_server  9.3 GB\ntesseract + torch cu126 + NER wheelhouse,\nno Spark / Java; code + weights mounted", "triton", font=11)
    g.box("inputs", 1070, 180, 330, 110, "*Offline build inputs\nbind-mounted during the build, never an image layer:\nwheels/ner_translate - pip wheelhouse\ndebs/ner_translate - apt .deb bundle", "note", font=11)
    g.container("ext", 0, 470, 1400, 100, "*Pulled, not built")
    g.box("hadoop", 20, 505, 420, 50, "*apache/hadoop:3.4.1  3.3 GB - HDFS namenode / datanode (air-gap simulation)", "storage", font=10)
    g.box("triton", 470, 505, 440, 50, "*nvcr.io/nvidia/tritonserver:<tag> - Triton model server (AWS modes runs)", "triton", font=10)
    g.box("cuda", 940, 505, 440, 50, "*nvidia/cuda:12.6.3-base - only for the nvidia-smi GPU check in setup scripts", "white", font=10)
    g.edge("ubu", "base", "FROM")
    g.edge("base", "final", "target final", exit=(1, 0.3), entry=(0, 0.5))
    g.edge("base", "lean", "target lean", exit=(1, 0.8), entry=(0, 0.5))
    g.edge("final", "worker", "FROM")
    g.edge("py", "server", "FROM", exit=(1, 0.5), entry=(0, 0.5), points=[(440, 365), (440, 367.5)])
    g.edge("inputs", "worker", "", dashed=True, exit=(0.5, 0), entry=(0.5, 1))
    g.edge("inputs", "server", "", dashed=True, exit=(0.5, 1), entry=(1, 0.5), points=[(1235, 367.5)])
    D.append(g)


# ============================================================ 29 three execution architectures
def d_exec_architectures():
    g = Diagram("docker_architectures", "29. Three ways the containers run a model - and which compose files build each",
                "[image] in brackets; host ports as published by the compose files")
    cols = [
        ("A. Shared cluster - models inside the executors",
         ("spark-master  [multi-model-inference]\nmaster :7077, UI :8080, driver UI :4040\nthe driver runs here (docker exec)", "spark"),
         ("spark-gpu-worker / spark-cpu-worker\n[multi-model-inference]\nexecutors + Python workers load the\ntensor models (GPU worker: on the GPU)", "gpu"),
         "docker-compose.laptop.yml / .cluster.yml /\n.cluster.linux.yml; docker run scripts:\nstart_cluster.ps1, setup_*.sh, AWS modes_node.sh\n(+ Triton container for the Triton mode)"),
        ("B. Dedicated pipeline cluster (Option A)",
         ("ner-translate-master  [ner-translate-worker]\nhost ports 7078 / 8081 / 4041\ndriver imports the pipeline", "spark"),
         ("ner-translate-worker  [ner-translate-worker]\nthe executor's Python worker imports the\npipeline and loads GLiNER + NLLB itself", "gpu"),
         "docker-compose.ner_translate.yml\nair-gap simulation, profile cluster\n(sim-ner-cluster-master / -worker, 8084 / 4044)\nwhen executors must own the models"),
        ("C. Waiter / kitchen (Option B)",
         ("ner-translate-master + ner-translate-worker\n[spark-lean - no torch]\nhost ports 7080 / 8083 / 4043", "spark"),
         ("ner-translate-server (kitchen)\n[ner-translate-server]  FastAPI :8000 (host 8001)\nGLiNER + NLLB loaded once on the GPU", "triton"),
         "docker-compose.ner_translate_server.yml\n(start via setup_ner_translate_server.sh)\nair-gap simulation, profile service (sim-*)\nrecommended for GPU pipelines"),
    ]
    for i, (title, top, bottom, note) in enumerate(cols):
        x = i * 470
        g.container(f"c{i}", x, 0, 450, 430, "*" + title)
        g.box(f"t{i}", x + 20, 40, 410, 80, "*" + top[0], top[1], font=11)
        g.box(f"b{i}", x + 20, 175, 410, 95, "*" + bottom[0], bottom[1], font=11)
        g.box(f"n{i}", x + 20, 310, 410, 100, note, "note", font=11)
        g.edge(f"t{i}", f"b{i}", ["tasks (RPC)", "tasks (RPC)", "tasks -> worker -> HTTP POST /predict {paths}"][i])
    g.box("shared", 0, 470, 1390, 60, "*Shared by all of them: bind mounts ../data  ../models  ../results at the same path (/app/...) in every container - "
          "Spark sends file paths, each container opens the files itself.  Air-gap simulation adds HDFS (apache/hadoop) as the model store.", "storage", font=11)
    D.append(g)


# ============================================================ 30 which file to use
def d_compose_decision():
    g = Diagram("docker_decision", "30. Which compose file or script to use",
                "Start from what you want to run; each leaf names the file and why")
    g.box("root", 0, 250, 190, 70, "*What do you\nwant to run?", "client", font=12)
    g.box("tm", 250, 110, 230, 70, "*Tensor models\n(10 built-ins, BYOM plugins)", "gpu", font=11)
    g.box("ner", 250, 420, 230, 70, "*NER pipeline\n(documents -> entities)", "triton", font=11)
    leaves_t = [("one container, no cluster, code mounted", "docker-compose.yml"),
                ("Spark cluster on this laptop (1 GPU)", "docker-compose.laptop.yml"),
                ("several workers, Windows Docker Desktop", "docker-compose.cluster.yml"),
                ("one Linux host / EC2 (host network)", "docker-compose.cluster.linux.yml"),
                ("several machines: LAN lab / AWS", "start_cluster.ps1 / run_aws_*.ps1 (docker run)")]
    leaves_n = [("production shape: one model copy per GPU", "docker-compose.ner_translate_server.yml"),
                ("executors hold the models, no server", "docker-compose.ner_translate.yml"),
                ("models from HDFS / master FS + test suite", "docker-compose.airgap_sim.yml (profiles)")]
    for i, (why, what) in enumerate(leaves_t):
        g.box(f"lt{i}", 560, i * 62, 560, 50, f"{why}\n*-> {what}", "white", font=11)
        g.edge("tm", f"lt{i}", "", exit=(1, 0.5), entry=(0, 0.5), points=[(520, 145), (520, i * 62 + 25)])
    for i, (why, what) in enumerate(leaves_n):
        g.box(f"ln{i}", 560, 360 + i * 62, 560, 50, f"{why}\n*-> {what}", "white", font=11)
        g.edge("ner", f"ln{i}", "", exit=(1, 0.5), entry=(0, 0.5), points=[(520, 455), (520, 360 + i * 62 + 25)])
    g.edge("root", "tm", "", exit=(1, 0.3), entry=(0, 0.5), points=[(220, 271), (220, 145)])
    g.edge("root", "ner", "", exit=(1, 0.7), entry=(0, 0.5), points=[(220, 299), (220, 455)])
    D.append(g)


# ============================================================ 31 who owns models and data (multi-host)
def d_ownership():
    g = Diagram("cluster_ownership", "31. Who owns models and data - recommended air-gapped layout (service mode)",
                "Each box is a machine. The Spark master owns nothing: models live in the model store, documents in the shared folder")
    g.container("st", 0, 0, 330, 470, "*Storage node (10.0.0.5)")
    g.box("hdfs", 20, 40, 290, 110, "*HDFS  (apache/hadoop)\nnamenode :8020 / WebHDFS :9870\ndatanode :9864 / :9866\n/models/weights: gliner, nllb, hf_cache", "storage", font=11)
    g.box("nfs", 20, 200, 290, 110, "*Shared data folder (NFS export)\n/srv/data  ->  mounted as /app/data\ndocuments to process\n(+ backend uploads)", "storage", shape="cyl", font=11)
    g.box("nt1", 20, 350, 290, 100, "OWNS: the model files and the\ndocuments. Nothing else needs a copy\nexcept the node caches.", "note", font=11)
    g.container("mn", 380, 0, 330, 470, "*Master node (10.0.0.10)")
    g.box("sm", 400, 40, 290, 70, "*Spark master :7077  [spark-lean]\nschedules only - owns nothing", "spark", font=11)
    g.box("drv", 400, 150, 290, 110, "*Driver (submit_pipeline_job.py)\nlists /app/data (needs the share)\nwrites results/ner_translate_<ts>.json", "driver", font=11)
    g.box("res", 400, 300, 290, 60, "*results/ (local or on the share)", "storage", shape="cyl", font=11)
    g.box("nt2", 400, 380, 290, 70, "NEEDS: the data share (to list files).\nNo models.", "note", font=11)
    g.container("gn", 760, 0, 330, 470, "*GPU node (10.0.0.12)")
    g.box("kit", 780, 40, 290, 110, "*Model server (kitchen)\n[ner-translate-server]  :8000\nopens the documents, runs OCR,\nNLLB + GLiNER on the GPU", "triton", font=11)
    g.box("kc", 780, 200, 290, 60, "*/model_cache (local disk)", "storage", shape="cyl", font=11)
    g.box("nt3", 780, 300, 290, 150, "NEEDS: the data share (same path),\nWebHDFS access to the storage node\n(first load), a GPU, >= 5 GB local disk.\nOWNS: the only loaded copy of the\nmodels.", "note", font=11)
    g.container("wn", 1140, 0, 300, 470, "*Worker node(s) (10.0.0.11, ...)")
    g.box("wk", 1160, 40, 260, 110, "*Spark worker  [spark-lean]\nexecutors send file NAMES to\nthe kitchen (HTTP)", "spark", font=11)
    g.box("nt4", 1160, 200, 260, 250, "NEEDS in service mode: nothing but\nnetwork - no data share, no models,\nno GPU.\n\nIn cluster mode it needs what the\nGPU node needs: the data share,\nWebHDFS access, a GPU, a local\nmodel cache.", "note", font=11)
    g.edge("hdfs", "kc", "WebHDFS, first load only", exit=(1, 0.3), entry=(0, 0.5), points=[(345, 73), (345, -25), (740, -25), (740, 230)], label_seg=2)
    g.edge("kc", "kit", "load", exit=(0.5, 0), entry=(0.5, 1))
    g.edge("nfs", "drv", "NFS: list files", exit=(1, 0.3), entry=(0, 0.5))
    g.edge("nfs", "kit", "NFS: read files", dashed=True, exit=(1, 0.9), entry=(0, 0.8), points=[(345, 299), (345, 370), (750, 370), (750, 128)], label_seg=2)
    g.edge("drv", "res", "", exit=(0.5, 1), entry=(0.5, 0))
    g.edge("sm", "wk", "tasks", exit=(1, 0.3), entry=(0, 0.2), points=[(725, 61), (725, -50), (1125, -50), (1125, 62)], label_seg=2)
    g.edge("wk", "kit", "POST /predict {paths}", exit=(0.5, 1), entry=(1, 0.8), points=[(1290, 175), (1110, 175), (1110, 128)], label_seg=1)
    D.append(g)


for fn in (d_rdd, d_udf, d_native, d_gpu_aware, d_triton_mode, d_recommended, d_alt_sidecar, d_alt_inprocess, d_alt_ray,
           d_alt_k8s, d_alt_queue, d_aws, d_airgapped, d_sequence,
           d_module_map, d_seq_submit, d_seq_pipeline, d_plugin_flow, d_observability,
           d_airgap_sim, d_model_fetch, d_ner_pipeline, d_lifecycle, d_data_paths, d_spark_sequence, d_tensor_path,
           d_image_tree, d_exec_architectures, d_compose_decision, d_ownership):
    fn()

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(out, "png"), exist_ok=True)
    for dg in D:
        dg.render_png(os.path.join(out, "png", f"{dg.key}.png"))
    write_drawio(D, os.path.join(out, "spark_inference_architectures.drawio"))
    print(f"{len(D)} diagrams ->", out)
