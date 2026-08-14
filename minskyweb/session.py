"""Locate and import pyminsky.

The module is built to the repo root, not RESTService/ as the layout suggests,
and on an installed app it lives in the bundle's Resources directory.
"""
import os, sys

# Order matters. ~/minsky is the durable build and must win: a stale copy under a
# session scratchpad will still satisfy the pyminsky.so check long after it stops
# being the build anyone is maintaining, and silently shadow the real one.
CANDIDATES = [
    os.environ.get("MINSKY_HOME"),
    os.path.expanduser("~/minsky"),
    "/Applications/ravel.app/Contents/Resources/build",
]

def load_minsky():
    for c in CANDIDATES:
        if c and os.path.exists(os.path.join(c, "pyminsky.so")):
            if c not in sys.path:
                sys.path.insert(0, c)
            from pyminsky import minsky
            return minsky, c
    raise ImportError(
        "pyminsky.so not found. Set MINSKY_HOME to the directory containing it.")
