param(
    [string]$OutputDir = "dist"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PackageName = "Risk_Compliance_Review_portable_8080"
$StagingRoot = Join-Path $ProjectRoot $OutputDir
$Staging = Join-Path $StagingRoot $PackageName
$Archive = Join-Path $StagingRoot "$PackageName.zip"

Set-Location $ProjectRoot
New-Item -ItemType Directory -Force -Path $StagingRoot | Out-Null

if (Test-Path $Staging) {
    Remove-Item -LiteralPath $Staging -Recurse -Force
}
if (Test-Path $Archive) {
    Remove-Item -LiteralPath $Archive -Force
}
New-Item -ItemType Directory -Force -Path $Staging | Out-Null

$excludePathParts = @(
    ".venv",
    ".pytest_cache",
    ".pytest_local_tmp",
    ".tmp_pytest",
    ".tmp_pytest_run",
    ".tmp_portable_verify",
    ".tmp_server",
    ".vscode",
    "dist",
    "__pycache__"
)
$excludeFileNames = @()
$excludeExtensions = @(".pyc", ".pyo")

foreach ($top in Get-ChildItem -LiteralPath $ProjectRoot -Force) {
    if ($excludePathParts -contains $top.Name -or $excludeFileNames -contains $top.Name) {
        continue
    }
    $items = @($top)
    if ($top.PSIsContainer) {
        $items += Get-ChildItem -LiteralPath $top.FullName -Force -Recurse -ErrorAction SilentlyContinue
    }
    foreach ($item in $items) {
        $relative = $item.FullName.Substring($ProjectRoot.Length).TrimStart("\", "/")
        if (-not $relative) {
            continue
        }
        $parts = $relative -split "[\\/]+"
        if ($parts | Where-Object { $excludePathParts -contains $_ }) {
            continue
        }
        if (-not $item.PSIsContainer -and ($excludeFileNames -contains $item.Name -or $excludeExtensions -contains $item.Extension)) {
            continue
        }
        $target = Join-Path $Staging $relative
        if ($item.PSIsContainer) {
            New-Item -ItemType Directory -Force -Path $target | Out-Null
        } else {
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
            Copy-Item -LiteralPath $item.FullName -Destination $target -Force
        }
    }
}

$portableData = Join-Path $Staging "data"
if (Test-Path $portableData) {
    Remove-Item -LiteralPath $portableData -Recurse -Force
}
New-Item -ItemType Directory -Force -Path (Join-Path $portableData "objects") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $portableData "vector_store\chemical_rag") | Out-Null

Compress-Archive -Path (Join-Path $Staging "*") -DestinationPath $Archive -Force
Write-Host "Portable package created:"
Write-Host $Archive
