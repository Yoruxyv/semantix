$BackendRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Names = @(
    "__pycache__"
    ".ruff_cache"
    ".mypy_cache"
    ".pytest_cache"
    ".cache"
)

Get-ChildItem -Path $BackendRoot -Directory -Recurse -Force |
    Where-Object {
        $Names -contains $_.Name -or $_.Name -like "*.egg-info"
    } |
    Sort-Object FullName -Descending |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Removed backend caches and editable-install metadata."
