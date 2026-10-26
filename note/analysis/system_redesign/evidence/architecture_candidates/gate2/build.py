"""Build only in this temporary directory; do not install a project dependency."""
import json
from pathlib import Path
import platform
import subprocess
import sys
import sysconfig

ROOT = Path(__file__).resolve().parent
command = ["g++", "-std=c++17", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
           "-pthread", "-shared", "-fPIC", "-fvisibility=hidden",
           "-I" + str(ROOT / "pydeps/pybind11/include"),
           "-I" + sysconfig.get_paths()["include"], str(ROOT / "kernel.cpp"),
           "-o", str(ROOT / ("gate1_kernel" + sysconfig.get_config_var("EXT_SUFFIX")))]
subprocess.run(command, check=True, cwd=ROOT)
environment = {"python": sys.version, "platform": platform.platform(),
               "compiler": subprocess.check_output(["g++", "--version"], text=True),
               "pybind11": "3.1.0", "build_command": command,
               "official_reference": "https://pybind11.readthedocs.io/en/stable/advanced/misc.html#global-interpreter-lock-gil",
               "purpose": "correctness only; not a performance benchmark"}
(ROOT / "environment.json").write_text(json.dumps(environment, indent=2) + "\n")
print(json.dumps({"built": command[-1], "pybind11": "3.1.0"}))
