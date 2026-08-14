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


def _resolve(m, ref: str):
    if ":" in ref:
        g, i = ref[1:].split(":")
        return m.model.groups[int(g)].items[int(i)]
    return m.model.items[int(ref)]


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
    refs = [ref for ref, _ in _iter_items(engine().minsky)]
    if len(ordered) != len(refs):
        return []                       # shapes disagree; report nothing over guessing
    ref_of = dict(zip(ordered, refs))

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

#: Wire topology snapshots, keyed by the ENGINE's history pointer.
#:
#: Undo rewrites engine state without telling us, and `_WIRES` is the only record of
#: which ports each wire joins -- the engine cannot report it. So undoing would leave the
#: canvas drawing wires that no longer exist. Snapshotting `_WIRES` at exactly the points
#: the engine pushes history, and keying by its own pointer, keeps the two in step
#: without a second pointer of our own to drift.
#:
#: `undo(0)` is a non-mutating getter for that pointer (1-based); `undo(1)` / `undo(-1)`
#: move it and return the new value.
_WHIST: dict[int, list] = {}


#: Our own history pointer.
#:
#: DO NOT use `undo(0)` to read the engine's. It is NOT a getter -- it restores the state
#: at the current pointer, DISCARDING anything not yet pushed. Calling it from snapshot()
#: to compute canUndo/canRedo silently reverted every edit the moment the client read
#: state back: add an item, ask for state, item gone. `pushHistory()` returns True only
#: when the state actually changed, which is enough to keep this in step.
_PTR = 1


def history_ptr() -> int:
    return _PTR


def checkpoint():
    """Record an undo point for the state as it is NOW, BEFORE a mutation.

    Two reasons it must run before rather than after:

    1. NOTHING pushes engine history from pyminsky. The REPL gets it free because
       RESTService.cc calls commandHook after every command; direct method calls do not.
       Without this, undo silently does nothing at all.

    2. `pushHistory()` REORDERS `model.items`. It round-trips the model, and Godley-owned
       variables are regenerated at the end of the list. Pushing after a mutation
       therefore invalidates the index that mutation just returned -- an /api/item call
       reported index 5, a push moved it to 1, and the next /api/wire against index 5 hit
       a different item entirely. Pushing first means every index handed out afterwards
       stays valid until the next checkpoint.

    The wire topology is snapshotted at the same instant and keyed by the engine's own
    history pointer, so the two timelines cannot drift.
    """
    global _PTR
    mk = engine().minsky
    if mk.pushHistory():
        _PTR += 1
    for k in [k for k in _WHIST if k > _PTR]:   # a new edit truncates the redo tail
        del _WHIST[k]
    _WHIST[_PTR] = list(_WIRES)


def reset_history():
    """Start a fresh timeline, with the current model as its baseline."""
    mk = engine().minsky
    global _PTR
    mk.clearHistory()
    _WHIST.clear()
    mk.pushHistory()
    _PTR = 1
    _WHIST[_PTR] = list(_WIRES)


def reset_history_sync():
    reset_history()


def capture_tip():
    """Record the live state at the tip so the newest action can be redone.

    Undo steps back through pushed states; the current one was never pushed (checkpoints
    happen before mutations). `checkPushHistory()` pushes it only if we are at the tip,
    which is exactly the condition that matters.
    """
    global _PTR
    mk = engine().minsky
    if mk.pushHistory():
        _PTR += 1
        _WHIST[_PTR] = list(_WIRES)


def mark_dirty(v: bool = True):
    global _DIRTY
    _DIRTY = v


def _roots() -> list[Path]:
    return [r for r in MODEL_ROOTS if r.is_dir()]


def check_save_path(name: str) -> Path:
    """Resolve a save target, or refuse it.

    A bare name goes to SAVE_DIR. A full path must land inside a WRITABLE root --
    notably NOT ~/minsky/examples, which is readable but must stay pristine.
    """
    raw = Path(name).expanduser()
    p = raw if raw.is_absolute() else SAVE_DIR / raw.name
    if p.suffix.lower() != ".mky":
        p = p.with_suffix(".mky")
    p = Path(os.path.normpath(str(p)))
    for r in WRITE_ROOTS:
        try:
            p.relative_to(r.resolve() if r.exists() else r)
            p.parent.mkdir(parents=True, exist_ok=True)
            return p
        except ValueError:
            continue
    raise HTTPException(
        403, f"cannot save to {p}. Writable directories: "
             f"{', '.join(str(r) for r in WRITE_ROOTS)}. The shipped examples are "
             f"read-only; use Save As, or Download to keep a copy elsewhere.")


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


class SaveSpec(BaseModel):
    name: str | None = None


# ------------------------------------------------------------------------ read model
def snapshot() -> dict[str, Any]:
    """Everything a client needs to draw the model."""
    m = engine().minsky
    items = []
    for ref, it in _iter_items(m):
        it.updateBoundingBox()          # port coords are stale until this runs
        ports = [dict(index=p, x=it.portX(p), y=it.portY(p),
                      role="output" if p == 0 else "input")
                 for p in range(it.portsSize())]
        nested = ":" in ref
        entry = dict(index=int(ref) if not nested else None, ref=ref,
                     classType=it.classType(), x=it.x(), y=it.y(), ports=ports,
                     readOnly=nested)
        try:
            entry["name"] = it.name()
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
        canUndo=(history_ptr() > 1),
        canRedo=any(k > history_ptr() for k in _WHIST),
        solver=dict(epsRel=m.epsRel(), epsAbs=m.epsAbs(), order=m.order(),
                    implicit=m.implicit(), t0=m.t0(), tmax=m.tmax())))


def create_app() -> FastAPI:
    app = FastAPI(title="Minsky headless server", version="0.1")

    @app.exception_handler(WiringError)
    async def _wiring(_req, exc: WiringError):
        # wiring failures carry the diagnosis; surface it rather than a bare 500
        return JSONResponse(status_code=400, content={"error": str(exc)})

    @app.get("/api/state")
    async def get_state():
        return await call(snapshot)

    @app.post("/api/clear")
    async def clear():
        global _CURRENT
        require_idle()
        await call(lambda: engine().clear())
        _WIRES.clear()
        _CURRENT = None; mark_dirty(False)
        await call(reset_history)
        return await call(snapshot)

    @app.post("/api/item")
    async def add_item(spec: ItemSpec):
        require_idle()
        await call(checkpoint)

        def _add():
            m = engine()
            if spec.kind == "parameter":
                if spec.name is None or spec.value is None:
                    raise HTTPException(422, "parameter needs name and value")
                return m.parameter(spec.name, spec.value, at=spec.at)
            if spec.kind == "variable":
                if spec.name is None:
                    raise HTTPException(422, "variable needs a name")
                return m.variable(spec.name, spec.var_type, at=spec.at)
            if spec.kind == "operation":
                if not spec.op:
                    raise HTTPException(422, "operation needs 'op'")
                return m.operation(spec.op, at=spec.at)
            if spec.kind == "godley":
                return m.godley(at=spec.at)
            raise HTTPException(422, f"unknown kind {spec.kind!r}")

        it = await call(_add)
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
            m.wire(Item(m, spec.src, "?"), Item(m, spec.dst, "?"), spec.port)
            _WIRES.append((str(spec.src), 0, str(spec.dst), spec.port))

        await call(_wire)
        mark_dirty()
        return await call(snapshot)

    @app.post("/api/item/{index}/move")
    async def move_item(index: int, spec: MoveSpec):
        require_idle()
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
            m.delete(Item(m, index, "?"))
        try:
            await call(_del)
        except RuntimeError as ex:
            raise HTTPException(400, str(ex))
        # deleting an item removes its wires and shifts every higher index down one
        def _shift(r):
            # only top-level refs shift; group members are unaffected by a top-level delete
            return str(int(r) - 1) if (":" not in r and int(r) > index) else r
        kept = [w for w in _WIRES
                if not (":" not in w[0] and int(w[0]) == index)
                and not (":" not in w[2] and int(w[2]) == index)]
        _WIRES[:] = [(_shift(a), b, _shift(c), d) for a, b, c, d in kept]
        mark_dirty()
        # indices shift after a delete -- the client must re-render from this snapshot
        return await call(snapshot)

    # ---- Godley tables ----------------------------------------------------------
    def _tbl(index: int):
        from .headless import Godley
        m = engine()
        n = len(m.minsky.model.items)
        if not 0 <= index < n:
            raise HTTPException(422, f"index {index} out of range (0..{n-1})")
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

    @app.get("/api/godley/{index}")
    async def godley_get(index: int):
        return await call(lambda: _godley_op(index, lambda t: t.snapshot()))

    @app.post("/api/godley/{index}/cell")
    async def godley_cell(index: int, spec: CellSpec):
        require_idle()
        await call(checkpoint)
        await call(lambda: _godley_op(
            index, lambda t: t.set_cell(spec.row, spec.col, spec.value)))
        mark_dirty()
        return await call(lambda: _godley_op(index, lambda t: t.snapshot()))

    @app.post("/api/godley/{index}/class")
    async def godley_class(index: int, spec: ClassSpec):
        require_idle()
        await call(checkpoint)
        await call(lambda: _godley_op(index, lambda t: t.set_class(spec.col, spec.cls)))
        mark_dirty()
        return await call(lambda: _godley_op(index, lambda t: t.snapshot()))

    @app.post("/api/godley/{index}/resize")
    async def godley_resize(index: int, spec: SizeSpec):
        require_idle()
        await call(checkpoint)
        await call(lambda: _godley_op(index, lambda t: t.resize(spec.rows, spec.cols)))
        mark_dirty()
        return await call(lambda: _godley_op(index, lambda t: t.snapshot()))

    @app.post("/api/godley/{index}/row/{action}")
    async def godley_row(index: int, action: str, spec: AtSpec):
        require_idle()
        await call(checkpoint)
        if action not in ("insert", "delete"):
            raise HTTPException(422, "action must be insert or delete")
        await call(lambda: _godley_op(index, lambda t:
            t.insert_row(spec.at) if action == "insert" else t.delete_row(spec.at)))
        mark_dirty()
        return await call(lambda: _godley_op(index, lambda t: t.snapshot()))

    @app.post("/api/godley/{index}/col/{action}")
    async def godley_col(index: int, action: str, spec: AtSpec):
        require_idle()
        await call(checkpoint)
        if action not in ("insert", "delete"):
            raise HTTPException(422, "action must be insert or delete")
        await call(lambda: _godley_op(index, lambda t:
            t.insert_col(spec.at) if action == "insert" else t.delete_col(spec.at)))
        mark_dirty()
        return await call(lambda: _godley_op(index, lambda t: t.snapshot()))

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
        kw = {k: v for k, v in spec.model_dump().items() if v is not None}

        def _cfg():
            m = engine()
            m.configure(**{k: v for k, v in kw.items()
                           if k in ("epsRel", "epsAbs", "order", "implicit")})
            for k in ("t0", "tmax"):
                if k in kw:
                    getattr(m.minsky, k)(kw[k])
        await call(_cfg)
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

        await call(capture_tip)

        def _go():
            global _PTR
            mk = engine().minsky
            was = _PTR
            now = int(mk.undo(delta))
            _PTR = now
            if now == was:
                return False
            # the engine has just rewritten the model; our wire record must follow it
            snap = _WHIST.get(now)
            if snap is None:
                # no snapshot for this point -- say so rather than draw stale wires
                _WIRES.clear()
            else:
                _WIRES[:] = list(snap)
            return True

        moved = await call(_go)
        if not moved:
            raise HTTPException(409, f"nothing to {what}")
        mark_dirty()
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
            for f in sorted(r.glob("*.mky")):
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
        await call(lambda: engine().minsky.load(str(dest)))
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
        await call(lambda: engine().minsky.load(path))
        _WIRES.clear()
        _WIRES.extend(await call(_topology_from_mky, path))
        _CURRENT = path; mark_dirty(False)
        await call(reset_history)
        return await call(snapshot)

    @app.post("/api/save")
    async def save(spec: SaveSpec):
        global _CURRENT
        if spec.name:
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
                    await call(lambda: engine().configure())
                    await call(lambda: engine().reset())
                except RuntimeError as ex:
                    await ws.send_json({"error": str(ex)})
                    return
                if tmax is not None:
                    await call(lambda: engine().minsky.tmax(float(tmax)))

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
