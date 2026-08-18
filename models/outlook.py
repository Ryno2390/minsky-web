"""What CBO's projections do to the fiscal ceiling, and to the policy band.

    python3 models/outlook.py

THE SETUP
---------
fiscal.py built a ceiling on the sustainable rate,

    i_max = g + s/b                and with the interest-as-income feedback,
    i_max = (g0 + s/b) / (1 - phi*b*theta)

and dominance.py found the constraint real but not yet binding on behaviour: fiscal is
active, monetary is not passive, and the Fed is currently running ABOVE the phi = 0
ceiling rather than below it. The forward question is whether that stays possible.

CBO's February 2026 long-term outlook supplies every input the ceiling needs, on its own
projections rather than on assumptions invented here: the debt ratio, the primary balance,
nominal growth, and the effective rate on the debt. So the ceiling can be computed out to
2056 without a single free parameter, and -- this is the part worth doing -- CBO's own
projected interest rate can be scored against it.

WHAT A PROJECTION IS
--------------------
Current law, February 2026. Current law assumes scheduled expiries happen on schedule,
which historically they do not, so the revenue path is optimistic in a direction nobody
disputes. Read everything below as "what would happen if nothing changed", which is the
one thing that will not happen. The value is in the SHAPE and the ORDERING, not the level.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import cbo                                                       # noqa: E402
import fiscal                                                    # noqa: E402
import invert                                                    # noqa: E402
import usbank                                                    # noqa: E402
import uscorp                                                    # noqa: E402

MARK = (2026, 2030, 2035, 2040, 2045, 2050, 2055)


def paths():
    p = {
        "b": cbo.series("budget", "lt_debt_held_by_public_gdp_share", 0.01),
        "s": cbo.series("budget", "lt_primary_deficit_gdp_share", 0.01),
        "bill": cbo.series("budget", "lt_outlays_net_interest_gdp_share", 0.01),
        "g": cbo.series("ltecon", "nominal_gdp_growth", 0.01),
        "i_eff": cbo.series("ltecon", "interest_rate_fed_debt", 0.01),
        "ff": cbo.series("econ", "fed_funds_rate", 0.01),
        "t10": cbo.series("econ", "treasury_note_rate_10yr", 0.01),
    }
    return p


# --------------------------------------------------------------------------- 1
def baseline(p):
    print("=" * 92)
    print("1. THE CBO BASELINE  (February 2026 vintage, current law)")
    print("=" * 92)
    print(f"  {'year':>6} {'debt/GDP':>9} {'primary':>9} {'net int':>9} {'nom g':>8} "
          f"{'i_eff':>8} {'i - g':>8}")
    for y in MARK:
        if y not in p["b"]:
            continue
        print(f"  {y:6d} {p['b'][y]*100:8.1f}% {p['s'][y]*100:+8.2f}% "
              f"{p['bill'][y]*100:8.2f}% {p['g'][y]*100:7.2f}% {p['i_eff'][y]*100:7.2f}% "
              f"{(p['i_eff'][y]-p['g'][y])*100:+7.2f}%")
    print("\n  Two things to hold onto. The interest bill roughly DOUBLES as a share of GDP.")
    print("  And i - g turns positive and stays there -- dominance.py found it at -2.19 pp")
    print("  today, and CBO has it crossing back above zero. The Sargent-Wallace arithmetic")
    print("  is idle now and is projected to stop being idle.")
    print("\n  The primary deficit, though, does NOT deteriorate. It sits near -2% of GDP")
    print("  throughout. The whole debt path is interest compounding on itself.")


# --------------------------------------------------------------------------- 2
def against_own_ceiling(p):
    print("\n" + "=" * 92)
    print("2. CBO'S BASELINE AGAINST CBO'S OWN CEILING")
    print("=" * 92)
    print("  i_max = g + s/b, computed entirely from CBO's projections. Then CBO's own")
    print("  projected effective rate is scored against it. No free parameter anywhere.\n")
    print(f"  {'year':>6} {'i_max':>8} {'CBO i_eff':>10} {'gap':>8}   debt path implied")
    for y in MARK:
        if y not in p["b"]:
            continue
        im = p["g"][y] + p["s"][y] / p["b"][y]
        gap = p["i_eff"][y] - im
        print(f"  {y:6d} {im*100:7.2f}% {p['i_eff'][y]*100:9.2f}% {gap*100:+7.2f}%   "
              f"{'rising' if gap > 0 else 'falling'}")
    print("\n  CBO's baseline runs above its own sustainability ceiling in every year, by")
    print("  one and a half to two points. That is not a criticism of CBO -- it IS the")
    print("  projection. Debt reaching 172% of GDP is precisely what a persistent gap of")
    print("  that size produces. The ceiling is not a forecast anyone is disputing; it is")
    print("  a restatement of the baseline in rate terms.")


# --------------------------------------------------------------------------- 3
def ceiling_path(p):
    """Does the ceiling fall as the debt rises? It does not, and the reason matters."""
    print("\n" + "=" * 92)
    print("3. THE CEILING PATH -- and it goes the wrong way for the intuition")
    print("=" * 92)
    print("  The natural expectation is that a bigger debt means a lower tolerable rate.")
    print("  i_max = g + s/b says otherwise, because b is in the DENOMINATOR of s/b: a")
    print("  primary deficit of a fixed share of GDP is spread thinner per dollar of debt")
    print("  as the stock grows.\n")
    print(f"  {'year':>6} {'b':>7} {'g':>8} {'s/b':>8} {'i_max':>8}   change from 2026")
    base = None
    for y in MARK:
        if y not in p["b"]:
            continue
        sb = p["s"][y] / p["b"][y]
        im = p["g"][y] + sb
        if base is None:
            base = im
        print(f"  {y:6d} {p['b'][y]:7.3f} {p['g'][y]*100:7.2f}% {sb*100:+7.2f}% "
              f"{im*100:7.2f}%   {(im-base)*100:+6.2f} pp")
    ys = [y for y in sorted(p["b"]) if y in p["g"]]
    ims = np.array([p["g"][y] + p["s"][y] / p["b"][y] for y in ys])
    print(f"\n  Full path: {ims[0]*100:.2f}% in {ys[0]} to {ims[-1]*100:.2f}% in {ys[-1]}, "
          f"net {(ims[-1]-ims[0])*100:+.2f} pp, but the route is not flat --")
    print(f"  it dips to {ims.min()*100:.2f}% and peaks at {ims.max()*100:.2f}%, a range of "
          f"{(ims.max()-ims.min())*100:.2f} pp. The 2026 reading is")
    print("  high because nominal growth is still 5.1%; once growth settles the ceiling")
    print("  sits in a narrow 1.9-2.3% channel for thirty years.")
    print("\n  The debt ratio nearly doubles and the ceiling ends roughly where it started,")
    print("  because two effects cancel: nominal growth falls, which lowers it, and the")
    print("  deficit is diluted across a larger stock, which raises it.")
    print("\n  So the mechanism people usually have in mind -- more debt, less room -- is")
    print("  NOT what this constraint says. What tightens is not the ceiling. It is the")
    print("  distance the actual rate has to fall to reach it, and the cost of the gap.")


# --------------------------------------------------------------------------- 4
def phi_path(p):
    """The Kelton threshold, projected. This is where higher debt does change things."""
    print("\n" + "=" * 92)
    print("4. THE CRITICAL PHI -- where a bigger debt DOES change the answer")
    print("=" * 92)
    h = fiscal.holders()
    th = h[max(h)]["theta"]
    print(f"  Interest becomes self-financing at phi = 1/(b*theta). Holding theta at its")
    print(f"  latest reading of {th*100:.1f}% -- CBO does not project holder composition.\n")
    print(f"  {'year':>6} {'b':>7} {'b*theta':>9} {'critical phi':>13} "
          f"{'i_max at phi=0.81':>18}")
    for y in MARK:
        if y not in p["b"]:
            continue
        bt = p["b"][y] * th
        crit = 1.0 / bt if bt > 0 else float("inf")
        den = 1.0 - 0.81 * bt
        base = p["g"][y] + p["s"][y] / p["b"][y]
        v = base / den if den > 0 else float("inf")
        print(f"  {y:6d} {p['b'][y]:7.3f} {bt:9.3f} {crit:13.2f} "
              f"{(f'{v*100:.2f}%' if np.isfinite(v) else 'infinite'):>18}")
    print("\n  DO NOT BELIEVE THE LAST COLUMN AT THE BOTTOM. By 2055, b*theta = 0.965 and")
    print("  phi = 0.81 puts the denominator at 0.218 -- four fifths of the way to the")
    print("  singularity, where a first-order linear feedback is being extrapolated far")
    print("  past anything it was fitted on. 10.27% is what the algebra says, not a")
    print("  forecast. The COLUMN THAT MATTERS is the critical phi, which is a ratio of")
    print("  two projected quantities and does not blow up.")
    print("\n  THIS is the channel debt actually works through. The threshold falls from")
    print("  1.77 to about 1.04: by the 2050s it takes a multiplier barely above one for")
    print("  the interest bill to finance itself, where today it takes nearly two.")
    print("\n  And theta is held FIXED here, which is conservative in a knowable direction.")
    print("  The Fed's share has fallen 26.5% -> 14.7% since 2021Q4 and the foreign share")
    print("  45.8% -> 30.0% since 2007. Both push theta UP, which pushes the critical phi")
    print("  further DOWN. QT strengthens the very feedback that loosens the constraint.")


# --------------------------------------------------------------------------- 5
def band(p):
    print("\n" + "=" * 92)
    print("5. THE POLICY BAND, PROJECTED")
    print("=" * 92)
    rows = fiscal.panel()
    fiscal.smooth_growth(rows)
    _a0, b1, _r2, _n = fiscal.pass_through(rows)
    dyn = fiscal.pass_through_dynamics(rows)
    b_lo, b_hi = min(dyn["long_run"].values()), max(dyn["long_run"].values())
    bank = usbank.usable()
    lam = float(np.mean([v["lam"] for v in bank.values() if v["lam"] is not None]))
    D = uscorp.load()
    r = float(np.mean(list(uscorp.annual(D, uscorp.ratios(D), "r").values())))
    marg = lam * r
    print(f"  The ceiling on the EFFECTIVE rate converts to a ceiling on the POLICY rate")
    print(f"  through the pass-through. The right one here is the LONG-RUN value, because")
    print(f"  the ceiling is a steady-state condition: {b_lo:.2f} to {b_hi:.2f} by")
    print(f"  distributed lag, against {b1:.3f} from the levels regression used in")
    print(f"  fiscal.py. The range is carried through rather than a point taken, and the")
    print(f"  direction matters -- a SMALLER pass-through means a LOWER policy ceiling,")
    print(f"  because the correction (i_max - i_eff) is negative and gets divided by it.\n")
    print(f"  {'year':>6} {'policy ceiling':>20} {'CBO ff':>8} {'CBO 10y':>9} "
          f"{'NIM rule':>9} {'rule over ceiling':>18}")
    for y in MARK:
        if y not in p["b"] or y not in p["ff"]:
            continue
        im = p["g"][y] + p["s"][y] / p["b"][y]
        lo = p["ff"][y] + (im - p["i_eff"][y]) / b_lo
        hi = p["ff"][y] + (im - p["i_eff"][y]) / b_hi
        rule = p["t10"][y] - marg
        print(f"  {y:6d} {f'{min(lo,hi)*100:.2f}-{max(lo,hi)*100:.2f}%':>20} "
              f"{p['ff'][y]*100:7.2f}% {p['t10'][y]*100:8.2f}% "
              f"{rule*100:8.2f}% {f'+{(rule-max(lo,hi))*100:.2f} pp':>18}")
    print("\n  CBO's projected fed funds rate stops in 2036; the long-term files carry no")
    print("  separate 10y, so the rule cannot be run past there.")
    last = max(y for y in p["ff"] if y in p["b"])
    im = p["g"][last] + p["s"][last] / p["b"][last]
    ipm = p["ff"][last] + (im - p["i_eff"][last]) / b_hi
    print(f"\n  At {last}: CBO assumes a {p['ff'][last]*100:.2f}% funds rate and a "
          f"{p['t10'][last]*100:.2f}% 10y. The profit-rate")
    print(f"  rule wants {(p['t10'][last]-marg)*100:.2f}%, "
          f"{(p['t10'][last]-marg-p['ff'][last])*100:+.2f} pp above CBO's own assumption, "
          "and the")
    print(f"  policy ceiling is {ipm*100:.2f}%. The rule and the ceiling are "
          f"{abs(p['t10'][last]-marg-ipm)*100:.2f} pp apart and the")
    print("  rule is on the wrong side of it, which is the same standoff as today, carried")
    print("  forward with no resolution built in.")


# --------------------------------------------------------------------------- 6
def expect(p):
    print("\n" + "=" * 92)
    print("6. WHAT TO EXPECT OF THE POLICY RATE")
    print("=" * 92)
    print("  Taking the projections at face value, four things follow, in descending order")
    print("  of how much this repo can actually support:\n")
    print("  1. THE CEILING DOES NOT TIGHTEN. It moves by under half a point over thirty")
    print("     years. Anyone expecting the debt to mechanically force rates down through")
    print("     this channel is expecting something the arithmetic does not deliver.")
    print()
    print("  2. THE CONFLICT DOES TIGHTEN, through i - g rather than through the ceiling.")
    print("     CBO has the effective rate crossing above nominal growth and staying there.")
    print("     Today that gap is -2.19 pp and idle. Positive, it compounds.")
    print()
    print("  3. THE SELF-FINANCING THRESHOLD FALLS SHARPLY, from phi = 1.77 to about 1.04,")
    print("     and further once QT and the falling foreign share are allowed to raise")
    print("     theta. The unidentified parameter that dominance.py said carries the whole")
    print("     question moves toward the range where the constraint dissolves. That cuts")
    print("     AGAINST the fiscal-dominance reading, not for it.")
    print()
    print("  4. THE STANDOFF PERSISTS RATHER THAN RESOLVES, and it is not our rule that")
    print("     causes it. CBO assumes a 3.33% funds rate against a 4.39% ten-year. The")
    print("     policy ceiling is 1.4-1.7%. CBO's OWN assumed rate breaches its own")
    print("     sustainability ceiling by about 1.6 pp, and the profit-rate rule breaches")
    print("     it by 2.3 pp. The disagreement between the rule and CBO is 0.6 pp; the")
    print("     disagreement between BOTH of them and the ceiling is three times that.")
    print("     Nothing in the baseline closes it, because the baseline is current law and")
    print("     current law does not close it.")
    print()
    print("  WHAT WOULD CHANGE THE ANSWER, in order of leverage: a primary balance that")
    print("  responds to the debt again -- Bohn's coefficient was +0.13 as recently as")
    print("  1996-2011 and is -0.09 now, so this is a switch that has been thrown before")
    print("  and could be thrown back; then theta, which policy moves through the Fed's")
    print("  balance sheet; then phi, which nobody can measure and everybody is implicitly")
    print("  assuming. The rate itself is the least powerful lever on the list, which is")
    print("  the through-line of this whole exercise.")


def main():
    print("CBO'S OUTLOOK, THE FISCAL CEILING, AND THE POLICY BAND\n")
    p = paths()
    baseline(p)
    against_own_ceiling(p)
    ceiling_path(p)
    phi_path(p)
    band(p)
    expect(p)


if __name__ == "__main__":
    main()
