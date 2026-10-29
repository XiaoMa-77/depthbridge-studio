param([string]$PythonExe = "", [switch]$OfflineOnly)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
if (-not $PythonExe) {
    $python312 = Join-Path $env:LOCALAPPDATA 'Programs/Python/Python312/python.exe'
    if (Test-Path -LiteralPath $python312) { $PythonExe = $python312 }
    else { $PythonExe = (Get-Command python -ErrorAction Stop).Source }
}
& $PythonExe -c "import sys; assert (3,10) <= sys.version_info[:2] < (3,14), 'Use Python 3.12 x64; pass -PythonExe with its path'"
if ($LASTEXITCODE -ne 0) { throw 'Please install Python 3.12 x64, then run setup.ps1 -PythonExe <python.exe path>.' }
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    & $PythonExe -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}
$packageSpec = if ($OfflineOnly) { '.' } else { '.[realsense]' }
& ./.venv/Scripts/python.exe -m pip install -e $packageSpec
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check the network and the Python version.' }
Write-Host 'DepthBridge Studio is ready. Run .\start.ps1' -ForegroundColor Green
