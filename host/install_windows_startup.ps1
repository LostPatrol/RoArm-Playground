# Register an interactive logon task and RK-only firewall access; run elevated.
[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$RkAddress = '192.168.112.122',
    [string]$RkHost = 'roarm.local',
    [ValidateSet('cuda', 'cpu')][string]$Backend = 'cuda'
)
$ErrorActionPreference = 'Stop'
# Stable names allow this script to update only its own task and rules.
$TaskName = 'RoArm-M2 Host'
$RuleName = 'RoArm-M2 Host RK'
$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
if (!$Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script in PowerShell as administrator to register startup/firewall rules.'
}
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask) {
    # Apply new server/backend settings to the running instance as well as its definition.
    Stop-ScheduledTask -TaskName $TaskName
    for ($Attempt = 0; $Attempt -lt 50; $Attempt++) {
        if ((Get-ScheduledTask -TaskName $TaskName).State -ne 'Running') { break }
        Start-Sleep -Milliseconds 200
    }
    if ((Get-ScheduledTask -TaskName $TaskName).State -eq 'Running') {
        throw 'The existing RoArm host task is still stopping; retry after it exits.'
    }
}
try {
    Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    New-NetFirewallRule -DisplayName $RuleName -Direction Inbound -Action Allow -Protocol TCP `
        -LocalPort 8081, 8082 -RemoteAddress $RkAddress -Profile Any | Out-Null
} catch {
    # Webpage startup remains useful even if model access needs manual firewall repair.
    Write-Warning $_.Exception.Message
}
$Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' +
    (Join-Path $ProjectRoot 'host\start_windows.ps1') + '" -ProjectRoot "' + $ProjectRoot +
    '" -Server "http://' + $RkHost + ':8080" -Backend ' + $Backend
$Action = New-ScheduledTaskAction -Execute (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') `
    -Argument $Arguments -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $Identity.Name
$TaskPrincipal = New-ScheduledTaskPrincipal -UserId $Identity.Name -LogonType Interactive -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -MultipleInstances IgnoreNew `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Priority 5
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $TaskPrincipal `
    -Settings $Settings -Description 'Native RoArm-M2 host model manager; starts after user logon.' -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Registered $TaskName for $($Identity.Name); initial RK address: $RkAddress."
& (Join-Path $PSScriptRoot 'install_windows_web.ps1') -ProjectRoot $ProjectRoot -RkHost $RkHost
