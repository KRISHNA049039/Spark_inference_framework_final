#!/bin/bash
# =============================================================================
# modes_node.sh - per-node steps for SparkModesClusterStack, executed over SSM
# by deploy/run_aws_modes.ps1.
#
#   modes_node.sh prepare <cpu|gpu>                 unzip code, build image (+ pull Triton)
#   modes_node.sh start   <cpu|gpu> <cpu_ip> <gpu_ip>  start Spark (+ Triton) and monitors
#   modes_node.sh run     cpu <cpu_ip> <gpu_ip>     run benchmark/spark_modes_stats.py
#   modes_node.sh collect <cpu|gpu>                 gather logs and sync to S3
# Log: /opt/modes/<step>.log
# =============================================================================
set +e
STEP=$1; ROLE=$2; CPU_IP=$3; GPU_IP=$4
mkdir -p /opt/modes
exec > >(tee -a /opt/modes/$STEP.log) 2>&1
cloud-init status --wait >/dev/null 2>&1 || true
source /etc/environment
REGION=${AWS_DEFAULT_REGION:-us-east-1}
[ -z "$BUCKET" ] && { echo "FATAL: BUCKET not set"; exit 1; }
APP=/opt/modes/app
OUT_REL=results/modes_20260926/aws_2node
IMG=multi-model-inference:latest
MOUNTS="-v $APP/results:/app/results -v $APP/benchmark:/app/benchmark -v $APP/inference:/app/inference \
 -v $APP/models:/app/models -v $APP/data:/app/data -v $APP/deploy:/app/deploy"
echo "=== $STEP $ROLE $(date) ==="

case "$STEP" in
prepare)
    aws s3 cp s3://$BUCKET/project.zip /opt/modes/project.zip --region $REGION || { echo "FATAL: download"; exit 1; }
    rm -rf $APP && mkdir -p $APP && unzip -oq /opt/modes/project.zip -d $APP
    find $APP -name "*.sh" -exec sed -i 's/\r$//' {} \; -exec chmod +x {} \;
    mkdir -p $APP/results/modes_20260926/aws_2node
    nvidia-smi -L 2>/dev/null; lscpu | grep -E "Model name|^CPU\(s\)"; free -g | head -2
    cd $APP && docker build --network host --target final -t $IMG -f deploy/Dockerfile . > /opt/modes/build.log 2>&1 \
        || { tail -30 /opt/modes/build.log; echo "FATAL: build"; exit 1; }
    if [ "$ROLE" = gpu ]; then
        for tag in 25.01-py3 24.12-py3 24.10-py3; do
            docker pull -q nvcr.io/nvidia/tritonserver:$tag && { echo "nvcr.io/nvidia/tritonserver:$tag" > /opt/modes/triton_image; break; }
        done
        [ -s /opt/modes/triton_image ] || { echo "FATAL: triton pull"; exit 1; }
    fi
    echo "PREPARED $ROLE"
    ;;

start)
    if [ "$ROLE" = cpu ]; then
        mkdir -p /opt/modes/work-cpu
        docker rm -f spark-master spark-cpu-worker 2>/dev/null
        docker run -d --name spark-master --network host -e SPARK_LOCAL_IP=$CPU_IP $MOUNTS $IMG \
            bash -c "pip install -q 'tritonclient[grpc]'; start-master.sh -h $CPU_IP && tail -f /opt/spark/logs/*master*"
        for i in $(seq 1 60); do curl -sf http://$CPU_IP:8080/json/ >/dev/null && break; sleep 5; done
        docker run -d --name spark-cpu-worker --network host -e SPARK_LOCAL_IP=$CPU_IP -e CUDA_VISIBLE_DEVICES= \
            $MOUNTS -v /opt/modes/work-cpu:/opt/spark/work $IMG \
            bash -c "pip install -q 'tritonclient[grpc]'; start-worker.sh spark://$CPU_IP:7077 -c 4 -m 12g && tail -f /opt/spark/logs/*worker*"
        nohup vmstat -t 2 > /opt/modes/vmstat_cpu.log 2>&1 &
    else
        mkdir -p /opt/modes/work-gpu /opt/modes/triton_models
        docker rm -f spark-gpu-worker triton 2>/dev/null
        docker run -d --name spark-gpu-worker --network host --gpus all --shm-size=4g -e SPARK_LOCAL_IP=$GPU_IP \
            -e SPARK_WORKER_OPTS="-Dspark.worker.resource.gpu.amount=1 -Dspark.worker.resource.gpu.discoveryScript=/app/deploy/scripts/gpu_discovery.sh" \
            $MOUNTS -v /opt/modes/work-gpu:/opt/spark/work $IMG \
            bash -c "pip install -q 'tritonclient[grpc]'; start-worker.sh spark://$CPU_IP:7077 -c 4 -m 12g && tail -f /opt/spark/logs/*worker*"
        # Triton model repository from the platform's own models, then the server
        docker run --rm $MOUNTS -v /opt/modes/triton_models:/models $IMG python benchmark/triton_export.py --out /models
        TRITON=$(cat /opt/modes/triton_image)
        docker run -d --name triton --gpus all --network host --shm-size=2g -v /opt/modes/triton_models:/models \
            $TRITON tritonserver --model-repository=/models --log-verbose=0
        for i in $(seq 1 60); do curl -sf localhost:8000/v2/health/ready && break; sleep 5; done
        curl -s localhost:8000/v2/health/ready -o /dev/null -w "triton ready http %{http_code}\n"
        sleep 20   # tritonclient pip install inside the worker
        docker exec spark-gpu-worker python benchmark/triton_export.py --verify localhost:8001 \
            > $APP/$OUT_REL/triton_verify.txt 2>&1; tail -5 $APP/$OUT_REL/triton_verify.txt
        nohup nvidia-smi dmon -s pucm -o DT -d 1 > /opt/modes/gpu_dmon.log 2>&1 &
        nohup vmstat -t 2 > /opt/modes/vmstat_gpu.log 2>&1 &
    fi
    echo "STARTED $ROLE"
    ;;

run)
    for i in $(seq 1 90); do
        n=$(curl -s http://$CPU_IP:8080/json/ | python3 -c "import sys,json;print(json.load(sys.stdin).get('aliveworkers',0))" 2>/dev/null)
        [ "$n" = "2" ] && break; sleep 10
    done
    curl -s http://$CPU_IP:8080/json/ > $APP/$OUT_REL/master_state_before.json
    echo "alive workers: $n"
    docker exec spark-master python benchmark/spark_modes_stats.py --master spark://$CPU_IP:7077 \
        --triton $GPU_IP --out $OUT_REL
    curl -s http://$CPU_IP:8080/json/ > $APP/$OUT_REL/master_state_after.json
    echo "RUN DONE"
    ;;

collect)
    if [ "$ROLE" = cpu ]; then
        D=$APP/$OUT_REL/cpu_node; mkdir -p $D
        docker cp spark-master:/opt/spark/logs $D/master-logs 2>/dev/null
        docker cp spark-cpu-worker:/opt/spark/logs $D/worker-logs 2>/dev/null
        cp -r /opt/modes/work-cpu $D/work 2>/dev/null; cp /opt/modes/*.log $D/ 2>/dev/null
        aws s3 sync $APP/$OUT_REL s3://$BUCKET/modes/aws_2node --region $REGION --exclude "gpu_node/*"
    else
        pkill -f "nvidia-smi dmon"; pkill vmstat
        D=$APP/$OUT_REL/gpu_node; mkdir -p $D
        curl -s localhost:8002/metrics > $D/triton_metrics_final.txt
        docker logs triton > $D/triton_server.log 2>&1
        docker cp spark-gpu-worker:/opt/spark/logs $D/worker-logs 2>/dev/null
        cp -r /opt/modes/work-gpu $D/work 2>/dev/null; cp /opt/modes/*.log $D/ 2>/dev/null
        cp /opt/modes/triton_models/*/config.pbtxt /opt/modes/triton_models/export_report.json $D/ 2>/dev/null
        for m in /opt/modes/triton_models/*/config.pbtxt; do cp $m $D/$(basename $(dirname $m)).config.pbtxt; done
        cat /opt/modes/triton_image > $D/triton_image.txt; nvidia-smi -q > $D/nvidia-smi-q.txt
        cp $APP/$OUT_REL/triton_verify.txt $D/ 2>/dev/null
        aws s3 sync $D s3://$BUCKET/modes/aws_2node/gpu_node --region $REGION
    fi
    echo "COLLECTED $ROLE"
    ;;
esac
