# =============================================================================
# run_aws_campaign.ps1 - AWS leg of the Windows / WSL2 / AWS test campaign.
#   1. cdk deploy GpuBenchmarkStack (g4dn.xlarge, T4, Deep Learning AMI)
#   2. upload project + deploy/scripts/aws_campaign.sh to the stack's bucket
#   3. run it via SSM (build image, Spark master+GPU worker, run_campaign.sh,
#      lowlevel_trace.py), poll until done
#   4. download results to results\campaign_<stamp>\aws_g4dn
#   5. cdk destroy (unless -KeepStack)
#
# Usage:  .\deploy\run_aws_campaign.ps1 [-Region us-east-1] [-KeepStack]
# =============================================================================
param(
    [string]$Region = "us-east-1",
    [string]$StackName = "GpuBenchmarkStack",
    [string]$Stamp = "20260926",
    [switch]$SkipDeploy,
    [switch]$KeepStack
)
$ErrorActionPreference = "Stop"
$PROJECT_DIR = Split-Path -Parent $PSScriptRoot
function Step($m, $c = "Cyan") { Write-Host "  [AWS] $m" -ForegroundColor $c }

$account = aws sts get-caller-identity --query Account --output text
if (-not $account) { throw "Not logged in - run 'aws login' first" }
Step "Account $account, region $Region"

if (-not $SkipDeploy) {
    Push-Location "$PROJECT_DIR\deploy\aws-cdk"
    Step "cdk deploy $StackName ..."
    npx cdk deploy $StackName --context region=$Region --context account=$account --require-approval never
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "cdk deploy failed" }
    Pop-Location
}
$q = { param($k) aws cloudformation describe-stacks --stack-name $StackName --region $Region --query "Stacks[0].Outputs[?OutputKey=='$k'].OutputValue" --output text }
$bucket = & $q "BucketName"; $instanceId = & $q "InstanceId"
Step "Instance $instanceId  bucket $bucket"

Step "Waiting for SSM agent..."
for ($i = 0; $i -lt 40; $i++) {
    $ping = aws ssm describe-instance-information --region $Region --filters "Key=InstanceIds,Values=$instanceId" --query "InstanceInformationList[0].PingStatus" --output text
    if ($ping -eq "Online") { break }; Start-Sleep 15
}

Set-Location $PROJECT_DIR
$zip = Join-Path $env:TEMP "campaign_project.zip"
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
aws s3 cp deploy/scripts/aws_campaign.sh "s3://$bucket/aws_campaign.sh" --region $Region | Out-Null

$params = @{ commands = @("aws s3 cp s3://$bucket/aws_campaign.sh /tmp/c.sh --region $Region && sed -i 's/\r$//' /tmp/c.sh && BUCKET=$bucket STAMP=$Stamp bash /tmp/c.sh"); executionTimeout = @("10800") } | ConvertTo-Json -Compress
$paramFile = Join-Path $env:TEMP "ssm_params.json"; $params | Set-Content -Encoding ascii $paramFile
$cmdId = aws ssm send-command --instance-ids $instanceId --document-name AWS-RunShellScript --parameters "file://$paramFile" --timeout-seconds 10800 --region $Region --query "Command.CommandId" --output text
Step "SSM command $cmdId started (log: /opt/benchmark/campaign.log)"

$t0 = Get-Date
while ($true) {
    Start-Sleep 60
    $st = (aws ssm get-command-invocation --command-id $cmdId --instance-id $instanceId --region $Region --query Status --output text).Trim()
    Step ("{0:N0} min  {1}" -f ((Get-Date) - $t0).TotalMinutes, $st) "Yellow"
    if ($st -in "Success", "Failed", "TimedOut", "Cancelled") { break }
}

$local = "$PROJECT_DIR\results\campaign_$Stamp"
aws s3 sync "s3://$bucket/campaign/" $local --region $Region
Step "Results in $local\aws_g4dn" "Green"

if ($st -ne "Success") {
    aws ssm get-command-invocation --command-id $cmdId --instance-id $instanceId --region $Region --query StandardOutputContent --output text | Select-Object -Last 40
    Step "Run did not succeed ($st) - keeping the stack for debugging. Re-run with -SkipDeploy after fixing, or destroy:" "Red"
    Step "  cd deploy\aws-cdk; npx cdk destroy $StackName --context region=$Region --context account=$account --force" "Red"
    exit 1
}
if (-not $KeepStack) {
    Push-Location "$PROJECT_DIR\deploy\aws-cdk"
    Step "cdk destroy $StackName ..."
    npx cdk destroy $StackName --context region=$Region --context account=$account --force
    Pop-Location
}
