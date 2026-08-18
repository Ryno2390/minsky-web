"""A policy rule from maturity-transformation equalisation, and whether it behaves.

    python3 models/nim_rule.py

THE RULE
--------
Not a description of what the FOMC does -- invert.py already settled that it is not, and
that the funds rate cannot be recovered from the curve. This is the NORMATIVE version:
take the 10y as market-given, impose that maturity transformation earns the general rate
of profit, and read off the policy rate that makes it so.

A book that funds at the policy rate and holds ten-year paper has, per dollar of assets,
a net interest margin of (i_10 - i_0), an operating cost c, and capital lam. Equalising
its return on capital with the general profit rate r:

    (i_10 - i_0 - c) / lam = r        =>        i_0 = i_10 - c - lam*r

Three measured inputs, one market input, NO free parameter, and -- this is the point --
NO error amplification. The catastrophe in invert.py was e^{+beta*m} multiplying every
uncertainty by six. Here the map from the 10y to the policy rate has a slope of exactly 1.

WHY NOT THE LADDER
------------------
The rung-by-rung version of the same idea, i_m = c + (1-lam) i_{m-1} + lam*r, looks more
faithful to Shaikh and is unusable. Iterated backward over N rungs it gives

    i_0 = r - (r - i_10) / (1-lam)^N

which is exponential in N, and N is the rung width -- the quantity invert.py section 4
showed is not independently observed. Section 2 below prices that: the same 10y implies
anything from 3.8% to deeply negative depending on a number nobody can measure. The
whole-book form is the same equalisation condition with the unmeasurable part integrated
out, which is why it is the one worth testing.

WHERE THE THEORY ALREADY SAYS THIS WILL STRAIN
----------------------------------------------
Iterating the ladder FORWARD converges to i* = c/lam + r, so equalisation says the long
end should asymptote at or above the general profit rate. Measured, it does not come
close: decompose.py found the real asymptote at 2.62% against r near 8.3%. The rule below
is therefore being asked to work on a curve whose level already violates the condition it
is built from. That does not make it useless -- a rule can be well behaved without the
world obeying it -- but the gap is not a detail and section 5 puts a number on it.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import decompose                                                 # noqa: E402
import fiscal                                                    # noqa: E402
import invert                                                    # noqa: E402
import usbank                                                    # noqa: E402
import uscorp                                                    # noqa: E402

#: Operating cost for a Treasury maturity book, per dollar of assets. NOT the 4.85% that
#: usbank measures: that is a lending bank with branches, underwriting and servicing,
#: against loan assets yielding far more than a Treasury. The marginal carry trade this
#: rule describes is a dealer book, so the benchmark is zero and the sensitivity to
#: plausible non-zero values is reported in section 6 rather than assumed away.
C_BOOK = 0.0


def inputs():
    bank = usbank.usable()
    lam = float(np.mean([v["lam"] for v in bank.values() if v["lam"] is not None]))
    D = uscorp.load()
    prof = uscorp.annual(D, uscorp.ratios(D), "r")
    r = float(np.mean(list(prof.values())))
    return lam, r, prof


# --------------------------------------------------------------------------- 1
def state(lam, r):
    print("=" * 92)
    print("1. THE RULE AND ITS INPUTS")
    print("=" * 92)
    print(f"    i_0 = i_10 - c - lam*r\n")
    print(f"  lam  (FDIC, fixed capital + required reserves)  = {lam:.5f}")
    print(f"  r    (NIPA net operating surplus / capital)     = {r:.5f}")
    print(f"  lam*r -- the required net interest margin       = {lam*r*1e4:.0f} bp")
    print(f"  c    (dealer book operating cost, benchmark)    = {C_BOOK*1e4:.0f} bp")
    print(f"\n  So the rule is: the policy rate should sit {(C_BOOK+lam*r)*1e4:.0f} bp "
          "below the 10y.")
    print("  That is a strong prescription in itself -- it says the curve should be nearly")
    print("  FLAT. The 1y-30y nominal slope actually runs 165 bp (decompose.py sec 1).")


# --------------------------------------------------------------------------- 2
def why_not_ladder(lam, r):
    print("\n" + "=" * 92)
    print("2. WHY NOT THE LADDER -- the rung width nobody can measure")
    print("=" * 92)
    g10 = invert.monthly("GS10")
    last = sorted(g10)[-1]
    i10 = g10[last]
    print(f"  Same equalisation, applied rung by rung, at GS10 = {i10*100:.2f}% ({last}):")
    print(f"  i_0 = r - (r - i_10)/(1-lam)^N\n")
    print(f"  {'rung width':>12} {'N over 10y':>11} {'implied i_0':>13}")
    for dt in (10.0, 5.0, 2.0, 1.0, 0.5, 0.25):
        N = 10.0 / dt
        v = r - (r - i10) / (1 - lam) ** N
        print(f"  {dt:11.2f}y {N:11.1f} {v*100:12.2f}%")
    print("\n  One rung is the whole-book rule and is well behaved. Everything below it")
    print("  runs away, and nothing in the data picks the row. That is not a rule.")


# --------------------------------------------------------------------------- 3
def behaviour(lam, r):
    """Is the prescription smooth, bounded, and never below zero?"""
    print("\n" + "=" * 92)
    print("3. IS IT WELL BEHAVED?")
    print("=" * 92)
    g10, ff = invert.monthly("GS10"), invert.monthly(invert.POLICY)
    t = sorted(set(g10) & set(ff))
    rule = np.array([g10[k] for k in t]) - C_BOOK - lam * r
    act = np.array([ff[k] for k in t])
    print(f"  {len(t)} months, {t[0]} to {t[-1]}\n")
    print(f"  {'':>20} {'mean':>8} {'sd':>8} {'min':>8} {'max':>8} {'sd of d/dt':>11} "
          f"{'months < 0':>11}")
    for nm, v in (("rule", rule), ("actual funds rate", act)):
        print(f"  {nm:>20} {v.mean()*100:7.2f}% {v.std()*100:7.2f}% {v.min()*100:7.2f}% "
              f"{v.max()*100:7.2f}% {np.std(np.diff(v))*1e4:10.1f}bp "
              f"{int(np.sum(v < 0)):11d}")
    print(f"\n  correlation with the actual rate : {np.corrcoef(rule, act)[0,1]:+.3f}")
    print(f"  mean gap (rule - actual)         : {(rule-act).mean()*100:+.2f} pp")
    print("\n  It never goes negative, it is SMOOTHER than the rate it would replace, and")
    print("  it is not a restatement of it. The sign of the mean gap is the substantive")
    print("  part: the rule would have run above the actual rate on average, which is the")
    print("  same direction Result 13 found from the equalising-rate side.")
    return t, rule, act


# --------------------------------------------------------------------------- 4
def in_the_band(t, rule, act, lam, r):
    """The question that matters: does it land inside the band, quarter by quarter?"""
    print("\n" + "=" * 92)
    print("4. DOES IT SIT IN THE BAND?")
    print("=" * 92)
    rows = fiscal.panel()
    fiscal.smooth_growth(rows)
    _a0, b1, _r2, _n = fiscal.pass_through(rows)
    rule_by_q = {}
    for k, v in zip(t, rule):
        y, mo = int(k[:4]), int(k[5:7])
        rule_by_q[(y, (mo - 1) // 3 + 1)] = v

    # The ceiling is g + s/b and s is the CONTEMPORANEOUS primary balance, so it dives
    # in every recession -- to -20.1% in 2020Q2, -11.6% in 1975Q2. A negative ceiling is
    # not a constraint any policy rule can satisfy; it says the debt ratio rises at any
    # non-negative rate. Scoring a long-run regime against those quarters counts
    # recessions, not rules. So they are separated out, and a structural ceiling built on
    # a trailing primary balance is reported alongside.
    keys = [r["key"] for r in rows]
    svals = [r["s"] for r in rows]
    strend = {}
    for i, k in enumerate(keys):
        lo = max(0, i - 19)
        strend[k] = float(np.mean(svals[lo:i + 1]))          # 5-year trailing

    def score(get_ceiling):
        n = neg = 0
        out = {"rule": [0, 0], "actual": [0, 0]}
        worst = []
        for row in rows:
            if row["key"] not in rule_by_q or not np.isfinite(row.get("g_trend", np.nan)):
                continue
            im = get_ceiling(row)
            if im < 0:
                neg += 1
                continue
            n += 1
            for nm, v in (("rule", rule_by_q[row["key"]]), ("actual", row["ff"])):
                if v < 0:
                    out[nm][0] += 1
                elif v > im:
                    out[nm][1] += 1
                    if nm == "rule":
                        worst.append((row["label"], v, im))
        return n, neg, out, worst

    for label, gc in (("AS PUBLISHED (contemporaneous primary balance)",
                       lambda row: fiscal.ceiling(row, b1)[0]),
                      ("STRUCTURAL (5-year trailing primary balance)",
                       lambda row: fiscal.ceiling(
                           dict(row, s=strend[row["key"]]), b1)[0])):
        n, neg, out, worst = score(gc)
        print(f"  {label}")
        print(f"    {neg} quarters have a NEGATIVE ceiling and are excluded -- no rule can")
        print(f"    satisfy them. {n} quarters remain.")
        print(f"    {'':>20} {'below 0':>9} {'above ceiling':>15} {'inside':>12}")
        for nm in ("rule", "actual"):
            z, c = out[nm]
            print(f"    {('NIM rule' if nm=='rule' else 'actual funds rate'):>20} "
                  f"{z:9d} {c:15d} {n-z-c:9d} ({(n-z-c)/n*100:3.0f}%)")
        if label.startswith("STRUCTURAL") and worst:
            worst.sort(key=lambda x: x[1] - x[2], reverse=True)
            print(f"    worst breaches:", ", ".join(
                f"{lab} by {(v-im)*100:.1f}pp" for lab, v, im in worst[:4]))
        print()
    print("  Read the structural row. On a ceiling that is not being dragged around by the")
    print("  cycle the rule sits inside the band about as often as the rate the FOMC")
    print("  actually set, and it fails in the same direction and the same episodes: it is")
    print("  too HIGH when the debt ratio is high and growth is slow, which is the fiscal")
    print("  edge doing exactly what Result 14 said it does.")
    return n


# --------------------------------------------------------------------------- 5
def real_version(lam, r):
    """Equalisation is a real-side condition. Run it on the real curve and re-inflate."""
    print("\n" + "=" * 92)
    print("5. THE REAL VERSION -- and the level problem")
    print("=" * 92)
    print("  decompose.py established the ladder is a real-side mechanism, so the honest")
    print("  form deflates first and adds expected inflation back at the end:\n")
    print("    i_0(nominal) = [real_10 - c - lam*r] + expected inflation over 10y\n")
    real = decompose.real_curve()
    e10 = invert.monthly("EXPINF10YR")
    ff = invert.monthly(invert.POLICY)
    g10 = invert.monthly("GS10")
    t = sorted(set(real[10]) & set(e10) & set(ff) & set(g10))
    rr = np.array([real[10][k] for k in t])
    ee = np.array([e10[k] for k in t])
    nom_rule = np.array([g10[k] for k in t]) - C_BOOK - lam * r
    real_rule = rr - C_BOOK - lam * r + ee
    act = np.array([ff[k] for k in t])
    print(f"  {len(t)} months, {t[0]} to {t[-1]}\n")
    print(f"  {'':>20} {'mean':>8} {'sd':>8} {'min':>8} {'max':>8}")
    for nm, v in (("nominal form", nom_rule), ("real form", real_rule),
                  ("actual", act)):
        print(f"  {nm:>20} {v.mean()*100:7.2f}% {v.std()*100:7.2f}% {v.min()*100:7.2f}% "
              f"{v.max()*100:7.2f}%")
    print(f"\n  The two forms differ by exactly "
          f"{np.mean(np.abs(nom_rule-real_rule))*1e4:.0f} bp, and that is not a result --")
    print("  it is an identity. The real curve here IS nominal minus expected inflation, so")
    print("  subtracting the expectation and adding it back cannot change anything. The")
    print("  deflating that mattered in decompose.py mattered because the LADDER decays")
    print("  with maturity and inflation does not. This rule has no ladder and no")
    print("  exponent, so there is nothing for the deflator to bite on. Worth stating")
    print("  plainly rather than presenting a tautology as a robustness check.")
    print("\n  THE LEVEL PROBLEM, PRICED. Iterating the ladder forward gives i* = c/lam + r,")
    print(f"  so equalisation says the real long rate should asymptote at or above "
          f"r = {r*100:.2f}%.")
    print(f"  The measured real 10y averages {rr.mean()*100:.2f}% over this window. The rule")
    print(f"  works off a curve sitting {(r-rr.mean())*100:.1f} pp below where the condition")
    print("  it is derived from says it should be. The rule is internally consistent; the")
    print("  world it is applied to is not, and that gap IS the enterprise margin.")
    last = t[-1]
    print(f"\n  Today ({last}): nominal form {nom_rule[-1]*100:.2f}%, "
          f"real form {real_rule[-1]*100:.2f}%, actual {act[-1]*100:.2f}%.")


# --------------------------------------------------------------------------- 6
def sensitivity(lam, r):
    print("\n" + "=" * 92)
    print("6. SENSITIVITY -- the rule is a spread, so only the spread can move")
    print("=" * 92)
    g10 = invert.monthly("GS10")
    last = sorted(g10)[-1]
    i10 = g10[last]
    print(f"  At GS10 = {i10*100:.2f}% ({last}). Required margin = c + lam*r.\n")
    print(f"  {'c (bp)':>8} {'lam':>7} {'r':>7} {'margin':>8} {'i_0':>8}")
    for c, lm, rr_ in ((0.0, lam, r), (0.0, lam * 2, r), (0.0, lam, r * 1.25),
                       (0.0, 0.10, r), (0.0010, lam, r), (0.0050, lam, r),
                       (0.0100, lam, r), (0.0050, lam * 2, r * 1.25)):
        m = c + lm * rr_
        print(f"  {c*1e4:8.0f} {lm:7.4f} {rr_:7.4f} {m*1e4:7.0f}bp {(i10-m)*100:7.2f}%")
    print("\n  Doubling lam, raising r by a quarter, or putting 100 bp of cost on the book")
    print("  all move the answer by less than a point. Compare invert.py, where the same")
    print("  uncertainty in i* alone opened a 2.6 pp band. Removing the exponential is what")
    print("  bought that, and it is the whole difference between the two constructions.")


# --------------------------------------------------------------------------- 7
def verdict_today(lam, r):
    """The question as asked: does the prescription sit nicely inside the band NOW?"""
    print("\n" + "=" * 92)
    print("7. TODAY, AGAINST EVERY EDGE OF THE BAND")
    print("=" * 92)
    g10 = invert.monthly("GS10")
    last = sorted(g10)[-1]
    v = g10[last] - C_BOOK - lam * r
    rows = fiscal.panel()
    fiscal.smooth_growth(rows)
    _a0, b1, _r2, _n = fiscal.pass_through(rows)
    w = [x for x in rows if np.isfinite(x.get("g_trend", np.nan))][-1]
    # holders() is a quarter behind the panel and returns a dict of shares, not a scalar.
    # Fall back to the most recent available quarter rather than silently passing None,
    # which makes ceiling() skip the phi branch and report three identical ceilings.
    hold = fiscal.holders()
    hk = w["key"] if w["key"] in hold else max(hold)
    th = hold[hk]["theta"]
    if hk != w["key"]:
        print(f"  (theta taken from {hk[0]}Q{hk[1]}, the latest holdings quarter; the "
              f"panel runs one quarter later)")
    c0, _ = fiscal.ceiling(w, b1, g=0.04)
    c81, _ = fiscal.ceiling(w, b1, g=0.04, phi=0.81, theta=th)
    c100, _ = fiscal.ceiling(w, b1, g=0.04, phi=1.00, theta=th)
    print(f"  GS10 = {g10[last]*100:.2f}% ({last}), required margin "
          f"{(C_BOOK+lam*r)*1e4:.0f} bp\n")
    print(f"  RULE SAYS {v*100:.2f}%\n")
    print(f"  {'edge':>28} {'level':>9}   verdict")
    edges = [("zero lower bound", 0.0, "floor"),
             ("dual mandate (Taylor)", 0.0343, "point"),
             ("actual fed funds", w["ff"], "point"),
             (f"fiscal ceiling, phi = 0", c0, "ceiling"),
             (f"fiscal ceiling, phi = 0.81", c81, "ceiling"),
             (f"fiscal ceiling, phi = 1.00", c100, "ceiling"),
             ("Shaikh ceiling (r)", r, "ceiling")]
    for nm, lvl, kind in edges:
        if kind == "floor":
            ok = "clears" if v >= lvl else "BREACHES"
        elif kind == "ceiling":
            ok = "clears" if v <= lvl else f"BREACHES by {(v-lvl)*100:.2f} pp"
        else:
            ok = f"{(v-lvl)*100:+.2f} pp"
        print(f"  {nm:>28} {lvl*100:8.2f}%   {ok}")
    print("\n  So: it clears the floor, sits about half a point above what the FOMC set and")
    print("  three quarters of a point above Taylor, and BREACHES the fiscal ceiling unless")
    print("  the interest-as-income feedback is real and near the top of its range. The")
    print("  rule lands on the one edge Result 14 identified as the binding one, from the")
    print("  outside. That is not a comfortable fit, and it is not a wild one either.")



def main():
    print("A POLICY RULE FROM MATURITY-TRANSFORMATION EQUALISATION\n")
    lam, r, _ = inputs()
    state(lam, r)
    why_not_ladder(lam, r)
    t, rule, act = behaviour(lam, r)
    in_the_band(t, rule, act, lam, r)
    real_version(lam, r)
    sensitivity(lam, r)
    verdict_today(lam, r)


if __name__ == "__main__":
    main()
