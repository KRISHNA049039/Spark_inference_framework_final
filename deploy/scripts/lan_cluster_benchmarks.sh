#!/bin/bash
# lan_cluster_benchmarks.sh — Full benchmark matrix for the local Windows LAN
# 2-node cluster (master 192.168.4.104 + GPU worker 192.168.4.101), mirroring
# deploy/scripts/gpu_benchmarks.sh's AWS phases 6-10 but run in-place via
# `docker exec` against the already-running spark-master container instead of
# SSM. Run from inside the container (this file is `docker cp`'d in and
# executed there by deploy/run_lan_cluster_benchmarks.ps1).
#
# Applies the sm_120 (Blackwell/RTX 5060) CUDA fix live via pip before running
# any GPU-mode test, since the base image (deploy/Dockerfile) hasn't been
# rebuilt with the fix yet — see docs/WINDOWS_LAN_NETWORKING_FIX_20260921.md
# for how this was diagnosed. Once deploy/Dockerfile is updated and the image
# rebuilt, this patch step becomes a no-op (pip skips an already-satisfied
# exact-version pin) and can be removed.
set -x

MASTER_IP=__MASTER_IP__

echo '=== Applying live CUDA fix (torch==2.9.1+cu128, sm_120/Blackwell support) ==='
pip install --quiet --default-timeout=300 --retries 5 \
  torch==2.9.1 torchvision==0.24.1 \
  --index-url https://download.pytorch.org/whl/cu128

echo '=== PHASE A: CPU baseline ==='
SPARK_MASTER_URL=spark://${MASTER_IP}:7077 CUDA_VISIBLE_DEVICES='' python benchmark/cluster_benchmark.py --device-mode cpu_only --partitions 4 --signal-samples 3000 --batch-size 128
sleep 3
SPARK_MASTER_URL=spark://${MASTER_IP}:7077 CUDA_VISIBLE_DEVICES='' python benchmark/cluster_benchmark.py --device-mode cpu_only --partitions 8 --signal-samples 3000 --batch-size 128
sleep 3

echo '=== PHASE B: GPU tests (now that sm_120 kernels are present) ==='
SPARK_MASTER_URL=spark://${MASTER_IP}:7077 python benchmark/cluster_benchmark.py --device-mode gpu_only --partitions 2 --signal-samples 1000 --image-samples 50 --detection-samples 20 --batch-size 128
sleep 3
SPARK_MASTER_URL=spark://${MASTER_IP}:7077 python benchmark/cluster_benchmark.py --device-mode gpu_only --partitions 4 --signal-samples 3000 --image-samples 100 --detection-samples 30 --batch-size 256
sleep 3
SPARK_MASTER_URL=spark://${MASTER_IP}:7077 python benchmark/cluster_benchmark.py --device-mode gpu_only --partitions 4 --signal-samples 5000 --image-samples 200 --detection-samples 50 --batch-size 256
sleep 3

echo '=== PHASE C: Hybrid tests ==='
SPARK_MASTER_URL=spark://${MASTER_IP}:7077 python benchmark/cluster_benchmark.py --device-mode hybrid --partitions 4 --signal-samples 3000 --image-samples 100 --detection-samples 30 --batch-size 256
sleep 3
SPARK_MASTER_URL=spark://${MASTER_IP}:7077 python benchmark/cluster_benchmark.py --device-mode hybrid --partitions 8 --signal-samples 5000 --image-samples 200 --detection-samples 50 --batch-size 256
sleep 3

echo '=== PHASE D: GPU batch size sweep ==='
for bs in 64 128 256 512; do
  SPARK_MASTER_URL=spark://${MASTER_IP}:7077 python benchmark/cluster_benchmark.py --device-mode gpu_only --partitions 4 --signal-samples 3000 --image-samples 100 --detection-samples 30 --batch-size $bs
  sleep 3
done

echo '=== PHASE E: Incremental load ==='
SPARK_MASTER_URL=spark://${MASTER_IP}:7077 python benchmark/incremental_load_test.py
sleep 3

echo '=== PHASE F: Full incremental (all modes x all loads) ==='
SPARK_MASTER_URL=spark://${MASTER_IP}:7077 python benchmark/cluster_benchmark.py --incremental

echo '=== ALL LAN CLUSTER BENCHMARKS COMPLETE ==='
