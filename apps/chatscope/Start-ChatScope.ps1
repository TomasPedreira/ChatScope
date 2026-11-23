param([switch]$Build)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$appExe = Join-Path $projectRoot 'dist/ChatScope.exe'
$buildRoot = Join-Path $env:LOCALAPPDATA 'Clipping/Cache/chatscope-target'
if ($Build -or -not (Test-Path -LiteralPath $appExe)) {
    cargo build --release --manifest-path (Join-Path $projectRoot 'Cargo.toml') --target-dir $buildRoot
    if ($LASTEXITCODE -ne 0) { throw 'A compilação falhou.' }
    New-Item -ItemType Directory -Path (Join-Path $projectRoot 'dist') -Force | Out-Null
    Move-Item -LiteralPath (Join-Path $buildRoot 'release/chatscope.exe') -Destination $appExe -Force
}
Start-Process -FilePath $appExe -WorkingDirectory $projectRoot

