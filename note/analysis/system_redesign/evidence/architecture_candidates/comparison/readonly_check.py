import json
import os
from pathlib import Path
import signal
import subprocess

root = Path(__file__).resolve().parent
command = ["g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
           str(root / "readonly_probe.cpp"), "-o", str(root / "readonly_probe")]
subprocess.run(command, check=True)
rows = []
for mode in ("read", "write", "read"):
    result = subprocess.run([str(root / "readonly_probe"), mode], capture_output=True, text=True)
    expected = -signal.SIGSEGV if mode == "write" else 0
    assert result.returncode == expected
    if mode == "read":
        assert result.stdout.strip() == "2016"
    rows.append({"mode": mode, "returncode": result.returncode, "stdout": result.stdout})
(root / "readonly_results.json").write_text(json.dumps({"passed": True, "cases": rows,
    "controller_survived": True, "controller_pid": os.getpid(),
    "limitation": "Standalone mmap arena, not production object ownership or Bank layout acceptance"}, indent=2) + "\n")
print(json.dumps({"passed": True, "read_ok_write_blocked_read_ok": True}))
