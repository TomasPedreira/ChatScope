[CmdletBinding(DefaultParameterSetName = 'Run')]
param(
    [Parameter(ParameterSetName = 'Run')]
    [ValidateRange(0.1, 10)]
    [double]$Hours = 8,
    [Parameter(ParameterSetName = 'Run')]
    [switch]$ForaDoHorario,
    [Parameter(ParameterSetName = 'Check', Mandatory)]
    [switch]$Check,
    [Parameter(ParameterSetName = 'Status', Mandatory)]
    [switch]$Status,
    [Parameter(ParameterSetName = 'Stop', Mandatory)]
    [switch]$Stop
)

$ErrorActionPreference = 'Stop'
$collector = Join-Path $PSScriptRoot 'collector.py'
$supervisor = Join-Path $PSScriptRoot 'supervise.py'
$workspace = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path
$results = Join-Path $workspace 'media/twitch/estudo-ao-vivo'
$latest = Join-Path $results 'ultima-sessao.txt'

if ($Check) {
    python $collector preflight
    if ($LASTEXITCODE -ne 0) { throw 'Falhou a verificação das fontes.' }
    return
}

$previous = $null
if (Test-Path -LiteralPath $latest -PathType Leaf) {
    $sessionName = (Get-Content -LiteralPath $latest -Raw).Trim()
    if ($sessionName -match '^\d{8}-\d{6}-[0-9a-f]{8}$') {
        $previous = Join-Path $results $sessionName
    }
}
if ($Status -or $Stop) {
    if (!$previous -or !(Test-Path -LiteralPath $previous -PathType Container)) {
        Write-Output 'Ainda não há uma sessão de estudo.'
        return
    }
    if ($Stop) {
        New-Item -ItemType File -Path (Join-Path $previous 'parar') -Force | Out-Null
        Write-Output 'Paragem pedida. O coletor termina os cortes que já estão em curso.'
    } else {
        $state = Join-Path $previous 'estado.json'
        if (Test-Path -LiteralPath $state) {
            $summary = Get-Content -LiteralPath $state -Raw | ConvertFrom-Json
            $summary | Select-Object status, start, deadline, updated, activeChannels, measuredWindows, failures
        } else {
            Write-Output 'Ainda não há estado. Verifica collector.stderr.log na pasta da sessão.'
        }
        $health = Join-Path $previous 'vigia.json'
        if (Test-Path -LiteralPath $health -PathType Leaf) {
            $lastCheck = Get-Content -LiteralPath $health -Raw | ConvertFrom-Json
            Write-Output "Última verificação ($($lastCheck.utc)): $($lastCheck.status)"
        }
    }
    Write-Output $previous
    return
}

$running = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like "*$collector* run --hours*" -or
                   $_.CommandLine -like "*$supervisor* --hours*" } |
    Select-Object -First 1
if ($running) { throw "O estudo já está em execução (PID $($running.ProcessId))." }

$today = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTimeOffset]::UtcNow, 'GMT Standard Time')
if (!$ForaDoHorario -and ($today.Hour -lt 8 -or $today.TimeOfDay -ge [TimeSpan]::FromMinutes(1318))) {
    throw 'O estudo só arranca das 08:00 até às 21:58, hora de Lisboa.'
}

$pythonPath = (Get-Command python.exe).Source
$sessionName = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + ([Guid]::NewGuid().ToString('N').Substring(0, 8))
$folder = Join-Path $results $sessionName
New-Item -ItemType Directory -Path $folder | Out-Null
$duration = $Hours.ToString([Globalization.CultureInfo]::InvariantCulture)
$arguments = @(('"' + $supervisor + '"'), '--hours', $duration, '--folder', ('"' + $folder + '"'))
if ($ForaDoHorario) { $arguments += '--fora-do-horario' }
$process = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $workspace `
    -WindowStyle Hidden -RedirectStandardOutput (Join-Path $folder 'supervisor.stdout.log') `
    -RedirectStandardError (Join-Path $folder 'supervisor.stderr.log') -PassThru
Set-Content -LiteralPath $latest -Value $sessionName -Encoding ascii
Write-Output "Estudo iniciado em segundo plano (PID $($process.Id))."
Write-Output $folder
