# =============================================================================
# run_aws_modes.ps1 - Measure every Spark inference execution mode on a real
# 2-node cluster (m5.2xlarge CPU master/worker + g4dn.xlarge GPU worker with
# Triton) and download the statistics.
#   1. cdk deploy SparkModesClusterStack
#   2. upload project + deploy/scripts/modes_node.sh
#   3. SSM: prepare (both nodes, parallel) -> start cpu -> start gpu -> run -> collect
#   4. download results\modes_20260926\aws_2node
#   5. cdk destroy (unless -KeepStack, or a step failed)
#
# Usage:  .\deploy\run_aws_modes.ps1 [-Region us-east-1] [-SkipDeploy] [-KeepStack]
# =============================================================================
param(
    [string]$Region = "us-east-1",
    [string]$StackName = "SparkModesClusterStack",
    [switch]$SkipDeploy,
    [switch]$KeepStack
)
$ErrorActionPreference = "Stop"
$PROJECT_DIR = Split-Path -Parent $PSScriptRoot
function Step($m, $c = "Cyan") { Write-Host ("  [MODES {0:HH:mm:ss}] {1}" -f (Get-Date), $m) -ForegroundColor $c }

$account = aws sts get-caller-identity --query Account --output text
if (-not $account) { throw "Not logged in - run 'aws login' first" }
$cdkCtx = @("--context", "region=$Region", "--context", "account=$account")

if (-not $SkipDeploy) {
    Push-Location "$PROJECT_DIR\deploy\aws-cdk"
    Step "cdk deploy $StackName (m5.2xlarge + g4dn.xlarge)"
    npx cdk deploy $StackName @cdkCtx --require-approval never
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "cdk deploy failed" }
    Pop-Location
}
function Out($k) { aws cloudformation describe-stacks --stack-name $StackName --region $Region --query "Stacks[0].Outputs[?OutputKey=='$k'].OutputValue" --output text }
$bucket = Out "BucketName"; $cpuId = Out "CpuInstanceId"; $gpuId = Out "GpuInstanceId"
$cpuIp = Out "CpuPrivateIp"; $gpuIp = Out "GpuPrivateIp"
Step "cpu $cpuId ($cpuIp)  gpu $gpuId ($gpuIp)  bucket $bucket"

foreach ($id in @($cpuId, $gpuId)) {
    for ($i = 0; $i -lt 60; $i++) {
        $ping = aws ssm describe-instance-information --region $Region --filters "Key=InstanceIds,Values=$id" --query "InstanceInformationList[0].PingStatus" --output text
        if ($ping -eq "Online") { break }; Start-Sleep 10
    }
    Step "SSM online: $id"
}

Set-Location $PROJECT_DIR
$zip = Join-Path $env:TEMP "modes_project.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
python -c @"
import zipfile, os
ex = {'.git','cdk.out','node_modules','__pycache__','results','weights','wheels','wheels-hotfix','debs'}
with zipfile.ZipFile(r'$zip','w',zipfile.ZIP_DEFLATED) as z:
    for r,d,fs in os.walk('.'):
        d[:] = [x for x in d if x not in ex]
        for f in fs:
            p = os.path.join(r,f); z.write(p, os.path.relpath(p,'.').replace('\\','/'))
    print('zipped', len(z.namelist()), 'files')
"@
aws s3 cp $zip "s3://$bucket/project.zip" --region $Region | Out-Null
aws s3 cp deploy/scripts/modes_node.sh "s3://$bucket/modes_node.sh" --region $Region | Out-Null

function Send($id, $stepArgs, $timeout) {
    $cmd = "aws s3 cp s3://$bucket/modes_node.sh /opt/modes_node.sh --region $Region && sed -i 's/\r$//' /opt/modes_node.sh && BUCKET=$bucket bash /opt/modes_node.sh $stepArgs"
    $p = @{ commands = @($cmd); executionTimeout = @("$timeout") } | ConvertTo-Json -Compress
    $f = Join-Path $env:TEMP ("ssm_" + [guid]::NewGuid().ToString() + ".json"); $p | Set-Content -Encoding ascii $f
    aws ssm send-command --instance-ids $id --document-name AWS-RunShellScript --parameters "file://$f" --timeout-seconds $timeout --region $Region --query "Command.CommandId" --output text
}
function WaitSsm($pairs, $label) {
    $t0 = Get-Date
    while ($true) {
        Start-Sleep 30
        $states = foreach ($p in $pairs) { (aws ssm get-command-invocation --command-id $p[0] --instance-id $p[1] --region $Region --query Status --output text 2>$null) }
        Step ("{0}: {1:N0} min  {2}" -f $label, ((Get-Date) - $t0).TotalMinutes, ($states -join " / ")) "Yellow"
        if (@($states | Where-Object { $_ -in "Pending", "InProgress", "Delayed", $null, "" }).Count -eq 0) { break }
    }
    $ok = $true
    foreach ($p in $pairs) {
        $s = aws ssm get-command-invocation --command-id $p[0] --instance-id $p[1] --region $Region --query Status --output text
        if ($s -ne "Success") {
            $ok = $false
            aws ssm get-command-invocation --command-id $p[0] --instance-id $p[1] --region $Region --query StandardOutputContent --output text | Select-Object -Last 30 | ForEach-Object { Write-Host $_ }
        }
    }
    return $ok
}

$failed = $false
$a = Send $cpuId "prepare cpu" 5400; $b = Send $gpuId "prepare gpu" 5400
if (-not (WaitSsm (@(, @($a, $cpuId)) + @(, @($b, $gpuId))) "prepare (build image, pull Triton)")) { $failed = $true }
if (-not $failed) {
    $a = Send $cpuId "start cpu $cpuIp $gpuIp" 1800
    if (-not (WaitSsm @(, @($a, $cpuId)) "start master + cpu worker")) { $failed = $true }
}
if (-not $failed) {
    $b = Send $gpuId "start gpu $cpuIp $gpuIp" 2400
    if (-not (WaitSsm @(, @($b, $gpuId)) "start gpu worker + Triton")) { $failed = $true }
}
if (-not $failed) {
    $a = Send $cpuId "run cpu $cpuIp $gpuIp" 10800
    if (-not (WaitSsm @(, @($a, $cpuId)) "run all modes")) { $failed = $true }
}
# collect even after a failure - partial results are still useful
$a = Send $cpuId "collect cpu" 1800; $b = Send $gpuId "collect gpu" 1800
WaitSsm (@(, @($a, $cpuId)) + @(, @($b, $gpuId))) "collect" | Out-Null

$local = "$PROJECT_DIR\results\modes_20260926\aws_2node"
aws s3 sync "s3://$bucket/modes/aws_2node" $local --region $Region | Out-Null
Step "Results in $local" "Green"

if ($failed) {
    Step "A step failed - keeping the stack for debugging. Fix, then re-run with -SkipDeploy, or destroy:" "Red"
    Step "  cd deploy\aws-cdk; npx cdk destroy $StackName --context region=$Region --context account=$account --force" "Red"
    exit 1
}
if (-not $KeepStack) {
    Push-Location "$PROJECT_DIR\deploy\aws-cdk"
    Step "cdk destroy $StackName"
    npx cdk destroy $StackName @cdkCtx --force
    Pop-Location
}
