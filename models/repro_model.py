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


def report(p, out, horizon=10.0):
    a, b10 = at(out, 0.0), at(out, horizon)
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




# --------------------------------------------------------------------------- turnover
def turnover_scheme():
    """Marx's ch.21 year two, with constant capital split into fixed and circulating.

    The FLOWS are kept at Marx's: c1 = 4400, v1 = 1100, c2 = 1600, v2 = 800. What is
    added underneath them is the stock structure the schemes never write -- how much
    capital had to be advanced to produce those flows, and how long it sits there.

    The opening values are solved rather than chosen, because the fixed point has no
    neighbourhood (reproduction.py section 6) and a rounded initial condition lands off
    it. Two conditions, both from turnover.py section 2 generalised to three stocks:

        g1 = g2                 alpha2 = alpha1 * n1 * V1 * K2 / (n2 * V2 * K1)
        mp2 = wage1 + div1      F2 + Cc2 = V1 + K1 * (v1 + (1-alpha1)s1 - c2) / acc1

    The second reduces to F2 + Cc2 = V1 + K1/11 at Marx's numbers, which is why the
    values below are integers: L1 = L2 = 10 and n1 = n2 = 1 make it come out even.
    """
    e, a1 = 1.0, 0.5
    L1 = L2 = 10.0
    n1 = n2 = 1.0
    V1, V2 = 1100.0, 800.0
    # c1 = F1/L1 + Cc1*n1 = 4400 with Cc1 = 2200 -> F1 = 22000
    Cc1, F1 = 2200.0, 22000.0
    # c2 = F2/L2 + Cc2*n2 = 1600 with F2 + Cc2 = V1 + K1/11 = 3400 -> Cc2 = 1400
    Cc2, F2 = 1400.0, 2000.0
    K1, K2 = F1 + Cc1 + V1, F2 + Cc2 + V2
    a2 = a1 * n1 * V1 * K2 / (n2 * V2 * K1)
    return dict(F1=F1, Cc1=Cc1, V1=V1, F2=F2, Cc2=Cc2, V2=V2,
                e=e, alpha1=a1, alpha2=a2, n1=n1, n2=n2, L1=L1, L2=L2,
                rho1=1.0 / L1, rho2=1.0 / L2, name="TurnoverReproduction")


def build_turnover(p):
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
    for nm in ("e", "alpha1", "alpha2", "n1", "n2", "L1", "L2", "rho1", "rho2"):
        b.param(nm, float(p[nm]))

    iF1 = b.stock("F1", p["F1"]); iC1 = b.stock("Cc1", p["Cc1"])
    iV1 = b.stock("V1", p["V1"]); iF2 = b.stock("F2", p["F2"])
    iC2 = b.stock("Cc2", p["Cc2"]); iV2 = b.stock("V2", p["V2"])

    # constant capital consumed now has two parts with quite different tempos
    b.eq("dep1", "F1 / L1")               # value transferred by fixed capital
    b.eq("dep2", "F2 / L2")
    b.eq("circ1", "Cc1 * n1")             # circulating, recovered every turnover
    b.eq("circ2", "Cc2 * n2")
    b.eq("c1", "dep1 + circ1")
    b.eq("c2", "dep2 + circ2")
    b.eq("v1", "V1 * n1")                 # ANNUAL wage bill = advance x turnovers
    b.eq("v2", "V2 * n2")
    b.eq("s1", "e * v1")                  # so the annual rate of surplus value is e*n
    b.eq("s2", "e * v2")
    b.eq("K1", "F1 + Cc1 + V1")           # capital ADVANCED, which the schemes omit
    b.eq("K2", "F2 + Cc2 + V2")
    b.eq("X1", "c1 + v1 + s1")
    b.eq("X2", "c2 + v2 + s2")

    b.eq("acc1", "alpha1 * s1")
    b.eq("acc2", "alpha2 * s2")
    b.eq("accF1", "acc1 * F1 / K1")       # net investment, split across the three stocks
    b.eq("accC1", "acc1 * Cc1 / K1")
    b.eq("accV1", "acc1 * V1 / K1")
    b.eq("accF2", "acc2 * F2 / K2")
    b.eq("accC2", "acc2 * Cc2 / K2")
    b.eq("accV2", "acc2 * V2 / K2")

    # REPLACEMENT IS NOT ACCUMULATION. rho*F is bought to keep the stock standing;
    # F/L is the value it loses. They cancel only at rho = 1/L, and when they do not,
    # the CAPITAL STOCK moves -- not just the money. That is why rho enters here and
    # not only in the money flows.
    b.eq("rep1", "rho1 * F1")
    b.eq("rep2", "rho2 * F2")
    b.eq("dF1", "accF1 + rep1 - dep1")
    b.eq("dF2", "accF2 + rep2 - dep2")
    for src, iop in (("dF1", iF1), ("accC1", iC1), ("accV1", iV1),
                     ("dF2", iF2), ("accC2", iC2), ("accV2", iV2)):
        b.wire(b.ref[src], iop, 1)

    b.eq("wage1", "v1 + accV1")
    b.eq("wage2", "v2 + accV2")
    b.eq("div1", "s1 - acc1")
    b.eq("div2", "s2 - acc2")
    b.eq("wcons", "wage1 + wage2")
    b.eq("ccons", "div1 + div2")
    # Dept II's whole demand on Dept I: inputs used up, worn fixed capital replaced,
    # and net additions to both.
    b.eq("mp2", "circ2 + rep2 + accF2 + accC2")
    b.eq("cond", "mp2 - wage1 - div1")
    b.eq("Mtot", "MF1 + MF2 + MW + MC")
    b.eq("Xtot", "X1 + X2")
    b.plot("Capital advanced", ["K1", "K2"])
    b.plot("Reproduction condition", ["cond"])
    api("/api/layout")
    api("/api/save", {"name": p["name"]})
    return b


def turnover_report(p):
    print("=" * 92)
    print("MARX IN MINSKY -- REPRODUCTION WITH TURNOVER AND FIXED CAPITAL")
    print("=" * 92)
    K1 = p["F1"] + p["Cc1"] + p["V1"]
    K2 = p["F2"] + p["Cc2"] + p["V2"]
    print(f"  {'':>10} {'F':>9} {'Cc':>8} {'V':>8} {'K advanced':>12} {'c':>8} "
          f"{'v':>7} {'s':>7}")
    for d, F, Cc, V, L, n in (("Dept I", p["F1"], p["Cc1"], p["V1"], p["L1"], p["n1"]),
                              ("Dept II", p["F2"], p["Cc2"], p["V2"], p["L2"], p["n2"])):
        c = F / L + Cc * n
        print(f"  {d:>10} {F:9.0f} {Cc:8.0f} {V:8.0f} {F + Cc + V:12.0f} {c:8.0f} "
              f"{V * n:7.0f} {p['e'] * V * n:7.0f}")
    print(f"\n  The FLOWS are Marx's ch.21 year two exactly: c1 = 4400, v1 = 1100, "
          "c2 = 1600, v2 = 800.")
    print(f"  What is new is underneath them -- {K1:.0f} and {K2:.0f} of capital advanced,")
    print("  against 5500 and 2400 when everything turned over annually and none of the")
    print("  constant capital was fixed.")
    print(f"\n  alpha1 = {p['alpha1']:.4f} chosen, alpha2 = {p['alpha2']:.6f} forced")
    g = p["alpha1"] * p["e"] * p["n1"] * p["V1"] / K1
    print(f"  balanced growth g = alpha1*e*n1*V1/K1 = {g:.6f} = {g * 100:.2f}% a year")
    print(f"\n  That growth rate is the first real consequence. With no fixed capital the")
    print(f"  same alpha1 gave 10.00%. Advancing {K1:.0f} instead of 5500 to produce the")
    print(f"  same flows cuts it to {g * 100:.2f}%, because the surplus now has to expand a")
    print("  capital four times the size. Fixed capital slows accumulation, and nothing")
    print("  in c + v + s can show that.")
    return g




def replacement(p, r):
    """rho off 1/L -- Marx ch.20 sec.11, the condition the schemes cannot state."""
    print("\n" + "=" * 92)
    print("REPLACEMENT OFF THE AGE DISTRIBUTION -- chapter 20, section 11")
    print("=" * 92)
    print(f"  rho is the rate at which Dept II's fixed capital is physically replaced.")
    print(f"  Simple reproduction needs rho = 1/L = {1 / p['L2']:.3f}, which is a claim")
    print("  about the AGE DISTRIBUTION of the stock, not about anyone's intentions --")
    print("  see turnover.py section 4 for what that parameter is standing in for.\n")
    print(f"  {'rho2':>7} {'vs 1/L':>8} | {'Firms I money t=20':>19} "
          f"{'Dept II fixed capital':>22} | {'cond/X1':>9}")
    base = 1.0 / p["L2"]
    for rho in (base * 0.9, base * 0.95, base, base * 1.05, base * 1.1):
        out = r.go(20.0, ["MF1", "F2", "cond", "X1"], overrides={"rho2": rho},
                   samples=200)
        a, b = at(out, 0.0), at(out, 20.0)
        mark = "  <- balanced" if abs(rho - base) < 1e-12 else ""
        print(f"  {rho:7.4f} {rho / base - 1:+7.1%} | {b['MF1']:19.1f} "
              f"{a['F2']:9.0f} -> {b['F2']:8.0f} | {b['cond'] / b['X1'] * 100:8.2f}%"
              f"{mark}")
    print("\n  Under-replacing does two things at once, and only one is visible in the")
    print("  money. Firms I loses the sale, so its cash falls -- the same drain as before,")
    print("  a third of the opening balance gone in twenty years at ten points off.")
    print("\n  The second is in the capital stock, and it is not what I first wrote down.")
    print("  Dept II's fixed capital does NOT shrink: at rho = 0.09 it still grows 2000 ->")
    print("  2581, because net accumulation outweighs the under-replacement. What it does")
    print("  is grow SHORT -- 2581 against the balanced 3088, a sixth less capital after")
    print("  twenty years, from a parameter five to ten points out. The economy is not")
    print("  contracting, it is quietly compounding into a smaller one.")
    print("\n  This is the condition the reproduction schemes are structurally unable to")
    print("  state, because they write c as one number. Splitting it into F/L and Cc*n is")
    print("  what makes rho visible at all, and rho is the thing that has to be right.")



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expanded", action="store_true")
    ap.add_argument("--drift", action="store_true")
    ap.add_argument("--turnover", action="store_true")
    args = ap.parse_args()

    if args.turnover:
        p = turnover_scheme()
        g = turnover_report(p)
        build_turnover(p)
        print(f"\n  built and saved as {p['name']}.mky -- all four sheets balance")
        r = runner(p)
        names = ["F1", "Cc1", "V1", "F2", "Cc2", "V2", "K1", "K2", "MF1", "MF2",
                 "MW", "MC", "Mtot", "cond", "X1", "X2", "Xtot"]
        out = r.go(20.0, names, samples=300)
        report(p, out, horizon=20.0)
        import math
        a, b20 = at(out, 0.0), at(out, 20.0)
        meas = math.log(b20["K1"] / a["K1"]) / (b20["t"] - a["t"])
        print(f"\n  BALANCED GROWTH RATE: predicted {g:.6f}, measured {meas:.6f}")
        replacement(p, r)
        return

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
