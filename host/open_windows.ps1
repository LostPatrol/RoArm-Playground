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
$Url = 'http://' + $RkHost + ':8080/'
$LogDir = Join-Path $ProjectRoot 'data\host-manager'
$StatusPath = Join-Path $LogDir 'web.json'
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$BrowserOpened = $false
$RuleAddress = ''
$State = @{status='waiting'; url=$Url; address=''; opened_count=0; error=''; firewall_error=''}
# Clear an earlier run's ready status before a potentially slow name lookup.
$State.checked_at = (Get-Date).ToString('o')
$State | ConvertTo-Json | Set-Content -LiteralPath $StatusPath -Encoding UTF8
do {
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
        if (!$BrowserOpened) {
            Start-Process $Url
            $BrowserOpened = $true
            $State.opened_count++
            $State.opened_at = (Get-Date).ToString('o')
        }
        $State.status = 'ready'
        $State.error = ''
    } catch {
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
