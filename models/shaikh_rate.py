"""Test Shaikh's classical theory of the interest rate before building a policy rule on it.

    python3 models/shaikh_rate.py

THE THEORY, IN ONE LINE
-----------------------
The loan rate is the price of production of banking: unit cost plus the normal profit rate
on the capital a bank must advance per dollar lent.

    i_N = c + lam * r          c, lam from bank call reports; r the general profit rate

WHY TEST THIS BEFORE MODELLING IT
---------------------------------
The previous model on this repo was built first and confronted with data afterwards, and
the data refused it: see models/calibrate.py. The order is reversed here. Four things are
checked, in the order that matters -- premise, then prediction, then discriminating
prediction, then the thing a policy rule would actually need.

  1. THE PREMISE. The whole theory rests on the bank profit rate being equalized with the
     general rate. That is not an assumption one has to grant: rB and r are both measured.
     If they are unrelated, nothing downstream survives.

  2. THE LEVEL. Is i_N the centre of gravity of the loan rate? Not "does i equal i_N in
     every year" -- Shaikh is explicit that market rates deviate over the short run -- but
     does i orbit i_N rather than something else?

  3. GIBSON'S PARADOX. The sharp one. Shaikh's equation makes the nominal rate depend on
     the price LEVEL, because bank costs and fixed capital are nominal. Every mainstream
     rule instead ties the nominal rate to the INFLATION RATE. The two are different
     regressors and the data can choose between them.

  4. MEAN REVERSION. A policy rule that pushes i toward i_N is only sensible if the gap
     (i - i_N) actually closes on its own. If the gap is a random walk, i_N is not a centre
     of gravity and there is nothing to steer toward.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import fred                                                      # noqa: E402
import usbank                                                    # noqa: E402
import uscorp                                                    # noqa: E402
from calibrate import ols, show                                  # noqa: E402


def annual_from_fred(sid, pct=False):
    s = fred.series(sid)
    if s is None:
        return {}
    b = {}
    for dt, v in zip(s["date"], s["value"]):
        b.setdefault(int(dt[:4]), []).append(v)
    return {y: (sum(v) / len(v)) / (100.0 if pct else 1.0) for y, v in b.items()}


def rule(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def build():
    """Everything on one annual index: banking coefficients, profit rate, prices, rates."""
    bank = usbank.usable()
    D = uscorp.load()
    R = uscorp.ratios(D)
    prof = uscorp.annual(D, R, "r")                     # general profit rate, NFCB
    prof = {int(y): v for y, v in prof.items()}
    price = annual_from_fred("GDPDEF")
    ffr = annual_from_fred("FEDFUNDS", pct=True)
    baa = annual_from_fred("BAA", pct=True)
    gs10 = annual_from_fred("GS10", pct=True)
    gs1 = annual_from_fred("GS1", pct=True)

    years = sorted(set(bank) & set(prof) & set(price))
    out = {"year": years}
    for k, src in (("c", None), ("lam", None), ("i", None), ("rB", None), ("d", None)):
        out[k] = np.array([bank[y][k] if bank[y][k] is not None else np.nan for y in years])
    out["r"] = np.array([prof[y] for y in years])
    out["p"] = np.array([price[y] for y in years])
    for k, m in (("ffr", ffr), ("baa", baa), ("gs10", gs10), ("gs1", gs1)):
        out[k] = np.array([m.get(y, np.nan) for y in years])
    out["iN"] = out["c"] + out["lam"] * out["r"]
    out["gap"] = out["i"] - out["iN"]
    return out


def main():
    A = build()
    ys = A["year"]
    print(f"US, {ys[0]}-{ys[-1]}, {len(ys)} annual observations")
    print("banking coefficients from FDIC call reports; profit rate from NIPA/Z.1;")
    print("price level and market rates from FRED.")

    # ------------------------------------------------------------------- 1. the premise
    rule("1. THE PREMISE: is the bank profit rate equalized with the general rate?")
    ok = ~np.isnan(A["rB"])
    rB, r = A["rB"][ok], A["r"][ok]
    print(f"  {'':>26} {'mean':>8} {'sd':>8}")
    print(f"  {'bank profit rate rB':>26} {rB.mean():8.4f} {rB.std():8.4f}")
    print(f"  {'general profit rate r':>26} {r.mean():8.4f} {r.std():8.4f}")
    print(f"  {'ratio of means':>26} {rB.mean()/r.mean():8.4f}")
    print(f"  {'correlation':>26} {np.corrcoef(rB, r)[0,1]:8.4f}")
    show("rB on r", ols(rB, [r], ["r"]))
    print(f"\n  n = {ok.sum()} (equity is unreported in the aggregates before ~1984).")
    print("  Equalization does not mean equality year by year -- it is a turbulent process")
    print("  and Shaikh says so. What it does require is that the two share a level.")

    # --------------------------------------------------------------------- 2. the level
    rule("2. THE LEVEL: is i_N the centre of gravity of the loan rate?")
    i, iN, gap = A["i"], A["iN"], A["gap"]
    print(f"  {'':>26} {'mean':>8} {'sd':>8} {'min':>8} {'max':>8}")
    for lab, v in (("actual loan rate i", i), ("classical normal i_N", iN),
                   ("gap i - i_N", gap)):
        print(f"  {lab:>26} {np.nanmean(v):8.4f} {np.nanstd(v):8.4f} "
              f"{np.nanmin(v):8.4f} {np.nanmax(v):8.4f}")
    print(f"\n  i_N is far STEADIER than i: sd {np.nanstd(iN):.4f} against "
          f"{np.nanstd(i):.4f}.")
    print("  That is the theory's actual claim -- a stable price of production of finance,")
    print("  with market rates swinging around it.")
    show("i on i_N", ols(i, [iN], ["i_N"]))
    print(f"  mean gap {np.nanmean(gap):+.4f}; the theory wants this near zero and it is")
    print(f"  {abs(np.nanmean(gap))*100:.1f} points off, which is the size of the whole story.")

    # ------------------------------------------------------------------ 3. Gibson
    rule("3. GIBSON'S PARADOX: does the rate follow the price LEVEL or the INFLATION RATE?")
    logp = np.log(A["p"])
    infl = np.concatenate([[np.nan], np.diff(logp)])
    good = ~np.isnan(infl)
    print("  Shaikh's equation puts the price level in the rate, because bank costs and")
    print("  fixed capital are nominal. Mainstream rules put the inflation rate there.\n")
    for lab, y in (("loan rate i", i), ("Baa yield", A["baa"]), ("fed funds", A["ffr"])):
        m1 = ols(y[good], [logp[good]], ["log p"])
        m2 = ols(y[good], [infl[good]], ["inflation"])
        m3 = ols(y[good], [logp[good], infl[good]], ["log p", "inflation"])
        print(f"  {lab}")
        show("    on the price level", m1)
        show("    on inflation", m2)
        show("    on both", m3)
    trend = np.arange(len(logp), dtype=float)
    rho = float(np.corrcoef(logp, trend)[0, 1])
    print(f"\n  READ THIS BEFORE SCORING THE ABOVE. Since 1966 the US price level has been")
    print(f"  very close to a monotone trend -- corr(log p, time) = {rho:.4f}. Regressing a")
    print("  rate on log p over this sample is therefore near enough to regressing it on")
    print("  time, and the negative coefficients above mostly record that rates fell after")
    print("  1981 while prices kept rising. That is a spurious result, not a refutation:")
    print("  Gibson's correlation was documented under the gold standard, when the price")
    print("  LEVEL itself was mean-reverting and so carried information a trend does not.")
    print("  This sample cannot test it, and Shaikh's own text anticipates the reason --")
    print("  he notes the nominal rate falls relative to the price level when real banking")
    print("  costs fall, which is exactly what technology has done to c since 1966.")

    rule("3b. THE FAIR VERSION: the rate against the two parts of i_N, measured directly")
    print("  c already contains the price level times real unit costs, so testing i against")
    print("  c is the same claim without the spurious trend. lam*r is the profit component.\n")
    lamr = A["lam"] * A["r"]
    show("i on c", ols(i, [A["c"]], ["c"]))
    show("i on lam*r", ols(i, [lamr], ["lam*r"]))
    show("i on both", ols(i, [A["c"], lamr], ["c", "lam*r"]))
    di, dc, dlr = np.diff(i), np.diff(A["c"]), np.diff(lamr)
    show("di on dc and d(lam*r)", ols(di, [dc, dlr], ["dc", "d(lam*r)"]))
    print(f"\n  i_N imposes a coefficient of exactly 1 on each. Whether the free estimates")
    print("  come near that is the honest measure of how much of the loan rate this")
    print("  cost-plus-normal-profit decomposition actually explains.")

    # --------------------------------------------------------- 4. is the gap steerable?
    rule("4. IS THE GAP MEAN-REVERTING? a rule needs something to steer toward")
    g = gap[~np.isnan(gap)]
    dg = np.diff(g)
    m = ols(dg, [g[:-1]], ["gap(-1)"])
    show("d(gap) on gap lagged", m)
    b = m["beta"][1]
    print(f"  A negative coefficient means the gap closes. Estimated {b:+.3f}, so about "
          f"{abs(b)*100:.0f}%")
    if b < 0:
        print(f"  of any deviation is undone within a year, a half-life of "
              f"{np.log(0.5)/np.log(1+b):.1f} years.")
    print("\n  Compare the same test on the actual rate against a constant, which is what")
    print("  'rates are just persistent' would look like:")
    ii = i[~np.isnan(i)]
    show("d(i) on i lagged", ols(np.diff(ii), [ii[:-1]], ["i(-1)"]))


if __name__ == "__main__":
    main()
