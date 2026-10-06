"""
trace_data.py - reads one traced run (results/ner_trace_<ts>/, produced by run_trace.sh)
into plain dicts for the PDF: Spark event logs, executor / driver / kitchen logs,
/proc probes, GPU samples, HTTP byte counts and the stage profile.
"""
import calendar
import glob
import json
import os
import re
import time


def latest_trace(repo):
    runs = sorted(glob.glob(os.path.join(repo, "results", "ner_trace_*")))
    return runs[-1] if runs else None


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _epoch(stamp):
    """'26/09/27 09:01:45' (UTC, Spark log4j) -> epoch seconds."""
    return calendar.timegm(time.strptime(stamp, "%y/%m/%d %H:%M:%S"))


def _iso(stamp):
    """docker --timestamps '2026-09-27T09:03:31.970988891Z' -> epoch seconds."""
    main, frac = stamp.rstrip("Z").split(".")
    return calendar.timegm(time.strptime(main, "%Y-%m-%dT%H:%M:%S")) + float("0." + frac)


# ------------------------------------------------------------------ Spark event log
def event_logs(trace):
    apps = {}
    for f in glob.glob(os.path.join(trace, "eventlog", "app-*")):
        ev = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
        props = next((e["Spark Properties"] for e in ev if e["Event"] == "SparkListenerEnvironmentUpdate"), {})
        mode = "cluster" if "ner-cluster-master" in props.get("spark.master", "") else "service"
        a = {"file": os.path.basename(f), "props": props, "tasks": [], "stages": [], "rdds": []}
        for e in ev:
            k = e["Event"]
            if k == "SparkListenerApplicationStart":
                a["app_start"], a["app_id"] = e["Timestamp"] / 1000, e["App ID"]
            elif k == "SparkListenerApplicationEnd":
                a["app_end"] = e["Timestamp"] / 1000
            elif k == "SparkListenerExecutorAdded":
                a["executor_added"] = e["Timestamp"] / 1000
                a["executor_host"], a["executor_cores"] = e["Executor Info"]["Host"], e["Executor Info"]["Total Cores"]
            elif k == "SparkListenerJobStart":
                a["job_submit"] = e["Submission Time"] / 1000
            elif k == "SparkListenerJobEnd":
                a["job_end"], a["job_result"] = e["Completion Time"] / 1000, e["Job Result"]["Result"]
            elif k == "SparkListenerStageSubmitted":
                si = e["Stage Info"]
                a["stages"].append({"id": si["Stage ID"], "name": si["Stage Name"], "tasks": si["Number of Tasks"],
                                    "details": si["Details"].splitlines()})
                a["rdds"] = [{"id": r["RDD ID"], "name": r["Name"], "callsite": r.get("Callsite"), "parents": r.get("Parent IDs"),
                              "partitions": r["Number of Partitions"]} for r in si["RDD Info"]]
            elif k == "SparkListenerStageCompleted":
                si = e["Stage Info"]
                a["stage_submit"], a["stage_done"] = si.get("Submission Time", 0) / 1000, si.get("Completion Time", 0) / 1000
            elif k == "SparkListenerTaskEnd":
                ti, tm = e["Task Info"], e["Task Metrics"]
                a["tasks"].append({"tid": ti["Task ID"], "index": ti["Index"], "host": ti["Host"], "executor": ti["Executor ID"],
                                   "locality": ti["Locality"], "launch": ti["Launch Time"] / 1000, "finish": ti["Finish Time"] / 1000,
                                   "deser_ms": tm["Executor Deserialize Time"], "deser_cpu_ms": tm["Executor Deserialize CPU Time"] / 1e6,
                                   "run_ms": tm["Executor Run Time"], "cpu_ms": tm["Executor CPU Time"] / 1e6,
                                   "result_bytes": tm["Result Size"], "gc_ms": tm["JVM GC Time"],
                                   "result_ser_ms": tm["Result Serialization Time"], "reason": e["Task End Reason"]["Reason"]})
        a["tasks"].sort(key=lambda t: t["tid"])
        apps[mode] = a
    return apps


# ------------------------------------------------------------------ executor log (worker work dir)
EXE_PATTERNS = [
    ("started", r"CoarseGrainedExecutorBackend: Started daemon with process name: (\S+)"),
    ("driver_conn", r"Successfully created connection to (\S+) after (\d+) ms"),
    ("registered", r"CoarseGrainedExecutorBackend: Successfully registered with driver"),
    ("blockmgr", r"NettyBlockTransferService: Server created on (\S+)"),
    ("assigned", r"Got assigned task (\d+)"),
    ("running", r"Running task (\S+) in stage (\S+) \(TID (\d+)\)"),
    ("bc_start", r"Started reading broadcast variable (\d+) with (\d+) pieces"),
    ("bc_piece", r"Block broadcast_(\d+)_piece0 stored as bytes in memory \(estimated size ([\d.]+ \w+)"),
    ("bc_values", r"Block broadcast_(\d+) stored as values in memory \(estimated size ([\d.]+ \w+)"),
    ("bc_took", r"Reading broadcast variable (\d+) took (\d+) ms"),
    ("times", r"PythonRunner: Times: total = (\d+), boot = (-?\d+), init = (\d+), finish = (\d+)"),
    ("finished", r"Finished task (\S+) in stage (\S+) \(TID (\d+)\)\. (\d+) bytes result sent to driver"),
    ("shutdown", r"Driver commanded a shutdown"),
]


def executor_log(trace, prefix):
    out = {"events": [], "command": "", "stdout": ""}
    for f in glob.glob(os.path.join(trace, f"{prefix}_work", "app-*", "*", "stderr")):
        txt = _read(f)
        m = re.search(r'Spark Executor Command: (.+)', txt)
        out["command"] = m.group(1) if m else ""
        for line in txt.splitlines():
            ts = re.match(r"(\d\d/\d\d/\d\d \d\d:\d\d:\d\d) ", line)
            if not ts:
                continue
            for name, pat in EXE_PATTERNS:
                mm = re.search(pat, line)
                if mm:
                    out["events"].append({"t": _epoch(ts.group(1)), "what": name, "groups": mm.groups(), "line": line[18:]})
        out["stdout"] = _read(os.path.join(os.path.dirname(f), "stdout"))
        out["stderr_text"] = txt
    return out


# ------------------------------------------------------------------ driver log
def driver_log(trace, prefix):
    txt = _read(os.path.join(trace, f"{prefix}_driver.log")).replace("\r", "\n")
    lines = [l for l in txt.splitlines() if not l.startswith("[Stage")]
    info = [l for l in lines if re.match(r"\d\d/\d\d/\d\d ", l)]
    m = re.search(r"(\{\s*\"elapsed_time\".*?\n\})", txt, re.S)
    summary = json.loads(m.group(1)) if m else {}
    docs = [l.strip() for l in lines if "entities=" in l]
    res = re.search(r"written to (\S+)", txt)
    return {"info": info, "summary": summary, "docs": docs, "results_file": res.group(1) if res else None, "text": txt}


# ------------------------------------------------------------------ kitchen log (docker logs --timestamps)
def kitchen_log(trace):
    out = []
    for line in _read(os.path.join(trace, "svc_kitchen.log")).splitlines():
        if " " not in line or "GET /health" in line:
            continue
        stamp, msg = line.split(" ", 1)
        try:
            out.append({"t": _iso(stamp), "msg": msg})
        except ValueError:
            continue
    return out


# ------------------------------------------------------------------ /proc probes
def probes(trace, prefix, name):
    f = os.path.join(trace, f"{prefix}_probe_{name}.jsonl")
    if not os.path.exists(f):
        return []
    rows = []
    for l in open(f, encoding="utf-8"):
        try:
            rows.append(json.loads(l))
        except ValueError:
            pass
    return rows


def proc_tree(sample, keep=lambda p: True):
    ps = {int(k): v for k, v in sample["procs"].items()}
    out = []

    def walk(pid, depth):
        p = ps[pid]
        if keep(p):
            out.append((depth, pid, p))
        for c in sorted(k for k, v in ps.items() if v["ppid"] == pid):
            walk(c, depth + 1)
    for r in sorted(k for k, v in ps.items() if v["ppid"] not in ps):
        walk(r, 0)
    return out


def net_delta(rows, ifc="eth0"):
    if len(rows) < 2:
        return 0, 0
    a, b = rows[0]["net"].get(ifc, {}), rows[-1]["net"].get(ifc, {})
    return b.get("rx", 0) - a.get("rx", 0), b.get("tx", 0) - a.get("tx", 0)


def series(rows, match):
    """[(t, rss_mb)] of the largest process whose command matches."""
    pts = []
    for r in rows:
        v = [p["rss_kb"] for p in r["procs"].values() if match(p["cmd"])]
        pts.append((r["t"], max(v) / 1024 if v else 0))
    return pts


# ------------------------------------------------------------------ GPU samples (nvidia-smi on the host, local time)
def gpu_csv(trace, prefix):
    rows = []
    for l in _read(os.path.join(trace, f"{prefix}_gpu.csv")).splitlines()[1:]:
        v = [x.strip() for x in l.split(",")]
        try:
            t = time.mktime(time.strptime(v[0].split(".")[0], "%Y/%m/%d %H:%M:%S")) + float("0." + v[0].split(".")[1])
            rows.append({"t": t, "util": float(v[1]), "mem": float(v[2]), "power": float(v[3]), "pcie": f"Gen{v[4]} x{v[5]}",
                         "sm_mhz": float(v[6])})
        except (ValueError, IndexError):
            continue
    return rows


def predict_bytes(trace):
    out = []
    for l in _read(os.path.join(trace, "predict_bytes.txt")).splitlines():
        p = l.split(" ", 7)
        if len(p) == 8:
            out.append({"req_headers": int(p[0]), "req_body": int(p[1]), "resp_headers": int(p[2]), "resp_body": int(p[3]),
                        "connect_s": float(p[4]), "ttfb_s": float(p[5]), "total_s": float(p[6]), "body": p[7]})
    return out


def vmstat(trace, prefix):
    """<prefix>_vmstat.txt: '<epoch> MemAvailable: n kB ... pgpgin n pswpin n pswpout n pgmajfault n' every 2 s (VM-wide)."""
    rows = []
    for line in _read(os.path.join(trace, f"{prefix}_vmstat.txt")).splitlines():
        p = line.split()
        if not p:
            continue
        r = {"t": float(p[0])}
        for i, tok in enumerate(p[1:-1], 1):
            key = tok.rstrip(":")
            if p[i + 1].isdigit():
                r[key] = int(p[i + 1])
        rows.append(r)
    return rows


def load(trace):
    t = {"dir": trace, "name": os.path.basename(trace)}
    t["apps"] = event_logs(trace)
    for m in ("svc", "clu"):
        t[m] = {"exe": executor_log(trace, m), "driver": driver_log(trace, m),
                "start": float(_read(os.path.join(trace, f"{m}_job_start.txt")) or 0),
                "end": float(_read(os.path.join(trace, f"{m}_job_end.txt")) or 0),
                "gpu": gpu_csv(trace, m),
                "network": dict(l.split(" ", 1) for l in _read(os.path.join(trace, f"{m}_network.txt")).split("\n") if " " in l)}
    t["svc"]["probes"] = {n: probes(trace, "svc", n) for n in ("spark-master", "spark-worker", "ner-translate-server")}
    t["clu"]["probes"] = {n: probes(trace, "clu", n) for n in ("ner-cluster-master", "ner-cluster-worker")}
    t["clu"]["vmstat"] = vmstat(trace, "clu")
    t["kitchen"] = kitchen_log(trace)
    t["predict"] = predict_bytes(trace)
    sp = os.path.join(trace, "stage_profile.json")
    t["profile"] = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else None
    return t
