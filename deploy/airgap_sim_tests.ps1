# =============================================================================
# airgap_sim_tests.ps1 - end-to-end tests of the air-gapped cluster simulation
# (deploy/docker-compose.airgap_sim.yml): models stored in HDFS or on the
# master's file system, NER pipeline served by the GPU "kitchen" or run
# in-process by Spark executors.
#
#   .\deploy\airgap_sim_tests.ps1                       # all tests T01..T12
#   .\deploy\airgap_sim_tests.ps1 -Tests T01,T02,T03    # a subset
#   .\deploy\airgap_sim_tests.ps1 -Tests T12 -Wipe      # teardown incl. HDFS data + caches
#
# Every test prints PASS/FAIL; outputs go to results\airgap_sim_<timestamp>\
# Runbook: docs\CLUSTER_RUNBOOK_MODES_AND_TESTS.pdf
# =============================================================================
param(
    [string[]]$Tests = @("all"),
    [string]$WeightsSrc = "D:\pytorch-spark-inference-platform_20260921\models\weights",
    [switch]$Wipe
)
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Compose = "deploy/docker-compose.airgap_sim.yml"
$Out = "results\airgap_sim_" + (Get-Date -Format "yyyyMMdd_HHmmss")
New-Item -ItemType Directory -Force $Out | Out-Null
$HdfsUri = "hdfs://hdfs-namenode:8020/models/weights"
$env:WEIGHTS_SRC = $WeightsSrc
$env:MODEL_STORE_URI = $HdfsUri          # default model source for every test (T10 switches to file:// and back)
Remove-Item Env:\MODEL_FS_DIR -ErrorAction SilentlyContinue
$Summary = @()

function Log($id, $text) { Add-Content -Path "$Out\$id.log" -Value $text; Write-Host "      $text" }
# plain function on purpose: an advanced function would bind "-d" to PowerShell's own -Debug switch
function Dc { & docker compose -f $Compose @args 2>&1 | ForEach-Object { "$_" } }   # progress goes to stderr: keep it as text
function Wait-Healthy($name, $timeoutSec) {
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt $timeoutSec) {
        $s = (docker inspect -f "{{.State.Health.Status}}" $name 2>$null)
        if ($s -eq "healthy") { return $true }
        Start-Sleep 5
    }
    return $false
}
function Wait-Workers($master, $n, $timeoutSec) {
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt $timeoutSec) {
        $j = docker exec $master curl -s http://localhost:8080/json/ 2>$null | Out-String
        if ($j -match '"aliveworkers"\s*:\s*(\d+)' -and [int]$Matches[1] -ge $n) { return $true }
        Start-Sleep 5
    }
    return $false
}
function Run-Test($id, $title, [scriptblock]$body) {
    if ($Tests -notcontains "all" -and $Tests -notcontains $id) { return }
    Write-Host ""
    Write-Host "[$id] $title" -ForegroundColor Cyan
    $t0 = Get-Date
    $ok = $false
    try { $ok = [bool](& $body) } catch { Log $id "EXCEPTION: $_" }
    $secs = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
    $res = if ($ok) { "PASS" } else { "FAIL" }
    Write-Host ("  => {0} ({1} s)" -f $res, $secs) -ForegroundColor $(if ($ok) { "Green" } else { "Red" })
    $script:Summary += [pscustomobject]@{ Test = $id; Title = $title; Result = $res; Seconds = $secs }
}
function Submit-Ner($master, $sparkUrl, $mode, $parts, $execMem, $id) {
    $o = docker exec $master python submit_pipeline_job.py --pipeline ner_translate --input data/ner_samples `
        --partitions $parts --execution-mode $mode --master $sparkUrl --driver-memory 1g --executor-memory $execMem 2>&1 | ForEach-Object { "$_" } | Out-String
    Add-Content -Path "$Out\$id.log" -Value $o
    $lines = ($o -split "`n") | Where-Object { $_ -match "execution-mode=|Processed \d+ document|lang=|ERROR|written to|elapsed_time" }
    $lines | ForEach-Object { Write-Host "      $($_.Trim())" }
    return ($o -match "Processed 6 document\(s\)") -and -not ($o -match ": ERROR ")
}

# ------------------------------------------------------------------ T01
Run-Test "T01" "Prerequisites: Docker, images, GPU, model weights on the staging disk" {
    $ok = $true
    docker info --format "{{.MemTotal}}" 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { Log "T01" "Docker engine not reachable"; return $false }
    $mem = [math]::Round((docker info --format "{{.MemTotal}}") / 1GB, 1); Log "T01" "Docker VM memory: $mem GB (>= 5.5 GB needed for the model server + HDFS + Spark)"
    if ($mem -lt 5.5) { $ok = $false }
    foreach ($img in "apache/hadoop:3.4.1", "ner-translate-server:latest", "spark-lean:latest", "ner-translate-worker:latest") {
        docker image inspect $img 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { Log "T01" "image ok: $img" } else { Log "T01" "MISSING image: $img"; $ok = $false }
    }
    foreach ($f in "gliner-multi\gliner_config.json", "nllb-200-distilled-600M\config.json", "hf_cache\models--microsoft--mdeberta-v3-base") {
        if (Test-Path (Join-Path $WeightsSrc $f)) { Log "T01" "weights ok: $f" } else { Log "T01" "MISSING weights: $WeightsSrc\$f"; $ok = $false }
    }
    $g = docker run --rm --gpus all --entrypoint python ner-translate-server:latest -c "import torch;print(torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')" 2>&1 | Out-String
    Log "T01" "GPU in containers: $($g.Trim())"
    if ($g -notmatch "True") { $ok = $false }
    return $ok
}

# ------------------------------------------------------------------ T02
Run-Test "T02" "Start HDFS (namenode + datanode) and wait for a live datanode" {
    Dc --profile hdfs up -d | Out-String | Add-Content "$Out\T02.log"
    if (-not (Wait-Healthy "sim-hdfs-namenode" 240)) { Log "T02" "namenode not healthy"; return $false }
    for ($i = 0; $i -lt 30; $i++) {
        $r = docker exec sim-hdfs-namenode hdfs dfsadmin -report 2>$null | Out-String
        if ($r -match "Live datanodes \((\d+)\)" -and [int]$Matches[1] -ge 1) { Log "T02" "Live datanodes: $($Matches[1]); WebHDFS: http://localhost:9870"; return $true }
        Start-Sleep 5
    }
    Log "T02" "no live datanode"; return $false
}

# ------------------------------------------------------------------ T03
Run-Test "T03" "Upload the model weights into HDFS (/models/weights) and verify byte counts" {
    docker exec sim-hdfs-namenode hdfs dfs -mkdir -p /models/weights | Out-Null
    # hf_cache = GLiNER's backbone (microsoft/mdeberta-v3-base) config + tokenizer, needed offline
    $o = docker exec sim-hdfs-namenode hdfs dfs -put -f /staging/gliner-multi /staging/nllb-200-distilled-600M /staging/hf_cache /models/weights/ 2>&1 | Out-String
    if ($o.Trim()) { Log "T03" $o.Trim() }
    $ok = $true
    foreach ($m in "gliner-multi", "nllb-200-distilled-600M", "hf_cache") {
        $local = (Get-ChildItem -Recurse -File -Force (Join-Path $WeightsSrc $m) | Measure-Object Length -Sum).Sum
        $du = (docker exec sim-hdfs-namenode hdfs dfs -du -s "/models/weights/$m" | Out-String).Trim() -split "\s+"
        Log "T03" ("{0}: local {1} bytes, HDFS {2} bytes" -f $m, $local, [int64]$du[0])
        if ($m -eq "hf_cache") {       # HF cache snapshots are symlinks; HDFS stores them as files (bigger, same content)
            if ([int64]$du[0] -le 0) { $ok = $false }
        } elseif ([int64]$du[0] -ne $local) { $ok = $false }
    }
    docker exec sim-hdfs-namenode hdfs dfs -ls -R /models/weights 2>&1 | Out-String | Add-Content "$Out\T03.log"
    return $ok
}

# ------------------------------------------------------------------ T04
Run-Test "T04" "model_store over WebHDFS: fetch + checksum, missing path, unreachable host" {
    $env:MODEL_STORE_URI = $HdfsUri
    $py = @"
import hashlib, sys
from models import model_store as m
p = m.resolve('$HdfsUri/gliner-multi/gliner_config.json')
print('sha256', hashlib.sha256(open(p,'rb').read()).hexdigest())
p2 = m.resolve('$HdfsUri/gliner-multi/gliner_config.json')          # second call: cache hit
for bad in ('$HdfsUri/does-not-exist', 'hdfs://no-such-namenode:8020/models'):
    try:
        m.resolve(bad); print('UNEXPECTED success', bad)
    except (FileNotFoundError, ConnectionError) as e:
        print('expected error:', type(e).__name__, str(e)[:110])
"@
    $o = Dc --profile service run --rm --no-deps -e MODEL_CACHE_DIR=/tmp/t04 --entrypoint python ner-translate-server -c $py | Out-String
    Log "T04" $o.Trim()
    $want = (Get-FileHash -Algorithm SHA256 (Join-Path $WeightsSrc "gliner-multi\gliner_config.json")).Hash.ToLower()
    Log "T04" "sha256 of the local original: $want"
    return ($o -match "sha256 $want") -and ($o -match "cache hit") -and (([regex]::Matches($o, "expected error")).Count -eq 2)
}

# ------------------------------------------------------------------ T05
Run-Test "T05" "Model server (kitchen) with models from HDFS: fetch into node cache, load on GPU" {
    $env:MODEL_STORE_URI = $HdfsUri
    Dc --profile hdfs --profile service up -d ner-translate-server | Out-String | Add-Content "$Out\T05.log"
    $h = Wait-Healthy "sim-ner-translate-server" 1200
    $logs = docker logs sim-ner-translate-server 2>&1 | Out-String
    $logs | Add-Content "$Out\T05.log"
    ($logs -split "`n") | Where-Object { $_ -match "model source|model_store|Models loaded|GPU detected|fp16|Error" } | ForEach-Object { Log "T05" $_.Trim() }
    docker stats --no-stream --format "{{.Name}} {{.MemUsage}}" | Out-String | ForEach-Object { Log "T05" $_.Trim() }
    return $h -and ($logs -match "model source: model store hdfs://") -and ($logs -match "\[model_store\] (fetched|cache hit)")
}

# ------------------------------------------------------------------ T06
Run-Test "T06" "Call the model server directly (POST /predict, no Spark)" {
    $r = Invoke-RestMethod -Method Post -Uri http://localhost:8001/predict -ContentType "application/json" `
        -Body '{"paths":["data/ner_samples/sample_text1.txt","data/ner_samples/sample_scan6.png"]}' -TimeoutSec 600
    $j = $r | ConvertTo-Json -Depth 6
    Add-Content "$Out\T06.log" $j
    $ok = $true
    foreach ($k in "sample_text1.txt", "sample_scan6.png") {
        $d = $r.$k
        if (-not $d -or $d.error) { Log "T06" "$k -> ERROR $($d.error)"; $ok = $false; continue }
        Log "T06" ("{0}: language={1} translated={2} entities={3}" -f $k, $d.language, $d.translated, @($d.entities_unique).Count)
    }
    return $ok
}

# ------------------------------------------------------------------ T07
Run-Test "T07" "Spark cluster, service mode: lean master + worker POST to the kitchen" {
    Dc --profile hdfs --profile service up -d ner-translate-master ner-translate-worker | Out-String | Add-Content "$Out\T07.log"
    if (-not (Wait-Workers "sim-spark-master" 1 180)) { Log "T07" "worker did not register"; return $false }
    Log "T07" "Spark master UI http://localhost:8083 - 1 worker alive"
    return (Submit-Ner "sim-spark-master" "spark://ner-translate-master:7077" "service" 2 "512m" "T07")
}

# ------------------------------------------------------------------ T08
Run-Test "T08" "Node cache: restarting the kitchen reuses the downloaded models" {
    # a new container on the same node: the node-local cache volume survives, the process starts cold
    Dc --profile service up -d --force-recreate ner-translate-server | Out-String | Add-Content "$Out\T08.log"
    $h = Wait-Healthy "sim-ner-translate-server" 900
    $logs = docker logs sim-ner-translate-server 2>&1 | Out-String
    ($logs -split "`n") | Where-Object { $_ -match "model_store|Models loaded" } | ForEach-Object { Log "T08" $_.Trim() }
    return $h -and (([regex]::Matches($logs, "cache hit")).Count -ge 2)
}

# ------------------------------------------------------------------ T09
Run-Test "T09" "HDFS outage with a warm cache: kitchen still starts and serves" {
    docker stop sim-hdfs-datanode sim-hdfs-namenode | Out-Null
    Dc --profile service up -d --force-recreate ner-translate-server | Out-String | Add-Content "$Out\T09.log"
    $h = Wait-Healthy "sim-ner-translate-server" 900
    docker logs sim-ner-translate-server 2>&1 | Select-String "model_store|Models loaded" | ForEach-Object { Log "T09" $_.Line.Trim() }
    $ok = $false
    if ($h) {
        $r = Invoke-RestMethod -Method Post -Uri http://localhost:8001/predict -ContentType "application/json" -Body '{"paths":["data/ner_samples/sample_text2.txt"]}' -TimeoutSec 300
        $ok = [bool]$r.'sample_text2.txt'.language
        Log "T09" "HDFS stopped; /predict -> language=$($r.'sample_text2.txt'.language)"
    }
    docker start sim-hdfs-namenode sim-hdfs-datanode | Out-Null
    Log "T09" "HDFS restarted"
    return $ok
}

# ------------------------------------------------------------------ T10
Run-Test "T10" "Master file-system mode: models read from a shared/local path (file://), no HDFS" {
    $env:MODEL_FS_DIR = $WeightsSrc
    $env:MODEL_STORE_URI = "file:///mnt/models"
    Dc --profile hdfs --profile service up -d --force-recreate ner-translate-server | Out-String | Add-Content "$Out\T10.log"
    $h = Wait-Healthy "sim-ner-translate-server" 900
    $logs = docker logs sim-ner-translate-server 2>&1 | Out-String
    ($logs -split "`n") | Where-Object { $_ -match "model source|model_store|Models loaded" } | ForEach-Object { Log "T10" $_.Trim() }
    $ok = $h -and ($logs -match "model source: model store file:///mnt/models") -and -not ($logs -match "\[model_store\] fetched")
    if ($ok) { $ok = Submit-Ner "sim-spark-master" "spark://ner-translate-master:7077" "service" 2 "512m" "T10" }
    Remove-Item Env:\MODEL_FS_DIR -ErrorAction SilentlyContinue; $env:MODEL_STORE_URI = $HdfsUri
    return $ok
}

# ------------------------------------------------------------------ T11
Run-Test "T11" "Cluster (in-process) mode: the Spark executor fetches models from HDFS and runs NER itself" {
    Dc --profile service stop | Out-String | Add-Content "$Out\T11.log"          # free memory for the executor
    $env:MODEL_STORE_URI = $HdfsUri
    Dc --profile hdfs --profile cluster up -d | Out-String | Add-Content "$Out\T11.log"
    if (-not (Wait-Workers "sim-ner-cluster-master" 1 240)) { Log "T11" "worker did not register"; return $false }
    Log "T11" "Spark master UI http://localhost:8084 - 1 worker alive"
    $ok = Submit-Ner "sim-ner-cluster-master" "spark://ner-cluster-master:7077" "cluster" 1 "4g" "T11"
    $ex = docker exec sim-ner-cluster-worker bash -c "grep -rh 'model_store\|model source' /opt/spark/work | tail -4" 2>&1 | Out-String
    ($ex -split "`n") | Where-Object { $_.Trim() } | ForEach-Object { Log "T11" ("executor: " + $_.Trim()) }
    return $ok -and ($ex -match "model_store")
}

# ------------------------------------------------------------------ T12
Run-Test "T12" "Teardown (keeps HDFS data + node caches unless -Wipe)" {
    if ($Wipe) { Dc --profile hdfs --profile service --profile cluster down -v | Out-String | Add-Content "$Out\T12.log"; Log "T12" "stopped + volumes removed" }
    else { Dc --profile hdfs --profile service --profile cluster down | Out-String | Add-Content "$Out\T12.log"; Log "T12" "stopped (volumes kept: hdfs-name, hdfs-data, kitchen-cache, worker-cache)" }
    return $true
}

Write-Host ""
$Summary | Format-Table -AutoSize | Out-String | Tee-Object -FilePath "$Out\summary.txt" | Write-Host
$Summary | ConvertTo-Json | Set-Content "$Out\summary.json"
Write-Host "Logs: $Out"
