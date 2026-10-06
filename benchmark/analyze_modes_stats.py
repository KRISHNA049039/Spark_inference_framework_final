"""
analyze_modes_stats.py - Turn the output of spark_modes_stats.py (event logs,
executor stdout/stderr, Triton metrics, GPU/CPU monitors) into statistics at
every level Spark has: application, job, stage, executor/worker, task.

  python benchmark/analyze_modes_stats.py results/modes_20260926/aws_2node

Writes into that directory:
  modes_summary.json   everything below, per application
  modes_summary.md     human-readable tables
  gantt/<app>.png      task placement timeline (one row per executor task slot)
"""
import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

ROOT = sys.argv[1] if len(sys.argv) > 1 else "results/modes_20260926/aws_2node"


def load_results():
    recs = []
    p = os.path.join(ROOT, "results.jsonl")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            if line.strip():
                recs.append(json.loads(line))
    return recs


# ------------------------------------------------------------------ event logs
def parse_eventlog(path):
    app = {"file": os.path.basename(path), "jobs": {}, "stages": {}, "tasks": [], "executors": {}}
    for line in open(path, encoding="utf-8"):
        e = json.loads(line)
        ev = e.get("Event", "")
        if ev == "SparkListenerApplicationStart":
            app.update(name=e["App Name"], app_id=e.get("App ID"), start=e["Timestamp"])
        elif ev == "SparkListenerApplicationEnd":
            app["end"] = e["Timestamp"]
        elif ev == "SparkListenerExecutorAdded":
            info = e["Executor Info"]
            app["executors"][e["Executor ID"]] = {"id": e["Executor ID"], "host": info["Host"],
                                                  "cores": info["Total Cores"], "added": e["Timestamp"],
                                                  "resources": {k: v.get("addresses") for k, v in (info.get("Resources") or {}).items()}}
        elif ev == "SparkListenerExecutorRemoved":
            if e["Executor ID"] in app["executors"]:
                app["executors"][e["Executor ID"]]["removed"] = e["Timestamp"]
                app["executors"][e["Executor ID"]]["removed_reason"] = e.get("Removed Reason")
        elif ev == "SparkListenerJobStart":
            app["jobs"][e["Job ID"]] = {"id": e["Job ID"], "submit": e["Submission Time"],
                                        "stage_ids": e["Stage IDs"],
                                        "desc": (e.get("Properties") or {}).get("spark.job.description", "")}
        elif ev == "SparkListenerJobEnd":
            j = app["jobs"].setdefault(e["Job ID"], {"id": e["Job ID"]})
            j["end"] = e["Completion Time"]
            j["result"] = e["Job Result"]["Result"]
        elif ev == "SparkListenerStageCompleted":
            si = e["Stage Info"]
            acc = {a["Name"]: a.get("Value") for a in si.get("Accumulables", [])}
            app["stages"][si["Stage ID"]] = {
                "id": si["Stage ID"], "attempt": si["Stage Attempt ID"], "name": si["Stage Name"][:80],
                "tasks": si["Number of Tasks"], "submit": si.get("Submission Time"), "done": si.get("Completion Time"),
                "rdd_names": [r["Name"] for r in si.get("RDD Info", [])][:6],
                "shuffle_write_bytes": acc.get("internal.metrics.shuffle.write.bytesWritten", 0),
                "shuffle_read_bytes": (acc.get("internal.metrics.shuffle.read.remoteBytesRead", 0) or 0)
                                      + (acc.get("internal.metrics.shuffle.read.localBytesRead", 0) or 0),
                "failure": si.get("Failure Reason"),
            }
        elif ev == "SparkListenerTaskEnd":
            ti, tm = e["Task Info"], e.get("Task Metrics") or {}
            sr, sw = tm.get("Shuffle Read Metrics") or {}, tm.get("Shuffle Write Metrics") or {}
            app["tasks"].append({
                "stage": e["Stage ID"], "task": ti["Task ID"], "index": ti["Index"], "attempt": ti["Attempt"],
                "executor": ti["Executor ID"], "host": ti["Host"], "locality": ti["Locality"],
                "launch": ti["Launch Time"], "finish": ti["Finish Time"],
                "getting_result": ti.get("Getting Result Time", 0),
                "failed": ti.get("Failed", False), "reason": e.get("Task End Reason", {}).get("Reason"),
                "deser_ms": tm.get("Executor Deserialize Time", 0),
                "deser_cpu_ms": (tm.get("Executor Deserialize CPU Time", 0) or 0) / 1e6,
                "run_ms": tm.get("Executor Run Time", 0), "cpu_ms": (tm.get("Executor CPU Time", 0) or 0) / 1e6,
                "gc_ms": tm.get("JVM GC Time", 0), "result_bytes": tm.get("Result Size", 0),
                "result_ser_ms": tm.get("Result Serialization Time", 0),
                "peak_mem": tm.get("Peak Execution Memory", 0),
                "shuffle_read_bytes": (sr.get("Remote Bytes Read", 0) or 0) + (sr.get("Local Bytes Read", 0) or 0),
                "shuffle_remote_bytes": sr.get("Remote Bytes Read", 0) or 0,
                "shuffle_fetch_wait_ms": sr.get("Fetch Wait Time", 0) or 0,
                "shuffle_write_bytes": sw.get("Shuffle Bytes Written", 0) or 0,
                "records_in": (tm.get("Input Metrics") or {}).get("Records Read", 0),
                "shuffle_records_read": sr.get("Total Records Read", 0) or 0,
            })
    return app


# ------------------------------------------------------------------ executor logs
MARK_NATIVE = re.compile(r"\[MODEL_LOAD\] app=(\S+) host=(\S+) pid=(\d+) device=(\S+) secs=([\d.]+)")
MARK_RDD = re.compile(r"\[Executor\] host=([^,]+), pid=(\d+), device=(\w+), cuda=(\w+), models_loaded=(\d+), model_load_time=([\d.]+)s")


def executor_logs(app_id):
    """Scan worker work dirs (both nodes) for this application's executor logs."""
    loads = []
    for d in glob.glob(os.path.join(ROOT, "*_node", "work", "**", app_id, "*"), recursive=True):
        node = os.path.relpath(d, ROOT).split(os.sep)[0]
        for fn in ("stdout", "stderr"):
            p = os.path.join(d, fn)
            if not os.path.exists(p):
                continue
            txt = open(p, encoding="utf-8", errors="replace").read()
            for m in MARK_NATIVE.finditer(txt):
                loads.append({"node": node, "executor": os.path.basename(d), "host": m.group(2), "pid": int(m.group(3)),
                              "device": m.group(4), "secs": float(m.group(5)), "kind": "predict_batch_udf make_predict_fn"})
            for m in MARK_RDD.finditer(txt):
                loads.append({"node": node, "executor": os.path.basename(d), "host": m.group(1), "pid": int(m.group(2)),
                              "device": m.group(3), "secs": float(m.group(6)), "models": int(m.group(5)),
                              "kind": "mapPartitions model load"})
    return loads


def driver_log_loads(app):
    """local[N] runs: executor output lands in the driver log."""
    p = os.path.join(ROOT, "logs", f"{app}.log")
    loads = []
    if os.path.exists(p):
        txt = open(p, encoding="utf-8", errors="replace").read()
        for m in MARK_NATIVE.finditer(txt):
            loads.append({"host": m.group(2), "pid": int(m.group(3)), "device": m.group(4), "secs": float(m.group(5)),
                          "kind": "predict_batch_udf make_predict_fn"})
        for m in MARK_RDD.finditer(txt):
            loads.append({"host": m.group(1), "pid": int(m.group(2)), "device": m.group(3), "secs": float(m.group(6)),
                          "models": int(m.group(5)), "kind": "mapPartitions model load"})
    return loads


# ------------------------------------------------------------------ triton / monitors
def prom(path):
    vals = {}
    if not path or not os.path.exists(path):
        return vals
    for line in open(path, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        m = re.match(r'(\w+)\{([^}]*)\}\s+([\d.eE+-]+)', line)
        if m:
            labels = dict(re.findall(r'(\w+)="([^"]*)"', m.group(2)))
            vals[(m.group(1), labels.get("model", ""))] = float(m.group(3))
    return vals


def triton_delta(rec):
    b, a = prom(os.path.join(ROOT, rec.get("triton_before", "") or "_")), prom(os.path.join(ROOT, rec.get("triton_after", "") or "_"))
    model = rec.get("model")
    d = {k[0]: a[k] - b.get(k, 0) for k in a if k[1] == model}
    if not d:
        return {}
    ex, inf = d.get("nv_inference_exec_count", 0), d.get("nv_inference_count", 0)
    req = d.get("nv_inference_request_success", 0)
    return {"requests": req, "inferences": inf, "executions": ex,
            "avg_client_batch": inf / req if req else None,
            "avg_executed_batch": inf / ex if ex else None,
            "avg_request_us": d.get("nv_inference_request_duration_us", 0) / req if req else None,
            "avg_queue_us": d.get("nv_inference_queue_duration_us", 0) / req if req else None,
            "avg_compute_input_us": d.get("nv_inference_compute_input_duration_us", 0) / req if req else None,
            "avg_compute_infer_us": d.get("nv_inference_compute_infer_duration_us", 0) / req if req else None,
            "avg_compute_output_us": d.get("nv_inference_compute_output_duration_us", 0) / req if req else None}


def load_dmon():
    rows = []
    p = os.path.join(ROOT, "gpu_node", "gpu_dmon.log")
    if not os.path.exists(p):
        return rows
    cols = None
    for line in open(p, encoding="utf-8", errors="replace"):
        if line.startswith("#"):
            if "gpu" in line and cols is None:
                cols = line.lstrip("#").split()
            continue
        parts = line.split()
        if not cols or len(parts) != len(cols):
            continue
        r = dict(zip(cols, parts))
        try:
            ts = datetime.strptime(r["Date"] + r["Time"], "%Y%m%d%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
            rows.append({"t": ts, "sm": float(r.get("sm", "nan").replace("-", "nan")),
                         "mem": float(r.get("mem", "nan").replace("-", "nan")),
                         "pwr": float(r.get("pwr", "nan").replace("-", "nan")),
                         "fb": float(r.get("fb", "nan").replace("-", "nan"))})
        except Exception:
            pass
    return rows


def window_stats(rows, t0, t1, key):
    v = [r[key] for r in rows if t0 <= r["t"] <= t1 and r[key] == r[key]]
    if not v:
        return None
    return {"avg": sum(v) / len(v), "max": max(v), "samples": len(v)}


def stage_kind(s):
    if (s.get("shuffle_write_bytes") or 0) > 0:
        return "shuffle map (repartition -> shuffle write)"
    if (s.get("shuffle_read_bytes") or 0) > 0:
        return "shuffle read -> Python UDF -> collect"
    return "map (Python) -> collect"


# ------------------------------------------------------------------ gantt
def gantt(app, out_png, title):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:  # timelines are optional; statistics are still written
        if not getattr(gantt, "_warned", False):
            print("[analyze_modes_stats] Pillow not installed - skipping gantt/*.png "
                  "(pip install pillow to get the task timelines)")
            gantt._warned = True
        return
    tasks = [t for t in app["tasks"]]
    if not tasks:
        return
    t0 = min(t["launch"] for t in tasks)
    t1 = max(t["finish"] for t in tasks)
    # assign each task to a slot row inside its executor (greedy interval packing)
    slots = defaultdict(list)  # executor -> [end time of each slot]
    rows = []
    for t in sorted(tasks, key=lambda x: x["launch"]):
        ends = slots[t["executor"]]
        # finish is logged a few ms after the slot's next launch -> small tolerance
        idx = next((i for i, e in enumerate(ends) if e <= t["launch"] + 150), None)
        if idx is None:
            ends.append(t["finish"])
            idx = len(ends) - 1
        else:
            ends[idx] = t["finish"]
        rows.append((t["executor"], idx, t))
    keys = sorted({(e, i) for e, i, _ in rows}, key=lambda k: (str(k[0]), k[1]))
    K = 2  # render at 2x for sharp embedding
    W, left, top, rh = 1400 * K, 260 * K, 60 * K, 30 * K
    H = top + rh * len(keys) + 70 * K
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("arial.ttf", 15 * K)
        fb = ImageFont.truetype("arialbd.ttf", 17 * K)
        fs = ImageFont.truetype("arial.ttf", 12 * K)
    except Exception:
        f = fb = fs = ImageFont.load_default()
    d.text((20 * K, 15 * K), title, fill="#1b1f24", font=fb)
    span = max(1, t1 - t0)
    scale = (W - left - 30 * K) / span
    palette = ["#0b5cad", "#d97706", "#15803d", "#7c3aed", "#be123c", "#0e7490"]
    stage_ids = sorted({t["stage"] for t in tasks})
    ex_host = {k: v["host"] for k, v in app["executors"].items()}
    for i, (ex, slot) in enumerate(keys):
        y = top + i * rh
        if i % 2 == 0:
            d.rectangle([left, y, W - 30 * K, y + rh], fill="#f6f8fa")
        d.text((20 * K, y + 7 * K), f"exec {ex} @ {ex_host.get(ex, '?')}  slot {slot}", fill="#1b1f24", font=f)
    for ex, slot, t in rows:
        y = top + keys.index((ex, slot)) * rh
        x0, x1 = left + (t["launch"] - t0) * scale, left + (t["finish"] - t0) * scale
        col = palette[stage_ids.index(t["stage"]) % len(palette)]
        d.rectangle([x0, y + 4 * K, max(x0 + 2 * K, x1), y + rh - 4 * K], fill=col, outline="white")
        lab = f"s{t['stage']}.{t['index']}"
        if x1 - x0 > 38 * K:
            d.text((x0 + 4 * K, y + 8 * K), lab, fill="white", font=fs)
    ya = top + rh * len(keys) + 8 * K
    d.line([left, ya, W - 30 * K, ya], fill="#57606a", width=K)
    for k in range(0, 11):
        x = left + (W - left - 30 * K) * k / 10
        d.line([x, ya, x, ya + 5 * K], fill="#57606a", width=K)
        d.text((x - 12 * K, ya + 8 * K), f"{span * k / 10 / 1000:.1f}s", fill="#57606a", font=fs)
    x = left
    for s in stage_ids:
        col = palette[stage_ids.index(s) % len(palette)]
        d.rectangle([x, H - 22 * K, x + 14 * K, H - 10 * K], fill=col)
        nm = stage_kind(app["stages"].get(s, {}))
        d.text((x + 20 * K, H - 24 * K), f"stage {s}: {nm}", fill="#1b1f24", font=fs)
        x += 360 * K
    img.save(out_png)


# ------------------------------------------------------------------ main
def main():
    loaded = load_results()
    recs = {r["app"]: r for r in loaded}
    recs_by_id = {r["app_id"]: r for r in loaded if r.get("app_id")}
    host_device = {}
    for ms in glob.glob(os.path.join(ROOT, "master_state_*.json")):
        try:
            for w in json.load(open(ms)).get("workers", []):
                host_device[w["host"]] = "gpu" if w.get("resources", {}).get("gpu") else "cpu"
        except Exception:
            pass
    dmon = load_dmon()
    os.makedirs(os.path.join(ROOT, "gantt"), exist_ok=True)
    summary = []
    for ev in sorted(glob.glob(os.path.join(ROOT, "spark-events", "*"))):
        if ev.endswith(".inprogress"):
            continue
        app = parse_eventlog(ev)
        rec = recs_by_id.get(app.get("app_id")) or recs.get(app.get("name", ""), {})
        name = rec.get("app") or app.get("name", "")
        ok_tasks = [t for t in app["tasks"] if not t["failed"]]
        per_exec = defaultdict(lambda: defaultdict(float))
        for t in ok_tasks:
            pe = per_exec[t["executor"]]
            pe["tasks"] += 1
            for k in ("run_ms", "cpu_ms", "deser_ms", "gc_ms", "result_bytes", "shuffle_read_bytes", "shuffle_write_bytes",
                      "shuffle_remote_bytes", "shuffle_fetch_wait_ms"):
                pe[k] += t[k]
            pe["max_task_ms"] = max(pe["max_task_ms"], t["finish"] - t["launch"])
            pe["busy_ms"] += t["finish"] - t["launch"]
        execs = []
        for eid, info in sorted(app["executors"].items(), key=lambda kv: kv[0]):
            pe = per_exec.get(eid, {})
            execs.append({**info, "device": host_device.get(info["host"], "gpu" if info.get("resources", {}).get("gpu") else "?"),
                          **{k: round(v, 1) for k, v in pe.items()}})
        stages = []
        for sid, s in sorted(app["stages"].items()):
            ts = [t for t in ok_tasks if t["stage"] == sid]
            durs = sorted(t["finish"] - t["launch"] for t in ts)
            stages.append({**s, "kind": stage_kind(s), "duration_ms": (s["done"] or 0) - (s["submit"] or 0),
                           "task_ms_min": durs[0] if durs else None,
                           "task_ms_median": durs[len(durs) // 2] if durs else None,
                           "task_ms_max": durs[-1] if durs else None,
                           "tasks_by_executor": {e: sum(1 for t in ts if t["executor"] == e) for e in {t["executor"] for t in ts}}})
        jobs = [{**j, "duration_ms": (j.get("end") or 0) - (j.get("submit") or 0)} for j in sorted(app["jobs"].values(), key=lambda x: x["id"])]
        loads = executor_logs(app.get("app_id", "")) or driver_log_loads(name)
        parts = rec.get("partition_details") or []
        t_start, t_end = rec.get("start_epoch"), rec.get("end_epoch")
        item = {
            "app": name, "app_id": app.get("app_id"), "mode": rec.get("mode"), "model": rec.get("model"),
            "samples": rec.get("samples"), "processed": rec.get("processed"), "wall_s": rec.get("wall_s"),
            "throughput": rec.get("throughput"), "batch_size": rec.get("batch_size"), "partitions": rec.get("partitions"),
            "app_duration_ms": (app.get("end") or 0) - (app.get("start") or 0),
            "executors": execs, "jobs": jobs, "stages": stages, "tasks": ok_tasks,
            "failed_tasks": [t for t in app["tasks"] if t["failed"]],
            "model_loads": loads,
            "partition_details": [{k: p.get(k) for k in ("partition_idx", "hostname", "device", "model_load_time_sec",
                                                          "inference_time_sec", "samples_processed")} for p in parts],
            "triton": triton_delta(rec) if rec.get("mode") == "triton_pbu" else {},
            "gpu_util": window_stats(dmon, t_start, t_end, "sm") if (dmon and t_start) else None,
            "gpu_mem_util": window_stats(dmon, t_start, t_end, "mem") if (dmon and t_start) else None,
            "gpu_fb_mb": window_stats(dmon, t_start, t_end, "fb") if (dmon and t_start) else None,
            "error": rec.get("error"),
        }
        summary.append(item)
        gantt(app, os.path.join(ROOT, "gantt", f"{name}.png"),
              f"{name}  -  {len(ok_tasks)} tasks, {len(app['executors'])} executors, "
              f"{rec.get('throughput', '?')} samples/s")
    order = ["rdd_cpu", "rdd_gpu", "rdd_hybrid", "rdd_gpu_aware", "udf_cpu", "udf_gpu", "native_pbu_cpu",
             "native_pbu_gpu", "triton_pbu", "platform10_cpu", "platform10_gpu", "platform10_hybrid"]
    summary.sort(key=lambda s: (s["model"] or "", order.index(s["mode"]) if s["mode"] in order else 99))
    json.dump(summary, open(os.path.join(ROOT, "modes_summary.json"), "w"), indent=1, default=str)

    md = ["# Spark execution modes - statistics", "",
          "| model | mode | samples/s | wall s | jobs | stages | tasks | executors (host: tasks) | model loads | GPU SM % avg |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for s in summary:
        ex = "; ".join(f"{e['host']}:{int(e.get('tasks', 0))}" for e in s["executors"])
        gu = f"{s['gpu_util']['avg']:.0f}" if s.get("gpu_util") else "-"
        md.append(f"| {s['model']} | {s['mode']} | {s['throughput']} | {s['wall_s']} | {len(s['jobs'])} | {len(s['stages'])} | "
                  f"{len(s['tasks'])} | {ex} | {len(s['model_loads'])} | {gu} |")
    open(os.path.join(ROOT, "modes_summary.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
