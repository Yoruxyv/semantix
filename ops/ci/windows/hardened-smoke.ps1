param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Command
)

$ErrorActionPreference = "Stop"
$ComposeArguments = @("compose", "-f", "docker-compose.prod.yml")

function Invoke-Compose {
    param([string[]] $Arguments)

    & docker @ComposeArguments @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose failed with exit code $LASTEXITCODE."
    }
}

function New-SmokeSecret {
    $Bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($Bytes)
    return [Convert]::ToBase64String($Bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function Get-Sha256 {
    param([string] $Value)

    $Bytes = [System.Text.Encoding]::UTF8.GetBytes($Value)
    $Hash = [System.Security.Cryptography.SHA256]::Create().ComputeHash($Bytes)
    return ([System.BitConverter]::ToString($Hash)).Replace("-", "").ToLowerInvariant()
}

if (-not $env:POSTGRES_DB) { $env:POSTGRES_DB = "semantix" }
if (-not $env:POSTGRES_MIGRATION_USER) { $env:POSTGRES_MIGRATION_USER = "semantix_migrator" }
if (-not $env:POSTGRES_MIGRATION_PASSWORD) { $env:POSTGRES_MIGRATION_PASSWORD = New-SmokeSecret }
if (-not $env:POSTGRES_RUNTIME_USER) { $env:POSTGRES_RUNTIME_USER = "semantix_runtime" }
if (-not $env:POSTGRES_RUNTIME_PASSWORD) { $env:POSTGRES_RUNTIME_PASSWORD = New-SmokeSecret }

$SmokeToken = if ($env:SMOKE_AUTH_TOKEN) {
    $env:SMOKE_AUTH_TOKEN
}
else {
    New-SmokeSecret
}
$TokenHash = Get-Sha256 -Value $SmokeToken
$ViewerToken = New-SmokeSecret
$OperatorToken = New-SmokeSecret
$ScopedAdminToken = New-SmokeSecret
$env:SEMANTIX_E2E_TOKEN = $SmokeToken
$env:SEMANTIX_E2E_VIEWER_TOKEN = $ViewerToken
$env:SEMANTIX_E2E_OPERATOR_TOKEN = $OperatorToken
$env:SEMANTIX_E2E_SCOPED_ADMIN_TOKEN = $ScopedAdminToken
$env:AUTH_PRINCIPALS = ConvertTo-Json -InputObject @(
    @{
        name = "smoke-admin"
        token_sha256 = $TokenHash
        role = "admin"
        namespaces = @("*")
    }
    @{
        name = "smoke-viewer"
        token_sha256 = Get-Sha256 -Value $ViewerToken
        role = "viewer"
        namespaces = @("alpha")
    }
    @{
        name = "smoke-operator"
        token_sha256 = Get-Sha256 -Value $OperatorToken
        role = "operator"
        namespaces = @("alpha")
    }
    @{
        name = "smoke-scoped-admin"
        token_sha256 = Get-Sha256 -Value $ScopedAdminToken
        role = "admin"
        namespaces = @("alpha")
    }
) -Compress
$UpstreamFile = Join-Path (Get-Location).Path (
    "semantix-smoke-upstream-" + [guid]::NewGuid().ToString("N") + ".conf"
)
Copy-Item -LiteralPath "apps/web/upstream.prod.conf" -Destination $UpstreamFile
$env:SEMANTIX_UPSTREAM_FILE = $UpstreamFile

try {
    Invoke-Compose -Arguments @("up", "--build", "--detach", "--wait", "--wait-timeout", "180")

    Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:18080/health" | Out-Null
    Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:18080/ready" | Out-Null

    $Headers = @{
        Authorization = "Bearer $SmokeToken"
    }
    $Body = @{
        prompt = "Hardened smoke cache verification"
    } | ConvertTo-Json

    $First = Invoke-RestMethod `
        -Method Post `
        -Uri "http://127.0.0.1:18080/api/v1/query" `
        -Headers $Headers `
        -ContentType "application/json" `
        -Body $Body
    $Second = Invoke-RestMethod `
        -Method Post `
        -Uri "http://127.0.0.1:18080/api/v1/query" `
        -Headers $Headers `
        -ContentType "application/json" `
        -Body $Body

    if ($First.cache_hit -or -not $First.provider_called) {
        throw "The first hardened query did not call the provider."
    }
    if (-not $Second.cache_hit -or $Second.provider_called) {
        throw "The second hardened query was not served from cache."
    }

    if ($Command.Count -gt 0) {
        $Executable = $Command[0]
        if ($Command.Count -eq 1) {
            & $Executable
        }
        else {
            $FollowUpArguments = $Command[1..($Command.Count - 1)]
            & $Executable @FollowUpArguments
        }
        if ($LASTEXITCODE -ne 0) { throw "Follow-up command failed with exit code $LASTEXITCODE." }
    }
}
finally {
    & docker @ComposeArguments down --volumes --remove-orphans
    Remove-Item -LiteralPath $UpstreamFile -Force -ErrorAction SilentlyContinue
}
