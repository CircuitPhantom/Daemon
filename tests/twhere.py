import sys; sys.path[:0]=["stubs","."]
import tools
def ok(c,m=""):
    if not c: print("FAIL",m); sys.exit(1)
calls=[]
tools.remote["call"]=lambda n,a:(calls.append((n,a)) or "from laptop")
tools.remote["names"]=lambda: {"execute_command","open_app"}
f=tools.available_functions["execute_command"]
ok(f(cmnd="echo hi")=="from laptop" and calls[-1][0]=="execute_command", "default -> laptop")
ok("hi" in f(cmnd="echo hi", where="server") and len(calls)==1, "where=server -> server")
tools.remote["names"]=lambda: {"open_app"}
ok("hi" in f(cmnd="echo hi"), "not listed -> server")
ok(tools.available_functions["open_app"](name="zzzznotanapp")=="from laptop", "open_app -> laptop")
print("WHERE OK")
