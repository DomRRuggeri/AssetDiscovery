[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$Search,

    [string]$DatabasePath = '.\data\assets.db',

    [int]$SelectionIndex,

    [string]$Hostname,

    [string]$IpAddress,

    [string]$MacAddress,

    [string]$AssetType,

    [string]$OperatingSystem,

    [string]$Owner,

    [string]$Environment,

    [string]$Status,

    [string]$Notes
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$matches = @(. $PSScriptRoot\Get-AssetRecords.ps1 -DatabasePath $DatabasePath -Search $Search)

if ($matches.Count -eq 0) {
    throw "No assets found for search '$Search'."
}

if ($matches.Count -eq 1) {
    $selectedAsset = $matches[0]
}
else {
    Write-Host ''
    Write-Host "Matches for '$Search':"
    for ($index = 0; $index -lt $matches.Count; $index++) {
        $asset = $matches[$index]
        $displayName = if ($asset.Hostname) { $asset.Hostname } else { '<no-hostname>' }
        $displayIp = if ($asset.IpAddress) { $asset.IpAddress } else { '<no-ip>' }
        $displayOwner = if ($asset.Owner) { $asset.Owner } else { '<no-owner>' }
        Write-Host ("[{0}] {1} | {2} | {3} | {4}" -f $index, $displayName, $displayIp, $asset.Status, $displayOwner)
    }

    $resolvedIndex = $SelectionIndex
    if (-not $PSBoundParameters.ContainsKey('SelectionIndex')) {
        $resolvedIndex = [int](Read-Host 'Enter selection index')
    }

    if ($resolvedIndex -lt 0 -or $resolvedIndex -ge $matches.Count) {
        throw "Selection index '$resolvedIndex' is out of range."
    }

    $selectedAsset = $matches[$resolvedIndex]
}

Write-Host "Selected asset: $($selectedAsset.AssetId)"

$updateArguments = @{
    AssetId      = [string]$selectedAsset.AssetId
    DatabasePath = $DatabasePath
}

foreach ($name in @('Hostname', 'IpAddress', 'MacAddress', 'AssetType', 'OperatingSystem', 'Owner', 'Environment', 'Status', 'Notes')) {
    if ($PSBoundParameters.ContainsKey($name)) {
        $updateArguments[$name] = (Get-Variable -Name $name -ValueOnly)
    }
}

. $PSScriptRoot\Update-AssetRecord.ps1 @updateArguments
