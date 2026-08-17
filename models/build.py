"""Build a Minsky model from algebra, over the HTTP API.

Minsky is a wiring diagram: an equation is a little subgraph of operation blocks feeding
a named variable. Writing 25 equations by hand as ~150 wire calls is how you get a model
that is wrong in a way nobody can see. So this module compiles

    eq("r", "(1 - omega) * Y / K")

into the blocks and wires Minsky would have had you draw, and keeps a registry of what
each name resolves to.

Why not a user function, which would take the whole expression as text? Because a
UserFunction that references a model variable BY NAME evaluates correctly at reset and
then returns 0 for essentially every step of the run, on both solvers, with no error
anywhere -- measured, see docs/MINSKY_HEADLESS.md. Wired blocks integrate exactly
(relative error 4e-12 against an analytic solution), so that is what this emits.
"""
import ast
import json
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8800"

#: Python operator -> Minsky operation block.
BINOPS = {ast.Add: "add", ast.Sub: "subtract", ast.Mult: "multiply",
          ast.Div: "divide", ast.Pow: "pow"}
#: Calls we allow, and the Minsky block each becomes.
CALLS = {"min": "min", "max": "max", "exp": "exp", "ln": "ln", "log": "log",
         "sqrt": "sqrt", "abs": "abs"}


class BuildError(Exception):
    pass


def api(path, body=None, method="POST"):
    data = json.dumps(body).encode() if body is not None else (
        b"" if method == "POST" else None)
    rq = urllib.request.Request(BASE + path, data=data, method=method,
                                headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(rq) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            detail = json.loads(raw).get("detail", raw.decode()[:200])
        except Exception:
            detail = raw.decode()[:200]
        raise BuildError(f"{method} {path} -> {e.code}: {detail}") from None


class Builder:
    """Places items, compiles equations, and remembers what every name refers to."""

    # Placement works on RECTANGLES, using the w and h the engine reports for every item.
    # It used to use a single scalar clearance, which is wrong in both directions at once:
    # an Operation icon is 29x26 and a PlotWidget is 151x151, so one number is either too
    # mean for the plots or absurdly wasteful for the operations. Measured on the term
    # structure model: Operation 29x26, VarConstant 37x22, Variable 36-80 x 26-28,
    # IntOp 81-121 x 44, PlotWidget 151x151. Godley tables are larger again.
    PAD = 14.0             # breathing room between two icons
    NEW_W, NEW_H = 130.0, 60.0   # generous box for whatever is about to be placed; the
    #                              real size is not known until the engine has made it

    def __init__(self):
        self.ref = {}          # name -> ref of the item whose OUTPUT carries that name
        self.integral = {}     # name -> the integral's OWN icon, which must not be wired
        self._x = 120.0        # a rough placement cursor; Tidy fixes it properly later
        self._y = 120.0
        self._col = 0
        self._taken = []       # every position known to be occupied, engine's included

    # ---------- placement ----------
    def _step(self):
        self._y += 120
        if self._y > 2600:
            self._y = 120
            self._x += 400

    def _free(self, x, y):
        """Would a NEW_W x NEW_H box centred here overlap anything already placed?"""
        for px, py, pw, ph in self._taken:
            if (abs(x - px) * 2 < self.NEW_W + pw + 2 * self.PAD
                    and abs(y - py) * 2 < self.NEW_H + ph + 2 * self.PAD):
                return False
        return True

    def _at(self):
        """Somewhere genuinely free. The real layout comes from /api/layout at the end.

        This used to be a blind cursor, and that was a real bug rather than a cosmetic
        one: `stock()` asks the engine for an integral, and the ENGINE places a second
        icon -- the integral's output variable -- wherever it likes. The cursor never knew
        about those, so on a big enough model it would eventually march an operation right
        on top of one, and the next `addWire` would be refused with "those two ports cannot
        be connected ... and that the items do not overlap". The failure surfaces as a
        wiring error several equations later, which points nowhere near the cause.
        """
        guard = 0
        while not self._free(self._x, self._y) and guard < 4000:
            self._step()
            guard += 1
        x, y = self._x, self._y
        self._taken.append((x, y, self.NEW_W, self.NEW_H))
        self._step()
        return [x, y]

    def _note_engine_items(self):
        """Re-read positions and sizes with an explicit GET.

        Only worth calling when something may have moved WITHOUT going through _add --
        _add already refreshes from its own response, so the normal build path never
        needs this.

        The size fields are `w` and `h`, not `width`/`height` -- an earlier version of this
        looked for the latter, found nothing, and silently fell back to treating every icon
        as a point. That matters most for the two biggest things on a canvas: a PlotWidget
        is 151x151 and a Godley table is larger again, so a cursor that thinks they are
        points will march straight through them on a model with a few hundred items.

        This REPLACES the record rather than appending to it, because the engine moves
        items after creation and a stale entry would fence off ground that is now free.
        """
        self._absorb(api("/api/state", method="GET")["items"])

    # ---------- items ----------
    def _add(self, spec):
        """Place an item, and refresh the occupancy map from the SAME response.

        `POST /api/item` already answers with the whole state snapshot, so the map costs
        nothing extra here. Fetching it separately once per equation instead made the
        builder quadratic -- measured at 688ms, 1701ms and 2843ms per equation over the
        first, second and third ten equations of a model, i.e. one extra full round trip
        whose payload grows with every item placed.
        """
        spec.setdefault("at", self._at())
        resp = api("/api/item", spec)
        state = resp.get("state")
        if state and state.get("items"):
            self._absorb(state["items"])
        return str(resp["index"])

    def _absorb(self, items):
        """Replace the occupancy map from an engine snapshot, positions AND sizes."""
        self._taken = [(float(i["x"]), float(i["y"]),
                        float(i.get("w") or self.NEW_W), float(i.get("h") or self.NEW_H))
                       for i in items if i.get("x") is not None and i.get("y") is not None]

    def param(self, name, value, *, slider=None):
        """A named constant the user can pull on."""
        r = self._add({"kind": "parameter", "name": name, "value": value})
        self.ref[name] = r
        if slider:
            lo, hi = slider
            api(f"/api/item/{r}/attrs", {"sliderMin": lo, "sliderMax": hi})
        return r

    def stock(self, name, init):
        """An integral: a state variable whose derivative is wired in.

        Returns the IntOp ref, which is what a derivative gets wired INTO. The integral's
        output variable is registered under `name`, so equations can read it.
        """
        before = {i["ref"] for i in api("/api/state", method="GET")["items"]}
        iop = self._add({"kind": "operation", "op": "integrate"})
        after = api("/api/state", method="GET")["items"]
        var = next(i["ref"] for i in after
                   if i["ref"] not in before and i["classType"] == "Variable:integral")
        api(f"/api/item/{var}/rename", {"name": name})
        api("/api/init", {"name": name, "value": init})
        self.integral[name] = var
        # READS GO THROUGH A COPY, and they have to.
        #
        # A wire is made by dragging on the canvas: mouseDown on the source's output port,
        # mouseUp on the destination's input. An integral's own icon shares its output
        # port with its IntOp -- both report port 0 at the same pixel -- so the mouseDown
        # can land on the operation body and DRAG IT instead of starting a wire. The
        # symptom is baffling from the outside: `addWire` is refused with the generic
        # "those two ports cannot be connected ... items do not overlap", the refusal is
        # unaffected by moving the destination hundreds of pixels away, and the only
        # trace is that the IntOp has quietly moved to where the drag dropped it. Whether
        # it happens at all depends on which icon the canvas picks at that pixel, so the
        # same expression can build in one model and fail in the next.
        #
        # Minsky's own answer to this is already recorded in scan(): place an ORDINARY
        # copy of the variable and wire that. Same name means the same value, so the copy
        # reads the integral.
        # The copy must declare the SAME type the integral already registered under that
        # name -- "integral", not "stock" -- or the engine refuses to create it at all.
        reader = self._add({"kind": "variable", "name": name, "var_type": "integral"})
        self.ref[name] = reader
        self._note_engine_items()
        return iop

    def flow(self, name):
        """A flow variable, reusing the icon a Godley table already made for it.

        Naming a variable in a Godley cell creates it, so by the time the equations are
        built the flows the tables use already exist. Adding a second icon would be
        legal -- Minsky shares the value by name -- but then two icons of one variable
        sit on the canvas and only one carries the definition, which reads as a mistake.
        """
        if name in self.ref:
            return self.ref[name]
        r = self._add({"kind": "variable", "name": name, "var_type": "flow"})
        self.ref[name] = r
        return r

    def scan(self):
        """Take stock of what the Godley tables created, and place working copies.

        A table draws its own icon for every stock column and every flow row, but those
        icons are display only: the engine refuses a wire out of one, and refuses a wire
        into one with "Godley table variables cannot be wired into from outside". The way
        Minsky's own models do it is to place ORDINARY copies of the variable elsewhere
        and wire those -- in LoanableFunds every flow has one icon wired into it and
        several plain copies feeding other blocks.

        So: a reader copy is placed for each stock, and the flows are deliberately left
        unregistered, so that eq() creates the icon that defines each one.
        """
        self.valueId = {}
        attached = {}
        for i in api("/api/state", method="GET")["items"]:
            nm = i.get("name")
            if nm and i["classType"].startswith("Variable"):
                attached.setdefault(nm, i["classType"])
                self.valueId[nm] = i.get("valueId")
        self.godley_names = set(attached)
        for nm, kind in attached.items():
            if kind == "Variable:stock":
                self.ref[nm] = self._add({"kind": "variable", "name": nm,
                                          "var_type": "stock"})
        return self.ref

    def value_ids(self):
        """name -> valueId, for reading results out of a run's frames.

        Collected after everything is built: `scan` runs before the states and the
        equations exist, so its map covers only what the tables made.
        """
        out = {}
        for i in api("/api/state", method="GET")["items"]:
            if i.get("name") and i["classType"].startswith("Variable"):
                out.setdefault(i["name"], i.get("valueId"))
        self.valueId = out
        return out

    def const(self, value):
        return self._add({"kind": "variable", "var_type": "constant", "value": value})

    def godley(self, title, rows, cols):
        r = self._add({"kind": "godley", "name": title})
        api(f"/api/godley/{r}/resize", {"rows": rows, "cols": cols})
        return r

    def plot(self, title, left, right=(), at=None):
        """A chart. `left` and `right` are variable names, one series each.

        A plot is born with room for ONE line -- one series per axis -- so the count has
        to be set before the series can be wired. With N lines the y ports run 6..6+2N-1:
        the first N are the left axis, the next N the right.
        """
        n = max(len(left), len(right), 1)
        r = self._add({"kind": "plot", "at": at or self._at()})
        api(f"/api/item/{r}/attrs", {"numLines": n})
        api(f"/api/item/{r}/rename", {"name": title})
        for k, nm in enumerate(left):
            self.wire(self.ref[nm], r, 6 + k)
        for k, nm in enumerate(right):
            self.wire(self.ref[nm], r, 6 + n + k)
        return r

    def wire(self, src, dst, port):
        api("/api/wire", {"src": src, "dst": dst, "port": port})

    # ---------- equations ----------
    def eq(self, name, expr):
        """Define flow variable `name` as `expr`, emitting the blocks and the wires."""
        try:
            tree = ast.parse(expr, mode="eval").body
        except SyntaxError as ex:
            raise BuildError(f"{name}: cannot parse {expr!r}: {ex}") from None
        try:
            src = self._compile(tree, name)
        except BuildError as ex:
            raise BuildError(f"while building {name} = {expr}: {ex}") from None
        var = self.flow(name)
        self.wire(src, var, 1)
        return var

    def _compile(self, node, ctx):
        """Emit blocks for `node`; return the ref whose port 0 carries its value."""
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)):
                raise BuildError(f"{ctx}: {node.value!r} is not a number")
            return self.const(float(node.value))

        if isinstance(node, ast.Name):
            if node.id not in self.ref:
                raise BuildError(
                    f"{ctx}: {node.id!r} is not defined yet. Minsky wires values "
                    f"forward, so every name must exist before it is used.")
            return self.ref[node.id]

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            # no unary minus block: 0 - x
            op = self._add({"kind": "operation", "op": "subtract"})
            self.wire(self.const(0.0), op, 1)
            self.wire(self._compile(node.operand, ctx), op, 2)
            return op

        if isinstance(node, ast.BinOp):
            kind = BINOPS.get(type(node.op))
            if not kind:
                raise BuildError(f"{ctx}: {type(node.op).__name__} is not available")
            op = self._add({"kind": "operation", "op": kind})
            self.wire(self._compile(node.left, ctx), op, 1)
            self.wire(self._compile(node.right, ctx), op, 2)
            return op

        if isinstance(node, ast.Call):
            fn = getattr(node.func, "id", None)
            if fn not in CALLS:
                raise BuildError(f"{ctx}: {fn!r} is not one of {sorted(CALLS)}")
            op = self._add({"kind": "operation", "op": CALLS[fn]})
            for k, arg in enumerate(node.args):
                self.wire(self._compile(arg, ctx), op, k + 1)
            return op

        raise BuildError(f"{ctx}: {ast.dump(node)[:60]} is not supported")
