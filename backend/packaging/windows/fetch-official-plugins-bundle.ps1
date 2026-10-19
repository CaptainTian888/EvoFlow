<#
.SYNOPSIS
  Windows wrapper for packaging/fetch-official-plugins-bundle.sh.

.DESCRIPTION
  Prefers Git Bash when available; otherwise extracts EVOFLOW_OFFICIAL_PLUGINS_URL
  archives with Windows tar, or syncs from EVOFLOW_OFFICIAL_PLUGINS_SOURCE /
  local cache via sync-official-plugins-bundle.ps1.
#>
$ErrorActionPreference = "Stop"

$ScriptDir = [System.IO.Path]::GetFullPath((Split-Path -Parent $MyInvocation.MyCommand.Path))
$PackagingDir = [System.IO.Path]::GetFullPath((Join-Path $ScriptDir ".."))
$Dest = Join-Path $PackagingDir "official-plugins-bundle"
$BashFetch = Join-Path $PackagingDir "fetch-official-plugins-bundle.sh"
$SyncPs1 = Join-Path $ScriptDir "sync-official-plugins-bundle.ps1"

function Test-BundleReady([string]$Root) {
  $required = @(
    "browser-use", "computer-use", "node-repl-host", "documents", "pdf",
    "presentations", "spreadsheets", "image-search", "plugin-creator", "skill-creator"
  )
  if (-not (Test-Path -LiteralPath $Root)) { return $false }
  foreach ($name in $required) {
    if (-not (Test-Path -LiteralPath (Join-Path $Root $name))) { return $false }
  }
  $helper = Join-Path $Root "cua-helper\runtime\dist\windows-helper.js"
  $addon = Join-Path $Root "cua-helper\runtime\build\Release\ax_native.node"
  return ((Test-Path -LiteralPath $helper) -and (Test-Path -LiteralPath $addon))
}

function Find-GitBash {
  $candidates = @(
    (Join-Path ${env:ProgramFiles} "Git\bin\bash.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Git\bin\bash.exe"),
    "C:\Program Files\Git\bin\bash.exe"
  )
  foreach ($c in $candidates) {
    if ($c -and (Test-Path -LiteralPath $c)) { return $c }
  }
  return $null
}

$bash = Find-GitBash
if ($bash -and (Test-Path -LiteralPath $BashFetch)) {
  Write-Host "[fetch-official-plugins] using Git Bash: $bash"
  $unixPath = ($BashFetch -replace '\\', '/')
  & $bash -lc "chmod +x `"$unixPath`" && `"$unixPath`""
  if ($LASTEXITCODE -ne 0) {
    throw "[fetch-official-plugins] bash fetch failed with exit $LASTEXITCODE"
  }
  exit 0
}

if (Test-BundleReady $Dest) {
  Write-Host "[fetch-official-plugins] OK (already populated)"
  exit 0
}

$src = [Environment]::GetEnvironmentVariable("EVOFLOW_OFFICIAL_PLUGINS_SOURCE")
if (-not [string]::IsNullOrWhiteSpace($src)) {
  Write-Host "[fetch-official-plugins] syncing from EVOFLOW_OFFICIAL_PLUGINS_SOURCE=$src"
  & $SyncPs1 -Source $src.Trim() -Dest $Dest
  if (-not (Test-BundleReady $Dest)) {
    throw "[fetch-official-plugins] sync left incomplete bundle"
  }
  Write-Host "[fetch-official-plugins] OK (synced from source dir)"
  exit 0
}

function Resolve-ReleaseAssetUrl([string]$Spec) {
  $ownerRepo = ""
  $tag = ""
  if ($Spec -match '@') {
    $parts = $Spec.Split('@', 2)
    $ownerRepo = $parts[0]
    $tag = $parts[1]
  } else {
    $tag = $Spec
    $ownerRepo = [Environment]::GetEnvironmentVariable("GITHUB_REPOSITORY")
  }
  if ([string]::IsNullOrWhiteSpace($ownerRepo) -or [string]::IsNullOrWhiteSpace($tag)) {
    throw "[fetch-official-plugins] EVOFLOW_OFFICIAL_PLUGINS_RELEASE needs owner/repo@tag"
  }
  $api = "https://api.github.com/repos/$ownerRepo/releases/tags/$tag"
  $headers = @{ Accept = "application/vnd.github+json"; "User-Agent" = "evoflow-fetch-official-plugins" }
  $token = [Environment]::GetEnvironmentVariable("EVOFLOW_OFFICIAL_PLUGINS_TOKEN")
  if ([string]::IsNullOrWhiteSpace($token)) {
    $token = [Environment]::GetEnvironmentVariable("GITHUB_TOKEN")
  }
  if (-not [string]::IsNullOrWhiteSpace($token)) {
    $headers["Authorization"] = "Bearer $($token.Trim())"
  }
  $payload = Invoke-RestMethod -Uri $api -Headers $headers
  $wanted = @("official-plugins-bundle.tar.gz", "official-plugins-bundle.tgz", "official-plugins-bundle.zip")
  foreach ($name in $wanted) {
    $asset = @($payload.assets | Where-Object { $_.name -eq $name }) | Select-Object -First 1
    if ($null -ne $asset) {
      if ($asset.url) { return [string]$asset.url }
      if ($asset.browser_download_url) { return [string]$asset.browser_download_url }
    }
  }
  throw "[fetch-official-plugins] release $Spec has no official-plugins-bundle archive"
}

function Install-FromArchiveUrl([string]$Url) {
  $tmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("evoflow-plugins-" + [guid]::NewGuid().ToString("N"))
  New-Item -ItemType Directory -Path $tmpRoot -Force | Out-Null
  try {
    $archive = if ($Url -match '\.zip($|\?)') {
      Join-Path $tmpRoot "bundle.zip"
    } else {
      Join-Path $tmpRoot "bundle.tar.gz"
    }
    Write-Host "[fetch-official-plugins] downloading $Url"
    $headers = @{ "User-Agent" = "evoflow-fetch-official-plugins" }
    $token = [Environment]::GetEnvironmentVariable("EVOFLOW_OFFICIAL_PLUGINS_TOKEN")
    if ([string]::IsNullOrWhiteSpace($token)) {
      $token = [Environment]::GetEnvironmentVariable("GITHUB_TOKEN")
    }
    if ($Url -match 'api\.github\.com/.*/releases/assets/') {
      $headers["Accept"] = "application/octet-stream"
      if (-not [string]::IsNullOrWhiteSpace($token)) {
        $headers["Authorization"] = "Bearer $($token.Trim())"
      }
    } elseif ((-not [string]::IsNullOrWhiteSpace($token)) -and ($Url -match 'github\.com')) {
      $headers["Authorization"] = "Bearer $($token.Trim())"
    }
    Invoke-WebRequest -Uri $Url -OutFile $archive -Headers $headers
    $extract = Join-Path $tmpRoot "extract"
    New-Item -ItemType Directory -Path $extract -Force | Out-Null
    if ($archive -like "*.zip") {
      Expand-Archive -LiteralPath $archive -DestinationPath $extract -Force
    } else {
      tar -xzf $archive -C $extract
    }
    $srcDir = $extract
    $nested = Join-Path $extract "official-plugins-bundle"
    if (Test-Path -LiteralPath $nested) {
      $srcDir = $nested
    } else {
      $kids = @(Get-ChildItem -LiteralPath $extract -Directory -ErrorAction SilentlyContinue)
      if ($kids.Count -eq 1) { $srcDir = $kids[0].FullName }
    }
    if (-not (Test-BundleReady $srcDir)) {
      throw "[fetch-official-plugins] archive contents incomplete under $srcDir"
    }
    New-Item -ItemType Directory -Path $Dest -Force | Out-Null
    Get-ChildItem -LiteralPath $Dest -Force -ErrorAction SilentlyContinue | ForEach-Object {
      if ($_.Name -eq ".gitignore") { return }
      Remove-Item -LiteralPath $_.FullName -Recurse -Force
    }
    Copy-Item -Path (Join-Path $srcDir "*") -Destination $Dest -Recurse -Force
    if (-not (Test-Path -LiteralPath (Join-Path $Dest ".gitignore"))) {
      @(
        "# Populated by packaging sync/fetch (do not commit blobs).",
        "*",
        "!.gitignore"
      ) | Set-Content -LiteralPath (Join-Path $Dest ".gitignore") -Encoding utf8
    }
  } finally {
    Remove-Item -LiteralPath $tmpRoot -Recurse -Force -ErrorAction SilentlyContinue
  }
}

$url = [Environment]::GetEnvironmentVariable("EVOFLOW_OFFICIAL_PLUGINS_URL")
$release = [Environment]::GetEnvironmentVariable("EVOFLOW_OFFICIAL_PLUGINS_RELEASE")
if ([string]::IsNullOrWhiteSpace($url) -and (-not [string]::IsNullOrWhiteSpace($release))) {
  $url = Resolve-ReleaseAssetUrl $release.Trim()
}
if (-not [string]::IsNullOrWhiteSpace($url)) {
  Install-FromArchiveUrl $url.Trim()
  if (-not (Test-BundleReady $Dest)) {
    throw "[fetch-official-plugins] download left incomplete bundle"
  }
  Write-Host "[fetch-official-plugins] OK (from URL/release)"
  exit 0
}

# Fall back to local cache sync.
Write-Host "[fetch-official-plugins] trying local cache sync..."
& $SyncPs1 -Dest $Dest
if (Test-BundleReady $Dest) {
  Write-Host "[fetch-official-plugins] OK (synced from local cache)"
  exit 0
}

# All sources failed -- generate stub bundle so CI build can proceed.
Write-Host @"
[fetch-official-plugins] WARNING: official-plugins-bundle is empty and no source was configured.
Generating stub bundle so the build can proceed without real plugin binaries.

To bundle real plugins, set one of:
  - EVOFLOW_OFFICIAL_PLUGINS_URL to a .tar.gz/.zip of the bundle
  - EVOFLOW_OFFICIAL_PLUGINS_RELEASE=owner/repo@tag (asset: official-plugins-bundle.tar.gz)
  - EVOFLOW_OFFICIAL_PLUGINS_SOURCE to a local cache directory
"@

$stubDirs = @(
  "browser-use", "computer-use", "node-repl-host", "documents", "pdf",
  "presentations", "spreadsheets", "image-search", "plugin-creator", "skill-creator"
)
New-Item -ItemType Directory -Path $Dest -Force | Out-Null
foreach ($name in $stubDirs) {
  $dir = Join-Path $Dest $name
  New-Item -ItemType Directory -Path $dir -Force | Out-Null
  @{ name = $name; version = "0.0.0-stub"; description = "stub - real plugin not bundled" } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dir "plugin.json") -Encoding utf8
}
$helperDir = Join-Path $Dest "cua-helper\runtime\dist"
$addonDir = Join-Path $Dest "cua-helper\runtime\build\Release"
New-Item -ItemType Directory -Path $helperDir -Force | Out-Null
New-Item -ItemType Directory -Path $addonDir -Force | Out-Null
Set-Content -LiteralPath (Join-Path $helperDir "windows-helper.js") -Value "// stub`n" -Encoding utf8
[byte[]] $zeroByte = 0
[System.IO.File]::WriteAllBytes((Join-Path $addonDir "ax_native.node"), $zeroByte)
if (-not (Test-Path -LiteralPath (Join-Path $Dest ".gitignore"))) {
  @(
    "# Populated by packaging sync/fetch (do not commit blobs).",
    "*",
    "!.gitignore"
  ) | Set-Content -LiteralPath (Join-Path $Dest ".gitignore") -Encoding utf8
}
Write-Host "[fetch-official-plugins] OK (stub bundle generated)"
