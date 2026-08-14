"""Tests for the headless model-building layer.

Each test builds a model whose answer is known analytically, so a silently mis-wired
model fails loudly instead of producing plausible numbers.
"""
import math
import sys
from minskyweb.headless import Model, WiringError

def fresh() -> Model:
    """A clean document in THE engine. pyminsky is a singleton, so there is only one:
    constructing a second Model now raises rather than silently wiping the first."""
    return Model.current().clear()

FAILED = []
def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not cond: FAILED.append(name)

def integrate_to(m, tmax, cap=2000):
    m.configure(); m.reset(); m.minsky.tmax(tmax)
    n = 0
    while m.minsky.t() < tmax and n < cap:
        m.minsky.step(); n += 1
    return m.minsky.t()

print("1. exponential growth  dS/dt = r*S   (feedback loop + 2-input operation)")
m = fresh()
r, mul, itg = m.parameter('r', 0.10), m.operation('multiply'), m.operation('integrate')
m.wire(r, mul, 1); m.wire(mul, itg, 1); m.wire(itg, mul, 2)
m.set_init('int1', 1.0)
t = integrate_to(m, 5.0)
S, exact = m.value('int1'), math.exp(0.10 * t)
check("matches exp(rt)", abs(S - exact) / exact < 1e-8, f"rel err {abs(S-exact)/exact:.2e}")
check("wire count", len(m.minsky.model.wires) == 3, m.summary())

print("\n2. linear ramp  dS/dt = c   (constant integrand)")
m = fresh()
c, itg = m.parameter('c', 2.5), m.operation('integrate')
m.wire(c, itg, 1); m.set_init('int1', 0.0)
t = integrate_to(m, 4.0)
check("matches c*t", abs(m.value('int1') - 2.5 * t) < 1e-8,
      f"{m.value('int1'):.6f} vs {2.5*t:.6f}")

print("\n3. wiring errors are RAISED, not silent")
m = fresh()
a, b = m.parameter('a', 1.0), m.variable('y', 'flow')
try:
    m.wire(a, b, 0); check("input port 0 rejected", False)
except WiringError as e:
    check("input port 0 rejected", "OUTPUT" in str(e))
stock = m.variable('s', 'stock')
try:
    m.wire(a, stock, 1); check("stock has no input port", False)
except WiringError as e:
    check("stock has no input port", "no input port" in str(e))
m.wire(a, b, 1)
try:
    m.wire(a, b, 1); check("double-wiring one input detected", False)
except WiringError as e:
    check("double-wiring one input detected", "expected 1" in str(e))

print("\n4. stale port coordinates cannot cause a silent no-op")
m = fresh()
p, v = m.parameter('p', 1.0), m.variable('q', 'flow')
p._raw.moveTo(900, 900)          # move behind the wrapper's back -> boxes now stale
m.wire(p, v, 1)                  # must still work: wire() refreshes before reading
check("wire survives an out-of-band move", len(m.minsky.model.wires) == 1)

print("\n5. save / load round-trip")
m = fresh()
r, mul, itg = m.parameter('r', 0.20), m.operation('multiply'), m.operation('integrate')
m.wire(r, mul, 1); m.wire(mul, itg, 1); m.wire(itg, mul, 2)
m.set_init('int1', 3.0)
n_items, n_wires = len(m.minsky.model.items), len(m.minsky.model.wires)
m.save('/tmp/mk_headless_rt.mky')
m2 = fresh(); m2.minsky.load('/tmp/mk_headless_rt.mky')
check("items preserved", len(m2.minsky.model.items) == n_items)
check("wires preserved", len(m2.minsky.model.wires) == n_wires)
t = integrate_to(m2, 3.0)
S, exact = m2.value('int1'), 3.0 * math.exp(0.20 * t)
check("reloaded model still correct", abs(S - exact) / exact < 1e-8,
      f"rel err {abs(S-exact)/exact:.2e}")

print("\n6. sane solver defaults are applied (Minsky ships epsRel=1e-2)")
m = fresh(); m.configure()
check("epsRel tightened", m.minsky.epsRel() <= 1e-8, f"epsRel={m.minsky.epsRel()}")
check("implicit solver on", m.minsky.implicit() is True)

print(f"\n{'ALL PASS' if not FAILED else 'FAILURES: ' + ', '.join(FAILED)}")
sys.exit(1 if FAILED else 0)
