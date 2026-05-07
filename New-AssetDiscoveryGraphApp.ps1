[CmdletBinding()]
param(
    [string]$DisplayName = 'AssetDiscovery Graph Reader',

    [int]$SecretYears = 2,

    [string]$OutputPath = '.\data\graph-app-credentials.json'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Import-Module (Join-Path $PSScriptRoot 'AssetToolkit.psm1') -Force

if (-not (Test-ToolkitCommand -Name 'Get-AzContext') -or -not (Test-ToolkitCommand -Name 'Get-AzAccessToken')) {
    throw 'Azure PowerShell is required for bootstrap. Install Az.Accounts and run Connect-AzAccount as an admin.'
}

$context = Get-AzContext -ErrorAction SilentlyContinue
if (-not $context) {
    throw 'No Azure context found. Run Connect-AzAccount as an admin before creating the Graph app.'
}

$graphToken = Get-ToolkitGraphAccessTokenFromAzContext
$headers = @{
    Authorization  = "Bearer $graphToken"
    'Content-Type' = 'application/json'
}

$graphServicePrincipalUri = "https://graph.microsoft.com/v1.0/servicePrincipals?`$filter=appId eq '00000003-0000-0000-c000-000000000000'&`$select=id,appId,appRoles"
$graphServicePrincipal = (Invoke-RestMethod -Method Get -Uri $graphServicePrincipalUri -Headers $headers -ErrorAction Stop).value | Select-Object -First 1
if (-not $graphServicePrincipal) {
    throw 'Microsoft Graph service principal was not found in this tenant.'
}

$deviceReadRole = @($graphServicePrincipal.appRoles | Where-Object {
    $_.value -eq 'Device.Read.All' -and $_.isEnabled -and @($_.allowedMemberTypes) -contains 'Application'
}) | Select-Object -First 1
if (-not $deviceReadRole) {
    throw 'Microsoft Graph Device.Read.All application role was not found.'
}

$requiredResourceAccess = @(
    @{
        resourceAppId  = '00000003-0000-0000-c000-000000000000'
        resourceAccess = @(
            @{
                id   = $deviceReadRole.id
                type = 'Role'
            }
        )
    }
)

$applicationBody = @{
    displayName            = $DisplayName
    signInAudience         = 'AzureADMyOrg'
    requiredResourceAccess = $requiredResourceAccess
} | ConvertTo-Json -Depth 8

Write-ToolkitLog -Message "Creating app registration '$DisplayName'."
try {
    $application = Invoke-RestMethod -Method Post -Uri 'https://graph.microsoft.com/v1.0/applications' -Headers $headers -Body $applicationBody -ErrorAction Stop
}
catch {
    throw "Failed to create the app registration. The signed-in account must be allowed to create app registrations and grant/admin-consent Microsoft Graph application permissions. Original error: $($_.Exception.Message)"
}

Write-ToolkitLog -Message 'Creating service principal.'
$servicePrincipalBody = @{ appId = $application.appId } | ConvertTo-Json
$servicePrincipal = Invoke-RestMethod -Method Post -Uri 'https://graph.microsoft.com/v1.0/servicePrincipals' -Headers $headers -Body $servicePrincipalBody -ErrorAction Stop

Write-ToolkitLog -Message 'Granting Microsoft Graph Device.Read.All application permission.'
$assignmentBody = @{
    principalId = $servicePrincipal.id
    resourceId  = $graphServicePrincipal.id
    appRoleId   = $deviceReadRole.id
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "https://graph.microsoft.com/v1.0/servicePrincipals/$($servicePrincipal.id)/appRoleAssignments" -Headers $headers -Body $assignmentBody -ErrorAction Stop | Out-Null

$secretEnd = (Get-Date).AddYears($SecretYears).ToUniversalTime().ToString('o')
$passwordBody = @{
    passwordCredential = @{
        displayName = 'AssetDiscovery automation'
        endDateTime = $secretEnd
    }
} | ConvertTo-Json -Depth 4

Write-ToolkitLog -Message "Creating client secret expiring $secretEnd."
$password = Invoke-RestMethod -Method Post -Uri "https://graph.microsoft.com/v1.0/applications/$($application.id)/addPassword" -Headers $headers -Body $passwordBody -ErrorAction Stop

$directory = Split-Path -Path $OutputPath -Parent
if ($directory -and -not (Test-Path -LiteralPath $directory)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}

$credentialPayload = [ordered]@{
    TenantId          = $context.Tenant.Id
    ClientId          = $application.appId
    ClientSecret      = $password.secretText
    SecretExpires     = $password.endDateTime
    ApplicationObject = $application.id
    ServicePrincipal  = $servicePrincipal.id
}

$credentialPayload | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $OutputPath -Encoding UTF8

[pscustomobject]@{
    TenantId         = $credentialPayload.TenantId
    ClientId         = $credentialPayload.ClientId
    SecretExpires    = $credentialPayload.SecretExpires
    CredentialOutput = $OutputPath
}
