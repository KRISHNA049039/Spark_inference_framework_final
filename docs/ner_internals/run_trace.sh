#!/usr/bin/env bash
# Traced NER runs for docs/NER_SPARK_DATA_PATHS_AND_EXECUTION.pdf (Git Bash on Windows).
#   1. service mode job (spark-lean + kitchen) with Spark event log, INFO logs, /proc probes, GPU samples
#   2. direct POST /predict with request/response byte counts
#   3. stage profile of the NER code in the kitchen image (model bytes, tensor shapes, GPU memory)
#   4. cluster mode job (executor loads the models itself), same instrumentation
# Models come from the warm node caches of the air-gap simulation (MODEL_STORE_URI=hdfs://..., cache hit).
set -u
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/../.."
C="docker compose -f deploy/docker-compose.airgap_sim.yml"
T="ner_trace_$(date +%Y%m%d_%H%M%S)"
H="results/$T"; A="/app/results/$T"
mkdir -p "$H/eventlog"
cp docs/ner_internals/probe.py docs/ner_internals/stage_profile.py "$H/"
export MODEL_STORE_URI="hdfs://hdfs-namenode:8020/models/weights"
unset MODEL_FS_DIR
DOCS=$(ls data/ner_samples | sed 's#^#/app/data/ner_samples/#' | tr '\n' ' ')
SUBMIT_ARGS="--conf spark.log.level=INFO --conf spark.eventLog.enabled=true --conf spark.eventLog.dir=file://$A/eventlog --conf spark.eventLog.logStageExecutorMetrics=true --conf spark.executor.processTreeMetrics.enabled=true pyspark-shell"
log() { echo "[$(date +%H:%M:%S)] $*"; }
wait_healthy() { for i in $(seq 1 180); do [ "$(docker inspect -f '{{.State.Health.Status}}' "$1" 2>/dev/null)" = healthy ] && return 0; sleep 5; done; return 1; }
wait_worker() { for i in $(seq 1 60); do curl -s "$1" | grep -Eq '"aliveworkers" ?: ?[1-9]' && return 0; sleep 3; done; return 1; }
gpu_log() { nvidia-smi --query-gpu=timestamp,utilization.gpu,memory.used,power.draw,pcie.link.gen.current,pcie.link.width.current,clocks.sm --format=csv,nounits -lms 500 > "$1" & echo $!; }
netmap() { docker network inspect airgap-sim_default -f '{{range .Containers}}{{.Name}} {{.IPv4Address}}{{"\n"}}{{end}}' > "$1"; }

log "trace dir $H"
docker stop cassandra-web-ui cassandra-database >/dev/null 2>&1 && log "cassandra stopped (memory)"

# ------------------------------------------------------------------ 1. service mode
log "service profile up"
$C --profile service up -d 2>&1 | tail -3
wait_healthy sim-ner-translate-server && log "kitchen healthy" || log "kitchen NOT healthy"
wait_worker http://localhost:8083/json/ && log "worker registered"
netmap "$H/svc_network.txt"
curl -s http://localhost:8083/json/ > "$H/svc_master.json"
for c in sim-spark-master sim-spark-worker sim-ner-translate-server; do
  docker exec -d "$c" python "$A/probe.py" "$A/svc_probe_${c#sim-}.jsonl" 150 1
done
GP=$(gpu_log "$H/svc_gpu.csv")
sleep 2
date +%s.%N > "$H/svc_job_start.txt"
docker exec -e PYSPARK_SUBMIT_ARGS="$SUBMIT_ARGS" sim-spark-master python submit_pipeline_job.py --pipeline ner_translate \
  --input data/ner_samples --partitions 2 --execution-mode service --master spark://ner-translate-master:7077 \
  --driver-memory 1g --executor-memory 512m > "$H/svc_driver.log" 2>&1
rc=$?; date +%s.%N > "$H/svc_job_end.txt"
log "service job exit $rc : $(grep -c 'entities=' "$H/svc_driver.log") documents"
sleep 3; kill "$GP" 2>/dev/null
docker cp sim-spark-worker:/opt/spark/work "$H/svc_work" >/dev/null
docker cp sim-spark-worker:/opt/spark/logs "$H/svc_worker_logs" >/dev/null
docker cp sim-spark-master:/opt/spark/logs "$H/svc_master_logs" >/dev/null
docker logs --timestamps sim-ner-translate-server > "$H/svc_kitchen.log" 2>&1

# ------------------------------------------------------------------ 2. direct /predict
log "direct /predict"
for body in '{"paths":["/app/data/ner_samples/sample_text3.txt"]}' \
            '{"paths":["/app/data/ner_samples/sample_scan6.png","/app/data/ner_samples/sample_text1.txt","/app/data/ner_samples/sample_text2.txt"]}' \
            '{"paths":["/app/data/ner_samples/sample_text3.txt","/app/data/ner_samples/sample_text4.txt","/app/data/ner_samples/sample_text5.txt"]}'; do
  curl -s -o "$H/predict_resp.json" -H 'Content-Type: application/json' -d "$body" \
       -w "%{size_request} %{size_upload} %{size_header} %{size_download} %{time_connect} %{time_starttransfer} %{time_total} $body\n" \
       http://localhost:8001/predict >> "$H/predict_bytes.txt"
done
cat "$H/predict_bytes.txt"
$C --profile service down 2>&1 | tail -1

# ------------------------------------------------------------------ 3. stage profile
log "stage profile"
$C --profile service run --rm --no-deps --entrypoint python ner-translate-server "$A/stage_profile.py" "$A/stage_profile.json" $DOCS \
  > "$H/stage_profile.log" 2>&1
log "stage profile exit $?"; tail -4 "$H/stage_profile.log"

# ------------------------------------------------------------------ 4. cluster mode
log "cluster profile up"
$C --profile cluster up -d 2>&1 | tail -2
wait_worker http://localhost:8084/json/ && log "worker registered"
netmap "$H/clu_network.txt"
curl -s http://localhost:8084/json/ > "$H/clu_master.json"
docker exec -d sim-ner-cluster-master python "$A/probe.py" "$A/clu_probe_ner-cluster-master.jsonl" 900 5
docker exec -d sim-ner-cluster-worker python "$A/probe.py" "$A/clu_probe_ner-cluster-worker.jsonl" 900 2
GP=$(gpu_log "$H/clu_gpu.csv")
sleep 2
date +%s.%N > "$H/clu_job_start.txt"
docker exec -e PYSPARK_SUBMIT_ARGS="$SUBMIT_ARGS" sim-ner-cluster-master python submit_pipeline_job.py --pipeline ner_translate \
  --input data/ner_samples --partitions 1 --execution-mode cluster --master spark://ner-cluster-master:7077 \
  --driver-memory 1g --executor-memory 4g > "$H/clu_driver.log" 2>&1
rc=$?; date +%s.%N > "$H/clu_job_end.txt"
log "cluster job exit $rc : $(grep -c 'entities=' "$H/clu_driver.log") documents"
sleep 3; kill "$GP" 2>/dev/null
docker cp sim-ner-cluster-worker:/opt/spark/work "$H/clu_work" >/dev/null
docker cp sim-ner-cluster-worker:/opt/spark/logs "$H/clu_worker_logs" >/dev/null
docker cp sim-ner-cluster-master:/opt/spark/logs "$H/clu_master_logs" >/dev/null
$C --profile cluster down 2>&1 | tail -1

docker start cassandra-database cassandra-web-ui >/dev/null 2>&1 && log "cassandra restarted"
log "done $H"
