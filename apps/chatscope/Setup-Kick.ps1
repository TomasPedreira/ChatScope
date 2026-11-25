param([switch]$Captions)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'Setup-Media.ps1') -Captions:$Captions
if ($LASTEXITCODE -ne 0) { throw 'A preparação de media falhou.' }
$python = Join-Path $PSScriptRoot '.venv-youtube/Scripts/python.exe'
& $python -m pip install -r (Join-Path $PSScriptRoot 'requirements-kick.txt')
if ($LASTEXITCODE -ne 0) { throw 'A preparação do suporte Kick falhou.' }
Write-Output 'Suporte Kick preparado. VODs e diretos usam áudio como sinal e o renderer comum.'
