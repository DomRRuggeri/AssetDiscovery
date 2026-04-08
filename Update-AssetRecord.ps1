[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$AssetId,

    [string]$DatabasePath = '.\data\assets.db',

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

Import-Module (Join-Path $PSScriptRoot 'AssetToolkit.psm1') -Force
$pythonPath = Get-ToolkitPythonPath

$arguments = @(
    '.\db\db_tool.py'
    'update-asset'
    '--db-path'
    $DatabasePath
    '--asset-id'
    $AssetId
)

$optionalParameters = @{
    '--hostname' = $Hostname
    '--ip-address' = $IpAddress
    '--mac-address' = $MacAddress
    '--asset-type' = $AssetType
    '--operating-system' = $OperatingSystem
    '--owner' = $Owner
    '--environment' = $Environment
    '--status' = $Status
    '--notes' = $Notes
}

foreach ($key in $optionalParameters.Keys) {
    $value = $optionalParameters[$key]
    if ($null -ne $value -and -not [string]::IsNullOrWhiteSpace($value)) {
        $arguments += @($key, $value)
    }
}

Write-Host "Updating asset $AssetId in $DatabasePath"
$result = & $pythonPath @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Asset update failed: $result"
}

$result | ConvertFrom-Json
