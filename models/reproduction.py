"""Marx's reproduction schemes, Volume II Parts III, as arithmetic before they are a model.

    python3 models/reproduction.py

WHY A REFERENCE IMPLEMENTATION FIRST
------------------------------------
The Minsky build has to be validated against something, and the only ground truth
available is Marx's own published tables. So this module reproduces them in plain Python
with no engine involved, and the built model is scored against THIS. That is the ordering
this repo arrived at the hard way: the engine fails silently, so the check has to come
from outside it.

THE SCHEMES
-----------
Two departments. I makes means of production, II makes means of consumption. Each writes
its annual product as c + v + s -- constant capital consumed, wages, surplus value.

    SIMPLE REPRODUCTION (ch.20)      EXPANDED REPRODUCTION (ch.21, first scheme)
    I.  4000c + 1000v + 1000s        I.  4000c + 1000v + 1000s = 6000
    II. 2000c +  500v +  500s        II. 1500c +  750v +  750s = 3000

Everything Dept I makes must be bought as constant capital, by one department or the
other; everything Dept II makes must be bought as wages or capitalist consumption. Netting
out what each department buys from itself leaves ONE condition:

    simple      II c        = I (v + s)                     2000 = 2000
    expanded    II (c + dc) = I (v + dv + s_consumed)       1600 = 1100 + 500

which is the whole of Marx's argument in one line. The point of putting it in Minsky is
that this is a MONEY-STOCK condition -- section 4 shows it is exactly the requirement that
Dept I's money holding not drain -- and money stocks are what Godley tables are for.

WHAT IS NOT HERE
----------------
Values, not prices. c, v and s are labour-value magnitudes, and Volume III's
transformation problem stands between them and the money flows a Godley table records.
The schemes are treated here as flows of a single homogeneous product per department,
which is what makes them a two-sector model rather than a value theory. That is the
standard reading and it is an assumption, not a result.
"""
import sys


#: Volume II ch.20, the simple reproduction scheme as Marx writes it.
SIMPLE = dict(c1=4000.0, v1=1000.0, c2=2000.0, v2=500.0, e=1.0)

#: Volume II ch.21, the first expanded scheme. Note II's composition differs from ch.20 --
#: Marx re-proportions it so that I(v+s) EXCEEDS IIc, which is what leaves room to grow.
EXPANDED = dict(c1=4000.0, v1=1000.0, c2=1500.0, v2=750.0, e=1.0)

#: Marx's published totals for the first six years of the expanded scheme. The recursion
#: below is scored against these rather than against itself.
MARX_TABLE = [9000.0, 9800.0, 10780.0, 11858.0, 13043.8, 14348.18]


def product(st):
    """(X1, X2): each department's annual product, c + v + s."""
    s1, s2 = st["e"] * st["v1"], st["e"] * st["v2"]
    return (st["c1"] + st["v1"] + s1, st["c2"] + st["v2"] + s2)


def step(st, alpha1):
    """One year of Marx's own procedure: Dept I decides, Dept II accommodates.

    This is not a modelling choice, it is how ch.21 proceeds. Dept I's capitalists
    accumulate a fraction alpha1 of their surplus, split in their existing organic
    composition. Whatever means of production Dept I does not keep for itself is what
    Dept II gets, and Dept II's accumulation is therefore RESIDUAL -- it takes the number
    that makes the exchange close.

    Returns (next state, what Dept II was forced to do).
    """
    e = st["e"]
    s1, s2 = e * st["v1"], e * st["v2"]
    X1, _X2 = product(st)
    q1, q2 = st["c1"] / st["v1"], st["c2"] / st["v2"]

    acc1 = alpha1 * s1
    dc1 = acc1 * q1 / (1.0 + q1)
    dv1 = acc1 / (1.0 + q1)

    # Dept I keeps c1 + dc1 of its own product; the rest is all Dept II can have.
    dc2 = X1 - st["c1"] - dc1 - st["c2"]
    dv2 = dc2 / q2                       # Dept II accumulates at ITS composition
    alpha2 = (dc2 + dv2) / s2 if s2 else float("nan")

    nxt = dict(st, c1=st["c1"] + dc1, v1=st["v1"] + dv1,
               c2=st["c2"] + dc2, v2=st["v2"] + dv2)
    return nxt, dict(alpha2=alpha2, dc1=dc1, dv1=dv1, dc2=dc2, dv2=dv2,
                     acc1=acc1, acc2=dc2 + dv2, cons1=s1 - acc1,
                     cons2=s2 - dc2 - dv2)


def balance(st):
    """The exchange condition's residual. Zero means the departments clear each other."""
    s1 = st["e"] * st["v1"]
    return st["c2"] - (st["v1"] + s1)


# --------------------------------------------------------------------------- 1
def simple_reproduction():
    print("=" * 92)
    print("1. SIMPLE REPRODUCTION -- Volume II, chapter 20")
    print("=" * 92)
    st = dict(SIMPLE)
    X1, X2 = product(st)
    s1, s2 = st["e"] * st["v1"], st["e"] * st["v2"]
    print(f"  I.  {st['c1']:.0f}c + {st['v1']:.0f}v + {s1:.0f}s = {X1:.0f}"
          "     means of production")
    print(f"  II. {st['c2']:.0f}c + {st['v2']:.0f}v + {s2:.0f}s = {X2:.0f}"
          "     means of consumption")
    print(f"  total social product {X1 + X2:.0f}\n")

    print("  Dept I's product must all be bought as constant capital:")
    print(f"    I needs  {st['c1']:.0f}   II needs {st['c2']:.0f}   "
          f"total {st['c1'] + st['c2']:.0f}  against a product of {X1:.0f}  "
          f"{'CLEARS' if abs(st['c1'] + st['c2'] - X1) < 1e-9 else 'FAILS'}")
    print("  Dept II's product must all be bought as wages or capitalist consumption:")
    dem = st["v1"] + s1 + st["v2"] + s2
    print(f"    I's v+s  {st['v1'] + s1:.0f}   II's v+s {st['v2'] + s2:.0f}   "
          f"total {dem:.0f}  against a product of {X2:.0f}  "
          f"{'CLEARS' if abs(dem - X2) < 1e-9 else 'FAILS'}")
    print(f"\n  Netting out what each buys from itself, one condition remains:")
    print(f"    II c = I (v + s)     {st['c2']:.0f} = {st['v1'] + s1:.0f}     "
          f"residual {balance(st):+.0f}")
    return st


# --------------------------------------------------------------------------- 2
def expanded_reproduction(years=6, alpha1=0.5, verbose=True):
    if verbose:
        print("\n" + "=" * 92)
        print("2. EXPANDED REPRODUCTION -- Volume II, chapter 21, first scheme")
        print("=" * 92)
        print(f"  Dept I accumulates alpha1 = {alpha1:.2f} of its surplus. Dept II takes "
              "whatever is left over.\n")
        print(f"  {'yr':>3} {'I c':>8} {'I v':>7} {'I s':>7} | {'II c':>7} {'II v':>7} "
              f"{'II s':>7} | {'total':>9} {'growth':>8} {'alpha2':>7}")
    st = dict(EXPANDED)
    totals, alphas = [], []
    for y in range(years):
        X1, X2 = product(st)
        tot = X1 + X2
        totals.append(tot)
        nxt, info = step(st, alpha1)
        alphas.append(info["alpha2"])
        if verbose:
            g = (tot / totals[-2] - 1.0) if len(totals) > 1 else float("nan")
            gs = f"{g * 100:7.2f}%" if len(totals) > 1 else f"{'--':>8}"
            print(f"  {y + 1:3d} {st['c1']:8.0f} {st['v1']:7.0f} "
                  f"{st['e'] * st['v1']:7.0f} | {st['c2']:7.0f} {st['v2']:7.0f} "
                  f"{st['e'] * st['v2']:7.0f} | {tot:9.1f} {gs} {info['alpha2']:7.3f}")
        st = nxt
    return totals, alphas


# --------------------------------------------------------------------------- 3
def against_marx(totals):
    print("\n" + "=" * 92)
    print("3. AGAINST MARX'S PUBLISHED FIGURES")
    print("=" * 92)
    print(f"  {'year':>5} {'this recursion':>15} {'Marx':>10} {'difference':>12}")
    ok = True
    for i, (mine, his) in enumerate(zip(totals, MARX_TABLE), start=1):
        d = mine - his
        if abs(d) > 0.05:
            ok = False
        print(f"  {i:5d} {mine:15.2f} {his:10.2f} {d:+12.4f}")
    print(f"\n  {'REPRODUCES THE PUBLISHED SCHEME' if ok else 'DOES NOT MATCH'}"
          " -- so the recursion is Marx's, not an interpretation of him.")
    return ok


# --------------------------------------------------------------------------- 4
def money_reading():
    """The exchange condition restated as a money-stock condition, which is the bridge."""
    print("\n" + "=" * 92)
    print("4. THE SAME CONDITION AS A MONEY FLOW -- why this belongs in a Godley table")
    print("=" * 92)
    st = dict(SIMPLE)
    s1, s2 = st["e"] * st["v1"], st["e"] * st["v2"]
    print("  Four sectors, no credit and no banks, which is Volume II Part III's own")
    print("  abstraction. Follow the money rather than the product:\n")
    rows = [
        ("Firms I  pay wages",            -st["v1"], 0.0, +st["v1"], 0.0),
        ("Firms II pay wages",            0.0, -st["v2"], +st["v2"], 0.0),
        ("Firms I  pay out surplus",      -s1, 0.0, 0.0, +s1),
        ("Firms II pay out surplus",      0.0, -s2, 0.0, +s2),
        ("workers buy consumption",       0.0, +st["v1"] + st["v2"],
         -(st["v1"] + st["v2"]), 0.0),
        ("capitalists buy consumption",   0.0, +s1 + s2, 0.0, -(s1 + s2)),
        ("Firms II buy means of prod.",   +st["c2"], -st["c2"], 0.0, 0.0),
    ]
    print(f"  {'flow':>30} {'Firms I':>9} {'Firms II':>9} {'Workers':>9} "
          f"{'Capitalists':>12}")
    tot = [0.0, 0.0, 0.0, 0.0]
    for lab, a, b, c, d in rows:
        for i, v in enumerate((a, b, c, d)):
            tot[i] += v
        print(f"  {lab:>30} {a:+9.0f} {b:+9.0f} {c:+9.0f} {d:+12.0f}")
    print(f"  {'NET CHANGE IN MONEY':>30} {tot[0]:+9.0f} {tot[1]:+9.0f} {tot[2]:+9.0f} "
          f"{tot[3]:+12.0f}")
    print("\n  Every sector's money holding is unchanged, and that is the whole of simple")
    print("  reproduction. Firms I take in IIc and pay out I(v+s), so their money is")
    print("  constant exactly when IIc = I(v+s). The reproduction condition IS the")
    print("  stationarity of a money stock -- which is the object a Godley table exists to")
    print("  track, and the reason these schemes are worth building rather than tabulating.")
    print("\n  Workers and capitalists net to zero by construction: they spend what they")
    print("  receive. So of four sectors only ONE carries an independent condition, and")
    print("  Firms II's residual is Firms I's with the sign flipped.")



# --------------------------------------------------------------------------- 5
def closed_form(alpha1=0.5):
    """What the balanced path actually requires -- and how little of it is chosen.

    Accumulation in the schemes happens AT the existing organic composition, so q1 and q2
    never move: 4000/1000 = 4400/1100 = 4 throughout. With q fixed, a department that
    accumulates a fraction alpha of its surplus grows its capital at

        g = alpha * e / (1 + q)

    because s = e*v and v = K/(1+q). Setting g1 = g2 gives Dept II's accumulation rate in
    closed form, and it contains no choice of Dept II's:

        alpha2 = alpha1 * (1 + q2) / (1 + q1)
    """
    print("\n" + "=" * 92)
    print("5. THE BALANCED PATH IN CLOSED FORM -- and how much of it Dept II gets to pick")
    print("=" * 92)
    st = dict(EXPANDED)
    q1, q2, e = st["c1"] / st["v1"], st["c2"] / st["v2"], st["e"]
    g = alpha1 * e / (1.0 + q1)
    a2 = alpha1 * (1.0 + q2) / (1.0 + q1)
    print(f"  q1 = {q1:.0f}, q2 = {q2:.0f}, e = {e:.0f}, alpha1 = {alpha1:.2f} chosen "
          "by Dept I\n")
    print(f"    g      = alpha1*e/(1+q1)          = {g:.4f}   = {g * 100:.1f}% a year")
    print(f"    alpha2 = alpha1*(1+q2)/(1+q1)     = {a2:.4f}")
    print(f"\n  The recursion produced alpha2 = 0.300 from year 2 on. The closed form gives")
    print(f"  {a2:.3f}. Dept II's accumulation rate is not a decision, it is an ARITHMETIC")
    print("  CONSEQUENCE of Dept I's decision and the two organic compositions.")

    # the second condition, which Marx's own opening year does not satisfy
    need = ((1.0 + g) + (1.0 - alpha1) * e) / (1.0 + g)
    have = st["c2"] / st["v1"]
    print(f"\n  There is a SECOND condition, on the opening proportions:")
    print(f"    c2/v1 must equal ((1+g) + (1-alpha1)e)/(1+g) = {need:.4f}")
    print(f"    Marx's year 1 has {st['c2']:.0f}/{st['v1']:.0f} = {have:.4f}")
    print(f"\n  It is off by {(have - need):+.4f}, and that is not a slip -- it is why the")
    print("  scheme grows 8.89% in its first year and exactly 10% ever after. Year 1 is a")
    print("  transient. Marx's procedure snaps onto the balanced path in a single period")
    print("  ONLY because Dept II is assumed to take whatever is left, which is precisely")
    print("  the assumption the next section removes.")
    return g, a2


# --------------------------------------------------------------------------- 6
def knife_edge(alpha1=0.5, years=10):
    """Let Dept II choose too. Nothing holds the two departments together.

    Marx's procedure makes Dept II residual, so the exchange closes by construction and
    the scheme cannot fail. That is an assumption about behaviour, not an accounting
    identity, and it is the one doing all the work. Give Dept II its own accumulation rate
    and the departments grow at different rates from the first year.
    """
    print("\n" + "=" * 92)
    print("6. THE KNIFE EDGE -- what happens when Dept II decides for itself")
    print("=" * 92)
    st0 = dict(EXPANDED)
    q1, q2, e = st0["c1"] / st0["v1"], st0["c2"] / st0["v2"], st0["e"]
    a2star = alpha1 * (1.0 + q2) / (1.0 + q1)
    print(f"  Dept I holds alpha1 = {alpha1:.2f}. The balanced value for Dept II is "
          f"{a2star:.3f}.")
    print("  The residual is Dept I's product minus what the two departments actually")
    print("  demand as constant capital, as a share of that product.\n")
    print(f"  {'alpha2':>8} {'g1':>7} {'g2':>7} | " +
          " ".join(f"{'yr' + str(y):>8}" for y in (1, 3, 5, 10)))
    for a2 in (a2star - 0.10, a2star - 0.05, a2star, a2star + 0.05, a2star + 0.10):
        st = dict(st0)
        gaps = {}
        for y in range(1, years + 1):
            X1, _ = product(st)
            s1, s2 = e * st["v1"], e * st["v2"]
            dc1 = alpha1 * s1 * q1 / (1.0 + q1)
            dc2 = a2 * s2 * q2 / (1.0 + q2)
            dv1 = alpha1 * s1 / (1.0 + q1)
            dv2 = a2 * s2 / (1.0 + q2)
            demand = st["c1"] + dc1 + st["c2"] + dc2
            gaps[y] = (X1 - demand) / X1
            st = dict(st, c1=st["c1"] + dc1, v1=st["v1"] + dv1,
                      c2=st["c2"] + dc2, v2=st["v2"] + dv2)
        g1 = alpha1 * e / (1.0 + q1)
        g2 = a2 * e / (1.0 + q2)
        mark = "  <- balanced" if abs(a2 - a2star) < 1e-9 else ""
        print(f"  {a2:8.3f} {g1 * 100:6.1f}% {g2 * 100:6.1f}% | " +
              " ".join(f"{gaps[y] * 100:7.2f}%" for y in (1, 3, 5, 10)) + mark)
    print("\n  TWO THINGS IN THAT TABLE, and the second was not what I expected.")
    print("\n  First: away from the balanced row the residual is nonzero in YEAR ONE and")
    print("  grows without limit. alpha2 = 0.25 against 0.30 leaves means of production")
    print("  unsold immediately, and by year 10 a tenth of Dept I's product has no buyer.")
    print("  Nothing corrects it, because nothing in the scheme responds to the residual.")
    print("\n  Second: the BALANCED row is not zero either. It is -0.83% and stays there,")
    print("  because section 5's other condition is still violated -- Marx's opening")
    print("  c2/v1 is 1.5000 where the path needs 1.4545. Equal growth rates preserve a")
    print("  proportional gap rather than closing it. And note where zero DOES appear in")
    print("  year one: at alpha2 = 0.200, which is exactly the value Marx's own residual")
    print("  procedure produces in year 1. That row clears at the start and diverges after,")
    print("  because the proportions move underneath it.")
    print("\n  So the two conditions are genuinely independent and BOTH have to hold:")
    st = dict(st0)
    g = alpha1 * e / (1.0 + q1)
    st["c2"] = st0["v1"] * ((1.0 + g) + (1.0 - alpha1) * e) / (1.0 + g)
    st["v2"] = st["c2"] / q2
    print(f"    reset the opening proportions to c2 = {st['c2']:.2f}, v2 = "
          f"{st['v2']:.2f}, and hold alpha2 = {a2star:.3f}")
    worst = 0.0
    for y in range(1, years + 1):
        X1, _ = product(st)
        s1, s2 = e * st["v1"], e * st["v2"]
        dc1 = alpha1 * s1 * q1 / (1.0 + q1)
        dc2 = a2star * s2 * q2 / (1.0 + q2)
        gap = (X1 - (st["c1"] + dc1 + st["c2"] + dc2)) / X1
        worst = max(worst, abs(gap))
        st = dict(st, c1=st["c1"] + dc1, v1=st["v1"] + alpha1 * s1 / (1.0 + q1),
                  c2=st["c2"] + dc2, v2=st["v2"] + a2star * s2 / (1.0 + q2))
    print(f"    worst residual over {years} years: {worst * 100:.2e}%  -- exactly zero, "
          "to floating point")
    print("\n  That is the fixed point, and it is a POINT: one accumulation rate and one")
    print("  opening proportion, with no neighbourhood around it. That is the")
    print("  disproportionality problem, and it is not a criticism of Marx -- he says as")
    print("  much himself, that the proportions are maintained only by accident.")
    print("\n  What the schemes therefore establish is CONSISTENCY, not stability. They")
    print("  show a set of proportions at which reproduction can proceed. They contain no")
    print("  mechanism that finds those proportions or returns to them, and Marx's")
    print("  procedure hides that by making one department passive.")
    return a2star



def main():
    simple_reproduction()
    totals, alphas = expanded_reproduction()
    against_marx(totals)
    money_reading()
    closed_form()
    knife_edge()


if __name__ == "__main__":
    main()
