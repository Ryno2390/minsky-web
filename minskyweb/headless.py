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
    """A handle on one canvas item.

    `index` addresses `model.items`. `ref` addresses anything, including a group member
    -- "3" for a top-level item, "g0:5" for member 5 of group 0 -- because group members
    live at `groups[g].items[i]` and are not in `model.items` at all.
    """
    model: "Model"
    index: int
    kind: str
    name: str | None = None
    ref: str | None = None

    @property
    def _raw(self):
        r = self.ref if self.ref is not None else str(self.index)
        if ":" in r:
            # groups nest, so the group part is a dotted PATH: "g0:5" is member 5 of
            # group 0, "g0.1:5" is member 5 of group 1 inside group 0
            head, _, i = r.partition(":")
            node = self.model.minsky.model
            for part in head[1:].split("."):
                node = node.groups[int(part)]
            return node.items[int(i)]
        return self.model.minsky.model.items[int(r)]

    @property
    def in_group(self) -> bool:
        return self.ref is not None and ":" in self.ref

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

    def _bounds(self, r=None, c=None, *, r_max_extra=0, c_max_extra=0):
        """Range-check before anything reaches C++.

        An out-of-range index passed through to the engine does not raise -- it KILLS THE
        PROCESS. `row/delete` with at=9999 took the whole server down and the unsaved
        model with it. Every index that crosses into the engine is checked here first.
        """
        t = self._t
        if r is not None and not 0 <= r < t.rows() + r_max_extra:
            raise IndexError(
                f"row {r} is outside 0..{t.rows() - 1 + r_max_extra}")
        if c is not None and not 0 <= c < t.cols() + c_max_extra:
            raise IndexError(
                f"column {c} is outside 0..{t.cols() - 1 + c_max_extra}")

    def set_cell(self, r: int, c: int, text: str):
        t = self._t
        if not (0 <= r < t.rows() and 0 <= c < t.cols()):
            raise IndexError(f"cell ({r},{c}) outside {t.rows()}x{t.cols()}")
        # An EMPTIED initial-condition cell is written straight back. set_cell writes ""
        # into the table, then `icon.update()` takes its `start==npos` branch and
        # repopulates the cell from the variable's own init -- so clearing the field
        # succeeded, the old number reappeared, and nothing said why. The engine's own
        # GodleyIcon::setCell stores a zero for this, so do the same: "no initial
        # condition" and "an initial condition of zero" are the same thing here.
        if not text.strip() and t.initialConditionRow(r) and c > 0:
            text = self.IC_CLEARED
        t.setCell(r, c, text)
        self._commit()

    def set_class(self, col: int, cls: str):
        self._bounds(c=col)
        if cls not in self.CLASSES:
            raise ValueError(f"asset class must be one of {self.CLASSES}, got {cls!r}")
        if col == 0:
            raise ValueError("column 0 holds flow labels and has no asset class")
        self._t.assetClass(col, cls)
        self._commit()

    def resize(self, rows: int, cols: int):
        if not (2 <= rows <= 500 and 2 <= cols <= 200):
            raise ValueError(
                f"a table of {rows}x{cols} is out of range (rows 2..500, cols 2..200)")
        self._t.resize(rows, cols)
        self._commit()

    def insert_row(self, at: int):
        # inserting is legal one past the end, hence the extra
        self._bounds(r=at, r_max_extra=1)
        if at == 0:
            raise ValueError("row 0 holds the stock names; insert below it")
        self._t.insertRow(at); self._commit()

    IC_CLEARED = "0"

    def delete_row(self, at: int):
        self._bounds(r=at)
        if at == 0:
            raise ValueError("row 0 holds the stock names and cannot be deleted")
        if self._t.rows() <= 2:
            raise ValueError("a Godley table needs its header and initial-conditions rows")
        if self._t.initialConditionRow(at):
            # The guard above only counted rows, so on a table with extra flow rows the
            # initial-conditions row itself could be deleted. The engine goes on
            # reporting the initial values it holds, so the app kept telling the user the
            # model opened at 100 with nothing on screen saying so.
            raise ValueError(
                "that row holds the initial conditions and cannot be deleted -- clear "
                "its cells instead if you want them empty")
        self._t.deleteRow(at); self._commit()

    def insert_col(self, at: int):
        self._bounds(c=at, c_max_extra=1)
        if at == 0:
            raise ValueError("column 0 holds the flow labels; insert to the right of it")
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
        self._bounds(c=at)
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
        # Minsky's own default epsRel is 1e-2, which produces NaN on stiff models and
        # then reports success. A NEW model gets sane tolerances; a LOADED one keeps
        # whatever its file specifies.
        self.configure()
        return self

    def _place(self, at):
        """A free slot, measured against the ENGINE's items.

        This used to index a grid by `len(self.items)`, a counter over our own list, which
        drifts from the model the moment anything is deleted or undone: add three, delete
        one, add another, and the new item lands EXACTLY on top of an existing one. That
        matters because delete, rename and wire-removal all resolve their target by
        position -- with two items at the same point the engine's hit test picks one
        arbitrarily, so the wrong item is acted on intermittently.
        """
        taken_now = [(self.minsky.model.items[i].x(), self.minsky.model.items[i].y())
                     for i in range(len(self.minsky.model.items))]
        if at is not None:
            # An explicit position is honoured, but never ON TOP of something. The client
            # picks placement because only it knows what is visible, and two adds in
            # quick succession both measure the same model and choose the same point.
            # Two items at one point are ambiguous to the engine's hit test, and delete,
            # rename and wire removal all resolve their target by position -- so from
            # then on those operations act on whichever of the two the engine picks.
            x, y = float(at[0]), float(at[1])
            for ring in range(24):
                for dx, dy in ((0, 0), (self.DX, 0), (0, self.DY), (self.DX, self.DY),
                               (-self.DX, 0), (0, -self.DY)):
                    px, py = x + dx * ring, y + dy * ring
                    if all(abs(tx - px) > self.COINCIDENT or abs(ty - py) > self.COINCIDENT
                           for tx, ty in taken_now):
                        return (px, py)
            return (x, y)
        taken = taken_now
        for row in range(200):
            for col in range(self.COLS):
                x = self.X0 + col * self.DX
                y = self.Y0 + row * self.DY
                if all(abs(tx - x) > self.DX * 0.5 or abs(ty - y) > self.DY * 0.5
                       for tx, ty in taken):
                    return (x, y)
        return (self.X0, self.Y0)

    #: two items closer than this are ambiguous to the engine's hit test
    COINCIDENT = 6.0

    def _unique_at(self, item: Item, what: str):
        """Refuse a positional operation when another item shares the spot.

        delete, rename and wire removal all focus their target with getItemAt, which
        resolves by position. If two items overlap the engine picks one arbitrarily, so
        acting would corrupt the model silently and non-deterministically. Refusing is
        the only safe answer, and it is actionable: move one of them.
        """
        item.refresh()
        raw = item._raw
        x, y = raw.x(), raw.y()
        clashes = 0
        for i in range(len(self.minsky.model.items)):
            if i == item.index:
                continue
            o = self.minsky.model.items[i]
            if abs(o.x() - x) < self.COINCIDENT and abs(o.y() - y) < self.COINCIDENT:
                clashes += 1
        if clashes:
            raise RuntimeError(
                f"cannot {what}: {clashes} other item(s) sit at the same point "
                f"({x:.0f},{y:.0f}), and the engine resolves this by position, so it "
                f"could act on the wrong one. Drag them apart first.")

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
        # every type reports as "Variable:<kind>" except a constant, which the engine
        # gives its own class -- checking for "Variable:constant" rejected a variable it
        # had just created perfectly well
        expect = "VarConstant" if kind == "constant" else f"Variable:{kind}"
        return self._adopt(f"var:{kind}", name, at, expect=expect)

    def constant(self, value: float, at=None) -> Item:
        """A literal constant. Its NAME is its value -- `init("3.5")` sets both.

        So a constant has no name to give it, and passing one silently produced a
        nameless item. The value has to go in through `init`, not `set_init`: the engine
        keys constants as "constant:N", not by name.
        """
        it = self.variable(str(value), "constant", at)
        self.minsky.model.items[it.index].init(repr(float(value)))
        return it

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

    def value_id(self, name: str) -> str:
        """The key `variableValues` actually stores a variable under.

        It is NOT ":name". Minsky MANGLES the name into the id -- `alpha_1` becomes
        `:alpha<sub>1</sub>`, `r^2` becomes `:r<sup>2</sup>`, a space becomes U+2423 --
        so writing to ":alpha_1" created a phantom entry and the real variable kept 0.
        Every parameter whose name contained an underscore, a caret or a space silently
        had no value, which is most of them in an economic model (`C_D`, `I_D`, `w_s`).
        """
        # Every item at every depth. This walked only model.items, so a variable inside
        # a GROUP never matched and the fallback wrote to ":name" -- a key no variable
        # uses. Setting the value reported success and changed nothing.
        for _ref, it in self.all_raw():
            if not it.classType().startswith("Variable:"):
                continue
            try:
                if it.name() == name or it.rawName() == name:
                    return it.valueId()
            except Exception:
                continue
        raise ValueError(
            f"no variable called {name!r} in this model. Its value cannot be set, and "
            f"writing to a name nothing uses would look like it had worked.")

    def set_init(self, name: str, value) -> None:
        """Initial value / parameter value. Minsky wants this as a STRING expression."""
        self.minsky.variableValues[self.value_id(name)].init(str(value))

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
        self._unique_at(item, "delete this item")
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
        """Move an item. Verified -- some items do not own their own position.

        A Godley table places the stock and flow variables it generates, so `moveTo` on
        one of those returns without error and changes nothing. That was reported as
        success, and still marked the document unsaved and pushed an undo point for an
        edit that had not happened.
        """
        item.move_to(x, y)
        # moveTo does set the position -- and then the owning GodleyIcon's
        # updateBoundingBox() puts it straight back, which is what the next snapshot
        # runs. Checking before that happens saw the move "succeed" and the user saw the
        # item where it started. Settle first, so the check sees what the user will.
        for _ref, r in self.all_raw():
            try:
                r.updateBoundingBox()
            except Exception:
                pass
        raw = item._raw
        if abs(raw.x() - x) > 1.0 or abs(raw.y() - y) > 1.0:
            raise RuntimeError(
                f"that item did not move: it is at ({raw.x():.0f},{raw.y():.0f}), not "
                f"({x:.0f},{y:.0f}). A Godley table places the variables it generates, "
                f"so they can only be moved by moving the table.")

    def ungroup(self, gref) -> int:
        """Dissolve a TOP-LEVEL group, leaving its contents as ordinary items.

        Only a top-level one. `canvas.getItemAt` searches the model the canvas is pointed
        at and never descends into a group, so asking it to focus a NESTED group silently
        focused the enclosing one and `ungroupItem()` dissolved that instead -- answering
        200, reporting a count, and leaving the group the caller named still a group.
        The guard did not catch it because the total group count fell either way.

        There is a way in, and it is to peel from the outside: dissolving the outer group
        re-roots the inner one at the top level, where it can be dissolved in turn.
        """
        path = str(gref)[1:] if str(gref).startswith("g") else str(gref)
        node = self.minsky.model
        for part in path.split("."):
            n = len(node.groups)
            if not (part.isascii() and part.isdigit()) or not 0 <= int(part) < n:
                raise IndexError(f"group {gref} out of range" if n
                                 else "this model has no groups")
            node = node.groups[int(part)]
        if "." in path:
            outer = "g" + path.rsplit(".", 1)[0]
            title = ""
            try:
                title = (self._group_at(path.rsplit(".", 1)[0]).title() or "").strip()
            except Exception:
                pass
            raise ValueError(
                f"{gref} is inside another group, and only a top-level group can be "
                f"dissolved -- the canvas cannot focus one that is nested. Ungroup "
                f"{(repr(title) + ' (' + outer + ')') if title else outer} first; that "
                f"leaves {gref} at the top level, where it can be dissolved in turn.")

        g = node
        inner = len(g.items)
        # Count groups at EVERY depth. Dissolving a group re-roots any sub-groups it
        # held, so the top-level count does not fall -- but the model holds exactly one
        # group fewer, wherever the survivors end up.
        before_groups = self._count_groups()
        if not self.minsky.canvas.getItemAt(g.x(), g.y()):
            raise RuntimeError(
                f"no item found at the group's own coordinates "
                f"({g.x():.1f},{g.y():.1f}) -- cannot focus it to ungroup it")
        before = len(self.minsky.model.items)
        self.minsky.canvas.ungroupItem()
        gained = len(self.minsky.model.items) - before
        if self._count_groups() != before_groups - 1:
            raise RuntimeError(
                "ungrouping did not remove exactly the group asked for. The canvas hit "
                "test may have focused a different item that overlaps it.")
        return gained if gained > 0 else inner

    def _group_at(self, path: str):
        node = self.minsky.model
        for part in path.split("."):
            node = node.groups[int(part)]
        return node

    def _count_groups(self) -> int:
        """Groups at every depth -- a nested one does not change the top-level count."""
        def walk(node):
            return len(node.groups) + sum(walk(node.groups[i])
                                          for i in range(len(node.groups)))
        return walk(self.minsky.model)

    #: Item classes that carry a user-visible name worth renaming. An operation accepts
    #: a rename call and does nothing with it, so offering one would be a lie.
    RENAMEABLE = ("Variable:", "GodleyIcon")

    def all_raw(self):
        """Every item in the model, at every depth, as (ref, raw).

        Group members live at `groups[g].items[i]`, not in `model.items`, and groups
        nest -- so this recurses, or a rename would miss the icons in a nested group and
        split the variable it was trying to rename.
        """
        for i in range(len(self.minsky.model.items)):
            yield str(i), self.minsky.model.items[i]

        def walk(node, path):
            for gi in range(len(node.groups)):
                grp = node.groups[gi]
                ref = "g" + ".".join(path + [str(gi)])
                for i in range(len(grp.items)):
                    yield f"{ref}:{i}", grp.items[i]
                yield from walk(grp, path + [str(gi)])
        yield from walk(self.minsky.model, [])

    def icons_of(self, vid: str):
        """Every icon that refers to the variable `vid`, wherever it lives."""
        out = []
        for ref, raw in self.all_raw():
            try:
                if raw.classType().startswith("Variable") and raw.valueId() == vid:
                    out.append((ref, raw))
            except Exception:
                continue
        return out

    def rename(self, item: Item, new: str) -> str:
        """Rename a variable everywhere, or retitle a Godley table. Verified.

        `renameItem` renames only THIS icon, which SPLITS a shared variable into two --
        two icons of `alpha` become `alpha` and `beta`, and the model gains a variable.
        `renameAllInstances` renames the variable itself, which is what "rename" means to
        someone looking at one of its icons, and is what this does. The value carries
        across: a parameter of 2.5 renamed still reads 2.5 after a reset.
        """
        new = new.strip()
        if not new:
            raise ValueError("a name cannot be empty")
        item.refresh()
        raw = item._raw
        ct = raw.classType()

        if "Godley" in ct:                      # a table's name is its title
            raw.table.title(new)
            self.minsky.model.items[item.index].update()
            return new

        if not ct.startswith("Variable:"):
            raise ValueError(
                f"{ct} has no name to change. Only variables, parameters and Godley "
                f"tables can be renamed.")

        # `renameAllInstances` renames the variable the CANVAS is focused on, and
        # focusing is done by position -- so it could not reach a variable inside a
        # group (the hit test resolves to the group itself, never its contents), and it
        # had to refuse any variable sharing a point with another.
        #
        # Setting `name()` on an icon renames only THAT icon, which SPLITS a shared
        # variable in two. But every icon of a variable can be found by its valueId,
        # anywhere in the model, so renaming all of them does the same job with no
        # dependence on where anything sits. Verified: one valueId afterwards, the
        # initial value carries across, and the model still resets.
        was = (raw.name() or "").strip()
        vid = raw.valueId()
        targets = self.icons_of(vid)
        if not targets:
            raise RuntimeError(f"no icon of {was!r} could be found to rename")
        for _ref, r in targets:
            r.name(new)
        got = item._raw.name()

        # The engine CANONICALISES names: it LaTeX-escapes "%", "#" and "&", and strips a
        # leading ":" (the global-namespace marker). Comparing literally called every one
        # of those a failure -- the caller got a 400 saying the rename had not happened
        # while looking at a canvas where it plainly had. So judge by whether the name
        # MOVED, and hand back what it actually became.
        if got.strip() == was and was != new:
            raise RuntimeError(
                f"rename to {new!r} left the item called {got!r}")
        return got

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
