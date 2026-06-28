<#
.SYNOPSIS
  Package the ImgEdge browser extension for distribution.

.DESCRIPTION
  Stages ONLY the extension front-end files (an explicit allow-list, so the local
  Python classifier in classifier/ inat/ voters/ training/ and the docs are never
  shipped) into dist\imgedge, then produces a store-ready ZIP with manifest.json
  at the archive root. Optionally also builds a self-hosted .crx.

.PARAMETER Crx
  Also pack a .crx (self-hosted / Edge / enterprise installs). Reuses
  dist\imgedge.pem when present so the extension ID stays stable across updates.

.PARAMETER ChromePath
  Full path to chrome.exe / msedge.exe. Only needed with -Crx if auto-detection
  fails.

.EXAMPLE
  .\package.ps1
  Build dist\imgedge-<version>.zip for the Chrome Web Store / Edge Add-ons.

.EXAMPLE
  .\package.ps1 -Crx
  Also produce dist\imgedge.crx (and dist\imgedge.pem on first run).
#>
[CmdletBinding()]
param(
    [switch]$Crx,
    [string]$ChromePath
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Front-end files that make up the extension. Everything else is excluded so the
# server code and signing material can never leak into a published package.
$include = @(
    "manifest.json",
    "background.js",
    "content.js",
    "content.css",
    "popup.html",
    "popup.js",
    "icons"
)

# ---- validate sources ------------------------------------------------------
$missing = $include | Where-Object { -not (Test-Path $_) }
if ($missing) { throw "Missing extension file(s): $($missing -join ', ')" }

try {
    $manifest = Get-Content manifest.json -Raw | ConvertFrom-Json
} catch {
    throw "manifest.json is not valid JSON: $($_.Exception.Message)"
}
$ver = $manifest.version
if (-not $ver) { throw "manifest.json has no version field" }

# ---- stage a clean copy ----------------------------------------------------
$dist  = Join-Path $PSScriptRoot "dist"
$stage = Join-Path $dist "imgedge"
Remove-Item $stage -Recurse -Force -ErrorAction Ignore
New-Item -ItemType Directory $stage -Force | Out-Null
Copy-Item $include -Destination $stage -Recurse -Force

# ---- zip (store-ready: manifest.json at the archive root) -------------------
$zip = Join-Path $dist "imgedge-$ver.zip"
Remove-Item $zip -Force -ErrorAction Ignore
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -Force
Write-Host "ZIP : $zip" -ForegroundColor Green

# ---- optional .crx ---------------------------------------------------------
if ($Crx) {
    if (-not $ChromePath) {
        $ChromePath = @(
            "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
            "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
            "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
            "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
            "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
        ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    }
    if (-not $ChromePath) {
        throw "Chrome/Edge not found. Re-run with -ChromePath '<path to chrome.exe>'."
    }

    $pem = Join-Path $dist "imgedge.pem"
    $packArgs = @("--pack-extension=$stage", "--no-message-box")
    if (Test-Path $pem) { $packArgs += "--pack-extension-key=$pem" }
    Start-Process -FilePath $ChromePath -ArgumentList $packArgs -Wait -NoNewWindow

    $crx = Join-Path $dist "imgedge.crx"
    if (Test-Path $crx) {
        Write-Host "CRX : $crx" -ForegroundColor Green
    } else {
        Write-Warning "CRX was not produced. Close all Chrome/Edge windows and retry."
    }
    if (Test-Path $pem) {
        Write-Host "KEY : $pem  (keep secret; reused for future updates)" -ForegroundColor Yellow
    }
}
