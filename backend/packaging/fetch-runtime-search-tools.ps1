# Download ZCode-aligned runtime search binaries into packaging/*-bundle/<platform>/.
# Env overrides still win: EVOFLOW_RG_BINARY / EVOFLOW_UGREP_BINARY / EVOFLOW_BFS_BINARY
# (and ZCODE_* equivalents).
#
# Usage (from repo):
#   powershell -File backend/packaging/fetch-runtime-search-tools.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Plat = if ($env:PROCESSOR_ARCHITECTURE -match "ARM64") { "win-arm64" } else { "win-x64" }

function Ensure-Dir([string]$Path) {
  New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Download-File([string]$Url, [string]$Dest) {
  Write-Host "GET $Url"
  Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing
}

# --- ripgrep (BurntSushi) ---
$RgDir = Join-Path $Root "ripgrep-bundle\$Plat"
Ensure-Dir $RgDir
$RgZip = Join-Path $env:TEMP "evoflow-rg.zip"
$RgUrl = "https://github.com/BurntSushi/ripgrep/releases/download/14.1.1/ripgrep-14.1.1-x86_64-pc-windows-msvc.zip"
if (-not (Test-Path (Join-Path $RgDir "rg.exe"))) {
  Download-File $RgUrl $RgZip
  $RgExtract = Join-Path $env:TEMP "evoflow-rg-extract"
  if (Test-Path $RgExtract) { Remove-Item -Recurse -Force $RgExtract }
  Expand-Archive -Path $RgZip -DestinationPath $RgExtract -Force
  $RgExe = Get-ChildItem -Path $RgExtract -Recurse -Filter "rg.exe" | Select-Object -First 1
  if (-not $RgExe) { throw "rg.exe not found in archive" }
  Copy-Item $RgExe.FullName (Join-Path $RgDir "rg.exe") -Force
  Write-Host "Installed $($RgExe.FullName) -> $RgDir"
} else {
  Write-Host "rg.exe already present in $RgDir"
}

# --- ugrep (Genivia) ---
$UgDir = Join-Path $Root "ugrep-bundle\$Plat"
Ensure-Dir $UgDir
$UgZip = Join-Path $env:TEMP "evoflow-ugrep.zip"
# Portable Windows build from Genivia releases
$UgUrl = "https://github.com/Genivia/ugrep/releases/download/v7.5.0/ugrep-windows-x64.zip"
if (-not (Test-Path (Join-Path $UgDir "ugrep.exe"))) {
  try {
    Download-File $UgUrl $UgZip
    $UgExtract = Join-Path $env:TEMP "evoflow-ugrep-extract"
    if (Test-Path $UgExtract) { Remove-Item -Recurse -Force $UgExtract }
    Expand-Archive -Path $UgZip -DestinationPath $UgExtract -Force
    $UgExe = Get-ChildItem -Path $UgExtract -Recurse -Filter "ugrep.exe" | Select-Object -First 1
    if (-not $UgExe) { throw "ugrep.exe not found in archive" }
    Copy-Item $UgExe.FullName (Join-Path $UgDir "ugrep.exe") -Force
    Write-Host "Installed $($UgExe.FullName) -> $UgDir"
  } catch {
    Write-Warning "ugrep download failed: $_"
    Write-Warning "Set EVOFLOW_UGREP_BINARY to a local ugrep.exe, or install from https://github.com/Genivia/ugrep/releases"
  }
} else {
  Write-Host "ugrep.exe already present in $UgDir"
}

# --- bfs ---
# Official Windows binaries are uncommon; ZCode also skips find→bfs wrap on win32
# unless bfs is present. Place bfs.exe here manually if you have one.
$BfsDir = Join-Path $Root "bfs-bundle\$Plat"
Ensure-Dir $BfsDir
Write-Host "bfs: place bfs.exe under $BfsDir if available (optional on Windows)."

Write-Host "Done. Restart the gateway so Bash prelude picks up the binaries."
