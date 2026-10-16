# Back up and deploy playground sources from Windows without changing robot firmware.
[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$RkHost = 'roarm.local',
    [string]$Key = (Join-Path $env:USERPROFILE '.ssh\roarm-rk3588'),
    [string]$KnownHosts = (Join-Path $env:USERPROFILE '.ssh\known_hosts'),
    [switch]$SyncOnly
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
# Match deploy_camera.sh application sources; keep board models and firmware untouched.
$Assets = @('camera_server.py', 'arm_serial.py', 'playground.py', 'follow_control.py',
    'vision.py', 'control.html', 'playground.js', 'playground.css', 'arm_adapter.js',
    'README.md', 'install_discovery.sh', 'prefer_hotspot.sh')
$SshOptions = @('-i', $Key, '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
    '-o', 'HostKeyAlias=roarm-rk3588', '-o', 'StrictHostKeyChecking=yes',
    '-o', ('UserKnownHostsFile=' + $KnownHosts.Replace('\', '/')))
$Target = "root@$RkHost"
$Token = [Guid]::NewGuid().ToString('N')
# Keep temporary deployment data beside the Windows project, not on the system drive.
$TempDir = Join-Path $ProjectRoot 'data\temp'
$Stage = Join-Path $TempDir "roarm-deploy-$Token"
$Archive = "$Stage.tar.gz"
$RemoteArchive = "/tmp/roarm-deploy-$Token.tar.gz"

function Invoke-RkPython([string]$Code) {
    <# Run a standalone script with the deployed project's Python. #>
    # A finite remote pipe avoids Windows OpenSSH waiting indefinitely for stdin EOF.
    $Encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Code))
    & ssh @SshOptions $Target "echo $Encoded | base64 --decode | /opt/roarm-camera/.venv/bin/python -"
    if ($LASTEXITCODE -ne 0) { throw 'RK operation failed; see output above.' }
}

if (!(Test-Path -LiteralPath $Key)) { throw "Missing RK SSH key: $Key" }
if ($RkHost -notmatch '^[a-zA-Z0-9.:-]+$') { throw 'Invalid RK host.' }
$IdleCheck = @'
import json
from urllib.request import ProxyHandler, build_opener
with build_opener(ProxyHandler({})).open('http://127.0.0.1:8080/api/state', timeout=5) as response:
    state = json.load(response)
if state.get('mode') != 'manual' or state.get('running') or state.get('job'):
    raise SystemExit('RK is active. Stop the experiment/job in the web page first; no restart performed.')
print('RK is in manual mode without an active job.')
'@
try {
    if (!$SyncOnly) { Invoke-RkPython $IdleCheck }
    New-Item -ItemType Directory -Path $Stage -Force | Out-Null
    foreach ($Asset in $Assets) {
        Copy-Item -LiteralPath (Join-Path $ProjectRoot "rk3588\$Asset") -Destination $Stage
    }
    # Copy source files rather than Windows bytecode or other generated host files.
    $HostStage = New-Item -ItemType Directory -Path (Join-Path $Stage 'host')
    Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'host') -File |
        Where-Object { $_.Extension -in '.py', '.ps1', '.sh', '.txt' } |
        Copy-Item -Destination $HostStage.FullName
    $DocsStage = New-Item -ItemType Directory -Path (Join-Path $Stage 'docs')
    Copy-Item -LiteralPath (Join-Path $ProjectRoot 'docs\playground') -Destination $DocsStage.FullName -Recurse
    foreach ($Doc in @('wifi-startup.md', 'baseboard-replacement.md', 'servo-diagnostics.md')) {
        Copy-Item -LiteralPath (Join-Path $ProjectRoot "docs\$Doc") -Destination $DocsStage.FullName
    }
    # Windows checkouts may use CRLF; deployed shell scripts require LF.
    foreach ($File in (Get-ChildItem -LiteralPath $Stage -Recurse -File)) {
        $Text = [IO.File]::ReadAllText($File.FullName).Replace("`r`n", "`n").Replace("`r", "`n")
        [IO.File]::WriteAllText($File.FullName, $Text, [System.Text.UTF8Encoding]::new($false))
    }
    & tar -czf $Archive -C $Stage .
    if ($LASTEXITCODE -ne 0) { throw 'Cannot package deployment sources.' }
    & scp @SshOptions $Archive "${Target}:$RemoteArchive"
    if ($LASTEXITCODE -ne 0) { throw 'Cannot upload deployment archive.' }
    $DeployCode = @'
import py_compile
import shutil
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
root = Path('/opt/roarm-camera')
archive = Path('REMOTE_ARCHIVE')
backup = root / 'backups' / ('windows-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
try:
    with tempfile.TemporaryDirectory(prefix='roarm-deploy-') as temporary:
        stage = Path(temporary)
        with tarfile.open(archive) as package:
            package.extractall(stage)
        for source in stage.rglob('*.py'):
            py_compile.compile(str(source), doraise=True)
        backup.mkdir(parents=True)
        for source in stage.iterdir():
            if source.name == '__pycache__':
                continue
            destination = root / source.name
            if destination.exists():
                if destination.is_dir():
                    shutil.copytree(destination, backup / source.name)
                else:
                    shutil.copy2(destination, backup / source.name)
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            else:
                shutil.copy2(source, destination)
            installed = [destination] + (list(destination.rglob('*')) if destination.is_dir() else [])
            for path in installed:
                path.chmod(0o755 if path.is_dir() else 0o644)
        print('Deployment backup:', backup)
finally:
    archive.unlink(missing_ok=True)
'@
    Invoke-RkPython ($DeployCode.Replace('REMOTE_ARCHIVE', $RemoteArchive))
    if ($SyncOnly) {
        Write-Output 'Sources synchronized; service was not restarted. Restart after stopping the current experiment.'
    } else {
        Invoke-RkPython ($IdleCheck + "`nimport subprocess`nsubprocess.run(['systemctl', 'restart', 'roarm-camera.service'], check=True)`nsubprocess.run(['systemctl', 'is-active', 'roarm-camera.service'], check=True)")
        Write-Output 'Deployment complete; refresh the web page.'
    }
} finally {
    if (Test-Path -LiteralPath $Stage) { Remove-Item -LiteralPath $Stage -Recurse -Force }
    if (Test-Path -LiteralPath $Archive) { Remove-Item -LiteralPath $Archive -Force }
}
