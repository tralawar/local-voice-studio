[CmdletBinding(DefaultParameterSetName = 'Existing')]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'Existing')][string]$EngineExe,
    [Parameter(Mandatory = $true, ParameterSetName = 'Build')][switch]$BuildEngine,
    [Parameter(Mandatory = $true, ParameterSetName = 'Build')][string]$EngineSource,
    [Parameter(Mandatory = $true)][string]$Model,
    [Parameter(Mandatory = $true)][string]$CudaRoot,
    [switch]$WithDictation,
    [switch]$ModelLicenseReviewed,
    [string]$Python = 'python'
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$studioRoot = $PSScriptRoot
if (-not $ModelLicenseReviewed) {
    throw 'Read LICENSES.md and the model license for your use, then pass -ModelLicenseReviewed. This acknowledges your own review; it accepts no agreement and grants no model rights. No Drama model is included or downloaded.'
}
if (Test-Path -LiteralPath (Join-Path $studioRoot 'standalone.local.json')) {
    throw 'Already configured. Nothing changed. Keep your existing installation; install updates in a separate folder and follow RELEASE.md.'
}
$modelPath = (Resolve-Path -LiteralPath $Model).Path
if (-not (Test-Path -LiteralPath $modelPath -PathType Leaf)) { throw 'Model must be an existing GGUF file. No Drama weights are downloaded by this installer.' }
$cudaPath = (Resolve-Path -LiteralPath $CudaRoot).Path
$cudaBin = Join-Path $cudaPath 'bin'
if (-not (Test-Path -LiteralPath $cudaBin -PathType Container)) { throw 'CudaRoot must contain a bin directory. Install the NVIDIA CUDA toolkit separately.' }
function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE. Setup can be retried; no original installation was changed." }
}
Invoke-Checked $Python @('-c', 'import sys,struct; assert sys.version_info >= (3,10) and struct.calcsize("P")==8, "64-bit Python 3.10+ required"')
if ($BuildEngine) {
    $sourceRoot = Split-Path (Split-Path $studioRoot -Parent) -Parent
    if ($EngineSource) { $sourceRoot = (Resolve-Path -LiteralPath $EngineSource).Path }
    if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot 'scripts/build_windows.ps1'))) {
        throw 'Supply -EngineSource with the pinned audio.cpp checkout. See RELEASE.md for the exact clone/revision commands.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $cudaBin 'nvcc.exe'))) { throw 'Building requires the complete CUDA toolkit including bin/nvcc.exe, plus Visual Studio C++ tools.' }
    Invoke-Checked $Python @((Join-Path $studioRoot 'bootstrap_engine.py'), '--model', $modelPath, '--build', '--cuda-root', $cudaPath, '--source-dir', $sourceRoot)
    $EngineExe = Join-Path $sourceRoot 'build/windows-cuda-release/bin/audiocpp_server.exe'
}
$enginePath = (Resolve-Path -LiteralPath $EngineExe).Path
if (-not (Test-Path -LiteralPath $enginePath -PathType Leaf)) { throw 'EngineExe must be a trusted local audiocpp_server.exe.' }
$setupArgs = @((Join-Path $studioRoot 'setup.py'))
if ($WithDictation) { $setupArgs += '--with-stt' }
Invoke-Checked $Python $setupArgs
Invoke-Checked $Python @((Join-Path $studioRoot 'standalone.py'), '--configure', '--engine-exe', $enginePath, '--model', $modelPath, '--cuda-bin', $cudaBin)
Write-Host 'Installed. No engine was started and no microphone permission was requested.'
Write-Host "Start: $studioRoot\launch-standalone.cmd"
Write-Host 'Keep the launcher window open. Ctrl+C stops its owned UI and engine. Read RELEASE.md before updating.'
