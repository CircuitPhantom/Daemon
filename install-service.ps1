# Runs Daemon in the background from the moment you log in to Windows (Task Scheduler, no extra program needed).
# It is a task of YOUR user, not a Windows service: a service runs in session 0 and cannot reach your desktop
# (clipboard, audio, apps, mouse and keyboard), a task at log on can.
#
#   .\install-service.ps1             install (or update) and start
#   .\install-service.ps1 -Port 8001  another port (default 8000, or $env:DAEMON_PORT)
#   .\install-service.ps1 -Print      only show what would be installed
#   .\install-service.ps1 -Remove     stop and remove
#
# Run it from the project folder (the one with server.py), in a normal (not administrator) PowerShell.
param(
    [int]$Port = $(if ($env:DAEMON_PORT) { [int]$env:DAEMON_PORT } else { 8000 }),
    [switch]$Print,
    [switch]$Remove
)
$ErrorActionPreference = 'Stop'
$TaskName = 'Daemon'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed the task '$TaskName'."
    } else {
        Write-Host "The task '$TaskName' is not installed."
    }
    exit 0
}

if (-not (Test-Path (Join-Path $Here 'server.py'))) { throw "server.py not found in $Here. Run this script from the Daemon folder." }

# Find the virtual environment: the active one first, then the usual folder names
$Py = $null
foreach ($cand in @($env:VIRTUAL_ENV, (Join-Path $Here 'venv'), (Join-Path $Here '.venv'))) {
    if ($cand) {
        $w = Join-Path $cand 'Scripts\pythonw.exe'
        if (Test-Path $w) { $Py = $w; break }
    }
}
if (-not $Py) { throw "no virtual environment found. Run .\setup.ps1 first (or activate your venv) and try again." }
$PyCheck = Join-Path (Split-Path -Parent $Py) 'python.exe'
& $PyCheck -c "import uvicorn, fastapi" 2>$null
if ($LASTEXITCODE -ne 0) { throw "uvicorn/fastapi are not installed in $PyCheck" }

$Log = Join-Path $Here 'logs\daemon.log'
$TaskArgs = "serve.py --host 127.0.0.1 --port $Port --log `"$Log`""

if ($Print) {
    Write-Host "Task:      $TaskName (at log on of $env:USERNAME, restarts after a crash)"
    Write-Host "Program:   $Py"
    Write-Host "Arguments: $TaskArgs"
    Write-Host "Folder:    $Here"
    exit 0
}

# pythonw.exe has no console window; serve.py writes everything to logs\daemon.log
$Action = New-ScheduledTaskAction -Execute $Py -Argument $TaskArgs -WorkingDirectory $Here
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew -StartWhenAvailable

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings `
    -Description 'Daemon voice assistant (web UI)' | Out-Null
Write-Host "Task '$TaskName' installed."
Start-ScheduledTask -TaskName $TaskName

# wait until the port answers
$up = $false
for ($i = 0; $i -lt 40 -and -not $up; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $c.Connect('127.0.0.1', $Port)
        $c.Close()
        $up = $true
    } catch { }
}
if ($up) {
    Write-Host "Daemon is running on http://127.0.0.1:$Port"
} else {
    Write-Host "The server did not answer within 20 seconds. Last log lines:"
    if (Test-Path $Log) { Get-Content $Log -Tail 30 } else { Write-Host "(no log yet: $Log)" }
    exit 1
}
Write-Host @"

Useful commands (PowerShell):
  Get-Content "$Log" -Wait -Tail 30     live log
  Stop-ScheduledTask -TaskName Daemon   stop it
  Start-ScheduledTask -TaskName Daemon  start it again (also after updating the files)
  .\install-service.ps1 -Remove         remove it
Windows may ask once whether python may listen on the network; the default (127.0.0.1) needs no firewall rule.
"@
