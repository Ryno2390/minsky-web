"""HTTP + WebSocket surface over the Minsky engine.

WHY A SERVER AT ALL: `minsky-RESTService` is not one. Despite the name it is a
stdin/stdout line REPL -- no sockets, no HTTP. Everything below is ours.

THE CONSTRAINT THAT SHAPES ALL OF THIS
--------------------------------------
`pyminsky` binds a C++ singleton, so **one process holds exactly one model**. Two
consequences that are not negotiable:

  1. Every engine call is serialised behind `_LOCK`. FastAPI serves requests on a
     thread pool, and two threads inside a stateful C++ singleton corrupts it. The
     engine calls are also *blocking*, so they run via `run_in_threadpool` rather than
     stalling the event loop.

  2. Multiple documents need multiple PROCESSES. This server is deliberately
     single-document: a real multi-user deployment forks a process per session and
     puts a router in front. Pretending otherwise here would build in a bug that only
     shows up under a second user.

SIMULATION STREAMS OVER A WEBSOCKET, and that is a deliberate choice over polling.
Minsky steps at a *variable* dt chosen by the solver -- `step()` returns [t, dt] and dt
moves with stiffness. A polling client cannot know when to ask, and would either miss
steps or spin. Streaming also gives the client a natural stop signal for a run that is
diverging, which matters when the whole point is exploring unstable models.

While a run streams, mutating endpoints return 409. The model must not change under a
simulation that is already stepping it.
"""
from __future__ import annotations

import asyncio
import math
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .headless import Model, WiringError

_LOCK = threading.RLock()
_RUNNING = threading.Event()

# Wire endpoints, as (src_item, src_port, dst_item, dst_port).
#
# WHY WE TRACK THIS OURSELVES: the engine has the geometry but pyminsky cannot marshal
# it. `wire.coords()` returns a 4-element wrapper whose elements all read as None from
# Python, while the SAME call over the JSON registry returns [112,100,286.5,100]. The
# binding's container marshalling is incomplete where the JSON path is complete, and
# `wire.from()/to()` expose no x()/y() either.
#
# Tracking topology is better than reading coordinates anyway: coordinates read once go
# stale the moment an item is dragged, whereas port positions are recomputed live.
_WIRES: list[tuple[int, int, int, int]] = []


def _iter_items(m):
    """Every item, top level and inside groups, as (ref, raw).

    Group members live at `groups[g].items[i]`, NOT in `model.items`, so a model with a
    group renders incomplete unless they are walked -- GoodwinLinear02 shows 18 of its
    26 items otherwise. Their coordinates are ABSOLUTE (verified: group contents sit at
    x 169-331 inside a top-level range of 33-441), so no transform is needed.

    Refs are "3" for a top-level item and "g0:5" for a group member. Group members are
    read-only here: `Item` addresses `model.items[i]`, so moving or deleting one would
    need a different path. Rendering them correctly matters more than editing them.
    """
    for i in range(len(m.model.items)):
        yield str(i), m.model.items[i]
    for gi in range(len(m.model.groups)):
        grp = m.model.groups[gi]
        for i in range(len(grp.items)):
            yield f"g{gi}:{i}", grp.items[i]


def _identity_list(m):
    """A fingerprint of every item in order, for remapping indices after a delete.

    Position is deliberately NOT part of the key: the engine nudges surviving items by a
    few pixels when the canvas is rebuilt, which would break every match.
    """
    out = []
    for ref, it in _iter_items(m):
        try:
            nm = it.name()
        except Exception:
            nm = ""
        out.append((ref, it.classType(), nm, round(it.x(), 1), round(it.y(), 1)))
    return out


def _remap_wires(m, before):
    """Rebuild `_WIRES` refs after a mutation, by matching items rather than counting.

    Item indices are not stable across anything structural:

      * Deleting ONE thing can remove SEVERAL items -- a Godley icon takes every stock
        variable it generated with it, an IntOp takes its variable. Subtracting 1 from
        each higher ref left a wire above the table pointing at the wrong items.
      * Godley tables generate and destroy variables as their headers are typed, and the
        engine regenerates them at the END of model.items. Renaming a stock header moves
        it from index 1 to index 4 and shifts everything in between.

    Neither is reported. In the first case the wire failed to resolve and was silently
    dropped from the canvas; in the second it resolved to two items that had never been
    connected and was drawn between them. The tracked COUNT still matched the engine's
    both times, so `desync` stayed quiet.

    Matching runs in layers, strongest evidence first, because no single property
    survives every mutation: a rename changes the name, a Godley edit changes the index,
    and a regenerated variable changes its position. Each layer only considers items no
    earlier layer has claimed, and both lists stay in order, so equally-good candidates
    pair up the way they are laid out.
    """
    after = _identity_list(m)
    pending, free, remap = list(before), list(after), {}

    def take(same):
        nonlocal pending
        rest = []
        for b in pending:
            hit = next((a for a in free if same(b, a)), None)
            if hit is None:
                rest.append(b)
            else:
                free.remove(hit)
                remap[b[0]] = hit[0]
        pending = rest

    take(lambda b, a: a[0] == b[0] and a[1:3] == b[1:3])   # same slot, same identity
    take(lambda b, a: a[1:3] == b[1:3])                    # same identity, moved slot
    take(lambda b, a: a[0] == b[0] and a[1] == b[1])       # same slot and class: renamed
    take(lambda b, a: a[1] == b[1] and a[3:] == b[3:])     # same class, same place
    take(lambda b, a: a[1] == b[1])                        # same class, in order

    _WIRES[:] = [(remap[a], b, remap[c], d) for a, b, c, d in _WIRES
                 if a in remap and c in remap]


def restructuring(fn):
    """Run a mutation that may add, remove or reorder items, and keep `_WIRES` honest."""
    m = engine().minsky
    before = _identity_list(m)
    try:
        return fn()
    finally:
        _remap_wires(m, before)


def _resolve(m, ref: str):
    if ":" in ref:
        g, i = ref[1:].split(":")
        return m.model.groups[int(g)].items[int(i)]
    return m.model.items[int(ref)]


def _engine_wire_count(m) -> int:
    return len(m.model.wires) + sum(len(m.model.groups[g].wires)
                                    for g in range(len(m.model.groups)))


def _wire_probes(x1, y1, x2, y2):
    """Points to try when hit-testing a wire, ordered so the FIRST hit is the right wire.

    Deletion is geometric: focus a wire by a point on it, then delete what is focused.
    Two things make the obvious approach wrong.

    The engine draws wires as CURVES, so the midpoint of the chord between the ports
    misses 6 of 27 wires on GoodwinLinear02.

    Worse, probing near the SOURCE is ambiguous: an output port fans out to many wires,
    so a hit there can focus a different one -- which deleted the wrong wire and left the
    tracked topology desynced. Probing near the DESTINATION cannot: an input port accepts
    exactly one wire, so whatever is found within a few pixels of it is the target.

    So probe outward from the destination only, then fall back to the chord and a bezier
    for long or oddly routed wires.
    """
    L = math.hypot(x2 - x1, y2 - y1) or 1.0
    ux, uy = (x2 - x1) / L, (y2 - y1) / L
    for d in (4, 6, 8, 11, 14, 18, 23, 28, 35, 45):
        if d < L:
            yield x2 - ux * d, y2 - uy * d
    for k in range(1, 21):                       # chord, from the destination end back
        t = 1 - k / 21
        yield x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
    dx = max(30.0, abs(x2 - x1) * 0.45)
    for k in range(1, 21):
        t = 1 - k / 21; u = 1 - t
        yield (u**3 * x1 + 3*u*u*t * (x1 + dx) + 3*u*t*t * (x2 - dx) + t**3 * x2,
               u**3 * y1 + 3*u*u*t * y1 + 3*u*t*t * y2 + t**3 * y2)


def _port_pos(m, ref, port: int):
    it = _resolve(m, str(ref))
    it.updateBoundingBox()
    return it.portX(port), it.portY(port)


def _topology_from_mky(path: str):
    """Exact wire topology, parsed straight out of the .mky file.

    Models built in the UI record their topology as they are wired. A file opened from
    disk has no record, and the engine cannot supply one -- `wire.coords()` marshals as
    None through pyminsky.

    An earlier version shelled out to the REST binary for wire COORDINATES and matched
    them against port positions. That lost 14 of 83 wires on LoanableFunds, because a
    coordinate match needs a tolerance and ports sit close together. The file carries the
    topology exactly, so parse it instead: no subprocess, no tolerance, no near misses.

    File structure: `<items>` is FLAT and holds every item including group members, each
    with `<id>`, `<type>`, `<x>`, `<y>` and `<ports>` (port IDs in order, index 0 the
    output). `<groups>` references its members by item id. `<Wire>` carries `<from>` and
    `<to>` PORT ids. Items are matched to engine refs by (type, x, y), which is exact --
    the engine reports the same coordinates the file stores.
    """
    import xml.etree.ElementTree as ET
    strip = lambda t: t.split("}")[-1]
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return []

    port_of: dict[str, tuple[str, int]] = {}
    ftype: dict[str, str] = {}     # file item id -> its declared type
    order: list[str] = []          # file item ids, in file order
    group_members: set[str] = set()
    wires_el = None

    def take(el, collect_order):
        d = {strip(c.tag): c for c in el}
        if "id" not in d:
            return
        iid = d["id"].text
        if "ports" in d:
            for k, pe in enumerate(d["ports"]):
                port_of[pe.text] = (iid, k)
        if collect_order and "type" in d:
            order.append(iid)
            ftype[iid] = d["type"].text

    for ch in root:
        tag = strip(ch.tag)
        if tag == "items":
            for it in ch:
                take(it, True)
        elif tag == "groups":
            for g in ch:
                take(g, False)          # the group icon itself is not a model item
                for c in g:
                    if strip(c.tag) == "items":
                        group_members.update(e.text for e in c)
        elif tag == "wires":
            wires_el = ch
    if wires_el is None:
        return []

    # MAP BY ORDER, NOT BY COORDINATES. File and engine list items in the same order
    # (verified 131/131 on EndogenousMoney), but the engine NUDGES positions on load --
    # x moves by up to 22px -- so a coordinate match silently dropped 48 of 131 items
    # and with them 12 wires. The engine also hoists group members to the end, exactly
    # as `_iter_items` yields them, so applying the same reordering aligns the two
    # (verified 26/26 on GoodwinLinear02).
    ordered = ([i for i in order if i not in group_members]
               + [i for i in order if i in group_members])
    live = [(ref, it) for ref, it in _iter_items(engine().minsky)]

    # The file's items align with a PREFIX of the engine's, not necessarily all of it.
    # A Godley table's stock and flow variables are regenerated on load rather than
    # stored, so a model saved with one has fewer items in the file than in the engine
    # (5 vs 8 in the case that found this) and they are appended at the end. Requiring
    # equal lengths made the whole trace bail out and report zero wires.
    if len(ordered) > len(live):
        return []
    for iid, (ref, it) in zip(ordered, live):
        ty = ftype.get(iid)
        if ty is not None and ty != it.classType():
            return []                   # the prefix does not correspond; do not guess
    ref_of = {iid: ref for iid, (ref, _) in zip(ordered, live)}

    topo = []
    for w in wires_el:
        d = {strip(c.tag): c for c in w}
        f, t = d.get("from"), d.get("to")
        if f is None or t is None:
            continue
        a_, b_ = port_of.get(f.text), port_of.get(t.text)
        if not a_ or not b_:
            continue
        ra, rb = ref_of.get(a_[0]), ref_of.get(b_[0])
        if ra is None or rb is None:
            continue
        topo.append((ra, a_[1], rb, b_[1]))
    return topo


#: Directories the picker will list and load from. A load is confined to these because
#: this server listens on localhost with no auth, and any page in the browser can POST to
#: it -- an unconstrained path parameter would turn that into an arbitrary-file read.
#: Uploads land in UPLOAD_DIR, which is therefore also a root.
UPLOAD_DIR = Path(tempfile.gettempdir()) / "minskyweb-uploads"
SAVE_DIR = Path.home() / "minsky-models"

#: Readable roots. Includes the shipped examples.
MODEL_ROOTS = [Path.home() / "minsky" / "examples", SAVE_DIR,
               Path.cwd() / "models", UPLOAD_DIR]

#: WRITABLE roots -- deliberately a smaller set. The shipped examples are read-only:
#: saving into them would quietly modify the Minsky installation, and "Save" is one
#: mis-click away from overwriting a reference model that nothing would restore.
WRITE_ROOTS = [SAVE_DIR, Path.cwd() / "models", UPLOAD_DIR]

#: The file the current model came from, and whether it has been edited since.
_CURRENT: str | None = None
_DIRTY = False

#: Undo history, owned by us rather than by the engine.
#:
#: The engine's own history cannot be driven correctly from outside the Tk client:
#:
#:  * `pushHistory()` early-returns false whenever its `undone` flag is set, so the FIRST
#:    push after any undo or redo silently does nothing. An edit made straight after an
#:    undo therefore got no undo point at all.
#:  * `undo(0)` looks like a getter for the pointer, and returns it, but it restores the
#:    state at the pointer (discarding unpushed edits) AND sets `undone`, poisoning the
#:    next push. There is no way to read the pointer without moving something.
#:  * `Minsky::save()` pushes history behind our back, so a push we made right after
#:    saving returned false and our mirror of the pointer stopped advancing -- the edit
#:    after a Save became permanently un-undoable.
#:  * `pushHistory()` never truncates the redo tail; it appends and jumps the pointer to
#:    the end, leaving the abandoned branch in the middle of the deque for a later undo
#:    to walk back into.
#:
#: Every one of those is invisible from Python: the calls report success. So we keep the
#: history ourselves, as full serialized documents. `save()` round-trips exactly, is
#: byte-deterministic for a given state, and costs ~2ms to write and ~5ms to restore --
#: cheap enough to snapshot on every edit, and it makes undo semantics ours to define.
#:
#: Each entry pairs the document with the wire topology at that instant, because `_WIRES`
#: is the only record of which PORTS each wire joins -- the engine cannot report it, so
#: restoring a document without its topology would leave the canvas drawing wires that no
#: longer exist.
MAX_HISTORY = 60
_HIST: list[tuple[bytes, list]] = []

#: Index into `_HIST` of the entry matching the live model. Invariant: after `_snap()` or
#: `_restore()`, `_HIST[_PTR]` IS the live state.
_PTR = -1

#: Whether the model has been mutated since the last entry was recorded. Serializing on
#: every state read just to answer "can I undo?" would be wasteful, and every mutating
#: endpoint already announces itself through `mark_dirty()`.
_PENDING = False


def history_ptr() -> int:
    return _PTR + 1


def _hist_file() -> Path:
    d = Path(tempfile.gettempdir()) / "minskyweb"
    d.mkdir(parents=True, exist_ok=True)
    return d / "history.mky"


def settle():
    """Bring every item's cached geometry up to date.

    `updateBoundingBox()` is not a read: it REWRITES the item's geometry, and those
    coordinates are part of the saved document. `snapshot()` has to call it to report
    honest port positions, which meant the first history entry after a load was taken in
    a different geometric state from every entry after it -- so the first edit recorded a
    spurious extra undo point, and undoing twice made the diagram visibly jump.
    Normalising here means both sides of every comparison are measured the same way.
    """
    m = engine().minsky
    for _ref, it in _iter_items(m):
        try:
            it.updateBoundingBox()
        except Exception:
            pass


def _serialize() -> bytes:
    settle()
    f = _hist_file()
    engine().minsky.save(str(f))
    return f.read_bytes()


def _restore(entry: tuple[bytes, list]):
    global _PENDING
    doc, wires = entry
    f = _hist_file()
    f.write_bytes(doc)
    engine().minsky.load(str(f))
    _WIRES[:] = list(wires)
    _PENDING = False


def _snap() -> bool:
    """Record the live state as a history entry, if anything has changed since the last.

    "Has anything changed" is answered by `_PENDING`, not by comparing documents. A
    reload does not reproduce the saved bytes exactly for every model -- restore a state
    and re-serialise it and the two can differ -- so a byte comparison decided the model
    had changed when nothing had, appended a duplicate, and the second undo in a row
    stepped back onto the state it had just restored. Every mutating endpoint announces
    itself through `mark_dirty()`, which is an exact signal.
    """
    global _PTR, _PENDING
    if _HIST and not _PENDING:
        return False
    del _HIST[_PTR + 1:]                 # a new state abandons the redo tail
    _HIST.append((_serialize(), list(_WIRES)))
    if len(_HIST) > MAX_HISTORY:
        del _HIST[0]
    _PTR = len(_HIST) - 1
    _PENDING = False
    return True


def checkpoint():
    """Record an undo point for the state as it is NOW, BEFORE a mutation.

    Recording before rather than after keeps the index a mutation just returned valid:
    the client gets an index and uses it in the next call, so nothing may reorder
    `model.items` in between.
    """
    _snap()


def capture_tip():
    """Record the live state so the newest action can be redone.

    Checkpoints happen before mutations, so the state produced by the most recent edit is
    not in the history yet. It has to go in before we step backwards, or the first undo
    would have nothing to come back to.
    """
    _snap()


def rollback():
    """Put the last recorded state back. Returns False if there is nothing to go back to.

    `Minsky::load()` clears the model BEFORE parsing, so a file that fails half way
    through leaves the canvas wiped -- and `_CURRENT` still naming the file that was open
    a moment ago, so the next Save wrote the wreckage over it. Since we keep whole
    documents, the previous one can simply be put back.
    """
    if not (0 <= _PTR < len(_HIST)):
        return False
    _restore(_HIST[_PTR])
    return True


def reset_history():
    """Start a fresh timeline, with the current model as its baseline."""
    global _PTR
    disable_engine_history()
    _HIST.clear()
    _PTR = -1
    _snap()


def reset_history_sync():
    reset_history()


def can_undo() -> bool:
    return _PTR > 0 or (_PENDING and _PTR >= 0)


def can_redo() -> bool:
    return not _PENDING and _PTR < len(_HIST) - 1


def mark_dirty(v: bool = True, pending: bool = True):
    """Note that the model changed.

    `_DIRTY` is about the FILE -- is there anything unsaved. `_PENDING` is about the
    HISTORY -- is the live state ahead of the newest recorded entry. They move together
    for an edit, but not otherwise: saving clears the first and must leave the second
    alone, and undo/redo dirties the file while leaving the history exactly in step
    (pass pending=False there, or the restored state looks un-redoable).
    """
    global _DIRTY, _PENDING
    _DIRTY = v
    if v and pending:
        _PENDING = True


def _roots() -> list[Path]:
    return [r for r in MODEL_ROOTS if r.is_dir()]


def _resolved(p: Path) -> Path:
    """Resolve symlinks in a path that need not exist yet.

    `Path.resolve()` handles a missing leaf fine but we want the deepest EXISTING
    ancestor resolved even when several trailing components are missing, so containment
    is judged on real locations rather than on the names someone typed.
    """
    p = Path(os.path.normpath(str(p.expanduser())))
    tail = []
    cur = p
    while True:
        try:
            return cur.resolve(strict=True).joinpath(*reversed(tail))
        except OSError:
            if cur.parent == cur:
                return p
            tail.append(cur.name)
            cur = cur.parent


def check_save_path(name: str) -> Path:
    """Resolve a save target, or refuse it.

    A bare name goes to SAVE_DIR. A full path must land inside a WRITABLE root --
    notably NOT ~/minsky/examples, which is readable but must stay pristine.
    """
    if not name.strip():
        raise HTTPException(422, "a name is required")
    raw = Path(name).expanduser()
    if not raw.is_absolute() and (len(raw.parts) > 1 or "\\" in name):
        # taking the basename silently turned "a/b/c" into c.mky and "../escape" into
        # escape.mky -- neutralised, but the user was not told where their file went
        raise HTTPException(
            422, f"{name!r} looks like a path. Give a bare name, which is saved into "
                 f"{SAVE_DIR}, or a full path inside a writable directory.")
    p = raw if raw.is_absolute() else SAVE_DIR / raw.name
    if not p.name:
        # "/" and "//" have no name to give a suffix to, and raised a bare 500
        raise HTTPException(422, f"{name!r} is not a usable file name")
    if p.suffix != ".mky":
        if p.suffix.lower() == ".mky":
            p = p.with_suffix(".mky")       # "x.MKY" -- normalise, or the Open picker
        else:                               # never lists the file that was just saved
            p = p.with_name(p.name + ".mky")   # append; do not eat "my.model"
    # Containment must be decided on RESOLVED paths, both sides. normpath() collapses
    # "..", but it cannot see a symlink: a link inside the save directory pointing
    # anywhere at all passed this check and the write followed it straight out. And
    # comparing an unresolved target against a resolved root failed the other way --
    # a plain Save after an Upload was refused 403 listing the very directory it was
    # refusing, because the upload directory's own path contains a symlink.
    p = _resolved(p)
    for r in WRITE_ROOTS:
        try:
            p.relative_to(_resolved(r))
            p.parent.mkdir(parents=True, exist_ok=True)
            return p
        except ValueError:
            continue
    raise HTTPException(
        403, f"cannot save to {p}. Writable directories: "
             f"{', '.join(str(r) for r in WRITE_ROOTS)}. The shipped examples are "
             f"read-only; use Save As, or Download to keep a copy elsewhere.")


def is_minsky_document(path) -> bool:
    """Is this actually a Minsky model?

    `minsky.load()` accepts any well-formed XML and quietly yields an empty model, so
    opening the wrong file reported success and silently replaced whatever was open with
    nothing. Checked before loading, so a mistake costs nothing.
    """
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(str(path)).getroot()
    except Exception:
        return False
    return root.tag.split("}")[-1] == "Minsky"


def load_complaint(path) -> str | None:
    """Did the engine actually read the file? Returns something to say, or None.

    Checking the root tag before loading catches a foreign document, but not a Minsky
    file that is truncated, or written by a schema this build cannot read. `load()`
    reports success for those too and leaves an EMPTY model -- so opening a damaged file
    silently replaced the open model with nothing, answered 200, and left the damaged
    file's name in the title bar for the next Save to overwrite.

    Nothing in the engine reports this, so compare what the file declares against what
    the engine produced.
    """
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(str(path)).getroot()
    except Exception as ex:
        return f"the XML could not be parsed ({ex})"
    n_items = len(root.findall(".//{*}Item")) + len(root.findall(".//{*}Group"))
    n_wires = len(root.findall(".//{*}Wire"))
    if not (n_items or n_wires):
        return None                      # a genuinely empty model is a legitimate file
    m = engine().minsky
    if len(m.model.items) or len(m.model.groups):
        return None
    return (f"it declares {n_items} items and {n_wires} wires, but the engine read "
            f"none of them")


def check_model_path(path: str) -> Path:
    """Resolve a requested path, or refuse it."""
    p = Path(path).expanduser()
    try:
        p = p.resolve(strict=True)
    except OSError:
        raise HTTPException(404, f"no such file: {path}")
    if p.suffix.lower() != ".mky":
        raise HTTPException(422, "only .mky files can be loaded")
    for r in _roots() + [UPLOAD_DIR]:
        try:
            p.relative_to(r.resolve())
            return p
        except ValueError:
            continue
    raise HTTPException(
        403, f"{p} is outside the model directories. Allowed: "
             f"{', '.join(str(r) for r in _roots())}. Upload the file instead.")


def engine() -> Model:
    return Model.current()


def disable_engine_history():
    """Stop the engine keeping a history we do not use.

    We keep our own (see `_HIST`). Left on, the engine's would still grow on every
    `save()` -- and `Minsky::save()` pushes whether we ask it to or not.
    """
    try:
        engine().minsky.doPushHistory(False)
    except Exception:
        pass    # older builds without the member: harmless, just wasted memory


def locked(fn, *a, **kw):
    with _LOCK:
        return fn(*a, **kw)


async def call(fn, *a, **kw):
    """Run a blocking engine call off the event loop, serialised."""
    return await run_in_threadpool(locked, fn, *a, **kw)


def require_idle():
    if _RUNNING.is_set():
        raise HTTPException(409, "a simulation is streaming; stop it before editing "
                                 "the model")


def jsonable(v):
    """JSON has no inf or NaN, and this engine produces both routinely.

    `tmax` is Infinity by default, and a diverging model -- the case this whole tool
    exists to explore -- fills every variable with inf or NaN. Letting either reach
    json.dumps raises ValueError and kills the response or the stream, which would
    make the server fail precisely when the model is doing the interesting thing.
    """
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    return v


def nonfinite(vals: dict) -> list[str]:
    return [k for k, v in vals.items()
            if isinstance(v, float) and not math.isfinite(v)]


# --------------------------------------------------------------------------- schemas
#: The types `canvas.addVariable` understands. Anything else creates NOTHING and raises
#: nothing -- the call simply returns, and the next line trips over the item that was
#: never made. Probed against the engine, not copied from the docs.
VAR_TYPES = ("flow", "stock", "parameter", "integral", "constant", "tempFlow")

#: Past this the item is on the canvas but unreachable: no amount of scrolling reaches it
#: and no fitView will ever include it without shrinking everything else to nothing.
COORD_LIMIT = 1e6


def check_at(at):
    """Refuse coordinates that would put an item where it can never be seen again."""
    if at is None:
        return None
    for v in at:
        if not math.isfinite(v):
            raise HTTPException(422, "coordinates must be finite numbers")
        if abs(v) > COORD_LIMIT:
            raise HTTPException(
                422, f"coordinate {v:g} is outside the canvas "
                     f"(+/-{COORD_LIMIT:g}); the item would be unreachable")
    return at


class ItemSpec(BaseModel):
    kind: str = Field(description="'variable' | 'parameter' | 'operation' | 'godley'")
    name: str | None = None
    op: str | None = Field(None, description="operation name, e.g. 'multiply'")
    var_type: str = Field("flow", description="flow | stock | parameter | integral")
    value: float | None = None
    at: tuple[float, float] | None = None


class WireSpec(BaseModel):
    src: int
    dst: int
    port: int = 1


class SolverSpec(BaseModel):
    epsRel: float | None = None
    epsAbs: float | None = None
    order: int | None = None
    implicit: bool | None = None
    t0: float | None = None
    tmax: float | None = None


class InitSpec(BaseModel):
    name: str
    value: float


class MoveSpec(BaseModel):
    x: float
    y: float


class CellSpec(BaseModel):
    row: int
    col: int
    value: str


class ClassSpec(BaseModel):
    col: int
    cls: str


class SizeSpec(BaseModel):
    rows: int
    cols: int


class AtSpec(BaseModel):
    at: int


class RenameSpec(BaseModel):
    name: str


class SaveSpec(BaseModel):
    name: str | None = None


# ------------------------------------------------------------------------ read model
def snapshot() -> dict[str, Any]:
    """Everything a client needs to draw the model."""
    m = engine().minsky
    items = []
    for ref, it in _iter_items(m):
        it.updateBoundingBox()          # port coords are stale until this runs
        # Port 0 is the output for operations and variables, whatever their rotation --
        # a mirrored multiply still has its output at port 0, so geometry cannot be used
        # to tell them apart. But some classes have NO output at all: a plot consumes and
        # never produces, and labelling its port 0 "output" offered the canvas a drag
        # source that could never make a wire.
        sink_only = any(k in it.classType() for k in ("Plot", "Godley", "Sheet"))
        ports = [dict(index=p, x=it.portX(p), y=it.portY(p),
                      role="input" if (sink_only or p != 0) else "output")
                 for p in range(it.portsSize())]
        nested = ":" in ref
        entry = dict(index=int(ref) if not nested else None, ref=ref,
                     classType=it.classType(), x=it.x(), y=it.y(), ports=ports,
                     readOnly=nested)
        try:
            entry["name"] = it.name()
        except Exception:
            pass
        if "Godley" in entry["classType"]:
            # a table's name is its TITLE, which lives on the table not the icon --
            # without this a renamed table still read "godley" on the canvas
            try:
                t = (it.table.title() or "").strip()
                if t:
                    entry["name"] = t
            except Exception:
                pass
        items.append(entry)
    groups = []
    for gi in range(len(m.model.groups)):
        grp = m.model.groups[gi]
        try:
            groups.append(dict(index=gi, title=(grp.title() or f"group {gi}"),
                               x=grp.x(), y=grp.y(),
                               displayContents=bool(grp.displayContents()),
                               size=len(grp.items)))
        except Exception:
            pass
    wires = []
    for i, (si, sp, di, dp) in enumerate(_WIRES):   # si/di are refs
        try:
            x1, y1 = _port_pos(m, si, sp)
            x2, y2 = _port_pos(m, di, dp)
            wires.append(dict(index=i, coords=[x1, y1, x2, y2],
                              src=si, src_port=sp, dst=di, dst_port=dp))
        except Exception:
            continue
    n_engine = len(m.model.wires) + sum(len(m.model.groups[g].wires)
                                        for g in range(len(m.model.groups)))
    if len(_WIRES) != n_engine:
        # our record and the engine disagree -- say so rather than draw a wrong picture
        wires.append(dict(index=-1, desync=True,
                          engine=n_engine, tracked=len(_WIRES)))
    vals = {}
    for k in m.variableValues.keys():
        if k.startswith("constant:"):
            continue
        try:
            vals[k] = m.variableValues[k].value()
        except Exception:
            vals[k] = None
    bad = nonfinite(vals)
    return jsonable(dict(
        items=items, groups=groups, wires=wires, values=vals, t=m.t(),
        running=_RUNNING.is_set(), diverged=bad or None,
        currentFile=(Path(_CURRENT).stem if _CURRENT else None),
        currentPath=_CURRENT, dirty=_DIRTY,
        canUndo=can_undo(),
        canRedo=can_redo(),
        solver=dict(epsRel=m.epsRel(), epsAbs=m.epsAbs(), order=m.order(),
                    implicit=m.implicit(), t0=m.t0(), tmax=m.tmax())))


def create_app() -> FastAPI:
    app = FastAPI(title="Minsky headless server", version="0.1")

    @app.on_event("startup")
    async def _boot():
        # baseline the history against whatever the model is at start, so the very first
        # edit already has something to undo back to
        await call(reset_history)

    @app.exception_handler(WiringError)
    async def _wiring(_req, exc: WiringError):
        # The WiringError text is a developer diagnosis -- object reprs, port pixel
        # coordinates, two speculative causes. Useful in a log, meaningless to someone
        # who just dragged a line. Keep the detail server-side, hand back a sentence.
        import logging
        logging.getLogger("minskyweb").warning("wiring failed: %s", exc)
        return JSONResponse(status_code=400, content={
            "detail": "those two ports cannot be connected. Check the wire starts at an "
                      "output and ends at a free input, and that the items do not overlap.",
            "diagnostic": str(exc)})

    @app.get("/api/state")
    async def get_state():
        return await call(snapshot)

    @app.post("/api/clear")
    async def clear():
        global _CURRENT
        require_idle()

        def _clear():
            m = engine()
            m.clear()
            # clearAllMaps leaves t where the last run stopped, so a brand-new empty
            # document reported t=3.04 in the toolbar
            try:
                m.minsky.reset()
            except Exception:
                pass
        await call(_clear)
        _WIRES.clear()
        _CURRENT = None; mark_dirty(False)
        await call(reset_history)
        return await call(snapshot)

    @app.post("/api/item")
    async def add_item(spec: ItemSpec):
        require_idle()
        check_at(spec.at)
        if spec.kind == "variable" and spec.var_type not in VAR_TYPES:
            # addVariable() with a type it does not know creates nothing and raises
            # nothing; the failure only surfaced later, as a bare 500 with no body
            raise HTTPException(
                422, f"unknown variable type {spec.var_type!r}. "
                     f"Use one of: {', '.join(VAR_TYPES)}")
        await call(checkpoint)

        def _add():
            m = engine()
            if spec.kind == "parameter":
                if not spec.name:
                    raise HTTPException(422, "a parameter needs a name")
                if spec.value is None:
                    # said "needs name and value" even when a name was given and only
                    # the value failed to parse, which sent people looking in the wrong
                    # place
                    raise HTTPException(
                        422, "a parameter needs a numeric value")
                return m.parameter(spec.name, spec.value, at=spec.at)
            if spec.kind == "variable":
                if spec.var_type == "constant":
                    # a constant's NAME is its value -- init("3.5") sets both -- so there
                    # is no name to give it, and one passed here was silently dropped,
                    # leaving a nameless item on the canvas
                    if spec.value is None:
                        raise HTTPException(
                            422, "a constant needs a numeric value. Its value IS its "
                                 "name, so 'name' does not apply -- use a parameter if "
                                 "you want a named quantity.")
                    return m.constant(spec.value, at=spec.at)
                if not spec.name:
                    raise HTTPException(422, "a variable needs a name")
                it = m.variable(spec.name, spec.var_type, at=spec.at)
                if spec.value is not None:      # optional initial value, e.g. for a stock
                    m.set_init(spec.name, spec.value)
                return it
            if spec.kind == "operation":
                if not spec.op:
                    raise HTTPException(422, "operation needs 'op'")
                return m.operation(spec.op, at=spec.at)
            if spec.kind == "godley":
                it = m.godley(at=spec.at)
                if spec.name:
                    # a table's name is its TITLE, and it was accepted and dropped --
                    # the caller named a table and got one called "godley"
                    m.rename(it, spec.name)
                return it
            raise HTTPException(422, f"unknown kind {spec.kind!r}")

        try:
            it = await call(_add)
        except HTTPException:
            raise
        except (RuntimeError, ValueError) as ex:
            # The engine explains itself here -- "Variable ':x' already exists with type
            # stock, cannot create with type flow" is exactly what the user needs to see,
            # and it was being thrown away in favour of a bare 500 with no body. A partly
            # created item can also be left behind, so put the model back first.
            await call(rollback)
            raise HTTPException(400, str(ex))
        mark_dirty()
        return {"index": it.index, "kind": it.kind, "state": await call(snapshot)}

    @app.post("/api/wire")
    async def add_wire(spec: WireSpec):
        require_idle()
        await call(checkpoint)

        def _wire():
            m = engine()
            n = len(m.minsky.model.items)
            for label, i in (("src", spec.src), ("dst", spec.dst)):
                if not 0 <= i < n:
                    raise HTTPException(422, f"{label} index {i} out of range (0..{n-1})")
            from .headless import Item
            from .headless import WiringError
            # Do NOT pre-refuse a busy input. Minsky's n-ary operations (add, subtract,
            # multiply, divide, min, max) legitimately take SEVERAL wires into one input
            # and sum them -- a blanket "already connected" check broke that. Attempt the
            # wire, then diagnose the failure: if the engine declined and that input
            # already has one, it is a single-wire input and we can say so plainly
            # instead of leaking the wiring diagnostic, which prints object reprs and
            # pixel coordinates and is written for a log.
            try:
                m.wire(Item(m, spec.src, "?"), Item(m, spec.dst, "?"), spec.port)
            except WiringError:
                if any(w[2] == str(spec.dst) and w[3] == spec.port for w in _WIRES):
                    raise HTTPException(
                        409, "that input already has a wire and accepts only one; "
                             "delete it first")
                raise
            _WIRES.append((str(spec.src), 0, str(spec.dst), spec.port))

        await call(_wire)
        mark_dirty()
        return await call(snapshot)

    @app.post("/api/item/{index}/move")
    async def move_item(index: int, spec: MoveSpec):
        require_idle()
        check_at((spec.x, spec.y))
        await call(checkpoint)

        def _move():
            from .headless import Item
            m = engine()
            n = len(m.minsky.model.items)
            if not 0 <= index < n:
                raise HTTPException(422, f"index {index} out of range (0..{n-1})")
            m.move(Item(m, index, "?"), spec.x, spec.y)
        await call(_move)
        mark_dirty()
        return await call(snapshot)

    @app.post("/api/item/{index}/rename")
    async def rename_item(index: int, spec: RenameSpec):
        require_idle()
        await call(checkpoint)

        def _rename():
            from .headless import Item
            m = engine()
            n = len(m.minsky.model.items)
            if not 0 <= index < n:
                raise HTTPException(422, f"index {index} out of range (0..{n-1})")

            # Renaming a variable onto a name another variable already uses MERGES them.
            # That is legitimate -- it is how one variable comes to appear in two places
            # -- but the two values become one, and this item's own value is the one that
            # goes. It reported plain success, so the number simply vanished.
            want = spec.name.strip()
            twin = None
            for ref, it in _iter_items(m.minsky):
                if ref == str(index) or not it.classType().startswith("Variable:"):
                    continue
                try:
                    if (it.name() or "").strip() == want:
                        twin = it.classType().split(":")[-1]
                        break
                except Exception:
                    continue
            try:
                before = m.minsky.model.items[index].name()
            except Exception:
                before = None

            try:
                got = restructuring(lambda: m.rename(Item(m, index, "?"), spec.name))
            except ValueError as ex:
                raise HTTPException(422, str(ex))
            except RuntimeError as ex:
                # The engine applies a rename and THEN discovers the name is bound to a
                # different variable type -- it reports the clash but keeps the change,
                # leaving a model that can never reset again. Put it back.
                rollback()
                raise HTTPException(400, f"{ex}. The model was left unchanged.")
            return got, twin, before

        got, twin, before = await call(_rename)
        mark_dirty()
        out = dict(name=got, state=await call(snapshot))
        if got.strip() != spec.name.strip():
            out["note"] = (f"Minsky stores that name as {got!r}.")
        if twin:
            out["warning"] = (
                f"{before!r} was merged into the existing {twin} {got!r}. They are one "
                f"variable now and share a single value; the value {before!r} had has "
                f"been discarded. Undo to separate them.")
        return out

    @app.delete("/api/item/{index}")
    async def delete_item(index: int):
        require_idle()
        await call(checkpoint)

        def _del():
            from .headless import Item
            m = engine()
            n = len(m.minsky.model.items)
            if not 0 <= index < n:
                raise HTTPException(422, f"index {index} out of range (0..{n-1})")
            restructuring(lambda: m.delete(Item(m, index, "?")))
        try:
            await call(_del)
        except RuntimeError as ex:
            raise HTTPException(400, str(ex))
        mark_dirty()
        # indices shift after a delete -- the client must re-render from this snapshot
        return await call(snapshot)

    # ---- Godley tables ----------------------------------------------------------
    def _tbl(index: int):
        from .headless import Godley
        m = engine()
        n = len(m.minsky.model.items)
        if not 0 <= index < n:
            raise HTTPException(
                422, f"there is no item {index} in this model — the Godley table may "
                     f"have been deleted or undone")
        try:
            return m.table(index)
        except TypeError as ex:
            raise HTTPException(422, str(ex))

    def _godley_op(index, fn):
        """Run a table mutation, converting its own error vocabulary into 4xx."""
        try:
            return fn(_tbl(index))
        except HTTPException:
            raise
        except (ValueError, IndexError) as ex:
            raise HTTPException(422, str(ex))
        except Exception as ex:
            raise HTTPException(400, str(ex))

    def _godley_write(index, fn):
        """A table mutation that must leave nothing behind if it fails.

        set_cell writes the cell and THEN commits it with `icon.update()`. When the
        commit throws -- a stock header naming a variable that already exists at another
        type is enough -- the API answered 400 as if nothing had happened, while the cell
        was already written and the model could no longer reset. Put it back.
        """
        try:
            return restructuring(lambda: _godley_op(index, fn))
        except HTTPException as ex:
            # 422 is OUR OWN range and shape checking, which runs before the engine is
            # touched, so there is nothing to put back -- and a needless restore would
            # re-impose the engine's canonical column order on a table the user has not
            # finished editing. 400 is the engine failing partway through a change it
            # had already begun.
            if ex.status_code != 422:
                rollback()
                sep = "" if str(ex.detail).rstrip().endswith((".", "!", "?")) else "."
                ex.detail = f"{ex.detail}{sep} The table was left unchanged."
            raise

    def _shared_stocks():
        """Stock names that appear as a header in more than one table, with the initial
        condition each table shows for them.

        Two tables can name the same stock -- that is how one account appears on both
        sides of a transaction -- but there is only ONE variable behind it, so only one
        initial condition. Each table stores and displays its own, and the engine quietly
        uses whichever was written last: a table could show 100 for a stock the model was
        running at 250.
        """
        from collections import defaultdict
        seen = defaultdict(list)
        m = engine().minsky
        for i in range(len(m.model.items)):
            it = m.model.items[i]
            if "Godley" not in it.classType():
                continue
            t = it.table
            ic = next((r for r in range(t.rows()) if t.initialConditionRow(r)), None)
            for c in range(1, t.cols()):
                nm = (t.getCell(0, c) or "").strip()
                if not nm:
                    continue
                val = (t.getCell(ic, c) or "").strip() if ic is not None else ""
                seen[nm].append((i, (t.title() or "").strip() or f"table {i}", val))
        return {nm: v for nm, v in seen.items()
                if len(v) > 1 and len({x[2] for x in v if x[2]}) > 1}

    @app.get("/api/godley/{index}")
    async def godley_get(index: int):
        return await call(lambda: _godley_op(index, lambda t: t.snapshot()))

    @app.post("/api/godley/{index}/cell")
    async def godley_cell(index: int, spec: CellSpec):
        require_idle()
        await call(checkpoint)
        await call(lambda: _godley_write(
            index, lambda t: t.set_cell(spec.row, spec.col, spec.value)))
        mark_dirty()
        out = await call(lambda: _godley_op(index, lambda t: t.snapshot()))
        clashes = await call(_shared_stocks)
        if clashes:
            out["conflicts"] = [
                {"stock": nm,
                 "shown": [{"table": ttl, "value": v} for _i, ttl, v in where],
                 "note": (f"{nm} is one variable in {len(where)} tables, so it has one "
                          f"initial condition. The tables disagree, and the engine uses "
                          f"whichever was written last.")}
                for nm, where in clashes.items()]
        return out

    @app.post("/api/godley/{index}/class")
    async def godley_class(index: int, spec: ClassSpec):
        require_idle()
        await call(checkpoint)
        await call(lambda: _godley_write(index, lambda t: t.set_class(spec.col, spec.cls)))
        mark_dirty()
        return await call(lambda: _godley_op(index, lambda t: t.snapshot()))

    @app.post("/api/godley/{index}/resize")
    async def godley_resize(index: int, spec: SizeSpec):
        require_idle()
        await call(checkpoint)
        await call(lambda: _godley_write(index, lambda t: t.resize(spec.rows, spec.cols)))
        mark_dirty()
        return await call(lambda: _godley_op(index, lambda t: t.snapshot()))

    @app.post("/api/godley/{index}/row/{action}")
    async def godley_row(index: int, action: str, spec: AtSpec):
        require_idle()
        await call(checkpoint)
        if action not in ("insert", "delete"):
            raise HTTPException(422, "action must be insert or delete")
        await call(lambda: _godley_write(index, lambda t:
            t.insert_row(spec.at) if action == "insert" else t.delete_row(spec.at)))
        mark_dirty()
        return await call(lambda: _godley_op(index, lambda t: t.snapshot()))

    @app.post("/api/godley/{index}/col/{action}")
    async def godley_col(index: int, action: str, spec: AtSpec):
        require_idle()
        await call(checkpoint)
        if action not in ("insert", "delete"):
            raise HTTPException(422, "action must be insert or delete")
        await call(lambda: _godley_write(index, lambda t:
            t.insert_col(spec.at) if action == "insert" else t.delete_col(spec.at)))
        mark_dirty()
        return await call(lambda: _godley_op(index, lambda t: t.snapshot()))

    @app.delete("/api/wire/{index}")
    async def delete_wire(index: int):
        require_idle()
        await call(checkpoint)

        def _del():
            if not 0 <= index < len(_WIRES):
                raise HTTPException(422, f"wire {index} out of range (0..{len(_WIRES)-1})")
            mk = engine().minsky
            si, sp, di, dp = _WIRES[index]
            x1, y1 = _port_pos(mk, si, sp)
            x2, y2 = _port_pos(mk, di, dp)
            # The probe starts at the DESTINATION because an input takes one wire, which
            # makes it unambiguous -- unless another wire's destination sits at the same
            # point, which happens when two items overlap. Then the hit test could focus
            # either, and the count check below would still see a clean -1 while the
            # wrong wire went.
            for j, (oi, op_, od, odp) in enumerate(_WIRES):
                if j == index:
                    continue
                try:
                    ox, oy = _port_pos(mk, od, odp)
                except Exception:
                    continue
                if abs(ox - x2) < 6.0 and abs(oy - y2) < 6.0:
                    raise HTTPException(
                        400, "another wire ends at the same point, so the engine cannot "
                             "tell them apart by position. Drag the items apart, or use "
                             "Undo.")
            # count wires INSIDE GROUPS too. Deleting a top-level wire can remove a
            # group's internal wiring as a side effect -- on GoodwinLinear02 the group's
            # 8 wires vanished across 16 deletions -- and counting only top-level wires
            # let that pass silently while the tracked record drifted.
            before = _engine_wire_count(mk)
            # deletion is geometric, like everything else here: focus the wire by a point
            # on it, then delete what is focused
            if not any(mk.canvas.getWireAt(px, py)
                       for px, py in _wire_probes(x1, y1, x2, y2)):
                raise HTTPException(
                    400, "That wire ends inside a collapsed group or on a plot widget, "
                         "where it is not drawn along its own port positions and cannot "
                         "be picked. Press Undo to remove it, or delete one of the items "
                         "it connects.")
            mk.canvas.deleteWire()
            after = _engine_wire_count(mk)
            if after != before - 1:
                # the engine took more than we asked for; undo puts it back
                mk.undo(1)
                raise HTTPException(
                    400, f"deleting that wire would have removed {before - after} wires, "
                         f"not 1 -- it is entangled with a group's internal wiring. "
                         f"Nothing was changed.")
            _WIRES.pop(index)

        await call(_del)
        mark_dirty()
        return await call(snapshot)

    @app.post("/api/init")
    async def set_init(spec: InitSpec):
        require_idle()
        await call(checkpoint)
        await call(lambda: engine().set_init(spec.name, spec.value))
        mark_dirty()
        return await call(snapshot)

    @app.post("/api/solver")
    async def set_solver(spec: SolverSpec):
        require_idle()
        # Distinguish "not sent" from "sent as null". A client that computes
        # parseFloat("abc") sends null, and silently dropping it meant the solver kept its
        # old value while the field on screen showed the new one -- the user believed a
        # tolerance had been applied that never was.
        sent = spec.model_fields_set
        bad = [k for k in sent if getattr(spec, k) is None]
        if bad:
            raise HTTPException(
                422, f"not a number: {', '.join(sorted(bad))}")
        kw = {k: v for k, v in spec.model_dump().items() if v is not None}

        # The engine only dispatches orders 1, 2 and 4 (rungeKutta.cc:91); anything else
        # throws "order N solver not supported" at reset time, long after the value was
        # accepted, stored, reported back to the panel and written into the saved file.
        # Refuse it here, while there is still something to say about it.
        if "order" in kw and kw["order"] not in (1, 2, 4):
            raise HTTPException(422, f"solver order must be 1, 2 or 4, not {kw['order']}")
        for k in ("epsAbs", "epsRel"):
            if k in kw and not kw[k] > 0:
                raise HTTPException(422, f"{k} must be greater than zero")
        for k in ("t0", "tmax"):
            if k in kw and not math.isfinite(kw[k]):
                raise HTTPException(422, f"{k} must be a finite number")
        t0 = kw.get("t0", await call(lambda: engine().minsky.t0()))
        tm = kw.get("tmax")
        if tm is not None and tm <= t0:
            raise HTTPException(422, f"tmax ({tm}) must be later than t0 ({t0})")

        await call(checkpoint)

        def _cfg():
            # configure() merges with SANE_SOLVER, so a partial payload silently reset the
            # fields the caller did not send: posting {"order": 4} put epsRel back to 1e-8
            # and implicit back to true. Apply exactly what was asked for.
            m = engine()
            for k, v in kw.items():
                if k in ("epsRel", "epsAbs", "order", "implicit", "t0", "tmax"):
                    getattr(m.minsky, k)(v)
        await call(_cfg)
        # These are saved with the document, so a change here is a change to the model:
        # leaving dirty false left the Save button greyed out over an unsaved change, and
        # skipping the checkpoint made it the one edit undo could not reach.
        mark_dirty()
        return await call(snapshot)

    @app.post("/api/reset")
    async def reset():
        require_idle()
        try:
            await call(lambda: engine().reset())
        except RuntimeError as ex:
            # a failed reset does NOT reliably stop step(); refuse rather than let the
            # client run a half-initialised model
            raise HTTPException(400, str(ex))
        return await call(snapshot)

    async def _step_history(delta: int, what: str):
        require_idle()

        def _go():
            global _PTR
            capture_tip()                     # the newest edit must be redoable
            target = _PTR - delta
            if not 0 <= target < len(_HIST):
                return False
            _restore(_HIST[target])
            _PTR = target
            return True

        moved = await call(_go)
        if not moved:
            raise HTTPException(409, f"nothing to {what}")
        mark_dirty(pending=False)   # _restore() left the history exactly in step
        return await call(snapshot)

    @app.post("/api/undo")
    async def undo():
        return await _step_history(1, "undo")

    @app.post("/api/redo")
    async def redo():
        return await _step_history(-1, "redo")

    @app.get("/api/files")
    async def list_files():
        out = []
        for r in _roots():
            entries = []
            for f in sorted(x for x in r.iterdir() if x.suffix.lower() == ".mky"):
                try:
                    st = f.stat()
                except OSError:
                    continue
                entries.append(dict(name=f.stem, path=str(f), bytes=st.st_size))
            if entries:
                out.append(dict(dir=str(r), files=entries))
        return dict(roots=out)

    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...)):
        require_idle()
        name = Path(file.filename or "model.mky").name
        if not name.lower().endswith(".mky"):
            raise HTTPException(422, "only .mky files can be uploaded")
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        dest = UPLOAD_DIR / name
        with dest.open("wb") as fh:
            shutil.copyfileobj(file.file, fh)
        global _CURRENT
        if not await call(is_minsky_document, str(dest)):
            raise HTTPException(
                422, f"{name} is not a Minsky model. Nothing was changed.")
        await call(checkpoint)
        try:
            await call(lambda: engine().minsky.load(str(dest)))
        except Exception as ex:
            kept = await call(rollback)
            raise HTTPException(422, f"{name} could not be read: {ex}. " +
                                ("The model you had open was kept." if kept else
                                 "The canvas has been cleared."))
        complaint = await call(load_complaint, str(dest))
        if complaint:
            kept = await call(rollback)
            raise HTTPException(422, f"{name} could not be read: {complaint}. " +
                                ("The model you had open was kept." if kept else
                                 "The canvas has been cleared."))
        _WIRES.clear()
        _WIRES.extend(await call(_topology_from_mky, str(dest)))
        _CURRENT = str(dest); mark_dirty(False)
        await call(reset_history)
        return dict(loaded=str(dest), state=await call(snapshot))

    @app.post("/api/load")
    async def load(path: str):
        global _CURRENT
        require_idle()
        path = str(check_model_path(path))
        if not await call(is_minsky_document, path):
            raise HTTPException(
                422, f"{Path(path).name} is not a Minsky model. Nothing was changed.")
        await call(checkpoint)
        try:
            await call(lambda: engine().minsky.load(path))
        except Exception as ex:
            kept = await call(rollback)
            raise HTTPException(422, f"{Path(path).name} could not be read: {ex}. " +
                                ("The model you had open was kept." if kept else
                                 "The canvas has been cleared."))
        complaint = await call(load_complaint, path)
        if complaint:
            kept = await call(rollback)
            raise HTTPException(422, f"{Path(path).name} could not be read: {complaint}. " +
                                ("The model you had open was kept." if kept else
                                 "The canvas has been cleared."))
        _WIRES.clear()
        _WIRES.extend(await call(_topology_from_mky, path))
        _CURRENT = path; mark_dirty(False)
        await call(reset_history)
        return await call(snapshot)

    @app.post("/api/save")
    async def save(spec: SaveSpec):
        global _CURRENT
        # distinguish "save to the current file" from "save as, with a blank name":
        # a blank name used to fall through and quietly overwrite the current file
        if "name" in spec.model_fields_set and spec.name is not None:
            dest = check_save_path(spec.name)
        elif _CURRENT:
            dest = check_save_path(_CURRENT)     # plain Save, re-validated
        else:
            raise HTTPException(422, "nothing to save to yet -- use Save As")
        await call(lambda: engine().minsky.save(str(dest)))
        _CURRENT = str(dest)
        mark_dirty(False)
        return dict(saved=str(dest), name=dest.stem, dirty=False)

    @app.get("/api/download")
    async def download():
        """Hand the model to the browser so it can be kept anywhere, without giving
        the server a write path outside its own directories."""
        tmp = Path(tempfile.gettempdir()) / "minskyweb-download.mky"
        await call(lambda: engine().minsky.save(str(tmp)))
        stem = Path(_CURRENT).stem if _CURRENT else "model"
        return FileResponse(str(tmp), media_type="application/xml",
                            filename=f"{stem}.mky")

    @app.websocket("/ws/sim")
    async def ws_sim(ws: WebSocket):
        """Stream a run. Client sends {"cmd":"run","steps":N,"tmax":T} then may send
        {"cmd":"stop"}. Server emits one frame per solver step."""
        await ws.accept()
        stop = asyncio.Event()

        async def reader():
            try:
                while True:
                    msg = await ws.receive_json()
                    if msg.get("cmd") == "stop":
                        stop.set()
                        return
            except (WebSocketDisconnect, RuntimeError):
                stop.set()

        try:
            first = await ws.receive_json()
            if first.get("cmd") != "run":
                await ws.send_json({"error": "expected {'cmd':'run'}"})
                return
            steps = int(first.get("steps", 200))
            tmax = first.get("tmax")

            if _RUNNING.is_set():
                await ws.send_json({"error": "a simulation is already streaming"})
                return
            _RUNNING.set()
            task = asyncio.create_task(reader())
            try:
                try:
                    # NO configure() here. It applied SANE_SOLVER on every run, so the
                    # solver the caller had just set was thrown away and the run used the
                    # defaults -- the solver panel had no effect unless its values
                    # happened to match. Sane defaults belong to a NEW model, not to
                    # every run, and a loaded file's own solver block must be respected.
                    await call(lambda: engine().reset())
                except RuntimeError as ex:
                    await ws.send_json({"error": str(ex)})
                    return
                if tmax is not None:
                    # tmax is part of the saved document, not a transient run argument,
                    # so a run edits the model. Announce it, or Save silently persists a
                    # horizon the user never chose to store.
                    await call(checkpoint)
                    await call(lambda: engine().minsky.tmax(float(tmax)))
                    mark_dirty()

                names = await call(
                    lambda: [k for k in engine().minsky.variableValues.keys()
                             if not k.startswith("constant:")])
                for i in range(steps):
                    if stop.is_set():
                        await ws.send_json({"stopped": True, "step": i})
                        break

                    def _one():
                        m = engine().minsky
                        m.step()
                        return m.t(), {k: m.variableValues[k].value() for k in names}

                    try:
                        t, vals = await call(_one)
                    except Exception as ex:
                        await ws.send_json({"error": f"step {i} failed: {ex}"})
                        break
                    bad = nonfinite(vals)
                    await ws.send_json(jsonable(
                        {"step": i, "t": t, "values": vals, "diverged": bad or None}))
                    if bad:
                        # keep going past this and every later frame is noise
                        await ws.send_json({"done": True, "reason": "diverged",
                                            "variables": bad})
                        break
                    if tmax is not None and t >= float(tmax):
                        await ws.send_json({"done": True, "reason": "tmax", "t": t})
                        break
                else:
                    await ws.send_json({"done": True, "reason": "steps"})
            finally:
                _RUNNING.clear()
                task.cancel()
        except WebSocketDisconnect:
            _RUNNING.clear()

    ui = Path(__file__).parent / "ui"
    if ui.is_dir():
        app.mount("/", StaticFiles(directory=str(ui), html=True), name="ui")

    return app


app = create_app()


def serve(host="127.0.0.1", port=8765):
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    serve()
