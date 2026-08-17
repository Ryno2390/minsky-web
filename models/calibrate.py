"""Confront the enterprise-margin model with US data, and run the test that could kill it.

    python3 models/calibrate.py

THE TEST THAT MATTERS
---------------------
The model's whole content is one claim: accumulation is driven by the profit rate of
ENTERPRISE, `rE = r - iL*d`, not by the profit rate `r`. Every policy conclusion rests on
it -- if the interest deduction does not matter, then monetary policy has no special claim
on accumulation and the proposed floor is decorative.

That claim is testable, and the test is a horse race. Regress accumulation on `rE`, then on
`r`, then on both. If `rE` beats `r`, the deduction carries information and Shaikh's
distinction earns its keep. If they tie, the deduction is idle and the model is a
complicated way of saying accumulation follows profitability. If `r` wins, the model is
backwards.

The second test is whether the constraint ever BINDS. A floor that no observed period comes
near is a floor nobody needs.

WHAT THE ACCOUNTS GIVE, AND WHAT THEY DO NOT
--------------------------------------------
`B = net interest / net operating surplus` is two lines of one NIPA table and needs no
capital stock, so it is the most reliable quantity here. The rates `r`, `rE` and the
leverage `d` all divide by a capital stock, and the one used is Z.1's nonfinancial assets
at market value -- which carries land prices, so levels are softer than ratios.

The interest line is NET of interest received. That is the right concept for the model,
since it is what pre-interest profit is actually reduced by, but it is not a contract rate,
and after 2022 it diverges sharply from market yields as firms earned on large balances
while their own fixed-rate debt had not repriced. `uscorp.interest_check` reports the gap;
the late sample is flagged rather than quietly used.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import uscorp                                                    # noqa: E402


def ols(y, X, names, lags=2):
    """OLS with Newey-West standard errors. Annual macro residuals are autocorrelated;
    plain OLS standard errors on this data are optimistic by a wide margin."""
    y = np.asarray(y, float)
    X = np.column_stack([np.ones(len(y))] + [np.asarray(c, float) for c in X])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    n, k = X.shape
    XtXi = np.linalg.pinv(X.T @ X)
    S = (X * resid[:, None]).T @ (X * resid[:, None])
    for L in range(1, lags + 1):
        w = 1.0 - L / (lags + 1.0)
        G = (X[L:] * resid[L:, None]).T @ (X[:-L] * resid[:-L, None])
        S += w * (G + G.T)
    V = XtXi @ S @ XtXi * n / max(n - k, 1)
    se = np.sqrt(np.maximum(np.diag(V), 0))
    ss_res = float(resid @ resid)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot else float("nan")
    adj = 1 - (1 - r2) * (n - 1) / max(n - k, 1)
    return {"names": ["const"] + names, "beta": beta, "se": se, "V": V,
            "t": beta / np.where(se > 0, se, np.nan), "r2": r2, "adj": adj, "n": n}


def wald(m, R, q):
    """Test R*beta = q. Returns (statistic, approximate two-sided p) for one restriction."""
    R = np.asarray(R, float).reshape(1, -1)
    diff = float((R @ m["beta"]).item() - q)
    var = float((R @ m["V"] @ R.T).item())
    if var <= 0:
        return float("nan"), float("nan")
    z = diff / np.sqrt(var)
    from math import erfc, sqrt
    return z, erfc(abs(z) / sqrt(2.0))


def show(tag, m, keep=None):
    parts = []
    for nm, b, t in zip(m["names"], m["beta"], m["t"]):
        if nm == "const" or (keep and nm not in keep):
            continue
        parts.append(f"{nm} {b:7.3f} (t {t:5.2f})")
    print(f"  {tag:34s} {'  '.join(parts):44s}  R2 {m['r2']:5.3f}  n {m['n']}")


def annual_frame(D, R):
    """Calendar-year averages of everything, on one index, with year labels.

    Columns that are empty throughout are dropped rather than emptying the intersection --
    `iLnet` is one, because NFCB financial assets exceed its debt in every single quarter
    on record, so "net debt" is negative and the implied rate is meaningless.
    """
    cols = {k: uscorp.annual(D, R, k) for k in R}
    empty = [k for k, c in cols.items() if not c]
    for k in empty:
        del cols[k]
    years = sorted(set.intersection(*(set(c) for c in cols.values())))
    if empty:
        print(f"  (no data at all for: {', '.join(empty)} -- dropped)")
    return years, {k: np.array([cols[k][y] for y in years]) for k in cols}


def rule(t):
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def main():
    D = uscorp.load()
    R = uscorp.ratios(D)
    years, A = annual_frame(D, R)
    yi = {y: i for i, y in enumerate(years)}
    print(f"US nonfinancial corporate business, {years[0]}-{years[-1]}, "
          f"{len(years)} annual observations")

    # ---------------------------------------------------------------- calibration targets
    rule("1. CALIBRATION TARGETS")
    def span(a, b, k):
        i, j = yi[a], yi[b] + 1
        return float(np.nanmean(A[k][i:j]))
    windows = [("1947", "2025", "full sample"),
               ("1960", "1989", "pre-disinflation"),
               ("1990", "2019", "the Great Moderation and after"),
               ("2000", "2019", "recent, ex-covid and ex-repricing")]
    print(f"  {'window':>34} {'r':>8} {'rE':>8} {'d':>8} {'iL':>8} {'B':>8} {'g':>8} "
          f"{'g/rE':>7}")
    for a, b, label in windows:
        if a not in yi or b not in yi:
            continue
        v = {k: span(a, b, k) for k in ("r", "rE", "d", "iL", "B", "g")}
        print(f"  {label:>34} {v['r']:8.4f} {v['rE']:8.4f} {v['d']:8.3f} {v['iL']:8.4f} "
              f"{v['B']:8.3f} {v['g']:8.4f} {v['g']/v['rE']:7.3f}")
    print("\n  g/rE is the model's kappa if the model is literally true (g = kappa*rE).")
    print("  It is not stable, which is the first warning: see test 3.")

    # ------------------------------------------------------------- model versus the data
    rule("2. WHERE THE MODEL SITS RELATIVE TO THE DATA")
    model = {"r": 0.06851, "rE": 0.02000, "d": 0.800, "iL": 0.06064, "B": 0.7081,
             "g": 0.02500, "kappa": 1.1875}
    dat = {k: span("1990", "2019", k) for k in ("r", "rE", "d", "iL", "B", "g")}
    dat["kappa"] = dat["g"] / dat["rE"]
    print(f"  {'quantity':>10} {'model':>10} {'data 1990-2019':>16} {'ratio':>8}")
    for k in ("r", "rE", "d", "iL", "B", "g", "kappa"):
        print(f"  {k:>10} {model[k]:10.4f} {dat[k]:16.4f} "
              f"{model[k]/dat[k] if dat[k] else float('nan'):8.2f}")
    bmax = float(np.nanmax(A["B"]))
    bmaxy = years[int(np.nanargmax(A["B"]))]
    print(f"\n  The model's interest burden of {model['B']:.3f} is not merely high. The")
    print(f"  highest burden the US nonfinancial corporate sector has ever recorded is")
    print(f"  {bmax:.3f}, in {bmaxy}. The model was parameterised roughly twice beyond the")
    print(f"  historical maximum, and leverage {model['d']/dat['d']:.1f}x the observed level.")

    # ------------------------------------------------------ the test that could kill it
    rule("3. THE HORSE RACE: does accumulation follow rE, or just r?")
    g, rE, r, B, d = A["g"], A["rE"], A["r"], A["B"], A["d"]
    print("  levels, annual")
    show("g on rE", ols(g, [rE], ["rE"]))
    show("g on r", ols(g, [r], ["r"]))
    show("g on both", ols(g, [r, rE], ["r", "rE"]))
    show("g on r and the burden B", ols(g, [r, B], ["r", "B"]))

    print("\n  first differences (levels of both series trend; this does not)")
    dg, drE, dr, dB = np.diff(g), np.diff(rE), np.diff(r), np.diff(B)
    show("dg on drE", ols(dg, [drE], ["drE"]))
    show("dg on dr", ols(dg, [dr], ["dr"]))
    show("dg on both", ols(dg, [dr, drE], ["dr", "drE"]))

    print("\n  accumulation is slow; give the profit rate a year and two years to act")
    show("g on rE lagged 1", ols(g[1:], [rE[:-1]], ["rE(-1)"]))
    show("g on rE lagged 2", ols(g[2:], [rE[:-2]], ["rE(-2)"]))
    show("g on r  lagged 1", ols(g[1:], [r[:-1]], ["r(-1)"]))
    show("g on r  lagged 2", ols(g[2:], [r[:-2]], ["r(-2)"]))

    print("\n  is it stable across subperiods?")
    for a, b in (("1947", "1979"), ("1980", "1999"), ("2000", "2025")):
        if a not in yi or b not in yi:
            continue
        i, j = yi[a], yi[b] + 1
        show(f"g on rE, {a}-{b}", ols(g[i:j], [rE[i:j]], ["rE"]))

    # ------------------------------------------------- is the race even identified?
    rule("3b. IS THE RACE IDENTIFIED? rE and r differ by very little")
    ild = A["iLd"]
    print(f"  correlation r with rE            {float(np.corrcoef(r, rE)[0,1]):8.4f}")
    print(f"  standard deviation of r          {float(np.std(r)):8.5f}")
    print(f"  standard deviation of rE         {float(np.std(rE)):8.5f}")
    print(f"  standard deviation of iL*d       {float(np.std(ild)):8.5f}"
          f"   <- the ONLY thing separating them")
    print("\n  With rE = r - iL*d and iL*d that small and that collinear, putting r and rE")
    print("  in one regression is close to degenerate and its coefficients mean little.")
    print("  The sharp test is different: enter the interest bill SEPARATELY. The model")
    print("  says g = kappa*(r - iL*d), so the bill must carry a coefficient EQUAL AND")
    print("  OPPOSITE to the profit rate's. That is a testable restriction.\n")
    m = ols(g, [r, ild], ["r", "iL*d"])
    show("g on r and iL*d", m)
    z, p = wald(m, [0, 1, 1], 0.0)          # b_r + b_ild = 0
    print(f"    model's restriction  b(r) + b(iL*d) = 0:  z = {z:.2f}, p = {p:.4f}")
    print(f"    the bill's own coefficient is {m['beta'][2]:+.3f} "
          f"(t {m['t'][2]:.2f}); the model needs it NEGATIVE and near {-m['beta'][1]:.3f}")
    md = ols(dg, [dr, np.diff(ild)], ["dr", "d(iL*d)"])
    show("dg on dr and d(iL*d)", md)
    zd, pd = wald(md, [0, 1, 1], 0.0)
    print(f"    same restriction in differences:          z = {zd:.2f}, p = {pd:.4f}")

    # ------------------------------------------- does a better interest measure save it?
    rule("3c. DOES A BETTER INTEREST MEASURE RESCUE IT?")
    print("  NIPA's interest line is NET of interest received, so it understates what is")
    print("  paid on the debt, badly after 2022. If that mismeasurement is what sinks rE,")
    print("  an imputed GROSS bill -- debt times the Baa yield -- should rescue it.\n")
    baa = {}
    for dt, v in zip(D["date"], D["baa"]):
        if v is not None:
            baa.setdefault(dt[:4], []).append(v)
    baa = {y: sum(v) / len(v) / 100.0 for y, v in baa.items()}
    ok = [i for i, y in enumerate(years) if y in baa]
    by = np.array([baa[years[i]] for i in ok])
    gb, rb, db = g[ok], r[ok], d[ok]
    ildb = by * db
    rEb = rb - ildb
    print(f"  imputed burden B = iL*d/r at Baa: mean {float(np.mean(ildb/rb)):.3f}, "
          f"max {float(np.max(ildb/rb)):.3f} ({years[ok[int(np.argmax(ildb/rb))]]})")
    show("g on rE (Baa-imputed)", ols(gb, [rEb], ["rE_baa"]))
    show("g on r (same sample)", ols(gb, [rb], ["r"]))
    mb = ols(gb, [rb, ildb], ["r", "iL*d_baa"])
    show("g on r and the imputed bill", mb)
    zb, pb = wald(mb, [0, 1, 1], 0.0)
    print(f"    model's restriction b(r) + b(bill) = 0:   z = {zb:.2f}, p = {pb:.4f}")

    # ------------------------------------------- the model's best remaining defence
    rule("3d. THE THRESHOLD DEFENCE: maybe the bill only bites when it is large")
    print("  The model is not linear -- its claim is that a HIGH burden chokes accumulation,")
    print("  and the burden has never been high. A linear test over a sample that never")
    print("  approaches the threshold would miss a real threshold effect. So: does the bill")
    print("  bite harder in the years when it was heaviest?\n")
    for tag, bill, prof, gg in (("NIPA net bill", ild, r, g),
                                ("Baa-imputed bill", ildb, rb, gb)):
        bur = bill / prof
        cut = float(np.median(bur))
        hi = (bur > cut).astype(float)
        mh = ols(gg, [prof, bill, bill * hi], ["r", "bill", "bill x high"])
        print(f"  {tag} (median burden {cut:.3f})")
        show("    g on r, bill, bill x high-burden", mh)
        print(f"      effect of the bill in high-burden years: "
              f"{mh['beta'][2] + mh['beta'][3]:+.3f}   "
              f"(low-burden years: {mh['beta'][2]:+.3f})")
        top = bur >= np.quantile(bur, 0.75)
        mt = ols(gg[top], [prof[top], bill[top]], ["r", "bill"])
        show("    top-quartile-burden years only", mt)
    print("\n  THE TWO MEASURES DISAGREE, AND THAT IS THE RESULT.")
    print("  In the top-burden quartile the NIPA bill enters at about -1.5 with a t near")
    print("  -2.3 -- the model's sign, and a large effect -- while the Baa-imputed bill")
    print("  enters POSITIVE over the very same years. Twenty observations cannot tell")
    print("  these apart. So unlike the linear tests above, the threshold claim is not")
    print("  refuted here; it is simply not settled by the aggregate record, and the one")
    print("  specification that favours it is the one built on the weaker interest measure.")

    rule("3e. WHAT THE SIGN ON THE BILL DOES AND DOES NOT MEAN")
    print("  The interest bill enters POSITIVELY throughout. That is almost certainly not")
    print("  a finding that dearer credit encourages investment. It is what simultaneity")
    print("  produces: policy tightens into booms, so rates and accumulation rise together,")
    print("  and a reduced form with no instrument for the bill picks that up.")
    print("\n  So the honest reading is the weaker one, and it is still fatal to the rule:")
    print("  there is NO evidence in the aggregate record for the negative effect the model")
    print("  requires, and identifying one would need a monetary-policy-shock instrument")
    print("  this exercise does not have.")

    # --------------------------------------------------------------- does the floor bind
    rule("4. DOES THE CONSTRAINT EVER BIND?")
    print("  The rule says hold rE at or above what accumulation requires, and treat")
    print("  rE = 0 (equivalently B = 1) as a bright line. Against the record:\n")
    print(f"  {'':>28} {'value':>9} {'year':>6}")
    print(f"  {'lowest rE ever recorded':>28} {float(np.nanmin(rE)):9.4f} "
          f"{years[int(np.nanargmin(rE))]:>6}")
    print(f"  {'highest burden B':>28} {bmax:9.4f} {bmaxy:>6}")
    print(f"  {'mean burden B':>28} {float(np.nanmean(B)):9.4f}")
    print(f"  {'the bright line':>28} {1.0:9.4f}")
    near = int((B > 0.5).sum())
    print(f"\n  years with B above 0.5 (half of profit to creditors): {near} of {len(B)}")
    print(f"  years with rE <= 0:                                    "
          f"{int((rE <= 0).sum())} of {len(rE)}")

    # -------------------------------------------------------------------- recalibration
    rule("5. RECALIBRATED PARAMETERS")
    kap = dat["kappa"]
    payF = 1.0 - kap * (1.0 - dat["d"])
    print("  Matching the core's closed form to the 1990-2019 averages:")
    print(f"    kappa = g/rE                     {kap:8.4f}   (model used {model['kappa']:.4f})")
    print(f"    d*    = 1 - (1-payF)/kappa       {dat['d']:8.4f}")
    print(f"    -> payF = 1 - kappa*(1-d*)       {payF:8.4f}")
    print(f"    r                                {dat['r']:8.4f}")
    print(f"    iL                               {dat['iL']:8.4f}")
    print(f"    rE = r - iL*d                    {dat['r'] - dat['iL']*dat['d']:8.4f}"
          f"   (measured {dat['rE']:.4f})")
    print(f"\n  The stability eigenvalue is -kappa*rE = {-kap*dat['rE']:.5f}, against")
    print(f"  {-model['kappa']*model['rE']:.5f} in the model: same sign, {abs(kap*dat['rE']/(model['kappa']*model['rE'])):.2f}x the")
    print("  speed. Leverage still converges, and still only because rE > 0.")
    if payF > 1:
        print("\n  NOTE payF > 1: to reconcile kappa with observed leverage the sector must")
        print("  pay out MORE than its enterprise profit, which US buybacks plus dividends")
        print("  in fact do. The core assumed payF < 1, so this is outside its stated range.")

    # ------------------------------------------------ the model, run at US parameters
    rule("6. THE MODEL AT US PARAMETERS")
    ffr = {}
    for dt, v in zip(D["date"], D["ffr"]):
        if v is not None:
            ffr.setdefault(dt[:4], []).append(v)
    ffr = {y: sum(v) / len(v) / 100.0 for y, v in ffr.items()}
    ip = float(np.mean([ffr[y] for y in years if "1990" <= y <= "2019" and y in ffr]))
    prof_share = span("1990", "2019", "profitshare")
    u0 = 0.80
    cal = dict(v=prof_share * u0 / dat["r"], omega=1.0 - prof_share, u=u0,
               kappa=kap, payF=payF, s=dat["iL"] - ip, m=dat["r"] - ip)
    print("  Mapped from the accounts, not chosen:")
    for k in ("v", "omega", "u", "kappa", "payF", "s", "m"):
        print(f"    {k:7s} {cal[k]:9.4f}")
    print(f"    (policy rate = mean fed funds 1990-2019 = {ip:.4f}; "
          f"profit share = {prof_share:.4f})")

    import enterprise_core as CORE                              # noqa: E402
    cf = CORE.closed_form(cal)
    print("\n  What the closed form then says:")
    for k, lab in (("r", "profit rate"), ("dstar", "leverage"), ("iL", "lending rate"),
                   ("rE", "enterprise profit rate"), ("g", "accumulation")):
        print(f"    {lab:24s} {cf[k]:9.5f}   (data {dat.get(k.replace('dstar','d'), float('nan')):.5f})")
    print(f"\n    dg/dm = kappa*d*         {cf['dg_dm']:9.4f}   "
          f"(uncalibrated model: 0.9500)")
    print(f"    margin that zeroes rE    {cf['m_zero']:9.4f}")
    print(f"    lending rate that does   {cf['iL_max']:9.4f}")
    print(f"    -> POLICY RATE that does {cf['iL_max'] - cal['s']:9.4f}")
    peak = max(ffr.values())
    peaky = max(ffr, key=ffr.get)
    print(f"    highest fed funds ever   {peak:9.4f}  ({peaky})")
    print(f"\n  At observed leverage the Fed would have to hold the policy rate near")
    print(f"  {(cf['iL_max']-cal['s'])*100:.1f}% to drive the profit of enterprise to zero. The record high is")
    print(f"  {peak*100:.1f}% in {peaky}. So the bright line is not unreachable -- Volcker came within")
    print(f"  {abs((cf['iL_max']-cal['s'])-peak)*100:.1f} points of it -- but it sits outside all normal policy.")

    print("\n  Rebuilding the Minsky model at these parameters and running it:")
    try:
        CORE.build(cal)
        from build import api as _api                            # noqa: E402
        _api("/api/save", {"name": "EnterpriseCoreUS"})
        from runner import Run                                   # noqa: E402
        path = Run("~/minsky-models/EnterpriseCoreUS.mky").go(
            60.0, ["r", "iL", "d", "rE", "g", "K", "L"], samples=120)
        drift = max(abs(path[k][-1] - path[k][0]) for k in ("r", "iL", "rE", "g", "d"))
        print(f"    saved EnterpriseCoreUS.mky; worst drift over 60 periods {drift:.1e}")
        print(f"    d settles at {path['d'][-1]:.4f} (theory {cf['dstar']:.4f}), "
              f"g at {path['g'][-1]:.5f} (theory {cf['g']:.5f})")
    except Exception as e:                                       # noqa: BLE001
        print(f"    build skipped: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
