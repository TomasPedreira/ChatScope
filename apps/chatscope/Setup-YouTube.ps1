$ErrorActionPreference = 'Stop'
$venv = Join-Path $PSScriptRoot '.venv-youtube'
$python = Join-Path $venv 'Scripts/python.exe'
if (!(Test-Path -LiteralPath $python)) {
    python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível criar o ambiente Python. É necessário Python 3.10 ou superior.' }
}
& $python -m pip install -r (Join-Path $PSScriptRoot 'requirements-youtube.txt')
if ($LASTEXITCODE -ne 0) { throw 'A instalação do suporte YouTube falhou.' }
Write-Output 'Suporte YouTube preparado. Abre ou reinicia o ChatScope.'
