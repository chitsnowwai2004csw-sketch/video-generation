param(
    [string]$ToolsRoot = (Join-Path $env:LOCALAPPDATA 'VideoCreator\tools')
)
$ErrorActionPreference = 'Stop'
# Run this once as the server administrator. Job handlers never invoke it.
foreach ($Command in @('node', 'npm.cmd', 'py', 'ffmpeg', 'ffprobe')) {
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) {
        throw "Install $Command on the server before setup."
    }
}
New-Item -ItemType Directory -Path $ToolsRoot -Force | Out-Null
$ManifestSource = Join-Path $PSScriptRoot 'server-tools\package.json'
$ManifestTarget = Join-Path $ToolsRoot 'package.json'
$NeedsInstall = -not (Test-Path -LiteralPath (Join-Path $ToolsRoot 'node_modules\hyperframes\bin\hyperframes.mjs'))
if ((Test-Path -LiteralPath $ManifestTarget) -and ((Get-FileHash -LiteralPath $ManifestSource).Hash -ne (Get-FileHash -LiteralPath $ManifestTarget).Hash)) {
    $NeedsInstall = $true
}
if (-not (Test-Path -LiteralPath (Join-Path $ToolsRoot 'node_modules\@remotion\renderer\package.json'))) { $NeedsInstall = $true }
Copy-Item -LiteralPath $ManifestSource -Destination $ManifestTarget -Force
if ($NeedsInstall) {
    $LockSource = Join-Path $PSScriptRoot 'server-tools\package-lock.json'
    if (Test-Path -LiteralPath $LockSource) {
        Copy-Item -LiteralPath $LockSource -Destination (Join-Path $ToolsRoot 'package-lock.json') -Force
        & npm.cmd ci --prefix $ToolsRoot --no-audit --no-fund
    } else {
        & npm.cmd install --prefix $ToolsRoot --no-audit --no-fund
    }
    if ($LASTEXITCODE -ne 0) { throw 'Shared Node.js tool installation failed.' }
}
$PythonPath = (& py -3.12 -c 'import sys; print(sys.executable)').Trim()
& $PythonPath -c 'import kokoro_onnx, soundfile' 2>$null
if ($LASTEXITCODE -ne 0) {
    & $PythonPath -m pip install 'kokoro-onnx==0.6.1' 'soundfile==0.13.1'
    if ($LASTEXITCODE -ne 0) { throw 'Kokoro installation failed.' }
}
$HyperframesPath = Join-Path $ToolsRoot 'node_modules\hyperframes\bin\hyperframes.mjs'
$env:HYPERFRAMES_PYTHON = $PythonPath
$env:HYPERFRAMES_NO_UPDATE_CHECK = '1'
$env:HYPERFRAMES_NO_AUTO_INSTALL = '1'
# These setup commands may download assets once. Request handlers never run them.
& node $HyperframesPath browser ensure
if ($LASTEXITCODE -ne 0) { throw 'HyperFrames browser setup failed.' }
& node $HyperframesPath tts 'Shared voice tools are ready.' --output (Join-Path $ToolsRoot 'voice-check.wav')
if ($LASTEXITCODE -ne 0) { throw 'Kokoro model preload failed.' }
& node (Join-Path $PSScriptRoot 'server-tools\render.mjs') ensure-browser $ToolsRoot
if ($LASTEXITCODE -ne 0) { throw 'Remotion browser preload failed.' }
$Config = @{
    node = (Get-Command node).Source
    tools_root = $ToolsRoot
    hyperframes = $HyperframesPath
    kokoro_python = $PythonPath
    kokoro_model = (Join-Path $env:USERPROFILE '.cache\hyperframes\tts\models\kokoro-v1.0.onnx')
    kokoro_voices = (Join-Path $env:USERPROFILE '.cache\hyperframes\tts\voices\voices-v1.0.bin')
    hyperframes_browser = (Join-Path $env:USERPROFILE '.cache\hyperframes\chrome')
    ffmpeg = (Get-Command ffmpeg).Source
    ffprobe = (Get-Command ffprobe).Source
}
$ConfigPath = Join-Path $ToolsRoot 'tools.json'
$Config | ConvertTo-Json | Set-Content -LiteralPath $ConfigPath -Encoding UTF8
Write-Output "Shared tools configured: $ConfigPath"
Write-Output 'All Open WebUI users share this installation. No per-user tool downloads.'
