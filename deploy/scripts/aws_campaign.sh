#!/bin/bash
# =============================================================================
# aws_campaign.sh - Run the same campaign + low-level trace as the local
# Windows / WSL2 legs, on the GpuBenchmarkStack EC2 instance (g4dn.xlarge, T4).
# Uploaded to S3 and executed via SSM by deploy/run_aws_campaign.ps1.
# Log: /opt/benchmark/campaign.log ; results synced to s3://$BUCKET/campaign/
# =============================================================================
set +e
mkdir -p /opt/benchmark
exec > >(tee -a /opt/benchmark/campaign.log) 2>&1
# SSM can come online before UserData (cloud-init) has finished installing
# docker / nvidia-ctk and writing BUCKET into /etc/environment - wait for it.
cloud-init status --wait >/dev/null 2>&1 || true
source /etc/environment
REGION=${AWS_DEFAULT_REGION:-us-east-1}
[ -z "$BUCKET" ] && BUCKET=$(grep BUCKET /etc/environment | cut -d= -f2)
[ -z "$BUCKET" ] && { echo "FATAL: BUCKET not set"; exit 1; }
LEG=${LEG:-aws_g4dn}
STAMP=${STAMP:-20260926}
echo "=== aws_campaign start $(date) bucket=$BUCKET leg=$LEG ==="

systemctl start docker 2>/dev/null || true
if ! docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu22.04 nvidia-smi >/dev/null 2>&1; then
    nvidia-ctk runtime configure --runtime=docker 2>/dev/null; systemctl restart docker; sleep 3
fi
apt-get install -y unzip >/dev/null 2>&1

mkdir -p /opt/benchmark/app
aws s3 cp s3://$BUCKET/project.zip /opt/benchmark/project.zip --region $REGION || { echo "FATAL: download"; exit 1; }
cd /opt/benchmark && rm -rf app/* && unzip -oq project.zip -d app && cd app

echo "=== host hardware ==="
nvidia-smi; nvidia-smi -q | sed -n '/PCI/,/Tx Throughput/p'; lscpu; free -g

if ! docker image inspect multi-model-inference:latest >/dev/null 2>&1; then
    echo "=== building image $(date) ==="
    docker build --network host --target final -t multi-model-inference:latest -f deploy/Dockerfile . || { echo FATAL build; exit 1; }
fi

docker rm -f spark-master spark-gpu-worker 2>/dev/null
IP=$(hostname -I | awk '{print $1}')
MOUNTS="-v /opt/benchmark/app/results:/app/results -v /opt/benchmark/app/benchmark:/app/benchmark \
 -v /opt/benchmark/app/inference:/app/inference -v /opt/benchmark/app/models:/app/models \
 -v /opt/benchmark/app/data:/app/data -v /opt/benchmark/app/submit_job.py:/app/submit_job.py"
docker run -d --name spark-master --network host --gpus all --shm-size=4g $MOUNTS \
  multi-model-inference:latest bash -c "start-master.sh && tail -f /opt/spark/logs/*master*"
sleep 10
docker run -d --name spark-gpu-worker --network host --gpus all --shm-size=4g $MOUNTS \
  multi-model-inference:latest bash -c "start-worker.sh spark://$IP:7077 -c 4 -m 12g && tail -f /opt/spark/logs/*worker*"
sleep 15
docker exec spark-master curl -s http://localhost:8080/json/ | head -c 600; echo

echo "=== campaign $(date) ==="
docker exec -e LEG=$LEG -e STAMP=$STAMP -e SPARK_MASTER_URL=spark://$IP:7077 spark-master \
  bash benchmark/run_campaign.sh

echo "=== low-level trace $(date) ==="
docker exec -e SPARK_MASTER_URL=spark://$IP:7077 spark-master bash -c \
  "python benchmark/lowlevel_trace.py --out results/campaign_$STAMP/$LEG/lowlevel > results/campaign_$STAMP/$LEG/lowlevel.log 2>&1"
docker exec -e SPARK_MASTER_URL=spark://$IP:7077 spark-master bash -c \
  "cp /opt/spark/logs/* results/campaign_$STAMP/$LEG/ 2>/dev/null; cp -r /opt/spark/work results/campaign_$STAMP/$LEG/spark-work 2>/dev/null" || true
docker cp spark-gpu-worker:/opt/spark/work /opt/benchmark/app/results/campaign_$STAMP/$LEG/spark-worker-work 2>/dev/null
nvidia-smi -q > /opt/benchmark/app/results/campaign_$STAMP/$LEG/nvidia-smi-q.txt
# Per-run JSON/MD reports that the benchmark scripts write to results/ itself
mkdir -p /opt/benchmark/app/results/campaign_$STAMP/$LEG/run_outputs
find /opt/benchmark/app/results -maxdepth 1 -type f -exec cp {} /opt/benchmark/app/results/campaign_$STAMP/$LEG/run_outputs/ \;

aws s3 sync /opt/benchmark/app/results/campaign_$STAMP/ s3://$BUCKET/campaign/ --region $REGION
aws s3 cp /opt/benchmark/campaign.log s3://$BUCKET/campaign/$LEG/campaign.log --region $REGION
echo "=== aws_campaign done $(date) ==="
