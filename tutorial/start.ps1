# Open the prebuilt static course site without installing a runtime.
$ErrorActionPreference = 'Stop'
Start-Process (Join-Path $PSScriptRoot 'site/index.html')
