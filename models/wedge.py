"""The wedge between gross and net investment, and where it came from.

    python3 models/wedge.py

THE HYPOTHESIS
--------------
circuit.py found that fixed capital lives shortened -- 17.9 years to 12.3 on the corporate
stock -- while every other measure of the circuit got faster. This module asks the
question that leaves open. Gross investment splits exactly two ways:

    gross investment = replacing what wore out + adding to the stock
                     =    depreciation         +    net investment

so if depreciation takes a rising share, net investment can fall while gross investment
rises. The proposed mechanism is compositional: the capital stock shifted out of
long-lived structures and into short-lived software and intellectual property, which
lowers the average service life without anything within a class changing at all.

That is a shift-share, and it can be tested rather than told. The aggregate depreciation
rate is a weighted average of the rates by asset class,

    delta = sum_i  w_i * delta_i          w_i the class's share of the stock

so the change in delta decomposes into a part from the WEIGHTS moving and a part from
the RATES moving, with an interaction term that has to be reported rather than
distributed. If the composition term carries most of it, the hypothesis holds.

DATA
----
BEA Fixed Assets tables, private nonresidential, current cost, 1925-2024, in three
classes: structures, equipment, and intellectual property products. Depreciation and net
stock are both published per class, so the rates are measured and not assumed -- which
matters, because assuming them is how a decomposition like this gets its answer put in
by hand.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import fred                                                      # noqa: E402

CLASSES = [("structures", "K1NTOTL1ST000", "M1NTOTL1ST000"),
           ("equipment", "K1NTOTL1EQ000", "M1NTOTL1EQ000"),
           ("IP products", "K1NTOTL1IP000", "M1NTOTL1IP000")]

#: gross private nonresidential fixed investment, by the same three classes
INVEST = {"structures": "B009RC1Q027SBEA", "equipment": "Y033RC1Q027SBEA",
          "IP products": "Y001RC1Q027SBEA"}

ERAS = [(1950, 1959), (1960, 1969), (1970, 1979), (1980, 1989),
        (1990, 1999), (2000, 2009), (2010, 2019), (2020, 2024)]


def annual(sid, scale=1.0):
    """{year: value}. Quarterly series are averaged to the year."""
    s = fred.series(sid)
    if s is None:
        raise SystemExit(f"could not fetch {sid}")
    by = {}
    for d, v in zip(s["date"], s["value"]):
        by.setdefault(int(d[:4]), []).append(v * scale)
    return {y: float(np.mean(v)) for y, v in by.items()}


def panel():
    K = {nm: annual(k, 1e-3) for nm, k, _m in CLASSES}
    M = {nm: annual(m, 1e-3) for nm, _k, m in CLASSES}
    I = {nm: annual(sid) for nm, sid in INVEST.items()}
    gdp = annual("GDP")
    years = sorted(set.intersection(*(set(d) for d in list(K.values()) + list(M.values())
                                      + list(I.values()) + [gdp])))
    rows = []
    for y in years:
        r = {"year": y, "gdp": gdp[y]}
        for nm, _k, _m in CLASSES:
            r[f"K_{nm}"] = K[nm][y]
            r[f"M_{nm}"] = M[nm][y]
            r[f"I_{nm}"] = I[nm][y]
        r["K"] = sum(r[f"K_{nm}"] for nm, _, _ in CLASSES)
        r["M"] = sum(r[f"M_{nm}"] for nm, _, _ in CLASSES)
        r["I"] = sum(r[f"I_{nm}"] for nm, _, _ in CLASSES)
        r["net"] = r["I"] - r["M"]
        rows.append(r)
    return rows


def era(rows, a, b):
    sel = [r for r in rows if a <= r["year"] <= b]
    if not sel:
        return None
    out = {k: float(np.mean([r[k] for r in sel])) for k in sel[0]}
    out["label"] = f"{a}-{b}"
    return out


# --------------------------------------------------------------------------- 1
def the_wedge(rows):
    print("=" * 92)
    print("1. THE WEDGE -- gross investment, what it replaces, and what is left")
    print("=" * 92)
    print("  Private nonresidential fixed investment, current dollars, against GDP.\n")
    print(f"  {'era':>10} {'gross/GDP':>10} {'deprec/GDP':>11} {'net/GDP':>9} "
          f"{'maintenance':>12} {'net share':>10}")
    for a, b in ERAS:
        m = era(rows, a, b)
        if m is None:
            continue
        print(f"  {m['label']:>10} {m['I'] / m['gdp'] * 100:9.2f}% "
              f"{m['M'] / m['gdp'] * 100:10.2f}% {m['net'] / m['gdp'] * 100:8.2f}% "
              f"{m['M'] / m['I'] * 100:11.1f}% {m['net'] / m['I'] * 100:9.1f}%")
    first, last = era(rows, *ERAS[0]), era(rows, *ERAS[-1])
    print(f"\n  Gross investment went {first['I'] / first['gdp'] * 100:.2f}% of GDP to "
          f"{last['I'] / last['gdp'] * 100:.2f}%, and net investment went")
    print(f"  {first['net'] / first['gdp'] * 100:.2f}% to {last['net'] / last['gdp'] * 100:.2f}%. "
          "The maintenance proportion is the whole of the difference:")
    print(f"  {first['M'] / first['I'] * 100:.1f}% of gross investment went to replacement then, "
          f"{last['M'] / last['I'] * 100:.1f}% now.")


# --------------------------------------------------------------------------- 2
def rates(rows):
    print("\n" + "=" * 92)
    print("2. DEPRECIATION RATES AND LIVES BY ASSET CLASS -- measured, not assumed")
    print("=" * 92)
    print("  BEA publishes depreciation and net stock separately for each class, so the")
    print("  rate is a ratio of two observed numbers.\n")
    print(f"  {'era':>10} | " + " | ".join(f"{nm:>22}" for nm, _, _ in CLASSES))
    print(f"  {'':>10} | " + " | ".join(f"{'rate':>9} {'life':>6} {'share':>5}"
                                        for _ in CLASSES))
    for a, b in ERAS:
        m = era(rows, a, b)
        if m is None:
            continue
        cells = []
        for nm, _, _ in CLASSES:
            d = m[f"M_{nm}"] / m[f"K_{nm}"]
            cells.append(f"{d * 100:8.2f}% {1 / d:5.1f}y {m[f'K_{nm}'] / m['K'] * 100:4.0f}%")
        print(f"  {m['label']:>10} | " + " | ".join(cells))
    last = era(rows, *ERAS[-1])
    ds = {nm: last[f"M_{nm}"] / last[f"K_{nm}"] for nm, _, _ in CLASSES}
    print(f"\n  IP products depreciate {ds['IP products'] / ds['structures']:.1f} times "
          "as fast as structures, and their share")
    first = era(rows, *ERAS[0])
    print(f"  of the stock went {first['K_IP products'] / first['K'] * 100:.1f}% to "
          f"{last['K_IP products'] / last['K'] * 100:.1f}%. That is the mechanism, stated. "
          "Whether it is")
    print("  big enough is the next section.")


# --------------------------------------------------------------------------- 3
def shift_share(rows):
    print("\n" + "=" * 92)
    print("3. SHIFT-SHARE -- composition against within-class")
    print("=" * 92)
    a0, b0 = ERAS[0]
    a1, b1 = ERAS[-1]
    m0, m1 = era(rows, a0, b0), era(rows, a1, b1)
    w0 = {nm: m0[f"K_{nm}"] / m0["K"] for nm, _, _ in CLASSES}
    w1 = {nm: m1[f"K_{nm}"] / m1["K"] for nm, _, _ in CLASSES}
    d0 = {nm: m0[f"M_{nm}"] / m0[f"K_{nm}"] for nm, _, _ in CLASSES}
    d1 = {nm: m1[f"M_{nm}"] / m1[f"K_{nm}"] for nm, _, _ in CLASSES}
    agg0 = sum(w0[nm] * d0[nm] for nm in w0)
    agg1 = sum(w1[nm] * d1[nm] for nm in w1)
    comp = sum((w1[nm] - w0[nm]) * d0[nm] for nm in w0)
    within = sum(w0[nm] * (d1[nm] - d0[nm]) for nm in w0)
    inter = sum((w1[nm] - w0[nm]) * (d1[nm] - d0[nm]) for nm in w0)
    tot = agg1 - agg0
    print(f"  Aggregate depreciation rate {m0['label']} -> {m1['label']}: "
          f"{agg0 * 100:.2f}% -> {agg1 * 100:.2f}%, a rise of {tot * 100:.2f} pp\n")
    print(f"  {'term':>34} {'pp':>8} {'share of the rise':>18}")
    for lab, v in (("COMPOSITION  weights move", comp),
                   ("WITHIN-CLASS  rates move", within),
                   ("interaction", inter)):
        print(f"  {lab:>34} {v * 100:+7.2f} {v / tot * 100:17.0f}%")
    print(f"  {'total':>34} {tot * 100:+7.2f} {100:17.0f}%")
    print("\n  The interaction is reported rather than split between the other two,")
    print("  because there is no non-arbitrary way to allocate it and it is large enough")
    print("  here to change the headline if it were quietly assigned.")
    print(f"\n  {'per class, composition contribution':>44}")
    for nm, _, _ in CLASSES:
        print(f"  {nm:>34} {(w1[nm] - w0[nm]) * d0[nm] * 100:+7.2f} pp   "
              f"weight {w0[nm] * 100:.0f}% -> {w1[nm] * 100:.0f}%")
    print(f"\n  {'per class, within contribution':>44}")
    for nm, _, _ in CLASSES:
        print(f"  {nm:>34} {w0[nm] * (d1[nm] - d0[nm]) * 100:+7.2f} pp   "
              f"rate {d0[nm] * 100:.2f}% -> {d1[nm] * 100:.2f}%")
    return comp, within, inter, tot



# --------------------------------------------------------------------------- 4
def per_class(rows):
    """The attribution that needs no interaction term, because there is not one.

    Section 3's three-way split is standard and it buries the answer: IP products'
    contribution is spread across all three terms, so no single one is large and the
    headline reads as an even split. The change in the aggregate rate is exactly the sum
    of the changes in each class's CONTRIBUTION w_i*delta_i, with nothing left over:

        delta(sum_i w_i delta_i) = sum_i delta(w_i delta_i)

    which attributes each class its weight change, its rate change, and the product of
    the two, all at once and without a choice being made.
    """
    print("\n" + "=" * 92)
    print("4. THE SAME NUMBERS WITHOUT AN INTERACTION TERM TO ALLOCATE")
    print("=" * 92)
    m0, m1 = era(rows, *ERAS[0]), era(rows, *ERAS[-1])
    tot0 = tot1 = 0.0
    print(f"  {'class':>14} {'w*delta then':>13} {'w*delta now':>12} {'change':>9} "
          f"{'share of rise':>14}")
    agg0 = sum(m0[f"M_{nm}"] / m0["K"] for nm, _, _ in CLASSES)
    agg1 = sum(m1[f"M_{nm}"] / m1["K"] for nm, _, _ in CLASSES)
    tot = agg1 - agg0
    for nm, _, _ in CLASSES:
        c0 = m0[f"M_{nm}"] / m0["K"]
        c1 = m1[f"M_{nm}"] / m1["K"]
        tot0 += c0; tot1 += c1
        print(f"  {nm:>14} {c0 * 100:12.2f}% {c1 * 100:11.2f}% {(c1 - c0) * 100:+8.2f} "
              f"{(c1 - c0) / tot * 100:13.0f}%")
    print(f"  {'total':>14} {tot0 * 100:12.2f}% {tot1 * 100:11.2f}% {tot * 100:+8.2f} "
          f"{100:13.0f}%")
    print("\n  THAT is the hypothesis, and it is stronger than the three-way split made")
    print("  it look. Intellectual property alone accounts for MORE than the whole rise")
    print("  in the depreciation rate. It is partly offset by equipment, whose share of")
    print("  the stock fell from 31% to 26% and which depreciates five times faster than")
    print("  structures, so losing equipment weight pushed the aggregate rate DOWN.")
    print("\n  Net of that offset the arithmetic is: IP products up 2.8 points, equipment")
    print("  down 0.4, structures flat, total up 2.4.")


# --------------------------------------------------------------------------- 5
def inside_ipp():
    """Is IP's own rate rise itself composition? Suggestive, not decomposed."""
    print("\n" + "=" * 92)
    print("5. INSIDE INTELLECTUAL PROPERTY -- as far as the data goes")
    print("=" * 92)
    print("  Section 2 has IP's own depreciation rate rising 15.6% to 24.1%, which the")
    print("  three-class decomposition has to call a WITHIN-class change. It may not be:")
    print("  software is written off in a few years and research is not, so a shift")
    print("  toward software inside the class would look identical from outside.")
    print("\n  BEA publishes no depreciation for the sub-classes, so this cannot be")
    print("  decomposed. Z.1 does publish the corporate stocks, which is enough to say")
    print("  whether the shift happened:\n")
    sub = {"software": "BOGZ1FL105013365Q", "R&D": "BOGZ1FL105013465Q",
           "originals": "BOGZ1FL105013565Q"}
    data = {k: annual(v, 1e-3) for k, v in sub.items()}
    years = sorted(set.intersection(*(set(d) for d in data.values())))
    print(f"  {'year':>6} {'software':>10} {'R&D':>9} {'originals':>10} | "
          f"{'software share of IP':>21}")
    for y in (1960, 1970, 1980, 1990, 2000, 2010, 2020, max(years)):
        if y not in years:
            continue
        tot = sum(data[k][y] for k in data)
        print(f"  {y:6d} {data['software'][y]:10.0f} {data['R&D'][y]:9.0f} "
              f"{data['originals'][y]:10.0f} | "
              f"{data['software'][y] / tot * 100:20.1f}%")
    print("\n  Software goes from nothing to about a sixth of the corporate IP stock by")
    print("  2000 and then STOPS, holding between 15% and 17% for twenty-five years while")
    print("  the aggregate IP rate kept climbing from 22% to 24%. So the sub-composition")
    print("  happened, it is part of the story, and it cannot be all of it -- the timing")
    print("  does not line up after 2000. Saying which part would need depreciation by")
    print("  sub-class, which is not published, and no more is claimed here.")


# --------------------------------------------------------------------------- 6
def deepening(rows):
    """The channel the wedge is supposed to act through: capital per worker."""
    print("\n" + "=" * 92)
    print("6. DOES IT REACH CAPITAL PER WORKER?")
    print("=" * 92)
    print("  The wedge matters only if it slows capital deepening. The capital stock")
    print("  grows at net investment over the stock, so deepening is that less the growth")
    print("  of employment:\n")
    print("      capital deepening = net investment / K  -  employment growth\n")
    emp = annual("PAYEMS")
    print(f"  {'era':>10} {'net inv/K':>10} {'employment g':>13} {'deepening':>10}")
    for a, b in ERAS:
        m = era(rows, a, b)
        if m is None:
            continue
        gs = [emp[y] / emp[y - 1] - 1.0 for y in range(a, b + 1)
              if y in emp and y - 1 in emp]
        if not gs:
            continue
        gk = m["net"] / m["K"]
        gl = float(np.mean(gs))
        print(f"  {m['label']:>10} {gk * 100:9.2f}% {gl * 100:12.2f}% "
              f"{(gk - gl) * 100:9.2f}%")
    print("\n  AND THIS IS WHERE THE CHAIN BREAKS. Net investment over the capital stock")
    print("  falls by a third, 3.10% to 2.04%. Employment growth falls by half, 2.02% to")
    print("  0.95%. The two very nearly cancel, and capital deepening ends at 1.09% a")
    print("  year against 1.08% in the fifties -- flat, not halved.")
    print("\n  The 2.21% in 2000-09 is not a boom in deepening, it is a decade whose")
    print("  employment growth was 0.18%, and the 0.75% in 2010-19 is its mirror. The")
    print("  series is noisy at decade length and the level is what to read, not the")
    print("  path.")
    print("\n  So the wedge is real, its cause is largely identified, and the channel it")
    print("  was supposed to act through does not show up. Less net investment did not")
    print("  mean less capital per worker, because there were proportionately fewer new")
    print("  workers to equip. Whatever the fall in net investment cost the economy, it")
    print("  was not paid in the capital-labour ratio.")



def main():
    rows = panel()
    print(f"BEA fixed assets, private nonresidential, {rows[0]['year']}-{rows[-1]['year']}\n")
    the_wedge(rows)
    rates(rows)
    shift_share(rows)
    per_class(rows)
    inside_ipp()
    deepening(rows)


if __name__ == "__main__":
    main()
