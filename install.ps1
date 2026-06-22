param(
  [switch]$SkipFfmpegInstall
)

$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$hostName = "com.dkaraoke.downloader"
$hostDir = Join-Path $root "host"
$hostScript = Join-Path $hostDir "dkaraoke_host.py"
$hostLauncher = Join-Path $hostDir "dkaraoke_host.cmd"
$hostManifest = Join-Path $hostDir "$hostName.json"
$registryPath = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$hostName"
$toolsVenv = Join-Path $root ".venv-tools"
$toolsPython = Join-Path $toolsVenv "Scripts\python.exe"
$toolsScripts = Join-Path $toolsVenv "Scripts"
$manifest = Get-Content (Join-Path $root "manifest.json") -Raw | ConvertFrom-Json

function Get-ExtensionId([string]$Key) {
  $bytes = [Convert]::FromBase64String($Key)
  $hash = [Security.Cryptography.SHA256]::Create().ComputeHash($bytes)
  $alphabet = "abcdefghijklmnop"
  $result = New-Object Text.StringBuilder
  foreach ($byte in $hash[0..15]) {
    [void]$result.Append($alphabet[$byte -shr 4])
    [void]$result.Append($alphabet[$byte -band 15])
  }
  $result.ToString()
}

function Refresh-ProcessPath {
  $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = @($machinePath, $userPath) -join ";"
}

function Invoke-Checked([string]$Description, [scriptblock]$Command) {
  & $Command
  if ($LASTEXITCODE -ne 0) {
    throw "$Description failed with exit code $LASTEXITCODE."
  }
}

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
  throw "Python 3 was not found. Install Python from https://www.python.org/downloads/windows/ and rerun install.ps1."
}
$python = $pythonCommand.Source
Invoke-Checked "Python validation" { & $python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" }

if (-not (Test-Path $toolsPython)) {
  Write-Host "Creating the DKaraoKe tools environment..."
  Invoke-Checked "Python environment creation" { & $python -m venv $toolsVenv }
}

Write-Host "Installing/updating yt-dlp and its YouTube JavaScript solver..."
Invoke-Checked "yt-dlp installation" { & $toolsPython -m pip install --disable-pip-version-check --upgrade "yt-dlp[default]" }
Invoke-Checked "yt-dlp validation" { & $toolsPython -m yt_dlp --version }
Invoke-Checked "yt-dlp JavaScript solver validation" { & $toolsPython -c "import yt_dlp_ejs" }

$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if (-not $winget) {
    throw "Node.js is required by yt-dlp to solve YouTube media URLs, and winget is unavailable. Install Node.js, then rerun install.ps1."
  }
  Write-Host "Installing Node.js for yt-dlp's YouTube JavaScript solver..."
  Invoke-Checked "Node.js installation" {
    & $winget.Source install --id OpenJS.NodeJS.LTS -e --silent --accept-package-agreements --accept-source-agreements
  }
  Refresh-ProcessPath
  $node = Get-Command node -ErrorAction SilentlyContinue
}
if (-not $node) {
  throw "Node.js was not found after installation. Restart PowerShell and rerun install.ps1."
}
Invoke-Checked "Node.js validation" { & $node.Source --version *> $null }

$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
$ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
if ((-not $ffmpeg -or -not $ffprobe) -and -not $SkipFfmpegInstall) {
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if (-not $winget) {
    throw "FFmpeg is missing and winget is unavailable. Install FFmpeg, or install App Installer from Microsoft Store, then rerun install.ps1."
  }
  Write-Host "Installing FFmpeg with winget..."
  Invoke-Checked "FFmpeg installation" {
    & $winget.Source install --id Gyan.FFmpeg -e --silent --accept-package-agreements --accept-source-agreements
  }
  Refresh-ProcessPath
  $ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
  $ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
}
if (-not $ffmpeg -or -not $ffprobe) {
  throw "ffmpeg and ffprobe must both be available on PATH. Install Gyan.FFmpeg and rerun install.ps1."
}
Invoke-Checked "FFmpeg validation" { & $ffmpeg.Source -version *> $null }
Invoke-Checked "ffprobe validation" { & $ffprobe.Source -version *> $null }

$extensionId = Get-ExtensionId $manifest.key
$ffmpegDir = Split-Path -Parent $ffmpeg.Source
$nodeDir = Split-Path -Parent $node.Source
$launcherPath = @($toolsScripts, $ffmpegDir, $nodeDir) -join ";"

New-Item -ItemType Directory -Path $hostDir -Force | Out-Null
@"
@echo off
set "PATH=$launcherPath;%PATH%"
"$toolsPython" "$hostScript"
"@ | Set-Content -LiteralPath $hostLauncher -Encoding ASCII

[ordered]@{
  name = $hostName
  description = "Local downloader and RoFormer separator for DKaraoKe"
  path = $hostLauncher
  type = "stdio"
  allowed_origins = @("chrome-extension://$extensionId/")
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $hostManifest -Encoding UTF8

New-Item -Path $registryPath -Force | Out-Null
Set-Item -Path $registryPath -Value $hostManifest

$roformerMissing = -not (Test-Path (Join-Path $root ".venv-roformer\Scripts\python.exe")) -or
  -not (Test-Path (Join-Path $root ".stem-models\MelBandRoformer.ckpt")) -or
  -not (Test-Path (Join-Path $root ".stem-models\mel-band-roformer"))

Write-Host ""
Write-Host "Registered native host: $hostName"
Write-Host "Extension ID: $extensionId"
Write-Host "yt-dlp: $toolsScripts\yt-dlp.exe"
Write-Host "Node.js: $($node.Source)"
Write-Host "FFmpeg: $($ffmpeg.Source)"
if ($roformerMissing) {
  Write-Warning "RoFormer is not ready. Run .\setup-roformer.ps1 (a large model/runtime download)."
} else {
  Write-Host "RoFormer is ready."
}
Write-Host "Load this folder as an unpacked extension: $root"
Write-Host "Restart Chrome if it was open during installation."
