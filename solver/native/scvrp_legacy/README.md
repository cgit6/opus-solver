# SCVRP legacy compatibility kernel

The files under `common/` and `metaheuristic/` are preserved from
`note/study/SCRP.rar` without source edits. Their SHA-256 values are recorded
below so observable legacy behaviour cannot be silently cleaned up or changed.

| File | SHA-256 |
| --- | --- |
| `common/dependences.cpp` | `ad7fde1a75ad1b51cb1d6b32cf7d562a38bdf88b492e7e98a5ba57dcba3d5194` |
| `common/dependences.h` | `142de5061173deb217c6c57ee5697c31018baaa479a7a4743f10a0cba274d453` |
| `common/io_tools.cpp` | `b390cd3df3f0cf6dbab408fa976b415fae5fea01db159fa4d2b539392bd2aae5` |
| `common/io_tools.h` | `ef650bd8d68514e3baf05d66fe464d80ec60abc5cd3ebb721ffb7ff8d28f083a` |
| `common/local_search.cpp` | `c4240d1877fdc08d314cec8dcc9557dd1b2f9f561f1a6587fc5e9cb436ede6bb` |
| `common/local_search.h` | `ec4ece6a59fd136a184cc42056437d3e4201e5289edd2bfb05d4f552fd151952` |
| `metaheuristic/differential_evolution.cpp` | `7d244e97675779a17a5f2405d6665de6016a65b65cbd2cf059951f63960dbf1a` |
| `metaheuristic/differential_evolution.h` | `de5853644fa476453248dc5104d364ac64ad0d6a02266533d4d17606a01595f1` |

`runner.cpp` replaces only the unsafe ten-run/output wrapper. It executes one
seed in a separate process, preserves `DE/rand/1/exp`, the temperature schedule,
and the legacy stopping rule, and emits deterministic JSON. `compat_rng.*`
provides the MSVC/UCRT 15-bit `rand()` sequence used by the archived x64 v142
binary.

The wrapper also requires an explicit transition safety limit. The verified
legacy profile sets it far above the archived stopping point; reaching it is a
distinct error/stop cause rather than being reported as legacy stagnation.

The native process is intentionally isolated from Python because the preserved
legacy sources contain allocator and bounds defects. Logical defects that affect
the optimization result are retained until the legacy profile has passed its
full oracle suite.

The Python adapter compiles this runner into a content-addressed temporary cache
on first use. A C++14-capable `g++` must therefore be available at runtime; a
missing compiler is reported before the timed optimization run begins.
