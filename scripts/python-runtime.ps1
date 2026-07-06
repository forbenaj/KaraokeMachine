$DKaraokeSupportedPython = "3.10, 3.11, or 3.12"
$DKaraokePreferredPythonWingetId = "Python.Python.3.12"

function Refresh-DKaraokeProcessPath {
  $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = @($machinePath, $userPath) -join ";"
}

function Get-DKaraokePythonRuntimeInfo([string]$Command, [string[]]$Arguments = @()) {
  $json = & $Command @Arguments -c "import json, platform, struct, sys; print(json.dumps({'version': platform.python_version(), 'major': sys.version_info.major, 'minor': sys.version_info.minor, 'bits': struct.calcsize('P') * 8, 'executable': sys.executable}))"
  if ($LASTEXITCODE -ne 0) {
    throw "Python validation failed for '$Command $($Arguments -join ' ')'."
  }
  return $json | ConvertFrom-Json
}

function Test-DKaraokePythonSupported($Info) {
  return $Info.bits -eq 64 -and $Info.major -eq 3 -and $Info.minor -ge 10 -and $Info.minor -le 12
}

function Get-DKaraokePythonCandidates([string]$RequestedPython = "") {
  $candidates = @()
  if ([string]::IsNullOrWhiteSpace($RequestedPython)) {
    $candidates += [pscustomobject]@{ Label = "Python Launcher 3.12"; Command = "py"; Arguments = @("-3.12") }
    $candidates += [pscustomobject]@{ Label = "Python Launcher 3.11"; Command = "py"; Arguments = @("-3.11") }
    $candidates += [pscustomobject]@{ Label = "Python Launcher 3.10"; Command = "py"; Arguments = @("-3.10") }
    $roots = @($env:LOCALAPPDATA, $env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    foreach ($version in @("312", "311", "310")) {
      foreach ($base in $roots) {
        $path = Join-Path $base "Programs\Python\Python$version\python.exe"
        if (Test-Path -LiteralPath $path) {
          $candidates += [pscustomobject]@{ Label = "Python install path $version"; Command = $path; Arguments = @() }
        }
        $path = Join-Path $base "Python$version\python.exe"
        if (Test-Path -LiteralPath $path) {
          $candidates += [pscustomobject]@{ Label = "Python install path $version"; Command = $path; Arguments = @() }
        }
      }
    }
    $candidates += [pscustomobject]@{ Label = "PATH python"; Command = "python"; Arguments = @() }
  } else {
    $candidates += [pscustomobject]@{ Label = "Requested Python"; Command = $RequestedPython; Arguments = @() }
  }
  return $candidates
}

function Find-DKaraokePython([string]$RequestedPython = "") {
  $checked = New-Object System.Collections.Generic.List[string]
  foreach ($candidate in (Get-DKaraokePythonCandidates $RequestedPython)) {
    try {
      $info = Get-DKaraokePythonRuntimeInfo $candidate.Command $candidate.Arguments
    } catch {
      $checked.Add("$($candidate.Label): unavailable")
      continue
    }
    if (Test-DKaraokePythonSupported $info) {
      return [pscustomobject]@{
        Found = $true
        Info = $info
        Checked = $checked
      }
    }
    $checked.Add("$($candidate.Label): Python $($info.version), $($info.bits)-bit at $($info.executable)")
  }
  return [pscustomobject]@{
    Found = $false
    Info = $null
    Checked = $checked
  }
}

function Install-DKaraokePythonWithWinget {
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if (-not $winget) {
    throw "No compatible 64-bit Python was found, and winget is unavailable. Install App Installer from Microsoft Store or install 64-bit Python $DKaraokeSupportedPython, then rerun setup."
  }

  Write-Host "Installing Python 3.12 with winget..."
  & $winget.Source install --id $DKaraokePreferredPythonWingetId -e --silent --scope user --accept-package-agreements --accept-source-agreements
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "Python per-user installation failed with exit code $LASTEXITCODE. Retrying without --scope user..."
    & $winget.Source install --id $DKaraokePreferredPythonWingetId -e --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
      throw "Python 3.12 installation failed with exit code $LASTEXITCODE."
    }
  }
  Refresh-DKaraokeProcessPath
}

function Resolve-DKaraokePython([string]$RequestedPython = "", [switch]$InstallIfMissing, [string]$Purpose = "DKaraoKe") {
  $result = Find-DKaraokePython $RequestedPython
  if ($result.Found) {
    Write-Host "Using $Purpose Python: $($result.Info.executable) ($($result.Info.version), $($result.Info.bits)-bit)"
    return $result.Info
  }

  if ($InstallIfMissing -and [string]::IsNullOrWhiteSpace($RequestedPython)) {
    Install-DKaraokePythonWithWinget
    $result = Find-DKaraokePython $RequestedPython
    if ($result.Found) {
      Write-Host "Using $Purpose Python: $($result.Info.executable) ($($result.Info.version), $($result.Info.bits)-bit)"
      return $result.Info
    }
  }

  throw "$Purpose requires 64-bit Python $DKaraokeSupportedPython on Windows. No compatible Python was found. Checked: $($result.Checked -join '; '). Install Python $DKaraokeSupportedPython, then rerun setup."
}

function Assert-DKaraokePythonSupported([string]$Executable, [string]$Context) {
  $info = Get-DKaraokePythonRuntimeInfo $Executable
  if ($info.bits -ne 64) {
    throw "$Context requires 64-bit Python, but found $($info.bits)-bit Python $($info.version) at $($info.executable)."
  }
  if ($info.major -ne 3 -or $info.minor -lt 10 -or $info.minor -gt 12) {
    throw "$Context requires Python $DKaraokeSupportedPython, but found Python $($info.version) at $($info.executable)."
  }
  return $info
}

function Remove-DKaraokeGeneratedVenv([string]$Root, [string]$VenvPath, [string]$Reason) {
  $rootPath = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')
  $parentPath = Split-Path -Parent $VenvPath
  $resolvedParent = (Resolve-Path -LiteralPath $parentPath).Path.TrimEnd('\')
  $targetPath = Join-Path $resolvedParent (Split-Path -Leaf $VenvPath)
  if (-not ($targetPath.StartsWith("$rootPath\", [StringComparison]::OrdinalIgnoreCase))) {
    throw "Refusing to remove generated venv outside the install folder: $targetPath"
  }
  Write-Warning "$Reason Removing generated venv: $targetPath"
  Remove-Item -LiteralPath $targetPath -Recurse -Force
}
