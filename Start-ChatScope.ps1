param([switch]$Build)

$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'apps/chatscope/Start-ChatScope.ps1') -Build:$Build
