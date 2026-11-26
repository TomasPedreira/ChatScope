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
    # GNU builds use a dynamic WebView2 loader; MSVC builds may link it statically.
    $webViewLoader = Join-Path $buildRoot 'release/WebView2Loader.dll'
    if (Test-Path -LiteralPath $webViewLoader) {
        Copy-Item -LiteralPath $webViewLoader -Destination (Join-Path $projectRoot 'dist/WebView2Loader.dll') -Force
    }
}
Start-Process -FilePath $appExe -WorkingDirectory $projectRoot

