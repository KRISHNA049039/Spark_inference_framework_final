"""
build_ner_internals_pdf.py - docs/NER_SPARK_DATA_PATHS_AND_EXECUTION.pdf

Every data movement path of the NER pipeline on Spark and how Spark executes it,
process by process, with the numbers of one traced run (docs/ner_internals/run_trace.sh
-> results/ner_trace_<ts>/).

    python docs/ner_internals/build_ner_internals_pdf.py [results/ner_trace_<ts>]
"""
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "docs", "runbook"))

from reportlab.platypus import Spacer  # noqa: E402

import charts  # noqa: E402
import trace_data  # noqa: E402
from build_ner_runbook_pdfs import BODY, S as STY, Doc  # noqa: E402

STY["note"].spaceBefore = STY["warn"].spaceBefore = 12
STY["h1"].keepWithNext = 1

TR = trace_data.load(sys.argv[1] if len(sys.argv) > 1 else trace_data.latest_trace(REPO))
OUT = os.path.join(REPO, "docs", "NER_SPARK_DATA_PATHS_AND_EXECUTION.pdf")
PF = TR["profile"] or {}
_p1 = os.path.join(TR["dir"], "stage_profile_run1.json")
PF1 = __import__("json").load(open(_p1, encoding="utf-8")) if os.path.exists(_p1) else None


# ------------------------------------------------------------------ formatting helpers
def kb(n):
    n = float(n)
    for u, d in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if n >= d:
            return f"{n / d:,.1f} {u}"
    return f"{n:,.0f} B"


def s(x, nd=1):
    return f"{x:,.{nd}f} s"


def hm(t):
    return time.strftime("%H:%M:%S", time.gmtime(t)) + f".{int((t % 1) * 1000):03d}"


def ev(mode, what):
    return [e for e in TR[mode]["exe"]["events"] if e["what"] == what]


def first(lst, default=None):
    return lst[0] if lst else default


def drv_info(mode, pat):
    for l in TR[mode]["driver"]["info"]:
        m = re.search(pat, l)
        if m:
            return l[:17], m
    return None, None


def mid_sample(rows, t):
    return min(rows, key=lambda r: abs(r["t"] - t)) if rows else None


def short_cmd(cmd):
    """java command lines -> 'java -Xmx.. <main class> <args>' (drops class path, -D / -XX / --add-opens flags)."""
    cmd = cmd.replace("/usr/lib/jvm/java-17-openjdk-amd64/bin/java", "java")
    cmd = re.sub(r"-cp \S+ ", "", cmd)
    cmd = re.sub(r" --add-opens[= ]\S+", "", cmd)
    cmd = re.sub(r" -(D|XX)\S+", "", cmd)
    return cmd


def tree_rows(sample, ips):
    rows = [["pid", "ppid", "RSS", "thr", "socks", "process (command line, shortened)"]]
    if not sample:
        return rows
    procs = sample["procs"]
    for depth, pid, p in trace_data.proc_tree(sample, keep=lambda p: "probe.py" not in p["cmd"]):
        cmd = short_cmd(p["cmd"])
        parent = procs.get(str(p["ppid"]), {}).get("cmd", "")
        if cmd.startswith("java") and "org.apache" not in cmd:  # probe keeps 600 chars; --add-opens flags use them up
            if "submit_pipeline_job" in parent:
                cmd += " ... org.apache.spark.deploy.SparkSubmit ... pyspark-shell   <- driver JVM"
            elif "deploy.worker.Worker" in parent:
                cmd += " ... org.apache.spark.executor.CoarseGrainedExecutorBackend   <- executor JVM"
        if "pyspark.daemon" in cmd and "pyspark.daemon" in parent:
            cmd += "   <- forked Python worker (runs a task)"
        rows.append([str(pid), str(p["ppid"]), f"{p['rss_kb'] / 1024:,.0f} MB", str(p["threads"]), str(p["socks"]),
                     "`" + ("  " * depth + cmd)[:170] + "`"])
    return rows


def exe_command(raw):
    """Executor log 'Spark Executor Command' -> one flag / argument pair per line."""
    toks = re.findall(r'"([^"]*)"', raw)
    out, i = [], 0
    while i < len(toks):
        t = toks[i]
        if t == "-cp":
            out.append(f"  -cp {toks[i + 1]}")
            i += 2
            continue
        if t.startswith("--add-opens"):
            i += 1
            continue
        if t.startswith("--") and i + 1 < len(toks):
            out.append(f"  {t} {toks[i + 1]}")
            i += 2
            continue
        out.append(("  " if out else "") + t)
        i += 1
    n_open = sum(1 for t in toks if t.startswith("--add-opens"))
    return "\n".join(out) + (f"\n  ({n_open} --add-opens flags for Java 17 omitted)" if n_open else "")


def conn_rows(sample, ips, names):
    out = [["state", "local", "remote", "owner pid(s)", "what it is"]]
    if not sample:
        return out
    ip2 = {v.split("/")[0]: k.replace("sim-", "") for k, v in ips.items()}

    def lab(a):
        ip, port = a.rsplit(":", 1)
        return f"{ip2.get(ip, ip)}:{port}"
    seen = set()
    for c in sample["conns"]:
        if c["state"] not in ("ESTABLISHED", "LISTEN") or c["local"].startswith("127.0.0.11"):
            continue
        key = (c["state"], c["local"], c["remote"])
        if key in seen:
            continue
        seen.add(key)
        pids = ",".join(sorted({str(p) for p in c["pids"]}))
        port_l, port_r = c["local"].rsplit(":", 1)[1], c["remote"].rsplit(":", 1)[1]
        what = names(c, port_l, port_r)
        out.append([c["state"], lab(c["local"]), lab(c["remote"]) if c["state"] != "LISTEN" else "-", pids, what])
    return out


# ------------------------------------------------------------------ document
d = Doc()
A_S, A_C = TR["apps"].get("service", {}), TR["apps"].get("cluster", {})
S_ = TR["svc"]
C_ = TR["clu"]
ips_s, ips_c = S_["network"], C_["network"]
d.story.append(Spacer(1, 26))
d.P("NER on Spark: Data Paths and Execution Internals", "title")
d.P("Where every byte comes from and goes to, and exactly how Spark runs the NER pipeline - driver, scheduler, executor, "
    "Python worker, model server and GPU - traced on the air-gapped simulation in service mode and in cluster mode.", "sub")
d.note(f"Traced run: `{TR['name']}` (docs/ner_internals/run_trace.sh). Inputs: the 6 documents in data/ner_samples. Models: warm node caches of "
       "the HDFS model store. Evidence used: Spark event logs, executor logs, driver logs, model-server log, a /proc probe in every "
       "container (processes, sockets, network counters, 1-2 samples/s), nvidia-smi samples (2/s) and a stage profile of the NER code "
       "on the GPU. Machine: laptop, Intel i5-9300H, 6 GB for Docker/WSL2, NVIDIA GTX 1650 4 GB, PCIe Gen3 x16.")
d.P("**Contents**", "h3")
for i, t in enumerate(["The short answer - ten data paths", "Where the data comes from", "Driver side: from the command line to a Spark job",
                       "Worker side: executor JVM and Python worker", "Inside the model process: NER step by step on the GPU",
                       "Service mode end to end - measured timeline", "Cluster mode end to end - measured timeline",
                       "Service mode vs cluster mode", "Nitty-gritty findings", "Reproduce"], 1):
    d.P(f"{i}. {t}", "small")
d.brk()

# ================================================================== 1
d.H("1. The short answer - ten data paths")
d.P("Three kinds of data move: **models** (large, move once per node), **document names** (tiny, move through Spark) and "
    "**document contents and results** (read and produced where the model runs). Spark itself never carries a document: it "
    "carries file names to the process that holds the models, and carries the result dictionaries back.")
d.img("ner_data_paths", "Figure 1 - every data path; the numbers match the table below", maxh=118)
svc_tasks = A_S.get("tasks", [])
res_bytes = " + ".join(f"{t['result_bytes']:,} B" for t in svc_tasks)
pb = TR["predict"]
body = pb[1] if len(pb) > 1 else (pb[0] if pb else None)
nd = sum(os.path.getsize(os.path.join(REPO, "data", "ner_samples", f)) for f in os.listdir(os.path.join(REPO, "data", "ner_samples")))
L = PF.get("load", {})
g_disk = L.get("gliner_dir", {}).get("bytes", 0)
n_disk = L.get("nllb_dir", {}).get("bytes", 0)
bc = {e["groups"][0]: e["groups"][1] for e in ev("svc", "bc_piece")}
tb_id = first([e["groups"][0] for e in ev("svc", "bc_start")], "?")
evsize = sum(os.path.getsize(os.path.join(TR["dir"], "eventlog", f)) for f in os.listdir(os.path.join(TR["dir"], "eventlog")))
res_file = S_["driver"]["results_file"]
res_size = os.path.getsize(os.path.join(REPO, res_file)) if res_file and os.path.exists(os.path.join(REPO, res_file)) else 0
d.table([["#", "what moves", "from -> to", "transport and format", "size (measured)", "when"],
         ["1", "model folders", "HDFS datanode -> node cache (/model_cache)", "WebHDFS HTTP: namenode 307 redirect, datanode streams 8 MB chunks; .partial dir -> rename",
          f"{kb(g_disk + n_disk)} (gliner {kb(g_disk)}, nllb {kb(n_disk)})", "first load on a node only"],
         ["2", "model weights", "node cache -> CPU RAM -> GPU VRAM", "from_pretrained reads the files; .to('cuda') copies every tensor over PCIe",
          f"GLiNER {kb(L.get('gliner_fp32', {}).get('bytes', 0))} fp32 -> {kb(L.get('gliner_fp16', {}).get('bytes', 0))} fp16; NLLB {kb(L.get('nllb', {}).get('bytes', 0))}",
          "every model load: kitchen start; every task in cluster mode"],
         ["3", "file names", "shared data volume -> driver", "directory listing (glob), then os.path.abspath", "6 names", "each submit"],
         ["4", "names + code", "driver Python -> driver JVM", "Py4J commands over localhost TCP; path batches pickled to a temp file; closure pickled (cloudpickle)",
          "2 batches of 3 paths; closure in the task binary", "each job"],
         ["5", "tasks", "driver JVM -> executor JVM", "Netty RPC LaunchTask; task binary and settings as TorrentBroadcast blocks fetched from the driver's BlockManager",
          f"task binary {bc.get(tb_id, '?')} + 3 settings broadcasts of {', '.join(v for k, v in bc.items() if k != tb_id)}", "each task"],
         ["6", "names in, results out", "executor JVM <-> Python worker", "localhost TCP to pyspark.daemon (forked worker); length-prefixed pickle frames",
          "in: header + closure + 3 paths; out: one result dict", "each task"],
         ["7", "HTTP request / response", "Python worker <-> kitchen (service mode)", "HTTP/1.1 POST /predict, JSON",
          f"request {body['req_body']} B body, response {kb(body['resp_body'])}" if body else "-", "each task"],
         ["8", "document contents", "shared volume -> model process", "open()/read in the kitchen (service) or the Python worker (cluster); OCR via a tesseract subprocess",
          f"{kb(nd)} for all 6 files", "each document"],
         ["9", "results", "Python worker -> executor -> driver JVM -> driver Python -> JSON file", "pickle frame; DirectTaskResult in a StatusUpdate RPC; local socket (collectAndServe); json.dump",
          f"task results {res_bytes}; file {kb(res_size)}", "each task / job"],
         ["10", "control", "driver, master, worker, executor", "RPC: RegisterApplication, LaunchExecutor, RegisterExecutor, heartbeats; event log file",
          f"event log {kb(evsize)} for both jobs", "continuous"]],
        [6, 22, 32, 52, 36, 26])
if S_["probes"].get("spark-worker"):
    rx_m, tx_m = trace_data.net_delta(S_["probes"]["spark-master"])
    rx_w, tx_w = trace_data.net_delta(S_["probes"]["spark-worker"])
    win = S_["probes"]["spark-worker"][-1]["t"] - S_["probes"]["spark-worker"][0]["t"]
    d.note(f"Network bytes between the containers during the service-mode job (eth0 counters over the probes' {win:.0f}-s window, which "
           f"covers all but the last {S_['end'] - S_['probes']['spark-worker'][-1]['t']:.0f} s of the job): master node received {kb(rx_m)} / sent "
           f"{kb(tx_m)}; worker node received {kb(rx_w)} / sent {kb(tx_w)}. The models did not move at all - they were already in the node "
           "caches (path 1 happened on an earlier run) and on the GPU (path 2 at model-server start).")

# ================================================================== 2
d.H("2. Where the data comes from")
d.H("2.1 The documents", 2)
d.P("The six test documents live in the repository (`data/ner_samples/`, tracked in git). Docker mounts the repository's `data` folder into "
    "every container at `/app/data`; on a real cluster this is a shared file system (NFS or similar) mounted at the same path on every node. "
    "Only the path string travels through Spark; the process that runs the models opens the file itself.")
rows = [["file", "bytes", "how text is obtained", "time", "characters", "language", "route", "chunks"]]
for name, x in (PF.get("docs") or {}).items():
    rows.append([name, f"{x['bytes']:,}", x["extractor"] + (f" ({x['image']})" if x.get("image") else ""), s(x["extract_s"], 3),
                 f"{x['chars']:,}", x["lang"], x["route"] + (f" ({x['nllb_src']})" if x.get("nllb_src") else ""), str(x["chunks"])])
d.table(rows, [30, 13, 44, 16, 17, 15, 26, 13])
d.P(f"OCR languages actually used (packs installed in the image): `{PF.get('ocr_langs', '')}`. "
    "Language id: py3langid on the first 1,000 characters; en/fr/de/es/it/pt go straight to GLiNER, languages with an NLLB code are "
    "translated to English first.", "small")
d.H("2.2 The models", 2)
rows = [["model", "on disk (node cache)", "files over 1 MB", "params", "in GPU memory", "used for"]]
if L:
    gd, ndr = L["gliner_dir"], L["nllb_dir"]
    rows.append(["gliner-multi (urchade/gliner_multi-v2.1)", kb(gd["bytes"]), ", ".join(f"{os.path.basename(f)} {kb(b)}" for f, b in gd["big_files"][:3]),
                 f"{L['gliner_fp32']['params'] / 1e6:,.0f} M", f"{kb(L['gliner_fp16']['bytes'])} fp16", "entity extraction (all documents)"])
    rows.append(["nllb-200-distilled-600M (facebook)", kb(ndr["bytes"]), ", ".join(f"{os.path.basename(f)} {kb(b)}" for f, b in ndr["big_files"][:3]),
                 f"{L['nllb']['params'] / 1e6:,.0f} M", f"{kb(L['nllb']['bytes'])} fp32", "translation to English (non-Latin-script documents)"])
    rows.append(["hf_cache (microsoft/mdeberta-v3-base)", "4 MB", "spm.model", "-", "-", "GLiNER backbone config + tokenizer"])
d.table(rows, [40, 20, 44, 16, 22, 32])
d.P("gliner-multi holds the same weights twice: GLiNER 0.2.13 loads model.safetensors and falls back to pytorch_model.bin only when it is "
    "missing, so the .bin (1.2 GB) is copied into HDFS and into every node cache but never read - it can be dropped from the model store.", "small")
d.H("2.3 Settings", 2)
st = PF.get("settings", {})
d.P(f"Labels (19), threshold and batch sizes are constants in `mt_ner_all_formats.py`, so they reach the model process as code, not as data: "
    f"MAX_CHARS {st.get('MAX_CHARS')}, GLiNER batch {st.get('BATCH_SIZE')}, NLLB batch {st.get('TRANSLATE_BATCH_SIZE')} / max {st.get('TRANSLATE_MAX_TOKENS')} tokens, "
    f"score threshold {st.get('SCORE_THRESHOLD')}, GLiNER in fp16 on the GPU: {st.get('USE_FP16')}. In service mode the executor also broadcasts the service URL, the "
    "label override (None = defaults) and the HTTP timeout - the three small broadcasts of path 5.")
d.brk()

# ================================================================== 3
d.H("3. Driver side: from the command line to a Spark job")
d.H("3.1 What submit_pipeline_job.py does before Spark exists", 2)
d.B(["Reads `models/pipelines/manifest.json` -> module `models.pipelines.ner_translate.pipeline`, `service_url` http://ner-translate-server:8000.",
     "`_collect_files('data/ner_samples')`: recursive glob, sorted, files only -> 6 names; then `os.path.abspath` -> `/app/data/ner_samples/...` "
     "(executors resolve paths from their own working directory, so relative names would break in cluster mode).",
     "Master: `--master` > SPARK_MASTER_URL > manifest master_url (if it resolves) > local[4]. Execution mode: `--execution-mode service|cluster|auto`.",
     "`create_cluster_session()` builds the SparkSession (settings below), then sets the log level to ERROR - which is why the scheduler's "
     "own INFO lines are missing from the driver log and this document reads them from the event log instead."], numbered=True)
props = A_S.get("props", {})
keys = ["spark.master", "spark.app.name", "spark.submit.deployMode", "spark.driver.memory", "spark.executor.memory", "spark.executor.cores", "spark.task.cpus",
        "spark.python.worker.reuse", "spark.python.worker.memory", "spark.rpc.message.maxSize", "spark.driver.maxResultSize", "spark.network.timeout",
        "spark.executor.heartbeatInterval", "spark.driver.host", "spark.driver.port", "spark.executorEnv.PYTHONPATH", "spark.eventLog.enabled"]
meaning = {"spark.task.cpus": "cores reserved per task -> 4 / 2 = 2 task slots per executor", "spark.python.worker.reuse": "keep the forked Python worker for the next task",
           "spark.rpc.message.maxSize": "MB; results above it would go through the BlockManager", "spark.driver.maxResultSize": "sum of all task results collect() may return",
           "spark.network.timeout": "long, because model loads can block a task for minutes", "spark.executor.heartbeatInterval": "executor -> driver liveness + metrics",
           "spark.executor.cores": "cores the executor offers", "spark.driver.port": "driver RPC endpoint (random, from the log)",
           "spark.submit.deployMode": "driver runs inside the submitting process", "spark.executorEnv.PYTHONPATH": "where the Python worker imports inference/ and models/ from"}
d.table([["setting", "value in this run", "what it does here"]] + [[k, props.get(k, "-"), meaning.get(k, "")] for k in keys if k in props],
        [52, 58, 64], mono=(0, 1))

d.H("3.2 Python starts a JVM and talks to it (Py4J)", 2)
d.P("`SparkSession.builder.getOrCreate()` runs `spark-submit pyspark-shell` as a child process: a JVM (SparkSubmit) that hosts the real "
    "SparkContext. Python and that JVM talk over **Py4J**: every `sc.parallelize`, `rdd.mapPartitions`, `collect` in Python is a remote call "
    "over a localhost TCP socket with an auth token. The processes and sockets on the master node while the job ran:")
t_mid = S_["start"] + 60
sm = mid_sample(S_["probes"].get("spark-master"), t_mid)
d.table(tree_rows(sm, ips_s), [10, 10, 14, 9, 10, 121], mono=(5,))


def names_master(c, pl, pr):
    m = {"7077": "Spark master RPC", "8080": "master web UI", "4040": "driver web UI (SparkUI)"}
    drv_port = props.get("spark.driver.port", "")
    bm = re.search(r"Server created on \S+:(\d+)", "\n".join(S_["driver"]["info"]))
    bm = bm.group(1) if bm else ""
    if c["state"] == "LISTEN":
        if pl == drv_port:
            return "driver RPC endpoint (sparkDriver) - executors connect here"
        if pl == bm:
            return "driver BlockManager (broadcast / task-binary blocks)"
        if c["local"].startswith("127.0.0.1"):
            return "Py4J gateway (JVM side)" if any("java" in (sm["procs"].get(str(p), {}).get("cmd", "")) for p in c["pids"]) else "accumulator update server (Python side)"
        return m.get(pl, "")
    if pr == drv_port or pl == drv_port:
        return "executor <-> driver RPC (tasks, status updates)"
    if pr == bm or pl == bm:
        return "executor fetching broadcast blocks"
    if pr == "7077" or pl == "7077":
        return "application / worker <-> master"
    if c["local"].startswith("127.0.0.1"):
        return "Py4J call channel (Python <-> JVM)"
    return m.get(pl, "")


d.table(conn_rows(sm, ips_s, names_master), [22, 44, 44, 18, 46], mono=(1, 2))
lines = [
    ("SparkContext: Submitted application", "application submitted"), ("'sparkDriver' on port (\\d+)", "driver RPC endpoint up"),
    ("MemoryStore started with capacity ([\\d.]+ MiB)", "driver MemoryStore"), ("Start Jetty .* for SparkUI|'SparkUI' on port", "Spark UI :4040"),
    ("Successfully created connection to ner-\\S+/\\S+:7077 after (\\d+) ms", "TCP connection to the master"),
    ("Connected to Spark cluster with app ID (\\S+)", "master accepted the application"),
    ("Executor added: \\S+ on (\\S+)", "master placed an executor on the worker"),
    ("Granted executor ID \\S+ on hostPort \\S+ with (.+)", "executor granted"),
    ("Logging events to", "event log opened"), ("is now RUNNING", "executor JVM running on the worker")]
rows = [["UTC time", "driver log", "meaning"]]
for pat, mean in lines:
    t, m = drv_info("svc", pat)
    if t:
        rows.append([t[9:], m.group(0)[:78], mean])
d.P("Start-up as logged by the driver (before the log level drops to ERROR):")
d.table(rows, [20, 100, 54], mono=(1,))

d.H("3.3 parallelize: six names become two partitions", 2)
d.P("`sc.parallelize(paths, 2)` (text_pipeline_engine.py). PySpark picks `batchSize = max(1, min(len(c) // numSlices, 1024)) = min(6 // 2, 1024) = 3`, "
    "pickles the list in batches of 3 into a temp file in the driver's local dir and asks the JVM (`PythonRDD.readRDDFromFile`) to load it "
    "as byte arrays - an RDD of pickled batches, sliced into 2 partitions. The paths are sorted, so:")
d.table([["partition", "task", "paths (in this order)", "went to"],
         ["0", "TID 0", "sample_scan6.png, sample_text1.txt, sample_text2.txt", "one POST /predict (kitchen log: scan6, text1, text2 together)"],
         ["1", "TID 1", "sample_text3.txt, sample_text4.txt, sample_text5.txt", "one POST /predict (text3, text4 hi, text5 mr)"]], [16, 12, 70, 76])
d.P("The pickled partition data is part of the ParallelCollectionRDD partition object, so it travels **inside the serialized task** (path 5), "
    "not through a separate broadcast.", "small")
d.H("3.4 mapPartitions + collect: the job", 2)
d.P("`paths_rdd.mapPartitions(process_partition)` only builds a PipelinedRDD in Python; nothing runs. `.collect()` makes Python "
    "cloudpickle `process_partition` (with everything it closes over: load_fn/run_fn or the broadcast handles) into a command, wrap it in a "
    "JVM `PythonFunction` and call `PythonRDD.collectAndServe(rdd)` over Py4J. In the JVM that is an ordinary `rdd.collect()`:")
rows = [["RDD id", "class", "created by (call site)", "parents", "partitions"]]
for r in A_S.get("rdds", []):
    rows.append([str(r["id"]), r["name"], r["callsite"], str(r["parents"]), str(r["partitions"])])
d.table(rows, [12, 34, 76, 16, 18], mono=(2,))
st0 = first(A_S.get("stages", []), {})
d.P(f"The DAGScheduler cuts the lineage into stages at shuffles; there is none, so **1 job -> 1 ResultStage (\"{st0.get('name', '')}\") -> "
    f"{st0.get('tasks', '?')} tasks**, one per partition. The stage's call stack in the event log shows the Python -> Py4J -> JVM hop:")
d.code("\n".join(st0.get("details", [])[:9]))
d.P(f"The DAGScheduler serialises (RDD chain + function) once into the **task binary** and broadcasts it (broadcast {tb_id}, "
    f"{bc.get(tb_id, '?')} as bytes). The TaskScheduler then offers the tasks to the executor's free slots: "
    f"{props.get('spark.executor.cores', 4)} cores / spark.task.cpus {props.get('spark.task.cpus', 2)} = 2 slots, so both tasks launch at once "
    "(locality PROCESS_LOCAL - the data is in the task itself).")
d.brk()

# ================================================================== 4
d.H("4. Worker side: executor JVM and Python worker")
d.H("4.1 The executor is a separate JVM, forked by the worker daemon", 2)
cmd = S_["exe"]["command"]
d.P("When the master grants an executor, the worker daemon starts `CoarseGrainedExecutorBackend` as a child JVM. Its command line "
    "(from the executor log) - note the driver URL it must call back and the 512 MB heap of service mode:")
d.code(exe_command(cmd), max_lines=30)
rows = [["UTC time", "executor log", "meaning"]]
mean = {"started": "JVM up (pid@host)", "driver_conn": "TCP to the driver / worker", "registered": "driver accepted the executor", "blockmgr": "executor BlockManager port",
        "assigned": "LaunchTask received", "running": "TaskRunner thread starts the task", "bc_start": "fetch broadcast from the driver",
        "bc_piece": "broadcast piece received", "bc_took": "broadcast read time", "times": "Python worker times (ms)",
        "finished": "result sent to the driver", "shutdown": "spark.stop() on the driver"}
for e in S_["exe"]["events"]:
    if e["what"] in ("bc_values",):
        continue
    ln = re.sub(r"^INFO ", "", e["line"])
    ln = re.sub(r" \(\d+ ms spent in bootstraps\)|, free [\d.]+ \w+| \(estimated total size [\d.]+ \w+\)", "", ln)
    rows.append([hm(e["t"])[:8], ln[:125], mean.get(e["what"], "")])
d.table(rows, [15, 125, 34], mono=(1,))
bcs = {e["groups"][0]: int(e["groups"][1]) for e in ev("svc", "bc_took")}
d.P(f"Broadcast {tb_id} is the task binary ({bc.get(tb_id, '?')} serialized, read in {bcs.get(tb_id, '?')} ms - the first fetch also opens the TCP "
    "connection to the driver's BlockManager). The three ~200-byte broadcasts are the service URL, labels and timeout; each Python worker "
    "receives their values through the local socket.")

d.H("4.2 The Python worker: pyspark.daemon forks one per task", 2)
sw = mid_sample(S_["probes"].get("spark-worker"), t_mid)
d.P("A JVM cannot run Python code, so for a PythonRDD partition the executor's `PythonRunner` asks `PythonWorkerFactory` for a worker. "
    "The first request starts `python -m pyspark.daemon`, which listens on a localhost port; for every task (the first included) the "
    "executor connects to it and the daemon **fork()**s a child that inherits the accepted socket - no new interpreter start-up, and "
    "pyspark's own modules are already imported. With "
    "spark.python.worker.reuse=true the child goes back to the daemon after the task instead of exiting. Worker node, mid-job:")
d.table(tree_rows(sw, ips_s), [10, 10, 14, 9, 10, 121], mono=(5,))


WORKER_PORT = (re.search(r"spark://Worker@[\d.]+:(\d+)", S_["exe"]["command"]) or re.search("(x)", "x")).group(1)


def names_worker(c, pl, pr):
    if c["state"] == "LISTEN":
        return {"8081": "worker web UI"}.get(pl, "pyspark.daemon (executor connects here)" if c["local"].startswith("127.0.0.1") else
                                              ("worker daemon RPC" if any(str(p) for p in c["pids"]) and pl not in ("8081",) and len(c["pids"]) and
                                               "Worker" in sw["procs"].get(str(c["pids"][0]), {}).get("cmd", "") else "executor BlockManager"))
    if pr == "8000":
        return "Python worker -> kitchen HTTP (path 7)"
    if pr == "7077":
        return "worker daemon <-> master"
    if c["local"].startswith("127.0.0.1"):
        return "executor JVM <-> Python worker (path 6)"
    if pr == props.get("spark.driver.port"):
        return "executor -> driver RPC (path 5 / 9)"
    if pr == WORKER_PORT or pl == WORKER_PORT:
        return "executor -> worker daemon (WorkerWatcher)"
    return "executor -> driver BlockManager (broadcast fetch)"


d.table(conn_rows(sw, ips_s, names_worker), [22, 44, 44, 18, 46], mono=(1, 2))
d.H("4.3 What crosses the executor <-> Python worker socket (path 6)", 2)
d.P("Both directions are a byte stream of 4-byte big-endian integers, lengths and pickled payloads (Spark 3.5 `PythonRunner` / `pyspark/worker.py`):")
d.table([["direction", "in this order", "here"],
         ["JVM -> Python", "auth secret; partition index; Python version; barrier flag; TaskContext (stage, partition, attempt, task id, cpus, resources, local properties)",
          "partition 0 or 1, stage 0"],
         ["", "SparkFiles dir; Python includes; broadcast variables (count, ids and values / file paths)", "3 settings broadcasts in service mode"],
         ["", "the command: pickled (function, profiler, deserializer, serializer) - the cloudpickled process_partition", "a few KB"],
         ["", "data frames: [length][pickled batch] ... then END_OF_DATA_SECTION (-1)", "one frame: a list of 3 absolute paths"],
         ["Python -> JVM", "result frames: [length][pickled object] for every object the iterator yields", "one dict {hostname, pid, times, results}"],
         ["", "TIMING_DATA (-3) + boot / init / finish times; spill counters; END_OF_DATA_SECTION; accumulator updates; END_OF_STREAM (-4)",
          "logged by the executor as 'Times: total, boot, init, finish'"]], [22, 104, 48])
times = [e["groups"] for e in ev("svc", "times")]
if times:
    d.P("Measured (ms): " + "; ".join(f"task {i}: total {int(t[0]):,}, boot {int(t[1]):,} (daemon start + fork), init {int(t[2]):,} (read header, "
                                        f"imports, unpickle command), finish {int(t[3]):,} (running process_partition = waiting for the kitchen)"
                                        for i, t in enumerate(times)) + ".")
d.H("4.4 Results back to the driver (path 9)", 2)
rows = [["task", "launched (UTC)", "deserialize", "run", "CPU of run", "result", "GC", "result ser.", "end"]]
for t in svc_tasks:
    rows.append([f"TID {t['tid']} (part. {t['index']})", hm(t["launch"]), f"{t['deser_ms']:,} ms", f"{t['run_ms'] / 1000:,.1f} s",
                 f"{t['cpu_ms']:,.0f} ms", f"{t['result_bytes']:,} B", f"{t['gc_ms']} ms", f"{t['result_ser_ms']} ms", t["reason"]])
d.table(rows, [26, 24, 17, 15, 17, 18, 11, 16, 16])
d.P("Run time is wall time of the task; CPU time is what the executor thread actually computed - under a second, because in service "
    "mode the task only waits for the HTTP answer. The Python worker's pickled dict comes back over the local socket; the executor "
    "serialises it into a **DirectTaskResult** (it is far below spark.task.maxDirectResultSize = 1 MB, so it rides inside the "
    "StatusUpdate RPC instead of being stored in the BlockManager) and sends StatusUpdate(FINISHED). The driver's TaskResultGetter "
    "deserialises it, the DAGScheduler hands it to the job's result handler in partition order, and when both tasks are in, "
    "`collectAndServe` opens a localhost socket from which Python reads the pickled list of 2 dicts. The driver merges them by file name "
    f"and writes `{res_file}` ({kb(res_size)}).")
d.brk()

# ================================================================== 5
d.H("5. Inside the model process: NER step by step on the GPU")
d.P("The same code runs in the kitchen (service mode) or in the Python worker (cluster mode): `pipeline.load()` once, then "
    "`pipeline.run(loaded, paths)` -> `process_paths_batched`. Measured with docs/ner_internals/stage_profile.py in the model-server image, "
    "alone on the machine, all 6 documents in one call: timers wrap the pipeline's own functions (GPU synchronised before every reading) "
    "and forward hooks record the tensors that reach the GPU.")
d.img("ner_tensor_path", "Figure 2 - from file bytes to entities; every crossing between the rows is a PCIe copy", maxh=78)
env = PF.get("env", {})
gpu = env.get("gpu", {})
pc = PF.get("pcie_256MB_copy", {})
d.table([["item", "value"],
         ["software", f"torch {env.get('torch')}, CUDA {env.get('cuda')}, cuDNN {env.get('cudnn')}, {env.get('cpu_count')} CPU threads visible"],
         ["GPU", f"{gpu.get('name')} (Turing): {gpu.get('sm_count')} SMs, compute capability {gpu.get('cc')}, {gpu.get('total_mb')} MB; PCIe Gen3 x16"],
         ["host -> GPU copy, 256 MB from pageable memory", f"{pc.get('pageable', {}).get('h2d_gb_s')} GB/s (the driver stages through its own pinned buffer)"],
         ["host -> GPU copy, 256 MB from pinned memory", f"{pc.get('pinned', {}).get('h2d_gb_s')} GB/s (DMA straight from locked pages)"],
         ["GPU -> host copy, 256 MB into new pageable memory", f"{pc.get('pageable', {}).get('d2h_gb_s')} GB/s - very slow under WSL2's paravirtualised GPU; "
          "irrelevant here because only small result tensors come back"]], [62, 112])

d.H("5.1 Loading the models (path 2)", 2)
L = PF.get("load", {})
if L:
    def vmtxt(k):
        v = L.get(k) or {}
        if not v:
            return "-"
        return (f"{v.get('pgpgin', 0) * 1024 / 1e6:,.0f} MB paged in, {v.get('pgmajfault', 0):,} major faults, "
                f"swap in/out {v.get('pswpin', 0) * 4096 / 1e6:,.0f}/{v.get('pswpout', 0) * 4096 / 1e6:,.0f} MB")
    L1 = (PF1 or {}).get("load", {})

    def t1(k, nd=1):
        return s(L1[k], nd) if k in L1 else "-"
    d.table([["step", "what happens", "bytes", "time", "1st run", "VM paging during the step"],
             ["resolve()", "model store: .complete marker found in /model_cache -> cache hit, no HDFS call; hf_cache copied into the HF hub cache", "-",
              s(L["resolve_and_hf_cache_s"], 2), t1("resolve_and_hf_cache_s", 2), "-"],
             ["GLiNER.from_pretrained", "load the tokenizer from the model folder (SentencePiece -> fast conversion: the convert_slow_tokenizer "
              "warning); build SpanModel with an mDeBERTa-v3 encoder from config (hf_cache), randomly initialised; read model.safetensors "
              "tensor by tensor (safe_open) and load_state_dict", kb(L["gliner_fp32"]["bytes"]), s(L["gliner_disk_to_ram_s"]), t1("gliner_disk_to_ram_s"),
              vmtxt("vm_gliner_disk_to_ram")],
             [".to('cuda')", "copy of every parameter / buffer (fp32) from pageable memory", kb(L["gliner_fp32"]["bytes"]), s(L["gliner_to_gpu_s"]),
              t1("gliner_to_gpu_s"), vmtxt("vm_gliner_to_gpu")],
             [".half()", "fp32 -> fp16 on the GPU (a cast kernel per tensor)", f"-> {kb(L['gliner_fp16']['bytes'])}", s(L["gliner_half_s"], 2),
              t1("gliner_half_s", 2), "-"],
             ["NLLB tokenizer", "tokenizer.json + sentencepiece.bpe.model", "22 MB", s(L["nllb_tokenizer_s"]), t1("nllb_tokenizer_s"), "-"],
             ["NLLB from_pretrained", "torch.load(pytorch_model.bin, mmap=True): tensors are mapped, pages are read on first touch",
              kb(L["nllb"]["bytes"]), s(L["nllb_disk_to_ram_s"]), t1("nllb_disk_to_ram_s"), vmtxt("vm_nllb_disk_to_ram")],
             [".to('cuda')", "copy of every parameter (fp32) - touches, and so reads, the mapped pages", kb(L["nllb"]["bytes"]), s(L["nllb_to_gpu_s"]),
              t1("nllb_to_gpu_s"), vmtxt("vm_nllb_to_gpu")]], [22, 62, 16, 13, 13, 48])
    h2d = pc.get("pageable", {}).get("h2d_gb_s", 1) or 1
    vg, vn = L.get("vm_gliner_to_gpu") or {}, L.get("vm_nllb_to_gpu") or {}
    d.P(f"Reading the table: at the measured {h2d} GB/s block-copy rate the two copies would take "
        f"{L['gliner_fp32']['bytes'] / 1e9 / h2d:.1f} s and {L['nllb']['bytes'] / 1e9 / h2d:.1f} s. NLLB's copy read "
        f"{vn.get('pgpgin', 0) * 1024 / 1e9:,.1f} GB from disk while it ran - the memory-mapped checkpoint is only read when the copy touches it, so this "
        f"step is really the disk read (~{L['nllb']['bytes'] / 1e6 / max(L['nllb_to_gpu_s'], 1e-3):,.0f} MB/s from the Docker volume). GLiNER's copy read "
        f"only {vg.get('pgpgin', 0) * 1024 / 1e6:,.0f} MB, yet still took {s(L['gliner_to_gpu_s'])}: the time is in the copy path itself - hundreds of "
        "separate pageable-memory copies through WSL2's paravirtualised GPU driver, each staged by the driver - which a single large block copy "
        "does not show. The two profiler runs differ by up to 2x on the same steps: model loading on this laptop is dominated by the machine's "
        "I/O and memory state, not by the models or PCIe. On a worker with enough RAM and a local SSD these steps take seconds; on small "
        "nodes this is the strongest argument for loading once, in a kitchen.", "small")
    d.P(f"GPU memory after loading: GLiNER {L['gpu_after_gliner'].get('allocated_mb', 0):,.0f} MB allocated (fp16); with NLLB "
        f"{L['gpu_after_nllb'].get('allocated_mb', 0):,.0f} MB allocated / {L['gpu_after_nllb'].get('reserved_mb', 0):,.0f} MB reserved by PyTorch's "
        "caching allocator, out of 4,096 MB - one copy of the models fits, two do not (hence one task per GPU in cluster mode).", "small")

d.H("5.2 Front end: text, language, route, chunks", 2)
docs = PF.get("docs") or {}
MAXT = st.get("TRANSLATE_MAX_TOKENS", 400)
rows = [["document", "extract", "chars (UTF-8 bytes)", "language id", "route", "chunks (chars)", "NLLB tokens per chunk"]]
for name, x in docs.items():
    toks = x.get("nllb_tokens_untruncated")
    tt = ", ".join(f"{t}" + (f" (> {MAXT}: cut)" if t > MAXT else "") for t in toks) if toks else "-"
    rows.append([name, s(x["extract_s"], 3), f"{x['chars']:,} ({x['utf8_bytes']:,})", f"{x['lang']} in {x['lid_s'] * 1000:,.1f} ms",
                 x["route"] + (f" {x['nllb_src']}" if x.get("nllb_src") else ""), f"{x['chunks']} ({', '.join(str(c) for c in x.get('chunk_chars', []))})", tt])
d.table(rows, [28, 15, 24, 24, 26, 26, 31])
trunc = [(n, x) for n, x in docs.items() if any(t > MAXT for t in (x.get("nllb_tokens_untruncated") or []))]
d.P("The first language-id call also loads py3langid's model (the slow first row); later calls take milliseconds. Devanagari text needs "
    "about 2.5 UTF-8 bytes per character and many more SentencePiece tokens per character than English, which matters for the next step.", "small")
if trunc:
    d.note("**Finding - translation input is truncated.** `translate_chunks` tokenizes with `truncation=True, max_length=400`, but chunks are "
           "cut at 1,500 **characters**, not tokens. " + "; ".join(f"{n}: chunk token counts {x['nllb_tokens_untruncated']}" for n, x in trunc) +
           f". Every token beyond {MAXT} is dropped before NLLB sees it, so the end of that chunk is never translated and its entities are only "
           "reachable by the phone-number regex on the original text.", warn=True)
TF = sorted(__import__("glob").glob(os.path.join(REPO, "results", "translate_fix_*", "report.json")))
if TF:
    tf = __import__("json").load(open(TF[-1], encoding="utf-8"))
    d.P("**Fixed after this trace** (`chunk_for_translation` in mt_ner_all_formats.py): sentences also end at the Devanagari danda / double "
        "danda and the Urdu full stop, and NLLB gets **one unit per sentence or line**, split further only above 398 tokens. Sending whole "
        "paragraphs was not enough: a token-bounded multi-sentence chunk fixed the truncation but NLLB still stopped early and dropped the "
        f"sentences after the first ones. Verified on the GPU with docs/ner_internals/verify_translate_chunking.py (`{os.path.basename(os.path.dirname(TF[-1]))}`), "
        "same process, models loaded once, warm:")
    rows = [["document", "tokens to NLLB, before", "after", "unique entities before -> after"]]
    for n, x in tf["docs"].items():
        if "tokens_to_nllb" in x.get("after", {}):
            rows.append([n, str(x["before"]["tokens_to_nllb"]), str(x["after"]["tokens_to_nllb"]),
                         f"{x['before']['entities_unique']} -> {x['after']['entities_unique']}; translation {len(x['before']['translation']):,} -> "
                         f"{len(x['after']['translation']):,} characters"])
    tm = tf.get("timing", {})
    rows.append(["all 6 documents", f"translate {tm.get('before', {}).get('translate_s')} s, total {tm.get('before', {}).get('total_s')} s",
                 f"translate {tm.get('after', {}).get('translate_s')} s, total {tm.get('after', {}).get('total_s')} s",
                 "English documents: " + ", ".join(f"{x['before']['entities_unique']} -> {x['after']['entities_unique']}" for n, x in tf["docs"].items()
                                                   if "tokens_to_nllb" not in x.get("after", {}))])
    d.table(rows, [30, 34, 50, 60])
    d.P("Before the fix NLLB returned only part of each Devanagari document (the old Hindi translation covers only its first few sentences); "
        "after it, every sentence is translated - aircraft, call signs, people and places that were missing are now found. Shorter units "
        "also make translation faster: the decoder runs as many steps as the longest output in a batch, and a sentence's output is short.", "small")

runs = PF.get("runs", [])
for i, r in enumerate(runs[:2]):
    d.H(f"5.{i + 3} {r['run'].capitalize()}: {s(r['total_s'], 2)} for all 6 documents", 2)
    stg = r["stage_s"]
    d.P("Time inside each stage function: " + ", ".join(f"`{k}` {s(v, 2)}" for k, v in stg.items()) +
        f". NLLB: {r['nllb_encoder_calls']} encoder passes, {r['nllb_decoder_steps']} decoder steps. Peak GPU memory above the weights "
        f"(activations, KV cache, workspaces): {r['peak_activation_mb']} MB. Result dict as JSON: {kb(r['result_json_bytes'])}.")
    rows = [["call (in order)", "input on the GPU", "output", "time"]]
    for c in r["calls"]:
        if c["op"] == "nllb.generate":
            rows.append([f"NLLB generate {c['src_lang']} -> eng_Latn", f"input_ids {c['input_ids']} int64 ({c['input_tokens_real']} real tokens)",
                         f"output_ids {c['output_ids']} (steps = longest output)", s(c["s"], 2)])
        else:
            rows.append(["GLiNER batch_predict_entities", f"{c['batch']} chunks pooled from all documents: {', '.join(str(x) for x in c['chars'])} chars",
                         f"entities per chunk {c['entities']}", s(c["s"], 2)])
    d.table(rows, [40, 70, 46, 18])
fi = (runs[0].get("gliner_forward_inputs") or [{}])[0] if runs else {}
if fi and "span_idx" in fi:
    B, T = fi["input_ids"][0]
    S = fi["span_idx"][0][1]
    d.P(f"What GLiNER's forward pass receives (hook on `SpanModel.forward`): input_ids / attention_mask / words_mask {fi['input_ids'][0]} int64 - "
        f"{B} chunks padded to {T} sub-word tokens (the 19 label prompts are prepended to every chunk's words); span_idx {fi['span_idx'][0]} - every "
        f"span of 1 to 12 words starting at every word, {S:,} = {S // 12} words x 12 widths for the longest chunk; span_mask {fi['span_mask'][0]} bool. "
        f"The model scores all {S:,} spans against all 19 labels ({S * 19:,} sigmoid scores per chunk) in one fp16 pass; spans above 0.35 "
        "survive, overlaps are resolved greedily, and only those (start, end, label, score) tuples are copied back to the host.", "small")
if len(runs) >= 2:
    c0, c1 = runs[0], runs[1]
    d.P(f"Cold vs warm: GLiNER {c0['stage_s'].get('predict_chunks', 0):.1f} s -> {c1['stage_s'].get('predict_chunks', 0):.1f} s, NLLB "
        f"{c0['stage_s'].get('translate_chunks', 0):.1f} s -> {c1['stage_s'].get('translate_chunks', 0):.1f} s. The first call pays for loading CUDA "
        "kernels (lazy module loading), creating cuBLAS / cuDNN handles and growing the caching allocator. NLLB stays expensive when warm "
        "because generation is sequential: one decoder pass per output token.", "small")
    d.P("Unique entities per document: " + ", ".join(f"{k} {v}" for k, v in c1["entities_unique"].items()) + ".", "small")

d.H("5.5 What the kitchen did during the Spark job", 2)
kl = [k for k in TR["kitchen"] if S_["start"] - 5 <= k["t"] <= S_["end"] + 5]
rows = [["UTC time", "t (s)", "kitchen log"]]
for k in kl:
    if "Asking to truncate" in k["msg"] or k["msg"].startswith("INFO:ner_translate") or "[done]" in k["msg"] or "POST /predict" in k["msg"]:
        rows.append([hm(k["t"])[:12], f"{k['t'] - S_['start']:.1f}", k["msg"][:110]])
d.table(rows, [22, 12, 140], mono=(2,))
tess = []
for r in S_["probes"].get("ner-translate-server", []):
    for p in r["procs"].values():
        if p["cmd"].startswith("tesseract"):
            tess.append(r["t"] - S_["start"])
if tess:
    d.P(f"The probe saw a `tesseract` child of the kitchen from t = {min(tess):.0f} s to {max(tess):.0f} s: pytesseract writes the decoded "
        "image to /tmp/tess_*.PNG, runs the tesseract binary with all 11 language models (eng+mar+hin+...), and reads the text back - "
        "one more copy of the document inside the node.", "small")
if len(pb) >= 3:
    pds = S_["driver"]["summary"].get("partition_details") or [{}, {}]
    d.note(f"Why the two Spark requests took {pds[0].get('run_time_sec', 0):.0f} s and {pds[-1].get('run_time_sec', 0):.0f} s while the same "
           f"batches sent directly afterwards took {pb[1]['total_s']:.1f} s and {pb[2]['total_s']:.1f} s: they were the **first** requests after the "
           "model server started (first OCR run loads 11 tesseract language models; first CUDA calls load kernels and create cuBLAS / cuDNN handles; "
           "the allocator grows) and they arrived **together**: FastAPI runs a plain `def` endpoint in a thread pool, so both requests ran at the "
           "same time in two threads, sharing one copy of the models, one GIL, 8 CPU threads and one GPU.")
d.brk()

# ================================================================== 6
d.H("6. Service mode end to end - measured timeline")
t0 = S_["start"]
lanes = []
if A_S:
    lanes.append(("driver: SparkContext", [(A_S["app_start"] - 1 - t0 + (0), A_S["app_start"] - t0, charts.C["driver"], ""),
                                            (A_S["app_start"] - t0, A_S["job_submit"] - t0, charts.C["driver"], "SparkContext + app registered")]))
    ex0 = first(ev("svc", "started"))
    reg = first(ev("svc", "registered"))
    if ex0 and reg:
        lanes.append(("executor JVM start", [(ex0["t"] - t0, reg["t"] - t0 + 1, charts.C["spark"], "JVM start -> registered")]))
    lanes.append(("job 0 / stage 0", [(A_S["job_submit"] - t0, A_S["job_end"] - t0, charts.C["spark"], "collect()")]))
    for i, tk in enumerate(svc_tasks):
        tm = times[i] if i < len(times) else None
        bars = [(tk["launch"] - t0, tk["launch"] - t0 + tk["deser_ms"] / 1000, charts.C["spark"], "")]
        if tm:
            b0 = tk["launch"] - t0 + tk["deser_ms"] / 1000
            bars += [(b0, b0 + int(tm[1]) / 1000, charts.C["boot"], "boot"),
                     (b0 + int(tm[1]) / 1000, b0 + (int(tm[1]) + int(tm[2])) / 1000, charts.C["python"], ""),
                     (b0 + (int(tm[1]) + int(tm[2])) / 1000, tk["finish"] - t0, charts.C["wait"], f"POST /predict, wait {int(tm[3]) / 1000:.0f} s")]
        lanes.append((f"task {tk['tid']} (partition {tk['index']})", bars))
    done = [k for k in kl if "Processed" in k["msg"]]
    for i, k in enumerate(done):
        dur = float(re.search(r"in ([\d.]+)s", k["msg"]).group(1))
        lanes.append((f"kitchen request {i + 1}", [(k["t"] - dur - t0, k["t"] - t0, charts.C["kitchen"], f"3 documents, {dur:.0f} s")]))
    if tess:
        lanes.append(("tesseract subprocess", [(min(tess), max(tess) + 1, charts.C["io"], "OCR sample_scan6.png")]))
    lanes.append(("driver: merge + write", [(A_S["job_end"] - t0, S_["end"] - t0, charts.C["driver"], "JSON, spark.stop()")]))
    d.P(f"t = 0 is `docker exec ... submit_pipeline_job.py` ({hm(t0)[:8]} UTC). Bars from the event log, executor log, kitchen log and probes:")
    d.story.append(charts.timeline(lanes, 0, S_["end"] - t0 + 2, font=BODY))
    g = S_["gpu"]
    if g:
        d.story.append(charts.linechart([("GPU utilisation %", charts.C["gpu"], [(x["t"] - t0, x["util"]) for x in g]),
                                         ("GPU memory used (x 40 MB)", charts.C["kitchen"], [(x["t"] - t0, x["mem"] / 40) for x in g])],
                                        0, S_["end"] - t0 + 2, 100, ylabel="GPU (nvidia-smi)", font=BODY, yfmt="{:.0f}"))
        d.P(f"GPU memory stayed at {min(x['mem'] for x in g):,.0f}-{max(x['mem'] for x in g):,.0f} MB (models resident since kitchen start); "
            f"utilisation peaked at {max(x['util'] for x in g):.0f} %; link {g[0]['pcie']}.", "small")
        busy = [x["t"] - t0 for x in g if x["util"] >= 5]
        if busy:
            d.P(f"The GPU was idle (< 5 %) until t = {min(busy):.0f} s although both requests reached the kitchen at t = 33 s: most of their "
                "time was CPU-side - OCR (the tesseract bar), the first-call initialisation of CUDA kernels and libraries, and two request "
                "threads taking turns on one GIL in a memory-starved VM. Once warm, the same six documents need about 21 s in total "
                "(section 5.4).", "small")
    d.table([["phase", "duration", "source"],
             ["python start -> SparkContext ready", s(A_S["app_start"] - t0), "event log ApplicationStart"],
             ["app start -> executor registered", s(A_S["executor_added"] - A_S["app_start"]), "event log ExecutorAdded"],
             ["job submitted -> tasks launched", s(min(t["launch"] for t in svc_tasks) - A_S["job_submit"]), "event log"],
             ["task wall time (max)", s(max(t["run_ms"] for t in svc_tasks) / 1000), "event log TaskEnd"],
             ["job (collect) total", s(A_S["job_end"] - A_S["job_submit"]), "event log JobStart/JobEnd"],
             ["whole command", s(S_["end"] - t0), "docker exec wall time"]], [70, 30, 74])

# ================================================================== 7
d.brk()
d.H("7. Cluster mode end to end - measured timeline")
d.P("Same command with `--execution-mode cluster --partitions 1` on the cluster profile (ner-translate-worker image: Spark + torch + "
    "GLiNER + NLLB in one image). There is no kitchen: the Python worker imports the pipeline and calls `load()` then `run()` itself, so "
    "paths 2 (cache -> RAM -> GPU) and 8 (reading documents) happen **inside the Spark task**. One partition, because two concurrent "
    "tasks would each load their own copy of the models into the 4 GB GPU.")
c_tasks = A_C.get("tasks", [])
t0c = C_["start"]
if A_C and c_tasks:
    ctimes = [e["groups"] for e in ev("clu", "times")]
    pd = C_["driver"]["summary"].get("partition_details") or [{}]
    tk = c_tasks[0]
    b0 = tk["launch"] - t0c + tk["deser_ms"] / 1000
    bars = [(tk["launch"] - t0c, b0, charts.C["spark"], "")]
    if ctimes:
        boot, init = int(ctimes[0][1]) / 1000, int(ctimes[0][2]) / 1000
        ld = pd[0].get("load_time_sec", 0)
        bars += [(b0, b0 + boot, charts.C["boot"], ""), (b0 + boot, b0 + boot + init, charts.C["python"], "import"),
                 (b0 + boot + init, b0 + boot + init + ld, charts.C["load"], f"load() {ld:.0f} s"),
                 (b0 + boot + init + ld, tk["finish"] - t0c, charts.C["gpu"], f"run() {pd[0].get('run_time_sec', 0):.0f} s")]
    lanes = [("driver: SparkContext", [(0, A_C["app_start"] - t0c, charts.C["driver"], ""), (A_C["app_start"] - t0c, A_C["job_submit"] - t0c, charts.C["driver"], "")]),
             ("job 0 / stage 0", [(A_C["job_submit"] - t0c, A_C["job_end"] - t0c, charts.C["spark"], "collect()")]),
             (f"task {tk['tid']} (6 documents)", bars),
             ("driver: merge + write", [(A_C["job_end"] - t0c, C_["end"] - t0c, charts.C["driver"], "")])]
    d.story.append(charts.timeline(lanes, 0, C_["end"] - t0c + 2, font=BODY))
    cw = C_["probes"].get("ner-cluster-worker", [])
    rss = trace_data.series(cw, lambda c: c.startswith("python -m pyspark.daemon") or "pyspark.worker" in c)
    g = C_["gpu"]
    ser = []
    if g:
        ser += [("GPU memory used (MB / 10)", charts.C["gpu"], [(x["t"] - t0c, x["mem"] / 10) for x in g]),
                ("GPU utilisation %", charts.C["kitchen"], [(x["t"] - t0c, x["util"]) for x in g])]
    if rss:
        ser.append(("Python worker RSS (MB / 10)", charts.C["python"], [(t - t0c, v / 10) for t, v in rss]))
    if ser:
        ymax = max(100, max(v for _, _, pts in ser for _, v in pts) * 1.05)
        d.story.append(charts.linechart(ser, 0, C_["end"] - t0c + 2, ymax, height=46 * 2.83465, ylabel="worker node", font=BODY, yfmt="{:.0f}"))
    rows = [["phase", "duration", "source"],
            ["python start -> SparkContext ready", s(A_C["app_start"] - t0c), "event log"],
            ["task deserialize", f"{tk['deser_ms']:,} ms", "event log TaskEnd"]]
    if ctimes:
        rows += [["Python worker boot (daemon start + fork)", f"{int(ctimes[0][1]):,} ms", "executor log 'Times'"],
                 ["Python worker init: unpickling the closure imports the pipeline module (torch, transformers, gliner)",
                  f"{int(ctimes[0][2]):,} ms", "executor log 'Times' (service mode: " + (f"{int(times[0][2]):,} ms" if times else "-") + ")"]]
    rows += [["load(): model store (cache hit) + GLiNER + NLLB to GPU", s(pd[0].get("load_time_sec", 0)), "partition_details"],
             ["run(): 6 documents", s(pd[0].get("run_time_sec", 0)), "partition_details"],
             ["task wall time / CPU time", f"{tk['run_ms'] / 1000:,.1f} s / {tk['cpu_ms'] / 1000:,.1f} s", "event log (CPU = JVM thread only)"],
             ["result size", f"{tk['result_bytes']:,} B", "event log"],
             ["whole command", s(C_["end"] - t0c), "docker exec wall time"]]
    d.table(rows, [80, 36, 58])
    if rss:
        d.P(f"The Python worker grew to {max(v for _, v in rss):,.0f} MB RSS while loading (checkpoint tensors in RAM before the copy to the GPU). "
            "The executor JVM's own CPU time stays small: all work happens in the forked Python process, which Spark accounts for only "
            "as wall time.", "small")
    cwm = mid_sample(cw, t0c + (tk["finish"] - t0c) * 0.8) if cw else None
    if cwm:
        d.P("Worker node processes near the end of the task:")
        d.table(tree_rows(cwm, ips_c), [10, 10, 14, 9, 10, 121], mono=(5,))
    outl = [l for l in C_["exe"].get("stderr_text", "").splitlines()
            if l.strip() and ("[model_store]" in l or "[ner_translate]" in l or "GPU detected" in l or "[done]" in l or "fp16" in l)]
    if outl:
        d.P("What the Python worker printed - it lands in the executor's **stderr** file of the Spark work dir (the worker's stdout is "
            "redirected there), next to the executor's own log lines:")
        d.code("\n".join(outl[:14]))
    vs = C_.get("vmstat") or []
    if len(vs) > 2:
        a0, a1 = vs[0], vs[-1]
        d.P(f"VM-wide paging while the task ran (sampled every 2 s): {(a1.get('pgpgin', 0) - a0.get('pgpgin', 0)) * 1024 / 1e9:,.1f} GB read from disk, "
            f"swap in / out {(a1.get('pswpin', 0) - a0.get('pswpin', 0)) * 4096 / 1e6:,.0f} / {(a1.get('pswpout', 0) - a0.get('pswpout', 0)) * 4096 / 1e6:,.0f} MB, "
            f"lowest MemAvailable {min(v.get('MemAvailable', 0) for v in vs) / 1024:,.0f} MB. The models the task needs are 3.6 GB "
            "(model.safetensors 1.2 GB + NLLB 2.5 GB), so pages were read more than once: under memory pressure the page cache "
            "evicted checkpoint pages before the copy to the GPU had used them. The load is bound by disk reads in a memory-starved "
            "VM, not by PCIe.", "small")

# ================================================================== 8
def ents_line(docs):
    return ", ".join(re.sub(r"sample_|\.txt|\.png", "", l.split(":")[0]) + " " + l.split("entities=")[1] for l in docs)


d.H("8. Service mode vs cluster mode")
pdc = (C_["driver"]["summary"].get("partition_details") or [{}])[0]
d.table([["", "service mode (waiter / kitchen)", "cluster mode (in-process)"],
         ["who reads the documents (path 8)", "the kitchen", "the Python worker of each task"],
         ["where models live in RAM / GPU (path 2)", "once, in the kitchen, loaded at server start", "in every Python worker, loaded by every task"],
         ["executor image", "spark-lean (no torch)", "ner-translate-worker (Spark + torch + models' code)"],
         ["what the Python worker sends over the network", "HTTP POST with 3 paths (134 B body)", "nothing - it reads files and uses the local GPU"],
         ["parallelism limit", "kitchen threads share one model copy", "GPU memory: one model copy per concurrent task"],
         ["this run", f"{S_['driver']['summary'].get('elapsed_time', 0):.0f} s job, first requests after server start, 2 tasks",
          f"{C_['driver']['summary'].get('elapsed_time', 0):.0f} s job: load {pdc.get('load_time_sec', 0):.0f} s + run {pdc.get('run_time_sec', 0):.0f} s, 1 task"],
         ["unique entities per document", ents_line(S_["driver"]["docs"]),
          ents_line(C_["driver"]["docs"]) + " (text1 differs by one: GPU batch composition + fp16, a mention at the 0.35 threshold)"]],
        [44, 65, 65])

# ================================================================== 9
d.H("9. Nitty-gritty findings")
d.B([f"**Spark moves names, not documents.** The task for 3 documents carries 3 path strings; the only large payloads Spark moves are the result "
     f"dicts ({res_bytes}). Every node must see `/app/data/...` at the same path.",
     "**Hindi / Marathi translations lost text - fixed** (section 5.2): chunks were sized in characters (1,500) but NLLB input is truncated at "
     "400 tokens (the Devanagari chunks were 431-444 tokens), and multi-sentence input made NLLB stop early. Now one unit per sentence: "
     "Hindi entities 14 -> 29, Marathi 24 -> 39, translation faster.",
     "**gliner-multi's pytorch_model.bin is never read** (GLiNER 0.2.13 prefers model.safetensors): 1.2 GB stored in HDFS, fetched into every "
     "node cache and never used.",
     "**Results are keyed by file base name** (`os.path.basename`): two inputs with the same name in different folders overwrite each other in the merge.",
     "**Result size grows with document size**: each result carries `original_text` and `text_used` besides the entities. Past 1 MB per task a result "
     "goes through the BlockManager (IndirectTaskResult); past spark.driver.maxResultSize (4 GB) collect() fails - for large corpora write per-partition "
     "outputs instead of collecting.",
     f"**In cluster mode load() runs once per task, not once per executor** (text_pipeline_engine calls load_fn inside process_partition): with worker "
     f"reuse the same Python process reloads 3.6 GB of weights into the GPU for every task ({pdc.get('load_time_sec', 0):.0f} s here). Caching the loaded "
     "models in a module-level variable of the pipeline would make it once per Python worker.",
     "**spark.task.cpus = 2** turns a 4-core executor into 2 task slots; in service mode both tasks' requests reach the kitchen at the same time and run "
     "concurrently in its thread pool on one model copy.",
     "**The executor's CPU time is not the work**: Spark's task CPU metric counts only the JVM thread; the Python worker (cluster mode) or the kitchen "
     "(service mode) does the computing.",
     "**First requests are slow**: tesseract language models, CUDA kernels and allocator warm-up; the stage profile's cold vs warm runs show the gap.",
     "**Network is not the bottleneck**: a whole service-mode job moved tens of KB between nodes; model bytes move only on the first load of a node (path 1)."])

# ================================================================== 10
d.H("10. Reproduce")
d.code("bash docs/ner_internals/run_trace.sh                    # ~25 min: both jobs, /predict, stage profile\n"
       "python docs/diagrams/build_diagrams.py                  # figures 25-27\n"
       "python docs/ner_internals/build_ner_internals_pdf.py    # this PDF from the newest results/ner_trace_*")
d.P(f"Raw evidence of this document: `results/{TR['name']}/` - eventlog/ (Spark), svc_* and clu_* (driver logs, executor work dirs, "
    "probe JSONL, GPU CSV), predict_bytes.txt, stage_profile.json.", "small")

d.build(OUT, "NER on Spark - data paths and execution internals")
