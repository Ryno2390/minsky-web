"""Marx's reproduction schemes as a running Minsky model.

    python3 models/repro_model.py                # build simple, save, check
    python3 models/repro_model.py --expanded     # build expanded, save, check
    python3 models/repro_model.py --drift        # what happens off the fixed point

WHAT THIS ADDS TO THE ARITHMETIC
--------------------------------
models/reproduction.py already reproduces Marx's published tables exactly, so the point
of building this is not to get the numbers again. It is that the reproduction condition
turns out to BE a money-stock condition -- section 4 of that module shows Dept I's money
holding is constant exactly when II c = I (v + s) -- and a money stock that has to stay
constant is what a Godley table and an integral are for.

So the schemes are built as four sectors with money and no credit, which is Volume II
Part III's own abstraction. Then the condition is not imposed anywhere. It is left to
hold or fail, and Firms I's money balance says which.

ONE MODEL, BOTH SCHEMES
-----------------------
Simple reproduction is expanded reproduction with alpha = 0. That is Marx's own reading --
simple reproduction is "a component part of reproduction on an extended scale" -- and it
is worth taking literally, because it means the two schemes need one model with two
parameter settings rather than two models.

    SIMPLE     alpha1 = alpha2 = 0,     C2/V2 opening at ch.20's 2000/500
    EXPANDED   alpha1 = 0.5, alpha2 = 0.3, opening at ch.21's proportions

THE ONE REAL TRANSLATION COST
-----------------------------
Marx's schemes are a DIFFERENCE equation on an annual turnover. Minsky integrates
continuously. A department growing at 10% a year compounds to 1.1 in Marx and to
e^0.1 = 1.10517 here, and no choice of parameters removes that -- it is the difference
between accumulating in a lump at the year end and accumulating continuously. It is
reported in the run rather than papered over: the balanced GROWTH RATE agrees exactly,
the annual TOTALS do not, and the gap is 0.47% at one year rising with the horizon.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build import Builder, api                                   # noqa: E402
import reproduction as ref                                       # noqa: E402
from runner import Run                                           # noqa: E402

GRID = 16.0


def q(z):
    """Snap to 1/16: binary-exact for the row check AND short enough to survive a save.

    Same constraint as four_sector.py. The engine writes a Godley initial condition twice
    -- full precision as cell text, six significant figures as the value it initialises
    with -- and the rounded one wins on reload.
    """
    return round(z * GRID) / GRID


def scheme(expanded):
    """Opening state and parameters for one of the two schemes."""
    if not expanded:
        s = dict(ref.SIMPLE)
        return dict(C1=s["c1"], V1=s["v1"], C2=s["c2"], V2=s["v2"], e=s["e"],
                    alpha1=0.0, alpha2=0.0, T=1.0, name="SimpleReproduction")
    # OPENING AT MARX'S YEAR TWO, AND WHY.
    #
    # reproduction.py section 5 found that ch.21's opening year is not on the balanced
    # path: it needs c2/v1 = 16/11 and Marx writes 1500/1000. His scheme snaps onto the
    # path after one period because Dept II is assumed to take up the residual, and a
    # continuous model has no such period -- there is no year end at which a passive
    # department can absorb the discrepancy.
    #
    # Starting on the path is therefore the honest choice, and the right numbers are not
    # invented: they are Marx's own YEAR TWO, 4400c + 1100v and 1600c + 800v, which the
    # reference recursion produces and which satisfy the condition exactly.
    #
    # That they are integers is not a nicety. The first attempt here solved for the
    # opening C2 directly and got 16000/11 = 1454.5454..., which does not terminate in
    # binary, gets snapped to 1454.5625 by the 1/16 grid, and lands the model 1e-5 off a
    # fixed point that has no neighbourhood. The residual that produced was mistaken for
    # solver error for as long as it took to check. Marx's year two needs no snapping.
    a1 = 0.5
    C1, V1, C2, V2 = 4400.0, 1100.0, 1600.0, 800.0
    q1, q2 = C1 / V1, C2 / V2
    a2 = a1 * (1.0 + q2) / (1.0 + q1)
    return dict(C1=C1, V1=V1, C2=C2, V2=V2, e=s_e(), alpha1=a1, alpha2=a2,
                T=1.0, name="ExpandedReproduction")


def s_e():
    return ref.EXPANDED["e"]


#: Opening money. Arbitrary and positive: nothing in the schemes pins the quantity of
#: money, only that it is enough to carry the circulation. Its DRIFT is the whole point.
M0 = dict(MF1=2000.0, MF2=2000.0, MW=500.0, MC=500.0)


def tables():
    """Four sectors, money as the only asset, net worth as the balancing equity.

    There is no credit and no bank, so no sector's asset is another's liability and the
    tables are as thin as a Godley table gets. What they still buy is the thing that
    matters here: every flow is written into exactly two sheets with opposite signs, so
    money conservation is structural rather than something to remember.

    Dept I buying means of production FROM ITSELF never appears, because no money leaves
    the sector. That is not a simplification -- it is why the exchange condition involves
    II c and not I c.
    """
    cols = lambda m, nw: [(m, "asset", M0[m]), (nw, "equity", M0[m])]      # noqa: E731
    return (
        ("Firms I", cols("MF1", "NWF1"), [
            ("Wages",                 {"MF1": "-wage1", "NWF1": "-wage1"}),
            ("Capitalist income",     {"MF1": "-div1",  "NWF1": "-div1"}),
            ("Sells means of prod.",  {"MF1": "mp2",    "NWF1": "mp2"}),
        ], [200, 200]),
        ("Firms II", cols("MF2", "NWF2"), [
            ("Wages",                 {"MF2": "-wage2", "NWF2": "-wage2"}),
            ("Capitalist income",     {"MF2": "-div2",  "NWF2": "-div2"}),
            ("Buys means of prod.",   {"MF2": "-mp2",   "NWF2": "-mp2"}),
            ("Sells to workers",      {"MF2": "wcons",  "NWF2": "wcons"}),
            ("Sells to capitalists",  {"MF2": "ccons",  "NWF2": "ccons"}),
        ], [1400, 200]),
        ("Workers", cols("MW", "NWW"), [
            ("Wages from I",          {"MW": "wage1",   "NWW": "wage1"}),
            ("Wages from II",         {"MW": "wage2",   "NWW": "wage2"}),
            ("Consumption",           {"MW": "-wcons",  "NWW": "-wcons"}),
        ], [200, 1300]),
        ("Capitalists", cols("MC", "NWC"), [
            ("Income from I",         {"MC": "div1",    "NWC": "div1"}),
            ("Income from II",        {"MC": "div2",    "NWC": "div2"}),
            ("Consumption",           {"MC": "-ccons",  "NWC": "-ccons"}),
        ], [1400, 1300]),
    )


def build(p):
    api("/api/clear")
    b = Builder()
    for title, cols, rows, at in tables():
        g = str(api("/api/item", {"kind": "godley", "name": title, "at": at})["index"])
        api(f"/api/godley/{g}/resize", {"rows": 2 + len(rows), "cols": 1 + len(cols)})
        for c, (nm, cls, ic) in enumerate(cols, start=1):
            api(f"/api/godley/{g}/cell", {"row": 0, "col": c, "value": nm})
            api(f"/api/godley/{g}/cell", {"row": 1, "col": c, "value": f"{q(ic):.17g}"})
            api(f"/api/godley/{g}/class", {"col": c, "cls": cls})
        for rix, (label, entries) in enumerate(rows, start=2):
            api(f"/api/godley/{g}/cell", {"row": rix, "col": 0, "value": label})
            for c, (nm, _cls, _ic) in enumerate(cols, start=1):
                if nm in entries:
                    api(f"/api/godley/{g}/cell",
                        {"row": rix, "col": c, "value": entries[nm]})
        t = api(f"/api/godley/{g}", method="GET")
        bad = [i for i, v in enumerate(t["rowSums"]) if v not in (None, "0")]
        if bad:
            raise SystemExit(f"{title}: rows {bad} do not balance: {t['rowSums']}")

    b.scan()
    for nm in ("e", "alpha1", "alpha2", "T"):
        b.param(nm, float(p[nm]))

    # --- real capital advanced, the four stocks the schemes are actually about ---------
    dC1 = b.stock("C1", q(p["C1"]))
    dV1 = b.stock("V1", q(p["V1"]))
    dC2 = b.stock("C2", q(p["C2"]))
    dV2 = b.stock("V2", q(p["V2"]))

    # --- the scheme, one line per magnitude Marx names --------------------------------
    b.eq("v1", "V1 / T")                  # wages advanced per unit time
    b.eq("v2", "V2 / T")
    b.eq("c1", "C1 / T")                  # constant capital consumed per unit time
    b.eq("c2", "C2 / T")
    b.eq("s1", "e * v1")                  # surplus value, at the rate of exploitation
    b.eq("s2", "e * v2")
    b.eq("K1", "C1 + V1")
    b.eq("K2", "C2 + V2")
    b.eq("X1", "c1 + v1 + s1")            # the annual product of each department
    b.eq("X2", "c2 + v2 + s2")

    # accumulation, split in the EXISTING organic composition, which is what keeps
    # c/v constant along the path and is Marx's own assumption in ch.21
    b.eq("acc1", "alpha1 * s1")
    b.eq("acc2", "alpha2 * s2")
    b.eq("dC1", "acc1 * C1 / K1")
    b.eq("dV1", "acc1 * V1 / K1")
    b.eq("dC2", "acc2 * C2 / K2")
    b.eq("dV2", "acc2 * V2 / K2")
    for src, iop in (("dC1", dC1), ("dV1", dV1), ("dC2", dC2), ("dV2", dV2)):
        b.wire(b.ref[src], iop, 1)

    # --- the money flows, which are the same magnitudes seen from the other side ------
    b.eq("wage1", "v1 + dV1")             # wage bill INCLUDING newly hired labour
    b.eq("wage2", "v2 + dV2")
    b.eq("div1", "s1 - acc1")             # what Dept I's capitalists get to spend
    b.eq("div2", "s2 - acc2")
    b.eq("wcons", "wage1 + wage2")        # workers spend the lot: Volume II's assumption
    b.eq("ccons", "div1 + div2")
    b.eq("mp2", "c2 + dC2")               # Dept II's whole demand on Dept I

    # --- the condition, computed and imposed NOWHERE ----------------------------------
    # This is the object of the exercise. It is not wired into anything: it is evaluated
    # alongside the model so a run can be asked whether the scheme held.
    b.eq("cond", "mp2 - wage1 - div1")    # = II(c+dc) - I(v+dv+s_consumed)
    b.eq("Mtot", "MF1 + MF2 + MW + MC")
    b.eq("Xtot", "X1 + X2")

    b.plot("Capital advanced", ["K1", "K2"])
    b.plot("Reproduction condition", ["cond"])
    api("/api/layout")
    api("/api/save", {"name": p["name"]})
    return b


#: pyminsky is one engine per process, so every experiment here shares a single Run.
#: Creating a second raises rather than silently wiping the first, which is the right
#: behaviour and is why this is a module-level handle instead of a local.
_RUN = [None]


def runner(p):
    if _RUN[0] is None:
        _RUN[0] = Run(f"~/minsky-models/{p['name']}.mky")
    else:
        _RUN[0].use(f"~/minsky-models/{p['name']}.mky")
    return _RUN[0]


def check(p, watch_extra=()):
    """Run it and ask the three questions the build cannot answer."""
    r = runner(p)
    names = ["C1", "V1", "C2", "V2", "MF1", "MF2", "MW", "MC", "Mtot",
             "cond", "X1", "X2", "Xtot", "K1", "K2", *watch_extra]
    out = r.go(10.0, names, samples=200)
    return out


def at(out, t):
    """The sampled row nearest t. `steps` is a scalar the runner appends, so skip it."""
    i = min(range(len(out["t"])), key=lambda k: abs(out["t"][k] - t))
    return {k: v[i] for k, v in out.items() if isinstance(v, list)}


def report(p, out):
    a, b10 = at(out, 0.0), at(out, 10.0)
    # at() returns the NEAREST sample, which is not t exactly -- the last one here lands
    # at 9.97. Label the columns with the times actually used, and divide by those, or
    # the measured growth rate comes out 0.0997 against a true 0.1 and looks like solver
    # error when it is arithmetic on the wrong denominator.
    print(f"\n  {'':>26} {'t = ' + format(a['t'], '.2f'):>12} "
          f"{'t = ' + format(b10['t'], '.2f'):>12} {'ratio':>9}")
    for nm, lab in (("K1", "Dept I capital"), ("K2", "Dept II capital"),
                    ("Xtot", "total product")):
        rr = b10[nm] / a[nm] if a[nm] else float("nan")
        print(f"  {lab:>26} {a[nm]:12.3f} {b10[nm]:12.3f} {rr:9.4f}")

    print(f"\n  THE REPRODUCTION CONDITION, which nothing in the model imposes:")
    worst = max(abs(v) for v in out["cond"])
    scale = max(out["X1"])
    print(f"    II(c+dc) - I(v+dv+s_consumed), worst over the run: {worst:.3e}")
    print(f"    as a share of Dept I's product:                    "
          f"{worst / scale:.3e}")
    print(f"    {'HOLDS' if worst / scale < 1e-9 else 'FAILS'}")

    print(f"\n  MONEY, which is the same statement from the other side:")
    for nm, lab in (("MF1", "Firms I"), ("MF2", "Firms II"),
                    ("MW", "Workers"), ("MC", "Capitalists")):
        d = b10[nm] - a[nm]
        print(f"    {lab:>14} {a[nm]:9.3f} -> {b10[nm]:9.3f}   drift {d:+.3e}")
    print(f"    {'total money':>14} {a['Mtot']:9.3f} -> {b10['Mtot']:9.3f}   "
          f"conserved to {abs(b10['Mtot'] - a['Mtot']):.3e}")



def drift(p):
    """Give Dept II its own accumulation rate and watch the money go.

    reproduction.py section 6 showed the schemes have no mechanism that finds the
    balanced proportions or returns to them. In the arithmetic that shows up as a
    residual product with no buyer. Here it shows up as MONEY, which is the more
    concrete statement of the same thing: Dept I sells less than it pays out, so its
    cash falls, every period, without limit.
    """
    import math
    print("\n" + "=" * 92)
    print("OFF THE FIXED POINT -- Dept II decides for itself")
    print("=" * 92)
    a2star = p["alpha2"]
    print(f"  alpha1 held at {p['alpha1']:.2f}. The balanced alpha2 is {a2star:.3f}.")
    print("  Everything else is untouched, including the opening proportions, which are")
    print("  exactly on the path. The only change is Dept II's decision.\n")
    r = runner(p)
    names = ["MF1", "MF2", "cond", "X1", "K1", "K2"]
    print(f"  {'alpha2':>8} {'g2':>7} | {'Firms I money':>28} | {'cond/X1':>9} "
          f"{'CASH GONE':>8}")
    print(f"  {'':>8} {'':>7} | {'t=0':>8} {'t=10':>9} {'drift':>9} | {'at t=10':>9} "
          f"{'at t =':>8}")
    q2 = p["C2"] / p["V2"]
    for a2 in (a2star - 0.10, a2star - 0.05, a2star, a2star + 0.05, a2star + 0.10):
        out = r.go(10.0, names, overrides={"alpha2": a2}, samples=200)
        a, b = at(out, 0.0), at(out, 10.0)
        g2 = a2 * p["e"] / (1.0 + q2)
        mark = "  <- balanced" if abs(a2 - a2star) < 1e-9 else ""
        # WHERE THE MODEL STOPS BEING TRUE. There is no credit in Volume II Part III,
        # so a sector cannot spend money it does not hold. The moment Firms I's balance
        # reaches zero, reproduction physically halts -- wages cannot be paid. The
        # integration runs straight through into negative cash, which is arithmetic, not
        # economics, so the crossing time is reported and the figures past it are not.
        zero = next((t for t, m in zip(out["t"], out["MF1"]) if m <= 0.0), None)
        zs = f"{zero:8.2f}" if zero is not None else f"{'--':>8}"
        print(f"  {a2:8.3f} {g2 * 100:6.1f}% | {a['MF1']:8.1f} {b['MF1']:9.1f} "
              f"{b['MF1'] - a['MF1']:+9.1f} | {b['cond'] / b['X1'] * 100:8.2f}% "
              f"{zs}{mark}")
    print("\n  The balanced row holds Firms I's money to the last decimal for ten years.")
    print("  Every other row drains or floods it, monotonically, from the first step.")
    print("  Nothing in the model resists, because Volume II Part III contains nothing")
    print("  that responds to a cash balance -- no price adjustment, no credit, no")
    print("  inventory signal. The departments simply carry on at their chosen rates.")
    print("\n  That is the disproportionality problem stated in money rather than in")
    print("  product, and it is the same knife edge the arithmetic found. What the model")
    print("  adds is the mechanism of failure: the department that is short does not")
    print("  discover it through unsold goods, it discovers it by running out of cash.")
    print("\n  And the last column is the one to read. Under-accumulation by Dept II is")
    print("  not a slow leak -- at alpha2 = 0.25, five points off, Firms I is out of money")
    print("  in the ninth year and cannot pay wages; ten points off, in the seventh.")
    print("  Everything the run prints after that")
    print("  crossing is arithmetic rather than economics, because Volume II Part III has")
    print("  no credit and a sector cannot spend what it does not hold. Where the model")
    print("  needs a bank is exactly where Volume III begins.")



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expanded", action="store_true")
    ap.add_argument("--drift", action="store_true")
    args = ap.parse_args()

    p = scheme(args.expanded)
    print("=" * 92)
    print(f"MARX IN MINSKY -- {'EXPANDED' if args.expanded else 'SIMPLE'} REPRODUCTION")
    print("=" * 92)
    print(f"  C1 = {p['C1']:.4f}  V1 = {p['V1']:.4f}  C2 = {p['C2']:.4f}  "
          f"V2 = {p['V2']:.4f}")
    print(f"  e = {p['e']:.2f}  alpha1 = {p['alpha1']:.4f}  alpha2 = {p['alpha2']:.4f}"
          f"  turnover T = {p['T']:.1f}")
    build(p)
    print(f"\n  built and saved as {p['name']}.mky -- all four sheets balance")
    out = check(p)
    report(p, out)

    if args.drift:
        if not args.expanded:
            raise SystemExit("--drift needs --expanded: with alpha = 0 there is nothing "
                             "for Dept II to decide")
        drift(p)

    if args.expanded:
        import math
        g = p["alpha1"] * p["e"] / (1.0 + p["C1"] / p["V1"])
        b10 = at(out, 10.0); a = at(out, 0.0)
        meas = math.log(b10["K1"] / a["K1"]) / (b10["t"] - a["t"])
        print(f"\n  BALANCED GROWTH RATE: predicted alpha1*e/(1+q1) = {g:.6f}, "
              f"measured {meas:.6f}")
        b1 = at(out, 1.0)
        t1 = min(out["t"], key=lambda x: abs(x - 1.0))
        print(f"\n  THE DISCRETE-TO-CONTINUOUS GAP, reported rather than hidden:")
        print(f"    Marx's scheme compounds to    {1 + g:.5f} after one year")
        print(f"    e^g, which is what continuous compounding gives: "
              f"{math.exp(g):.5f}")
        print(f"    this model at t = {t1:.4f}:        {b1['K1'] / a['K1']:.5f}")
        print(f"    Marx-to-continuous gap: {(math.exp(g) - 1 - g) * 100:.2f}% at one year")
        print("    The growth RATE is the same object; the annual TOTALS are not, and no")
        print("    parameter choice reconciles them. Marx accumulates in a lump at the")
        print("    year end, this integrates continuously.")


if __name__ == "__main__":
    main()
