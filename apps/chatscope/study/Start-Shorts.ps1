$ErrorActionPreference = 'Stop'
$shorts = Join-Path $PSScriptRoot 'shorts.py'
$state = Join-Path $env:LOCALAPPDATA 'ChatScope/Shorts'
$python = Join-Path $state 'venv/Scripts/python.exe'

foreach ($name in @('venv/Scripts/python.exe', 'youtube.json', 'alerts.json')) {
    if (!(Test-Path -LiteralPath (Join-Path $state $name) -PathType Leaf)) {
        throw 'Falta ligar o canal ou configurar os avisos. Consulta o guia de Shorts.'
    }
}
$active = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like "*$shorts* enviar --vigiar*" } |
    Select-Object -First 1
if ($active) {
    Write-Output "Fila de Shorts já ativa (PID $($active.ProcessId))."
    return
}
$worker = Start-Process -FilePath $python -ArgumentList @('-X', 'utf8', '"' + $shorts + '"', 'enviar', '--vigiar') `
    -WindowStyle Hidden -RedirectStandardOutput (Join-Path $state 'worker.log') `
    -RedirectStandardError (Join-Path $state 'worker-erro.log') -PassThru
Write-Output "Fila de Shorts em segundo plano (PID $($worker.Id))."
