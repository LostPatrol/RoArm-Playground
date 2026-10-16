# Register a user-logon watcher and a desktop shortcut for the stable RK webpage.
[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$RkHost = 'roarm.local'
)
$ErrorActionPreference = 'Stop'
# The watcher needs elevation only to maintain this project's existing model firewall rule.
$TaskName = 'RoArm-M2 Web'
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
if (!$Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script in PowerShell as administrator.'
}
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$Script = Join-Path $ProjectRoot 'host\open_windows.ps1'
if (!(Test-Path -LiteralPath $Script)) { throw "Missing webpage watcher: $Script" }
$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing) { Stop-ScheduledTask -TaskName $TaskName }
$Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $Script +
    '" -ProjectRoot "' + $ProjectRoot + '" -RkHost "' + $RkHost + '"'
$Action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $Arguments
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $Identity.Name
$TaskPrincipal = New-ScheduledTaskPrincipal -UserId $Identity.Name -LogonType Interactive -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $TaskPrincipal `
    -Settings $Settings -Description 'Wait for the RK local webpage, update model access, and open the browser.' -Force | Out-Null
$Desktop = [Environment]::GetFolderPath('Desktop')
"[InternetShortcut]`r`nURL=http://$RkHost`:8080/" | Set-Content -LiteralPath (Join-Path $Desktop 'RoArm Playground.url') -Encoding ASCII
Start-ScheduledTask -TaskName $TaskName
Write-Host "Registered $TaskName; desktop shortcut: RoArm Playground."
