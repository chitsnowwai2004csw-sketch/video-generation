param([int]$Port = 8001)
$ErrorActionPreference = 'Stop'
$Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$ToolsConfig = Join-Path $env:LOCALAPPDATA 'VideoCreator\tools\tools.json'
$ServerConfig = Join-Path $PSScriptRoot 'server.local.json'
if (-not (Test-Path -LiteralPath $Python)) { throw 'Create .venv and install worker-requirements.txt once first.' }
if (-not (Test-Path -LiteralPath $ToolsConfig)) { throw 'Run setup_shared_tools.ps1 once first.' }
if (-not (Test-Path -LiteralPath $ServerConfig)) {
    $RandomBytes = New-Object byte[] 32
    $Generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $Generator.GetBytes($RandomBytes)
    $Generator.Dispose()
    @{ VIDEO_API_KEY = [Convert]::ToBase64String($RandomBytes) } | ConvertTo-Json | Set-Content -LiteralPath $ServerConfig -Encoding UTF8
}
$Config = Get-Content -LiteralPath $ServerConfig -Raw | ConvertFrom-Json
$env:VIDEO_API_KEY = $Config.VIDEO_API_KEY
$env:VIDEO_TOOLS_CONFIG = $ToolsConfig
$env:VIDEO_DATA_DIR = Join-Path $PSScriptRoot '.video-data'
Write-Output "Worker: http://127.0.0.1:$Port"
Write-Output "Copy VIDEO_API_KEY from $ServerConfig into the Open WebUI Function Valves."
Write-Output 'Shared tools are reused. This start command installs and downloads nothing.'
Push-Location $PSScriptRoot
try { & $Python -m uvicorn video_worker:app --host 127.0.0.1 --port $Port }
finally { Pop-Location }
