#!/usr/bin/env bash
# =============================================================================
# run_campaign.sh - Run the BENCHMARK_TESTS.md phase matrix on one "leg"
# (environment), sized for a small machine (8 GB RAM / 4 GB VRAM laptop).
#
#   LEG=windows  bash benchmark/run_campaign.sh   # native Windows python, Spark local[2]
#   LEG=docker   bash benchmark/run_campaign.sh   # inside the spark-master container (WSL2),
#                                                 # against spark://spark-master:7077
#   LEG=aws_g4dn SPARK_MASTER_URL=spark://<ip>:7077 bash benchmark/run_campaign.sh  # inside the
#                                                 # container on EC2 (deploy/scripts/aws_campaign.sh)
#
# Every run's full stdout/stderr goes to results/campaign_<date>/<leg>/<phase>.log,
# Spark event logs (per-task JVM/Python timing) go to .../<leg>/spark-events/.
# =============================================================================
set -u
LEG="${LEG:-windows}"
STAMP="${STAMP:-$(date +%Y%m%d)}"
ONLY="${ONLY:-}"          # optional regex filter on test names

if [ -d /app/benchmark ]; then     # running inside the multi-model-inference image
    ROOT=/app
    PY=python
    export SPARK_MASTER_URL="${SPARK_MASTER_URL:-spark://spark-master:7077}"
else
    ROOT="$(cd "$(dirname "$0")/.." && pwd)"
    PY=python
    export PYSPARK_PYTHON=python PYSPARK_DRIVER_PYTHON=python
    # local[2] + spark.task.cpus=2 => 1 concurrent task => 1 python worker
    # holding 10 models (local[4] OOMs an 8 GB host).
    export SPARK_MASTER_URL="${SPARK_MASTER_URL:-local[2]}"
fi
export PYTHONIOENCODING=utf-8
OUT="$ROOT/results/campaign_$STAMP/$LEG"
EV="${EVENT_DIR:-$OUT/spark-events}"
mkdir -p "$OUT" "$EV"
EV_URI="file://$EV"; case "$EV" in [A-Za-z]:*) EV_URI="file:///$EV";; esac
# Event logs go through Hadoop's local FS, which on Windows needs winutils.exe
# (HADOOP_HOME) - so they are on by default only for the Linux/docker leg.
if [ "${EVENTLOG:-$([ -d /app/benchmark ] && echo 1 || echo 0)}" = "1" ]; then
    export PYSPARK_SUBMIT_ARGS="--conf spark.eventLog.enabled=true --conf spark.eventLog.dir=$EV_URI pyspark-shell"
fi
cd "$ROOT"

SUMMARY="$OUT/summary.tsv"
[ -f "$SUMMARY" ] || printf "test\texit\tseconds\tcommand\n" > "$SUMMARY"

run() {   # run <name> <args...>
    local name="$1"; shift
    if [ -n "$ONLY" ] && ! echo "$name" | grep -Eq "$ONLY"; then return; fi
    echo ">>> [$LEG] $name : $*"
    local t0=$(date +%s)
    RUN_NAME="${LEG}_$name" timeout 1800 "$PY" "$@" > "$OUT/$name.log" 2>&1
    local rc=$? t1=$(date +%s)
    printf "%s\t%s\t%s\t%s\n" "$name" "$rc" "$((t1 - t0))" "$*" >> "$SUMMARY"
    echo "    exit=$rc  $((t1 - t0))s"
}
RB=benchmark/run_benchmark.py
CB=benchmark/cluster_benchmark.py

# Phase 1 - mode comparison
run p1_modes_small   $RB --mode all --signal-samples 1000 --image-samples 20 --detection-samples 5  --batch-size 64 --partitions 4
run p1_modes_medium  $RB --mode all --signal-samples 5000 --image-samples 50 --detection-samples 10 --batch-size 64 --partitions 4
run p1_dist_large    $RB --mode distributed --signal-samples 10000 --image-samples 100 --detection-samples 20 --batch-size 64 --partitions 8
# Phase 2 - partition scaling
for p in 2 4 8 16; do
  run p2_partitions_$p $RB --mode distributed --signal-samples 5000 --image-samples 50 --detection-samples 10 --batch-size 64 --partitions $p
done
# Phase 3 - data size scaling
run p3_tiny   $RB --mode distributed --signal-samples 500   --image-samples 10 --detection-samples 5  --batch-size 64 --partitions 4
run p3_medium $RB --mode distributed --signal-samples 5000  --image-samples 50 --detection-samples 10 --batch-size 64 --partitions 4
run p3_xlarge $RB --mode distributed --signal-samples 10000 --image-samples 80 --detection-samples 15 --batch-size 64 --partitions 8
# Phase 4 - batch size impact
for bs in 16 64 256 512; do
  run p4_batch_$bs $RB --mode distributed --signal-samples 5000 --image-samples 50 --detection-samples 10 --batch-size $bs --partitions 4
done
# Phase 6/7/10 - cluster engine, all 3 device modes x 2 loads
for m in cpu_only gpu_only hybrid; do
  run p7_${m}_small  $CB --device-mode $m --partitions 2 --signal-samples 1000 --image-samples 50  --detection-samples 20
  run p7_${m}_medium $CB --device-mode $m --partitions 4 --signal-samples 3000 --image-samples 100 --detection-samples 30
done
# Phase 8 - GPU batch size scaling
for bs in 32 128 512; do
  run p8_gpu_batch_$bs $CB --device-mode gpu_only --partitions 2 --signal-samples 3000 --image-samples 50 --detection-samples 20 --batch-size $bs
done
# Engines - RDD vs pandas UDF (Arrow) on the plugin model
for e in rdd udf; do
  for m in cpu_only gpu_only; do
    run eng_${e}_${m} submit_job.py --model example_mlp --engine $e --mode $m --samples 20000 --partitions 4
  done
done
# Spark vs single GPU (fair comparison script)
run svs_single_gpu benchmark/spark_vs_single_gpu.py --signals 3000 --images 50 --detections 20 --batch-size 128

echo "=== done: $SUMMARY ==="
column -t -s $'\t' "$SUMMARY" 2>/dev/null || cat "$SUMMARY"
