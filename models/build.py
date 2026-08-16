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

    def __init__(self):
        self.ref = {}          # name -> ref of the item whose OUTPUT carries that name
        self._x = 120.0        # a rough placement cursor; Tidy fixes it properly later
        self._y = 120.0
        self._col = 0

    # ---------- placement ----------
    def _at(self):
        """Somewhere free-ish. The real layout comes from /api/layout at the end."""
        x, y = self._x, self._y
        self._y += 72
        if self._y > 2600:
            self._y = 120
            self._x += 240
        return [x, y]

    # ---------- items ----------
    def _add(self, spec):
        spec.setdefault("at", self._at())
        return str(api("/api/item", spec)["index"])

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
        self.ref[name] = var
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
