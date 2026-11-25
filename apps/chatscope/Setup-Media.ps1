param([switch]$Captions)
$ErrorActionPreference = 'Stop'
$venv = Join-Path $PSScriptRoot '.venv-youtube'
$python = Join-Path $venv 'Scripts/python.exe'
if (!(Test-Path -LiteralPath $python)) {
    python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível criar o ambiente Python.' }
}
& $python -m pip install -r (Join-Path $PSScriptRoot 'requirements-media.txt')
if ($LASTEXITCODE -ne 0) { throw 'A instalação das ferramentas de vídeo falhou.' }
if ($Captions) {
    & $python -m pip install 'faster-whisper>=1.2,<2'
    if ($LASTEXITCODE -ne 0) { throw 'A instalação das legendas falhou.' }
}
& $python -c 'from imageio_ffmpeg import get_ffmpeg_exe; print(get_ffmpeg_exe())'
if ($LASTEXITCODE -ne 0) { throw 'O FFmpeg não ficou disponível.' }
Write-Output 'Produção local preparada. As legendas descarregam o modelo apenas quando pedidas.'
