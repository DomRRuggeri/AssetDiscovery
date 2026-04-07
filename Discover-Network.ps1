[CmdletBinding()]
param(
    [Parameter(Mandatory, ParameterSetName = 'SubnetRange')]
    [string]$Subnet,

    [Parameter(Mandatory, ParameterSetName = 'TargetList')]
    [string[]]$TargetIpAddress,

    [Parameter(Mandatory, ParameterSetName = 'TargetFile')]
    [string]$TargetFilePath,

    [int]$StartHost = 1,

    [int]$EndHost = 254,

    [switch]$NoDns,

    [switch]$NoMac,

    [int]$DelayMilliseconds = 0,

    [int]$TimeoutMilliseconds = 1000,

    [string]$OutputPath = '.\output\discovery.json'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot 'AssetToolkit.psm1') -Force

if ($PSCmdlet.ParameterSetName -eq 'SubnetRange') {
    Write-ToolkitLog -Message "Starting discovery on subnet $Subnet ($StartHost-$EndHost). DNS disabled: $NoDns. MAC disabled: $NoMac. Delay: ${DelayMilliseconds}ms."
    $prefix = $Subnet.TrimEnd('.')
    $targets = $StartHost..$EndHost | ForEach-Object { '{0}.{1}' -f $prefix, $_ }
}
else {
    if ($PSCmdlet.ParameterSetName -eq 'TargetList') {
        Write-ToolkitLog -Message "Starting discovery on explicit target list ($($TargetIpAddress.Count) hosts). DNS disabled: $NoDns. MAC disabled: $NoMac. Delay: ${DelayMilliseconds}ms."
    $targets = $TargetIpAddress
    }
    else {
        if (-not (Test-Path -LiteralPath $TargetFilePath)) {
            throw "Target file not found: $TargetFilePath"
        }

        $targets = @(Get-Content -LiteralPath $TargetFilePath | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith('#') })
        Write-ToolkitLog -Message "Starting discovery from target file $TargetFilePath ($($targets.Count) hosts). DNS disabled: $NoDns. MAC disabled: $NoMac. Delay: ${DelayMilliseconds}ms."
    }
}

$totalTargets = @($targets).Count
$currentIndex = 0

$discovered = foreach ($ipAddress in $targets) {
    $currentIndex++
    $percentComplete = if ($totalTargets -gt 0) {
        [int](($currentIndex / $totalTargets) * 100)
    }
    else {
        0
    }

    Write-Progress -Activity 'Network discovery in progress' -Status "Scanning $ipAddress ($currentIndex of $totalTargets)" -PercentComplete $percentComplete

    $pingSucceeded = $false
    try {
        $pingReply = New-Object System.Net.NetworkInformation.Ping
        $pingResult = $pingReply.Send($ipAddress, $TimeoutMilliseconds)
        $pingSucceeded = $pingResult.Status -eq [System.Net.NetworkInformation.IPStatus]::Success
    }
    catch {
        $pingSucceeded = $false
    }

    if (-not $pingSucceeded) {
        if ($DelayMilliseconds -gt 0) {
            Start-Sleep -Milliseconds $DelayMilliseconds
        }
        continue
    }

    $dnsName = $null
    if (-not $NoDns) {
        try {
            $dnsName = [System.Net.Dns]::GetHostEntry($ipAddress).HostName
        }
        catch {
        }
    }

    $macAddress = $null
    if (-not $NoMac) {
        $arpEntry = arp -a $ipAddress 2>$null | Select-String -Pattern '([0-9a-f]{2}-){5}[0-9a-f]{2}'
        if ($arpEntry) {
            $macAddress = ($arpEntry.Matches.Value | Select-Object -First 1)
        }
    }

    if ($DelayMilliseconds -gt 0) {
        Start-Sleep -Milliseconds $DelayMilliseconds
    }

    [pscustomobject]@{
        Hostname   = $dnsName
        IpAddress  = $ipAddress
        MacAddress = $macAddress
        Source     = 'network-discovery'
        LastSeen   = Get-Date
    }
}

Write-Progress -Activity 'Network discovery in progress' -Completed

$normalized = @($discovered | Normalize-ToolkitAssetRecord)
Export-ToolkitAssetFile -Assets $normalized -Path $OutputPath

Write-ToolkitLog -Message "Discovery complete. Found $($normalized.Count) responsive assets. Output: $OutputPath"
$normalized
