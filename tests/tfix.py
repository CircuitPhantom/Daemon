import subprocess as _s; _s.run(["pkill","-f","[s]"+"pamapp"])
import os, sys, time, subprocess
sys.path[:0]=["."]
os.environ["PATH"]=os.path.abspath("fakebin")+":"+os.environ["PATH"]
os.environ["FAKELOG"]="/tmp/fakelog"
import tools as T, agent
def ok(c,m):
    if not c: print("FAIL",m); sys.exit(1)
def timed(f, *a):
    t=time.time(); r=f(*a); return r, time.time()-t
# background program that keeps printing: must return promptly and not be killed
r,dt = timed(T.execute_command, "spamapp &")
print(repr(r), round(dt,2)); ok(dt<1.5, (r,dt))
time.sleep(1.0)
ok(subprocess.run(["pgrep","-f","[s]"+"pamapp"],capture_output=True).stdout.strip()!=b"", "background app still alive")
time.sleep(0.5)   # it keeps writing into our drain thread: no SIGPIPE, still alive
ok(subprocess.run(["pgrep","-f","[s]"+"pamapp"],capture_output=True).stdout.strip()!=b"", "still alive after output kept flowing")
# nohup-style with output
r,dt = timed(T.execute_command, "echo started; spamapp &"); ok(dt<1.5 and "started" in r, (r,dt))
# foreground never-ending program: stopped at timeout with a hint
T.CMD_TIMEOUT=1
r,dt = timed(T.execute_command, "spamapp"); print(repr(r[-120:]), round(dt,2)); ok(1<=dt<2.5 and "open_app" in r and "app log line" in r, (r,dt))
T.CMD_TIMEOUT=20
ok(T.execute_command("echo hi; exit 2")=="hi\n[exit code 2]", "exit code")
ok("x"*10 in T.execute_command("head -c 20000 /dev/zero | tr '\\0' x") and len(T.execute_command("head -c 20000 /dev/zero | tr '\\0' x"))<4300, "clip")
# open_app with a program that spams and never exits
r,dt = timed(T.open_app, "spamapp"); print(r, round(dt,2)); ok(r=="Started spamapp" and dt<1.5, (r,dt))
subprocess.run(["pkill","-f","[s]"+"pamapp"])
# hung tool is abandoned
agent.TOOL_TIMEOUT=1
r,dt = timed(agent.call_tool, lambda: time.sleep(30), {}); ok(r.startswith("Error: the tool did not finish") and dt<2, (r,dt))
ok(agent.call_tool(lambda x: x+1, {"x":1})==2 and agent.call_tool(lambda: 1/0, {}).startswith("Error:"), "call_tool basic")
print("FIX OK")
