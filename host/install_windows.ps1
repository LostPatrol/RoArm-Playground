# Install the native Windows host in a project venv, without changing drivers.
[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$Python = 'D:\softwares\miniconda\python.exe',
    [switch]$SkipDownloads
)
$ErrorActionPreference = 'Stop'
# Fixed upstream release matches the Linux director build.
$Release = 'b4514'
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$DownloadDir = Join-Path $ProjectRoot 'data\cache\downloads'
$ModelDir = Join-Path $ProjectRoot 'models'
$ToolDir = Join-Path $ProjectRoot "tools\llama-$Release"
$VenvPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

function Invoke-Python {
    # Surface native Python failures to unattended installation callers.
    param([string]$Executable, [string[]]$Arguments)
    $ErrorActionPreference = 'Continue'
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python command failed (exit $LASTEXITCODE)." }
}

function Get-Artifact {
    # Reuse pinned files and replace downloads only after successful validation.
    param([string]$Path, [string]$Url, [string]$Sha256 = '')
    if (Test-Path -LiteralPath $Path) {
        if (!$Sha256 -or (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -eq $Sha256) { return }
    }
    # Native stderr can contain retry notices; the exit code determines failure.
    $ErrorActionPreference = 'Continue'
    & curl.exe --silent --show-error --fail --location --retry 3 --connect-timeout 20 --max-time 3600 $Url --output "$Path.part"
    $ErrorActionPreference = 'Stop'
    if ($LASTEXITCODE -ne 0) { throw "Download failed: $Url" }
    if ($Sha256 -and (Get-FileHash -LiteralPath "$Path.part" -Algorithm SHA256).Hash -ne $Sha256) {
        throw "SHA256 mismatch: $Path.part"
    }
    Move-Item -LiteralPath "$Path.part" -Destination $Path -Force
}

function Install-Archive {
    # Verified b4514 archives place their executables and DLLs at the archive root.
    param([string]$Name, [string]$Backend, [string]$Sha256)
    $Archive = Join-Path $DownloadDir $Name
    Get-Artifact -Path $Archive -Url "https://github.com/ggml-org/llama.cpp/releases/download/$Release/$Name" -Sha256 $Sha256
    $Destination = Join-Path $ToolDir $Backend
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Expand-Archive -LiteralPath $Archive -DestinationPath $Destination -Force
}

New-Item -ItemType Directory -Path $DownloadDir, $ModelDir, (Join-Path $ProjectRoot 'data\cache\pip'),
    (Join-Path $ProjectRoot 'data\temp') -Force | Out-Null
$env:PIP_CACHE_DIR = Join-Path $ProjectRoot 'data\cache\pip'
$env:MPLCONFIGDIR = Join-Path $ProjectRoot 'data\cache\matplotlib'
$env:PYTHONUTF8 = '1'
$env:TEMP = Join-Path $ProjectRoot 'data\temp'
$env:TMP = $env:TEMP
if (!(Test-Path -LiteralPath $VenvPython)) {
    if (!(Test-Path -LiteralPath $Python)) { throw "Specify an existing Python 3.12 executable with -Python: $Python" }
    Invoke-Python -Executable $Python -Arguments @('-m', 'venv', (Join-Path $ProjectRoot '.venv'))
}
Invoke-Python -Executable $VenvPython -Arguments @('-m', 'pip', 'install', '-r', (Join-Path $ProjectRoot 'host\requirements.txt'))

# Model hashes are shared with scripts/fetch_interaction_models.sh.
$Models = @(
    @('gesture_recognizer.task', 'https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task', '97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482'),
    @('qwen2.5-1.5b-instruct-q4_k_m.gguf', 'https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/91cad51170dc346986eccefdc2dd33a9da36ead9/qwen2.5-1.5b-instruct-q4_k_m.gguf', '6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e')
)
foreach ($Model in $Models) {
    $Path = Join-Path $ModelDir $Model[0]
    if (!$SkipDownloads) { Get-Artifact -Path $Path -Url $Model[1] -Sha256 $Model[2] }
    if (!(Test-Path -LiteralPath $Path) -or (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ne $Model[2]) {
        throw "Missing or incorrect model: $Path"
    }
    "$($Model[2])  $($Model[0])" | Set-Content -LiteralPath "$Path.sha256" -Encoding ASCII
    $Model[1] | Set-Content -LiteralPath "$Path.source.txt" -Encoding ASCII
}
if (!$SkipDownloads) {
    # Hashes pin the official release bytes downloaded for the Windows deployment.
    Install-Archive -Name "llama-$Release-bin-win-avx2-x64.zip" -Backend 'cpu' -Sha256 '932386fdd6790eed49a4c1c2957ddacede379b32a0709099863c70f0b5d05c78'
    Install-Archive -Name "llama-$Release-bin-win-cuda-cu12.4-x64.zip" -Backend 'cuda' -Sha256 'df9ee8839bc48bbbbf4f43c1f26a19dd657abfa8f882c48cc8f7ac7adb7c20cc'
    Install-Archive -Name 'cudart-llama-bin-win-cu12.4-x64.zip' -Backend 'cuda' -Sha256 '8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6'
}
foreach ($Backend in 'cpu', 'cuda') {
    $Binary = Join-Path $ToolDir "$Backend\llama-server.exe"
    if (!(Test-Path -LiteralPath $Binary)) { throw "Missing native llama server: $Binary" }
}
Invoke-Python -Executable $VenvPython -Arguments @('-c', "import mediapipe, cv2, numpy; print('Host imports ready:', mediapipe.__version__, cv2.__version__, numpy.__version__)")
Write-Host 'Installed. Run host\start_windows.ps1, or install_windows_startup.ps1 as administrator.'
