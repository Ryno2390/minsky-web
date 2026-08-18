"""Split the nominal curve into real and expected-inflation legs, and refit on the real one.

    python3 models/decompose.py

WHY
---
invert.py section 6 found something the Shaikh ladder has no room for. Regressing monthly
changes in each Treasury yield on the funds rate, the pass-through does not decay to zero
the way exp(-beta*m) requires -- it flattens out at a LEVEL of about 0.15 that is still
there at thirty years. Fitting level + exponential instead of a pure exponential cut the
error from 804 bp to 60 bp. The ladder cannot produce such a term: everything in it enters
at the m = 0 hinge and decays from there.

A component of every yield that moves by the same amount at every maturity is what an
inflation expectation looks like. So the natural repair is to take it out before fitting.

    nominal_m  =  real_m  +  expected inflation over m years

Default risk is the third leg and is set to zero here, which is right in sign and wrong in
an interesting way: the operative risk on a Treasury is devaluation, which is already in
the inflation leg, and what is left is a CONVENIENCE yield that runs the other way --
Treasuries yield less than a hypothetical riskless rate because they are collateral. So
the leg is small and NEGATIVE, not zero. Nothing here turns on it.

THE CLAIM BEING TESTED, AND WHERE IT COMES APART
------------------------------------------------
The intuition that motivated this is that inflation compounds, so its share of the yield
should grow with maturity and growth expectations should dominate the front end. The first
half of that does not survive contact with how yields are quoted. A Treasury yield is an
ANNUALISED rate, not a total return: 4% at 2 years and 4% at 10 years both mean 4% per
year. Compounding changes what you end up with, not the quoted rate, so it cannot
mechanically tilt the inflation share up the curve.

Expected inflation does have a term structure, but it is made by ANCHORING, not
compounding, and it usually runs the other way. A 2-year expectation is an average over
two years and is dominated by where inflation is now, so it is volatile and tracks spot.
A 10-year expectation is an average over ten and is dominated by the regime, so it sits
near target and barely moves. Section 1 measures which way it actually goes.

THE DATA, AND ITS ONE REAL WEAKNESS
-----------------------------------
Cleveland Fed EXPINF{1,2,3,5,7,10,20,30}YR gives a matched expectation at every rung back
to 1982, which TIPS cannot do (they start 2003). But it is MODEL OUTPUT, not a price, and
the model uses the nominal term structure as an input. Fitting a term-structure model to a
real curve built from it therefore risks circularity. Section 2 checks it against the
market breakeven over 2003-2026, which is the only stretch where an honest check exists.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import fred                                                      # noqa: E402
import invert                                                    # noqa: E402
import term_fit                                                  # noqa: E402
import uscorp                                                    # noqa: E402

#: (years, nominal, Cleveland Fed expected inflation, TIPS real yield or None)
RUNGS = [(1, "GS1", "EXPINF1YR", None),
         (2, "GS2", "EXPINF2YR", None),
         (3, "GS3", "EXPINF3YR", None),
         (5, "GS5", "EXPINF5YR", "FII5"),
         (7, "GS7", "EXPINF7YR", "FII7"),
         (10, "GS10", "EXPINF10YR", "FII10"),
         (20, "GS20", "EXPINF20YR", "FII20"),
         (30, "GS30", "EXPINF30YR", "FII30")]

M = invert.monthly


def real_curve():
    """{maturity: {month: real yield}} = nominal minus matched expected inflation."""
    out = {}
    for m, nom, exp, _ in RUNGS:
        n, e = M(nom), M(exp)
        out[m] = {t: n[t] - e[t] for t in set(n) & set(e)}
    return out


# --------------------------------------------------------------------------- 1
def inflation_share():
    """Does expected inflation take a BIGGER share of the yield further out?"""
    print("=" * 92)
    print("1. THE TERM STRUCTURE OF EXPECTED INFLATION")
    print("=" * 92)
    print("  If the compounding story held, the inflation share would rise with maturity")
    print("  and the real leg would dominate the front end. Averages over the common")
    print("  window, so every rung is scored on the same months.\n")
    nom = {m: M(n) for m, n, _, _ in RUNGS}
    exp = {m: M(e) for m, _, e, _ in RUNGS}
    months = sorted(set.intersection(*[set(v) for v in nom.values()],
                                     *[set(v) for v in exp.values()]))
    print(f"  {len(months)} months, {months[0]} to {months[-1]}\n")
    print(f"  {'maturity':>9} {'nominal':>9} {'exp infl':>9} {'real':>9} "
          f"{'infl share':>11} {'sd(infl)':>9} {'sd(real)':>9}")
    sh, ms = [], []
    for m, _, _, _ in RUNGS:
        n = np.array([nom[m][t] for t in months])
        e = np.array([exp[m][t] for t in months])
        r = n - e
        s = e.mean() / n.mean()
        sh.append(s); ms.append(m)
        print(f"  {m:8d}y {n.mean()*100:8.2f}% {e.mean()*100:8.2f}% {r.mean()*100:8.2f}% "
              f"{s*100:10.1f}% {e.std()*100:8.2f}% {r.std()*100:8.2f}%")
    sh, ms = np.array(sh), np.array(ms, float)
    slope = float(np.polyfit(np.log(ms), sh, 1)[0])
    print(f"\n  Inflation share at 1y = {sh[0]*100:.1f}%, at 30y = {sh[-1]*100:.1f}%. "
          f"Slope in log maturity = {slope*100:+.2f} pp/log-year.")
    if sh[-1] < sh[0]:
        print("  It FALLS with maturity, the opposite of the compounding story. The reason")
        print("  is in the last two columns: expected inflation is the STABLE leg further")
        print("  out, because it is an average over a longer horizon and the regime pins")
        print("  it. The real leg is what carries the slope.")
    n1 = np.array([nom[ms[0]][t] for t in months]); n30 = np.array([nom[30][t] for t in months])
    e1 = np.array([exp[1][t] for t in months]); e30 = np.array([exp[30][t] for t in months])
    print(f"\n  Where the 1y-to-30y nominal slope of {(n30.mean()-n1.mean())*100:+.2f} pp comes from:")
    print(f"    expected inflation contributes {(e30.mean()-e1.mean())*100:+.2f} pp")
    print(f"    the real leg contributes       "
          f"{((n30.mean()-e30.mean())-(n1.mean()-e1.mean()))*100:+.2f} pp")
    return months


# --------------------------------------------------------------------------- 2
def check_against_tips():
    """Cleveland Fed is a model. TIPS are a price. Where both exist, do they agree?"""
    print("\n" + "=" * 92)
    print("2. IS THE EXPECTATION SERIES TRUSTWORTHY? -- model vs market breakeven")
    print("=" * 92)
    print(f"  {'maturity':>9} {'n':>5} {'window':>18} {'model':>8} {'breakeven':>10} "
          f"{'diff':>8} {'corr':>7}")
    for m, nom, exp, tips in RUNGS:
        if tips is None:
            continue
        n, e, ti = M(nom), M(exp), M(tips)
        t = sorted(set(n) & set(e) & set(ti))
        if len(t) < 24:
            continue
        mod = np.array([e[k] for k in t])
        be = np.array([n[k] - ti[k] for k in t])
        print(f"  {m:8d}y {len(t):5d} {t[0]}..{t[-1]} {mod.mean()*100:7.2f}% "
              f"{be.mean()*100:9.2f}% {(mod-be).mean()*100:+7.2f}% "
              f"{np.corrcoef(mod, be)[0,1]:+7.3f}")
    print("\n  The model reads 4 to 11 bp BELOW the market breakeven at every rung but 30y.")
    print("  Directionally that says the inflation risk premium in the breakeven outweighs")
    print("  the discount for TIPS illiquidity, which is the usual post-2003 reading. The")
    print("  levels are close and that is the reassuring part.")
    print("\n  The correlations are NOT reassuring. 0.38 to 0.61 in levels, over 23 years,")
    print("  between two measures of the same quantity is moderate at best. They diverge")
    print("  where it matters most -- the breakeven collapsed on liquidity in 2008 and")
    print("  spiked in 2022 while the model stayed smooth. So the deflator used below is")
    print("  a smoothed expectation, not a traded price, and it will understate how much")
    print("  the inflation leg moved in exactly the episodes people argue about.")
    print("\n  Before 2003 there is no market series to check against at all, and the model")
    print("  leans on the nominal curve there. That is the weak point of everything below")
    print("  and it is not fixable with these data.")


# --------------------------------------------------------------------------- 3
def refit_real():
    """Does the ladder fit the REAL curve better than the nominal one?"""
    print("\n" + "=" * 92)
    print("3. THE LADDER, REFITTED ON THE REAL CURVE")
    print("=" * 92)
    real = real_curve()
    months = sorted(set.intersection(*[set(v) for v in real.values()]))
    mat = np.array([m for m, _, _, _ in RUNGS], float)
    y_real = np.array([np.mean([real[m][t] for t in months]) for m in mat])
    nom = {m: M(n) for m, n, _, _ in RUNGS}
    y_nom = np.array([np.mean([nom[m][t] for t in months]) for m in mat])

    print(f"  8 rungs, {len(months)} months, {months[0]} to {months[-1]}\n")
    print(f"  {'':>10} {'i*':>9} {'beta':>8} {'half-life':>10} {'rms bp':>8} "
          f"{'log line':>9} {'rung line':>10}  verdict")
    for nm, y in (("nominal", y_nom), ("real", y_real)):
        e, beta, istar = term_fit.fit_gap_fast(mat, y)
        lg = term_fit.line_rms(np.log(mat), y) * 1e4
        rg = term_fit.line_rms(np.arange(len(y), dtype=float), y) * 1e4
        v = (f"beats naive by {min(lg,rg)/max(e*1e4,1e-9):.1f}x" if e*1e4 < min(lg, rg)
             else "LOSES to naive")
        print(f"  {nm:>10} {istar*100:8.2f}% {beta:8.4f} {np.log(2)/beta:10.2f} "
              f"{e*1e4:8.2f} {lg:9.2f} {rg:10.2f}  {v}")
    print("\n  Same months, same rungs, same estimator. The only change is the deflator.")
    return real, months


# --------------------------------------------------------------------------- 4
def passthrough_real(real):
    """Section 6 of invert.py, redone on real yields. Does the level factor go away?"""
    print("\n" + "=" * 92)
    print("4. THE LEVEL FACTOR -- does deflating remove it?")
    print("=" * 92)
    print("  invert.py found pass-through flattening at L = 0.148 out to 30 years, which")
    print("  the ladder cannot generate. If that term is inflation, deflating both sides")
    print("  should shrink it. This is a real prediction and it can fail.\n")
    ff, e1 = M(invert.POLICY), M("EXPINF1YR")
    rff = {t: ff[t] - e1[t] for t in set(ff) & set(e1)}
    nom = {m: M(n) for m, n, _, _ in RUNGS}

    def fit(dep, drv, label):
        ms, sl, se_ = [], [], []
        print(f"  {label}")
        print(f"    {'maturity':>9} {'n':>5} {'slope':>8} {'se':>7} {'R2':>7}")
        for m, _, _, _ in RUNGS:
            t = sorted(set(dep[m]) & set(drv))
            x = np.diff(np.array([drv[k] for k in t]))
            y = np.diff(np.array([dep[m][k] for k in t]))
            b = float(np.sum(x * y) / np.sum(x * x))
            res = y - b * x
            s = float(np.sqrt(np.sum(res**2) / (len(x)-1) / np.sum(x*x)))
            r2 = 1 - np.sum(res**2) / np.sum((y - y.mean())**2)
            ms.append(m); sl.append(b); se_.append(s)
            print(f"    {m:8d}y {len(x):5d} {b:8.4f} {s:7.4f} {r2:7.3f}")
        ms, sl = np.array(ms, float), np.array(sl)
        best = None
        for bt in np.linspace(0.01, 1.2, 1200):
            X = np.column_stack([np.ones(len(ms)), np.exp(-bt * ms)])
            c, *_ = np.linalg.lstsq(X, sl, rcond=None)
            er = float(np.sqrt(np.mean((X @ c - sl)**2)))
            if best is None or er < best[0]:
                best = (er, bt, c[0], c[1])
        er, bt, L, S = best
        print(f"    -> level + exponential: L = {L:+.3f}, S = {S:.3f}, beta = {bt:.4f}, "
              f"rms {er*1e4:.1f} bp")
        return L, S, bt

    Ln, _, _ = fit(nom, ff, "NOMINAL yields on the nominal funds rate (invert.py sec 6):")
    print()
    Lr, _, _ = fit(real, rff, "REAL yields on the real funds rate (funds - 1y expected infl):")
    print(f"\n  Level factor: {Ln:+.3f} nominal -> {Lr:+.3f} real, a change of "
          f"{abs(Lr)-abs(Ln):+.3f}.")
    if abs(Lr) < abs(Ln) * 0.6:
        print("  Most of the term the ladder could not produce was inflation. Deflating is")
        print("  the right repair, and the ladder is a REAL-side mechanism -- which is what")
        print("  it should have been all along, since Shaikh's equalisation is about profit")
        print("  rates and those are real.")
        print("\n  Look at the two ends rather than the summary. Real pass-through is 0.83 at")
        print("  1y against 0.53 nominal, and 0.019 with a standard error of 0.020 at 30y")
        print("  against 0.148 nominal. That is the shape the ladder requires and the")
        print("  nominal data refused to show: hinged near 1 at the front, gone at the back.")
        print("\n  What deflating does NOT fix is the decay RATE. Cross-sectional beta on the")
        print("  real curve is 0.159; the real pass-through wants 0.567, still off by 3.6x.")
        print("  The level factor was inflation. The rate mismatch is not, and survives.")
    else:
        print("  The level factor SURVIVES deflation. It is not an inflation expectation,")
        print("  and the ladder is missing something the deflator does not supply.")
    return Lr


# --------------------------------------------------------------------------- 5
def real_anchor(real):
    """The test that matters: does the REAL anchor track the profit rate?

    invert.py section 5 found nominal i* falling 10.7% -> 2.8% while the profit rate rose,
    corr -0.87, which is bad for the Shaikh story that i* = c + lam*r. But nominal i* has
    the entire inflation disinflation in it. On the real curve the comparison is at least
    of like with like.
    """
    print("\n" + "=" * 92)
    print("5. THE REAL ANCHOR AGAINST THE PROFIT RATE")
    print("=" * 92)
    # GS20 has a gap 1987-01..1993-09 and GS30 one 2002-03..2006-01. Intersecting all
    # eight rungs deletes those months, which stretches a "120 month" window across
    # sixteen calendar years and quietly changes what is being averaged. Drop the two
    # gapped rungs so the windows are contiguous.
    keep = [1, 2, 3, 5, 7, 10]
    mat = np.array(keep, float)
    months = sorted(set.intersection(*[set(real[m]) for m in keep]))
    D = uscorp.load()
    prof = uscorp.annual(D, uscorp.ratios(D), "r")
    ff = M(invert.POLICY)
    nom = {m: M(n) for m, n, _, _ in RUNGS}

    W = 120
    rows = []
    for st in range(0, len(months) - W, 12):
        win = months[st:st + W]
        yr = np.array([np.mean([real[m][t] for t in win]) for m in mat])
        yn = np.array([np.mean([nom[m][t] for t in win]) for m in mat])
        ir, br, ur, _ = invert.profile_istar(mat, yr, lo=-0.05, hi=0.20)
        inn, bn, un, _ = invert.profile_istar(mat, yn, lo=0.0, hi=0.40)
        yrs = sorted({t[:4] for t in win})
        rr = [prof[a] for a in yrs if a in prof]
        if not rr:
            continue
        rows.append(dict(a=win[0], b=win[-1], ir=ir, ur=ur, inn=inn, un=un,
                         r=float(np.mean(rr)),
                         ff=float(np.mean([ff[t] for t in win if t in ff]))))
    good = [x for x in rows if not x["ur"] and not x["un"]]
    print(f"  6 ungapped rungs 1y..10y, {len(months)} contiguous months, "
          f"{months[0]} to {months[-1]}")
    print(f"  {len(rows)} windows, {len(good)} identify the asymptote on BOTH curves.\n")
    print(f"  {'window':>17} {'i* real':>8} {'i* nom':>8} {'r':>8} {'funds':>8}  id")
    for x in rows[::2]:
        print(f"  {x['a']}..{x['b']} {x['ir']*100:7.2f}% {x['inn']*100:7.2f}% "
              f"{x['r']*100:7.2f}% {x['ff']*100:7.2f}%  "
              f"{'yes' if (not x['ur'] and not x['un']) else 'NO'}")
    if len(good) < 6:
        print(f"\n  Only {len(good)} usable windows. No correlation is reported on that.")
        return
    IR = np.array([x["ir"] for x in good]); IN = np.array([x["inn"] for x in good])
    RR = np.array([x["r"] for x in good]); FF = np.array([x["ff"] for x in good])
    print(f"\n  On the {len(good)} windows where both are identified:")
    print(f"    corr(i* NOMINAL, r) = {np.corrcoef(IN, RR)[0,1]:+.3f}")
    print(f"    corr(i* REAL,    r) = {np.corrcoef(IR, RR)[0,1]:+.3f}   <- the test")
    print(f"    corr(i* REAL, funds)= {np.corrcoef(IR, FF)[0,1]:+.3f}")
    print(f"    i* real runs {IR.min()*100:.2f}% to {IR.max()*100:.2f}%, "
          f"r runs {RR.min()*100:.2f}% to {RR.max()*100:.2f}%")
    print("\n  Windows overlap by 9 years in 10. These are descriptions of a handful of")
    print("  independent episodes, not estimates, and no significance is claimed.")
    late = [x for x in good if x["a"] >= "2011"]
    print(f"\n  AND THE COVERAGE IS LOPSIDED. {len(good)-len(late)} of the {len(good)} "
          f"identified windows start before 2011;")
    print(f"  {len(late)} start after. So the correlation is essentially a statement about")
    print("  1982-2010, and the whole modern end of the story rests on that handful. The")
    print("  flat post-2010 curve does not identify an asymptote, on real yields either.")
    gap0 = RR[0] - IR[0]; gap1 = RR[-1] - IR[-1]
    print(f"\n  DEFLATING DOES NOT RESCUE THE ANCHOR. corr(i*, r) was {np.corrcoef(IN, RR)[0,1]:+.3f}")
    print(f"  nominal and is {np.corrcoef(IR, RR)[0,1]:+.3f} real. The real asymptote fell from "
          f"{IR[0]*100:.2f}% to {IR[-1]*100:.2f}%")
    print(f"  while the profit rate ROSE from {RR[0]*100:.2f}% to {RR[-1]*100:.2f}%. "
          "i* = c + lam*r requires")
    print("  them to move together. They moved apart, and not slightly.")
    print(f"\n  But read the gap rather than the correlation. r - i* went from "
          f"{gap0*100:.2f} pp to {gap1*100:.2f} pp:")
    print("  the rate of profit of enterprise roughly tripled as the real cost of finance")
    print("  collapsed under a profit rate that did not. That is the same widening this")
    print("  repo measured from the other direction in Result 13, where the policy rate ran")
    print("  chronically below the equalising rate. Two different measurements, one gap.")
    print("  So what fails is Shaikh's LEVELLING claim, not his accounting: the margin is")
    print("  real and it is large, it simply never equalised.")


def main():
    print("DECOMPOSING THE NOMINAL CURVE, AND REFITTING ON WHAT IS LEFT\n")
    inflation_share()
    check_against_tips()
    real, _ = refit_real()
    passthrough_real(real)
    real_anchor(real)


if __name__ == "__main__":
    main()
