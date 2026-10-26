import json
from pathlib import Path
import platform
import subprocess
import sys
import sysconfig

root = Path(__file__).resolve().parent
command = ["g++", "-std=c++17", "-O2", "-g", "-Wall", "-Wextra", "-Werror", "-pthread",
           "-shared", "-fPIC", "-fvisibility=hidden", "-I" + str(root / "pydeps/pybind11/include"),
           "-I" + sysconfig.get_paths()["include"], str(root / "perf_kernel.cpp"),
           "-o", str(root / ("perf_kernel" + sysconfig.get_config_var("EXT_SUFFIX")))]
subprocess.run(command, check=True)
(root / "perf_environment.json").write_text(json.dumps({"python": sys.version,
    "platform": platform.platform(), "compiler": subprocess.check_output(["g++", "--version"], text=True),
    "pybind11": "3.1.0", "command": command, "assertions_enabled": sys.flags.optimize == 0}, indent=2) + "\n")
print("built", command[-1])
