param([int]$Port = 8765, [switch]$NoBrowser)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { throw 'Run .\setup.ps1 first.' }
$launchArgs = @('-m', 'depthbridge', '--port', "$Port")
if ($NoBrowser) { $launchArgs += '--no-browser' }
& ./.venv/Scripts/python.exe @launchArgs
