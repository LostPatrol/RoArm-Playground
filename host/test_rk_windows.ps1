# Run Linux-only core tests against isolated Windows sources on the RK, without hardware.
[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$RkHost = 'roarm.local',
    [string]$Key = (Join-Path $env:USERPROFILE '.ssh\roarm-rk3588'),
    [string]$KnownHosts = (Join-Path $env:USERPROFILE '.ssh\known_hosts')
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
# Each run gets an isolated tree; tests use fake transports, pseudo-terminals and HTTP mocks.
$Token = [Guid]::NewGuid().ToString('N')
$TempDir = Join-Path $ProjectRoot 'data\temp'
$Stage = Join-Path $TempDir "roarm-tests-$Token"
$Archive = "$Stage.tar.gz"
$RemoteArchive = "/tmp/roarm-tests-$Token.tar.gz"
$SshOptions = @('-i', $Key, '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
    '-o', 'HostKeyAlias=roarm-rk3588', '-o', 'StrictHostKeyChecking=yes',
    '-o', ('UserKnownHostsFile=' + $KnownHosts.Replace('\', '/')))
$Target = "root@$RkHost"
if (!(Test-Path -LiteralPath $Key)) { throw "Missing RK SSH key: $Key" }
if ($RkHost -notmatch '^[a-zA-Z0-9.:-]+$') { throw 'Invalid RK host.' }
try {
    New-Item -ItemType Directory -Path $Stage -Force | Out-Null
    foreach ($Directory in @('rk3588', 'host')) {
        $Destination = New-Item -ItemType Directory -Path (Join-Path $Stage $Directory)
        Get-ChildItem -LiteralPath (Join-Path $ProjectRoot $Directory) -File |
            Where-Object { $_.Extension -in '.py', '.html', '.js', '.css' } |
            Copy-Item -Destination $Destination.FullName
    }
    $TestsStage = New-Item -ItemType Directory -Path (Join-Path $Stage 'tests')
    foreach ($Test in @('arm_controls', 'playground', 'follow_control', 'camera_server')) {
        Copy-Item -LiteralPath (Join-Path $ProjectRoot "tests\test_$Test.py") -Destination $TestsStage.FullName
    }
    # Normalize text independently of the Windows Git checkout line-ending setting.
    foreach ($File in (Get-ChildItem -LiteralPath $Stage -Recurse -File)) {
        $Text = [IO.File]::ReadAllText($File.FullName).Replace("`r`n", "`n").Replace("`r", "`n")
        [IO.File]::WriteAllText($File.FullName, $Text, [System.Text.UTF8Encoding]::new($false))
    }
    & tar -czf $Archive -C $Stage .
    if ($LASTEXITCODE -ne 0) { throw 'Cannot package test sources.' }
    & scp @SshOptions $Archive "${Target}:$RemoteArchive"
    if ($LASTEXITCODE -ne 0) { throw 'Cannot upload test archive.' }
    $Code = @'
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
archive = Path('REMOTE_ARCHIVE')
try:
    with tempfile.TemporaryDirectory(prefix='roarm-tests-') as temporary:
        with tarfile.open(archive) as package:
            package.extractall(temporary)
        environment = dict(os.environ, PYTHONPATH=temporary, PYTHONDONTWRITEBYTECODE='1')
        command = ['/opt/roarm-camera/.venv/bin/python', '-m', 'unittest', 'discover', '-s', 'tests', '-v']
        result = subprocess.run(command, cwd=temporary, env=environment)
        raise SystemExit(result.returncode)
finally:
    archive.unlink(missing_ok=True)
'@
    # Supply finite stdin on the RK; Windows OpenSSH may otherwise delay the pipe EOF.
    $Encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Code.Replace('REMOTE_ARCHIVE', $RemoteArchive)))
    & ssh @SshOptions $Target "echo $Encoded | base64 --decode | /opt/roarm-camera/.venv/bin/python -"
    if ($LASTEXITCODE -ne 0) { throw 'RK core tests failed; see output above.' }
} finally {
    if (Test-Path -LiteralPath $Stage) { Remove-Item -LiteralPath $Stage -Recurse -Force }
    if (Test-Path -LiteralPath $Archive) { Remove-Item -LiteralPath $Archive -Force }
}
