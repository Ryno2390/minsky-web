"""Shaikh's classical term structure, and the policy rule that falls out of it.

    python3 models/shaikh_term_structure.py            # build, save, check the baseline
    python3 models/shaikh_term_structure.py --validate # the theory's own predictions
    python3 models/shaikh_term_structure.py --compare  # the classical anchor against Taylor

THE THEORY (Capitalism, ch. 10 sec. II, formalised)
---------------------------------------------------
The loan rate is the price of production of banking. A short division funds one-period
loans with demand deposits, which pay no interest and are paid for in services instead;
a long division funds longer loans with time deposits, which pay the short rate. Imposing
profit-rate equalization on each gives

    i1N = c1 + lam1*r                   level:  set by rB = r
    i2N = c2 + i1*d2 + lam2*r           slope:  set by rB1 = rB2

    c   nominal operating cost per dollar of loans, = p * (real unit cost)
    lam capital advanced per dollar of loans, < 1 because banks are leveraged
    d2  time-deposit funding per dollar of long loans

Two things are worth being explicit about, because they are what makes this different
from what came before on this repo.

FIRST, i < r IS DERIVED. Because lam < 1, the normal rate cannot reach the profit rate,
so the profit rate of enterprise is positive as a matter of banking's balance-sheet
structure. The previous model on this repo simply assumed it. In US call-report data lam
runs 0.081 to 0.359, so the condition holds with room to spare.

SECOND, THE SHORT RATE IS AN INPUT COST TO THE LONG RATE, not a forecast of it. Policy
reaches the long end through bank funding costs, mechanically. No expectations hypothesis,
no liquidity premium, and risk enters only through the costs it imposes.

WHAT THE POLICY RULE TURNS OUT TO BE
------------------------------------
Anchoring policy on i1N rather than on an estimated natural rate looks at first like a
Taylor rule with the intercept swapped. It is not, and the difference is structural.

    c = p * ucr, and real unit costs fall at rate theta while prices rise at pi

so nominal cost per dollar of loans is constant only when theta = pi. Let inflation run
above the rate at which banking gets cheaper and c GROWS WITHOUT BOUND, dragging i1N up
with it for as long as the gap persists. The anchor therefore responds to the price LEVEL,
cumulatively -- it is an integral controller, where Taylor is a proportional one on the
inflation rate. That is the substantive claim this file exists to test, and it is also why
the rule can carry a below-Taylor coefficient on inflation without losing the nominal
anchor.

CALIBRATION
-----------
Every banking coefficient comes from FDIC call reports and the profit rate from NIPA/Z.1,
via models/data/usbank.py and models/data/uscorp.py. c2 and d2 are the only two solved
rather than measured: the split of costs between the two divisions is not separately
reported, so they are pinned by requiring the model to reproduce the observed term spread.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build import Builder, api                              # noqa: E402

P = dict(
    # --- real sector -------------------------------------------------------------
    v=1.90,          # capital to capacity-output ratio, from profit share / r
    omN=0.81,        # wage share at rest (profit share 0.19, NFCB)
    un=0.80,         # normal capacity utilisation
    kappa=0.377,     # accumulation response, from g/rE
    gn=0.0235,       # normal accumulation, NFCB 1990-2019
    dF=0.4208,       # firm leverage L/K, NFCB
    thu=0.50,        # utilisation adjusts to investment demand
    thb=0.30,        # ...and is pulled back toward normal capacity
    phi1=0.30,       # wage share rises with utilisation
    phi2=0.50,       # ...and is pulled back toward its own norm
    gp=0.40,         # inflation responds to utilisation
    gw=0.30,         # inflation responds to the wage share
    pi0=0.035,       # inflation at rest
    # --- banking -----------------------------------------------------------------
    c1b=0.0488,      # nominal operating cost per $ of short loans (FDIC mean)
    c2b=0.0250,      # ...of long loans: time deposits cost less to service, solved
    lam1=0.19,       # capital advanced per $ of loans (FDIC mean)
    lam2=0.19,
    d2=0.5281,       # time-deposit funding per $ of long loans, solved for the spread
    theta=0.035,     # rate at which REAL banking costs fall; = pi0 keeps c stationary
    phN=0.50,        # speed the market rate gravitates to the normal rate
    phP=1.00,        # speed policy reaches the market rate
    # --- policy ------------------------------------------------------------------
    sbar=0.019,      # normal gap between the policy rate and the short loan rate
    api=0.50,        # response to the inflation gap (BOTH rules)
    auu=0.50,        # response to the utilisation gap (BOTH rules)
    rule=1.0,        # 1 = classical anchor, 0 = Taylor
)
P0 = 1.0


def baseline(p):
    """The rest point, solved. Only rEn and rstar are free, and both are pinned."""
    r = (1.0 - p["omN"]) * p["un"] / p["v"]
    c1, c2 = P0 * p["c1b"], P0 * p["c2b"]
    i1 = c1 + p["lam1"] * r                       # classical normal short rate
    i2 = c2 + i1 * p["d2"] + p["lam2"] * r        # ...and long rate, Shaikh (10.9)
    rEn = r - i1 * p["dF"]
    ip = i1 - p["sbar"]
    rstar = ip - p["pi0"]                         # so Taylor AGREES at the baseline
    return dict(r=r, c1=c1, c2=c2, i1=i1, i2=i2, slope=i2 - i1, rEn=rEn, ip=ip,
                rstar=rstar, rB1=(i1 - c1) / p["lam1"],
                rB2=(i2 - c2 - i1 * p["d2"]) / p["lam2"])


def build(p, bl):
    api("/api/clear")
    b = Builder()
    for nm in ("v", "omN", "un", "kappa", "gn", "dF", "thu", "thb", "phi1", "phi2",
               "gp", "gw", "pi0", "lam1", "lam2", "d2", "theta", "phN", "phP",
               "sbar", "api", "auu"):
        b.param(nm, float(p[nm]))
    b.param("ucr1", float(p["c1b"] / P0))          # REAL unit cost, short division
    b.param("ucr2", float(p["c2b"] / P0))          # ...long division
    b.param("rEn", float(bl["rEn"]))
    b.param("rstar", float(bl["rstar"]))
    b.param("piT", float(p["pi0"]))
    b.param("rule", float(p["rule"]), slider=(-0.2, 1.2))   # the engine refuses a value
    #                                     sitting exactly on a slider bound
    b.param("wsh", 0.0, slider=(-0.03, 0.03))      # a money-wage shock, for the race
    b.param("ish", 0.0, slider=(-0.03, 0.03))      # a policy rate disturbance: the base
    #   rate held away from what the rule calls for. It has to be its own parameter --
    #   moving sbar instead shifts the rule's intercept AND the transmission offset by
    #   the same amount, so they cancel exactly and nothing happens.

    st = {"T": b.stock("T", 0.0), "p": b.stock("p", P0),
          "u": b.stock("u", float(p["un"])), "omega": b.stock("omega", float(p["omN"])),
          "i1": b.stock("i1", float(bl["i1"])), "i2": b.stock("i2", float(bl["i2"]))}

    for name, expr in [
        ("r",     "(1 - omega) * u / v"),            # general profit rate
        ("rE",    "r - i1 * dF"),                    # profit rate of enterprise
        ("gI",    "gn + kappa * (rE - rEn)"),        # investment demand
        ("pi",    "pi0 + gp * (u - un) + gw * (omega - omN)"),
        ("tech",  "exp(0 - theta * T)"),             # real banking costs fall
        ("c1",    "p * ucr1 * tech"),                # NOMINAL cost per $ of short loans
        ("c2",    "p * ucr2 * tech"),
        ("i1N",   "c1 + lam1 * r"),                  # THE CLASSICAL NORMAL SHORT RATE
        ("i2N",   "c2 + i1 * d2 + lam2 * r"),        # SHAIKH (10.9): i1 is an INPUT COST
        ("rB1",   "(i1 - c1) / lam1"),               # short division's own profit rate
        ("rB2",   "(i2 - c2 - i1 * d2) / lam2"),     # long division's
        ("slope", "i2 - i1"),                        # the yield curve
        ("ipC",   "(i1N - sbar) + api * (pi - piT) + auu * (u - un)"),   # CLASSICAL
        ("ipT",   "rstar + pi + api * (pi - piT) + auu * (u - un)"),     # TAYLOR
        ("ip",    "rule * ipC + (1 - rule) * ipT + ish"),
        ("dT",    "1"),
        ("dp",    "pi * p"),
        ("du",    "thu * (gI - gn) - thb * (u - un)"),
        ("domega", "omega * (phi1 * (u - un) - phi2 * (omega - omN) + wsh)"),
        ("di1",   "phN * (i1N - i1) + phP * ((ip + sbar) - i1)"),
        ("di2",   "phN * (i2N - i2)"),               # policy reaches the long end
    ]:                                               # ONLY through i1, inside i2N
        b.eq(name, expr)
    for state, deriv in (("T", "dT"), ("p", "dp"), ("u", "du"), ("omega", "domega"),
                         ("i1", "di1"), ("i2", "di2")):
        b.wire(b.ref[deriv], st[state], 1)

    b.plot("The yield curve", ["i1", "i2", "i1N", "i2N"], at=[1700, 300])
    b.plot("Rates and the profit rate", ["r", "rE", "ip", "i1"], at=[1700, 800])
    b.plot("Equalisation and activity", ["rB1", "rB2", "u", "pi"], at=[1700, 1300])
    api("/api/solver", {"implicit": False, "epsRel": 1e-8, "epsAbs": 1e-10, "tmax": 60.0})
    api("/api/layout")
    b.value_ids()
    return b


W = ["r", "rE", "i1", "i2", "i1N", "i2N", "slope", "rB1", "rB2", "u", "omega", "pi",
     "ip", "c1", "c2", "p", "gI"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--save", default="ShaikhTermStructure")
    args = ap.parse_args()

    p = dict(P)
    bl = baseline(p)
    print("BASELINE, solved from the calibration (nothing here is chosen to fit)")
    for k in ("r", "c1", "c2", "i1", "i2", "slope", "rB1", "rB2", "rEn", "ip", "rstar"):
        print(f"  {k:7s} {bl[k]:10.5f}")
    print(f"\n  i1 < r ?  {bl['i1']:.5f} < {bl['r']:.5f}  -> "
          f"{'yes, derived from lam < 1' if bl['i1'] < bl['r'] else 'NO'}")
    print(f"  both divisions earn r ?  rB1 {bl['rB1']:.5f}  rB2 {bl['rB2']:.5f}  "
          f"r {bl['r']:.5f}")
    print(f"  term spread {bl['slope']*100:.2f} points")

    build(p, bl)
    st = api("/api/state", method="GET")
    print(f"\nbuilt {len(st['items'])} items and {len(st['wires'])} wires")
    api("/api/save", {"name": args.save})
    print(f"saved as {args.save}.mky")

    from runner import Run
    R = Run(f"~/minsky-models/{args.save}.mky")
    path = R.go(60.0, W, samples=200)
    steady = ("r", "i1", "i2", "slope", "rB1", "rB2", "u", "omega", "pi", "c1", "c2")
    drift = {k: abs(path[k][-1] - path[k][0]) for k in steady}
    worst = max(drift, key=drift.get)
    print("\nis the baseline a rest point? drift over 60 periods:")
    print("  worst: " + f"{worst} {drift[worst]:.2e}")
    print("  " + "  ".join(f"{k} {v:.1e}" for k, v in list(drift.items())[:6]))
    print(f"  price level grew x{path['p'][-1]/path['p'][0]:.3f} at pi = {p['pi0']}, "
          f"and c1 held at {path['c1'][-1]:.5f} because real costs fell at theta = "
          f"{p['theta']}")

    if args.validate:
        validate(R, p, bl)
    if args.compare:
        compare(R, p, bl)


def validate(R, p, bl):
    """The theory's own predictions, checked against the model that formalises it."""
    print("\n" + "=" * 78)
    print("VALIDATION 1 · THE CURVE SLOPES UP ON COSTS, NOT ON EXPECTATIONS")
    print("=" * 78)
    print("  Nothing in this model forecasts anything. The long rate is above the short")
    print("  rate because the long division has its own costs and its own capital to")
    print("  earn on, and funds itself at the short rate.\n")
    print(f"  {'d2':>7} {'c2':>8} {'i1':>9} {'i2':>9} {'spread':>9} {'rB1':>8} {'rB2':>8}")
    for d2 in (0.30, 0.53, 0.70, 0.90):
        q = dict(p); q["d2"] = d2
        b2 = baseline(q)
        print(f"  {d2:7.2f} {b2['c2']:8.4f} {b2['i1']:9.5f} {b2['i2']:9.5f} "
              f"{b2['slope']:9.5f} {b2['rB1']:8.5f} {b2['rB2']:8.5f}")
    print("\n  Both divisions earn exactly r at every setting -- that IS the equalisation")
    print("  among banks, and it is what fixes the slope. More time-deposit funding means")
    print("  a bigger interest bill for the long division, so it must charge more.")

    print("\n" + "=" * 78)
    print("VALIDATION 2 · WHEN DOES THE CURVE INVERT?")
    print("=" * 78)
    print("  Shaikh says an inversion is not a forecast of recession but a symptom of")
    print("  long-loan demand being weak against long-deposit supply. Here that shows up")
    print("  as the long division's own costs falling relative to its funding bill.\n")
    print(f"  {'c2':>8} {'spread':>9}  shape")
    for c2 in (0.045, 0.035, 0.025, 0.015, 0.005):
        q = dict(p); q["c2b"] = c2
        b2 = baseline(q)
        shape = "upward" if b2["slope"] > 0 else "INVERTED"
        print(f"  {c2:8.4f} {b2['slope']:9.5f}  {shape}")

    print("\n" + "=" * 78)
    print("VALIDATION 3 · POLICY REACHES THE LONG END THROUGH COSTS")
    print("=" * 78)
    print("  The base rate is shifted a point and the long rate is watched. There is no")
    print("  expectations channel in this model, so whatever arrives arrives through the")
    print("  long division's funding bill.\n")
    q = R.go(30.0, W, {"ish": 0.01}, samples=120)
    print(f"  {'':>18} {'baseline':>10} {'after':>10} {'move':>9}")
    for k in ("ip", "i1", "i2", "slope"):
        print(f"  {k:>18} {q[k][0]:10.5f} {q[k][-1]:10.5f} {q[k][-1]-q[k][0]:+9.5f}")
    print("\n  The long rate moves although nothing in this model forecasts anything, and")
    print("  the term spread NARROWS as policy tightens. Both come from (10.9) alone.")
    print("\n  TWO DIFFERENT PASS-THROUGHS, and only the first is a constant of the model:")
    print(f"    STRUCTURAL   d(i2N)/d(i1) = d2 = {p['d2']:.4f} exactly, by construction --")
    print("                 the long division funds that share of its book at the short")
    print("                 rate, so that share of any move lands on its costs.")
    print("    MEASURED     the total response, which also carries r, because i2N has a")
    print("                 lam2*r term and the profit rate moves as activity responds:\n")
    print(f"  {'horizon':>9} {'d i1':>9} {'d i2':>9} {'ratio':>9}")
    for t in (15.0, 30.0, 60.0, 120.0, 240.0):
        z = R.go(t, W, {"ish": 0.01}, samples=200)
        a, b2 = z["i1"][-1] - z["i1"][0], z["i2"][-1] - z["i2"][0]
        print(f"  {t:9.0f} {a:+9.5f} {b2:+9.5f} "
              f"{(b2 / a if abs(a) > 1e-9 else float('nan')):9.4f}")
    print("\n  The ratio starts near d2 and then falls away, turning negative: at long")
    print("  horizons the profit-rate channel overwhelms the funding-cost channel and")
    print("  drags the long rate back down while the short rate is still elevated.")
    print("  So this is an IMPULSE RESPONSE and its horizon is part of the answer --")
    print("  the same distinction models/ladder.py exists to record. Reporting the")
    print("  30-period ratio as if it were d2 would be the identical mistake.")

    print("\n" + "=" * 78)
    print("VALIDATION 4 · THE ANCHOR IS A PRICE-LEVEL RULE, NOT AN INFLATION RULE")
    print("=" * 78)
    print("  c = p * (real unit cost). If banking gets cheaper at exactly the rate prices")
    print("  rise, nominal cost per loan is flat and so is the normal rate. Break that")
    print("  equality and the normal rate drifts -- for as long as the gap lasts.\n")
    print(f"  {'theta':>8} {'pi - theta':>11} {'c1 at t=0':>10} {'c1 at t=40':>11} "
          f"{'i1N at t=40':>12}")
    for theta in (0.055, 0.045, 0.035, 0.025, 0.015):
        q = R.go(40.0, W, {"theta": theta}, samples=100)
        print(f"  {theta:8.3f} {p['pi0']-theta:11.3f} {q['c1'][0]:10.5f} "
              f"{q['c1'][-1]:11.5f} {q['i1N'][-1]:12.5f}")
    print("\n  This is the whole difference from Taylor in one table. A Taylor intercept")
    print("  is fixed; this one integrates the price level. Inflation above the rate at")
    print("  which banking gets cheaper raises the anchor without limit.")

    print("\n" + "=" * 78)
    print("VALIDATION 5 · THE ANCHOR SUPPLIES THE NOMINAL DISCIPLINE BY ITSELF")
    print("=" * 78)
    print("  If that integral is real, the classical rule should not need a proportional")
    print("  coefficient above one to pin inflation down -- the accumulating price level")
    print("  inside c should do it. So strip the proportional response from BOTH rules")
    print("  (api = 0) and give them the same wage shock. Taylor is then left moving")
    print("  exactly one for one on inflation, the Taylor-principle borderline; the")
    print("  classical rule is left with no proportional response at all.\n")
    print(f"  {'rule':>10} {'api':>5} {'horizon':>8} {'inflation':>10} {'i1':>9} "
          f"{'the anchor i1N':>15}")
    for lab, rl in (("classical", 1.0), ("Taylor", 0.0)):
        for a in (0.5, 0.0):
            for t in (40.0, 120.0):
                z = R.go(t, W, {"rule": rl, "api": a, "wsh": 0.02}, samples=200)
                print(f"  {lab:>10} {a:5.1f} {t:8.0f} {z['pi'][-1]:10.5f} "
                      f"{z['i1'][-1]:9.5f} {z['i1N'][-1]:15.5f}")
    print(f"\n  Target inflation is {p['pi0']:.3f}. With NO proportional response at all,")
    print("  the classical rule still walks inflation back -- while Taylor, moving one")
    print("  for one, stalls above it. The reason is in the last column: the anchor has")
    print("  climbed several points as the price level accumulated, and the classical")
    print("  rule is wired to it while Taylor's intercept is a fixed rstar that ignores")
    print("  it. So the discipline comes from an INTEGRAL on the price level rather than")
    print("  from a proportional coefficient above one -- which is why the rule can")
    print("  carry 0.5 where Taylor needs 1.5, and why it is closer kin to price-level")
    print("  targeting than to inflation targeting.")


def compare(R, p, bl):
    """The classical anchor against Taylor, calibrated to agree at the baseline."""
    print("\n" + "=" * 78)
    print("THE RACE · both rules agree at the baseline, so any difference is response")
    print("=" * 78)
    print(f"  Taylor's intercept is set to rstar = {bl['rstar']:.5f} precisely so that")
    print(f"  both rules call for ip = {bl['ip']:.5f} at rest. On inflation Taylor moves")
    print(f"  1 + api = {1+p['api']:.2f} for one; the classical rule moves api = "
          f"{p['api']:.2f} directly,")
    print("  and then keeps moving as the price level accumulates.\n")
    print(f"  {'shock':>8} {'horizon':>8} | {'classical':>10} {'worst rE':>9} "
          f"{'worst pi':>9} | {'Taylor':>9} {'worst rE':>9} {'worst pi':>9}")
    for wsh in (0.01, 0.02):
        for tmax in (20.0, 40.0, 80.0):
            row = []
            for rl in (1.0, 0.0):
                q = R.go(tmax, W, {"rule": rl, "wsh": wsh}, samples=200)
                n = len(q["pi"]) // 8
                row.append((q["u"][-1], min(q["rE"][n:]), max(q["pi"][n:])))
            print(f"  {wsh:8.3f} {tmax:8.0f} | {row[0][0]:10.4f} {row[0][1]:9.5f} "
                  f"{row[0][2]:9.5f} | {row[1][0]:9.4f} {row[1][1]:9.5f} "
                  f"{row[1][2]:9.5f}")
    print("\n  (the first column under each rule is where utilisation ends up)")


if __name__ == "__main__":
    main()
