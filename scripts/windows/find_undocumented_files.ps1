[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$DocumentableExtensions = @(
    ".conf"
    ".css"
    ".example"
    ".html"
    ".js"
    ".json"
    ".mjs"
    ".ps1"
    ".py"
    ".sh"
    ".sql"
    ".toml"
    ".ts"
    ".tsx"
    ".yaml"
    ".yml"
)

function Get-RepositoryRoot {
    $Root = & git -C $PSScriptRoot rev-parse --show-toplevel
    if ($LASTEXITCODE -ne 0 -or -not $Root) {
        throw "Run this script from inside a Git repository."
    }

    return $Root.Trim()
}

function Get-ProjectFiles {
    param(
        [Parameter(Mandatory)]
        [string] $RepositoryRoot
    )

    $Files = & git -C $RepositoryRoot ls-files --cached --others --exclude-standard
    if ($LASTEXITCODE -ne 0) {
        throw "Could not list project files."
    }

    $IgnoredTrackedFiles = & git -C $RepositoryRoot ls-files `
        --cached `
        --ignored `
        --exclude-standard
    if ($LASTEXITCODE -ne 0) {
        throw "Could not evaluate ignored tracked files."
    }

    $IgnoredTracked = [System.Collections.Generic.HashSet[string]]::new(
        [System.StringComparer]::OrdinalIgnoreCase
    )
    foreach ($IgnoredFile in $IgnoredTrackedFiles) {
        [void] $IgnoredTracked.Add($IgnoredFile)
    }

    return $Files | Where-Object {
        $_ -and -not $IgnoredTracked.Contains($_)
    }
}

function Test-DocumentationCandidate {
    param(
        [Parameter(Mandatory)]
        [string] $Path
    )

    $NormalizedPath = $Path.Replace("\", "/")
    $Name = [System.IO.Path]::GetFileName($NormalizedPath)
    $Extension = [System.IO.Path]::GetExtension($Name).ToLowerInvariant()

    if ($DocumentableExtensions -notcontains $Extension) {
        return $false
    }

    if (
        $NormalizedPath -like "docs/*" -or
        $NormalizedPath -like "apps/server/tests/*" -or
        $NormalizedPath -like "apps/web/tests/*" -or
        $NormalizedPath -like ".github/ISSUE_TEMPLATE/*" -or
        $Name -eq "__init__.py" -or
        $Name -in @("package.json", "package-lock.json", "uv.lock")
    ) {
        return $false
    }

    return $true
}

$RepositoryRoot = Get-RepositoryRoot
$ProjectFiles = Get-ProjectFiles -RepositoryRoot $RepositoryRoot
$MarkdownFiles = $ProjectFiles | Where-Object {
    [System.IO.Path]::GetExtension($_).Equals(
        ".md",
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

$DocumentationText = foreach ($MarkdownFile in $MarkdownFiles) {
    $AbsolutePath = Join-Path $RepositoryRoot $MarkdownFile
    if (Test-Path -LiteralPath $AbsolutePath -PathType Leaf) {
        [System.IO.File]::ReadAllText($AbsolutePath).Replace("\", "/")
    }
}
$DocumentationCorpus = $DocumentationText -join "`n"

$Candidates = $ProjectFiles |
    Where-Object { Test-DocumentationCandidate -Path $_ } |
    ForEach-Object { $_.Replace("\", "/") } |
    Sort-Object -Unique

$Undocumented = $Candidates | Where-Object {
    $DocumentationCorpus.IndexOf(
        $_,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -lt 0
}

Write-Output ("=" * 72)
Write-Output "SEMANTIX DOCUMENTATION COVERAGE REPORT"
Write-Output ("=" * 72)
Write-Output "Definition: documented means the exact repository-relative path appears in Markdown."
Write-Output "Excluded: tests, package markers, package manifests, lockfiles, ignored files,"
Write-Output "          dependencies, and build output."
Write-Output "Scanned files: $($Candidates.Count)"
Write-Output "Undocumented files: $($Undocumented.Count)"

if (-not $Undocumented) {
    Write-Output ""
    Write-Output "Every scanned project file is referenced in the documentation."
    exit 0
}

$Groups = $Undocumented |
    Group-Object {
        $Extension = [System.IO.Path]::GetExtension($_).ToLowerInvariant()
        if ($Extension) { $Extension } else { "<none>" }
    } |
    Sort-Object Name

foreach ($Group in $Groups) {
    $FileLabel = if ($Group.Count -eq 1) { "file" } else { "files" }
    Write-Output ""
    Write-Output "[$($Group.Name.ToUpperInvariant())] $($Group.Count) undocumented $FileLabel"
    Write-Output ("-" * 72)
    foreach ($File in $Group.Group) {
        Write-Output "  $File"
    }
}
