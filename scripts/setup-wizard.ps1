param(
  [Parameter(Mandatory = $true)]
  [string]$InstallDir,

  [string]$DownloadsDir,

  [ValidateSet("cpu", "cu121", "cu124")]
  [string]$TorchBuild = "cpu",

  [switch]$SkipRoFormerSetup,
  [switch]$SkipFfmpegInstall
)

$ErrorActionPreference = "Stop"

function Get-LocalAppDataRoot {
  if ($env:LOCALAPPDATA) {
    return $env:LOCALAPPDATA
  }
  return Join-Path $HOME "AppData\Local"
}

function Resolve-SetupPath([string]$Path, [string]$Fallback) {
  $candidate = if ([string]::IsNullOrWhiteSpace($Path)) { $Fallback } else { $Path }
  $expanded = [Environment]::ExpandEnvironmentVariables($candidate)
  New-Item -ItemType Directory -Path $expanded -Force | Out-Null
  return (Resolve-Path -LiteralPath $expanded).Path
}

$appDataRoot = Join-Path (Get-LocalAppDataRoot) "DKaraoKe"
New-Item -ItemType Directory -Path $appDataRoot -Force | Out-Null
$logPath = Join-Path $appDataRoot "setup.log"
$transcriptStarted = $false

try {
  Start-Transcript -Path $logPath -Append | Out-Null
  $transcriptStarted = $true

  $resolvedInstallDir = (Resolve-Path -LiteralPath $InstallDir).Path
  $defaultDownloadsDir = Join-Path $appDataRoot "downloads"
  $resolvedDownloadsDir = Resolve-SetupPath $DownloadsDir $defaultDownloadsDir
  $configPath = Join-Path $appDataRoot "config.json"

  [ordered]@{
    downloadsDir = $resolvedDownloadsDir
  } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $configPath -Encoding UTF8

  Write-Host "DKaraoKe setup"
  Write-Host "Install folder: $resolvedInstallDir"
  Write-Host "Downloads folder: $resolvedDownloadsDir"
  Write-Host "Setup log: $logPath"
  Write-Host ""

  $installScript = Join-Path $resolvedInstallDir "install.ps1"
  if (-not (Test-Path -LiteralPath $installScript)) {
    throw "install.ps1 was not found in $resolvedInstallDir."
  }

  Push-Location $resolvedInstallDir
  try {
    Write-Host "Installing the local backend and registering Chrome native messaging..."
    & $installScript -SkipFfmpegInstall:$SkipFfmpegInstall
    if ($LASTEXITCODE -ne 0) {
      throw "install.ps1 failed with exit code $LASTEXITCODE."
    }

    if ($SkipRoFormerSetup) {
      Write-Host "Skipping RoFormer setup. You can run setup-roformer.ps1 later."
    } else {
      $roformerScript = Join-Path $resolvedInstallDir "setup-roformer.ps1"
      if (-not (Test-Path -LiteralPath $roformerScript)) {
        throw "setup-roformer.ps1 was not found in $resolvedInstallDir."
      }
      Write-Host "Installing RoFormer runtime and model with Torch build: $TorchBuild"
      & $roformerScript -TorchBuild $TorchBuild
      if ($LASTEXITCODE -ne 0) {
        throw "setup-roformer.ps1 failed with exit code $LASTEXITCODE."
      }
    }
  } finally {
    Pop-Location
  }

  Write-Host ""
  Write-Host "DKaraoKe setup is complete."
  Write-Host ""
  Write-Host "Load the Chrome extension manually:"
  Write-Host "1. Open chrome://extensions"
  Write-Host "2. Enable Developer mode"
  Write-Host "3. Click Load unpacked"
  Write-Host "4. Select this folder: $resolvedInstallDir"
  Write-Host "5. Restart Chrome if it was open during setup"
  exit 0
} catch {
  Write-Error $_
  exit 1
} finally {
  if ($transcriptStarted) {
    Stop-Transcript | Out-Null
  }
}
