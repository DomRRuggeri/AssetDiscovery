Set-StrictMode -Version Latest

function Write-ToolkitLog {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Message,

        [ValidateSet('INFO', 'WARN', 'ERROR')]
        [string]$Level = 'INFO'
    )

    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Write-Host "[$timestamp] [$Level] $Message"
}

function Test-ToolkitCommand {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Name
    )

    return [bool](Get-Command -Name $Name -ErrorAction SilentlyContinue)
}

function Get-ToolkitPythonPath {
    [CmdletBinding()]
    param()

    $commands = @(
        (Get-Command -Name 'python' -ErrorAction SilentlyContinue),
        (Get-Command -Name 'py' -ErrorAction SilentlyContinue)
    ) | Where-Object { $_ }

    foreach ($command in $commands) {
        if ($command.Source -and $command.Source -notlike '*WindowsApps*') {
            return $command.Source
        }
    }

    $candidates = @(
        "$env:LocalAppData\Programs\Python\Python312\python.exe",
        "$env:LocalAppData\Programs\Python\Python311\python.exe",
        "$env:LocalAppData\Programs\Python\Python310\python.exe"
    )

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }

    throw 'Python runtime not found. Install Python 3.x or update PATH.'
}

function ConvertTo-ToolkitMacAddress {
    [CmdletBinding()]
    param(
        [AllowNull()]
        [AllowEmptyString()]
        [string]$MacAddress
    )

    if ([string]::IsNullOrWhiteSpace($MacAddress)) {
        return $null
    }

    $cleaned = ($MacAddress -replace '[^a-fA-F0-9]', '').ToUpperInvariant()
    if ($cleaned.Length -ne 12) {
        return $MacAddress.Trim()
    }

    return (($cleaned -split '(.{2})' | Where-Object { $_ }) -join ':')
}

function Get-ToolkitAssetKey {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [psobject]$Asset
    )

    foreach ($candidate in @($Asset.Hostname, $Asset.IpAddress, $Asset.MacAddress, $Asset.AssetId)) {
        if (-not [string]::IsNullOrWhiteSpace($candidate)) {
            return $candidate.ToString().Trim().ToLowerInvariant()
        }
    }

    return $null
}

function Get-ToolkitPropertyValue {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [psobject]$InputObject,

        [Parameter(Mandatory)]
        [string[]]$PropertyName
    )

    foreach ($name in $PropertyName) {
        $property = $InputObject.PSObject.Properties[$name]
        if ($property -and -not [string]::IsNullOrWhiteSpace([string]$property.Value)) {
            return $property.Value
        }
    }

    return $null
}

function Normalize-ToolkitAssetRecord {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory, ValueFromPipeline)]
        [psobject]$InputObject
    )

    process {
        $hostname = Get-ToolkitPropertyValue -InputObject $InputObject -PropertyName @('Hostname', 'Name', 'DeviceName', 'ComputerName')
        $ipAddress = Get-ToolkitPropertyValue -InputObject $InputObject -PropertyName @('IpAddress', 'IPAddress', 'PrivateIpAddress', 'Address')
        $macAddress = Get-ToolkitPropertyValue -InputObject $InputObject -PropertyName @('MacAddress', 'MACAddress', 'Mac')
        $assetType = Get-ToolkitPropertyValue -InputObject $InputObject -PropertyName @('AssetType', 'Type', 'Category', 'DeviceType')
        $source = Get-ToolkitPropertyValue -InputObject $InputObject -PropertyName @('Source', 'InventorySource')
        $assetId = Get-ToolkitPropertyValue -InputObject $InputObject -PropertyName @('AssetId')
        $operatingSystem = Get-ToolkitPropertyValue -InputObject $InputObject -PropertyName @('OperatingSystem')
        $owner = Get-ToolkitPropertyValue -InputObject $InputObject -PropertyName @('Owner')
        $environment = Get-ToolkitPropertyValue -InputObject $InputObject -PropertyName @('Environment')
        $lastSeen = Get-ToolkitPropertyValue -InputObject $InputObject -PropertyName @('LastSeen')
        $notes = Get-ToolkitPropertyValue -InputObject $InputObject -PropertyName @('Notes')

        [pscustomobject]@{
            AssetId         = if ($assetId) { [string]$assetId } else { [guid]::NewGuid().Guid }
            Hostname        = if ($hostname) { [string]$hostname } else { $null }
            IpAddress       = if ($ipAddress) { [string]$ipAddress } else { $null }
            MacAddress      = ConvertTo-ToolkitMacAddress -MacAddress $macAddress
            AssetType       = if ($assetType) { [string]$assetType } else { $null }
            OperatingSystem = if ($operatingSystem) { [string]$operatingSystem } else { $null }
            Owner           = if ($owner) { [string]$owner } else { $null }
            Environment     = if ($environment) { [string]$environment } else { $null }
            Source          = if ($source) { [string]$source } else { 'manual-import' }
            LastSeen        = if ($lastSeen) { [datetime]$lastSeen } else { Get-Date }
            Notes           = if ($notes) { [string]$notes } else { $null }
        }
    }
}

function Import-ToolkitAssetFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Inventory file not found: $Path"
    }

    $extension = [System.IO.Path]::GetExtension($Path)
    switch ($extension.ToLowerInvariant()) {
        '.csv' {
            return Import-Csv -LiteralPath $Path | Normalize-ToolkitAssetRecord
        }
        '.json' {
            $raw = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
            if ($raw -is [System.Collections.IEnumerable] -and -not ($raw -is [string])) {
                return $raw | Normalize-ToolkitAssetRecord
            }

            return @($raw | Normalize-ToolkitAssetRecord)
        }
        default {
            throw "Unsupported inventory format '$extension'. Use CSV or JSON."
        }
    }
}

function Export-ToolkitAssetFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [System.Collections.IEnumerable]$Assets,

        [Parameter(Mandatory)]
        [string]$Path
    )

    $directory = Split-Path -Path $Path -Parent
    if ($directory -and -not (Test-Path -LiteralPath $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }

    $serializableAssets = foreach ($asset in $Assets) {
        $copy = [ordered]@{}
        foreach ($property in $asset.PSObject.Properties) {
            if ($property.Name -eq 'LastSeen' -and $property.Value) {
                $copy[$property.Name] = ([datetime]$property.Value).ToString('o')
            }
            else {
                $copy[$property.Name] = $property.Value
            }
        }

        [pscustomobject]$copy
    }

    $serializableAssets | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Merge-ToolkitAssets {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [System.Collections.IEnumerable]$ExistingAssets,

        [Parameter(Mandatory)]
        [System.Collections.IEnumerable]$IncomingAssets
    )

    $merged = @{}

    foreach ($asset in $ExistingAssets) {
        $key = Get-ToolkitAssetKey -Asset $asset
        if ($key) {
            $merged[$key] = $asset
        }
    }

    foreach ($asset in $IncomingAssets) {
        $key = Get-ToolkitAssetKey -Asset $asset
        if (-not $key) {
            $key = [guid]::NewGuid().Guid
        }

        if ($merged.ContainsKey($key)) {
            $current = $merged[$key]
            $merged[$key] = [pscustomobject]@{
                AssetId         = if ($asset.AssetId) { $asset.AssetId } else { $current.AssetId }
                Hostname        = if ($asset.Hostname) { $asset.Hostname } else { $current.Hostname }
                IpAddress       = if ($asset.IpAddress) { $asset.IpAddress } else { $current.IpAddress }
                MacAddress      = if ($asset.MacAddress) { $asset.MacAddress } else { $current.MacAddress }
                AssetType       = if ($asset.AssetType) { $asset.AssetType } else { $current.AssetType }
                OperatingSystem = if ($asset.OperatingSystem) { $asset.OperatingSystem } else { $current.OperatingSystem }
                Owner           = if ($asset.Owner) { $asset.Owner } else { $current.Owner }
                Environment     = if ($asset.Environment) { $asset.Environment } else { $current.Environment }
                Source          = if ($asset.Source) { $asset.Source } else { $current.Source }
                LastSeen        = if ($asset.LastSeen) { $asset.LastSeen } else { $current.LastSeen }
                Notes           = if ($asset.Notes) { $asset.Notes } else { $current.Notes }
            }
        }
        else {
            $merged[$key] = $asset
        }
    }

    return $merged.Values | Sort-Object Hostname, IpAddress
}

function ConvertFrom-ToolkitSecureString {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [System.Security.SecureString]$SecureString
    )

    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureString)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function Get-ToolkitHostnameVariants {
    [CmdletBinding()]
    param(
        [AllowNull()]
        [AllowEmptyString()]
        [string]$Hostname
    )

    if ([string]::IsNullOrWhiteSpace($Hostname)) {
        return @()
    }

    $value = $Hostname.Trim().ToLowerInvariant()
    $variants = [System.Collections.Generic.List[string]]::new()
    $variants.Add($value)

    $shortName = $value.Split('.')[0]
    if ($shortName -and $shortName -ne $value) {
        $variants.Add($shortName)
    }

    return $variants | Select-Object -Unique
}

function Get-ToolkitAzureAssetSnapshot {
    [CmdletBinding()]
    param()

    $requiredCommands = @(
        'Get-AzContext',
        'Get-AzAccessToken',
        'Invoke-RestMethod'
    )

    $missingCommands = @($requiredCommands | Where-Object { -not (Test-ToolkitCommand -Name $_) })
    if ($missingCommands.Count -gt 0) {
        throw "Azure PowerShell modules are not available. Missing commands: $($missingCommands -join ', '). Install Az.Accounts."
    }

    $context = Get-AzContext -ErrorAction SilentlyContinue
    if (-not $context) {
        throw 'No Azure context found. Run Connect-AzAccount first.'
    }

    $tokenResponse = Get-AzAccessToken -ResourceTypeName MSGraph -ErrorAction Stop
    $accessToken = ConvertFrom-ToolkitSecureString -SecureString $tokenResponse.Token
    $headers = @{
        Authorization = "Bearer $accessToken"
    }

    $requestUrl = 'https://graph.microsoft.com/v1.0/devices?$select=id,deviceId,displayName,operatingSystem,operatingSystemVersion,trustType,accountEnabled,approximateLastSignInDateTime,isManaged,isCompliant'
    $results = [System.Collections.Generic.List[object]]::new()

    while ($requestUrl) {
        $response = Invoke-RestMethod -Method Get -Uri $requestUrl -Headers $headers -ErrorAction Stop
        foreach ($device in @($response.value)) {
            $results.Add([pscustomobject]@{
                Name                         = $device.displayName
                AzureDeviceId                = $device.deviceId
                AzureObjectId                = $device.id
                OperatingSystem              = $device.operatingSystem
                OperatingSystemVersion       = $device.operatingSystemVersion
                TrustType                    = $device.trustType
                AccountEnabled               = $device.accountEnabled
                ApproximateLastSignInDateTime = $device.approximateLastSignInDateTime
                IsManaged                    = $device.isManaged
                IsCompliant                  = $device.isCompliant
            })
        }

        $nextLinkProperty = $response.PSObject.Properties['@odata.nextLink']
        $requestUrl = if ($nextLinkProperty) { [string]$nextLinkProperty.Value } else { $null }
    }

    return $results
}

function Compare-ToolkitAssetsToAzure {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [System.Collections.IEnumerable]$InventoryAssets,

        [Parameter(Mandatory)]
        [System.Collections.IEnumerable]$AzureAssets
    )

    $azureByHostname = @{}
    foreach ($asset in $AzureAssets) {
        foreach ($variant in @(Get-ToolkitHostnameVariants -Hostname $asset.Name)) {
            if (-not $azureByHostname.ContainsKey($variant)) {
                $azureByHostname[$variant] = $asset
            }
        }
    }

    foreach ($inventoryAsset in $InventoryAssets) {
        $match = $null
        $matchReason = $null

        foreach ($variant in @(Get-ToolkitHostnameVariants -Hostname $inventoryAsset.Hostname)) {
            if ($azureByHostname.ContainsKey($variant)) {
                $match = $azureByHostname[$variant]
                $matchReason = if ($variant -eq $inventoryAsset.Hostname.ToLowerInvariant()) { 'hostname' } else { 'short-hostname' }
                break
            }
        }

        [pscustomobject]@{
            AssetId                = $inventoryAsset.AssetId
            InventoryName          = $inventoryAsset.Hostname
            InventoryIp            = $inventoryAsset.IpAddress
            InventoryMac           = $inventoryAsset.MacAddress
            AzureName              = if ($match) { $match.Name } else { $null }
            AzureDeviceId          = if ($match) { $match.AzureDeviceId } else { $null }
            AzureObjectId          = if ($match) { $match.AzureObjectId } else { $null }
            AzureOperatingSystem   = if ($match) { $match.OperatingSystem } else { $null }
            AzureOsVersion         = if ($match) { $match.OperatingSystemVersion } else { $null }
            AzureTrustType         = if ($match) { $match.TrustType } else { $null }
            AzureAccountEnabled    = if ($match) { $match.AccountEnabled } else { $null }
            AzureLastSignIn        = if ($match) { $match.ApproximateLastSignInDateTime } else { $null }
            AzureIsManaged         = if ($match) { $match.IsManaged } else { $null }
            AzureIsCompliant       = if ($match) { $match.IsCompliant } else { $null }
            MatchStatus            = if ($match) { 'Matched' } else { 'NotFoundInAzure' }
            MatchReason            = $matchReason
        }
    }
}

Export-ModuleMember -Function @(
    'Compare-ToolkitAssetsToAzure',
    'ConvertTo-ToolkitMacAddress',
    'Export-ToolkitAssetFile',
    'Get-ToolkitPythonPath',
    'Get-ToolkitPropertyValue',
    'Import-ToolkitAssetFile',
    'Merge-ToolkitAssets',
    'Normalize-ToolkitAssetRecord',
    'Get-ToolkitAzureAssetSnapshot',
    'Test-ToolkitCommand',
    'Write-ToolkitLog'
)
