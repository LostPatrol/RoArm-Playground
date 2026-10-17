# Upload a ready-built static site and publish a versioned Nginx release.
param([string]$SshTarget = 'aliyun')
$ErrorActionPreference = 'Stop'

# Resolve all local inputs relative to this script, never the caller's folder.
$tutorialRoot = Split-Path $PSScriptRoot -Parent
$projectRoot = Split-Path $tutorialRoot -Parent
$release = Get-Date -Format 'yyyyMMdd-HHmmss'
$work = Join-Path $projectRoot 'agent/codex/deploy'
$archive = Join-Path $work "tutorial-$release.tar.gz"
$remoteArchive = "/tmp/roarm-tutorial-$release.tar.gz"
$remoteInstaller = "/tmp/roarm-tutorial-install-$release.sh"
New-Item -ItemType Directory -Force -Path $work | Out-Null
if (!(Test-Path (Join-Path $tutorialRoot 'site/index.html'))) {
    throw 'Build tutorial/site before deploying.'
}
& tar -czf $archive -C (Join-Path $tutorialRoot 'site') .
if ($LASTEXITCODE -ne 0) { throw 'Site archive failed.' }
& scp $archive "${SshTarget}:$remoteArchive"
if ($LASTEXITCODE -ne 0) { throw 'Archive upload failed.' }
& scp (Join-Path $PSScriptRoot 'install_server.sh') "${SshTarget}:$remoteInstaller"
if ($LASTEXITCODE -ne 0) { throw 'Installer upload failed.' }
& ssh $SshTarget "sh $remoteInstaller $release $remoteArchive"
if ($LASTEXITCODE -ne 0) { throw 'Server publication failed; inspect the reported error.' }
Write-Host 'Published: http://47.93.249.150/tutorial/'
