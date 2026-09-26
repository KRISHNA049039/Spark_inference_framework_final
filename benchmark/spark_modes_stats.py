"""
spark_modes_stats.py - Run every inference execution mode of the platform on a
real multi-worker Spark cluster, one Spark application per mode, and record
what's needed for worker / executor / job / stage / task level statistics.

Modes (each is its own Spark application, so its event log, executors and
tasks are cleanly separated):

  rdd_cpu / rdd_gpu / rdd_hybrid   inference/cluster_engine.py  (mapPartitions,
                                   model weights broadcast, counts returned)
  rdd_gpu_aware                    same, with Spark GPU-aware scheduling
                                   (spark.executor.resource.gpu.amount=1) so
                                   executors only start on GPU workers
  udf_cpu / udf_gpu                inference/cluster_engine_udf.py (the repo's
                                   own predict_batch_udf: scalar-iterator
                                   pandas UDF, model loaded once per task)
  native_pbu_cpu / native_pbu_gpu  Spark's built-in
                                   pyspark.ml.functions.predict_batch_udf
                                   (model cached per Python worker process)
  triton_pbu                       built-in predict_batch_udf whose predict
                                   function calls Triton Inference Server over
                                   gRPC (executors do no model work at all)
  platform10_{cpu,gpu,hybrid}      the platform's full 10-model workload
                                   through cluster_engine (as cluster_benchmark)

  python benchmark/spark_modes_stats.py --master spark://10.0.0.5:7077 \
      --triton 10.0.0.6 --out results/modes_20260926/aws_2node

Writes <out>/results.jsonl (one JSON per mode), <out>/logs/<app>.log,
<out>/triton_metrics/<app>_{before,after}.txt, and Spark event logs to
<out>/spark-events/. benchmark/analyze_modes_stats.py turns those into
per-worker / per-task statistics.
"""
import argparse
import io
import json
import os
import subprocess
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

MODELS = {
    # model -> (dataset key in generate_mixed_data, samples, batch size, Triton max_batch_size)
    "ew_classifier": ("ew_classifier", 100_000, 1024, 4096),
    "resnet18": ("resnet18", 256, 64, 256),
}
PER_MODEL_MODES = ["rdd_cpu", "rdd_gpu", "rdd_hybrid", "udf_cpu", "udf_gpu",
                   "native_pbu_cpu", "native_pbu_gpu", "triton_pbu", "rdd_gpu_aware"]
PLATFORM_MODES = ["platform10_cpu", "platform10_gpu", "platform10_hybrid"]


# ----------------------------------------------------------------- helpers
def triton_metrics(host):
    try:
        return urllib.request.urlopen(f"http://{host}:8002/metrics", timeout=5).read().decode()
    except Exception as e:
        return f"# unavailable: {e}\n"


def build_input_df(spark, arr, partitions):
    """Same construction as cluster_engine_udf.py: flat float arrays with an
    explicit schema, then repartition (so every UDF mode ingests identically)."""
    from pyspark.sql import Row
    from pyspark.sql.types import StructType, StructField, ArrayType, FloatType
    rows = [Row(input=r.reshape(-1).tolist()) for r in arr]
    schema = StructType([StructField("input", ArrayType(FloatType()), False)])
    return spark.createDataFrame(rows, schema=schema).repartition(partitions)


def native_pbu(spark, model_name, model, arr, partitions, bs, device, app):
    """Spark's built-in predict_batch_udf with a local PyTorch model."""
    from pyspark.ml.functions import predict_batch_udf
    from pyspark.sql.types import ArrayType, FloatType
    from inference.cluster_engine import _serialize_model, _get_class_map
    bc = spark.sparkContext.broadcast(_serialize_model(model))
    cls = _get_class_map()[model_name]
    shape = list(arr.shape[1:])

    def make_predict_fn():
        import io as _io, os as _os, socket as _s, sys as _sys, time as _t
        import torch
        t0 = _t.time()
        m = cls()
        m.load_state_dict(torch.load(_io.BytesIO(bc.value), map_location="cpu", weights_only=True))
        dev = "cuda" if (device == "cuda" and torch.cuda.is_available()) else "cpu"
        m = m.to(dev).eval()
        print(f"[MODEL_LOAD] app={app} host={_s.gethostname()} pid={_os.getpid()} device={dev} "
              f"secs={_t.time() - t0:.3f}", file=_sys.stderr, flush=True)

        def predict(inputs):
            with torch.no_grad():
                return m(torch.from_numpy(inputs).to(dev)).cpu().numpy()
        return predict

    udf = predict_batch_udf(make_predict_fn, return_type=ArrayType(FloatType()), batch_size=bs,
                            input_tensor_shapes=[shape])
    df = build_input_df(spark, arr, partitions)
    out = df.select(udf("input").alias("p")).collect()
    return sum(1 for r in out if r.p is not None)


def triton_pbu(spark, model_name, arr, partitions, bs, triton_host, app):
    """Built-in predict_batch_udf whose predict fn is a Triton gRPC client."""
    from pyspark.ml.functions import predict_batch_udf
    from pyspark.sql.types import ArrayType, FloatType
    shape = list(arr.shape[1:])
    url = f"{triton_host}:8001"

    def make_predict_fn():
        import os as _os, socket as _s, sys as _sys, time as _t
        import tritonclient.grpc as grpcclient
        t0 = _t.time()
        client = grpcclient.InferenceServerClient(url=url)
        print(f"[MODEL_LOAD] app={app} host={_s.gethostname()} pid={_os.getpid()} device=triton "
              f"secs={_t.time() - t0:.3f}", file=_sys.stderr, flush=True)

        def predict(inputs):
            inp = grpcclient.InferInput("INPUT__0", list(inputs.shape), "FP32")
            inp.set_data_from_numpy(inputs.astype("float32"))
            res = client.infer(model_name, [inp], outputs=[grpcclient.InferRequestedOutput("OUTPUT__0")])
            return res.as_numpy("OUTPUT__0")
        return predict

    udf = predict_batch_udf(make_predict_fn, return_type=ArrayType(FloatType()), batch_size=bs,
                            input_tensor_shapes=[shape])
    df = build_input_df(spark, arr, partitions)
    out = df.select(udf("input").alias("p")).collect()
    return sum(1 for r in out if r.p is not None)


# ----------------------------------------------------------------- one mode
def run_one(args):
    import numpy as np  # noqa: F401
    from models import get_default_registry
    from data.image_generator import generate_mixed_data
    from inference.cluster_engine import create_cluster_session, run_cluster_inference
    from inference.cluster_engine_udf import run_cluster_inference_udf

    mode, model_name = args.mode, args.model
    app = f"modes-{model_name}-{mode}"
    reg = get_default_registry()
    t_setup = time.time()

    if mode.startswith("platform10"):
        data = generate_mixed_data(3000, 100, 30)
        models = {n: reg.load_model(n, device="cpu") for n in data}
        bs, n_total = 256, sum(len(a) for a in data.values())
    else:
        key, n, bs, _ = MODELS[model_name]
        n = max(4, int(n * args.scale))
        if model_name == "resnet18":
            data = generate_mixed_data(1, n, 1)
        else:
            data = generate_mixed_data(n, 1, 1)
        arr = data[key][:n]
        models = {model_name: reg.load_model(model_name, device="cpu")}
        n_total = len(arr)
    setup_s = time.time() - t_setup

    spark = create_cluster_session(app_name=app, master_url=args.master,
                                   gpu_aware_scheduling=(mode == "rdd_gpu_aware"))
    sc = spark.sparkContext
    rec = {"app": app, "app_id": sc.applicationId, "mode": mode, "model": model_name,
           "partitions": args.partitions, "batch_size": bs, "samples": n_total, "setup_s": round(setup_s, 2),
           "start_epoch": time.time()}
    if mode == "triton_pbu":
        rec["triton_before"] = f"triton_metrics/{app}_before.txt"
        open(os.path.join(args.out, rec["triton_before"]), "w").write(triton_metrics(args.triton))

    t0 = time.time()
    extra = {}
    if mode.startswith("platform10"):
        dm = {"platform10_cpu": "cpu_only", "platform10_gpu": "gpu_only", "platform10_hybrid": "hybrid"}[mode]
        r = run_cluster_inference(spark, data, models, args.partitions, bs, dm)
        processed = r["total_samples_processed"]
        extra["partition_details"] = r["partition_details"]
    elif mode.startswith("rdd"):
        dm = {"rdd_cpu": "cpu_only", "rdd_gpu": "gpu_only", "rdd_hybrid": "hybrid", "rdd_gpu_aware": "gpu_only"}[mode]
        r = run_cluster_inference(spark, {model_name: arr}, models, args.partitions, bs, dm)
        processed = r["total_samples_processed"]
        extra["partition_details"] = r["partition_details"]
    elif mode.startswith("udf"):
        dm = "cpu_only" if mode == "udf_cpu" else "gpu_only"
        r = run_cluster_inference_udf(spark, {model_name: arr}, models, args.partitions, bs, dm)
        processed = r["total_samples_processed"]
    elif mode.startswith("native_pbu"):
        processed = native_pbu(spark, model_name, models[model_name], arr, args.partitions, bs,
                               "cpu" if mode.endswith("cpu") else "cuda", app)
    elif mode == "triton_pbu":
        processed = triton_pbu(spark, model_name, arr, args.partitions, bs, args.triton, app)
    else:
        raise SystemExit(f"unknown mode {mode}")
    wall = time.time() - t0

    rec.update({"wall_s": round(wall, 3), "processed": processed,
                "throughput": round(processed / wall, 1) if wall else 0, "end_epoch": time.time(), **extra})
    if mode == "triton_pbu":
        rec["triton_after"] = f"triton_metrics/{app}_after.txt"
        open(os.path.join(args.out, rec["triton_after"]), "w").write(triton_metrics(args.triton))
    spark.stop()
    print("RESULT_JSON " + json.dumps(rec, default=str), flush=True)


# ----------------------------------------------------------------- orchestrator
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--master", required=True)
    ap.add_argument("--triton", default="", help="Triton host (gRPC 8001, metrics 8002)")
    ap.add_argument("--out", default="results/modes_20260926/aws_2node")
    ap.add_argument("--partitions", type=int, default=8)
    ap.add_argument("--models", default="ew_classifier,resnet18")
    ap.add_argument("--modes", default=",".join(PER_MODEL_MODES + PLATFORM_MODES))
    ap.add_argument("--run-one", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--mode", help=argparse.SUPPRESS)
    ap.add_argument("--model", help=argparse.SUPPRESS)
    ap.add_argument("--timeout", type=int, default=1200)
    ap.add_argument("--scale", type=float, default=1.0, help="multiply sample counts (dry runs)")
    args = ap.parse_args()
    for d in ("logs", "triton_metrics", "spark-events"):
        os.makedirs(os.path.join(args.out, d), exist_ok=True)
    if args.run_one:
        return run_one(args)

    ev = os.path.abspath(os.path.join(args.out, "spark-events"))
    env = dict(os.environ, PYTHONIOENCODING="utf-8",
               PYSPARK_SUBMIT_ARGS=f"--conf spark.eventLog.enabled=true --conf spark.eventLog.dir=file://{ev} pyspark-shell")
    modes = args.modes.split(",")
    plan = [(m, md) for m in args.models.split(",") for md in modes if md in PER_MODEL_MODES]
    plan += [("platform10", md) for md in modes if md in PLATFORM_MODES]
    if not args.triton:
        plan = [p for p in plan if p[1] != "triton_pbu"]
    out_jsonl = os.path.join(args.out, "results.jsonl")
    for model_name, mode in plan:
        app = f"modes-{model_name}-{mode}"
        print(f">>> {app}", flush=True)
        cmd = [sys.executable, os.path.abspath(__file__), "--run-one", "--master", args.master, "--triton", args.triton,
               "--out", args.out, "--partitions", str(args.partitions), "--mode", mode, "--model", model_name,
               "--scale", str(args.scale)]
        t0 = time.time()
        with open(os.path.join(args.out, "logs", f"{app}.log"), "w") as lf:
            try:
                p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
                                   timeout=args.timeout, cwd=REPO)
                lf.write(p.stdout)
                line = next((l for l in p.stdout.splitlines() if l.startswith("RESULT_JSON ")), None)
                rec = json.loads(line[12:]) if line else {"app": app, "mode": mode, "model": model_name,
                                                          "error": f"exit {p.returncode}"}
            except subprocess.TimeoutExpired as e:
                lf.write((e.stdout or "") if isinstance(e.stdout, str) else "")
                rec = {"app": app, "mode": mode, "model": model_name, "error": "timeout"}
        rec["subprocess_s"] = round(time.time() - t0, 1)
        with open(out_jsonl, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        print(f"    {rec.get('throughput', rec.get('error'))} samples/s  wall={rec.get('wall_s')}s", flush=True)
        time.sleep(3)


if __name__ == "__main__":
    main()
