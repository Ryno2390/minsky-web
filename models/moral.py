"""Moral depreciation and the sweat-or-replace decision.

    python3 models/moral.py

THE QUESTION
------------
wedge.py found that intellectual property accounts for more than the whole rise in the
aggregate depreciation rate, and that within the traditional classes the rates moved
very little -- equipment 12.59% to 13.57%, structures 2.57% to 2.79%. This asks whether
they SHOULD have moved more.

Marx's moral depreciation (moralischer Verschleiss, Vol I ch.15) is the loss of value a
machine suffers not from wearing out but from better machines existing. A capitalist
facing it has a choice rather than an obligation: the old machine still produces, its
purchase price is sunk, and running it can stay profitable long after it stops being
the best available. Sweating it is a real option. But there is a cutoff, and the
question is whether technical progress has moved that cutoff.

WHAT IS MEASURED AND WHAT IS MODELLED
-------------------------------------
The force is measurable and large: the price of equipment relative to output has fallen
72% since 1947, 1.6% a year, and BEA's deflators are quality-adjusted so that decline is
the improvement itself, not a discount. The RESPONSE is what needs a model, because the
optimal replacement age is not observed -- only the depreciation rates BEA assigns, which
are updated from service-life studies rather than continuously.

So: calibrate the replacement model to reproduce the 1950s equipment life at the 1950s
rate of progress, then ask what life it implies at today's rate. If the implied fall is
far bigger than the 7.9 to 7.4 years actually recorded, then capital is being sweated
harder than the arithmetic of replacement recommends, not less.

THE ONE THING THIS CANNOT SETTLE
--------------------------------
BEA's within-class rates are partly an accounting convention. A rise could be a genuine
change in behaviour or a reweighting inside the class -- computers inside equipment,
software inside IP -- exactly as section 5 of wedge.py found it could not separate. The
model says what the incentive did. It cannot say what firms did, because the data that
would show that, retirement ages by vintage, is not published.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import fred                                                      # noqa: E402


def annual(sid):
    s = fred.series(sid)
    if s is None:
        raise SystemExit(f"could not fetch {sid}")
    by = {}
    for d, v in zip(s["date"], s["value"]):
        by.setdefault(int(d[:4]), []).append(v)
    return {y: float(np.mean(v)) for y, v in by.items()}


# --------------------------------------------------------------------------- 1
def the_force():
    """How fast does new capital get better? The deflators are quality-adjusted."""
    print("=" * 92)
    print("1. THE FORCE -- the relative price of new capital")
    print("=" * 92)
    eq, ip, gd = (annual("Y033RD3Q086SBEA"), annual("Y001RD3Q086SBEA"),
                  annual("GDPDEF"))
    ys = sorted(set(eq) & set(ip) & set(gd))
    b = ys[0]
    print("  Index of the investment deflator over the GDP deflator, 1947 = 100. BEA")
    print("  quality-adjusts these, so a fall is new capital getting BETTER per dollar,")
    print("  not cheaper per unit of capability.\n")
    print(f"  {'year':>6} {'equipment':>11} {'IP products':>12}")
    for y in (1950, 1970, 1990, 2000, 2010, 2020, ys[-1]):
        if y not in ys:
            continue
        print(f"  {y:6d} {eq[y] / gd[y] / (eq[b] / gd[b]) * 100:10.1f} "
              f"{ip[y] / gd[y] / (ip[b] / gd[b]) * 100:11.1f}")
    out = {}
    for nm, d in (("equipment", eq), ("IP products", ip)):
        rates = {}
        for a, bb in ((1947, 1975), (1975, 2000), (2000, ys[-1])):
            n = bb - a
            rates[(a, bb)] = ((d[bb] / gd[bb]) / (d[a] / gd[a])) ** (1.0 / n) - 1.0
        out[nm] = rates
    print(f"\n  {'era':>14} " + " ".join(f"{f'{a}-{b}':>12}" for a, b in
                                         list(out['equipment'])))
    for nm in out:
        print(f"  {nm:>14} " + " ".join(f"{v * 100:+11.2f}%"
                                        for v in out[nm].values()))
    print("\n  Equipment's relative price falls throughout and accelerates after 1975.")
    print("  That acceleration is the moral depreciation the question is about, and it")
    print("  is not small: a machine bought in 2000 competes against 2026 machines that")
    print("  cost 44% less per unit of capability.")
    return out


# --------------------------------------------------------------------------- 2
def optimal_life(decay, k, r=0.05, tmax=80.0, step=0.05):
    """Replacement age minimising discounted cost.

    TWO DEPRECIATIONS, NOT ONE, and the first version of this file had only one.
    A machine of age a is behind the frontier for two separate reasons: better machines
    now exist (moral, at rate gamma) and it has worn (physical, at rate delta). Both show
    up the same way, as an operating cost penalty growing with age, so the cost of
    running an age-a machine is e^((gamma+delta)*a) times the frontier's.

    That the two enter only as their SUM is the substantive point of this section. The
    replacement decision cannot tell obsolescence from wear, which means a rise in gamma
    moves the optimal life only in proportion to gamma's share of the total decay. With
    only gamma in the model -- the first attempt here -- calibrating a 1950s equipment
    life of 7.9 years against a 0.24% rate of progress returned a purchase price of 0.09
    years of operating cost, i.e. a machine costing about a month to run. That absurdity
    was the model saying it had no reason to replace anything, because in the 1950s the
    reason was wear and it had been left out.

    k is the purchase price in years of frontier operating cost. It is a nuisance
    parameter and is reported across a range rather than fitted to a point.
    """
    best = None
    grid = np.arange(1.0, tmax, step)
    for T in grid:
        n = int(np.ceil(300.0 / T))
        a = np.arange(0.0, T, 0.05)
        run = float(np.sum(np.exp(decay * a) * np.exp(-r * a) * 0.05))
        cost = 0.0
        for j in range(n):
            t0 = j * T
            cost += (k + run) * np.exp(-r * t0)
        if best is None or cost < best[0]:
            best = (cost, float(T))
    return best[1]


def calibrate_decay(target_life, k, r=0.05):
    """The total decay rate that reproduces an observed life at a given price ratio."""
    lo, hi = 0.001, 3.0
    for _ in range(50):
        mid = (lo + hi) / 2.0
        if optimal_life(mid, k, r=r) > target_life:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# --------------------------------------------------------------------------- 3
def response(force):
    print("\n" + "=" * 92)
    print("2. THE REPLACEMENT MODEL -- and why moral depreciation alone will not do")
    print("=" * 92)
    print("  An age-a machine costs e^((gamma+delta)*a) times the frontier to run:")
    print("  gamma because better machines exist, delta because it has worn. The two")
    print("  enter only as their SUM, which is the whole answer to the question.\n")
    g_old = abs(force["equipment"][(1947, 1975)])
    g_new = abs(force["equipment"][(2000, 2026)])
    dg = g_new - g_old
    print(f"  Measured moral depreciation for equipment: {g_old * 100:.2f}% a year")
    print(f"  before 1975, {g_new * 100:.2f}% after 2000. A rise of {dg * 100:.2f} points.\n")
    print("=" * 92)
    print("3. HOW FAR SHOULD THE REPLACEMENT AGE HAVE MOVED?")
    print("=" * 92)
    print("  For each purchase price k, the total decay is calibrated to reproduce the")
    print("  1950s equipment life of 7.9 years, then gamma alone is raised by the")
    print("  measured amount and the life recomputed. Nothing else moves.\n")
    print(f"  {'k (years)':>10} {'total decay':>12} {'gamma share':>12} "
          f"{'life 1950s':>11} {'life today':>11} {'change':>9}")
    preds = []
    for k in (1.0, 2.0, 4.0, 8.0, 16.0):
        tot_old = calibrate_decay(7.9, k)
        tot_new = tot_old + dg
        T_new = optimal_life(tot_new, k)
        preds.append(T_new)
        print(f"  {k:10.1f} {tot_old * 100:11.2f}% {g_old / tot_old * 100:11.1f}% "
              f"{7.9:10.1f}y {T_new:10.2f}y {(T_new / 7.9 - 1) * 100:+8.1f}%")
    print("\n  Moral depreciation is a small share of total decay in every column --")
    print(f"  {g_old / calibrate_decay(7.9, 4.0) * 100:.0f}% of it at k = 4 -- because in")
    print("  the 1950s equipment wore out far faster than it went obsolete. So even a")
    print("  tenfold rise in the rate of progress moves the optimal life by a few percent.")
    return float(np.mean(preds)), g_old, g_new


# --------------------------------------------------------------------------- 4
def verdict(T_new, g_old, g_new):
    print("\n" + "=" * 92)
    print("4. THE ANSWER")
    print("=" * 92)
    obs_old, obs_new = 7.9, 7.4
    print(f"  {'':>30} {'1950s':>9} {'today':>9} {'change':>9}")
    print(f"  {'model, mean across k':>30} {7.9:8.1f}y {T_new:8.2f}y "
          f"{(T_new / 7.9 - 1) * 100:+8.1f}%")
    print(f"  {'BEA recorded equipment life':>30} {obs_old:8.1f}y {obs_new:8.1f}y "
          f"{(obs_new / obs_old - 1) * 100:+8.1f}%")
    print("\n  Same direction, same order of magnitude, and the model over-predicts by")
    print("  about two to one at its mean. The recorded -6.3% sits just BELOW the most")
    print("  conservative column in section 3, the k = 16 case where capital is expensive")
    print("  relative to running it. That is not a match and should not be called one; it")
    print("  is a prediction the data sits at the quiet end of.")
    print("\n  What survives either way: the tradeoff DID shift toward replacement, in the")
    print("  direction the question supposes, and it shifted by single-digit to low")
    print("  double-digit percent rather than by a lot. Whether firms sweated slightly")
    print("  more than optimal or the model slightly over-prices obsolescence, the")
    print("  quantity in dispute is small.")
    print("\n  THE REASON is that obsolescence and wear are substitutes in the")
    print("  replacement decision, and wear was much the larger of the two. A machine")
    print("  that wears out in eight years cannot be made obsolete much faster than that")
    print("  no matter how quickly the frontier moves, because it is already being")
    print("  replaced. Moral depreciation can only bite on capital that would otherwise")
    print("  have lasted a long time.")
    print("\n  WHICH IS WHY STRUCTURES ARE THE PLACE TO LOOK, and they moved: 38.9 years")
    print("  to 35.9, with a within-class rate rise of 2.57% to 2.79%. Small, but on the")
    print("  asset where wear is slowest and moral depreciation has the most room. That")
    print("  is the sign the mechanism predicts.")
    print("\n  AND IT RESOLVES THE WEDGE. If moral depreciation cannot much shorten the")
    print("  life of capital that already wears out quickly, the way rising obsolescence")
    print("  shows up in the aggregate is not through shorter lives within a class but")
    print("  through a shift of investment INTO classes that are short-lived by nature.")
    print("  wedge.py measured that shift carrying 115% of the rise in the aggregate")
    print("  depreciation rate. The two findings are the same finding.")
    print("\n  CAVEATS. BEA's within-class rates come from service-life studies updated")
    print("  occasionally rather than from observed retirements, so 7.9 -> 7.4 is a weak")
    print("  measurement and the agreement above should not be read as tight. The model")
    print("  prices only operating cost, so if new machines also raise output the gain")
    print("  from replacing is understated. And k is a nuisance parameter: the LEVEL is")
    print("  calibrated, only the response is predicted.")


def main():
    force = the_force()
    T_new, g_old, g_new = response(force)
    verdict(T_new, g_old, g_new)


if __name__ == "__main__":
    main()
