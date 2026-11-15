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
