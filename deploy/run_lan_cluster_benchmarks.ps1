# =============================================================================
# run_lan_cluster_benchmarks.ps1 — Run the full benchmark matrix against the
# local 2-node Windows LAN cluster (master + GPU worker, both running Docker
# CE inside a mirrored-networking WSL2 Ubuntu distro — see
# docs/WINDOWS_LAN_NETWORKING_FIX_20260921.md for why this setup exists
# instead of plain Docker Desktop) and pull the results back to this machine.
#
# Sibling to deploy/run_gpu_benchmarks.ps1 (same phase structure), adapted
# for a local WSL2/Docker-CE cluster instead of AWS EC2 + SSM: `docker exec`
# via `wsl -d <distro> --` replaces SSM commands, and results come back via
# `docker cp` instead of S3 sync.
#
# Usage:
#   .\deploy\run_lan_cluster_benchmarks.ps1
#   .\deploy\run_lan_cluster_benchmarks.ps1 -MasterIp 192.168.4.104 -Distro Ubuntu-22.04
# =============================================================================
param(
    [string]$MasterIp = "192.168.4.104",
    [string]$Distro = "Ubuntu-22.04",
    [string]$MasterContainer = "spark-master",
    [string]$ResultsLocalPath = ".\results\lan_cluster_benchmark"
)

$ErrorActionPreference = "Stop"
$PROJECT_DIR = Split-Path -Parent $PSScriptRoot

function Write-Step($msg, $color = "Cyan") { Write-Host "  [LAN-BENCH] $msg" -ForegroundColor $color }
function Wsl([string]$cmd) { wsl -d $Distro -- bash -c $cmd }

Write-Host ""
Write-Host "  ============================================" -ForegroundColor White
Write-Host "  LAN CLUSTER BENCHMARK — full matrix" -ForegroundColor White
Write-Host "  ============================================" -ForegroundColor White
Write-Host ""

# --- Preflight: master alive, worker registered ---
Write-Step "Checking master ($MasterIp)..."
$statusJson = Wsl "curl -s http://${MasterIp}:8080/json/ --max-time 5"
if (-not $statusJson) {
    Write-Step "Master not reachable at http://${MasterIp}:8080/json/ — aborting. Is spark-master running in the '$Distro' WSL distro?" "Red"
    exit 1
}
$status = $statusJson | ConvertFrom-Json
Write-Step "Master status: $($status.status) | aliveworkers: $($status.aliveworkers)" "Green"
if ($status.aliveworkers -lt 1) {
    Write-Step "No alive workers registered — GPU/hybrid/distributed phases will run with reduced or zero parallelism. Continuing anyway." "Yellow"
}

# --- Copy the static benchmark script into the container, with MASTER_IP filled in ---
Write-Step "Preparing benchmark script..."
$scriptPath = Join-Path $PSScriptRoot "scripts\lan_cluster_benchmarks.sh"
$scriptContent = (Get-Content $scriptPath -Raw).Replace("__MASTER_IP__", $MasterIp).Replace("`r`n", "`n")
$tmpScript = Join-Path $env:TEMP "lan_cluster_benchmarks_$([guid]::NewGuid()).sh"
[System.IO.File]::WriteAllText($tmpScript, $scriptContent)

# wsl.exe needs a WSL-visible path, not a Windows one — /mnt/c/... form.
$driveLetter = $tmpScript.Substring(0,1).ToLower()
$wslTmpPath = "/mnt/$driveLetter" + $tmpScript.Substring(2).Replace('\','/')

Write-Step "Copying script into $MasterContainer and running the full matrix (this takes a while — CPU + GPU + hybrid + batch sweep + incremental)..."
wsl -d $Distro -- docker cp $wslTmpPath "${MasterContainer}:/tmp/lan_cluster_benchmarks.sh"

# --- Run it, streaming output to a local log as it goes ---
if (-not (Test-Path $ResultsLocalPath)) { New-Item -ItemType Directory -Path $ResultsLocalPath -Force | Out-Null }
$logPath = Join-Path $ResultsLocalPath "lan_cluster_benchmarks.log"

$job = Start-Job -ScriptBlock {
    param($distro, $container, $logPath)
    wsl -d $distro -- docker exec $container bash /tmp/lan_cluster_benchmarks.sh *>&1 |
        Tee-Object -FilePath $logPath
} -ArgumentList $Distro, $MasterContainer, $logPath

$elapsed = 0
$interval = 20
while ($job.State -eq "Running") {
    Start-Sleep -Seconds $interval
    $elapsed += $interval
    $min = [math]::Floor($elapsed / 60)
    $lastLine = if (Test-Path $logPath) { Get-Content $logPath -Tail 1 -ErrorAction SilentlyContinue } else { "" }
    Write-Step "${min}m elapsed | $lastLine" "Yellow"
}
Receive-Job $job | Out-Null
Remove-Job $job
Remove-Item $tmpScript -Force -ErrorAction SilentlyContinue

if ((Get-Content $logPath -Raw) -notmatch "ALL LAN CLUSTER BENCHMARKS COMPLETE") {
    Write-Step "Benchmark script did not report completion — check $logPath before trusting results" "Red"
} else {
    Write-Step "Benchmark matrix complete" "Green"
}

# --- Pull results out of the container ---
Write-Step "Copying results out of $MasterContainer..."
wsl -d $Distro -- docker cp "${MasterContainer}:/app/results/." $wslTmpPath.Replace((Split-Path $tmpScript -Leaf), "lan_bench_results_tmp") 2>$null
$wslResultsTmp = "/tmp/lan_bench_results_$([guid]::NewGuid())"
wsl -d $Distro -- docker cp "${MasterContainer}:/app/results/." $wslResultsTmp
$winResultsTmp = "\\wsl$\$Distro$($wslResultsTmp.Replace('/','\'))"
Copy-Item -Path "$winResultsTmp\*" -Destination $ResultsLocalPath -Recurse -Force -ErrorAction SilentlyContinue
wsl -d $Distro -- rm -rf $wslResultsTmp

$jsonFiles = Get-ChildItem -Path $ResultsLocalPath -Filter "*.json" -ErrorAction SilentlyContinue
Write-Step "Copied $($jsonFiles.Count) result JSON files to: $ResultsLocalPath" "Green"

# --- Summarize the incremental run (Phase F) if present ---
# NOTE on schema (verified against a real results file, not guessed): a
# FAILED run has {run_number, device_mode, status: "failed", error}. A
# SUCCESSFUL run has NO "status" field at all — instead {mode, device_mode,
# elapsed_time, total_samples_processed, total_throughput, per_model_processed,
# run_number, timestamp}. There is no "partitions" or execution-"device"
# field at the top level for either case.
$incrementalFile = $jsonFiles | Where-Object { $_.Name -like "incremental_all_modes_*" } | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($incrementalFile) {
    Write-Host ""
    Write-Step "Summary (from $($incrementalFile.Name)):" "White"
    $runs = Get-Content $incrementalFile.FullName -Raw | ConvertFrom-Json
    "{0,-4} {1,-14} {2,-10} {3,-14} {4,-10}" -f "#","Mode","Samples","Throughput/s","Time(s)" | Write-Host
    foreach ($r in $runs) {
        $failed = $r.status -eq "failed"
        $line = "{0,-4} {1,-14} {2,-10} {3,-14} {4,-10}" -f `
            $r.run_number, $r.device_mode, `
            $(if ($failed) { "-" } else { $r.total_samples_processed }), `
            $(if ($failed) { "FAILED" } else { $r.total_throughput }), `
            $(if ($failed) { "-" } else { [math]::Round($r.elapsed_time, 1) })
        Write-Host $line
    }
}

Write-Host ""
Write-Step "Done. Full log: $logPath"
Write-Host ""
