$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false

$ComposeArguments = @(
    "compose"
    "-f"
    "docker-compose.dev.yml"
    "-f"
    "ops/ci/docker-compose.dev-smoke.yml"
)
$BackendPort = if ($env:BACKEND_PORT) { $env:BACKEND_PORT } else { "8000" }

function Invoke-Compose {
    param(
        [string[]] $Arguments,
        [switch] $AllowFailure
    )

    & docker @ComposeArguments @Arguments | Out-Host
    $ExitCode = $LASTEXITCODE
    if ($AllowFailure) {
        return $ExitCode
    }
    if ($ExitCode -ne 0) {
        throw "Docker Compose failed with exit code $ExitCode."
    }
}

function New-SmokeSecret {
    $Bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($Bytes)
    return [Convert]::ToBase64String($Bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

try {
    $env:EMBEDDING_PROVIDER = "mock"
    $env:GENERATION_PROVIDER = "mock"
    $env:CACHE_BACKEND = "memory"

    Invoke-Compose -Arguments @("up", "--build", "--detach", "--wait", "--wait-timeout", "180")
    Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$BackendPort/health" | Out-Null
    Invoke-Compose -Arguments @("down", "--volumes", "--remove-orphans")

    $env:CACHE_BACKEND = "pgvector"
    if (-not $env:POSTGRES_USER) { $env:POSTGRES_USER = "semantix" }
    if (-not $env:POSTGRES_DB) { $env:POSTGRES_DB = "semantix" }
    if (-not $env:POSTGRES_PASSWORD) { $env:POSTGRES_PASSWORD = New-SmokeSecret }
    $env:DATABASE_URL = "postgresql://$($env:POSTGRES_USER):$($env:POSTGRES_PASSWORD)@postgres:5432/$($env:POSTGRES_DB)"

    # Official cache storage requires explicit setup before normal startup validation.
    Invoke-Compose -Arguments @("--profile", "pgvector", "up", "--no-build", "--detach", "--wait", "--wait-timeout", "180", "postgres")
    $env:MIGRATION_DATABASE_URL = $env:DATABASE_URL
    $env:DATABASE_RUNTIME_ROLE = $env:POSTGRES_USER
    Invoke-Compose -Arguments @("--profile", "pgvector", "run", "--rm", "--no-deps", "-e", "MIGRATION_DATABASE_URL", "-e", "DATABASE_RUNTIME_ROLE", "-e", "DATABASE_MIGRATION_MODE=external", "backend", "python", "-m", "app.infrastructure.migrate")
    Invoke-Compose -Arguments @("--profile", "pgvector", "up", "--build", "--detach", "--wait", "--wait-timeout", "180")
    Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$BackendPort/ready" | Out-Null
    Invoke-Compose -Arguments @("--profile", "pgvector", "down", "--volumes", "--remove-orphans")

    $env:CACHE_BACKEND = "memory"
    $env:MOCK_EMBEDDING_DIMENSIONS = "0"
    Remove-Item Env:DATABASE_URL, Env:MIGRATION_DATABASE_URL, Env:DATABASE_RUNTIME_ROLE -ErrorAction SilentlyContinue

    $ExitCode = Invoke-Compose `
        -Arguments @("up", "--build", "--detach", "--wait", "--wait-timeout", "45") `
        -AllowFailure
    if ($ExitCode -eq 0) {
        throw "Invalid backend configuration unexpectedly became healthy."
    }
}
finally {
    Invoke-Compose `
        -Arguments @("--profile", "pgvector", "down", "--volumes", "--remove-orphans") `
        -AllowFailure | Out-Null
}
