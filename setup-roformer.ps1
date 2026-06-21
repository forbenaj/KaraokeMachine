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

if (-not (Test-Path $pythonPath)) {
  & $Python -m venv $venv
  if ($LASTEXITCODE -ne 0) {
    throw "Could not create the RoFormer Python environment."
  }
}
foreach ($command in @("git", "curl.exe")) {
  if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
    throw "Required command not found: $command"
  }
}

New-Item -ItemType Directory -Path $modelsRoot -Force | Out-Null
if (-not (Test-Path (Join-Path $repo ".git"))) {
  git clone https://github.com/KimberleyJensen/Mel-Band-Roformer-Vocal-Model.git $repo
}
git -C $repo fetch origin $commit --depth 1
git -C $repo checkout --detach $commit

& $pythonPath -m pip install --upgrade pip setuptools wheel
$torchIndex = "https://download.pytorch.org/whl/$TorchBuild"
& $pythonPath -m pip install "torch==$TorchVersion" --index-url $torchIndex
& $pythonPath -m pip install numpy SoundFile PyYAML ml_collections "omegaconf==2.2.3" `
  "beartype==0.14.1" "rotary_embedding_torch==0.3.5" "einops==0.6.1" librosa
& $pythonPath -m pip install whisper-timestamped

$download = $true
if (Test-Path $checkpoint) {
  $download = (Get-FileHash -Algorithm SHA256 $checkpoint).Hash.ToLowerInvariant() -ne $checkpointSha256
  if ($download -and (Get-Item $checkpoint).Length -ge $checkpointSize) {
    Remove-Item -LiteralPath $checkpoint -Force
  }
}
if ($download) {
  Write-Host "Downloading 913 MB RoFormer checkpoint..."
  & curl.exe --location --fail --continue-at - --output $checkpoint $checkpointUrl
  if ($LASTEXITCODE -ne 0) {
    throw "RoFormer checkpoint download failed. Re-run setup-roformer.ps1 to resume."
  }
}
$actualHash = (Get-FileHash -Algorithm SHA256 $checkpoint).Hash.ToLowerInvariant()
if ($actualHash -ne $checkpointSha256) {
  Remove-Item -LiteralPath $checkpoint -Force
  throw "RoFormer checkpoint checksum mismatch. Removed unsafe/incomplete file."
}

Write-Host "RoFormer ready."
Write-Host "Python: $pythonPath"
Write-Host "Repository: $repo"
Write-Host "Checkpoint: $checkpoint"
