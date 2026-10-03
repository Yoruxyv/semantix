$BackendRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$CacheRoot = Join-Path $BackendRoot ".cache"

$env:PYTHONPYCACHEPREFIX = Join-Path $CacheRoot "python"

@(
    $env:PYTHONPYCACHEPREFIX
    (Join-Path $CacheRoot "ruff")
    (Join-Path $CacheRoot "mypy")
    (Join-Path $CacheRoot "pytest")
) | ForEach-Object {
    New-Item -ItemType Directory -Path $_ -Force | Out-Null
}

Write-Host "Backend caches are centralized under $CacheRoot"
Write-Host "PYTHONPYCACHEPREFIX=$env:PYTHONPYCACHEPREFIX"
