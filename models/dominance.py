"""Is this fiscal dominance, or just a constraint that exists? They are not the same claim.

    python3 models/dominance.py

THE DISTINCTION THAT HAS TO BE MADE FIRST
-----------------------------------------
nim_rule.py found the fiscal ceiling binding: a profit-rate-grounded rule prescribes 4.19%
against a phi = 0 ceiling of 2.13%. It is tempting to read that as fiscal dominance. But
what was shown is that a CONSTRAINT EXISTS and would be violated. Fiscal dominance is a
claim about BEHAVIOUR -- that the monetary authority actually defers to it.

Sargent and Wallace (1981) is specific about the regime: the fiscal authority sets deficits
independently, and the monetary authority is forced to accommodate, ultimately by
monetizing. Leeper (1991) makes it testable as a pair of questions, and both have to come
out the same way for the label to apply:

    is FISCAL active?    does the primary surplus fail to respond to the debt ratio?
    is MONETARY passive?  does the policy rate defer to the debt rather than the mandate?

Active fiscal with active monetary is not dominance, it is a collision. Passive fiscal is
not dominance at any debt level, because the debt is being stabilised by taxes.

AND THE ARITHMETIC HAS TO BE UNPLEASANT
---------------------------------------
The Sargent-Wallace mechanism needs the interest rate above the growth rate. If g > i the
debt ratio falls on its own and there is nothing for the fiscal authority to force. That
was Blanchard's 2019 point and it is the first thing to check, because if i - g is
negative the whole apparatus is idle no matter how large the debt is.

WHERE THE EVIDENCE FROM THIS REPO ALREADY POINTS THE OTHER WAY
--------------------------------------------------------------
Two facts already in hand cut against the dominance reading, and they are stated up front
rather than buried:

  * The actual funds rate is 3.64% against a phi = 0 ceiling of 2.13%. Policy is currently
    running ABOVE the sustainability ceiling, not below it. That is not deference.
  * In 2022-23 the Fed hiked to 5.33% with the debt ratio near parity. If the debt
    constrained the rate, that is the cycle in which it should have shown, and it is the
    single most aggressive tightening in forty years.

The tests below try to overturn that reading rather than confirm it.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "data"))
import fiscal                                                    # noqa: E402
import fred                                                      # noqa: E402
import invert                                                    # noqa: E402


def yoy(sid):
    """{(year, quarter): year-over-year growth} from a monthly index."""
    s = fred.series(sid)
    m = {d[:7]: v for d, v in zip(s["date"], s["value"])}
    out = {}
    for t, v in m.items():
        y, mo = int(t[:4]), int(t[5:7])
        prev = f"{y-1}-{mo:02d}"
        if prev in m and m[prev]:
            out.setdefault((y, (mo - 1) // 3 + 1), []).append(v / m[prev] - 1.0)
    return {k: float(np.mean(v)) for k, v in out.items()}


def q_mean(sid, scale=1.0):
    s = fred.series(sid)
    out = {}
    for d, v in zip(s["date"], s["value"]):
        y, mo = int(d[:4]), int(d[5:7])
        out.setdefault((y, (mo - 1) // 3 + 1), []).append(v * scale)
    return {k: float(np.mean(v)) for k, v in out.items()}


def ols(y, X, names):
    """Coefficients with Newey-West standard errors at 4 lags."""
    X = np.column_stack([np.ones(len(y))] + list(X))
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ b
    n, k = X.shape
    S = (e[:, None] * X).T @ (e[:, None] * X)
    for L in range(1, 5):
        w = 1 - L / 5
        G = (e[L:, None] * X[L:]).T @ (e[:-L, None] * X[:-L])
        S += w * (G + G.T)
    XtXi = np.linalg.pinv(X.T @ X)
    V = XtXi @ S @ XtXi
    se = np.sqrt(np.maximum(np.diag(V), 0))
    r2 = 1 - (e ** 2).sum() / ((y - y.mean()) ** 2).sum()
    return list(zip(["const"] + names, b, se, b / np.where(se > 0, se, np.nan))), r2, n


# --------------------------------------------------------------------------- 1
def unpleasant(rows):
    """Sargent-Wallace needs i > g. If growth beats the rate there is nothing to force."""
    print("=" * 92)
    print("1. IS THE ARITHMETIC EVEN UNPLEASANT?  i - g")
    print("=" * 92)
    print("  The mechanism needs the effective rate on the debt above nominal growth.")
    print("  Below it the ratio falls on its own at any primary balance.\n")
    print(f"  {'decade':>9} {'i_eff':>8} {'g':>8} {'i - g':>8} {'b':>7} "
          f"{'quarters i>g':>14}")
    dec = {}
    for r in rows:
        if not np.isfinite(r["g"]):
            continue
        dec.setdefault(f"{r['key'][0]//10*10}s", []).append(r)
    for d, rs in sorted(dec.items()):
        i = float(np.mean([x["i_eff"] for x in rs]))
        g = float(np.mean([x["g"] for x in rs]))
        b = float(np.mean([x["b"] for x in rs]))
        n = sum(1 for x in rs if x["i_eff"] > x["g"])
        print(f"  {d:>9} {i*100:7.2f}% {g*100:7.2f}% {(i-g)*100:+7.2f}% {b:7.3f} "
              f"{n:6d} of {len(rs):3d}")
    good = [r for r in rows if np.isfinite(r["g"])]
    n = sum(1 for r in good if r["i_eff"] > r["g"])
    print(f"\n  Overall {n} of {len(good)} quarters have i > g "
          f"({n/len(good)*100:.0f}%). Mean i - g = "
          f"{np.mean([r['i_eff']-r['g'] for r in good])*100:+.2f} pp.")
    last = good[-1]
    print(f"  Latest ({last['label']}): i_eff {last['i_eff']*100:.2f}%, g "
          f"{last['g']*100:.2f}%, i - g {(last['i_eff']-last['g'])*100:+.2f} pp.")


# --------------------------------------------------------------------------- 2
def bohn(rows):
    """Bohn (1998): does the primary surplus respond to the debt ratio?

    This is the test for whether fiscal is ACTIVE or PASSIVE, and it is the half of the
    dominance question that does not involve the Fed at all. A positive coefficient means
    the fiscal authority stabilises its own debt, which is the Ricardian case -- and no
    debt level, however large, makes that fiscal dominance.
    """
    print("\n" + "=" * 92)
    print("2. BOHN'S TEST -- is fiscal ACTIVE or PASSIVE?")
    print("=" * 92)
    print("  s_t = a + rho*b_{t-1} + controls.  rho > 0 means fiscal stabilises its own")
    print("  debt, which is the Ricardian case and rules out dominance whatever b is.\n")
    unr = q_mean("UNRATE", 0.01)
    keys = [r["key"] for r in rows]
    idx = {k: i for i, k in enumerate(keys)}
    use = [r for r in rows[1:] if r["key"] in unr and keys[idx[r["key"]] - 1] in idx]
    s = np.array([r["s"] for r in use])
    b = np.array([rows[idx[r["key"]] - 1]["b"] for r in use])
    u = np.array([unr[r["key"]] for r in use])

    for label, X, nm in (("no controls", [b], ["b(t-1)"]),
                         ("with unemployment", [b, u], ["b(t-1)", "unemployment"])):
        res, r2, n = ols(s, X, nm)
        print(f"  {label}  (n = {n}, R2 = {r2:.3f})")
        for name, c, se, t in res:
            star = "***" if abs(t) > 2.58 else ("**" if abs(t) > 1.96 else "")
            print(f"    {name:>16} {c:+9.4f}  se {se:.4f}  t {t:+6.2f} {star}")
        print()

    # 2020 is a 30-sd outlier in s. Report the test without it rather than let one
    # quarter set the sign.
    ok = [i for i, r in enumerate(use) if r["key"][0] != 2020]
    res, r2, n = ols(s[ok], [b[ok], u[ok]], ["b(t-1)", "unemployment"])
    print(f"  excluding 2020  (n = {n}, R2 = {r2:.3f})")
    for name, c, se, t in res:
        star = "***" if abs(t) > 2.58 else ("**" if abs(t) > 1.96 else "")
        print(f"    {name:>16} {c:+9.4f}  se {se:.4f}  t {t:+6.2f} {star}")

    print("\n  Rolling 15-year windows, to see whether the response DIED rather than")
    print("  never existed -- a regime change is what the dominance story needs:")
    print(f"    {'window':>13} {'rho':>9} {'t':>7}")
    W = 60
    for st in range(0, len(use) - W, 20):
        sl = slice(st, st + W)
        res, _, _ = ols(s[sl], [b[sl], u[sl]], ["b(t-1)", "u"])
        _, c, se, t = res[1]
        print(f"    {use[st]['label']}..{use[st+W-1]['label']:>7} {c:+9.4f} {t:+7.2f}")


# --------------------------------------------------------------------------- 3
def cycles(rows):
    """Does the peak of each hiking cycle fall as the debt ratio rises?

    The cleanest behavioural test available. Small N, but no trend problem and no
    specification choices: just how high the Fed actually went, against how indebted the
    government was when it went there.
    """
    print("\n" + "=" * 92)
    print("3. HIKING CYCLES -- does the Fed stop lower when the debt is higher?")
    print("=" * 92)
    ff = {r["key"]: r["ff"] for r in rows}
    b = {r["key"]: r["b"] for r in rows}
    cpi = yoy("CPIAUCSL")
    keys = sorted(ff)
    v = np.array([ff[k] for k in keys])

    # troughs and peaks with a minimum 1.5pp move, found rather than hand-listed
    cyc, i = [], 0
    while i < len(v) - 1:
        j = i
        while j + 1 < len(v) and v[j + 1] >= v[j] - 0.0025:
            j += 1
        if v[j] - v[i] >= 0.015:
            cyc.append((i, j))
            i = j
        else:
            i += 1
    print(f"  {len(cyc)} cycles found (trough to peak, minimum 1.5 pp move). The detector")
    print("  tolerates small dips, so it chains 2009Q1..2019Q3 and 2020Q2..2024Q3 into")
    print("  single long episodes. The PEAKS are right, which is what the test uses.\n")
    print(f"  {'trough':>9} {'peak':>9} {'from':>7} {'to':>7} {'debt/GDP':>9} "
          f"{'CPI at peak':>12} {'real peak':>10}")
    B, P, R = [], [], []
    for a, z in cyc:
        ka, kz = keys[a], keys[z]
        infl = cpi.get(kz, float("nan"))
        rp = v[z] - infl
        print(f"  {rows[a]['label']:>9} {rows[z]['label']:>9} {v[a]*100:6.2f}% "
              f"{v[z]*100:6.2f}% {b[kz]:9.3f} {infl*100:11.2f}% {rp*100:9.2f}%")
        B.append(b[kz]); P.append(v[z]); R.append(rp)
    B, P, R = np.array(B), np.array(P), np.array(R)
    ok = np.isfinite(R)
    print(f"\n  corr(debt ratio, NOMINAL peak) = {np.corrcoef(B, P)[0,1]:+.3f}")
    print(f"  corr(debt ratio, REAL peak)    = {np.corrcoef(B[ok], R[ok])[0,1]:+.3f}"
          "   <- the one that controls for disinflation")
    print("\n  The nominal correlation is the disinflation, not the debt: peaks fell")
    print("  because inflation fell. The real peak is what fiscal dominance would have to")
    print("  push down, and n is small enough that this is a description, not a test.")


# --------------------------------------------------------------------------- 4
def defers(rows):
    """Does the policy rate respond to the debt, controlling for the mandate?

    THE TRAP. b trends up over the sample and the funds rate trends down, so a levels
    regression returns a large negative coefficient that is pure common trend. This repo
    has been caught by exactly that twice. So the specification is in CHANGES, and the
    levels version is shown alongside only to display the size of the artefact.
    """
    print("\n" + "=" * 92)
    print("4. DOES THE POLICY RATE DEFER TO THE DEBT?")
    print("=" * 92)
    unr = q_mean("UNRATE", 0.01)
    cpi = yoy("CPIAUCSL")
    use = [r for r in rows if r["key"] in unr and r["key"] in cpi]
    ff = np.array([r["ff"] for r in use])
    b = np.array([r["b"] for r in use])
    pi = np.array([cpi[r["key"]] for r in use])
    u = np.array([unr[r["key"]] for r in use])

    res, r2, n = ols(ff, [b, pi, u], ["debt ratio", "inflation", "unemployment"])
    print(f"  LEVELS -- the artefact  (n = {n}, R2 = {r2:.3f})")
    for name, c, se, t in res:
        print(f"    {name:>16} {c:+9.4f}  se {se:.4f}  t {t:+6.2f}")
    print("    A large negative loading on the debt ratio. It is a trend, not a response.")

    d = lambda x: np.diff(x)                                     # noqa: E731
    res, r2, n = ols(d(ff), [d(b), d(pi), d(u)],
                     ["d debt ratio", "d inflation", "d unemployment"])
    print(f"\n  CHANGES -- the specification  (n = {n}, R2 = {r2:.3f})")
    for name, c, se, t in res:
        star = "***" if abs(t) > 2.58 else ("**" if abs(t) > 1.96 else "")
        print(f"    {name:>16} {c:+9.4f}  se {se:.4f}  t {t:+6.2f} {star}")
    print("\n  Dominance predicts a NEGATIVE, significant loading on the change in the debt")
    print("  ratio: the Fed easing as the debt grows, over and above what the mandate")
    print("  variables ask for.")


# --------------------------------------------------------------------------- 5
def monetizing():
    """The Sargent-Wallace endgame is the central bank absorbing the debt. Is it?"""
    print("\n" + "=" * 92)
    print("5. IS THE FED MONETIZING?")
    print("=" * 92)
    h = fiscal.holders()
    ks = sorted(h)
    print("  Federal Reserve share of the debt held by the public.\n")
    print(f"  {'quarter':>9} {'Fed share':>10} {'foreign':>9} {'domestic priv':>14}")
    show = sorted({(1980, 1), (2007, 4), (2014, 4), (2020, 1), (2022, 1)} & set(ks)) + [ks[-1]]
    for k in show:
        v = h[k]
        print(f"  {k[0]}Q{k[1]:<6} {v['fed']*100:9.1f}% {v['foreign']*100:8.1f}% "
              f"{v['theta']*100:13.1f}%")
    peak = max(ks, key=lambda k: h[k]["fed"])
    now = ks[-1]
    print(f"\n  Peak Fed share {h[peak]['fed']*100:.1f}% in {peak[0]}Q{peak[1]}, "
          f"now {h[now]['fed']*100:.1f}% in {now[0]}Q{now[1]}: a fall of "
          f"{(h[peak]['fed']-h[now]['fed'])*100:.1f} pp.")
    print("  The central bank has been SHEDDING the debt, not absorbing it. Whatever else")
    print("  quantitative tightening is, it is the opposite of the monetization the")
    print("  Sargent-Wallace endgame requires.")



# --------------------------------------------------------------------------- 6
def verdict():
    print("\n" + "=" * 92)
    print("6. VERDICT -- Leeper's two-by-two")
    print("=" * 92)
    print("""
                        |  FISCAL PASSIVE          |  FISCAL ACTIVE
    --------------------+--------------------------+---------------------------
    MONETARY ACTIVE     |  Ricardian. The textbook |  COLLISION. No stable split
                        |  case, no dominance at   |  of the adjustment. Someone
                        |  any debt level.         |  has to give.
    --------------------+--------------------------+---------------------------
    MONETARY PASSIVE    |  Indeterminate           |  FISCAL DOMINANCE
    """)
    print("  WHERE THE EVIDENCE PUTS US: fiscal ACTIVE, monetary ACTIVE. The top right box.")
    print()
    print("  Fiscal is active, and that half of the claim holds up. Bohn's coefficient is")
    print("  -0.086 with a t of -5.8: the primary balance DETERIORATES as the debt ratio")
    print("  rises, which is the non-Ricardian case. The rolling windows say this is not")
    print("  eternal -- it ran +0.12 to +0.13 through 1991-2011 and turned negative after")
    print("  -- so it is a regime that changed, which is exactly what the story needs.")
    print()
    print("  Monetary is not passive, and that is where the reading comes apart. Three")
    print("  independent looks all say the Fed is not deferring:")
    print("    - the change in the debt ratio carries +0.03 with a t of +0.6 in a policy")
    print("      rule controlling for inflation and unemployment. Wrong sign, no")
    print("      significance. The -0.062 in levels is the common trend, not a response.")
    print("    - the real peak of the 2020-24 cycle was 2.60% at a debt ratio of 0.96,")
    print("      against 2.72% at 0.35 in 2002-07. Debt nearly tripled and the real peak")
    print("      did not move.")
    print("    - the Fed's share of the debt has fallen from 26.5% to 14.7% since 2021Q4.")
    print("      The Sargent-Wallace endgame is the central bank absorbing the debt. This")
    print("      is the opposite.")
    print()
    print("  And the arithmetic is not currently unpleasant: i - g is -2.19 pp, with only")
    print("  16 of the last 65 quarters above zero. The ceiling in this repo binds because")
    print("  the PRIMARY BALANCE is deeply negative, not because the rate exceeds growth.")
    print("  That matters for the label -- what constrains policy here is the deficit, and")
    print("  a deficit is a choice in a way that an interest rate is not.")
    print()
    print("  SO: the ingredients are assembling and the regime has not switched. The Fed is")
    print("  currently running 3.64% against a phi = 0 ceiling of 2.13% -- above the")
    print("  sustainability line, not below it. That is resistance, not deference.")
    print()
    print("  What this repo can say about how a collision resolves: three ways, and the")
    print("  phi term decides between them. Fiscal consolidates, the Fed capitulates, or")
    print("  the price level does the adjusting. At phi = 0 the constraint is hard and")
    print("  something must give. At phi near 0.81 the interest bill largely finances")
    print("  itself and the collision is much softer than the phi = 0 ceiling implies.")
    print("  Result 14 already said nothing here identifies phi. That unidentified")
    print("  parameter is now carrying the whole question of whether dominance arrives.")



def main():
    print("FISCAL DOMINANCE, OR A CONSTRAINT THAT EXISTS?\n")
    rows = fiscal.panel()
    fiscal.smooth_growth(rows)
    unpleasant(rows)
    bohn(rows)
    cycles(rows)
    defers(rows)
    monetizing()
    verdict()


if __name__ == "__main__":
    main()
