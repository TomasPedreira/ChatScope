[CmdletBinding(DefaultParameterSetName = 'Install')]
param(
    [Parameter(ParameterSetName = 'Install')]
    [guid]$Thread = $env:CODEX_THREAD_ID,
    [Parameter(ParameterSetName = 'Status', Mandatory)]
    [switch]$Status,
    [Parameter(ParameterSetName = 'Stop', Mandatory)]
    [switch]$Stop
)

$ErrorActionPreference = 'Stop'
$taskName = 'ChatScope - Rotina de clipping'
if ($Stop) {
    Disable-ScheduledTask -TaskName $taskName | Out-Null
    return
}
if ($Status) {
    $task = Get-ScheduledTask -TaskName $taskName
    $info = Get-ScheduledTaskInfo -InputObject $task
    [pscustomobject]@{ Name = $task.TaskName; State = $task.State; NextRun = $info.NextRunTime; LastResult = $info.LastTaskResult }
    return
}

if ($Thread -eq [guid]::Empty) {
    throw 'Executa o instalador a partir da conversa de Clipping ou indica -Thread.'
}
$codex = Get-Process codex | Where-Object { $_.Path } | Select-Object -First 1 -ExpandProperty Path
if (!$codex) { throw 'Não encontrei o executável do Codex em execução.' }
$python = (Get-Command python.exe).Source
$pythonw = (Get-Command pythonw.exe).Source
$runner = Join-Path $PSScriptRoot 'rotina.py'
$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path
& $python -X utf8 $runner --codex $codex --thread $Thread --check
if ($LASTEXITCODE -ne 0) { throw 'Falhou a verificação da fila do Codex.' }

$now = Get-Date
$morning = $now.Date.AddHours(8)
$evening = $now.Date.AddHours(22)
$dailyStart = if ($now -lt $morning) { $morning } else { $morning.AddDays(1) }
$interval = New-TimeSpan -Minutes 30
$daily = New-ScheduledTaskTrigger -Daily -At $dailyStart
$pattern = New-ScheduledTaskTrigger -Once -At $dailyStart -RepetitionInterval $interval -RepetitionDuration ($evening - $morning)
$daily.Repetition = $pattern.Repetition
$triggers = @($daily)
if ($morning -le $now -and $now -lt $evening) {
    $nextSlot = $now.Date.AddMinutes(30 * ([math]::Floor($now.TimeOfDay.TotalMinutes / 30) + 1))
    if ($nextSlot -lt $evening) {
        $triggers += New-ScheduledTaskTrigger -Once -At $nextSlot -RepetitionInterval $interval -RepetitionDuration ($evening - $nextSlot)
    }
}

$arguments = '"{0}" --codex "{1}" --thread {2}' -f $runner, $codex, $Thread
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $workspace
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 4)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings `
    -Description 'Reabre a triagem de Clipping na mesma conversa a cada meia hora, das 08:00 às 22:00.' -Force | Out-Null
& $PSCommandPath -Status
