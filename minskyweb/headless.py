"""A logical model-building API over Minsky's geometric one.

WHY THIS EXISTS
---------------
Minsky's engine is fully headless-capable, but connecting two items is not a logical
operation on the model -- it is a simulated mouse gesture at pixel coordinates:

    canvas.mouseDown(src.portX(0), src.portY(0))
    canvas.mouseUp(dst.portX(1), dst.portY(1))

Two things make that hostile to use directly, and both fail SILENTLY:

  1. Port coordinates are stale until `updateBoundingBox()` runs. Straight after
     `moveTo(100,100)` a port reports the item CENTRE, not the port. Wiring there
     creates nothing, raises nothing, and `len(model.wires)` simply stays put. The
     REPL never shows this because rendering item icons updates the boxes as a side
     effect -- so the identical script works over the pipe and fails from Python.

  2. If items overlap, port coordinates collide and the gesture attaches to whichever
     item the hit test finds first. Also silent, and it produces a model that loads
     and runs while being wired wrongly.

So every wire here is VERIFIED against the wire count and raises on failure. Nothing
in this module returns quietly on a wiring error -- that is its main job.

PORT CONVENTION (measured, not assumed -- see docs/MINSKY_HEADLESS.md)
    port 0        the OUTPUT, always
    ports 1..n-1  the INPUTS, in order
    stock/parameter variables and `time` have an output only (portsSize() == 1)
"""
from __future__ import annotations

from dataclasses import dataclass

from .session import load_minsky

# Minsky's own shipped default is epsRel=1e-2, which silently produces NaN on stiff
# models and then reports success. These are the defaults this layer applies unless
# told otherwise.
SANE_SOLVER = dict(epsRel=1e-8, epsAbs=1e-10, order=4, implicit=True)


class WiringError(RuntimeError):
    """A wire was requested and the engine did not create it."""


@dataclass
class Item:
    """A handle on one canvas item, identified by its index in model.items."""
    model: "Model"
    index: int
    kind: str
    name: str | None = None

    @property
    def _raw(self):
        return self.model.minsky.model.items[self.index]

    def refresh(self):
        """Port coordinates are meaningless until this has run. Called automatically."""
        self._raw.updateBoundingBox()
        return self

    @property
    def n_ports(self) -> int:
        return self._raw.portsSize()

    def port_xy(self, port: int) -> tuple[float, float]:
        if not 0 <= port < self.n_ports:
            raise IndexError(
                f"{self} has ports 0..{self.n_ports - 1}; asked for {port}. "
                f"Port 0 is the output; inputs start at 1.")
        self.refresh()
        r = self._raw
        return r.portX(port), r.portY(port)

    def move_to(self, x: float, y: float):
        self._raw.moveTo(x, y)
        return self.refresh()

    def __repr__(self):
        return f"<{self.kind}{':' + self.name if self.name else ''} #{self.index}>"


_ACTIVE: "Model | None" = None


class Godley:
    """A Godley table: the double-entry block that makes Minsky worth keeping.

    SEMANTICS, ALL MEASURED AGAINST A SHIPPED MODEL (examples/LoanableFunds.mky):

      row 0     column headers. cell(0,0) is a label ("Flows V / Stock Variables ->");
                cells 1.. are STOCK names, plain -- an "Assets:" prefix is not used and
                does not set the class.
      row 1     initial conditions (`initialConditionRow(r)` reports which row it is).
      rows 2..  flows. Column 0 is the flow's label; cells 1.. are flow VARIABLE NAMES.
      classes   set with `assetClass(col, "asset"|"liability"|"equity")`. This is a
                SETTER, and it is the only thing that sets the class.
      balance   `rowSum(r)` returns a SYMBOLIC string -- '0' balanced, '-2L' not.
                It raises on row 0. The sum is assets - liabilities - equity, so a
                balanced transfer between an asset and a liability carries the SAME
                sign on both sides, while two liabilities carry opposite signs.

    THE TRAP: `icon.update()` must be called after editing, or `reset()` dies with
    "Invalid valueId: :<stock>" and the stock variables are never created. Neither
    `editor.update()` nor doing nothing works -- only the icon's own `update()`. Every
    mutating method here calls it, so it cannot be forgotten.

    A numeric literal in a flow cell parses and balances but drives NOTHING -- the stock
    stays at its initial condition. Flow cells name flow variables, whose values come
    from the canvas. Verified end to end: rate=5 wired into flow `Lend` moves Reserves
    100 -> 120.1 and Deposits 60 -> 80.1 over t=4.02, both exact.
    """
    CLASSES = ("noAssetClass", "asset", "liability", "equity")

    def __init__(self, model: "Model", index: int):
        self.model, self.index = model, index

    @property
    def _icon(self):
        return self.model.minsky.model.items[self.index]

    @property
    def _t(self):
        return self._icon.table

    def _commit(self):
        self._icon.update()

    def snapshot(self) -> dict:
        t = self._t
        rows, cols = t.rows(), t.cols()
        sums = []
        for r in range(rows):
            if r == 0:
                sums.append(None)          # rowSum raises on the header row
                continue
            try:
                sums.append(str(t.rowSum(r)))
            except Exception:
                sums.append(None)
        return dict(
            index=self.index, rows=rows, cols=cols,
            title=(t.title() or ""),
            cells=[[t.getCell(r, c) for c in range(cols)] for r in range(rows)],
            classes=[t.assetClass(c) for c in range(cols)],
            rowSums=sums,
            icRow=[bool(t.initialConditionRow(r)) for r in range(rows)],
            doubleEntry=bool(t.doubleEntryCompliant()))

    def set_cell(self, r: int, c: int, text: str):
        t = self._t
        if not (0 <= r < t.rows() and 0 <= c < t.cols()):
            raise IndexError(f"cell ({r},{c}) outside {t.rows()}x{t.cols()}")
        t.setCell(r, c, text)
        self._commit()

    def set_class(self, col: int, cls: str):
        if cls not in self.CLASSES:
            raise ValueError(f"asset class must be one of {self.CLASSES}, got {cls!r}")
        if col == 0:
            raise ValueError("column 0 holds flow labels and has no asset class")
        self._t.assetClass(col, cls)
        self._commit()

    def resize(self, rows: int, cols: int):
        self._t.resize(max(2, rows), max(2, cols))
        self._commit()

    def insert_row(self, at: int):
        self._t.insertRow(at); self._commit()

    def delete_row(self, at: int):
        if at == 0:
            raise ValueError("row 0 holds the stock names and cannot be deleted")
        self._t.deleteRow(at); self._commit()

    def insert_col(self, at: int):
        self._t.insertCol(at); self._commit()

    def delete_col(self, at: int):
        """Remove a stock column, by rewriting the grid.

        The engine's own `deleteCol` cannot be used. It is not "remove column N": it
        indexes differently from `deleteRow`, it SWAPS the last column into the gap
        instead of shifting, and it sometimes leaves the column count unchanged --

            deleteCol(2): ['', 'A','B','C','D'] -> ['', 'D','B','C']
            deleteCol(3): ['', 'A','B','C','D'] -> ['', 'A','D','','C']

        so a user removing the second of four stocks would silently find the fourth had
        moved into its place. `deleteRow` behaves correctly and is used directly.

        Rewriting is deterministic: read the grid, drop the column, shrink, write it back,
        and carry the asset classes across with the shift.
        """
        if at == 0:
            raise ValueError("column 0 holds the flow labels and cannot be deleted")
        snap = self.snapshot()
        if snap["cols"] <= 2:
            raise ValueError("a Godley table needs at least one stock column")
        if at >= snap["cols"]:
            raise IndexError(f"column {at} outside 0..{snap['cols'] - 1}")
        cells = [[v for c, v in enumerate(row) if c != at] for row in snap["cells"]]
        classes = [v for c, v in enumerate(snap["classes"]) if c != at]
        t = self._t
        t.resize(snap["rows"], snap["cols"] - 1)
        for r, row in enumerate(cells):
            for c, v in enumerate(row):
                t.setCell(r, c, v)
        for c in range(1, len(classes)):
            if classes[c] in self.CLASSES:
                t.assetClass(c, classes[c])
        self._commit()

    def unbalanced(self) -> list[int]:
        """Rows whose sum is not '0' -- the stock-flow consistency check."""
        s = self.snapshot()
        return [i for i, v in enumerate(s["rowSums"])
                if i > 0 and v is not None and v.strip() not in ("0", "")]


class Model:
    """Build, wire and run a Minsky model with no GUI.

    ONE ENGINE PER PROCESS. `pyminsky` binds a C++ *singleton* (`RESTMinsky rminsky`
    in RESTService.cc), so every Model shares one engine and one model. Constructing a
    second Model therefore WIPES the first -- which looks exactly like an independent
    document object right up until your items vanish. Constructing a second one raises
    unless you pass takeover=True to say you meant it.

    Serving multiple documents concurrently needs multiple PROCESSES, not multiple
    Model objects. See server.py.

    Items are auto-placed on a grid when no position is given, because overlapping
    items make port hit-testing ambiguous and mis-wire silently.
    """

    #: grid spacing, comfortably wider than any default item
    DX, DY, X0, Y0, COLS = 220.0, 140.0, 120.0, 120.0, 6

    def __init__(self, minsky=None, takeover: bool = False):
        global _ACTIVE
        if _ACTIVE is not None and not takeover:
            raise RuntimeError(
                "a Model already owns this process's Minsky engine. pyminsky is a "
                "singleton, so a second Model would silently wipe the first. Use "
                "Model.current() to get the existing one, model.clear() to start a "
                "fresh document in it, or Model(takeover=True) if you really mean to "
                "discard what is loaded.")
        self.minsky = minsky if minsky is not None else load_minsky()[0]
        self.items: list[Item] = []
        self.clear()
        _ACTIVE = self

    @classmethod
    def current(cls) -> "Model":
        """The Model owning this process's engine, creating it on first use."""
        return _ACTIVE if _ACTIVE is not None else cls()

    # ---- construction -------------------------------------------------------
    def clear(self):
        self.minsky.clearAllMaps()
        self.items = []
        return self

    def _place(self, at):
        if at is not None:
            return at
        i = len(self.items)
        return (self.X0 + (i % self.COLS) * self.DX,
                self.Y0 + (i // self.COLS) * self.DY)

    def _adopt(self, kind: str, name: str | None, at, expect: str) -> Item:
        """Take ownership of the item the engine just added, and CHECK it is the right one.

        Some calls create more than one item: addOperation('integrate') creates a
        Variable:integral AND an IntOp. The one to wire is the last, but relying on
        that silently would mis-wire the day the order changes, so the classType is
        verified rather than assumed.
        """
        idx = len(self.minsky.model.items) - 1
        if idx < 0:
            raise RuntimeError(f"engine did not create the {kind} item")
        got = self.minsky.model.items[idx].classType()
        if expect not in got:
            raise RuntimeError(
                f"expected the new {kind} to be a {expect!r} but the last item is "
                f"{got!r}. addOperation/addVariable may have changed how many items "
                f"it creates; _adopt needs updating.")
        it = Item(self, idx, kind, name)
        x, y = self._place(at)
        it.move_to(x, y)
        self.items.append(it)
        return it

    def variable(self, name: str, kind: str = "flow", at=None) -> Item:
        self.minsky.canvas.addVariable(name, kind)
        return self._adopt(f"var:{kind}", name, at, expect=f"Variable:{kind}")

    def parameter(self, name: str, value: float, at=None) -> Item:
        it = self.variable(name, "parameter", at)
        self.set_init(name, value)
        return it

    def operation(self, op: str, at=None) -> Item:
        self.minsky.canvas.addOperation(op)
        # 'integrate' yields an IntOp (plus a Variable:integral); the rest are Operation:<op>
        return self._adopt(f"op:{op}", None, at,
                           expect="IntOp" if op == "integrate" else f"Operation:{op}")

    def godley(self, at=None, flow_rows: int = 1) -> Item:
        """A Godley table, with `flow_rows` blank flow rows.

        The engine creates one with only two rows -- the stock headers and initial
        conditions -- so it has nowhere to enter a flow, while every description of the
        thing (including the editor's own hint) talks about flow rows. Seeding one means
        the table matches what it says it is and can be typed into immediately. A blank
        flow row sums to '0' and drives nothing, so it costs nothing to leave unused.
        """
        self.minsky.canvas.addGodley()
        it = self._adopt("godley", None, at, expect="GodleyIcon")
        if flow_rows:
            t = Godley(self, it.index)
            snap = t.snapshot()
            t.resize(snap["rows"] + flow_rows, snap["cols"])
        return it

    def table(self, index: int) -> "Godley":
        """The Godley table at `index`, wrapped so update() cannot be forgotten."""
        ct = self.minsky.model.items[index].classType()
        if "Godley" not in ct:
            raise TypeError(f"item {index} is a {ct}, not a Godley table")
        return Godley(self, index)

    def set_init(self, name: str, value) -> None:
        """Initial value / parameter value. Minsky wants this as a STRING expression."""
        self.minsky.variableValues[f":{name}"].init(str(value))

    # ---- the part that actually needed writing -------------------------------
    def wire(self, src: Item, dst: Item, port: int = 1) -> None:
        """Connect src's output to dst's input `port`. Verified; raises if not created.

        `port` defaults to 1, the first input, which is the only input on unary
        operations and on flow variables.
        """
        if src.n_ports < 1:
            raise WiringError(f"{src} has no output port")
        if port == 0:
            raise WiringError(
                f"port 0 of {dst} is its OUTPUT; inputs start at 1")
        if port >= dst.n_ports:
            raise WiringError(
                f"{dst} has inputs 1..{dst.n_ports - 1}; asked for {port}. "
                f"A stock or parameter variable has no input port -- drive it from "
                f"an integral or a Godley table instead.")

        before = len(self.minsky.model.wires)
        sx, sy = src.port_xy(0)
        dx, dy = dst.port_xy(port)
        self.minsky.canvas.mouseDown(sx, sy)
        self.minsky.canvas.mouseUp(dx, dy)
        after = len(self.minsky.model.wires)

        if after != before + 1:
            raise WiringError(
                f"wiring {src} -> {dst}[{port}] created {after - before} wires, "
                f"expected 1.\n"
                f"  src port 0 at ({sx:.1f},{sy:.1f});  dst port {port} at ({dx:.1f},{dy:.1f})\n"
                f"  Usual causes: the two items overlap, so the hit test picked the "
                f"wrong one; or the target port already has a wire (inputs accept one).")

    def connect(self, *chain: Item) -> None:
        """wire(a,b); wire(b,c); ... for a linear chain."""
        for a, b in zip(chain[:-1], chain[1:]):
            self.wire(a, b)

    def delete(self, item: Item) -> None:
        """Remove an item. Verified -- deletion is another silent-no-op hazard.

        `model.deleteItem(i)` accepts an index, returns without error, and deletes
        NOTHING. The route that works is the canvas hit-test: focus the item by its
        coordinates, then delete the focused item. So deletion, like wiring, is
        geometric rather than logical.

        NOTE indices shift after a delete. Callers holding Item handles must re-read
        the model; the server returns a fresh snapshot after every mutation for exactly
        this reason.
        """
        before = len(self.minsky.model.items)
        item.refresh()
        raw = item._raw
        if not self.minsky.canvas.getItemAt(raw.x(), raw.y()):
            raise RuntimeError(
                f"no item found at {item}'s own coordinates "
                f"({raw.x():.1f},{raw.y():.1f}) -- cannot focus it to delete it")
        self.minsky.canvas.deleteItem()
        after = len(self.minsky.model.items)
        if after >= before:
            raise RuntimeError(
                f"deleting {item} removed {before - after} items. "
                f"model.deleteItem(index) silently does nothing; this uses the canvas "
                f"hit-test, which may have focused a different overlapping item.")
        self.items = [i for i in self.items if i.index != item.index]
        for i in self.items:
            if i.index > item.index:
                i.index -= 1

    def move(self, item: Item, x: float, y: float) -> None:
        item.move_to(x, y)

    # ---- running -------------------------------------------------------------
    def configure(self, **kw):
        cfg = {**SANE_SOLVER, **kw}
        for k, v in cfg.items():
            getattr(self.minsky, k)(v)
        return self

    def reset(self):
        """Reset, and REPORT failure. A failed reset does not reliably stop step()."""
        try:
            self.minsky.reset()
        except Exception as ex:
            raise RuntimeError(
                f"reset failed: {ex}. Do not step -- a model whose reset threw can "
                f"still advance t on whatever subgraph happens to be valid.") from ex
        return self

    def run(self, steps: int = 100, configure: bool = True):
        """Reset and step. Returns {name: [values]} for every named variable."""
        if configure:
            self.configure()
        self.reset()
        names = [k for k in self.minsky.variableValues.keys()
                 if not k.startswith("constant:")]
        out = {k: [self.minsky.variableValues[k].value()] for k in names}
        ts = [self.minsky.t()]
        for _ in range(steps):
            self.minsky.step()
            ts.append(self.minsky.t())
            for k in names:
                out[k].append(self.minsky.variableValues[k].value())
        out["t"] = ts
        return out

    def value(self, name: str) -> float:
        return self.minsky.variableValues[f":{name}"].value()

    def save(self, path: str):
        self.minsky.save(path)
        return self

    def summary(self) -> str:
        return (f"{len(self.minsky.model.items)} items, "
                f"{len(self.minsky.model.wires)} wires")
