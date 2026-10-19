<#
.SYNOPSIS
  Fill packaging/official-plugins-bundle from a local official plugin cache.

.DESCRIPTION
  Product installers only ship plugins found under official-plugins-bundle
  (gitignored blobs). Run this before build-gateway-exe.ps1, or let that script
  call it automatically when a cache is discoverable.

  Default sources (first hit wins):
    1. -Source / EVOFLOW_OFFICIAL_PLUGINS_SOURCE
    2. ~/.evoflow-dev/data/plugins/cache/evoflow-plugins-official
    3. ~/.evoflow/data/plugins/cache/evoflow-plugins-official

  CI / clean machines: use packaging/fetch-official-plugins-bundle.sh with
  EVOFLOW_OFFICIAL_PLUGINS_URL or EVOFLOW_OFFICIAL_PLUGINS_RELEASE instead.
  To publish the archive: packaging/pack-official-plugins-bundle.sh
#>
param(
  [string]$Source = "",
  [string]$Dest = "",
  [switch]$Force
)

$ErrorActionPreference = "Stop"

$ScriptDir = [System.IO.Path]::GetFullPath((Split-Path -Parent $MyInvocation.MyCommand.Path))
$BackendDir = [System.IO.Path]::GetFullPath((Join-Path $ScriptDir "..\.."))

if ([string]::IsNullOrWhiteSpace($Dest)) {
  $Dest = Join-Path $BackendDir "packaging\official-plugins-bundle"
}

# Must match evoflow.plugins.builtin.BUNDLED_OFFICIAL_PLUGIN_NAMES (+ cua-helper runtime).
$RequiredPlugins = @(
  "browser-use",
  "computer-use",
  "documents",
  "pdf",
  "presentations",
  "spreadsheets",
  "image-search",
  "plugin-creator",
  "skill-creator",
  "node-repl-host"
)
$RuntimeDirs = @("cua-helper")
$SkipNames = @(
  "evoflow-guide",
  "hello-command",
  "evoflow-skill-kit",
  "zcode-guide",
  "github"
)

function Test-PluginTree([string]$Root) {
  if (-not (Test-Path -LiteralPath $Root)) { return $false }
  $dirs = @(Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue)
  return $dirs.Count -gt 0
}

function Resolve-SourceCache {
  param([string]$Explicit)
  $candidates = New-Object System.Collections.Generic.List[string]
  if (-not [string]::IsNullOrWhiteSpace($Explicit)) {
    $candidates.Add($Explicit)
  }
  $envSrc = [Environment]::GetEnvironmentVariable("EVOFLOW_OFFICIAL_PLUGINS_SOURCE")
  if (-not [string]::IsNullOrWhiteSpace($envSrc)) {
    $candidates.Add($envSrc.Trim())
  }
  $profileDir = [Environment]::GetFolderPath("UserProfile")
  $candidates.Add((Join-Path $profileDir ".evoflow-dev\data\plugins\cache\evoflow-plugins-official"))
  $candidates.Add((Join-Path $profileDir ".evoflow\data\plugins\cache\evoflow-plugins-official"))

  foreach ($c in $candidates) {
    if (Test-PluginTree $c) {
      return [System.IO.Path]::GetFullPath($c)
    }
  }
  return $null
}

function Get-LatestVersionDir([string]$PluginRoot) {
  $dirs = @(Get-ChildItem -LiteralPath $PluginRoot -Directory -ErrorAction SilentlyContinue)
  if ($dirs.Count -eq 0) { return $null }
  return ($dirs | Sort-Object {
      ($_.Name -split '\.' | ForEach-Object {
        if ($_ -match '^\d+$') { [int]$_ } else { 0 }
      }) -join '.'
    } | Select-Object -Last 1)
}

function Read-PluginMeta([string]$VersionDir, [string]$FallbackName) {
  foreach ($rel in @(".evoflow-plugin\plugin.json", ".zcode-plugin\plugin.json", "package.json")) {
    $p = Join-Path $VersionDir $rel
    if (-not (Test-Path -LiteralPath $p)) { continue }
    try {
      $raw = Get-Content -LiteralPath $p -Raw -Encoding UTF8
      $obj = $raw | ConvertFrom-Json
      if ($null -eq $obj) { continue }
      $name = [string]$obj.name
      if ([string]::IsNullOrWhiteSpace($name)) { $name = $FallbackName }
      $ver = [string]$obj.version
      if ([string]::IsNullOrWhiteSpace($ver)) { $ver = Split-Path -Leaf $VersionDir }
      $desc = [string]$obj.description
      $display = [string]$obj.displayName
      if ([string]::IsNullOrWhiteSpace($display)) { $display = $name }
      $authorName = $null
      if ($obj.author -and $obj.author.name) { $authorName = [string]$obj.author.name }
      return [pscustomobject]@{
        name        = $name
        version     = $ver
        displayName = $display
        description = $desc
        authorName  = $authorName
      }
    } catch {}
  }
  return [pscustomobject]@{
    name        = $FallbackName
    version     = (Split-Path -Leaf $VersionDir)
    displayName = $FallbackName
    description = ""
    authorName  = $null
  }
}

$resolvedSource = Resolve-SourceCache -Explicit $Source
if (-not $resolvedSource) {
  throw @"
[sync-official-plugins] no source cache found.
Set -Source or EVOFLOW_OFFICIAL_PLUGINS_SOURCE to a directory like:
  <home>\.evoflow-dev\data\plugins\cache\evoflow-plugins-official
"@
}

Write-Host "[sync-official-plugins] source: $resolvedSource"
Write-Host "[sync-official-plugins] dest:   $Dest"

New-Item -ItemType Directory -Path $Dest -Force | Out-Null

# Wipe previous plugin trees (keep .gitignore).
Get-ChildItem -LiteralPath $Dest -Force -ErrorAction SilentlyContinue | ForEach-Object {
  if ($_.Name -eq ".gitignore") { return }
  if ($_.PSIsContainer) {
    Remove-Item -LiteralPath $_.FullName -Recurse -Force
  } else {
    Remove-Item -LiteralPath $_.FullName -Force
  }
}

$copied = New-Object System.Collections.Generic.List[string]
$listings = New-Object System.Collections.Generic.List[object]

foreach ($name in ($RequiredPlugins + $RuntimeDirs)) {
  $srcPlugin = Join-Path $resolvedSource $name
  if (-not (Test-Path -LiteralPath $srcPlugin)) {
    throw "[sync-official-plugins] missing required plugin in source: $name ($srcPlugin)"
  }
  $latest = Get-LatestVersionDir $srcPlugin
  if ($null -eq $latest) {
    throw "[sync-official-plugins] no version directory under $srcPlugin"
  }
  $destPlugin = Join-Path $Dest $name
  $destVersion = Join-Path $destPlugin $latest.Name
  New-Item -ItemType Directory -Path $destPlugin -Force | Out-Null
  Copy-Item -LiteralPath $latest.FullName -Destination $destVersion -Recurse -Force
  $copied.Add("$name/$($latest.Name)")
  Write-Host "[sync-official-plugins] copied $name/$($latest.Name)"

  if ($RuntimeDirs -contains $name) { continue }
  if ($SkipNames -contains $name) { continue }

  $meta = Read-PluginMeta -VersionDir $destVersion -FallbackName $name
  $entry = [ordered]@{
    name        = $meta.name
    displayName = $meta.displayName
    description = $meta.description
    version     = $meta.version
    source      = "filesystem"
    cachePath   = ""  # rewritten at seed time
  }
  if ($meta.authorName) {
    $entry.author = @{ name = $meta.authorName }
  }
  $listings.Add([pscustomobject]$entry)
}

# Also copy any other non-demo product trees present in source (optional extras).
Get-ChildItem -LiteralPath $resolvedSource -Directory -ErrorAction SilentlyContinue | ForEach-Object {
  $name = $_.Name
  if ($RequiredPlugins -contains $name) { return }
  if ($RuntimeDirs -contains $name) { return }
  if ($SkipNames -contains $name) { return }
  if (Test-Path -LiteralPath (Join-Path $Dest $name)) { return }
  $latest = Get-LatestVersionDir $_.FullName
  if ($null -eq $latest) { return }
  $destPlugin = Join-Path $Dest $name
  $destVersion = Join-Path $destPlugin $latest.Name
  New-Item -ItemType Directory -Path $destPlugin -Force | Out-Null
  Copy-Item -LiteralPath $latest.FullName -Destination $destVersion -Recurse -Force
  $copied.Add("$name/$($latest.Name) (extra)")
  Write-Host "[sync-official-plugins] copied extra $name/$($latest.Name)"
  $meta = Read-PluginMeta -VersionDir $destVersion -FallbackName $name
  $listings.Add([pscustomobject]@{
    name        = $meta.name
    displayName = $meta.displayName
    description = $meta.description
    version     = $meta.version
    source      = "filesystem"
    cachePath   = ""
  })
}

$pluginArray = @($listings.ToArray())
$marketplace = @{
  name        = "evoflow-plugins-official"
  description = "EvoFlow official plugins (packaged with the installer)."
  plugins     = $pluginArray
}
$marketplacePath = Join-Path $Dest "marketplace.json"
$json = $marketplace | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText($marketplacePath, $json, [System.Text.UTF8Encoding]::new($false))

# Copy plugin icons from ../plugins/icons (sibling of cache/) into the bundle.
# Source layout: <plugins>/cache/evoflow-plugins-official  ->  <plugins>/icons
$iconSrc = Join-Path (Split-Path -Parent (Split-Path -Parent $resolvedSource)) "icons"
if (-not (Test-Path -LiteralPath $iconSrc)) {
  $iconSrc = Join-Path (Split-Path -Parent $resolvedSource) "icons"
}
$iconDest = Join-Path $Dest "icons"
if (Test-Path -LiteralPath $iconSrc) {
  New-Item -ItemType Directory -Path $iconDest -Force | Out-Null
  $iconCopied = 0
  foreach ($name in $RequiredPlugins) {
    foreach ($ext in @(".png", ".jpg", ".jpeg", ".svg", ".webp")) {
      $srcIcon = Join-Path $iconSrc ($name + $ext)
      if (Test-Path -LiteralPath $srcIcon) {
        Copy-Item -LiteralPath $srcIcon -Destination (Join-Path $iconDest ($name + $ext)) -Force
        $iconCopied++
        break
      }
    }
  }
  Write-Host "[sync-official-plugins] copied $iconCopied icons from $iconSrc"
} else {
  Write-Host "[sync-official-plugins] WARNING: no icons dir next to source cache ($iconSrc); store may lack icons until CDN/local seed"
}

# Validate required presence.
$missing = @()
foreach ($name in $RequiredPlugins) {
  if (-not (Test-Path -LiteralPath (Join-Path $Dest $name))) { $missing += $name }
}
$helperRuntime = Join-Path $Dest "cua-helper\runtime"
$helperEntry = Join-Path $helperRuntime "dist\windows-helper.js"
$helperAddon = Join-Path $helperRuntime "build\Release\ax_native.node"
if (-not ((Test-Path -LiteralPath $helperEntry) -and (Test-Path -LiteralPath $helperAddon))) {
  $missing += "cua-helper/runtime (windows-helper.js + ax_native.node)"
}
if ($missing.Count -gt 0) {
  throw "[sync-official-plugins] incomplete bundle, missing: $($missing -join ', ')"
}

$sum = (Get-ChildItem -LiteralPath $Dest -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
$mb = if ($null -ne $sum) { [math]::Round($sum / 1MB, 1) } else { 0 }
Write-Host "[sync-official-plugins] OK: $($copied.Count) trees, ${mb} MB -> $Dest"
