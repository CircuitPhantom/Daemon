# Sets up the Daemon laptop agent on Windows (wake word + desktop commands for a Daemon that runs on another computer).
# Run it in a normal (not administrator) PowerShell, inside a folder that has daemon-agent.py, tools.py, wakeword.py,
# win_desktop.py and screeninput.py (the Daemon folder works).
#
#   .\setup-agent.ps1 -Server https://NAME.tailnet.ts.net -Token TOKEN     install, save the settings, start the task
#   .\setup-agent.ps1 -Remove                                              stop and remove the task
#   options: -Device "mic name"  -Allow execute_command,screen_input  -NoService  -Print
#
# The server address is the one you open the dashboard with. The token comes from `python satellite_setup.py` on the server.
# The agent is a Task Scheduler task of YOUR user ("at log on"), not a Windows service: a service cannot reach your
# desktop (audio, clipboard, apps, mouse and keyboard). The token is kept in %APPDATA%\daemon-agent\config.json (only you can read it).
param(
    [string]$Server = '',
    [string]$Token = '',
    [string]$Device = '',
    [string[]]$Allow = @(),
    [switch]$NoService,
    [switch]$Print,
    [switch]$Remove
)
$ErrorActionPreference = 'Stop'
$TaskName = 'Daemon Agent'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Conf = Join-Path $env:APPDATA 'daemon-agent\config.json'
function Say($m) { Write-Host "`n== $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "warning: $m" -ForegroundColor Yellow }

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed the task '$TaskName' (the settings stay in $Conf)."
    } else {
        Write-Host "The task '$TaskName' is not installed."
    }
    exit 0
}
foreach ($f in 'daemon-agent.py', 'tools.py', 'wakeword.py', 'screeninput.py', 'win_desktop.py', 'platform_support.py') {
    if (-not (Test-Path (Join-Path $Here $f))) { throw "$f is missing in $Here (copy it from the Daemon folder)" }
}

# -- Python environment: an existing Daemon venv already has most of it --
Say 'Python environment'
$Py = $null
foreach ($v in 'venv', '.venv', 'agent-venv') {
    $cand = Join-Path $Here "$v\Scripts\python.exe"
    if (Test-Path $cand) {
        & $cand -c "import numpy, websockets, sounddevice, pycaw" 2>$null
        if ($LASTEXITCODE -eq 0) { $Py = $cand; break }
    }
}
if (-not $Py) {
    $Py = Join-Path $Here 'agent-venv\Scripts\python.exe'
    if (-not (Test-Path $Py)) {
        if (Get-Command py -ErrorAction SilentlyContinue) { py -3 -m venv (Join-Path $Here 'agent-venv') }
        elseif (Get-Command python -ErrorAction SilentlyContinue) { python -m venv (Join-Path $Here 'agent-venv') }
        else { throw 'Python not found. Install Python 3.10+ (winget install Python.Python.3.12) and open a new PowerShell.' }
        if ($LASTEXITCODE -ne 0) { throw 'could not create the venv' }
    }
    & $Py -m pip install --upgrade pip | Out-Null
    & $Py -m pip install -r (Join-Path $Here 'requirements-agent.txt')
    if ($LASTEXITCODE -ne 0) { throw 'pip install failed (see above)' }
}
$PyW = Join-Path (Split-Path -Parent $Py) 'pythonw.exe'
Write-Host "using $Py"

# -- Settings: written by Python (UTF-8 without BOM), then locked to your user --
$HaveNew = ($Server -ne '') -or ($Token -ne '') -or ($Allow.Count -gt 0) -or ($Device -ne '')
if ($HaveNew) {
    if (($Server -ne '' -or $Token -ne '') -and -not ($Server -ne '' -and $Token -ne '')) { throw 'give both -Server and -Token' }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Conf) | Out-Null
    $Tmp = Join-Path $env:TEMP 'daemon-agent-conf.py'
    @'
import json, os
conf = os.environ["DA_CONF"]
server, token, device = os.environ.get("DA_SERVER", ""), os.environ.get("DA_TOKEN", ""), os.environ.get("DA_DEVICE", "")
allow = [x for x in os.environ.get("DA_ALLOW", "").split(",") if x]
try:
    d = json.load(open(conf, encoding="utf-8-sig"))
except Exception:
    d = {}
if server:
    d.update(server=server, token=token)
if device:
    d["device"] = device
if allow:
    d["allow"] = sorted(set(d.get("allow") or []) | set(allow))
json.dump(d, open(conf, "w", encoding="utf-8"), indent=1)
'@ | Set-Content -Path $Tmp -Encoding ASCII
    # passed in environment variables: PowerShell 5.1 drops empty arguments of native commands
    $env:DA_CONF = $Conf; $env:DA_SERVER = $Server; $env:DA_TOKEN = $Token; $env:DA_DEVICE = $Device
    $env:DA_ALLOW = (@($Allow | ForEach-Object { $_ -split ',' } | Where-Object { $_ }) -join ',')
    & $Py $Tmp
    $code = $LASTEXITCODE
    Remove-Item Env:DA_CONF, Env:DA_SERVER, Env:DA_TOKEN, Env:DA_DEVICE, Env:DA_ALLOW -ErrorAction SilentlyContinue
    Remove-Item $Tmp -ErrorAction SilentlyContinue
    if ($code -ne 0) { throw 'could not save the settings' }
    & icacls $Conf /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null
    Write-Host "saved $Conf"
}
if (-not (Test-Path $Conf)) { throw 'no settings yet: run again with -Server and -Token' }

# -- Connection test --
Say 'Connection test'
$Tmp = Join-Path $env:TEMP 'daemon-agent-test.py'
@'
import json, sys, urllib.request
c = json.load(open(sys.argv[1], encoding="utf-8-sig"))
req = urllib.request.Request(c["server"].rstrip("/") + "/api/sat/config", headers={"Authorization": "Bearer " + c["token"], "User-Agent": "daemon-agent/1.0"})
try:
    urllib.request.urlopen(req, timeout=10)
    print("server answered, token accepted")
except Exception as e:
    print("could not use the server:", e)
    sys.exit(1)
'@ | Set-Content -Path $Tmp -Encoding ASCII
& $Py $Tmp $Conf
if ($LASTEXITCODE -ne 0) { Warn 'the agent will keep retrying; check the address, the token and that satellite is enabled on the server (python satellite_setup.py)' }
Remove-Item $Tmp -ErrorAction SilentlyContinue

if ($NoService) {
    Write-Host "Start by hand:  $Py daemon-agent.py"
    Write-Host "Check this desktop:  $Py daemon-agent.py --probe"
    exit 0
}

# -- Task Scheduler (at log on of this user) --
Say 'Task'
$Log = Join-Path $Here 'logs\agent.log'
$TaskArgs = "daemon-agent.py --log `"$Log`""
if ($Print) {
    Write-Host "Task:      $TaskName (at log on of $env:USERNAME, restarts after a crash)"
    Write-Host "Program:   $PyW"
    Write-Host "Arguments: $TaskArgs"
    Write-Host "Folder:    $Here"
    exit 0
}
$Action = New-ScheduledTaskAction -Execute $PyW -Argument $TaskArgs -WorkingDirectory $Here
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
    -Description 'Daemon laptop agent (wake word + desktop commands)' | Out-Null
Write-Host "Task '$TaskName' installed."
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 4
if (Test-Path $Log) { Write-Host 'Last log lines:'; Get-Content $Log -Tail 8 } else { Warn "no log yet: $Log" }
Write-Host @"

Useful commands (PowerShell):
  Get-Content "$Log" -Wait -Tail 30          live log
  Stop-ScheduledTask -TaskName "$TaskName"   stop it
  Start-ScheduledTask -TaskName "$TaskName"  start it again (also after updating the files)
  $Py daemon-agent.py --probe   check media, volume, clipboard, screenshot and apps on this desktop
  .\setup-agent.ps1 -Remove                  remove it
The first time the microphone is used, Windows may ask for permission (Settings > Privacy > Microphone, allow desktop apps).
"@
