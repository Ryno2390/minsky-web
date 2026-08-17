"""Locate and import pyminsky.

The module is built to the repo root, not RESTService/ as the layout suggests,
and on an installed app it lives in the bundle's Resources directory.

WHY THE EXTENSION IS NOT HARDCODED
----------------------------------
This used to look for `pyminsky.so` literally, which is right on macOS and Linux and wrong
on Windows, where a Python extension module is `.pyd`. It also missed ABI-tagged builds --
`pyminsky.cpython-313-darwin.so`, `pyminsky.abi3.so`, `pyminsky.cp313-win_amd64.pyd` --
which are what most build systems actually emit.

So rather than guess, ask Python: `EXTENSION_SUFFIXES` is the list the interpreter itself
will accept for a native module on this platform. Checking against it means the loader
works wherever the engine will, and fails with a message naming what it looked for rather
than a bare "not found".
"""
import os
import sys
from importlib.machinery import EXTENSION_SUFFIXES

# Order matters. ~/minsky is the durable build and must win: a stale copy under a
# session scratchpad will still satisfy the check long after it stops being the build
# anyone is maintaining, and silently shadow the real one.
CANDIDATES = [
    os.environ.get("MINSKY_HOME"),
    os.path.expanduser("~/minsky"),
    "/Applications/ravel.app/Contents/Resources/build",   # macOS installed bundle
]

#: What a built pyminsky is called here: "pyminsky" plus whatever this interpreter accepts.
#: On macOS/Linux that includes ".so"; on Windows ".pyd".
NAMES = tuple("pyminsky" + suffix for suffix in EXTENSION_SUFFIXES)


def find_minsky(candidates=None):
    """(directory, filename) of the first built pyminsky found, or (None, None)."""
    for c in (candidates if candidates is not None else CANDIDATES):
        if not c:
            continue
        for name in NAMES:
            if os.path.exists(os.path.join(c, name)):
                return c, name
    return None, None


def load_minsky():
    c, _name = find_minsky()
    if c is None:
        looked = " or ".join(NAMES[:3]) + (", ..." if len(NAMES) > 3 else "")
        where = ", ".join(x for x in CANDIDATES if x) or "(nowhere -- no candidates)"
        raise ImportError(
            f"no built pyminsky found. Looked for {looked} in: {where}. "
            f"Set MINSKY_HOME to the directory containing it.")
    if c not in sys.path:
        sys.path.insert(0, c)
    from pyminsky import minsky
    return minsky, c
