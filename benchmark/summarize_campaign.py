"""
summarize_campaign.py - Parse every run log of a campaign (all legs) into one
table: status (OK / FAIL + root cause, independent of exit code - many scripts
catch Spark errors and still exit 0), throughput, elapsed time, device.

  python benchmark/summarize_campaign.py results/campaign_20260926
Writes <campaign>/summary.md and <campaign>/summary.json
"""
import json
import os
import re
import sys

FAIL_PATTERNS = [
    (r"paging file is too small", "host commit limit (JVM mmap failed)"),
    (r"CUDA error: out of memory|CUDA out of memory", "GPU out of memory"),
    (r"not enough memory|DefaultCPUAllocator", "host RAM (torch CPU allocator)"),
    (r"Memory allocation failure", "host RAM during CUDA JIT"),
    (r"CUDA error: unknown error", "CUDA unknown error"),
    (r"Container killed|exit code 137|OutOfMemoryError|Killed", "container/JVM OOM kill"),
    (r"HADOOP_HOME and hadoop.home.dir are unset.*\n.*JavaSparkContext", "winutils missing"),
    (r"actively refused|Connection reset|forcibly closed|Py4JNetworkError", "JVM died (Py4J connection lost)"),
    (r"unexpected pos \d+ vs \d+", "torch.load of truncated model bytes"),
    (r"Initial job has not accepted any resources", "no executor resources"),
]


def parse(path):
    txt = open(path, encoding="utf-8", errors="replace").read()
    r = {"test": os.path.basename(path)[:-4]}
    thr = [float(x.replace(",", "")) for x in re.findall(r"Total Throughput\s*:\s*([\d,\.]+)", txt)]
    thr += [float(x.replace(",", "")) for x in re.findall(r"► Throughput\s*:\s*([\d,\.]+)", txt)]
    modes = {}
    for m, v in re.findall(r"\[MODE \d\] ([^\n]+?)\.\.\.\n(?:.*\n){0,25}?\s+Throughput: ([\d,]+)", txt):
        modes[m.split("—")[0].strip()] = float(v.replace(",", ""))
    if thr:
        modes["Spark distributed"] = thr[-1]
    js = re.findall(r'"total_throughput":\s*([\d\.]+)', txt)
    if js and not modes:
        modes["Spark job"] = float(js[-1])
    for cfg, v, t in re.findall(r"^\s+(\w+)\s+([\d,]+)/s\s+([\d\.]+)s", txt, re.M):
        modes[cfg] = float(v.replace(",", ""))
    r["throughput"] = modes
    el = re.findall(r"Elapsed Time\s*:\s*([\d\.]+)", txt) or re.findall(r'"elapsed_time":\s*([\d\.]+)', txt)
    r["elapsed_s"] = float(el[-1]) if el else None
    dev = re.findall(r"^\s*\d+\s+\S+\s+(cuda|cpu)\s", txt, re.M)
    r["devices"] = sorted(set(dev))
    reasons = [label for pat, label in FAIL_PATTERNS if re.search(pat, txt)]
    spark_failed = bool(re.search(r"\[ERROR\] Spark mode failed|PythonException|Py4JJavaError|Traceback \(most recent", txt))
    has_result = bool(modes)
    if spark_failed and not has_result:
        r["status"] = "FAIL"
    elif spark_failed and not thr and not js:
        r["status"] = "PARTIAL"     # single/hybrid (or single-GPU configs) ran, the Spark part failed
    elif spark_failed:
        r["status"] = "PARTIAL"
    else:
        r["status"] = "OK" if has_result else "FAIL"
    r["reason"] = reasons[0] if (reasons and r["status"] != "OK") else ""
    return r


def main(root):
    legs = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    out = {}
    for leg in legs:
        d = os.path.join(root, leg)
        logs = sorted(f for f in os.listdir(d) if f.endswith(".log") and f[:2] in ("p1", "p2", "p3", "p4", "p5", "p7", "p8", "en", "sv"))
        out[leg] = [parse(os.path.join(d, f)) for f in logs]
    lines = ["# Campaign summary", ""]
    tests = sorted({r["test"] for rs in out.values() for r in rs})
    lines.append("| test | " + " | ".join(legs) + " |")
    lines.append("|---|" + "---|" * len(legs))
    for t in tests:
        cells = []
        for leg in legs:
            r = next((x for x in out[leg] if x["test"] == t), None)
            if not r:
                cells.append("-")
                continue
            thr = ", ".join(f"{k.split()[0]} {v:,.0f}/s" for k, v in r["throughput"].items())
            cell = f"**{r['status']}** {thr}"
            if r["reason"]:
                cell += f" _({r['reason']})_"
            cells.append(cell)
        lines.append(f"| {t} | " + " | ".join(cells) + " |")
    open(os.path.join(root, "summary.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    json.dump(out, open(os.path.join(root, "summary.json"), "w"), indent=1)
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results/campaign_20260926")
