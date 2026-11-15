# Packs everything that is *yours* (settings, calendar, chats, memory, logins) into one archive, to move Daemon
# to another computer or to keep a backup. The code itself is not needed in it, copy the project folder separately.
# The archive is a .tar.gz with the same layout as backup.sh makes, so Linux and Windows backups restore on either.
#
#   .\backup.ps1                          settings, tasks, calendar, memory, reminders, chats, Spotify login
#   .\backup.ps1 -WithSignal              ...and the Signal account (signal-cli data)
#   .\backup.ps1 -WithSignal -Stop        same, and stop the Daemon task first (so the Signal data is not changing)
#   .\backup.ps1 -Out C:\path\file.tar.gz where to write it (default: ~\daemon-backup-DATE.tar.gz)
#   .\backup.ps1 -Project DIR             back up the Daemon folder DIR instead of the one this script is in
#   .\backup.ps1 -WithFiles               ...and the Daemon folder (~\Documents\Daemon: files you sent, notes it wrote)
#   .\backup.ps1 -Dir DIR -Keep 14        write DIR\daemon-backup-DATE.tar.gz and keep only the newest 14 there
#   .\backup.ps1 -InstallTimer            daily automatic backup (Task Scheduler): ~\daemon-backups, newest 14 kept,
#                                         with the Daemon folder, without the Signal account (it is in use while running)
#   .\backup.ps1 -RemoveTimer             turn the daily backup off
#
# The archive holds your API keys and the Signal login: it is made readable for your user only. Move it with a USB
# stick, never through a chat or cloud storage, and delete it when you are done.
param(
    [switch]$WithSignal,
    [switch]$Stop,
    [string]$Project = '',
    [string]$Out = '',
    [string]$Dir = '',
    [int]$Keep = 0,
    [switch]$WithFiles,
    [switch]$InstallTimer,
    [switch]$RemoveTimer
)
$ErrorActionPreference = 'Stop'
$Here = if ($Project) { (Resolve-Path $Project).Path } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$ScriptPath = $MyInvocation.MyCommand.Path
$DataHome = if ($env:XDG_DATA_HOME) { $env:XDG_DATA_HOME } else { Join-Path $HOME '.local\share' }
$SignalDir = Join-Path $DataHome 'signal-cli'
$FilesDir = if ($env:DAEMON_FILES) { $env:DAEMON_FILES } else { Join-Path $HOME 'Documents\Daemon' }
$TaskName = 'Daemon Backup'

if ($RemoveTimer) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }
    Write-Host "Daily backup is off (old backups stay in ~\daemon-backups)."
    exit 0
}
if ($InstallTimer) {
    $dest = Join-Path $HOME 'daemon-backups'
    $arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`" -Project `"$Here`" -Dir `"$dest`" -Keep 14 -WithFiles"
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arg
    $trigger = New-ScheduledTaskTrigger -Daily -At '04:17'
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force `
        -Description 'Daemon daily backup' | Out-Null
    Write-Host "Daily backup is on: every day around 04:17 into $dest (the newest 14 are kept; a missed run starts when the computer is on again)."
    Write-Host "  run one now:   Start-ScheduledTask -TaskName '$TaskName'"
    exit 0
}

if (-not $Out) {
    $base = if ($Dir) { $Dir } else { $HOME }
    $Out = Join-Path $base ("daemon-backup-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + ".tar.gz")
}
foreach ($v in 'DAEMON_CONFIG', 'DAEMON_CHATS', 'DAEMON_MEMORY', 'DAEMON_REMINDERS', 'DAEMON_CALENDAR', 'DAEMON_INBOX', 'DAEMON_TOOL_LOG') {
    $val = [Environment]::GetEnvironmentVariable($v)
    if ($val) { Write-Host "warning: $v is set ($val): files outside the project folder are not included" }
}

$task = Get-ScheduledTask -TaskName 'Daemon' -ErrorAction SilentlyContinue
if ($task -and $task.State -eq 'Running') {
    if ($Stop) {
        Stop-ScheduledTask -TaskName 'Daemon'
        Write-Host "Stopped the Daemon task (start it again with: Start-ScheduledTask -TaskName Daemon). On the new computer start only one copy."
    } elseif ($WithSignal) {
        Write-Host 'The Daemon task is running and uses the Signal data. Stop it first or add -Stop:' -ForegroundColor Red
        Write-Host '  Stop-ScheduledTask -TaskName Daemon'
        exit 1
    }
}

$Stage = Join-Path $env:TEMP ("daemon-backup-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path "$Stage\project" | Out-Null
try {
    $copied = @()
    foreach ($f in 'config.yaml', '.env', 'tasks.yaml', 'calendar.json', 'memory.json', 'reminders.json', 'inbox.json', 'tool_log.jsonl', 'spotify_token.json', 'tts_usage.json') {
        $src = Join-Path $Here $f
        if (Test-Path $src) { Copy-Item $src "$Stage\project\$f"; $copied += $f }
    }
    foreach ($d in 'chats', 'runs', 'static\lib') {
        $src = Join-Path $Here $d
        if (Test-Path $src) {
            $target = Join-Path "$Stage\project" $d
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
            Copy-Item $src $target -Recurse
            $copied += "$d/"
        }
    }
    # exact package versions of this machine, for a repeatable install
    foreach ($cand in @($env:VIRTUAL_ENV, (Join-Path $Here 'venv'), (Join-Path $Here '.venv'))) {
        if ($cand -and (Test-Path (Join-Path $cand 'Scripts\python.exe'))) {
            & (Join-Path $cand 'Scripts\python.exe') -m pip freeze 2>$null | Set-Content -Path "$Stage\project\requirements.lock" -Encoding ASCII
            $copied += 'requirements.lock'
            break
        }
    }
    if ($WithFiles) {
        if (Test-Path $FilesDir) { Copy-Item $FilesDir "$Stage\daemon-files" -Recurse; $copied += "Daemon folder ($FilesDir)" }
        else { Write-Host "note: no Daemon folder at $FilesDir, skipped" }
    }
    if ($WithSignal) {
        if (Test-Path $SignalDir) {
            Copy-Item $SignalDir "$Stage\signal-cli" -Recurse
            foreach ($x in 'attachments', 'avatars', 'stickers') { Remove-Item "$Stage\signal-cli\$x" -Recurse -Force -ErrorAction SilentlyContinue }
            $copied += 'signal-cli account'
        } else { Write-Host "warning: no Signal data in $SignalDir, skipped" -ForegroundColor Yellow }
    }
    $manifest = @(
        'Daemon backup',
        ('date:     ' + (Get-Date -Format 'yyyy-MM-ddTHH:mm:sszzz')),
        ('host:     ' + $env:COMPUTERNAME),
        ('os:       Windows'),
        ('contents: ' + ($copied -join ' '))
    )
    Set-Content -Path "$Stage\MANIFEST.txt" -Value $manifest -Encoding ASCII

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Out) | Out-Null
    tar -C $Stage -czf $Out .
    if ($LASTEXITCODE -ne 0) { throw 'tar could not write the archive' }
    try { icacls $Out /inheritance:r /grant:r "${env:USERNAME}:(R,W,D)" | Out-Null } catch { Write-Host 'note: could not restrict the archive to your user' }
} finally {
    Remove-Item $Stage -Recurse -Force -ErrorAction SilentlyContinue
}

if ($Keep -gt 0 -and $Dir) {                          # rotation: only the newest Keep backups in Dir
    $old = Get-ChildItem -Path $Dir -Filter 'daemon-backup-*.tar.gz' | Sort-Object LastWriteTime -Descending | Select-Object -Skip $Keep
    if ($old) { $old | Remove-Item -Force; Write-Host "Removed $(@($old).Count) old backup(s) from $Dir" }
}

$size = '{0:N1} MB' -f ((Get-Item $Out).Length / 1MB)
Write-Host ''
Write-Host "Wrote $Out ($size)"
Write-Host "Contains: $($copied -join ' ')"
if (-not $WithSignal) { Write-Host 'Signal account not included (add -WithSignal if the new computer should keep the same Signal login).' }
$secrets = if ($WithSignal) { 'API keys and the Signal login' } else { 'API keys' }
Write-Host "It holds secrets ($secrets): copy it with a USB stick and delete it afterwards."
