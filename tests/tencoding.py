"""Lint: text files and child-process output must name their encoding, or Windows (cp1254/cp1252) corrupts non-ASCII text."""
import ast, glob, sys
def ok(c,m=""):
    if not c: print("FAIL",m); sys.exit(1)
def kw(call, name): return next((k for k in call.keywords if k.arg==name), None)
def const(n): return n.value if isinstance(n, ast.Constant) else None
bad=[]
for f in sorted(glob.glob("*.py")):
    src=open(f,encoding="utf-8").read()
    if "def ok(c" in src: continue                                       # the test scripts themselves (they run in the same folder)
    tree=ast.parse(src, f)
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call): continue
        fn=n.func; name=fn.attr if isinstance(fn, ast.Attribute) else getattr(fn,"id","")
        owner=getattr(getattr(fn,"value",None),"id","")
        if name=="open" and owner in ("","os","io") or name=="fdopen":
            if owner=="os" and name=="open": continue                      # os.open: file descriptors
            mode=const(n.args[1]) if len(n.args)>1 else const(kw(n,"mode").value) if kw(n,"mode") else "r"
            if mode is None or "b" in mode or kw(n,"encoding"): continue
            bad.append(f"{f}:{n.lineno} open() without encoding")
        elif name in ("read_text","write_text") and not kw(n,"encoding"):
            bad.append(f"{f}:{n.lineno} {name}() without encoding")
        elif owner=="subprocess" and name in ("run","Popen","check_output"):
            t=kw(n,"text") or kw(n,"universal_newlines")
            if t and const(t.value) and not kw(n,"encoding"):
                bad.append(f"{f}:{n.lineno} subprocess text=True without encoding")
ok(not bad, "\n".join(bad))
print("ok")
