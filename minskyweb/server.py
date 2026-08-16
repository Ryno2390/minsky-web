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
import atexit
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
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


def _iter_groups(m):
    """Every group at every depth, as (ref, raw, parent_ref).

    A group can contain groups: grouping a selection that includes one nests it. Refs are
    "g0" for a top-level group and "g0.1" for group 1 inside group 0.
    """
    def walk(container, path, parent):
        for gi in range(len(container.groups)):
            grp = container.groups[gi]
            ref = f"g{'.'.join(path + [str(gi)])}"
            yield ref, grp, parent
            yield from walk(grp, path + [str(gi)], ref)
    yield from walk(m.model, [], None)


def _iter_items(m):
    """Every item, at every depth, as (ref, raw).

    Group members live at `groups[g].items[i]`, NOT in `model.items`, so a model with a
    group renders incomplete unless they are walked -- GoodwinLinear02 shows 18 of its
    26 items otherwise. Their coordinates are ABSOLUTE (verified: group contents sit at
    x 169-331 inside a top-level range of 33-441), so no transform is needed.

    Groups NEST, so this recurses. Walking only one level meant the contents of a nested
    group were absent from the canvas entirely, with nothing to say so -- and a nested
    group is one lasso away, since grouping a selection that contains a group puts it
    inside the new one.

    Refs are "3" for a top-level item, "g0:5" for member 5 of group 0, and "g0.1:5" for
    member 5 of group 1 inside group 0.
    """
    for i in range(len(m.model.items)):
        yield str(i), m.model.items[i]
    for gref, grp, _parent in _iter_groups(m):
        for i in range(len(grp.items)):
            yield f"{gref}:{i}", grp.items[i]


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

    def take(same, unique=True):
        """Claim the matches this layer can make.

        With `unique`, a layer may only claim a match it can make UNAMBIGUOUSLY: exactly
        one free candidate fits this item, and no other pending item fits that same
        candidate. Taking the first fit instead meant two items the layer could not tell
        apart -- two unnamed sqrt operations, say -- were paired in list order, and after
        a delete a wire was silently re-attached to the wrong one with the counts still
        matching, so nothing flagged it. Deferring an ambiguous pair leaves it to a later
        layer that also looks at WHERE the items are, which does tell them apart.
        """
        nonlocal pending
        rest = []
        cand = [[a for a in free if same(b, a)] for b in pending]
        for i, b in enumerate(pending):
            fits = [a for a in cand[i] if a in free]
            if not fits:
                rest.append(b)
                continue
            if unique and (len(fits) > 1
                           or sum(1 for j in range(len(pending))
                                  if b is not pending[j] and fits[0] in cand[j]) > 0):
                rest.append(b)             # ambiguous here; a later layer knows more
                continue
            free.remove(fits[0])
            remap[b[0]] = fits[0][0]
        pending = rest

    # Order matters, and POSITION comes before SLOT. A slot is only stable across a
    # rename; a delete shifts every slot above it, so "same slot, same identity" matched
    # a deleted item against the one that had moved down into its place -- two unnamed
    # sqrt operations in different rows, and the wires of the deleted one were re-attached
    # to the survivor. A position is stable across both.
    take(lambda b, a: a[1:] == b[1:])                      # class, name and place: unmoved
    take(lambda b, a: a[1] == b[1] and a[3:] == b[3:])     # class and place: renamed there
    take(lambda b, a: a[1:3] == b[1:3])                    # class and name: moved
    take(lambda b, a: a[0] == b[0] and a[1] == b[1])       # same slot and class
    # last resort: whatever is left is indistinguishable by class, name and position, so
    # any pairing is as good as another. Match in order.
    take(lambda b, a: a[1] == b[1], unique=False)

    _WIRES[:] = [(remap[a], b, remap[c], d) for a, b, c, d in _WIRES
                 if a in remap and c in remap]


def _wire_descriptors(topo):
    """Describe a topology by what its endpoints ARE, resolved against the live model.

    Refs cannot be compared across a load, because loading reorders model.items. A
    description built from class, name and port survives it.
    """
    m = engine().minsky
    out = []
    for si, sp, di, dp in topo:
        def desc(ref):
            try:
                it = _resolve(m, ref)
                try:
                    nm = it.name() or ""
                except Exception:
                    nm = ""
                return (it.classType(), nm)
            except Exception:
                return ("?", "")
        out.append((desc(si), sp, desc(di), dp))
    return sorted(out)


def _derive_topology():
    """Re-derive the wire topology from the document, by writing it and reading it back.

    `_topology_from_mky` aligns the file's items with the engine's by ORDER, and that
    alignment is only true immediately after a LOAD: the engine then lists exactly what
    the file listed, with a Godley table's regenerated variables appended at the end.
    It is NOT true of a model edited in this session -- those regenerated variables sit
    wherever the editing left them, in the middle -- so parsing a file written from a
    live model paired the wrong items and mapped every wire onto the wrong ends.

    Writing and then reading back puts the engine into exactly the state the alignment
    assumes. It costs a load, which is also a reset; every caller here has already
    invalidated any run.
    """
    f = _hist_file()
    settle()
    m = engine().minsky
    m.save(str(f))
    m.load(str(f))
    return _topology_from_mky(str(f))


def resync_wires():
    """Re-derive the wire topology from the document.

    `_WIRES` records which PORTS each wire joins, because the engine cannot report that.
    Most edits leave the wires alone, so remapping the item refs is enough. Grouping does
    not: `splitBoundaryCrossingWires()` replaces every wire crossing the new boundary
    with TWO, joined by a generated variable, so the record stops describing the model
    and the canvas would draw wires that are no longer there.

    Writing the document and reading its topology back is exactly the route a load takes.
    """
    _WIRES[:] = _derive_topology()


def restructuring(fn):
    """Run a mutation that may add, remove or reorder items, and keep `_WIRES` honest."""
    m = engine().minsky
    before = _identity_list(m)
    try:
        return fn()
    finally:
        _remap_wires(m, before)


def _group_at(m, path: str):
    """The group named by a dotted path: "0" is groups[0], "0.1" is its group 1."""
    node = m.model
    for part in path.split("."):
        node = node.groups[int(part)]
    return node


def _resolve(m, ref: str):
    if ":" in ref:
        head, _, i = ref.partition(":")
        return _group_at(m, head[1:]).items[int(i)]
    return m.model.items[int(ref)]


#: str.isdigit() is True for characters int() will not take -- superscripts ("\u00b2"),
#: and other scripts' digits -- so `isdigit()` followed by `int()` is a 500 waiting to
#: happen. And `lstrip("-").isdigit()` accepted "-0" and "--5": the first named an item
#: that does not exist (nothing is ever reffed "-0", so a wire recorded against it was
#: silently dropped at the next remap), the second reached int() and threw.
def _is_index(part: str) -> bool:
    return part.isascii() and part.isdigit()


def check_group_ref(ref: str):
    """Validate a group reference ("g0", or "g0.1" for a group inside a group)."""
    m = engine().minsky
    if not ref.startswith("g") or not ref[1:]:
        raise HTTPException(422, f"{ref!r} is not a group reference")
    node = m.model
    for part in ref[1:].split("."):
        if not _is_index(part):
            raise HTTPException(422, f"{ref!r} is not a group reference")
        n = len(node.groups)
        if not 0 <= int(part) < n:
            raise HTTPException(422, f"there is no group {ref!r} in this model"
                                     + (f"; it has {n} at that level" if n else ""))
        node = node.groups[int(part)]
    return node


def check_ref(ref: str) -> str:
    """Validate an item reference: "3", "g0:5", or "g0.1:5" for a nested group."""
    m = engine().minsky
    if ":" in ref:
        head, _, tail = ref.partition(":")
        if not _is_index(tail):
            raise HTTPException(422, f"{ref!r} is not an item reference")
        grp = check_group_ref(head)
        ni = len(grp.items)
        if not 0 <= int(tail) < ni:
            raise HTTPException(422, f"group {head} has items 0..{ni - 1}, not {tail}")
        return ref
    if not _is_index(ref):
        raise HTTPException(422, f"{ref!r} is not an item reference")
    n = len(m.model.items)
    if not 0 <= int(ref) < n:
        raise HTTPException(422, f"index {ref} out of range (0..{n - 1})")
    return ref


def refuse_in_group(ref: str, what: str):
    """Both of these find their target through the canvas hit test, which searches only
    the model the canvas is pointed at and never descends into a group. Acting anyway
    would focus the GROUP and {what} the whole thing."""
    if ":" in ref:
        title = ""
        try:
            title = (_group_at(engine().minsky,
                               ref.partition(":")[0][1:]).title() or "").strip()
        except Exception:
            pass
        raise HTTPException(
            409, f"this item is inside {('the group ' + repr(title)) if title else 'a group'}"
                 f", and the engine can only {what} something the canvas can focus -- "
                 f"which never reaches inside a group. Ungroup it first; undo puts the "
                 f"group back.")


def _engine_wire_count(m) -> int:
    """Every wire the engine holds, at every depth.

    Groups nest, and this summed one level only -- so once a group held a group, the
    wires inside it were never counted. The engine total then came out BELOW the tracked
    total, and snapshot() reported a permanent desync with a negative difference, which
    the UI showed as "-8 wires could not be traced". Nothing was actually wrong.
    """
    def walk(node):
        return len(node.wires) + sum(walk(node.groups[i])
                                     for i in range(len(node.groups)))
    return walk(m.model)


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

    So probe outward from the destination, then fall back to a bezier approximating the
    drawn curve for long or oddly routed wires.

    There used to be a third fallback that walked the straight CHORD between the ports.
    It is the one that made a stale tracked wire dangerous: when the wire does not exist
    in the engine at all, the sweep crosses the whole diagram and `getWireAt` focuses
    whatever unrelated wire it first meets, which was then deleted and reported as
    success. Measured against every wire in GoodwinLinear02 (27) and LoanableFunds (83),
    deleting each in turn from a fresh load: removing the chord sweep changed nothing --
    the same 2 and 12 were refused with it and without it, and neither ever deleted the
    wrong wire. It bought no accuracy and carried the whole risk.
    """
    L = math.hypot(x2 - x1, y2 - y1) or 1.0
    ux, uy = (x2 - x1) / L, (y2 - y1) / L
    for d in (4, 6, 8, 11, 14, 18, 23, 28, 35, 45):
        if d < L:
            yield x2 - ux * d, y2 - uy * d
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
#: Where a bare name is saved. Overridable, so a test run writes into a directory of its
#: own instead of the user's: the suite was leaving its probe files -- and a `.mky;1`
#: backup for each, since Minsky renames the old file aside on every save -- among real
#: models, where they then showed up in the Open picker.
SAVE_DIR = Path(os.environ.get("MINSKYWEB_SAVE_DIR") or (Path.home() / "minsky-models"))

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

#: (id, document, wire topology). The id is what marks the saved point: `_SAVED_PTR` used
#: to be a raw INDEX into this list, and the list is both truncated from the right when a
#: new edit abandons a redo tail and trimmed from the left at MAX_HISTORY. Either one
#: leaves the index naming a different state, so the unsaved-changes marker went FALSE
#: over a model that differed from the file -- which also disabled Save, silenced the
#: "discard unsaved changes?" confirmations and the leave-the-page warning.
_HIST: list[tuple[int, bytes, list]] = []
_NEXT_ID = 0

#: Index into `_HIST` of the entry matching the live model. Invariant: after `_snap()` or
#: `_restore()`, `_HIST[_PTR]` IS the live state.
_PTR = -1

#: Whether the model has been mutated since the last entry was recorded. Serializing on
#: every state read just to answer "can I undo?" would be wasteful, and every mutating
#: endpoint already announces itself through `mark_dirty()`.
_PENDING = False


def history_ptr() -> int:
    return _PTR + 1


#: A scratch directory private to THIS process.
#:
#: These files were at fixed paths under the system temp directory, shared by every
#: minskyweb process on the machine. Two instances -- a stale server, a second checkout,
#: the test suite running while a server is up -- then wrote to the same file and read
#: each other's models back. Measured: an undo answered 200 having replaced its own
#: document with the OTHER instance's items; a download served the other instance's
#: model; and because `Minsky::save()` renames the existing file out of the way before
#: rewriting it, one process's save deleted the file another was mid-read of, producing a
#: 500 from an ordinary edit -- or, on the restore path, a 500 with the canvas already
#: wiped, since `Minsky::load()` clears before it parses.
_SCRATCH = Path(tempfile.mkdtemp(prefix=f"minskyweb-{os.getpid()}-"))
atexit.register(lambda: shutil.rmtree(_SCRATCH, ignore_errors=True))


def _hist_file() -> Path:
    return _SCRATCH / "history.mky"


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


def _restore(entry: tuple[int, bytes, list]):
    """Put a recorded state back, and re-derive its topology rather than trusting the
    refs recorded with it.

    The refs were recorded against the item order of the LIVE model at the time. Loading
    the document does not reproduce that order -- a Godley table's variables are
    regenerated at the END -- so the stored refs then named different items, and undo
    followed by redo left the canvas drawing wires between two things that had never been
    connected, with the counts still matching so nothing flagged it.
    """
    global _PENDING
    _id, doc, wires = entry
    f = _hist_file()
    f.write_bytes(doc)
    engine().minsky.load(str(f))
    derived = _topology_from_mky(str(f))
    _WIRES[:] = derived if derived else list(wires)
    _PENDING = False


#: The history entry that matches what is on disk, so stepping back onto it can clear the
#: unsaved marker instead of leaving the file looking edited when it is not.
_SAVED_ID: int | None = None


def _snap(force: bool = False) -> bool:
    """Record the live state as a history entry, if anything has changed since the last.

    "Has anything changed" is answered by `_PENDING`, not by comparing documents. A
    reload does not reproduce the saved bytes exactly for every model -- restore a state
    and re-serialise it and the two can differ -- so a byte comparison decided the model
    had changed when nothing had, appended a duplicate, and the second undo in a row
    stepped back onto the state it had just restored. Every mutating endpoint announces
    itself through `mark_dirty()`, which is an exact signal.
    """
    global _PTR, _PENDING
    if _HIST and not _PENDING and not force:
        return False
    global _NEXT_ID
    del _HIST[_PTR + 1:]                 # a new state abandons the redo tail
    _NEXT_ID += 1
    _HIST.append((_NEXT_ID, _serialize(), list(_WIRES)))
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


def reset_history(saved: bool = False):
    """Start a fresh timeline, with the current model as its baseline."""
    global _PTR, _SAVED_ID
    disable_engine_history()
    _HIST.clear()
    _PTR = -1
    _SAVED_ID = None
    _snap()
    if saved:                            # this state is what is on disk
        _SAVED_ID = _HIST[_PTR][0]


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
        except (OSError, ValueError):
            # ValueError, not just OSError: a path with an embedded NUL raises
            # "embedded null character in path" from lstat, which escaped as a bare 500
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
    if "\x00" in name:
        raise HTTPException(422, "a file name cannot contain a null character")
    if len(p.name.encode("utf8")) > 240:
        raise HTTPException(
            422, f"that name is {len(p.name.encode('utf8'))} bytes long; "
                 f"the filesystem will not take more than 255")
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
        except ValueError:
            continue
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
        except (FileExistsError, NotADirectoryError):
            # a component of the path is an existing FILE. The function whose job is to
            # accept or refuse a target was throwing instead, as a bare 500.
            bad = next((a for a in [p.parent, *p.parent.parents]
                        if a.exists() and not a.is_dir()), p.parent)
            raise HTTPException(
                422, f"{bad} is a file, not a directory, so nothing can be saved "
                     f"inside it")
        except OSError as ex:
            raise HTTPException(422, f"cannot use that location: {ex.strerror or ex}")
        return p
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


#: A Godley table inside a GROUP is a state the engine cannot serialise twice.
#:
#: Writing such a model produces a complete, valid-looking .mky. Reading that file back
#: and serialising it again SEGFAULTS -- not an exception, a SIGSEGV that takes the whole
#: process with it: the model, the undo history, and every other browser tab on this
#: server. And because /api/save reads the file back to reconcile Godley column order, an
#: ordinary Save is enough to trigger it. The file it wrote is then permanently
#: unopenable, killing the process again on every attempt.
#:
#: Measured: a table alone is fine, a table with a named stock column is fine, a group is
#: fine -- only "a table with a named stock column, inside a group" is poison. None of
#: the 37 shipped examples contains one, so this is reachable only by grouping.
#:
#: There is nothing to do about the engine from here, so do not let the state exist:
#: refuse the grouping that creates it, and refuse to open a file that already has it.
def _tables_in_groups_live() -> list[str]:
    """Titles of any Godley tables that currently sit inside a group."""
    out = []
    m = engine().minsky
    for gref, grp, _parent in _iter_groups(m):
        for i in range(len(grp.items)):
            it = grp.items[i]
            if "Godley" in it.classType():
                try:
                    t = (it.table.title() or "").strip()
                except Exception:
                    t = ""
                out.append(t or gref)
    return out


def tables_in_groups_on_disk(path) -> list[str]:
    """The same question asked of a FILE, before it is opened."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(str(path)).getroot()
    except Exception:
        return []
    kind = {}
    for holder in root.findall(".//{*}items"):
        for it in holder:
            i = it.findtext("{*}id") or it.findtext("id")
            if i is None:
                for c in it:
                    if c.tag.split("}")[-1] == "id":
                        i = c.text
                        break
            t = None
            for c in it:
                if c.tag.split("}")[-1] == "type":
                    t = c.text
            if i is not None and t:
                kind[i] = t
    bad = []
    for g in root.findall(".//{*}groups/{*}Group"):
        holder = g.find("{*}items")
        if holder is None:
            continue
        for ref in holder:
            if "Godley" in (kind.get((ref.text or "").strip()) or ""):
                bad.append((g.findtext("{*}title") or "").strip() or "a group")
    return bad


def godley_owner(name: str):
    """The Godley table that owns a stock of this name, at any depth, or None.

    A table holds its stocks' initial conditions in its own initial-conditions row and
    rewrites them from there at every reset, so setting one anywhere else is accepted and
    then thrown away. This walked only `model.items`, so the guard evaporated the moment
    the table was inside a group -- and it was skipped altogether by the other writer,
    POST /api/item, which the UI's optional "initial value" field goes through.
    """
    m = engine().minsky
    for ref, it in _iter_items(m):
        if "Godley" not in it.classType():
            continue
        try:
            t = it.table
        except Exception:
            continue
        for c in range(1, t.cols()):
            if (t.getCell(0, c) or "").strip() == name.strip():
                return ref, (t.title() or "").strip(), c
    return None


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
    poison = tables_in_groups_on_disk(path)
    if poison:
        return ("it holds a Godley table inside a group, which this engine cannot read "
                "and re-save without crashing (it exits on a segmentation fault, taking "
                "the model and the undo history with it). Opening it is refused rather "
                "than risked")
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
    if "\x00" in path:
        raise HTTPException(422, "a path cannot contain a null character")
    p = Path(path).expanduser()
    try:
        p = p.resolve(strict=True)
    except (OSError, ValueError):
        # ValueError as well: a path with an embedded null raises out of lstat, and this
        # is the read half of the crash the write half was already taught to refuse
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
    # accepted as strings too, so a group member can be NAMED here and refused with an
    # explanation rather than failing schema validation with nothing useful to say
    src: int | str
    dst: int | str
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


class AnimSpec(BaseModel):
    """Must live at module level. `from __future__ import annotations` makes the
    handler's annotation a STRING, which FastAPI resolves in the module namespace -- a
    class nested inside create_app() is invisible there, so the body model was silently
    treated as a query parameter and every request 422'd for a missing field."""
    format: str = "mp4"
    steps: int = 400          # solver steps to run in total
    every: int = 4            # render one frame every N steps
    fps: int = 25
    width: int = 960
    height: int = 640


class AttrSpec(BaseModel):
    """Everything on the variable dialog that is not the name or the value.

    All optional: a client sends only what it is changing, so setting the rotation does
    not have to restate the units and risk clobbering them.
    """
    units: str | None = None
    sliderMin: float | None = None
    sliderMax: float | None = None
    sliderStep: float | None = None
    rotation: float | None = None


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


class LassoSpec(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class RefsSpec(BaseModel):
    refs: list[str]


class NudgeSpec(BaseModel):
    refs: list[str]
    dx: float
    dy: float


class RenameSpec(BaseModel):
    name: str


class SaveSpec(BaseModel):
    name: str | None = None


# ------------------------------------------------------------------------ read model
def live_value_ids() -> set[str]:
    """The value ids that some item on the canvas actually refers to.

    `variableValues` keeps an entry after the last icon referring to it is gone, until the
    next reset, so reading it directly reports variables the model does not have.
    """
    out = set()
    m = engine().minsky
    for _ref, it in _iter_items(m):
        try:
            vid = it.valueId()
        except Exception:
            continue
        if vid and not vid.startswith("constant:"):
            out.add(vid)
    return out


# ------------------------------------------------------------------------ auto-layout

#: A probe offset no item can land on by coincidence, and small enough that the whole
#: model stays inside COORD_LIMIT while it is displaced.
_PROBE = (9973.0, 7919.0)


def _all_positions(m):
    """Every item AND group, by ref, as (x, y)."""
    pos = {ref: (it.x(), it.y()) for ref, it in _iter_items(m)}
    for gref, grp, _parent in _iter_groups(m):
        pos[gref] = (grp.x(), grp.y())
    return pos


def _move_ref(m, ref: str, x: float, y: float):
    """moveTo for an item ref, a group-member ref, or a group ref."""
    if ref.startswith("g") and ":" not in ref:
        _group_at(m, ref[1:]).moveTo(x, y)
    else:
        _resolve(m, ref).moveTo(x, y)


def settle_twice():
    """Settle until the geometry stops changing.

    One pass is not enough, and that is measured rather than assumed: moving a Godley
    table in LoanableFunds changed nothing on the first `settle()` and moved 16 of the
    table's variables on the SECOND. A layout that settled once read the old positions
    back and concluded its own moves had failed.
    """
    settle()
    settle()


def _carriers(m):
    """Which refs travel when another is moved: {anchor ref: [carried refs]}.

    Measured by moving each candidate and watching, because the engine is the only thing
    that knows and it will not say otherwise:

      * An IntOp carries its integral variable -- they are drawn as one glyph.
      * A Godley table carries the stock and flow variables it generates.
      * A group carries its members.

    Guessing this from the document does not work. The obvious rule for a table -- the
    variable's name appears in the table's cells and its icon is drawn on the table's box
    -- finds 13 of the 43 that the engine actually carries, because column 0 holds a
    human-readable row DESCRIPTION ("Hire workers (C)") and not the flow variable's name
    ("C_W"). Position alone is no better: it over-selects by 10 on one LoanableFunds
    table, whose box happens to sit under icons it does not own.

    The probe restores what it moved and verifies the restoration; a model left displaced
    would be far worse than a diagram left untidy.
    """
    dx, dy = _PROBE
    anchors = [ref for ref, it in _iter_items(m)
               if any(k in it.classType() for k in ("Godley", "IntOp"))]
    # Groups are deliberately NOT probed. A group does carry its members, but that is
    # containment, not one glyph, and it is already handled by laying each group out as
    # its own scope. Recording it here instead made every member map to the group, which
    # collapsed the interior to a single box and left it exactly as messy as it was.

    carried: dict[str, list[str]] = {}
    for ref in anchors:
        before = _all_positions(m)
        if ref not in before:
            continue
        ax, ay = before[ref]
        try:
            _move_ref(m, ref, ax + dx, ay + dy)
        except Exception:
            continue
        settle_twice()
        after = _all_positions(m)
        carried[ref] = [
            r for r in before
            if r != ref and r in after
            and abs(after[r][0] - before[r][0] - dx) < 0.5
            and abs(after[r][1] - before[r][1] - dy) < 0.5
        ]
        try:
            _move_ref(m, ref, ax, ay)
        except Exception:
            pass
        settle_twice()
        back = _all_positions(m)
        stray = [r for r in before if r in back
                 and (abs(back[r][0] - before[r][0]) > 0.5
                      or abs(back[r][1] - before[r][1]) > 0.5)]
        if stray:
            raise HTTPException(
                500, f"could not put the model back after measuring {ref}: "
                     f"{len(stray)} item(s) stayed moved. Nothing was rearranged.")
    return carried


def _scope_of(ref: str) -> str | None:
    """Which container a ref sits directly in: None for the top level, else a group ref.

    "3" -> None, "g0:5" -> "g0", "g0.1:5" -> "g0.1". A group ref names a thing that lives
    in ITS parent's scope, so "g0.1" is in scope "g0" and "g0" is in the top level.
    """
    if ":" in ref:
        return ref.partition(":")[0]
    if ref.startswith("g"):
        head = ref[1:]
        return f"g{head.rpartition('.')[0]}" if "." in head else None
    return None


def _plan_scope(m, scope, owner):
    """Lay out one container. Returns (moves, report) for the things directly inside it.

    Called for each group before the top level, so that by the time the outer canvas is
    arranged each group's box is already the size of its tidied contents.
    """
    from .layout import arrange

    def node_of(ref: str) -> str:
        """The layout box a ref belongs to, within this scope."""
        while ref in owner:
            ref = owner[ref]
        while _scope_of(ref) != scope:
            nxt = _scope_of(ref)
            if nxt is None:
                return ref
            ref = nxt
        return ref

    boxes: dict[str, list[float]] = {}
    kinds: dict[str, str] = {}

    def note(key, l, t, r, b, cls=None):
        box = boxes.get(key)
        if box:
            box[0] = min(box[0], l); box[1] = min(box[1], t)
            box[2] = max(box[2], r); box[3] = max(box[3], b)
        else:
            boxes[key] = [l, t, r, b]
        if cls:
            kinds[key] = cls

    members = set()
    for ref, it in _iter_items(m):
        key = node_of(ref)
        if _scope_of(key) != scope:
            continue
        members.add(key)
        note(key, it.left(), it.top(), it.right(), it.bottom(),
             it.classType() if key == ref else None)
    for gref, grp, _parent in _iter_groups(m):
        if _scope_of(gref) != scope:
            continue
        members.add(gref)
        note(gref, grp.left(), grp.top(), grp.right(), grp.bottom(), "Group")

    if len(members) < 2:
        return [], dict(boxes=len(members), layers=0, reversed=0, loose=0)

    sizes = {k: (v[2] - v[0], v[3] - v[1]) for k, v in boxes.items()}
    edges = []
    for si, _sp, di, _dp in _WIRES:
        a, b = node_of(si), node_of(di)
        if a in sizes and b in sizes:
            edges.append((a, b))

    integrals = {k for k, c in kinds.items() if "IntOp" in c}
    placed, report = arrange(sizes, edges, integrals)

    # A group's contents keep their absolute coordinates, so the tidied block is put back
    # where the group already was rather than at the canvas origin.
    ox = oy = 0.0
    if scope is not None:
        ox = min(v[0] for v in boxes.values())
        oy = min(v[1] for v in boxes.values())
        ox -= min((x for x, _y in placed.values()), default=0.0)
        oy -= min((y for _x, y in placed.values()), default=0.0)

    moves = []
    for key, (nx, ny) in placed.items():
        dx, dy = nx + ox - boxes[key][0], ny + oy - boxes[key][1]
        if abs(dx) > 0.01 or abs(dy) > 0.01:
            moves.append((key, dx, dy))
    return moves, report


def _apply_moves(m, moves):
    """Move anchors by an offset and report how many actually travelled."""
    for _key, dx, dy in moves:
        check_at((dx, dy))
    before = _all_positions(m)
    for key, dx, dy in moves:
        if key not in before:
            continue
        x, y = before[key]
        try:
            _move_ref(m, key, x + dx, y + dy)
        except Exception:
            pass
    settle_twice()
    # Judge by the offset achieved, the way a drag does: an anchor can be nudged off the
    # exact point it was sent to and still have travelled correctly.
    after = _all_positions(m)
    placed, refused = 0, []
    for key, dx, dy in moves:
        if key not in before or key not in after:
            continue
        if (abs(after[key][0] - before[key][0] - dx) < 1.0
                and abs(after[key][1] - before[key][1] - dy) < 1.0):
            placed += 1
        else:
            refused.append(key)
    return placed, refused


def _layout_plan(m):
    """Arrange every container, innermost first. Returns (moved, report, refused).

    Group interiors are laid out before the canvas that holds them, so the outer pass
    sees each group at the size of its tidied contents rather than its old one.
    """
    settle_twice()
    carried = _carriers(m)
    settle_twice()
    owner = {r: anchor for anchor, rs in carried.items() for r in rs}

    # A Godley table inside a group crashes the engine on save, so a group holding one is
    # left exactly as it is -- tidying it would only make the damage prettier.
    unsafe = set()
    for gref, grp, _parent in _iter_groups(m):
        for i in range(len(grp.items)):
            if "Godley" in grp.items[i].classType():
                unsafe.add(gref)
                break

    scopes = [g for g, _grp, _p in _iter_groups(m) if g not in unsafe]
    scopes.sort(key=lambda g: -g.count("."))     # deepest first
    scopes.append(None)                          # the top level, last

    total, refused = 0, []
    report = dict(layers=0, reversed=0, loose=0, groups=0)
    for scope in scopes:
        moves, rep = _plan_scope(m, scope, owner)
        if not moves:
            continue
        n, bad = _apply_moves(m, moves)
        total += n
        refused += bad
        if scope is None:
            report.update(layers=rep.get("layers", 0),
                          reversed=rep.get("reversed", 0),
                          loose=rep.get("loose", 0))
        else:
            report["groups"] += 1
            try:
                _group_at(m, scope[1:]).resizeOnContents()
            except Exception:
                pass
            settle_twice()

    report["carried"] = sum(len(v) for v in carried.values())
    report["skipped"] = len(unsafe)
    return total, report, refused


def snapshot() -> dict[str, Any]:
    """Everything a client needs to draw the model."""
    m = engine().minsky
    items = []
    live_ids: set[str] = set()
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
                     readOnly=nested,
                     # More precisely than "readOnly": a group member CAN be moved and
                     # renamed -- moveTo works on the raw item, and a rename now finds
                     # every icon of the variable by valueId rather than by asking the
                     # canvas what is at a point. Delete and wiring cannot: both find
                     # their target through the canvas hit test, which searches only the
                     # model the canvas is pointed at and never descends into a group.
                     inGroup=(ref.partition(":")[0] if nested else None),
                     can=dict(move=True, rename=True,
                              delete=not nested, wire=not nested))
        try:
            entry["name"] = it.name()
        except Exception:
            pass
        try:
            entry["rotation"] = it.rotation()
        except Exception:
            pass
        if entry["classType"] == "UserFunction":
            for attr in ("expression", "description", "name"):
                try:
                    entry[attr if attr != "name" else "fname"] = getattr(it, attr)()
                except Exception:
                    pass
            try:
                entry["args"] = list(it.argNames())
            except Exception:
                pass
        if entry["classType"].startswith("Variable") or entry["classType"] == "VarConstant":
            # Units and slider bounds belong to the VARIABLE, so every icon of it reports
            # the same thing; rotation belongs to the ICON. The UI has to say which is
            # which, or changing one icon's units looks like a bug when the others follow.
            try:
                entry["units"] = it.unitsStr()
            except Exception:
                pass
            try:
                entry["slider"] = dict(min=it.sliderMin(), max=it.sliderMax(),
                                       step=it.sliderStep(), visible=bool(it.sliderVisible()))
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
        try:
            vid = it.valueId()
            if vid:
                live_ids.add(vid)
                # Report the key `values` and `inits` are ACTUALLY stored under. It is
                # not ":name": Minsky mangles the name into the id, so `\tau_L` is held
                # at `:τ<sub>L</sub>` and `B_C` at `:B<sub>C</sub>`. A client that
                # rebuilt the key from the name therefore found nothing for any variable
                # with a subscript or a Greek letter -- 17 of 17 parameters in
                # EndogenousMoney -- and showed an empty value box for a variable that
                # has a perfectly good value.
                entry["valueId"] = vid
        except Exception:
            if entry.get("name"):
                live_ids.add(":" + entry["name"])
        items.append(entry)
    groups = []
    for gref, grp, parent in _iter_groups(m):
        try:
            groups.append(dict(ref=gref, parent=parent,
                               index=(int(gref[1:]) if "." not in gref else None),
                               title=(grp.title() or f"group {gref[1:]}"),
                               x=grp.x(), y=grp.y(),
                               displayContents=bool(grp.displayContents()),
                               size=len(grp.items), groups=len(grp.groups)))
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
    # What each plot on the canvas actually draws.
    #
    # A PlotWidget's ports are not interchangeable. From plotWidget.cc: ports 0..5 are
    # AXIS BOUNDS (xmin/xmax, ymin/ymax, y1min/y1max), then 2*numLines y-data ports --
    # the first numLines on the left axis and the next on the right -- then 2*numLines
    # x-data ports. numLines is therefore (ports - 6) / 4.
    #
    # Getting this wrong is not subtle: the bounds ports carry constants, so treating
    # every wire as a series plots the axis limits as data. And a wired x port means the
    # plot is a PHASE PORTRAIT, not a time series -- MinskyNonLinear draws lambda against
    # w_s that way.
    by_ref = {e["ref"]: e for e in items}
    N_BOUNDS = 6
    for e in items:
        if "Plot" not in e["classType"]:
            continue
        n = max((len(e["ports"]) - N_BOUNDS) // 4, 0)
        left, right, xs = [], [], {}
        for si, _sp, di, dp in _WIRES:
            if di != e["ref"] or dp < N_BOUNDS or not n:
                continue
            src = by_ref.get(si)
            if not src:
                continue
            who = dict(ref=si, name=src.get("name"), valueId=src.get("valueId"))
            k = dp - N_BOUNDS
            if k < n:
                who["line"] = k; left.append(who)
            elif k < 2 * n:
                who["line"] = k - n; right.append(who)
            else:
                xs[(k - 2 * n) % n] = who
        raw = _resolve(m, e["ref"])
        def _lbl(meth):
            try:
                return (getattr(raw, meth)() or "").strip()
            except Exception:
                return ""
        e["plot"] = dict(lines=n, left=left, right=right,
                         x=[dict(line=k, **v) for k, v in sorted(xs.items())],
                         # a modeller titles these; "plot 122" is our name, not theirs
                         title=_lbl("title"), xlabel=_lbl("xlabel"),
                         ylabel=_lbl("ylabel"), y1label=_lbl("y1label"))

    n_engine = _engine_wire_count(m)
    if len(_WIRES) != n_engine:
        # our record and the engine disagree -- say so rather than draw a wrong picture
        wires.append(dict(index=-1, desync=True,
                          engine=n_engine, tracked=len(_WIRES)))
    # Two different numbers, and conflating them made setting a value look like it had
    # done nothing. `value()` is what the variable holds RIGHT NOW, which only picks up a
    # new initial condition at the next reset -- so a caller who set a parameter to 0.9
    # read 0.4 straight back. `init()` is the initial condition itself, and is true the
    # moment it is written.
    # `variableValues` keeps an entry after the last icon referring to it is gone, until
    # the next reset. Typing a flow name into a Godley cell and then changing it left the
    # abandoned name in the values panel, listed with a value, next to variables that
    # really exist -- a variable the model does not have. Report what is on the canvas.
    vals, inits = {}, {}
    for k in m.variableValues.keys():
        if k.startswith("constant:") or k not in live_ids:
            continue
        try:
            vals[k] = m.variableValues[k].value()
        except Exception:
            vals[k] = None
        try:
            inits[k] = m.variableValues[k].init()
        except Exception:
            inits[k] = None
    bad = nonfinite(vals)
    return jsonable(dict(
        items=items, groups=groups, wires=wires, values=vals, inits=inits, t=m.t(),
        running=_RUNNING.is_set(), diverged=bad or None,
        currentFile=(Path(_CURRENT).stem if _CURRENT else None),
        currentPath=_CURRENT, dirty=_DIRTY, saveDir=str(SAVE_DIR),
        canUndo=can_undo(),
        canRedo=can_redo(),
        solver=dict(epsRel=m.epsRel(), epsAbs=m.epsAbs(), order=m.order(),
                    implicit=m.implicit(), t0=m.t0(), tmax=m.tmax())))


def create_app() -> FastAPI:
    app = FastAPI(title="Minsky", version="0.1")

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
            if spec.kind == "sheet":
                return m.sheet(at=spec.at)
            if spec.kind == "switch":
                return m.switch(at=spec.at)
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
                    # the same ownership rule /api/init applies. Without it, naming an
                    # existing Godley stock here set a value that the table rewrites at
                    # the next reset -- accepted, echoed back, and silently discarded.
                    owner = godley_owner(spec.name)
                    if owner:
                        ref, title, col = owner
                        raise HTTPException(
                            409, f"{spec.name!r} is already a stock of "
                                 f"{('the table ' + repr(title)) if title else 'a Godley table'}"
                                 f", which holds its initial condition in the table's own "
                                 f"initial-conditions row (column {col}). A value set here "
                                 f"is rewritten from the table at the next reset.")
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
            for _label, r in (("src", str(spec.src)), ("dst", str(spec.dst))):
                check_ref(r)
                refuse_in_group(r, "wire")
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
                m.wire(Item(m, int(spec.src), "?"), Item(m, int(spec.dst), "?"),
                       spec.port)
            except WiringError as ex:
                if "second copy" in str(ex):
                    # the engine cloned the target instead of connecting it, so the model
                    # gained an item; put it back and say what happened, rather than let
                    # the generic "those two ports cannot be connected" hide it
                    rollback()
                    raise HTTPException(409, str(ex))
                if any(w[2] == str(spec.dst) and w[3] == spec.port for w in _WIRES):
                    raise HTTPException(
                        409, "that input already has a wire and accepts only one; "
                             "delete it first")
                raise
            _WIRES.append((str(spec.src), 0, str(spec.dst), spec.port))

        await call(_wire)
        mark_dirty()
        return await call(snapshot)

    @app.post("/api/item/{ref}/move")
    async def move_item(ref: str, spec: MoveSpec):
        require_idle()
        check_at((spec.x, spec.y))
        await call(check_ref, ref)
        await call(checkpoint)

        def _move():
            from .headless import Item
            m = engine()
            # moveTo works directly on the raw item, so this reaches a group member too
            try:
                m.move(Item(m, 0, "?", ref=ref), spec.x, spec.y)
            except RuntimeError as ex:
                rollback()
                raise HTTPException(409, str(ex))
        await call(_move)
        mark_dirty()
        return await call(snapshot)

    @app.post("/api/item/{ref}/rename")
    async def rename_item(ref: str, spec: RenameSpec):
        require_idle()
        await call(check_ref, ref)
        await call(checkpoint)

        def _rename():
            from .headless import Item
            m = engine()

            # Renaming a variable onto a name another variable already uses MERGES them.
            # That is legitimate -- it is how one variable comes to appear in two places
            # -- but the two values become one, and this item's own value is the one that
            # goes. It reported plain success, so the number simply vanished.
            want = spec.name.strip()
            twin = None
            for other, it in _iter_items(m.minsky):
                if other == ref or not it.classType().startswith("Variable:"):
                    continue
                try:
                    if (it.name() or "").strip() == want:
                        twin = it.classType().split(":")[-1]
                        break
                except Exception:
                    continue
            try:
                before = _resolve(m.minsky, ref).name()
            except Exception:
                before = None

            try:
                got = restructuring(
                    lambda: m.rename(Item(m, 0, "?", ref=ref), spec.name))
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

    @app.delete("/api/item/{ref}")
    async def delete_item(ref: str):
        require_idle()
        await call(check_ref, ref)
        await call(refuse_in_group, ref, "delete")
        await call(checkpoint)

        def _del():
            from .headless import Item
            m = engine()
            restructuring(lambda: m.delete(Item(m, int(ref), "?", ref=ref)))
        try:
            await call(_del)
        except RuntimeError as ex:
            raise HTTPException(400, str(ex))
        mark_dirty()
        # indices shift after a delete -- the client must re-render from this snapshot
        return await call(snapshot)

    @app.post("/api/item/{ref}/copy")
    async def copy_icon(ref: str):
        """Another icon of the SAME variable, which is what Minsky's copy does.

        Not a duplicate variable: the copy shares the original's valueId, so both show
        one value and renaming either renames both. It is how a model avoids dragging a
        wire across the whole canvas.
        """
        require_idle()
        await call(check_ref, ref)
        await call(checkpoint)

        def _go():
            from .headless import Item
            m = engine()
            raw = _resolve(m.minsky, ref)
            cls = raw.classType()
            if not (cls.startswith("Variable") or cls == "VarConstant"):
                raise HTTPException(
                    422, f"{cls} cannot be copied as another icon. Only a variable can "
                         f"appear more than once in a model.")
            was = raw.valueId()
            it = m.copy_icon(Item(m, 0, "?", ref=ref))
            new = _resolve(m.minsky, str(it.index))
            if new.valueId() != was:
                raise HTTPException(
                    500, "the copy is a different variable, not another icon of this "
                         "one. Nothing was added.")
            # beside the original, not on top of it -- the engine leaves the copy at
            # the same point, where it hides the icon it was copied from
            new.moveTo(raw.x() + 40.0, raw.y() + 62.0)
            settle()
            return it.index, was

        try:
            index, vid = await call(_go)
        except HTTPException:
            rollback()
            raise
        except Exception as ex:
            rollback()
            raise HTTPException(422, str(ex))
        # no wire re-derivation: the copy is appended, and appending cannot disturb the
        # index of anything already wired
        mark_dirty()
        out = await call(snapshot)
        out["index"] = index
        out["valueId"] = vid
        return out

    @app.get("/api/item/{ref}/instances")
    async def instances(ref: str):
        """Every icon of this variable, and what defines it.

        Minsky's own `canvas.findVariableDefinition` is not used: in this build it
        SEGFAULTS for every input, including an empty string, taking the process and the
        unsaved model with it. The definition is found by walking our own wire record
        instead -- whatever feeds the variable's input port.
        """
        await call(check_ref, ref)

        def _go():
            m = engine().minsky
            raw = _resolve(m, ref)
            try:
                vid = raw.valueId()
            except Exception:
                vid = None
            if not vid:
                return None
            icons = []
            for r, it in _iter_items(m):
                try:
                    if it.valueId() == vid:
                        icons.append(dict(ref=r, x=it.x(), y=it.y(),
                                          classType=it.classType()))
                except Exception:
                    continue
            # what defines it: whatever is wired INTO any icon of this variable
            defs = []
            for si, _sp, di, _dp in _WIRES:
                if di not in {i["ref"] for i in icons}:
                    continue
                try:
                    src = _resolve(m, si)
                    defs.append(dict(ref=si, classType=src.classType(),
                                     name=(src.name() if hasattr(src, "name") else None)))
                except Exception:
                    continue
            # A Godley table's stocks have no incoming wire: the TABLE defines them,
            # and its initial-conditions row is rewritten over anything set elsewhere.
            # Reporting "nothing defines this" would send someone looking for a wire.
            try:
                nm = (raw.name() or "").lstrip(":")
            except Exception:
                nm = ""
            if nm and not defs:
                own = godley_owner(nm)
                if own:
                    gref, title, col = own
                    defs.append(dict(ref=gref, classType="GodleyIcon",
                                     name=title or None, column=col,
                                     note="a table stock: its value comes from the "
                                          "table's initial-conditions row"))
            return dict(valueId=vid, name=(raw.name() or None),
                        icons=icons, definedBy=defs)

        got = await call(_go)
        if not got:
            raise HTTPException(422, "that item is not a variable, so it has no instances")
        return got

    @app.post("/api/item/{ref}/attrs")
    async def set_attrs(ref: str, spec: AttrSpec):
        """Units, slider bounds and rotation -- the rest of the variable dialog.

        Every write is read back. `setUnits` NORMALISES what it is given -- "m/s" comes
        back as "m s^-1", "1/yr" as "yr^-1" -- and it reorders terms it does not
        understand rather than refusing them, so echoing the request would tell the user
        their input was stored verbatim when it was not. The response carries what the
        engine actually holds.
        """
        require_idle()
        await call(check_ref, ref)

        given = {k: v for k, v in spec.model_dump().items() if v is not None}
        if not given:
            raise HTTPException(422, "nothing to set")
        for k in ("sliderMin", "sliderMax", "sliderStep", "rotation"):
            if k in given and not math.isfinite(given[k]):
                raise HTTPException(422, f"{k} must be a finite number")
        if "sliderMin" in given and "sliderMax" in given \
                and given["sliderMin"] >= given["sliderMax"]:
            raise HTTPException(
                422, f"the slider's minimum ({given['sliderMin']:g}) must be below its "
                     f"maximum ({given['sliderMax']:g})")
        if "sliderStep" in given and given["sliderStep"] < 0:
            raise HTTPException(422, "a slider step cannot be negative")

        await call(checkpoint)

        def _apply():
            raw = _resolve(engine().minsky, ref)
            if "units" in given:
                # The engine raises on some malformed input and silently mangles other
                # input; only the first is worth refusing.
                raw.setUnits(given["units"])
            if "sliderMin" in given:
                raw.sliderMin(given["sliderMin"])
            if "sliderMax" in given:
                raw.sliderMax(given["sliderMax"])
            if "sliderStep" in given:
                raw.sliderStep(given["sliderStep"])
            if "rotation" in given:
                # 999 and -30 are both accepted and stored verbatim, which then reads
                # back as a rotation nobody typed. Fold it into one turn.
                raw.rotation(given["rotation"] % 360)
            settle()

            out = {}
            try:
                out["units"] = raw.unitsStr()
            except Exception:
                pass
            try:
                out["slider"] = dict(min=raw.sliderMin(), max=raw.sliderMax(),
                                     step=raw.sliderStep())
            except Exception:
                pass
            try:
                out["rotation"] = raw.rotation()
            except Exception:
                pass
            return out

        try:
            got = await call(_apply)
        except HTTPException:
            raise
        except Exception as ex:
            # setUnits rejects "m^2 kg / s^3" with "empty unit name" -- a complaint about
            # the input, not a fault, so it must not surface as a 500.
            rollback()
            raise HTTPException(422, f"{ex}".strip() or "the engine refused that value")

        # Did the write land? Nothing here reports failure on its own.
        stale = []
        if "rotation" in given and abs(got.get("rotation", 1e9)
                                       - given["rotation"] % 360) > 0.01:
            stale.append("rotation")
        for key, field in (("sliderMin", "min"), ("sliderMax", "max"),
                           ("sliderStep", "step")):
            if key in given and abs(got.get("slider", {}).get(field, 1e9)
                                    - given[key]) > 1e-9:
                stale.append(key)
        if stale:
            rollback()
            raise HTTPException(
                409, f"the engine did not keep {', '.join(stale)}. Nothing was changed.")

        mark_dirty()
        out = await call(snapshot)
        out["attrs"] = got
        if "units" in given and got.get("units", "") != given["units"]:
            # not an error: "m/s" really is stored as "m s^-1"
            out["note"] = (f"units stored as {got.get('units') or 'none'!r}"
                           if got.get("units") != given["units"] else None)
        return out

    @app.post("/api/layout")
    async def tidy():
        """Arrange the canvas left to right, as ONE undo step.

        Only anchors are moved. A Godley table, an integral and a group each carry other
        items with them, so moving both the anchor and what it carries applies the offset
        twice -- and which items those are is measured from the engine, never guessed.
        """
        require_idle()
        await call(checkpoint)

        placed, report, refused = await call(lambda: _layout_plan(engine().minsky))
        if placed == 0:
            rollback()
            n = await call(lambda: sum(1 for _r, _i in _iter_items(engine().minsky)))
            raise HTTPException(
                422 if n < 2 else 409,
                "there is nothing on the canvas to arrange" if n < 2
                else "nothing could be moved; the canvas is unchanged")

        # A rearrangement must not change what is wired to what. If our record and the
        # engine's have drifted, say so and put it back rather than save a wrong model.
        n_engine = await call(lambda: _engine_wire_count(engine().minsky))
        if n_engine != len(_WIRES):
            rollback()
            raise HTTPException(
                500, f"arranging changed the wiring ({len(_WIRES)} tracked, {n_engine} "
                     f"in the model). The canvas has been put back.")

        mark_dirty()
        out = await call(snapshot)
        out["layout"] = dict(moved=placed, layers=report.get("layers", 0),
                             feedback=report.get("reversed", 0),
                             carried=report.get("carried", 0),
                             loose=report.get("loose", 0),
                             groups=report.get("groups", 0),
                             skipped=report.get("skipped", 0))
        notes = []
        if refused:
            notes.append(f"arranged {placed} of {placed + len(refused)} icons; "
                         f"{len(refused)} would not move")
        if report.get("skipped"):
            # Not a failure to hide: the user can see the group is still a mess, and
            # without the reason they would just press Tidy again.
            notes.append(
                f"{report['skipped']} group(s) left alone because they hold a Godley "
                f"table, which crashes the engine when a grouped table is saved")
        if notes:
            out["note"] = ". ".join(notes)
        return out

    @app.post("/api/items/move")
    async def move_items(spec: NudgeSpec):
        """Move several items by the same offset, as ONE edit.

        By offset rather than to a position, because that is what dragging a selection
        means, and because it needs no per-item arithmetic on the client. One checkpoint,
        so the whole drag is a single undo step rather than one per item.
        """
        require_idle()
        if not spec.refs:
            raise HTTPException(422, "no items given")
        for ref in spec.refs:
            await call(check_ref, ref)
        await call(checkpoint)

        def _go():
            m = engine()
            # One entry per item. The same ref named twice used to move it twice, which
            # also walked straight through the coordinate check: that validated
            # raw.x()+dx once, from the pre-move position, while the loop re-read the
            # position each time -- so three copies of one ref moved it 3*dx, past the
            # limit a single move is refused for.
            refs, seen = [], set()
            for r in spec.refs:
                if r not in seen:
                    seen.add(r); refs.append(r)

            before = {}
            for r in refs:
                raw = _resolve(m.minsky, r)
                before[r] = (raw.x(), raw.y())
                check_at((raw.x() + spec.dx, raw.y() + spec.dy))

            for r in refs:
                x, y = before[r][0] + spec.dx, before[r][1] + spec.dy
                try:
                    _resolve(m.minsky, r).moveTo(x, y)
                except Exception:
                    pass

            # Judge by the OFFSET ACHIEVED, not by the final coordinates. An item whose
            # owner carries it -- an IntOp's variable, a Godley table's stocks -- can end
            # up correctly displaced without landing on the exact point asked for, and
            # comparing absolute positions called those moves failures while the user
            # watched them move.
            settle()
            moved, refused = 0, []
            for r in refs:
                raw = _resolve(m.minsky, r)
                gx, gy = raw.x() - before[r][0], raw.y() - before[r][1]
                if abs(gx - spec.dx) < 1.0 and abs(gy - spec.dy) < 1.0:
                    moved += 1
                else:
                    try:
                        nm = raw.name() or raw.classType()
                    except Exception:
                        nm = raw.classType()
                    refused.append(nm)
            return moved, refused

        moved, refused = await call(_go)
        if not moved:
            rollback()
            raise HTTPException(
                409, f"{refused[0]} did not move. A Godley table places the variables it "
                     f"generates, so they can only be moved by moving the table."
                if refused else "nothing moved")
        mark_dirty()
        out = await call(snapshot)
        if refused:
            # say WHY, not where. The reason is the half that tells the user what to do.
            out["note"] = (
                f"{moved} moved; {len(refused)} did not "
                f"({', '.join(refused[:3])}{'...' if len(refused) > 3 else ''}). "
                f"A Godley table places the variables it generates, so they can only be "
                f"moved by moving the table.")
        return out

    @app.post("/api/items/delete")
    async def delete_items(spec: RefsSpec):
        """Delete several items, as ONE edit.

        Deleting is geometric AND shifts every higher index, so the refs the client sent
        go stale the moment the first one goes. Each target is therefore pinned by what
        it IS -- class, name and position -- and re-found by that before it is deleted.
        """
        require_idle()
        if not spec.refs:
            raise HTTPException(422, "no items given")
        for ref in spec.refs:
            await call(check_ref, ref)
            await call(refuse_in_group, ref, "delete")
        await call(checkpoint)

        def _go():
            from .headless import Item
            m = engine()

            # Pin each target by WHAT IT IS, and deliberately NOT by where it is.
            # Removing an item can translate the entire model: deleting one item of
            # BasicGrowthModel moves every survivor by (-106,-108). A pin that included
            # the position then matched nothing -- or, worse, matched a DIFFERENT item
            # that had just slid onto the remembered coordinates, so an unselected item
            # was deleted and the selected one survived, reported as success.
            want = []
            for r in spec.refs:
                if ":" in r:
                    continue                       # refused earlier; belt and braces
                raw = _resolve(m.minsky, r)
                try:
                    nm = raw.name()
                except Exception:
                    nm = ""
                want.append((int(r), raw.classType(), nm))
            # Descending, so each remaining index is unaffected by the deletions already
            # done -- removing item N never renumbers anything below N.
            want.sort(key=lambda t: -t[0])
            seen, uniq = set(), []
            for t in want:                          # the same item named twice is one
                if t[0] not in seen:
                    seen.add(t[0]); uniq.append(t)

            gone = 0
            for idx, cls, nm in uniq:
                n_before = len(m.minsky.model.items)
                here = None
                if 0 <= idx < n_before:
                    raw = m.minsky.model.items[idx]
                    try:
                        got = raw.name()
                    except Exception:
                        got = ""
                    if raw.classType() == cls and got == nm:
                        here = idx
                if here is None:
                    # something shifted further than expected -- find it by identity,
                    # but only when that identity is unambiguous
                    hits = []
                    for i in range(n_before):
                        raw = m.minsky.model.items[i]
                        try:
                            got = raw.name()
                        except Exception:
                            got = ""
                        if raw.classType() == cls and got == nm:
                            hits.append(i)
                    if len(hits) == 1:
                        here = hits[0]
                if here is None:
                    continue        # already went, as a Godley table takes its variables
                restructuring(lambda h=here: m.delete(Item(m, h, "?", ref=str(h))))
                # count what actually LEFT, not the calls made: deleting a Godley icon
                # takes its generated stock variables with it, and reporting "2 deleted"
                # over an emptied canvas is worse than saying nothing
                gone += n_before - len(m.minsky.model.items)
            return gone

        try:
            gone = await call(_go)
        except RuntimeError as ex:
            rollback()
            raise HTTPException(400, str(ex))
        mark_dirty()
        out = await call(snapshot)
        out["deleted"] = gone
        return out

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

    def _relocate(index: int, was: tuple) -> int:
        """Where the Godley table that WAS at `index` is now.

        A table edit can reorder model.items -- renaming a stock header moves the
        regenerated variable, and everything after it shifts. Re-resolving the table by
        its old index then found something else: the endpoint answered 422 "item 16 is a
        Variable:stock, not a Godley table" over an edit that had been applied.
        """
        m = engine().minsky
        hits = []
        for i in range(len(m.model.items)):
            it = m.model.items[i]
            if "Godley" not in it.classType():
                continue
            try:
                here = ((it.table.title() or "").strip(), round(it.x(), 1), round(it.y(), 1))
            except Exception:
                continue
            if here == was:
                hits.append(i)
        if len(hits) == 1:
            return hits[0]
        # Either nothing matched, or SEVERAL did -- two tables with the same title at the
        # same point are indistinguishable by this identity, and taking the first meant
        # an edit meant for one was answered with the other's grid. Fall back to the
        # index the caller used, which is at least the one they asked for, and only if it
        # is still a table.
        if 0 <= index < len(m.model.items) and "Godley" in m.model.items[index].classType():
            return index
        if hits:
            return hits[0]
        raise HTTPException(
            409, "that table cannot be identified after the edit -- another table shares "
                 "its name and position. Give them different names, or move one.")

    def _godley_ident(index: int):
        m = engine().minsky
        it = m.model.items[index]
        try:
            return ((it.table.title() or "").strip(), round(it.x(), 1), round(it.y(), 1))
        except Exception:
            return None

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

        def same(a: str, b: str) -> bool:
            try:
                return float(a) == float(b)
            except ValueError:
                return a.strip() == b.strip()

        out = {}
        for nm, where in seen.items():
            vals = [x[2] for x in where if x[2]]
            # Compare NUMBERS where both are numbers. Comparing the raw cell text called
            # "100" and "100.0" a disagreement, and told the user two tables were in
            # conflict over a stock they agreed about exactly.
            if len(where) > 1 and vals and any(not same(vals[0], v) for v in vals[1:]):
                out[nm] = where
        return out

    @app.get("/api/godley/{index}")
    async def godley_get(index: int):
        return await call(lambda: _godley_op(index, lambda t: t.snapshot()))

    @app.post("/api/godley/{index}/cell")
    async def godley_cell(index: int, spec: CellSpec):
        require_idle()
        await call(checkpoint)
        was = await call(_godley_ident, index)
        await call(lambda: _godley_write(
            index, lambda t: t.set_cell(spec.row, spec.col, spec.value)))
        mark_dirty()
        index = await call(_relocate, index, was)
        out = await call(lambda: _godley_op(index, lambda t: t.snapshot()))
        clashes = await call(_shared_stocks)
        if clashes:
            out["conflicts"] = [
                {"stock": nm,
                 "shown": [{"table": ttl, "value": v} for _i, ttl, v in where],
                 "note": (f"{nm} is one variable in {len(where)} tables, so it has one "
                          f"initial condition. They disagree, and the engine keeps the "
                          f"value from {where[-1][1]} -- the last of them in the model, "
                          f"whichever you typed into most recently. Set it there.")}
                for nm, where in clashes.items()]
        return out

    @app.post("/api/godley/{index}/class")
    async def godley_class(index: int, spec: ClassSpec):
        require_idle()
        await call(checkpoint)
        was = await call(_godley_ident, index)
        await call(lambda: _godley_write(index, lambda t: t.set_class(spec.col, spec.cls)))
        mark_dirty()
        index = await call(_relocate, index, was)
        return await call(lambda: _godley_op(index, lambda t: t.snapshot()))

    @app.post("/api/godley/{index}/resize")
    async def godley_resize(index: int, spec: SizeSpec):
        require_idle()
        await call(checkpoint)
        was = await call(_godley_ident, index)
        await call(lambda: _godley_write(index, lambda t: t.resize(spec.rows, spec.cols)))
        mark_dirty()
        index = await call(_relocate, index, was)
        return await call(lambda: _godley_op(index, lambda t: t.snapshot()))

    @app.post("/api/godley/{index}/row/{action}")
    async def godley_row(index: int, action: str, spec: AtSpec):
        require_idle()
        await call(checkpoint)
        if action not in ("insert", "delete"):
            raise HTTPException(422, "action must be insert or delete")
        was = await call(_godley_ident, index)
        await call(lambda: _godley_write(index, lambda t:
            t.insert_row(spec.at) if action == "insert" else t.delete_row(spec.at)))
        mark_dirty()
        index = await call(_relocate, index, was)
        return await call(lambda: _godley_op(index, lambda t: t.snapshot()))

    @app.post("/api/godley/{index}/col/{action}")
    async def godley_col(index: int, action: str, spec: AtSpec):
        require_idle()
        await call(checkpoint)
        if action not in ("insert", "delete"):
            raise HTTPException(422, "action must be insert or delete")
        was = await call(_godley_ident, index)
        await call(lambda: _godley_write(index, lambda t:
            t.insert_col(spec.at) if action == "insert" else t.delete_col(spec.at)))
        mark_dirty()
        index = await call(_relocate, index, was)
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

            # Counting is not enough. The probe sweep can focus a DIFFERENT wire and
            # delete that instead, and the count still falls by exactly one: measured
            # against the engine's own saved document, 2 of 27 deletions on
            # GoodwinLinear02 and 1 of 83 on LoanableFunds removed a wire the caller had
            # not named. (The check that missed it compared the tracked record with
            # itself, so it could not have caught this.) Read the topology back out of
            # the engine and require that what went is what was asked for.
            expect = _wire_descriptors(
                [w for j, w in enumerate(_WIRES) if j != index])
            derived = _derive_topology()
            got = _wire_descriptors(derived)
            if got != expect:
                rollback()
                raise HTTPException(
                    409, "the engine could not tell that wire from another one crossing "
                         "the same place, and deleted a different one -- so nothing was "
                         "changed. Move the items apart, or delete one of the items the "
                         "wire connects.")
            _WIRES[:] = derived

        await call(_del)
        mark_dirty()
        return await call(snapshot)

    @app.post("/api/init")
    async def set_init(spec: InitSpec):
        require_idle()
        if not math.isfinite(spec.value):
            # the engine takes the value, stores it as the string "inf", and only then
            # fails -- leaving an initial condition no reset can ever accept
            raise HTTPException(422, "an initial value must be a finite number")
        # A Godley table owns the initial condition of the stocks it generates: it is
        # stored in the table's initial-conditions row and rewritten from there at every
        # reset. Setting it here was accepted, echoed back, shown in the panel -- and
        # thrown away by the next run.
        owner = await call(godley_owner, spec.name)
        if owner:
            ref, title, col = owner
            i = ref
            raise HTTPException(
                409, f"{spec.name!r} is a stock of "
                     f"{('the table ' + repr(title)) if title else f'Godley table {i}'}, "
                     f"which holds its initial condition in the table's initial-conditions "
                     f"row. Set it there (column {col}) -- a value set here is rewritten "
                     f"from the table at the next reset.")

        await call(checkpoint)
        try:
            await call(lambda: engine().set_init(spec.name, spec.value))
        except ValueError as ex:
            rollback()
            raise HTTPException(422, str(ex))
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

        def _same():
            m = engine().minsky
            return all(getattr(m, k)() == v for k, v in kw.items()
                       if k in ("epsRel", "epsAbs", "order", "implicit", "t0", "tmax"))
        if await call(_same):
            # Setting a value to what it already holds is not an edit. It was taking a
            # checkpoint and marking the document unsaved anyway, so pressing Run --
            # which posts the panel's values before every run -- turned a saved model
            # into an unsaved one and pushed an undo point that undid nothing.
            return await call(snapshot)

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

    @app.post("/api/group")
    async def make_group(spec: LassoSpec):
        """Put every item in a rectangle into a new group.

        `Canvas::select` takes a LassoBox, which pyminsky marshals from a dict -- passing
        four floats leaves the selection EMPTY, and `groupSelection()` then cheerfully
        creates a group with nothing in it. So check that something actually moved.
        """
        require_idle()
        for pt in ((spec.x0, spec.y0), (spec.x1, spec.y1)):
            check_at(pt)
        box = dict(x0=min(spec.x0, spec.x1), y0=min(spec.y0, spec.y1),
                   x1=max(spec.x0, spec.x1), y1=max(spec.y0, spec.y1))

        def _enclosing_group():
            """The group whose bounds swallow this box, if any.

            `Canvas::select` starts with `minimalEnclosingGroup` (group.cc:865) and, when
            the whole lasso fits inside a group, searches THAT GROUP'S children instead
            of the top level. So a box drawn over a group -- to grab two ordinary items
            that happen to sit on top of it -- selects nothing at all, and the failure
            came back as "nothing in that region to group", which is the opposite of what
            the user can see.
            """
            m = engine().minsky
            for gref, grp, _p in _iter_groups(m):
                try:
                    z = grp.zoomFactor()
                    hw, hh = 0.5 * z * grp.iWidth(), 0.5 * z * grp.iHeight()
                    if (box["x0"] >= grp.x() - hw and box["x1"] <= grp.x() + hw
                            and box["y0"] >= grp.y() - hh and box["y1"] <= grp.y() + hh):
                        return gref, (grp.title() or "").strip()
                except Exception:
                    continue
            return None

        enclosing = await call(_enclosing_group)
        if enclosing:
            gref, title = enclosing
            raise HTTPException(
                409, f"that region lies entirely inside "
                     f"{('the group ' + repr(title)) if title else gref}, and the engine "
                     f"groups what it finds INSIDE the smallest group enclosing the "
                     f"region -- so nothing outside {gref} can be grouped from there. "
                     f"Drag a box that extends beyond {gref}, or move the items clear "
                     f"of it first.")

        await call(checkpoint)

        def _go():
            m = engine().minsky
            # Does the model reset NOW? If it does and it does not afterwards, the
            # grouping broke it. This is a backstop only: it is SKIPPED for a model that
            # does not reset to begin with, which is easy to arrange (one unwired stock
            # is enough), so it cannot be what protects against the Godley case. That is
            # refused outright below, whatever the model's state.
            def resets():
                try:
                    m.requestReset(); m.reset()
                    return True
                except Exception:
                    return False
            was_runnable = resets()
            # Count TOP-LEVEL ENTITIES, not top-level groups. Grouping a selection that
            # includes a group puts that group inside the new one, so the top-level group
            # count is unchanged -- and checking it rolled a perfectly good grouping back
            # while reporting that nothing had been grouped, which was the opposite of
            # what had happened. Every real grouping moves at least two things off the top
            # level and adds one group there, so the total always falls.
            before = len(m.model.items) + len(m.model.groups)
            m.canvas.select(box)
            m.canvas.groupSelection()
            after = len(m.model.items) + len(m.model.groups)
            if after >= before:
                # nothing moved: groupSelection() still made a group, with nothing in it
                rollback()
                raise HTTPException(
                    422, "nothing in that region to group. Drag a box around two or more "
                         "items -- one on its own has nothing to be grouped with.")
            # BEFORE anything serialises -- resync_wires() below writes the document,
            # and writing this state is what kills the process.
            poisoned = _tables_in_groups_live()
            if poisoned:
                rollback()
                raise HTTPException(
                    409, "that selection would put a Godley table inside a group, which "
                         "this engine cannot save: writing the file and reading it back "
                         "exits on a segmentation fault, taking the model and the undo "
                         "history with it. Leave the table out of the selection.")
            if was_runnable and not resets():
                rollback()
                raise HTTPException(
                    409, "grouping those items leaves the model unable to run: the "
                         "engine re-scopes a Godley table's stock variables into the "
                         "group while the table's own references stay outside it. "
                         "Leave the table out of the selection, or group it on its own "
                         "with everything that refers to it.")
            resync_wires()
            return before - after + 1
        moved = await call(_go)
        mark_dirty()
        return dict(grouped=moved, state=await call(snapshot))

    @app.post("/api/group/{ref}/rename")
    async def rename_group(ref: str, spec: RenameSpec):
        require_idle()

        def _go():
            grp = check_group_ref(ref)
            want = spec.name.strip()
            if not want:
                raise HTTPException(422, "a name is required")
            grp.title(want)
            return grp.title()
        await call(checkpoint)
        title = await call(_go)
        mark_dirty()
        return dict(name=title, state=await call(snapshot))

    @app.post("/api/group/{ref}/ungroup")
    async def ungroup(ref: str):
        """Dissolve a group so its contents become ordinary, editable items.

        The canvas hit test -- how delete and wiring find their target -- searches only
        the model the canvas is pointed at, and never descends into a group. Minsky's own
        client re-points the canvas at the group; that entry point takes an ItemPtr which
        pyminsky cannot marshal, so from here the way to edit a group's contents is to
        take the group apart. Undo puts it back.
        """
        require_idle()
        await call(check_group_ref, ref)
        await call(checkpoint)

        def _go():
            m = engine()
            try:
                return restructuring(lambda: m.ungroup(ref))
            except IndexError as ex:
                raise HTTPException(422, str(ex))
            except ValueError as ex:
                # a nested group: refused before anything is touched, so nothing to undo
                raise HTTPException(409, str(ex))
            except RuntimeError as ex:
                rollback()
                raise HTTPException(400, f"{ex} The model was left unchanged.")
        freed = await call(_go)
        mark_dirty()
        return dict(freed=freed, state=await call(snapshot))

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
        # Stepping back onto the state that was written to disk means the file is NOT
        # edited, whatever route got us here. _restore() left the history exactly in step,
        # so nothing is pending either way.
        here = _HIST[_PTR][0] if 0 <= _PTR < len(_HIST) else None
        mark_dirty(here != _SAVED_ID, pending=False)
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
        if len(name.encode("utf8")) > 240:
            raise HTTPException(
                422, f"that name is {len(name.encode('utf8'))} bytes long; the "
                     f"filesystem will not take more than 255")
        dest = UPLOAD_DIR / name
        # Stage under a name unique to THIS request, and put it in place only once the
        # engine has accepted it. Two things went wrong before: the staging name was
        # derived from the upload's name, so two uploads of the same name raced and one
        # deleted the other's bytes mid-move; and the move to `dest` happened before the
        # model was read, so an upload that was then REJECTED had already overwritten the
        # model of the same name -- under a reply saying "Nothing was changed."
        fd, tmpname = tempfile.mkstemp(dir=str(_SCRATCH), suffix=".mky")
        staged = Path(tmpname)
        global _CURRENT
        try:
            with os.fdopen(fd, "wb") as fh:
                shutil.copyfileobj(file.file, fh)
            if not await call(is_minsky_document, str(staged)):
                raise HTTPException(
                    422, f"{name} is not a Minsky model. Nothing was changed.")
            await call(checkpoint)
            try:
                await call(lambda: engine().minsky.load(str(staged)))
            except Exception as ex:
                kept = await call(rollback)
                raise HTTPException(422, f"{name} could not be read: {ex}. " +
                                    ("The model you had open was kept." if kept else
                                     "The canvas has been cleared."))
            complaint = await call(load_complaint, str(staged))
            if complaint:
                kept = await call(rollback)
                raise HTTPException(422, f"{name} could not be read: {complaint}. " +
                                    ("The model you had open was kept." if kept else
                                     "The canvas has been cleared."))
            shutil.move(str(staged), str(dest))     # accepted: now it may take the name
        finally:
            staged.unlink(missing_ok=True)
        _WIRES.clear()
        _WIRES.extend(await call(_topology_from_mky, str(dest)))
        _CURRENT = str(dest); mark_dirty(False)
        await call(reset_history, True)
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
        await call(reset_history, True)
        return await call(snapshot)

    @app.post("/api/save")
    async def save(spec: SaveSpec):
        # Saving reads the file back, which resets the engine -- done mid-run that
        # restarted the simulation under the client, with the stream's clock jumping
        # backwards and the values returning to their initial conditions. Every other
        # mutating endpoint is guarded; these two were not.
        require_idle()
        global _CURRENT
        # distinguish "save to the current file" from "save as, with a blank name":
        # a blank name used to fall through and quietly overwrite the current file
        if "name" in spec.model_fields_set and spec.name is not None:
            dest = check_save_path(spec.name)
        elif _CURRENT:
            dest = check_save_path(_CURRENT)     # plain Save, re-validated
        else:
            raise HTTPException(422, "nothing to save to yet -- use Save As")
        def _write():
            m = engine().minsky
            settle()
            m.save(str(dest))
            # A Godley table is not STORED the way it is displayed: writing the document
            # groups its columns by asset class -- assets, then liabilities, then equity
            # -- and appends an empty column for any class the table lacks. A table
            # edited to read A B C D came back as A D B C with an extra column, and
            # nothing said so: the file simply did not match the screen, and the user
            # only found out on reopening it. Read the file back, so that from the moment
            # of saving what is on screen IS what is in the file.
            #
            # Only when there IS a table, though. Reading the file back resets the
            # engine, which throws away the results of any completed run -- t and every
            # value snap back to their initial conditions. That is a steep price for a
            # model with nothing to reorder, and only a Godley table is reordered.
            if not any("Godley" in it.classType() for _r, it in _iter_items(m)):
                return False
            # Read it back, then say whether that CHANGED anything. Reporting "reloaded"
            # for every model with a table meant a snapshot was forced on every save: a
            # Save As with no edits made the document undoable, that undo restored a
            # byte-identical model while flipping the file to unsaved, repeated saves
            # pushed the real history out past MAX_HISTORY, and a save after an undo threw
            # the redo branch away. Comparing the document with itself across the reload
            # is exact -- both sides are the same serialisation of a live model.
            was = dest.read_bytes()
            restructuring(lambda: m.load(str(dest)))
            settle()
            m.save(str(_hist_file()))
            return _hist_file().read_bytes() != was
        reloaded = await call(_write)

        def _mark():
            global _SAVED_ID
            # Record a history entry only if there is something new to record. Forcing
            # one appended a duplicate of the current state on EVERY save, so the first
            # undo afterwards did nothing visible -- and flipped the file to "unsaved"
            # while doing it.
            if _PENDING or reloaded:
                _snap(force=reloaded)
            _SAVED_ID = _HIST[_PTR][0] if 0 <= _PTR < len(_HIST) else None
        await call(_mark)
        _CURRENT = str(dest)
        mark_dirty(False)
        return dict(saved=str(dest), name=dest.stem, dirty=False,
                    state=await call(snapshot))

    @app.get("/api/download")
    async def download():
        """Hand the model to the browser so it can be kept anywhere, without giving
        the server a write path outside its own directories."""
        require_idle()
        tmp = _SCRATCH / "download.mky"
        await call(lambda: engine().minsky.save(str(tmp)))
        stem = Path(_CURRENT).stem if _CURRENT else "model"
        return FileResponse(str(tmp), media_type="application/xml",
                            filename=f"{stem}.mky")

    #: What the engine can draw, and what to call the result. EMF is deliberately absent:
    #: renderToEMF raises "only available on Windows".
    EXPORT = {"svg": ("image/svg+xml", "renderToSVG", "renderCanvasToSVG"),
              "png": ("image/png", "renderToPNG", "renderCanvasToPNG"),
              "pdf": ("application/pdf", "renderToPDF", "renderCanvasToPDF"),
              "ps":  ("application/postscript", "renderToPS", "renderCanvasToPS")}

    #: What the engine draws in, and what each theme wants instead. It emits pure black
    #: on TRANSPARENT -- measured: 58 `fill="rgb(0%, 0%, 0%)"` in the equations, 56 in a
    #: Phillips diagram, and no background rect in either. So both themes get an explicit
    #: ground: without one, "light" is really "transparent", which a viewer compositing
    #: over black renders as black on black.
    _EQ_INK = 'rgb(0%, 0%, 0%)'
    EQ_THEME = {"light": ("#FFFFFF", "rgb(0%, 0%, 0%)", (255, 255, 255), (0, 0, 0)),
                "dark":  ("#0E1113", "rgb(90%, 93%, 94%)", (14, 17, 19), (230, 237, 240))}

    #: Breathing room around a render, in output pixels. The engine sizes its surface to
    #: the EXACT bounds of the drawing -- vectorRender measures it on a recording surface
    #: first -- so nothing is clipped, but labels sit hard against the edge with no
    #: margin at all, which reads as cropped even though it is not.
    RENDER_PAD = 18
    #: Raster renders come out at the drawing's natural size, which is small -- a
    #: Phillips diagram of EndogenousMoney is 242px across and soft once enlarged. The
    #: engine's own resolutionScaleFactor cannot be used to fix that: ecolab's
    #: vectorRender sets the surface's device OFFSET to -left,-top without scaling it
    #: while setting device SCALE to the factor, so any factor but 1 displaces the
    #: drawing and crops it. The SVG is correct at 1, so a raster is made from that.
    RENDER_SCALE = 3.0

    def _themed(raw: Path, out: Path, fmt: str, th: str, pad: int = RENDER_PAD):
        """Recolour a render into `th`, and give it a margin.

        Only the one black the engine writes is touched. A Phillips diagram also carries
        red and blue, which mean something -- rewriting every colour, or inverting, would
        destroy them.
        """
        bg_hex, ink_rgb, bg_px, ink_px = EQ_THEME[th]
        if fmt == "svg":
            doc = raw.read_text()
            doc = doc.replace(_EQ_INK, ink_rgb)
            # Grow the viewBox rather than the content: the drawing keeps its own
            # coordinates and simply gains a margin on every side.
            def _grow(m):
                w, h = float(m.group(1)), float(m.group(2))
                return (f'width="{w + 2*pad:g}" height="{h + 2*pad:g}" '
                        f'viewBox="{-pad:g} {-pad:g} {w + 2*pad:g} {h + 2*pad:g}"')
            doc, n = re.subn(r'width="([\d.]+)" height="([\d.]+)" viewBox="[^"]*"',
                             _grow, doc, count=1)
            i = doc.find(">", doc.find("<svg"))
            # the ground must cover the grown box, so it is placed in user units rather
            # than as a percentage of a box it no longer starts at
            bg = (f'\n<rect x="{-pad:g}" y="{-pad:g}" width="100%" height="100%" '
                  f'fill="{bg_hex}"/>') if n else (
                  f'\n<rect width="100%" height="100%" fill="{bg_hex}"/>')
            out.write_text(doc[:i + 1] + bg + doc[i + 1:])
            return
        from PIL import Image
        with Image.open(raw) as im:
            im = im.convert("RGBA")
            # The alpha channel IS the shape, so the ink is painted through it rather
            # than the pixels inverted -- inverting takes the transparent ground to
            # white and swallows the drawing.
            w, h = im.size
            ground = Image.new("RGB", (w + 2*pad, h + 2*pad), bg_px)
            ink = Image.new("RGB", im.size, ink_px)
            ground.paste(ink, (pad, pad), mask=im.split()[-1])
            ground.save(out)

    #: how to ask the engine for a PNG directly, set per request for the fallback path
    _FALLBACK_PNG = [lambda _p: None]

    def _render_out(raw: Path, out: Path, fmt: str, th: str):
        """Theme the render, and for a raster go via the SVG so it comes out crisp."""
        if fmt == "svg":
            _themed(raw, out, "svg", th)
            return
        tmp = out.with_suffix(".viasvg.svg")
        _themed(raw, tmp, "svg", th)
        if _rasterise(tmp, out):
            return
        # No rasteriser available. Fall back to the engine's own PNG, which is correct
        # at scale 1 -- just small.
        eng_png = raw.with_name(raw.stem + "-fallback.png")
        _FALLBACK_PNG[0](str(eng_png))
        _themed(eng_png, out, "png", th)

    def _rasterise(svg: Path, png: Path, scale: float = RENDER_SCALE) -> bool:
        """SVG -> PNG at `scale`. False if there is no rasteriser to do it with."""
        if not shutil.which("rsvg-convert"):
            return False
        r = subprocess.run(["rsvg-convert", "-z", str(scale), "-o", str(png), str(svg)],
                           capture_output=True)
        return r.returncode == 0 and png.exists() and png.stat().st_size > 0

    def _check_render_args(fmt: str, theme: str):
        f, t = fmt.lower(), theme.lower()
        if f not in ("svg", "png"):
            raise HTTPException(422, f"unknown format {fmt!r}. Use svg or png")
        if t not in EQ_THEME:
            raise HTTPException(422, f"unknown theme {theme!r}. "
                                     f"Use {' or '.join(EQ_THEME)}")
        return f, t

    @app.get("/api/equations")
    async def equations(format: str = "svg", theme: str = "dark"):
        """The model written out as equations, drawn by the engine.

        Derived from the wiring, so it is the one place a modeller can check that what
        they drew is what they meant.
        """
        require_idle()
        fmt, th = _check_render_args(format, theme)
        # ALWAYS render SVG: it is correct at the engine's own scale, and a raster is
        # made from it so the resolution is ours to choose.
        raw = _SCRATCH / "equations-raw.svg"
        out = _SCRATCH / f"equations-{th}.{fmt}"

        def _draw():
            settle()
            ed = engine().minsky.equationDisplay
            ed.renderToSVG(str(raw))
            _FALLBACK_PNG[0] = ed.renderToPNG
        await call(_draw)
        if not raw.exists() or raw.stat().st_size == 0:
            raise HTTPException(500, "the engine drew no equations")
        await run_in_threadpool(_render_out, raw, out, fmt, th)
        stem = Path(_CURRENT).stem if _CURRENT else "model"
        return FileResponse(str(out),
                            media_type="image/svg+xml" if fmt == "svg" else "image/png",
                            filename=f"{stem}-equations-{th}.{fmt}")

    @app.get("/api/phillips")
    async def phillips(format: str = "svg", theme: str = "dark"):
        """The Phillips diagram: the model's stocks and the flows between them.

        It is built from Godley tables, so a model without any has nothing to draw. The
        engine says so by producing a near-empty file rather than by failing, which would
        reach the user as a blank panel with no explanation -- so the size is checked and
        the reason given.
        """
        require_idle()
        fmt, th = _check_render_args(format, theme)
        raw = _SCRATCH / "phillips-raw.svg"
        out = _SCRATCH / f"phillips-{th}.{fmt}"

        def _draw():
            settle()
            pd = engine().minsky.phillipsDiagram
            pd.init()
            pd.renderToSVG(str(raw))
            _FALLBACK_PNG[0] = pd.renderToPNG
            n = sum(1 for _r, it in _iter_items(engine().minsky)
                    if "Godley" in it.classType())
            return n
        tables = await call(_draw)
        if not raw.exists():
            raise HTTPException(500, "the engine drew no Phillips diagram")
        # an empty render is ~169 bytes of SVG preamble and nothing else
        if raw.stat().st_size < 900:
            raise HTTPException(
                422,
                "there is nothing to draw: a Phillips diagram is built from the stocks "
                "and flows of Godley tables, and this model has "
                + (f"{tables} table(s) but no flows between them."
                   if tables else "no Godley tables."))
        await run_in_threadpool(_render_out, raw, out, fmt, th)
        stem = Path(_CURRENT).stem if _CURRENT else "model"
        return FileResponse(str(out),
                            media_type="image/svg+xml" if fmt == "svg" else "image/png",
                            filename=f"{stem}-phillips-{th}.{fmt}")

    @app.post("/api/analysis/units")
    async def check_units():
        """Are the units consistent?

        The engine raises on the first inconsistency it finds and says nothing at all
        when everything checks out, so a plain call cannot be told apart from a call that
        did nothing. Both outcomes are reported here.
        """
        require_idle()

        def _go():
            try:
                engine().minsky.dimensionalAnalysis()
            except Exception as ex:
                return str(ex).strip() or "the engine reported an inconsistency"
            return None
        problem = await call(_go)
        n = await call(lambda: sum(
            1 for _r, it in _iter_items(engine().minsky)
            if it.classType().startswith("Variable")
            and (getattr(it, "unitsStr", lambda: "")() or "")))
        return dict(ok=problem is None, problem=problem, withUnits=n)

    @app.post("/api/item/{ref}/data")
    async def load_data(ref: str, file: UploadFile = File(...),
                        x: int = 0, y: int = 1, delimiter: str = ""):
        """Load a series into an interpolated-data item from a CSV.

        `DataOp::readData` is not a CSV reader despite the name -- it is `while (f>>x>>y)`,
        whitespace-separated pairs, so a comma-separated file parses as nothing and the
        item is left empty with the filename set and no error raised. The file is parsed
        here and handed over in the form the engine actually reads.
        """
        require_idle()
        await call(check_ref, ref)
        blob = await file.read()
        if len(blob) > 8_000_000:
            raise HTTPException(413, "that file is larger than 8 MB")
        try:
            text = blob.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise HTTPException(422, "that file is not text this can read (expected UTF-8)")
        if x == y:
            raise HTTPException(422, "the x and y columns must be different")

        import csv as _csv
        sample = text[:8000]
        if delimiter:
            dial = None
            sep = delimiter
        else:
            try:
                dial = _csv.Sniffer().sniff(sample, delimiters=",;\t| ")
                sep = dial.delimiter
            except Exception:
                sep = ","
        rows = list(_csv.reader(text.splitlines(), delimiter=sep))
        pairs, skipped, header = [], 0, None
        for i, row in enumerate(rows):
            if max(x, y) >= len(row):
                skipped += 1
                continue
            try:
                pairs.append((float(row[x]), float(row[y])))
            except ValueError:
                # a first row that will not parse is a header, not an error
                if i == 0 and header is None:
                    header = [row[x].strip(), row[y].strip()]
                else:
                    skipped += 1
        if not pairs:
            raise HTTPException(
                422, f"no numeric pairs found in columns {x} and {y}. The file was read "
                     f"as {sep!r}-separated with {len(rows)} row(s); check the columns "
                     f"or give a delimiter.")
        # the engine keeps a map keyed by x, so duplicates silently overwrite
        dupes = len(pairs) - len({px for px, _ in pairs})

        staged = _SCRATCH / "data-import.txt"
        staged.write_text("".join(f"{px!r} {py!r}\n" for px, py in pairs))
        await call(checkpoint)

        def _go():
            raw = _resolve(engine().minsky, ref)
            if raw.classType() != "DataOp":
                raise HTTPException(
                    422, f"{raw.classType()} cannot hold a data series. Add an "
                         f"interpolated-data item from the palette first.")
            raw.readData(str(staged))
            got = list(raw.data.keys())
            if len(got) != len(pairs) - dupes:
                raise HTTPException(
                    500, f"the engine kept {len(got)} of {len(pairs) - dupes} points")
            return len(got), min(got), max(got)

        try:
            n, lo, hi = await call(_go)
        except HTTPException:
            rollback()
            raise
        except Exception as ex:
            rollback()
            raise HTTPException(422, str(ex))
        mark_dirty()
        out = await call(snapshot)
        out["loaded"] = dict(points=n, xFrom=lo, xTo=hi, delimiter=sep,
                             skipped=skipped, duplicates=dupes, header=header,
                             filename=file.filename)
        return out

    @app.post("/api/item/{ref}/expression")
    async def set_expression(ref: str, spec: RenameSpec):
        """A user function's body. Without one the item computes nothing."""
        require_idle()
        await call(check_ref, ref)
        await call(checkpoint)

        def _go():
            raw = _resolve(engine().minsky, ref)
            if raw.classType() != "UserFunction":
                raise HTTPException(
                    422, f"{raw.classType()} has no expression to set. Only a user "
                         f"function does.")
            raw.expression(spec.name)
            settle()
            got = raw.expression()
            if got != spec.name:
                raise HTTPException(
                    409, f"the engine kept {got!r} rather than {spec.name!r}")
            return got, raw.name(), list(raw.argNames())

        try:
            expr, name, args = await call(_go)
        except HTTPException:
            rollback()
            raise
        except Exception as ex:
            rollback()
            raise HTTPException(422, str(ex))
        mark_dirty()
        out = await call(snapshot)
        out["expression"] = expr
        out["fname"] = name
        out["args"] = args
        return out

    @app.get("/api/export/canvas")
    async def export_canvas(format: str = "svg"):
        """The whole diagram, drawn by the engine rather than by us.

        Minsky renders its own canvas to vector formats, so an export is the engine's
        own picture at any resolution -- not a screenshot of our SVG, which would carry
        our approximations of its icons.
        """
        require_idle()
        fmt = format.lower()
        if fmt not in EXPORT:
            raise HTTPException(
                422, f"unknown format {format!r}. Use one of: {', '.join(EXPORT)}")
        media, _item_meth, canvas_meth = EXPORT[fmt]
        out = _SCRATCH / f"canvas.{fmt}"

        def _draw():
            settle()
            getattr(engine().minsky, canvas_meth)(str(out))
        await call(_draw)
        if not out.exists() or out.stat().st_size == 0:
            # the renderers report success by returning; an empty file is the only sign
            raise HTTPException(500, f"the engine drew nothing for {fmt}")
        stem = Path(_CURRENT).stem if _CURRENT else "model"
        return FileResponse(str(out), media_type=media, filename=f"{stem}.{fmt}")

    @app.get("/api/export/plot/{ref}")
    async def export_plot(ref: str, format: str = "svg"):
        """One plot, at whatever size and quality the format allows."""
        require_idle()
        fmt = format.lower()
        if fmt not in EXPORT:
            raise HTTPException(
                422, f"unknown format {format!r}. Use one of: {', '.join(EXPORT)}")
        media, item_meth, _c = EXPORT[fmt]
        await call(check_ref, ref)

        def _kind():
            return _resolve(engine().minsky, ref).classType()
        cls = await call(_kind)
        if "Plot" not in cls and "Sheet" not in cls:
            raise HTTPException(422, f"{cls} is not a plot; there is nothing to draw")

        out = _SCRATCH / f"plot.{fmt}"

        def _draw():
            settle()
            getattr(_resolve(engine().minsky, ref), item_meth)(str(out))
        await call(_draw)
        if not out.exists() or out.stat().st_size == 0:
            raise HTTPException(500, f"the engine drew nothing for {fmt}")
        stem = Path(_CURRENT).stem if _CURRENT else "model"
        return FileResponse(str(out), media_type=media,
                            filename=f"{stem}-plot{ref.replace(':', '-')}.{fmt}")

    def _ink_bounds(mk, probe_dir, zoom=1.0, off=400.0, w=2600.0, h=2000.0):
        """Where the drawing actually is, in canvas coordinates.

        Canvas coordinates are not model coordinates and part of the picture sits at
        NEGATIVE ones, so a probe at the origin clips the top-left corner off and reports
        a bounding box that starts at (0,0) whatever the model looks like. Shifting the
        probe by `off` first is what makes the measurement honest.
        """
        from PIL import Image
        p = probe_dir / "probe.png"
        mk.renderCanvasToPNG(str(p), {"zoom": zoom, "left": -off, "top": -off,
                                      "width": w, "height": h})
        with Image.open(p) as im:
            box = im.split()[-1].getbbox() if im.mode == "RGBA" else im.convert("L").getbbox()
        if not box:
            return None
        return tuple(v - off for v in box)

    @app.post("/api/export/animation")
    async def export_animation(spec: AnimSpec):
        """The whole canvas running, with the values on the icons updating.

        Frames come from the engine's own renderer, so this is Minsky's picture -- real
        glyphs, curved wires, live values -- rather than a capture of our canvas.
        """
        require_idle()
        fmt = spec.format.lower()
        if fmt not in ("mp4", "gif"):
            raise HTTPException(422, f"unknown format {spec.format!r}. Use mp4 or gif")
        if not shutil.which("ffmpeg"):
            raise HTTPException(
                503, "ffmpeg is not installed, so frames cannot be encoded. The canvas "
                     "and plots can still be exported as SVG, PNG or PDF.")
        if spec.every < 1 or spec.steps < 1:
            raise HTTPException(422, "steps and every must be positive")
        frames = spec.steps // spec.every
        if not 2 <= frames <= 900:
            raise HTTPException(
                422, f"that is {frames} frames; ask for between 2 and 900 "
                     f"(steps / every)")
        # yuv420p needs even dimensions, and h264 will not encode odd ones
        W = max(320, min(1920, spec.width) // 2 * 2)
        H = max(240, min(1200, spec.height) // 2 * 2)
        fps = max(1, min(60, spec.fps))

        work = Path(tempfile.mkdtemp(dir=_SCRATCH, prefix="anim-"))
        out = work / f"animation.{fmt}"

        def _render():
            from PIL import Image
            mk = engine().minsky
            mk.reset()
            settle()

            # Frame the shot ONCE, from the union of the drawing at the start and at the
            # end: value text grows as the numbers do, and a box measured only at t=0
            # crops the digits off later in the run.
            first = _ink_bounds(mk, work)
            for _ in range(spec.steps):
                mk.step()
            last = _ink_bounds(mk, work)
            mk.reset()
            settle()
            if not first and not last:
                raise HTTPException(422, "there is nothing on the canvas to animate")
            boxes = [b for b in (first, last) if b]
            x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes)
            x1 = max(b[2] for b in boxes); y1 = max(b[3] for b in boxes)
            pad = 20.0
            zoom = min((W - 2*pad) / max(x1 - x0, 1), (H - 2*pad) / max(y1 - y0, 1))
            crop = {"zoom": zoom, "left": x0*zoom - pad, "top": y0*zoom - pad,
                    "width": float(W), "height": float(H)}

            white = Image.new("RGB", (W, H), "white")
            n = 0
            for k in range(frames):
                for _ in range(spec.every):
                    mk.step()
                raw = work / "raw.png"
                mk.renderCanvasToPNG(str(raw), crop)
                with Image.open(raw) as im:
                    # MP4 has no alpha; an unflattened frame encodes as solid black
                    flat = white.copy()
                    flat.paste(im, mask=im.split()[-1] if im.mode == "RGBA" else None)
                    flat.save(work / f"f{k:05d}.png")
                n += 1
            return n, mk.t()

        _RUNNING.set()
        try:
            n, t_end = await run_in_threadpool(locked, _render)
        finally:
            _RUNNING.clear()

        pat = str(work / "f%05d.png")
        if fmt == "mp4":
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
                   "-i", pat, "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                   "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
            r = subprocess.run(cmd, capture_output=True, text=True)
        else:
            # one shared palette, or a GIF of a line drawing bands badly
            pal = work / "palette.png"
            r = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", pat,
                 "-vf", "palettegen=stats_mode=diff", str(pal)],
                capture_output=True, text=True)
            if r.returncode == 0:
                r = subprocess.run(
                    ["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps),
                     "-i", pat, "-i", str(pal),
                     "-lavfi", "paletteuse=dither=bayer:bayer_scale=3", str(out)],
                    capture_output=True, text=True)
        if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            raise HTTPException(
                500, f"ffmpeg could not encode the {fmt}: "
                     f"{(r.stderr or '').strip()[:200] or 'no output'}")

        # The frames have served their purpose; a 900-frame render is hundreds of
        # megabytes of PNG and the scratch dir only empties when the process exits.
        for f in work.glob("*.png"):
            try:
                f.unlink()
            except OSError:
                pass

        stem = Path(_CURRENT).stem if _CURRENT else "model"
        media = "video/mp4" if fmt == "mp4" else "image/gif"
        resp = FileResponse(str(out), media_type=media, filename=f"{stem}.{fmt}",
                            # and the film itself goes once it has been sent
                            background=BackgroundTask(shutil.rmtree, work, True))
        resp.headers["X-Frames"] = str(n)
        resp.headers["X-Sim-Time"] = f"{t_end:.4f}"
        return resp

    @app.websocket("/ws/sim")
    async def ws_sim(ws: WebSocket):
        """Stream a run. Client sends {"cmd":"run","steps":N,"tmax":T} then may send
        {"cmd":"stop"}. Server emits one frame per solver step."""
        await ws.accept()
        stop = asyncio.Event()
        mine = False            # did THIS connection take the run lock?

        async def say(payload):
            try:
                await ws.send_json(payload)
                return True
            except Exception:
                return False

        async def reader():
            while True:
                try:
                    msg = await ws.receive_json()
                except (WebSocketDisconnect, RuntimeError):
                    stop.set()
                    return
                except (ValueError, KeyError):
                    # KeyError as well as ValueError: receive_json() reads message["text"],
                    # so a BINARY frame raises KeyError, not a decode error -- the same
                    # failure the ValueError arm was added to remove, by another route
                    # A frame that is not JSON used to kill this task outright, and with
                    # it the only route for "stop". For the rest of the run the Stop
                    # button did nothing, and nothing was reported either way.
                    if not await say({"error": "frames must be JSON"}):
                        stop.set()
                        return
                    continue
                if isinstance(msg, dict) and msg.get("cmd") == "stop":
                    stop.set()
                    return

        task = None
        try:
            try:
                first = await ws.receive_json()
            except (ValueError, KeyError):
                # a binary first frame raises KeyError from receive_json(); without this
                # the socket died with no error frame at all
                await say({"error": "frames must be JSON text"})
                return
            if not isinstance(first, dict) or first.get("cmd") != "run":
                await say({"error": "expected {'cmd':'run'}"})
                return

            # These were read straight into int()/float() inside the request handler, so
            # a malformed value raised where nothing was catching it: the socket simply
            # dropped, with no error frame at all, and the UI sat waiting for a run that
            # was never going to report anything.
            try:
                steps = int(first.get("steps", 200))
            except (TypeError, ValueError):
                await say({"error": f"steps must be a whole number, not "
                                    f"{first.get('steps')!r}"})
                return
            if steps < 1:
                # the loop body never ran, so its else-clause fired and the run reported
                # itself complete -- after reset() had already thrown away the state of
                # the run before it
                await say({"error": f"steps must be at least 1, not {steps}"})
                return
            # How fast to play the run back, in MODEL time units per real second.
            # Absent means as fast as the solver goes, which is how it behaved before --
            # and on a loaded model that is far too fast to watch: EndogenousMoney
            # reaches t=10 in well under a second.
            #
            # Pacing by MODEL time rather than by frames is what makes this stable. The
            # solver takes adaptive steps, so a fixed delay per step runs fast where the
            # steps are small and slow where they are large -- exactly backwards.
            rate = first.get("rate")
            if rate is not None:
                try:
                    rate = float(rate)
                except (TypeError, ValueError):
                    await say({"error": f"rate must be a number, not {first.get('rate')!r}"})
                    return
                if not math.isfinite(rate) or rate <= 0:
                    await say({"error": "rate must be a positive number of model time "
                                        "units per second"})
                    return

            tmax = first.get("tmax")
            if tmax is not None:
                try:
                    tmax = float(tmax)
                except (TypeError, ValueError):
                    await say({"error": f"tmax must be a number, not "
                                        f"{first.get('tmax')!r}"})
                    return
                if not math.isfinite(tmax):
                    await say({"error": "tmax must be a finite number"})
                    return
                # the same rule /api/solver enforces. Without it the socket accepted
                # tmax=0, wrote it into the document, took one step and reported the run
                # complete -- leaving a horizon no later run could use.
                t0 = await call(lambda: engine().minsky.t0())
                if tmax <= t0:
                    await say({"error": f"tmax ({tmax:g}) must be later than "
                                        f"t0 ({t0:g})"})
                    return

            if _RUNNING.is_set():
                await say({"error": "a simulation is already streaming"})
                return
            _RUNNING.set()
            mine = True
            task = asyncio.create_task(reader())

            try:
                # NO configure() here. It applied SANE_SOLVER on every run, so the solver
                # the caller had just set was thrown away and the run used the defaults --
                # the solver panel had no effect unless its values happened to match.
                # Sane defaults belong to a NEW model, not to every run, and a loaded
                # file's own solver block must be respected.
                await call(lambda: engine().reset())
            except RuntimeError as ex:
                await say({"error": str(ex)})
                return
            if tmax is not None:
                # tmax is part of the saved document, not a transient run argument, so a
                # run that CHANGES it edits the model, and Save would persist a horizon
                # the user never chose to store. But a run that sets it to what it
                # already is changes nothing, and was still marking a saved document
                # unsaved and pushing an undo point that undid nothing.
                was = await call(lambda: engine().minsky.tmax())
                if was != tmax:
                    await call(checkpoint)
                    await call(lambda: engine().minsky.tmax(tmax))
                    mark_dirty()

            # Same filter the snapshot uses, so the plot's series and the values panel
            # list the same variables -- and neither shows one the model has dropped.
            names = await call(
                lambda: [k for k in engine().minsky.variableValues.keys()
                         if k in live_value_ids()])
            t_start = await call(lambda: engine().minsky.t())
            wall_start = time.monotonic()

            for i in range(steps):
                if stop.is_set():
                    await say({"stopped": True, "step": i})
                    break

                def _one():
                    m = engine().minsky
                    m.step()
                    return m.t(), {k: m.variableValues[k].value() for k in names}

                try:
                    t, vals = await call(_one)
                except Exception as ex:
                    await say({"error": f"step {i} failed: {ex}"})
                    break
                bad = nonfinite(vals)
                if not await say(jsonable(
                        {"step": i, "t": t, "values": vals, "diverged": bad or None})):
                    break
                if bad:
                    # keep going past this and every later frame is noise
                    await say({"done": True, "reason": "diverged", "variables": bad})
                    break
                if rate is not None:
                    # Wait until the wall clock catches up with model time. Measured
                    # against the START of the run, not the previous frame, so a step
                    # that took too long is absorbed rather than accumulating drift.
                    #
                    # One wait, not a capped one: stop.wait() returns the moment Stop is
                    # pressed, so a long sleep is already interruptible. Capping it made
                    # the loop fall through and take another step while still behind,
                    # which ran ahead of the requested rate.
                    behind = (t - t_start) / rate - (time.monotonic() - wall_start)
                    if behind > 0:
                        try:
                            await asyncio.wait_for(stop.wait(), timeout=behind)
                        except asyncio.TimeoutError:
                            pass
                    if stop.is_set():
                        await say({"stopped": True, "step": i})
                        break

                if tmax is not None and t >= tmax:
                    await say({"done": True, "reason": "tmax", "t": t})
                    break
            else:
                await say({"done": True, "reason": "steps"})
        except WebSocketDisconnect:
            pass
        finally:
            # Only the connection that TOOK the lock may release it. A second socket that
            # opened and closed without sending anything used to clear the flag belonging
            # to a run already in progress, which unlocked editing in the middle of it.
            if mine:
                _RUNNING.clear()
            if task is not None:
                task.cancel()

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
