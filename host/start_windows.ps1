# Run the native host manager and its supervised workers with project-local logs.
[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$Server = 'http://roarm.local:8080',
    [ValidateSet('cuda', 'cpu')][string]$Backend = 'cuda'
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
# Runtime data and caches stay beside the deployment on D:.
$LogDir = Join-Path $ProjectRoot 'data\host-manager'
$TempDir = Join-Path $ProjectRoot 'data\temp'
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
New-Item -ItemType Directory -Path $LogDir, $TempDir -Force | Out-Null
$env:ROARM_DIRECTOR_BACKEND = $Backend
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONUTF8 = '1'
$env:PIP_CACHE_DIR = Join-Path $ProjectRoot 'data\cache\pip'
$env:MPLCONFIGDIR = Join-Path $ProjectRoot 'data\cache\matplotlib'
$env:CUDA_CACHE_PATH = Join-Path $ProjectRoot 'data\cache\cuda'
New-Item -ItemType Directory -Path $env:CUDA_CACHE_PATH -Force | Out-Null
$env:TEMP = $TempDir
$env:TMP = $TempDir
# Native process failures are supervised here; Task Scheduler mainly handles logon/start failures.
$RestartDelay = 3
if (!(Test-Path -LiteralPath $Python)) { throw "Run host\install_windows.ps1 first: $Python" }
Push-Location -LiteralPath $ProjectRoot
try {
    # PowerShell 5.1 redirects native stderr as error records, including harmless model warnings.
    $ErrorActionPreference = 'Continue'
    do {
        $Log = Join-Path $LogDir ('manager-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
        & $Python -m host.manager --server $Server --start-director --log-dir $LogDir *> $Log
        $ExitCode = $LASTEXITCODE
        if ($ExitCode -eq 0) { break }
        "Manager exited with $ExitCode; retrying in $RestartDelay seconds." | Out-File -LiteralPath $Log -Append
        Start-Sleep -Seconds $RestartDelay
    } while ($true)
    exit $ExitCode
} finally {
    Pop-Location
}
