"""
modes_from_campaign.py - re-shape the single-node AWS campaign run
(results/campaign_20260926/aws_g4dn: master + GPU-worker containers on one
g4dn.xlarge) into the layout analyze_modes_stats.py expects, so its Spark
event logs and executor logs get the same worker / task statistics as the
2-node modes run.

  python benchmark/modes_from_campaign.py [campaign_leg_dir] [out_dir]
"""
import glob
import json
import os
import re
import shutil
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "results/campaign_20260926/aws_g4dn"
OUT = sys.argv[2] if len(sys.argv) > 2 else "results/modes_20260926/aws_1node"

# campaign test (in run order == event-log order) -> (model label, mode, samples, partitions, batch)
MAP = {
    "p2_partitions_2": ("platform10_5k", "dist_p2", 25170, 2, 64),
    "p2_partitions_4": ("platform10_5k", "dist_p4", 25170, 4, 64),
    "p2_partitions_8": ("platform10_5k", "dist_p8", 25170, 8, 64),
    "p2_partitions_16": ("platform10_5k", "dist_p16", 25170, 16, 64),
    "p7_cpu_only_small": ("platform10_1k", "rdd_cpu", 5190, 2, 256),
    "p7_cpu_only_medium": ("platform10_3k", "rdd_cpu", 15360, 4, 256),
    "p7_gpu_only_small": ("platform10_1k", "rdd_gpu", 5190, 2, 256),
    "p7_gpu_only_medium": ("platform10_3k", "rdd_gpu", 15360, 4, 256),
    "p7_hybrid_small": ("platform10_1k", "rdd_hybrid", 5190, 2, 256),
    "p7_hybrid_medium": ("platform10_3k", "rdd_hybrid", 15360, 4, 256),
    "eng_rdd_cpu_only": ("example_mlp", "rdd_cpu", 20000, 4, 256),
    "eng_rdd_gpu_only": ("example_mlp", "rdd_gpu", 20000, 4, 256),
    "eng_udf_cpu_only": ("example_mlp", "udf_cpu", 20000, 4, 256),
    "eng_udf_gpu_only": ("example_mlp", "udf_gpu", 20000, 4, 256),
}
PART_CB = re.compile(r"^\s+(\d+)\s+(\S+)\s+(cuda|cpu)\s+(\d+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*$", re.M)
PART_RB = re.compile(r"^\s+(\d+)\s+(\S+)\s+(cuda|cpu)\s+.*?\s([\d.]+)\s+([\d.]+)\s+(\d+)\s*$", re.M)


def main():
    tests = [l.split("\t")[0] for l in open(os.path.join(SRC, "summary.tsv")).read().splitlines()[1:]]
    evs = sorted(glob.glob(os.path.join(SRC, "spark-events", "app-*")))
    camp = {r["test"]: r for r in json.load(open(os.path.join(os.path.dirname(SRC), "summary.json")))[os.path.basename(SRC)]}
    for d in ("spark-events", "gpu_node/work", "logs"):
        os.makedirs(os.path.join(OUT, d), exist_ok=True)
    json.dump({"workers": [{"host": "10.0.0.240", "cores": 4, "resources": {"gpu": {"name": "gpu", "addresses": ["0"]}}}]},
              open(os.path.join(OUT, "master_state_before.json"), "w"))
    out = open(os.path.join(OUT, "results.jsonl"), "w")
    for test, ev in zip(tests, evs):
        if test not in MAP:
            continue
        model, mode, n, parts, bs = MAP[test]
        app_id = os.path.basename(ev)
        shutil.copy(ev, os.path.join(OUT, "spark-events", app_id))
        wd = os.path.join(SRC, "spark-worker-work", app_id)
        if os.path.isdir(wd):
            shutil.copytree(wd, os.path.join(OUT, "gpu_node", "work", app_id), dirs_exist_ok=True)
        log = open(os.path.join(SRC, f"{test}.log"), encoding="utf-8", errors="replace").read()
        shutil.copy(os.path.join(SRC, f"{test}.log"), os.path.join(OUT, "logs", f"modes-{model}-{mode}.log"))
        c = camp.get(test, {})
        thr = next(iter(c.get("throughput", {}).values()), None)
        details = []
        if mode.startswith("dist"):
            for m in PART_RB.finditer(log):
                details.append({"partition_idx": int(m.group(1)), "hostname": m.group(2), "device": m.group(3),
                                "model_load_time_sec": float(m.group(4)), "inference_time_sec": float(m.group(5)),
                                "samples_processed": int(m.group(6))})
        elif mode.startswith("rdd"):
            for m in PART_CB.finditer(log):
                details.append({"partition_idx": int(m.group(1)), "hostname": m.group(2), "device": m.group(3),
                                "samples_processed": int(m.group(4)), "model_load_time_sec": float(m.group(5)),
                                "inference_time_sec": float(m.group(6))})
        rec = {"app": f"modes-{model}-{mode}", "app_id": app_id, "mode": mode, "model": model, "samples": n,
               "processed": n, "partitions": parts, "batch_size": bs, "wall_s": c.get("elapsed_s"),
               "throughput": thr, "partition_details": details, "source_test": test}
        out.write(json.dumps(rec) + "\n")
        print(f"{test:22s} -> {rec['app']:36s} {app_id}  {thr}")
    out.close()


if __name__ == "__main__":
    main()
