[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$SourcePath,

    [string]$InventoryPath = '.\data\asset-inventory.json'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot 'AssetToolkit.psm1') -Force

Write-ToolkitLog -Message "Loading source inventory from $SourcePath."
$incomingAssets = @(Import-ToolkitAssetFile -Path $SourcePath)

$existingAssets = @()
if (Test-Path -LiteralPath $InventoryPath) {
    Write-ToolkitLog -Message "Merging with existing inventory at $InventoryPath."
    $existingAssets = @(Import-ToolkitAssetFile -Path $InventoryPath)
}

$mergedAssets = @(Merge-ToolkitAssets -ExistingAssets $existingAssets -IncomingAssets $incomingAssets)
Export-ToolkitAssetFile -Assets $mergedAssets -Path $InventoryPath

Write-ToolkitLog -Message "Inventory updated. Total assets: $($mergedAssets.Count). Output: $InventoryPath"
$mergedAssets
