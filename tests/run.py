#!/usr/bin/env python3
"""Cross-platform test runner (same job as run.sh, which needs bash).
  python tests/run.py              all tests
  python tests/run.py tjobs tllm   only these
Runs the scripts in a scratch copy (they write state files next to themselves). Needs the requirements installed
(speech / LLM parts are stubbed), node for the PWA test and ffmpeg for the audio tests."""
import os, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for tool in ("node", "ffmpeg"):
    if not shutil.which(tool):
        print(f"warning: {tool} not found, some tests will fail")
work = Path(tempfile.mkdtemp(prefix="daemon-tests-"))
try:
    for f in list(ROOT.glob("*.py")) + [ROOT / "index.html"]:
        shutil.copy2(f, work)
    for item in HERE.iterdir():
        if item.name in ("run.sh", "run.py", "__pycache__"):
            continue
        if item.is_dir():
            shutil.copytree(item, work / item.name, dirs_exist_ok=True)
        else:
            shutil.copy2(item, work)
    names = sys.argv[1:] or sorted(p.stem for p in work.glob("t*.py"))
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    passed, failed = 0, []
    for name in names:
        try:
            r = subprocess.run([sys.executable, f"{name}.py"], cwd=work, env=env, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=300)
            rc, out = r.returncode, (r.stdout + r.stderr)
        except subprocess.TimeoutExpired:
            rc, out = 1, "timeout after 300 s"
        if rc == 0:
            passed += 1
            print(f"ok    {name}")
        else:
            failed.append(name)
            print(f"FAIL  {name}: {' '.join(out.strip().splitlines()[-2:])[:160]}")
    print(f"\n{passed} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)
finally:
    shutil.rmtree(work, ignore_errors=True)
