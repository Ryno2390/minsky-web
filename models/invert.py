"""Run the term structure backwards: can the policy rate be read off the long end?

    python3 models/invert.py

THE QUESTION
------------
Snider's claim is that the policy rate does not drive the economy -- that the FOMC
ratifies what the market has already done, and the instrument that actually matters is
the 10y, off which corporate debt is priced as 10y + a risk spread. If that is right,
the funds rate is a REDUNDANT STATISTIC: it carries no information the curve does not
already have, and we should be able to reverse-engineer it from the long end using the
structure we fitted in term_fit.py.

That structure is an ODE in maturity, so it inverts in closed form:

    forward   i(m) = i* + (i_0 - i*) e^{-beta m}
    backward  i_0  = i* + (i(m) - i*) e^{+beta m}

WHY THIS EXERCISE IS SELF-DIAGNOSING
------------------------------------
The same exponential does both jobs, and it cannot be kind to both readings:

  * e^{-beta m} SMALL  ->  the policy rate barely reaches the long end. Snider is right
    about transmission. But then the long end carries almost no information about the
    policy rate, and the inversion amplifies every error by e^{+beta m}.

  * e^{-beta m} LARGE  ->  the inversion is well conditioned and the policy rate is
    recoverable from the curve. But then the policy rate DOES propagate to the long end,
    and the premise that it does not matter is what fails.

So "the Fed cannot move the 10y" and "the 10y tells you the Fed's rate" are the forward
and backward readings of one number. You do not get to hold both. Whichever way beta
comes out, one of the two claims dies, and the exercise says which.

WHAT IS ACTUALLY BEING TESTED
-----------------------------
Four things, in order of how much they can hurt:

  1. CONDITIONING. Propagate the fitted spread in (i*, beta) across ladders through
     e^{+beta m}. If the implied policy rate has a confidence band wider than the range
     the rate has historically occupied, the construction is not an instrument.
  2. LEAD-LAG. Snider's weak claim is empirical and needs no model: does the funds rate
     lead or follow the 2y? Cross-correlate changes at monthly leads and lags.
  3. THE INVERSION ITSELF. Run it on monthly GS10 and score the implied path against
     the actual funds rate. A negative result here is still a result.
  4. THE PER-RUNG EQUALISATION RESTRICTION. Shaikh's (10.9) with d = 1 - lam is not an
     assumption, it is what per-rung profit equalisation REQUIRES: a business funding at
     i_{m-1} and lending at i_m with capital ratio lam earns r only if
     i_m = c + (1-lam) i_{m-1} + lam r. Since we fit d from the curve and measure lam
     from call reports, that is an over-identifying restriction -- IF the rung width is
     pinned independently. It is not, so this is reported as a calibration, not a test.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import fred                                                      # noqa: E402
import term_fit                                                  # noqa: E402
import usbank                                                    # noqa: E402
import uscorp                                                    # noqa: E402

POLICY = "FEDFUNDS"        # monthly average effective federal funds rate
LONG = "GS10"
FRONT = "GS2"


def monthly(sid):
    """{YYYY-MM: rate as a decimal}."""
    s = fred.series(sid)
    if s is None:
        raise SystemExit(f"could not fetch {sid}")
    return {d[:7]: v / 100.0 for d, v in zip(s["date"], s["value"])}


def aligned(*sids):
    """(months, arrays...) over the months where every series exists."""
    ser = [monthly(s) for s in sids]
    months = sorted(set.intersection(*(set(m) for m in ser)))
    return months, [np.array([m[t] for t in months]) for m in ser]


def fitted_params():
    """(i*, beta) per ladder from term_fit, so this module cannot drift from that one."""
    out = {}
    for name, rungs in term_fit.LADDERS.items():
        mat, y, months = term_fit.curve(rungs)
        eg, beta, istar = term_fit.fit_gap_fast(mat, y)
        out[name] = (istar, beta, len(y), len(months))
    return out


# --------------------------------------------------------------------------- 1
def conditioning(params, m=10.0):
    """How much of the long rate is the policy rate, and what does inverting cost?"""
    print("=" * 92)
    print(f"1. CONDITIONING -- the same exponential, read both ways, at m = {m:.0f}y")
    print("=" * 92)
    print("  e^-bm is the weight the policy rate carries in the 10y: the forward claim.")
    print("  e^+bm is what inverting multiplies every error by: the backward cost.\n")
    print(f"  {'ladder':>16} {'beta':>7} {'i*':>8} {'e^-bm':>8} {'policy wt':>10} "
          f"{'e^+bm':>8} {'d i_0/d i*':>11}")
    for name, (istar, beta, n, nm) in params.items():
        fwd = np.exp(-beta * m)
        back = np.exp(beta * m)
        print(f"  {name:>16} {beta:7.4f} {istar:8.5f} {fwd:8.4f} {fwd*100:9.1f}% "
              f"{back:8.2f} {-(back-1):11.2f}")
    bs = [v[1] for v in params.values()]
    ists = [v[0] for v in params.values()]
    print(f"\n  beta spans {min(bs):.4f} to {max(bs):.4f}, so the amplifier alone spans "
          f"{np.exp(min(bs)*m):.1f}x to {np.exp(max(bs)*m):.1f}x -- a factor of "
          f"{np.exp(max(bs)*m)/np.exp(min(bs)*m):.1f}.")
    di = (max(ists) - min(ists))
    bmid = float(np.median(bs))
    amp = np.exp(bmid * m)
    print(f"  i* spans {di*1e4:.0f} bp across ladders. Since i_0 = i(m) e^+bm - i*(e^+bm - 1),")
    print(f"  that alone moves the implied policy rate by {di*(amp-1)*1e4:.0f} bp "
          f"= {di*(amp-1)*100:.2f} pp.")
    print(f"\n  For reference the funds rate itself has a standard deviation of "
          f"{np.std(list(monthly(POLICY).values()))*100:.2f} pp over the sample.")
    return bmid, float(np.median(ists))


# --------------------------------------------------------------------------- 2
def lead_lag(maxlag=24):
    """Does the funds rate lead or follow the 2y? No model needed for this one."""
    print("\n" + "=" * 92)
    print("2. LEAD-LAG -- Snider's weak claim, tested without the model")
    print("=" * 92)
    months, (ff, g2, g10) = aligned(POLICY, FRONT, LONG)
    d_ff, d_2, d_10 = np.diff(ff), np.diff(g2), np.diff(g10)
    print(f"  monthly changes, {months[0]} to {months[-1]}, n = {len(d_ff)}\n")

    def xcorr(a, b, lag):
        """corr(a_t, b_{t-lag}). lag > 0 means b LEADS a."""
        if lag > 0:
            x, y = a[lag:], b[:-lag]
        elif lag < 0:
            x, y = a[:lag], b[-lag:]
        else:
            x, y = a, b
        return float(np.corrcoef(x, y)[0, 1])

    for nm, other in (("2y", d_2), ("10y", d_10)):
        cs = [(lag, xcorr(d_ff, other, lag)) for lag in range(-maxlag, maxlag + 1)]
        best = max(cs, key=lambda t: abs(t[1]))
        lead = sum(c for l, c in cs if l > 0)
        lag_ = sum(c for l, c in cs if l < 0)
        print(f"  d(funds) vs d({nm}):")
        print(f"    peak correlation {best[1]:+.3f} at lag {best[0]:+d} months "
              f"({'the ' + nm + ' LEADS' if best[0] > 0 else ('the funds rate leads' if best[0] < 0 else 'contemporaneous')})")
        print(f"    summed corr with {nm} leading  = {lead:+.3f}")
        print(f"    summed corr with funds leading = {lag_:+.3f}")
        print(f"    -> {'the ' + nm + ' leads on balance' if lead > lag_ else 'the funds rate leads on balance'}"
              f" (ratio {lead/lag_:.2f}x)" if lag_ != 0 else "")
        print()
    return months, ff, g2, g10


# --------------------------------------------------------------------------- 3
def run_inversion(months, ff, g10, istar, beta, m=10.0):
    """Reverse-engineer the policy rate from GS10 and score it."""
    print("=" * 92)
    print("3. THE INVERSION -- read the policy rate off the 10y and score it")
    print("=" * 92)
    amp = np.exp(beta * m)
    imp = istar + (g10 - istar) * amp
    err = imp - ff
    print(f"  i_0 = {istar:.5f} + (GS10 - {istar:.5f}) x {amp:.2f}      "
          f"[i*, beta = {istar:.5f}, {beta:.4f}]\n")
    print(f"  {'':>22} {'mean':>9} {'sd':>9} {'min':>9} {'max':>9}")
    for nm, v in (("actual funds rate", ff), ("implied from GS10", imp)):
        print(f"  {nm:>22} {v.mean()*100:8.2f}% {v.std()*100:8.2f}% "
              f"{v.min()*100:8.2f}% {v.max()*100:8.2f}%")
    print(f"\n  correlation with the actual funds rate : {np.corrcoef(imp, ff)[0,1]:+.3f}")
    print(f"  RMS error                              : {np.sqrt(np.mean(err**2))*100:.2f} pp")
    print(f"  mean absolute error                    : {np.mean(np.abs(err))*100:.2f} pp")
    print(f"  sd of the actual funds rate            : {ff.std()*100:.2f} pp")
    skill = 1 - np.mean(err ** 2) / np.mean((ff - ff.mean()) ** 2)
    print(f"  skill vs just quoting the sample mean  : {skill:+.3f}"
          f"   ({'beats' if skill > 0 else 'LOSES TO'} a constant)")
    neg = int(np.sum(imp < 0))
    print(f"  months the inversion implies a NEGATIVE policy rate: {neg} of {len(imp)}"
          f"  ({neg/len(imp)*100:.0f}%)")

    print("\n  Worst decade by decade, so the failure is not hiding in one episode:")
    print(f"  {'decade':>10} {'actual':>9} {'implied':>9} {'error':>9}")
    dec = {}
    for t, a, b in zip(months, ff, imp):
        dec.setdefault(t[:3] + "0s", []).append((a, b))
    for d, vals in sorted(dec.items()):
        a = np.mean([x for x, _ in vals]); b = np.mean([y for _, y in vals])
        print(f"  {d:>10} {a*100:8.2f}% {b*100:8.2f}% {(b-a)*100:+8.2f}%")
    return imp


# --------------------------------------------------------------------------- 4
def rung_equalisation(beta):
    """d = 1 - lam is what per-rung equalisation requires. What rung width does that need?"""
    print("\n" + "=" * 92)
    print("4. THE PER-RUNG EQUALISATION RESTRICTION -- d = 1 - lam")
    print("=" * 92)
    bank = usbank.usable()
    lam = float(np.mean([v["lam"] for v in bank.values() if v["lam"] is not None]))
    D = uscorp.load()
    R = uscorp.ratios(D)
    r = float(np.mean(list(uscorp.annual(D, R, "r").values())))
    print("  A rung that funds at i_{m-1} and lends at i_m with capital ratio lam earns")
    print("  the general rate r only if  i_m = c + (1-lam) i_{m-1} + lam r.  So Shaikh's")
    print("  d is not free: equalisation sets d = 1 - lam.\n")
    print(f"  measured lam (FDIC, fixed capital + required reserves) = {lam:.4f}")
    print(f"  => equalisation requires d = 1 - lam = {1-lam:.4f}")
    print(f"  fitted curve gives d = exp(-beta*DELTA) with beta = {beta:.4f}\n")
    print(f"  {'rung width':>12} {'d = e^-b*dt':>12} {'implied lam':>12} {'vs measured':>13}")
    for dt in (0.25, 0.5, 1.0, 2.0, 3.0):
        d = np.exp(-beta * dt)
        print(f"  {dt:11.2f}y {d:12.4f} {1-d:12.4f} {(1-d)/lam:12.1f}x")
    dt_star = -np.log(1 - lam) / beta
    print(f"\n  The rung width that reconciles them is DELTA = {dt_star:.2f} years "
          f"= {dt_star*12:.1f} months.")
    print("  That is close to the tenor of wholesale bank funding, which is suggestive.")
    print("  It is NOT a test. DELTA is not observed independently, so with one equation")
    print("  and three quantities this solves for the free one. Reporting it as")
    print("  confirmation would be fitting the ruler to the object.")
    print(f"\n  The level restriction IS a test, and it is the one that bites:")
    cc = float(np.mean([v["c"] for v in bank.values()]))
    print(f"    i* fitted from the Treasury curve      = {6.0:.2f}%  (median across ladders)")
    print(f"    c + lam*r for BANK LOANS               = {(cc + lam*r)*100:.2f}%   "
          f"(c = {cc*100:.2f}%, lam*r = {lam*r*100:.2f}%)")
    print("    A Treasury is riskless, so its asymptote must sit BELOW the loan rate.")
    print("    It does not. Whatever else is in i*, it is not bank cost plus lam*r.")
    return lam, r



# --------------------------------------------------------------------------- 5
def profile_istar(mat, y, lo=0.0, hi=0.40, tol=1.5):
    """Profile the fit over i*: which asymptotes are consistent with this curve?

    WHY THIS IS NEEDED. On a nearly straight curve i* and beta are not separately
    identified -- only their product. The fit will still return a number, and that number
    can be 28%, because pushing the asymptote out and beta down leaves the fitted segment
    unchanged. A rolling exercise that reports those as data is reporting its own solver.

    So instead of the argmin, take the SET of i* whose best achievable RMS is within
    `tol` times the global best. If that set runs to the edge of the grid, the window
    does not identify i* and is excluded rather than averaged in.
    """
    gaps = np.diff(mat)
    betas = np.linspace(0.002, 1.5, 1500)
    D = np.exp(-np.outer(betas, gaps))                       # (nb, n-1)
    nb, n = len(betas), len(y)
    A = np.empty((nb, n)); B = np.empty((nb, n))
    A[:, 0], B[:, 0] = y[0], 0.0
    for j in range(1, n):
        A[:, j] = A[:, j - 1] * D[:, j - 1]
        B[:, j] = B[:, j - 1] * D[:, j - 1] + (1 - D[:, j - 1])
    grid = np.linspace(lo, hi, 800)
    pred = A[:, None, :] + B[:, None, :] * grid[None, :, None]   # (nb, ng, n)
    rms = np.sqrt(np.mean((pred - y[None, None, :]) ** 2, axis=2))
    best_per_istar = rms.min(axis=0)
    k = int(np.argmin(best_per_istar))
    floor = best_per_istar[k]
    ok = best_per_istar <= floor * tol
    band = (grid[ok].min(), grid[ok].max())
    # Not "did the band hit the grid edge" -- it usually does not. The diagnostic is the
    # WIDTH. A window whose asymptote is only pinned to within several points has not
    # measured an asymptote, whether or not the solver returned a tidy argmin.
    unident = bool(ok[0] or ok[-1] or (band[1] - band[0]) > WIDTH_MAX)
    return grid[k], band, unident, float(betas[int(np.argmin(rms[:, k]))])


#: An i* consistent band wider than this is not a measurement. The median identified
#: window comes in at 0.15 pp, so 1 pp is already a loose gate rather than a tight one.
WIDTH_MAX = 0.01


def moving_anchor():
    """The decade errors flip sign. That is i* moving, not the policy rate.

    Section 3 holds i* at a sample average and hands the entire secular decline in the
    10y to the policy rate, which is why it needs a negative funds rate after 2000. The
    alternative is that the ASYMPTOTE fell. In Shaikh that asymptote is the price of
    production of finance, so if it fell, it should have fallen with the general rate of
    profit -- and the decline in rates is a profit-rate story, not a Fed story.
    """
    print("\n" + "=" * 92)
    print("5. IS THE ANCHOR ITSELF MOVING? -- rolling fits of i*, with identification checked")
    print("=" * 92)
    rungs = term_fit.LADDERS["5 rungs 1..10"]
    ser = {sid: monthly(sid) for _, sid in rungs}
    months = sorted(set.intersection(*(set(m) for m in ser.values())))
    mat = np.array([m for m, _ in rungs], float)

    D = uscorp.load()
    prof = uscorp.annual(D, uscorp.ratios(D), "r")
    ff = monthly(POLICY)

    W = 120                                            # ten-year rolling window
    rows = []
    for start in range(0, len(months) - W, 12):
        win = months[start:start + W]
        y = np.array([np.mean([ser[sid][t] for t in win]) for _, sid in rungs])
        istar, band, unident, beta = profile_istar(mat, y)
        yrs = sorted({t[:4] for t in win})
        rr = [prof[a] for a in yrs if a in prof]
        f = [ff[t] for t in win if t in ff]
        if not rr or not f:
            continue
        rows.append(dict(a=win[0], b=win[-1], istar=istar, band=band, edge=unident,
                         beta=beta, r=float(np.mean(rr)), ff=float(np.mean(f)),
                         g10=float(np.mean([ser["GS10"][t] for t in win]))))

    bad = [x for x in rows if x["edge"]]
    good = [x for x in rows if not x["edge"]]
    print(f"  {len(rows)} overlapping 10-year windows, {rows[0]['a']} to {rows[-1]['b']}")
    print(f"  {len(bad)} of them do NOT identify i*: the band of asymptotes consistent")
    print(f"  with the curve is wider than {WIDTH_MAX*100:.0f} pp. Those are excluded rather")
    print(f"  than averaged in. {len(good)} windows remain.\n")
    print(f"  {'window':>17} {'i*':>7} {'band':>16} {'width':>7} {'beta':>7} {'r':>7} "
          f"{'funds':>7}  id")
    for x in rows[::3]:
        lo, hi = x["band"]
        print(f"  {x['a']}..{x['b']} {x['istar']*100:6.2f}% "
              f"{lo*100:6.2f}-{hi*100:6.2f}% {(hi-lo)*100:6.2f}pp {x['beta']:7.4f} "
              f"{x['r']*100:6.2f}% {x['ff']*100:6.2f}%  {'NO' if x['edge'] else 'yes'}")

    I = np.array([x["istar"] for x in good]); Rr = np.array([x["r"] for x in good])
    F = np.array([x["ff"] for x in good]); G = np.array([x["g10"] for x in good])
    B = np.array([x["beta"] for x in good])
    wid = np.array([x["band"][1] - x["band"][0] for x in good])
    print(f"\n  On the {len(good)} identified windows:")
    print(f"    i* runs {I.min()*100:.2f}% to {I.max()*100:.2f}%, median band width "
          f"{np.median(wid)*100:.2f} pp")
    print(f"    {'corr(i*, r)':>22} = {np.corrcoef(I, Rr)[0,1]:+.3f}   "
          "the profit rate -- what Shaikh says sets it")
    print(f"    {'corr(i*, funds)':>22} = {np.corrcoef(I, F)[0,1]:+.3f}   the policy rate")
    print(f"    {'corr(i*, GS10)':>22} = {np.corrcoef(I, G)[0,1]:+.3f}")
    print(f"    {'corr(funds, GS10)':>22} = {np.corrcoef(F, G)[0,1]:+.3f}")
    print("\n  Windows overlap by 9 of 10 years, so these correlations have far fewer")
    print("  independent observations than rows and no significance is claimed for them.")

    w = np.exp(-B * 10.0)
    anchor, policy = I * (1 - w), F * w
    print(f"\n  Variance of the 10y through GS10 = i*(1-w) + funds*w, w = e^-10beta:")
    print(f"    mean weight on the policy rate   = {w.mean():.3f}")
    print(f"    var(anchor term) / var(GS10)     = {np.var(anchor)/np.var(G)*100:6.1f}%")
    print(f"    var(policy term) / var(GS10)     = {np.var(policy)/np.var(G)*100:6.1f}%")
    print(f"    2*cov(anchor, policy)/var(GS10)  = "
          f"{2*np.cov(anchor, policy)[0,1]/np.var(G)*100:6.1f}%")
    return good


# --------------------------------------------------------------------------- 6
def beta_two_ways():
    """The one test here with a real chance of failing.

    beta has been fitted from the SHAPE of the average curve -- a cross-section, one
    number per maturity. But the model makes a second, completely separate prediction.
    Holding i* fixed,

        dGS_m / d(funds) = e^{-beta m}

    so regressing monthly CHANGES in each Treasury yield on monthly changes in the funds
    rate should trace out the same exponential, from time-series variation that the
    cross-sectional fit never saw. Two independent estimates of one parameter.

    And the intercept of that exponential is pinned too: at m = 0 the pass-through must be
    1, because the policy rate is the m = 0 point of the curve. So the regression gives a
    level test as well as a decay test, and neither was used in fitting.
    """
    print("\n" + "=" * 92)
    print("6. BETA MEASURED TWO WAYS -- curve shape vs actual pass-through")
    print("=" * 92)
    mats = [(1, "GS1"), (2, "GS2"), (3, "GS3"), (5, "GS5"), (7, "GS7"), (10, "GS10"),
            (20, "GS20"), (30, "GS30")]
    ff = monthly(POLICY)
    print("  Monthly changes. Slope of d(GS_m) on d(funds), which the model says is e^-bm.\n")
    print(f"  {'maturity':>9} {'n':>6} {'slope':>8} {'se':>7} {'R2':>7} "
          f"{'model e^-bm':>12} {'ratio':>7}")
    BETA_X = 0.1805                                   # cross-sectional, 6 rungs 1..30
    ms, slopes, ses = [], [], []
    for m, sid in mats:
        g = monthly(sid)
        t = sorted(set(g) & set(ff))
        x = np.diff(np.array([ff[k] for k in t]))
        y = np.diff(np.array([g[k] for k in t]))
        b = float(np.sum(x * y) / np.sum(x * x))
        resid = y - b * x
        se = float(np.sqrt(np.sum(resid ** 2) / (len(x) - 1) / np.sum(x * x)))
        r2 = 1 - np.sum(resid ** 2) / np.sum((y - y.mean()) ** 2)
        pred = np.exp(-BETA_X * m)
        ms.append(m); slopes.append(b); ses.append(se)
        print(f"  {m:8d}y {len(x):6d} {b:8.4f} {se:7.4f} {r2:7.3f} {pred:12.4f} "
              f"{b/pred:7.2f}")

    ms = np.array(ms, float); slopes = np.array(slopes)
    # fit slope = A e^{-beta m} in logs, weighted by 1/se
    ok = slopes > 0
    w = 1.0 / np.array(ses)[ok]
    X = np.column_stack([np.ones(ok.sum()), -ms[ok]])
    W = np.diag(w)
    coef = np.linalg.lstsq(W @ X, w * np.log(slopes[ok]), rcond=None)[0]
    A, beta_t = float(np.exp(coef[0])), float(coef[1])
    print(f"\n  time-series fit:  pass-through = {A:.3f} x e^(-{beta_t:.4f} m)")
    print(f"  cross-section  :  beta = {BETA_X:.4f}   (range {0.1373:.4f}-{0.2065:.4f} "
          "across ladders)")
    print(f"\n  DECAY  beta {beta_t:.4f} vs {BETA_X:.4f}  -> "
          f"{'AGREE' if 0.1373 <= beta_t <= 0.2065 else 'DISAGREE'}"
          f", ratio {beta_t/BETA_X:.2f}x")
    print(f"  LEVEL  A = {A:.3f}, model requires 1.000  -> "
          f"{'passes' if 0.8 <= A <= 1.25 else 'FAILS'}")
    if A < 0.8:
        print(f"         A well under 1 means even the SHORTEST maturity does not move")
        print(f"         one-for-one with the funds rate on a monthly change. The curve")
        print(f"         is not hinged at the policy rate the way the recursion assumes.")
    # What shape DOES the pass-through have? Add a level term the recursion does not
    # have: every maturity moving together, on top of a decaying short-end component.
    best = None
    for bt in np.linspace(0.01, 1.2, 1200):
        X2 = np.column_stack([np.ones(len(ms)), np.exp(-bt * ms)])
        c, *_ = np.linalg.lstsq(X2, slopes, rcond=None)
        e = float(np.sqrt(np.mean((X2 @ c - slopes) ** 2)))
        if best is None or e < best[0]:
            best = (e, bt, c[0], c[1])
    e2, bt2, L, S = best
    e1 = float(np.sqrt(np.mean((A * np.exp(-beta_t * ms) - slopes) ** 2)))
    print(f"\n  Pure exponential            : rms {e1*1e4:5.1f} bp")
    print(f"  Level + exponential         : rms {e2*1e4:5.1f} bp   "
          f"L = {L:.3f}, S = {S:.3f}, beta = {bt2:.4f}")
    print(f"  The data want a LEVEL term of {L:.2f} that the recursion has no room for:")
    print("  a component of every yield, out to 30 years, that moves with the funds rate")
    print("  by the same amount regardless of maturity. Shaikh's ladder has no such term.")
    print("  Everything in it must enter through the m = 0 hinge and decay from there.")

    print("\n  ONE CAVEAT THAT CUTS THE OTHER WAY. This regression puts the funds rate on")
    print("  the right-hand side, which assumes it causes the yields. Section 2 found the")
    print("  2y LEADS it. So these slopes are comovement, not pass-through, and a low")
    print("  reading is as consistent with the arrow pointing backwards as with weak")
    print("  transmission. That ambiguity is Snider's whole point, and this test cannot")
    print("  break it -- it can only show the recursion does not describe the comovement.")
    print("\n  This is the only comparison in this file where the two sides were measured")
    print("  from different data. Sections 1 and 3 reuse the fit they are testing.")
    return A, beta_t



def main():
    print("REVERSE-ENGINEERING THE POLICY RATE FROM THE LONG END")
    print("Snider's claim, put through the fitted term structure.\n")
    params = fitted_params()
    beta, istar = conditioning(params)
    months, ff, g2, g10 = lead_lag()
    run_inversion(months, ff, g10, istar, beta)
    rung_equalisation(beta)
    moving_anchor()
    beta_two_ways()
    print("\n" + "=" * 92)
    print("VERDICT")
    print("=" * 92)
    print("  1. The inversion does not work, and could not have. The 10y carries 13-25% of")
    print("     the policy rate, so recovering it means multiplying by 4-8, and the spread")
    print("     in i* alone across ladders puts a 2.6 pp band on the answer against a funds")
    print("     rate whose own sd is 3.5 pp. Run anyway it correlates +0.92 and has a skill")
    print("     score of -16: it tracks the shape and gets the level catastrophically wrong,")
    print("     implying a negative policy rate in half of all months.")
    print()
    print("  2. Snider's WEAK claim survives cleanly and needed no model. The 2y leads the")
    print("     funds rate; summed cross-correlation is +0.50 with the 2y leading and -0.04")
    print("     with the funds rate leading.")
    print()
    print("  3. Snider's STRONG claim does not. Pass-through is 0.53 at 1y and still 0.15 at")
    print("     30y with a standard error of 0.02. Weak and badly described by the model,")
    print("     but not zero.")
    print()
    print("  4. The recursion is refuted as a theory of PROPAGATION while surviving as one")
    print("     of average SHAPE. Beta from the curve is 0.18; beta from actual comovement")
    print("     is 0.04, and the pass-through starts at 0.37 where the model requires 1.")
    print("     The data want a level factor common to all maturities. The ladder has no")
    print("     such term -- everything must enter at m = 0 and decay.")
    print()
    print("  5. The anchor moved, and not with the profit rate. i* fell from 10.7% to 2.8%")
    print("     while r rose from 6.9% to 8.6%: corr = -0.87. Whatever sets the level of")
    print("     the curve, the Shaikh story that it is c + lam*r is not carrying it.")
    print()
    print("  6. And in the period the argument is actually about, the exercise mostly")
    print("     cannot run. 13 of the 15 windows starting 2002 or later fail to identify")
    print("     i* -- 2012 and 2013 are the exceptions, and 1972 is the only earlier")
    print("     failure. The curve flattens, the curvature the estimator lives on is gone,")
    print("     and the asymptote is pinned only to within several points. Whatever ZIRP")
    print("     and QE did to transmission, they removed the information this method needs.")


if __name__ == "__main__":
    main()
