"""Temporary planning experiment; no repository source or dependency changes."""
import pathlib
import subprocess
import sysconfig
import time

root = pathlib.Path(__file__).parent
flags = ["g++", "-std=c++17", "-O2", "-Wall", "-Wextra", "-pthread",
         "-I" + str(root / "pydeps/pybind11/include"),
         "-I" + sysconfig.get_paths()["include"]]
for mode, extra, output in [
    ("native", [], root / "native_probe"),
    ("binding", ["-DBUILD_BINDING", "-shared", "-fPIC", "-fvisibility=hidden"],
     root / ("invocation_probe" + sysconfig.get_config_var("EXT_SUFFIX"))),
]:
    begin = time.perf_counter()
    subprocess.run(flags + extra + [str(root / "probe.cpp"), "-o", str(output)], check=True)
    print(mode, "build_seconds", time.perf_counter() - begin, "output", output, flush=True)
