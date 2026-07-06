param(
  [ValidateSet("cpu", "cu121", "cu124")]
  [string]$TorchBuild = "cpu",
  [string]$TorchVersion = "2.5.1",
  [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venv = Join-Path $root ".venv-roformer"
$pythonPath = Join-Path $venv "Scripts\python.exe"
$modelsRoot = Join-Path $root ".stem-models"
$repo = Join-Path $modelsRoot "mel-band-roformer"
$checkpoint = Join-Path $modelsRoot "MelBandRoformer.ckpt"
$commit = "25f44ffb55ee3c301281bba21b2d6d311cb69ae2"
$checkpointSha256 = "87201f4d31afb5bc79993230fc49446918425574db48c01c405e44f365c7559e"
$checkpointSize = 913106900
$checkpointUrl = "https://huggingface.co/KimberleyJSN/melbandroformer/resolve/main/MelBandRoformer.ckpt?download=true"
$supportedPython = "3.10, 3.11, or 3.12"

function Invoke-Checked([string]$Description, [scriptblock]$Command) {
  & $Command
  if ($LASTEXITCODE -ne 0) {
    throw "$Description failed with exit code $LASTEXITCODE."
  }
}

function Get-PythonRuntimeInfo([string]$Executable) {
  $json = & $Executable -c "import json, platform, struct, sys; print(json.dumps({'version': platform.python_version(), 'major': sys.version_info.major, 'minor': sys.version_info.minor, 'bits': struct.calcsize('P') * 8, 'executable': sys.executable}))"
  if ($LASTEXITCODE -ne 0) {
    throw "Python validation failed for '$Executable'."
  }
  return $json | ConvertFrom-Json
}

function Assert-RoFormerPythonSupported([string]$Executable, [string]$Context) {
  $info = Get-PythonRuntimeInfo $Executable
  if ($info.bits -ne 64) {
    throw "RoFormer requires 64-bit Python, but $Context is $($info.bits)-bit Python $($info.version) at $($info.executable). Install 64-bit Python $supportedPython and rerun setup-roformer.ps1."
  }
  if ($info.major -ne 3 -or $info.minor -lt 10 -or $info.minor -gt 12) {
    throw "RoFormer is pinned to PyTorch $TorchVersion, which supports Python $supportedPython on Windows. $Context is Python $($info.version) at $($info.executable). Install Python $supportedPython, remove .venv-roformer if it already exists, and rerun setup-roformer.ps1."
  }
  return $info
}

Assert-RoFormerPythonSupported $Python "Requested Python" | Out-Null

if (-not (Test-Path $pythonPath)) {
  Invoke-Checked "RoFormer Python environment creation" { & $Python -m venv $venv }
}
$roformerPython = Assert-RoFormerPythonSupported $pythonPath "RoFormer virtual environment"
foreach ($command in @("git", "curl.exe")) {
  if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
    throw "Required command not found: $command"
  }
}

New-Item -ItemType Directory -Path $modelsRoot -Force | Out-Null
if (-not (Test-Path (Join-Path $repo ".git"))) {
  Invoke-Checked "RoFormer repository clone" {
    git clone https://github.com/KimberleyJensen/Mel-Band-Roformer-Vocal-Model.git $repo
  }
}
Invoke-Checked "RoFormer repository fetch" { git -C $repo fetch origin $commit --depth 1 }
Invoke-Checked "RoFormer repository checkout" { git -C $repo checkout --detach $commit }

Invoke-Checked "Python packaging tool installation" {
  & $pythonPath -m pip install --upgrade pip setuptools wheel
}
$torchIndex = "https://download.pytorch.org/whl/$TorchBuild"
Invoke-Checked "PyTorch installation" {
  & $pythonPath -m pip install "torch==$TorchVersion" --index-url $torchIndex
}
Invoke-Checked "TorchAudio installation" {
  & $pythonPath -m pip install "torchaudio==$TorchVersion" --index-url $torchIndex
}
Invoke-Checked "RoFormer dependency installation" {
  & $pythonPath -m pip install numpy SoundFile PyYAML ml_collections "omegaconf==2.2.3" `
    "beartype==0.14.1" "rotary_embedding_torch==0.3.5" "einops==0.6.1" librosa `
    "silero-vad"
}

$download = $true
if (Test-Path $checkpoint) {
  $download = (Get-FileHash -Algorithm SHA256 $checkpoint).Hash.ToLowerInvariant() -ne $checkpointSha256
  if ($download -and (Get-Item $checkpoint).Length -ge $checkpointSize) {
    Remove-Item -LiteralPath $checkpoint -Force
  }
}
if ($download) {
  Write-Host "Downloading 913 MB RoFormer checkpoint..."
  try {
    Invoke-Checked "RoFormer checkpoint download" {
      & curl.exe --location --fail --continue-at - --output $checkpoint $checkpointUrl
    }
  } catch {
    throw "RoFormer checkpoint download failed. Re-run setup-roformer.ps1 to resume. $($_.Exception.Message)"
  }
}
$actualHash = (Get-FileHash -Algorithm SHA256 $checkpoint).Hash.ToLowerInvariant()
if ($actualHash -ne $checkpointSha256) {
  Remove-Item -LiteralPath $checkpoint -Force
  throw "RoFormer checkpoint checksum mismatch. Removed unsafe/incomplete file."
}

Write-Host "RoFormer ready."
Write-Host "Python: $pythonPath ($($roformerPython.version), $($roformerPython.bits)-bit)"
Write-Host "Repository: $repo"
Write-Host "Checkpoint: $checkpoint"
