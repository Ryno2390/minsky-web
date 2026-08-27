"""Does any of the capital-composition story explain the fall in total factor productivity?

    python3 models/tfp.py

WHERE THIS COMES FROM
---------------------
circuit.py found the circuit of capital got faster, not slower, and the profit rate on
capital advanced nearly back to its 1950s level while real growth halved. wedge.py found
gross investment rising and net investment falling, with intellectual property carrying
more than the whole rise in the depreciation rate -- and capital deepening FLAT, so the
channel that was supposed to transmit the wedge to growth did not. moral.py found
obsolescence cannot much shorten the life of capital that already wears out fast, so it
shows up as buying capital short-lived by nature. hollowing.py found the shift is
economy-wide rather than a manufacturing story.

Every one of those closed a door. What is behind the last one is total factor
productivity, and this asks whether anything found so far bears on it.

TWO QUESTIONS, AND THEY ARE DIFFERENT
-------------------------------------
    1. Is the growth slowdown IN TFP at all, or in capital? If capital's contribution to
       labour productivity held up, then the slowdown is TFP by construction and nothing
       about investment can explain it away.

    2. Does the composition shift itself depress MEASURED TFP? It can, and mechanically.
       Productivity accounting does not weight assets by their dollar value, it weights
       them by their RENTAL price, r + delta - price change. A dollar of intellectual
       property depreciating at 24% carries roughly four times the weight of a dollar of
       structures depreciating at 2.8%, because it has to earn back four times as much
       each year to be worth owning. So as the stock tilts toward short-lived assets,
       measured capital INPUT grows faster than the capital stock, and TFP is what is
       left after subtracting capital input.

That second one is not a measurement error. It is the correct treatment, and it says
something real: the economy put in more capital services and did not get proportionally
more output. The question is how much of the TFP slowdown it accounts for.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import beafa                                                     # noqa: E402
import fred                                                      # noqa: E402

ASSETS = ("structures", "equipment", "ip")
ERAS = [(1950, 1969), (1970, 1979), (1980, 1989), (1990, 1999),
        (2000, 2009), (2010, 2019), (2020, 2024)]

#: real rate in the user cost. The level barely matters for the COMPARISON below --
#: section 4 shows the answer across 2% to 8% -- because it enters every asset's weight.
R = 0.04

#: capital's share of income. The standard third; section 4 varies it.
ALPHA = 0.33


def annual(sid):
    s = fred.series(sid)
    if s is None:
        raise SystemExit(f"could not fetch {sid}")
    by = {}
    for d, v in zip(s["date"], s["value"]):
        by.setdefault(int(d[:4]), []).append(v)
    return {y: float(np.mean(v)) for y, v in by.items()}


def stocks():
    """Real stock, current-cost stock and depreciation by asset class, summed over all
    74 BEA industries."""
    cur, _n = beafa.table("stock")
    real, names = beafa.table("real")
    dep, _d = beafa.table("deprec")
    years = list(range(1948, 2025))

    def tot(tab, a, y):
        return sum(tab[(c, a)].get(y, 0.0) for c in names if (c, a) in tab)

    K = {a: {y: tot(real, a, y) for y in years} for a in ASSETS}
    KC = {a: {y: tot(cur, a, y) for y in years} for a in ASSETS}
    D = {a: {y: tot(dep, a, y) for y in years} for a in ASSETS}
    return K, KC, D, years


def mean_growth(d, a, b):
    g = [d[y] / d[y - 1] - 1.0 for y in range(a, b + 1) if y in d and y - 1 in d]
    return float(np.mean(g)) if g else float("nan")


# --------------------------------------------------------------------------- 1
def slowdown():
    print("=" * 92)
    print("1. THE SLOWDOWN, MEASURED")
    print("=" * 92)
    tfp, lp, emp = annual("MFPNFBS"), annual("OPHNFB"), annual("PAYEMS")
    print("  BLS private nonfarm business.\n")
    print(f"  {'era':>12} {'TFP growth':>11} {'labour prod':>12} {'employment':>11}")
    for a, b in ERAS:
        print(f"  {f'{a}-{b}':>12} {mean_growth(tfp, a, b) * 100:10.2f}% "
              f"{mean_growth(lp, a, b) * 100:11.2f}% "
              f"{mean_growth(emp, a, b) * 100:10.2f}%")
    t0 = mean_growth(tfp, *ERAS[0])
    t1 = float(np.mean([mean_growth(tfp, *e) for e in ERAS[-3:]]))
    print(f"\n  TFP growth {t0 * 100:.2f}% in 1950-69 against {t1 * 100:.2f}% averaged "
          f"over 2000-2024:")
    print(f"  a slowdown of {(t0 - t1) * 100:.2f} points a year. That is the number the")
    print("  rest of this file is trying to account for.")
    return t0 - t1


# --------------------------------------------------------------------------- 2
def where_it_sits(K, KC, D):
    """Is the labour-productivity slowdown in capital or in TFP?"""
    print("\n" + "=" * 92)
    print("2. IS IT CAPITAL OR IS IT TFP?")
    print("=" * 92)
    print("  Labour productivity growth = alpha * capital deepening + TFP growth, with")
    print("  deepening measured on capital SERVICES, which is what the accounting uses.\n")
    tfp, lp, emp = annual("MFPNFBS"), annual("OPHNFB"), annual("PAYEMS")
    ks = services_index(K, KC, D)
    print(f"  {'era':>12} {'K services g':>13} {'employment':>11} {'deepening':>10} "
          f"{'alpha*deep':>11} {'TFP':>7} {'sum':>7} {'actual LP':>10}")
    for a, b in ERAS:
        gs = mean_growth(ks, a, b)
        ge = mean_growth(emp, a, b)
        deep = gs - ge
        gt = mean_growth(tfp, a, b)
        print(f"  {f'{a}-{b}':>12} {gs * 100:12.2f}% {ge * 100:10.2f}% "
              f"{deep * 100:9.2f}% {ALPHA * deep * 100:10.2f}% {gt * 100:6.2f}% "
              f"{(ALPHA * deep + gt) * 100:6.2f}% {mean_growth(lp, a, b) * 100:9.2f}%")
    print("\n  The sum tracks measured labour productivity to a few tenths, which is as")
    print("  close as a hand-built decomposition on a different sector definition gets,")
    print("  and close enough to read the columns.")
    print("\n  The 2000-09 and 2020-24 deepening figures are inflated by employment")
    print("  growth of 0.18% and 0.95%, not by a surge in investment -- deepening is a")
    print("  ratio and its denominator collapsed. Read the decade pattern, not the rows.")
    print("\n  Capital's contribution is flat to rising across the whole period. TFP falls")
    print("  by about a point. So the productivity slowdown is a TFP slowdown, and")
    print("  nothing about the QUANTITY of investment explains it -- which is the same")
    print("  conclusion wedge.py reached from the other direction when capital deepening")
    print("  turned out not to have slowed at all.")


# --------------------------------------------------------------------------- 3
def services_index(K, KC, D, r=R):
    """Rental-price-weighted capital services, chained. Returns {year: index}."""
    years = sorted(K["ip"])
    idx = {years[0]: 100.0}
    for y in years[1:]:
        w, tot = {}, 0.0
        for a in ASSETS:
            if not KC[a].get(y) or not K[a].get(y) or not K[a].get(y - 1):
                continue
            delta = D[a][y] / KC[a][y]
            p0 = KC[a][y - 1] / K[a][y - 1]
            p1 = KC[a][y] / K[a][y]
            pi = p1 / p0 - 1.0
            # user cost of capital. Floored: a year in which an asset's own price rises
            # faster than r + delta gives a negative rental price, which is a real
            # feature of the formula and not usable as a weight.
            w[a] = max(r + delta - pi, 1e-4) * KC[a][y]
            tot += w[a]
        g = sum(w[a] / tot * (K[a][y] / K[a][y - 1] - 1.0) for a in w)
        idx[y] = idx[y - 1] * (1.0 + g)
    return idx


def composition(K, KC, D):
    print("\n" + "=" * 92)
    print("3. THE COMPOSITION CHANNEL, QUANTIFIED")
    print("=" * 92)
    print("  Capital services weight each asset by its rental price, r + delta - price")
    print("  change, so short-lived assets count for more per dollar. The net stock does")
    print("  not. The gap between the two growth rates IS the composition effect.\n")
    ks = services_index(K, KC, D)
    net = {y: sum(K[a][y] for a in ASSETS) for y in sorted(K["ip"])}
    print(f"  {'era':>12} {'K services':>11} {'net stock':>10} {'gap':>8} "
          f"{'alpha*gap':>10} {'IP weight':>10}")
    base = None
    for a, b in ERAS:
        gs, gn = mean_growth(ks, a, b), mean_growth(net, a, b)
        y = b
        ws = {}
        for asset in ASSETS:
            delta = D[asset][y] / KC[asset][y]
            ws[asset] = (R + delta) * KC[asset][y]
        ipw = ws["ip"] / sum(ws.values())
        if base is None:
            base = gs - gn
        print(f"  {f'{a}-{b}':>12} {gs * 100:10.2f}% {gn * 100:9.2f}% "
              f"{(gs - gn) * 100:+7.2f}% {-ALPHA * (gs - gn) * 100:+9.2f}% "
              f"{ipw * 100:9.1f}%")
    last = np.mean([mean_growth(ks, *e) - mean_growth(net, *e) for e in ERAS[-3:]])
    print(f"\n  The gap widens from {base * 100:+.2f} points to {last * 100:+.2f}. The "
          "CHANGE is what matters:")
    print(f"  {(last - base) * 100:.2f} points more capital input for the same stock, "
          f"which at a capital")
    print(f"  share of {ALPHA:.2f} subtracts {ALPHA * (last - base) * 100:.2f} points "
          "from measured TFP growth.")
    print("\n  The last column says why: intellectual property is now nearly a third of")
    print("  capital by RENTAL weight while being about a seventh by dollar value,")
    print("  because it has to earn back a quarter of itself every year.")
    return ALPHA * (last - base)


# --------------------------------------------------------------------------- 4
def robustness(K, KC, D, drag):
    print("\n" + "=" * 92)
    print("4. HOW MUCH OF THAT SURVIVES THE ASSUMPTIONS")
    print("=" * 92)
    net = {y: sum(K[a][y] for a in ASSETS) for y in sorted(K["ip"])}
    print(f"  {'r':>6} {'alpha':>7} {'TFP drag from composition':>28}")
    for r in (0.02, 0.04, 0.08):
        for al in (0.30, 0.33, 0.40):
            ks = services_index(K, KC, D, r=r)
            b0 = mean_growth(ks, *ERAS[0]) - mean_growth(net, *ERAS[0])
            b1 = np.mean([mean_growth(ks, *e) - mean_growth(net, *e) for e in ERAS[-3:]])
            print(f"  {r:6.2f} {al:7.2f} {al * (b1 - b0) * 100:26.2f} pp")
    print("\n  Between a fifth and two fifths of a point across every combination. The")
    print("  real rate barely matters because it enters every asset's weight alike; the")
    print("  capital share scales it directly and is the only assumption doing work.")


# --------------------------------------------------------------------------- 5
def verdict(total, drag):
    print("\n" + "=" * 92)
    print("5. VERDICT")
    print("=" * 92)
    print(f"  TFP growth fell by {total * 100:.2f} points a year. The shift of the capital")
    print(f"  stock toward short-lived assets accounts for about {drag * 100:.2f} of that, "
          f"or {drag / total * 100:.0f}%.")
    print(f"\n  So: part of it, and a real part, but a fifth. The other "
          f"{(1 - drag / total) * 100:.0f}% of the TFP")
    print("  slowdown is not explained by anything in this repo.")
    print("\n  AND THE PART THAT IS EXPLAINED SPLITS THREE WAYS, none of which this can")
    print("  settle:")
    print("\n    IT IS REAL. Firms bought capital that has to earn back a quarter of")
    print("    itself every year, and it did not deliver proportionally more output.")
    print("    On this reading the IP transition was expensive and TFP is telling the")
    print("    truth about it.")
    print("\n    IT IS MISMEASURED OUTPUT. Software and research produce things the")
    print("    national accounts capture badly -- free services, quality, variety. The")
    print("    input is counted at cost and the output is not counted at all.")
    print("\n    IT IS MISMEASURED DEPRECIATION. If BEA's 24% for intellectual property")
    print("    is too high, the rental weights are too high, capital input is overstated")
    print("    and TFP is understated by construction. Note this one is self-sealing:")
    print("    the same number that made the wedge in wedge.py makes the drag here, so")
    print("    an error in it would propagate through everything above.")
    print("\n  WHAT THE WHOLE SEQUENCE ADDS UP TO. The circuit is faster, the profit rate")
    print("  recovered, capital deepening never slowed, and the maintenance proportion")
    print("  rose for a reason that is compositional rather than behavioural. Every")
    print("  quantity-of-capital explanation for the slowdown has been closed off, and")
    print("  what is left is the productivity of capital rather than its amount. This")
    print(f"  section moves about a fifth of that residual back onto the composition")
    print("  shift. The remaining four fifths are genuinely unexplained here, and the")
    print("  honest thing is to say so rather than keep decomposing until something fits.")


def main():
    K, KC, D, _years = stocks()
    total = slowdown()
    where_it_sits(K, KC, D)
    drag = composition(K, KC, D)
    robustness(K, KC, D, drag)
    verdict(total, drag)


if __name__ == "__main__":
    main()
