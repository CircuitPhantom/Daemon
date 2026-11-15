import os, sys, io, tempfile
sys.path[:0]=["stubs","."]
def ok(c,m=""):
    if not c: print("FAIL",m); sys.exit(1)
import platform_support as ps

# replace_file: retries on Windows when the target is busy, raises at once on Linux
d=tempfile.mkdtemp()
a,b=d+"/a",d+"/b"
open(a,"w").write("new"); open(b,"w").write("old")
real=os.replace; calls=[]
def flaky(s,t):
    calls.append(1)
    if len(calls)<3: raise PermissionError("busy")
    return real(s,t)
os.replace=flaky
try:
    ps.IS_WINDOWS=True; ps.replace_file(a,b,delay=0)
    ok(len(calls)==3 and open(b).read()=="new", "retried until free")
    def always(s,t): raise PermissionError("busy")
    os.replace=always
    try: ps.replace_file(a,b,tries=3,delay=0); ok(False,"must raise after the last try")
    except PermissionError: pass
    ps.IS_WINDOWS=False; n=[]
    def once(s,t): n.append(1); raise PermissionError("busy")
    os.replace=once
    try: ps.replace_file(a,b,delay=0); ok(False,"must raise")
    except PermissionError: pass
    ok(len(n)==1, "no retry on Linux")
finally:
    os.replace=real

# readable_by_others: mode bits on POSIX, never on Windows
open(a,"w").write("x")
if sys.platform!="win32":
    os.chmod(a,0o644); ps.IS_WINDOWS=False; ok(ps.readable_by_others(a), "644 is readable by others")
    os.chmod(a,0o600); ok(not ps.readable_by_others(a), "600 is private")
    os.chmod(a,0o644); ps.IS_WINDOWS=True; ok(not ps.readable_by_others(a), "no warning on Windows")
ps.IS_WINDOWS=(sys.platform=="win32")

# setup_console: switches to UTF-8, survives streams without reconfigure()
old=sys.stdout, sys.stderr
try:
    sys.stdout=io.TextIOWrapper(io.BytesIO(), encoding="cp1254"); sys.stderr=io.StringIO()
    ps.setup_console(); sys.stdout.write("✓ ı"); sys.stdout.flush()
    ok(sys.stdout.encoding.lower().replace("-","")=="utf8", sys.stdout.encoding)
finally:
    sys.stdout, sys.stderr = old
ok(os.environ.get("PYTHONUTF8")=="1", "child Python processes use UTF-8")
print("ok")

# ───────── step 2: backends ─────────
import base64, subprocess, types, importlib
import platform_windows as pw
import platform_linux as pl

# Windows shell: PowerShell with an encoded command (quotes, pipes and Turkish letters pass through untouched)
cmd="Write-Output 'çay \"1\" | x'; Get-Date"
argv=pw.powershell_argv(cmd)
ok(argv[0].lower().endswith("powershell") or argv[0].lower().endswith("powershell.exe"), argv[0])
ok(argv[argv.index("-EncodedCommand")-1]=="Bypass" and "-NoProfile" in argv and "-NonInteractive" in argv, argv[:6])
decoded=base64.b64decode(argv[-1]).decode("utf-16-le")
ok(decoded.endswith(cmd) and "OutputEncoding" in decoded, decoded[:120])

# kill_tree: taskkill /T /F, then Popen.kill()
calls=[]; real_run=subprocess.run
subprocess.run=lambda a,**k:(calls.append(a),types.SimpleNamespace(returncode=0))[1]
class P:
    pid=4242; killed=False
    def kill(self): self.killed=True
try:
    p=P(); pw.kill_tree(p)
    ok(calls[0][:4]==["taskkill","/T","/F","/PID"] and calls[0][4]=="4242" and p.killed, calls)
finally:
    subprocess.run=real_run

# system_info on Windows with a fake psutil
fake=types.ModuleType("psutil")
fake.boot_time=lambda: __import__("time").time()-90061
fake.cpu_percent=lambda interval=0: 12.0
fake.virtual_memory=lambda: types.SimpleNamespace(total=16*2**30, available=6*2**30, percent=62.5)
fake.sensors_battery=lambda: types.SimpleNamespace(percent=80, power_plugged=False)
class Pr:
    def __init__(s,n,m): s.info={"name":n,"memory_percent":m}
fake.process_iter=lambda attrs=None:[Pr("chrome.exe",9.5),Pr("python.exe",3.1),Pr("idle",0.0),Pr("code.exe",5.0)]
sys.modules["psutil"]=fake
try:
    lines=pw.system_info(); txt="\n".join(lines)
    ok("Uptime: 1 d 1 h 1 min" in txt, txt); ok("Memory: 10.0 GB used of 16.0 GB (62%)" in txt, txt)
    ok("Battery: 80% (discharging)" in txt and "CPU: 12% busy" in txt, txt)
    ok("Biggest processes (name, %mem): chrome.exe 9.5; code.exe 5.0; python.exe 3.1" in txt, txt)
    ok(pw.mem_available_percent()==100.0*6/16, "mem percent")
    del sys.modules["psutil"]; sys.modules["psutil"]=None          # import fails -> hint instead of a crash
    ok("install psutil" in "\n".join(pw.system_info()), "no psutil")
finally:
    sys.modules.pop("psutil",None)

# service_state: parses schtasks, also on a Turkish Windows
real_sch=pw._schtasks
try:
    pw._schtasks=lambda *a:(0,"TaskName: \\Daemon\nStatus:   Running")
    ok(pw.service_state("daemon")=="active", "running")
    pw._schtasks=lambda *a:(0,"Görev Adı: \\Daemon\nDurum:   Çalışıyor")
    ok(pw.service_state("daemon")=="active", "running (tr)")
    pw._schtasks=lambda *a:(0,"Durum:   Hazır")
    ok(pw.service_state("daemon-agent")=="inactive", "ready (tr)")
    seen=[]; pw._schtasks=lambda *a:(seen.append(a),(1,"ERROR: The system cannot find the file specified."))[1]
    ok(pw.service_state("daemon-agent")=="not installed" and "Daemon Agent" in seen[0], seen)
    ok(pw.backup_scheduled() is False, "no backup task")
finally:
    pw._schtasks=real_sch

# the facade picks the backend and the model gets the shell hint only on Windows
ps.IS_WINDOWS=True
ok(ps.backend() is pw and "PowerShell" in ps.shell_hint(), "windows backend")
import conversation as conv
ok("PowerShell" in conv.system_msg()["content"], "hint in the system prompt")
ps.IS_WINDOWS=False
ok(ps.backend() is pl and ps.shell_hint()=="" and "PowerShell" not in conv.system_msg()["content"], "linux backend, no hint")
ps.IS_WINDOWS=(sys.platform=="win32")

# Linux backend still reports (real /proc and /sys on a Linux box)
if sys.platform.startswith("linux"):
    out="\n".join(pl.system_info()); ok("Memory:" in out and "Uptime:" in out and "Disk /:" in out, out)
    ok(0<pl.mem_available_percent()<=100, "mem percent")
    pr=ps.start_shell("echo hi; sleep 30 & wait"); import time; time.sleep(0.3); ps.kill_tree(pr); pr.wait(5)
    ok(pr.returncode is not None, "process group killed")

# search_text without grep: same file:line:text answer from plain Python
import tools
base=tempfile.mkdtemp()
os.makedirs(base+"/sub"); os.makedirs(base+"/venv")
open(base+"/a.txt","w",encoding="utf-8").write("one\nHello World\nthree\nhello again\nhello 3\nhello 4\n")
open(base+"/sub/b.txt","w",encoding="utf-8").write("nothing\ncaf\u00e9 HELLO\n")
open(base+"/venv/c.txt","w",encoding="utf-8").write("hello in a skipped folder\n")
open(base+"/bin.dat","wb").write(b"hello\0binary")
res=tools._grep_python("hello", __import__("pathlib").Path(base))
lines=res.splitlines()
ok(len([l for l in lines if l.startswith(os.path.join(base,"a.txt")+":")])==3, res)           # max 3 per file
ok(any(l.endswith(":2:caf\u00e9 HELLO") for l in lines), res)
ok("venv" not in res and "bin.dat" not in res, res)
ok(tools._grep_python("zzzz", __import__("pathlib").Path(base))=="No matches found", "no match")
real_run=subprocess.run
def nogrep(*a,**k): raise FileNotFoundError("grep")
subprocess.run=nogrep
try:
    out=tools.search_text(text="hello", path=base); ok("a.txt:2:Hello World" in out, out)
finally:
    subprocess.run=real_run

# serve.py: all output (also of child processes) goes to the log file
logf=os.path.join(base,"logs","daemon.log")
code=("import sys; sys.path.insert(0,'.'); import serve, subprocess; f=serve.redirect_output(sys.argv[1]); "
      "print('from print'); sys.stderr.write('from stderr\\n'); "
      "subprocess.run([sys.executable,'-c','print(\"from child\")'])")
r=subprocess.run([sys.executable,"-c",code,logf],capture_output=True,text=True,encoding="utf-8")
log=open(logf,encoding="utf-8").read()
ok("from print" in log and "from stderr" in log and r.stdout=="" , (log, r.stdout, r.stderr))
if sys.platform!="win32": ok("from child" in log, "child output too")
print("ok")

# upload and file "rel" paths always use "/" (they become download URLs), also when the OS joins with "\\"
import uploads, pathlib as _pl
_rel=_pl.PureWindowsPath("2026-11","abc-memo.txt").relative_to(_pl.PureWindowsPath("."))
ok(_rel.as_posix()=="2026-11/abc-memo.txt", _rel.as_posix())
os.environ.setdefault("DAEMON_UPLOADS", tempfile.mkdtemp())
_r=uploads.process("memo.txt", b"hello")["rel"]
ok("\\" not in _r and "/" in _r, _r)
print("ok")
