# Wait for the RK webpage, update its model access rule, and open the default browser.
[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$RkHost = 'roarm.local',
    [switch]$Once
)
$ErrorActionPreference = 'Stop'
# A short polling interval also handles an RK powered on after the laptop has logged in.
$PollSeconds = 5
$RequestTimeoutMs = 3000
# Retry Windows' negative local-name cache no more than once a minute while waiting.
$DnsRefreshSeconds = 60
$LastDnsRefresh = [DateTime]::MinValue
$Url = 'http://' + $RkHost + ':8080/'
$LogDir = Join-Path $ProjectRoot 'data\host-manager'
$StatusPath = Join-Path $LogDir 'web.json'
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$BrowserOpened = $false
$RuleAddress = ''
$State = @{status='waiting'; url=$Url; address=''; opened_count=0; error=''; firewall_error=''; proxy_error=''}
# Clear an earlier run's ready status before a potentially slow name lookup.
$State.checked_at = (Get-Date).ToString('o')
$State | ConvertTo-Json | Set-Content -LiteralPath $StatusPath -Encoding UTF8
do {
    $WaitingForNetwork = $true
    $State.proxy_error = ''
    # Proxy apps can start after this watcher and replace the dotted .local exception.
    try {
        $ProxyPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
        $ProxySettings = Get-ItemProperty $ProxyPath
        $Bypass = @(([string]$ProxySettings.ProxyOverride -split ';') | Where-Object { $_ })
        if ($Bypass -notcontains $RkHost) {
            Set-ItemProperty $ProxyPath -Name ProxyOverride -Value (($Bypass + $RkHost) -join ';')
        }
    } catch { $State.proxy_error = $_.Exception.Message }
    try {
        $Addresses = @([System.Net.Dns]::GetHostAddresses($RkHost) | Where-Object {
            $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork
        })
        if (!$Addresses.Count) { throw 'The RK local name has no IPv4 address yet.' }
        $Address = ''
        foreach ($Candidate in $Addresses) {
            try {
                # Use the address that actually answers HTTP when multiple interfaces are advertised.
                $CandidateUrl = 'http://' + $Candidate.IPAddressToString + ':8080/'
                $Request = [System.Net.HttpWebRequest]::Create($CandidateUrl)
                $Request.Proxy = $null
                $Request.Timeout = $RequestTimeoutMs
                $Response = $Request.GetResponse()
                try {
                    if ([int]$Response.StatusCode -eq 200) { $Address = $Candidate.IPAddressToString }
                } finally {
                    $Response.Close()
                }
            } catch {
                continue
            }
            if ($Address) { break }
        }
        if (!$Address) { throw 'The RK webpage is not reachable yet.' }
        $WaitingForNetwork = $false
        $State.address = $Address
        $State.firewall_error = ''
        if ($Address -ne $RuleAddress) {
            try {
                # Keep model ports limited to the currently discovered RK, including Public networks.
                Set-NetFirewallRule -DisplayName 'RoArm-M2 Host RK' -RemoteAddress $Address
                $RuleAddress = $Address
            } catch {
                # Basic webpage use remains available when model access cannot be updated.
                $State.firewall_error = $_.Exception.Message
            }
        }
        try {
            # Validate the browser's route using fresh Windows proxy settings each time.
            $Request = [System.Net.HttpWebRequest]::Create($Url)
            $Request.Proxy = [System.Net.WebRequest]::GetSystemWebProxy()
            $Request.Timeout = $RequestTimeoutMs
            $Response = $Request.GetResponse()
            try {
                if ([int]$Response.StatusCode -ne 200) { throw 'The RK browser URL did not return HTTP 200.' }
            } finally {
                $Response.Close()
            }
        } catch {
            $State.proxy_error = $_.Exception.Message
            throw
        }
        if (!$BrowserOpened) {
            Start-Process $Url
            $BrowserOpened = $true
            $State.opened_count++
            $State.opened_at = (Get-Date).ToString('o')
        }
        $State.status = 'ready'
        $State.error = ''
    } catch {
        if ($WaitingForNetwork -and ((Get-Date) - $LastDnsRefresh).TotalSeconds -ge $DnsRefreshSeconds) {
            Clear-DnsClientCache -ErrorAction SilentlyContinue
            $LastDnsRefresh = Get-Date
        }
        $State.status = 'waiting'
        $State.error = $_.Exception.Message
    }
    $State.checked_at = (Get-Date).ToString('o')
    $State | ConvertTo-Json | Set-Content -LiteralPath $StatusPath -Encoding UTF8
    if ($Once) {
        if ($State.status -ne 'ready') { throw $State.error }
        break
    }
    # The browser opens once per watcher session; address changes only update model access.
    Start-Sleep -Seconds $PollSeconds
} while ($true)
