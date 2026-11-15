# Sets Daemon up on a Windows computer: programs, Python environment, web libraries, your backup, the background task.
# Run it in PowerShell inside the project folder (the one with server.py), as your normal user.
#
#   .\setup.ps1                            install everything that is missing
#   .\setup.ps1 -Restore C:\path\backup.tar.gz   also restore settings, calendar, chats, memory and the Signal login
#   .\setup.ps1 -Models                    also download the speech models now (otherwise on first start)
#   .\setup.ps1 -Service                   also install and start the background task (install-service.ps1)
#   .\setup.ps1 -NoSystem                  skip the programs (winget)
#   .\setup.ps1 -Yes                       do not ask questions
#
# If PowerShell refuses to run the script:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
# Safe to run again: it only adds what is missing.
param(
    [string]$Restore = '',
    [switch]$Models,
    [switch]$Service,
    [switch]$NoSystem,
    [switch]$Yes
)
$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Here
$DataHome = if ($env:XDG_DATA_HOME) { $env:XDG_DATA_HOME } else { Join-Path $HOME '.local\share' }
$SignalDir = Join-Path $DataHome 'signal-cli'

function Say($t)  { Write-Host "`n== $t" -ForegroundColor Cyan }
function Warn($t) { Write-Host "warning: $t" -ForegroundColor Yellow }
function Ask($q)  { if ($Yes) { return $true }; $a = Read-Host "$q [Y/n]"; return ($a -eq '' -or $a -match '^[Yy]') }
function Have($c) { return [bool](Get-Command $c -ErrorAction SilentlyContinue) }

if (-not ((Test-Path server.py) -and (Test-Path model_config.py))) { throw 'run this inside the Daemon project folder (server.py not found here)' }

# -- 1. programs (winget) --
if (-not $NoSystem) {
    Say 'Programs'
    if (-not (Have 'winget')) {
        Warn 'winget not found (Windows 10 1809+ / 11 has it; install "App Installer" from the Microsoft Store). Install by hand: Python 3.10+, ffmpeg, Java 21, signal-cli, Tailscale.'
    } else {
        $pkgs = @()
        if (-not (Have 'py') -and -not (Have 'python')) { $pkgs += 'Python.Python.3.12' }
        if (-not (Have 'ffmpeg')) { $pkgs += 'Gyan.FFmpeg' }
        if (-not (Have 'java')) { $pkgs += 'EclipseAdoptium.Temurin.21.JRE' }
        if (-not (Have 'tailscale')) { $pkgs += 'Tailscale.Tailscale' }
        if ($pkgs.Count -gt 0) {
            Write-Host "Missing: $($pkgs -join ', ')"
            if (Ask 'Install them with winget?') {
                foreach ($p in $pkgs) { winget install --id $p -e --accept-package-agreements --accept-source-agreements }
                Warn 'Close this PowerShell window and open a new one so the new programs are found, then run .\setup.ps1 again.'
            } else { Warn 'skipped' }
        } else { Write-Host 'all there' }
    }
    if (-not (Have 'signal-cli') -and -not (Have 'signal-cli.bat')) {
        Warn 'signal-cli is not installed (only needed for Signal): download the release from github.com/AsamK/signal-cli/releases, unzip it and add its bin folder to PATH.'
    }
}

# -- 2. Python environment --
Say 'Python environment'
$VenvPy = Join-Path $Here 'venv\Scripts\python.exe'
if (-not (Test-Path $VenvPy)) {
    if (Have 'py') { py -3 -m venv venv } elseif (Have 'python') { python -m venv venv } else { throw 'Python not found. Install Python 3.10+ (winget install Python.Python.3.12) and open a new PowerShell.' }
    if ($LASTEXITCODE -ne 0) { throw 'could not create the venv' }
}
$Req = 'requirements.txt'
if ((Test-Path requirements.lock) -and (Ask 'Use the exact versions from requirements.lock (from your old computer)?')) { $Req = 'requirements.lock' }
& $VenvPy -m pip install --upgrade pip | Out-Null
& $VenvPy -m pip install -r $Req
if ($LASTEXITCODE -ne 0) { throw 'pip install failed (see above)' }
Write-Host "installed from $Req"

# -- 3. web libraries (3D sphere, markdown, code highlighting) --
Say 'Web libraries'
New-Item -ItemType Directory -Force -Path static\lib | Out-Null
$libs = @(
    @('three.min.js',        'https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js'),
    @('marked.min.js',       'https://cdn.jsdelivr.net/npm/marked@16.3.0/lib/marked.umd.min.js'),
    @('highlight.min.js',    'https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.10.0/build/highlight.min.js'),
    @('github-dark.min.css', 'https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.10.0/build/styles/github-dark.min.css')
)
foreach ($l in $libs) {
    $dest = Join-Path 'static\lib' $l[0]
    if ((Test-Path $dest) -and ((Get-Item $dest).Length -gt 0)) { continue }
    try { Invoke-WebRequest -UseBasicParsing -Uri $l[1] -OutFile $dest; Write-Host "downloaded $($l[0])" }
    catch { Warn "could not download $($l[0]) from $($l[1])" }
}

# -- 4. restore the backup (same archive layout as backup.sh: works with a backup made on Linux) --
if ($Restore) {
    Say "Restoring $Restore"
    if (-not (Test-Path $Restore)) { throw "backup file not found: $Restore" }
    if (Get-ScheduledTask -TaskName Daemon -ErrorAction SilentlyContinue | Where-Object { $_.State -eq 'Running' }) {
        throw 'the Daemon task is running here: stop it first (Stop-ScheduledTask -TaskName Daemon)'
    }
    $Tmp = Join-Path $env:TEMP ("daemon-restore-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $Tmp | Out-Null
    try {
        tar -C $Tmp -xzf $Restore
        if ($LASTEXITCODE -ne 0) { throw 'tar could not unpack the backup' }
        if (Test-Path "$Tmp\MANIFEST.txt") { Get-Content "$Tmp\MANIFEST.txt" | ForEach-Object { "  $_" } }
        $Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
        if (Test-Path "$Tmp\project") {
            # whatever exists here is kept as *.before-restore-STAMP, nothing is lost
            foreach ($item in Get-ChildItem "$Tmp\project" -Force) {
                $name = $item.Name
                if ($name -eq 'requirements.lock' -and (Test-Path requirements.lock)) { continue }
                if ((Test-Path $name) -and $name -ne 'static') { Move-Item $name "$name.before-restore-$Stamp" }
                if ($name -eq 'static') { New-Item -ItemType Directory -Force -Path static | Out-Null; Copy-Item "$($item.FullName)\*" static -Recurse -Force }
                else { Copy-Item $item.FullName ".\$name" -Recurse -Force }
            }
            Write-Host "settings and data restored (old files, if any, are named *.before-restore-$Stamp)"
        }
        if (Test-Path "$Tmp\daemon-files") {
            $FilesDir = if ($env:DAEMON_FILES) { $env:DAEMON_FILES } else { Join-Path $HOME 'Documents\Daemon' }
            if (Test-Path $FilesDir) { Move-Item $FilesDir "$FilesDir.before-restore-$Stamp"; Write-Host "existing Daemon folder kept as $FilesDir.before-restore-$Stamp" }
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $FilesDir) | Out-Null
            Copy-Item "$Tmp\daemon-files" $FilesDir -Recurse
            Write-Host "Daemon folder restored to $FilesDir"
        }
        if (Test-Path "$Tmp\signal-cli") {
            if (Test-Path $SignalDir) { Move-Item $SignalDir "$SignalDir.before-restore-$Stamp"; Write-Host "existing Signal data kept as $SignalDir.before-restore-$Stamp" }
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $SignalDir) | Out-Null
            Copy-Item "$Tmp\signal-cli" $SignalDir -Recurse
            Write-Host "Signal account restored to $SignalDir"
            Write-Host 'IMPORTANT: the old computer must NOT run Daemon or signal-cli any more, one account can only live in one place.'
        }
    } finally {
        Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# -- 5. models --
if ($Models) {
    Say 'Models'
    $py = @'
import model_config as m
from faster_whisper import WhisperModel
print("speech recognition:", m.stt["model"])
WhisperModel(m.stt["model"], device=m.stt["device"], compute_type=m.stt["compute_type"])
from pykokoro import KokoroSynthesizer, GenerationConfig, SynthesisConfig
print("voice: kokoro")
with KokoroSynthesizer(SynthesisConfig(voice=m.tts["voice"], generation=GenerationConfig(lang=m.tts["lang"]))) as s:
    s.synthesize_text("ok", language=m.tts["lang"], voice=m.tts["voice"])
'@
    $env:PYTHONUTF8 = '1'
    & $VenvPy -c $py
    if ($LASTEXITCODE -ne 0) { Warn 'could not pre-load the speech models (they download on the first start instead). If it mentions espeak, see docs/windows.md.' }
}

# -- 6. background task --
if ($Service) {
    Say 'Background task'
    & "$Here\install-service.ps1"
}

Say 'Done'
Write-Host @"
Next:
  venv\Scripts\python.exe doctor.py        check that everything is in place
  .\install-service.ps1                    run Daemon in the background from log on (or: .\setup.ps1 -Service)
  python serve.py                          or just run it in this window
  Open http://127.0.0.1:8000               the dashboard
Settings to revisit on a new computer (MIGRATION.md has the details):
  notify.base_url, phone.public_url        new Tailscale address, and the Twilio incoming-call webhook
  wake.input_device                        microphone name can differ
  stt.device                               "cuda" only if this computer has an NVIDIA GPU
"@
