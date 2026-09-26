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


for fn in (d_rdd, d_udf, d_native, d_gpu_aware, d_triton_mode, d_recommended, d_alt_sidecar, d_alt_inprocess, d_alt_ray,
           d_alt_k8s, d_alt_queue, d_aws, d_airgapped, d_sequence,
           d_module_map, d_seq_submit, d_seq_pipeline, d_plugin_flow, d_observability):
    fn()

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
    os.makedirs(os.path.join(out, "png"), exist_ok=True)
    for dg in D:
        dg.render_png(os.path.join(out, "png", f"{dg.key}.png"))
    write_drawio(D, os.path.join(out, "spark_inference_architectures.drawio"))
    print(f"{len(D)} diagrams ->", out)
