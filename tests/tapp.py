import os, sys, tempfile
sys.path[:0]=["."]
d = tempfile.mkdtemp(); apps = d+"/share/applications"; os.makedirs(apps)
open(apps+"/org.gimp.GIMP.desktop","w").write("[Desktop Entry]\nName=GNU Image Manipulation Program\nExec=gimp-real %U\nType=Application\n")
open(apps+"/gimp-hidden.desktop","w").write("[Desktop Entry]\nName=GIMP Hidden\nExec=gimp-real\nNoDisplay=true\n")
open(apps+"/org.kde.okular.desktop","w").write("[Desktop Entry]\nName=Okular\nExec=gimp-real --okular %f\n[Desktop Action x]\nName=Other\nExec=bad\n")
open(apps+"/foo-a.desktop","w").write("[Desktop Entry]\nName=Foo Editor\nExec=gimp-real foo-a\n")
open(apps+"/foo-b.desktop","w").write("[Desktop Entry]\nName=Foo Viewer\nExec=gimp-real foo-b\n")
os.environ.update(PATH=os.path.abspath("fakebin")+":"+os.environ["PATH"], FAKELOG=d+"/log", XDG_DATA_HOME=d+"/share", XDG_DATA_DIRS=d+"/none")
import tools as T, time
def ok(c,m):
    if not c: print("FAIL",m); sys.exit(1)
log=lambda: open(d+"/log").read()
ok(T.open_app("spotify")=="Started spotify (as spotify-launcher)" and "spotify-launcher" in log(), T.open_app("spotify"))   # -launcher fallback, no config needed
T.hooks["app_aliases"] = lambda: {"Browser": "spotify-launcher --skip-update", "codium": "vscodium-bin"}
r = T.open_app("browser"); time.sleep(0.1); ok(r=="Started browser (as spotify-launcher)" and "spotify-launcher --skip-update" in log(), (r, log()))
ok(T.open_app("codium")=="Started codium (as vscodium-bin)" and "codium" in log(), "alias")
ok(T.open_app("Okular")=="Started Okular (as gimp-real)" and "gimp-real --okular" in log(), (T.open_app("Okular"), log()))
r = T.open_app("gimp"); ok(r=="Started gimp (as gimp-real)", r)   # contains-match on GNU ... / org.gimp.GIMP, hidden entry ignored
r = T.open_app("foo"); print(r); ok(r.startswith("Error") and "Foo Editor" in r and "Foo Viewer" in r, r)   # ambiguous -> candidates, nothing started
r = T.open_app("spotfy"); print(r); ok(r.startswith("Error") and "not found" in r and "app_aliases" in r, r)
ok("without arguments" in T.open_app("rm -rf /; x") and "without arguments" in T.open_app("../x"), "validation")
T.hooks["app_aliases"] = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
ok(T.open_app("spotify").startswith("Started"), "broken hook ignored")
print("APPS OK")
