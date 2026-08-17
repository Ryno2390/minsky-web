"""The enterprise-margin mechanism on its own, small enough to solve by hand.

    python3 models/enterprise_core.py            # build, save, and check against theory
    python3 models/enterprise_core.py --compare  # and against the full model

WHY A SECOND MODEL
------------------
`shaikh_monetary_policy.py` has the mechanism in it, but it also has a wage-price spiral,
a demand multiplier, an endogenous profit rate and a Harrod instability. Every experiment
there measures all of them at once, so a number like "growth falls 0.4 points when the
margin closes" cannot be attributed. This model has the mechanism and nothing else, which
makes it solvable -- and a closed form gives elasticities rather than tables.

Deliberately NOT here: employment, prices, demand, capacity utilisation, a banking sector,
and any Godley table. Accumulation is not what double entry is for; the full model carries
the accounting and this one carries the mechanism.

THE WHOLE MODEL
---------------
Two stocks, real capital and debt, with the profit rate taken as given:

    r  = (1-omega) * u / v          the pre-interest profit rate
    iL = (r - m) + s                policy holds ip a margin m below r; banks add a spread
    d  = L / K                      leverage
    rE = r - iL * d                 THE RATE OF PROFIT OF ENTERPRISE
    g  = kappa * rE                 accumulation out of it
    K' = g * K
    L' = g*K - (1-payF)*rE*K        firms borrow what they invest less what they retain

WHAT FALLS OUT
--------------
In leverage alone, d = L/K obeys

    d' = (r - iL*d) * (A - kappa*d)        A = kappa - 1 + payF

a quadratic with two rest points: d* = A/kappa, where leverage settles, and d = r/iL,
where the enterprise profit rate hits zero. Linearising at the first gives

    f'(d*) = -kappa * rE*

so THE GROWTH EQUILIBRIUM IS STABLE EXACTLY WHEN rE* > 0. Push the lending rate past
r/d* and the only rest point left is the one where enterprise profit is nothing and
accumulation stops. That is the claim, as a stability condition rather than a simulation.

And because iL = r - m + s, growth is linear in the margin:

    g* = kappa * (r*(1 - d*) + (m - s)*d*)          dg*/dm = kappa * d*

which is the number the full model cannot report, because there r moves too.
"""
import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build import Builder, api                      # noqa: E402

P = dict(
    v=3.0,          # capital to capacity-output ratio
    omega=1.0/1.35, # wage share (the full model's markup, at rest)
    u=0.792776,     # capacity utilisation (the full model's baseline)
    kappa=1.20,     # accumulation out of the enterprise profit rate
    payF=0.75,      # share of profit of enterprise paid out
    s=0.022128,     # lending spread over the policy rate (a parameter here)
    m=0.030,        # THE MARGIN: policy holds ip this far below r
)
K0 = 100.0


def closed_form(p):
    """Solve the model on paper. Everything here is exact, not simulated."""
    r = (1.0 - p["omega"]) * p["u"] / p["v"]
    A = p["kappa"] - 1.0 + p["payF"]
    dstar = A / p["kappa"]                       # leverage where L and K grow together
    iL = (r - p["m"]) + p["s"]
    rE = r - iL * dstar
    out = dict(r=r, A=A, dstar=dstar, iL=iL, ip=r - p["m"], rE=rE, g=p["kappa"] * rE)
    # d' = (r - iL*d)(A - kappa*d); the slope at d* decides whether growth survives
    out["slope"] = -p["kappa"] * rE
    out["stable"] = rE > 0
    # growth is linear in the margin, so the elasticity is a number, not a table
    out["dg_dm"] = p["kappa"] * dstar
    # the margin at which enterprise profit is exactly nothing
    out["m_zero"] = r * (1.0 - 1.0 / dstar) + p["s"]
    out["iL_max"] = r / dstar                    # the lending rate that leaves nothing
    return out


def build(p):
    """The same model as a Minsky diagram, so it can be opened, run and pulled on."""
    api("/api/clear")
    b = Builder()
    for nm in ("v", "omega", "u", "kappa", "payF", "s"):
        b.param(nm, float(p[nm]))
    b.param("m", float(p["m"]), slider=(-0.02, 0.06))

    cf = closed_form(p)
    iK = b.stock("K", K0)
    iL_ = b.stock("L", cf["dstar"] * K0)

    for name, expr in [
        ("r",   "(1 - omega) * u / v"),      # the pre-interest profit rate, taken as given
        ("ip",  "r - m"),                    # THE SHAIKH RULE
        ("iL",  "ip + s"),
        ("d",   "L / K"),                    # leverage
        ("rE",  "r - iL * d"),               # THE RATE OF PROFIT OF ENTERPRISE
        ("g",   "kappa * rE"),
        ("Inv", "g * K"),
        ("PE",  "rE * K"),
        ("NB",  "Inv - (1 - payF) * PE"),    # borrow the gap between investing and retaining
        ("dK",  "Inv"),
        ("dL",  "NB"),
    ]:
        b.eq(name, expr)
    b.wire(b.ref["dK"], iK, 1)
    b.wire(b.ref["dL"], iL_, 1)

    b.plot("Rates", ["r", "iL", "ip", "rE"], at=[1500, 300])
    b.plot("Leverage and growth", ["d", "g"], at=[1500, 800])
    api("/api/solver", {"implicit": False, "epsRel": 1e-8, "epsAbs": 1e-10, "tmax": 60.0})
    api("/api/layout")
    b.value_ids()
    return b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", action="store_true",
                    help="also measure the full model at the same horizons")
    ap.add_argument("--save", default="EnterpriseCore")
    args = ap.parse_args()

    p = dict(P)
    cf = closed_form(p)
    print("closed form")
    for k in ("r", "ip", "iL", "dstar", "rE", "g", "dg_dm", "m_zero", "iL_max"):
        print(f"  {k:8s} {cf[k]:11.6f}")
    print(f"  {'stable':8s} {cf['stable']}   (the growth equilibrium survives only "
          f"while rE > 0)")

    build(p)
    st = api("/api/state", method="GET")
    print(f"\nbuilt {len(st['items'])} items and {len(st['wires'])} wires")
    api("/api/save", {"name": args.save})
    print(f"saved as {args.save}.mky")

    from runner import Run
    R = Run(f"~/minsky-models/{args.save}.mky")
    W = ["r", "ip", "iL", "d", "rE", "g", "K", "L"]

    print("\ndoes the diagram agree with the paper?")
    path = R.go(60.0, W, samples=200)
    worst = max(abs(path[k][-1] - cf[k]) for k in ("r", "ip", "iL", "rE", "g"))
    print(f"  after 60 periods, the rates differ from the closed form by at most "
          f"{worst:.2e}")
    print(f"  leverage settled at {path['d'][-1]:.6f}, theory says {cf['dstar']:.6f} "
          f"({abs(path['d'][-1]-cf['dstar']):.1e})")
    grew = path["K"][-1] / path["K"][0]
    print(f"  K grew x{grew:.4f}, e^(g*t) = {math.exp(cf['g']*path['t'][-1]):.4f}")

    print("\nis the stability condition right? push the margin below m_zero and growth "
          "should stop")
    print(f"  {'m':>8} {'rE':>10} {'g':>10} {'d at t=60':>10}  {'':2}")
    for m in (0.040, 0.030, 0.020, 0.010, cf["m_zero"] + 0.002, cf["m_zero"] - 0.002):
        q = R.go(60.0, W, {"m": m}, samples=100)
        tag = "growth stops" if q["g"][-1] <= 1e-6 else ""
        print(f"  {m:8.4f} {q['rE'][-1]:10.5f} {q['g'][-1]:10.5f} {q['d'][-1]:10.5f}  {tag}")

    # d* is a rest point whichever way it is unstable, so a run started exactly on it
    # never leaves. Nudging it is the only way to see the stability condition work.
    print("\n  the stability condition, by nudging leverage 1% off d* and watching:")
    print(f"  {'m':>8} {'rE*':>9} | {'measured':>9} {'predicted':>10}  verdict")
    for m in (0.040, 0.030, cf["m_zero"] + 0.002, cf["m_zero"] - 0.004):
        q = R.go(80.0, W, {"m": m, "L": 1.01 * cf["dstar"] * K0}, samples=100)
        rEstar = cf["r"] - ((cf["r"] - m) + p["s"]) * cf["dstar"]
        d0 = abs(q["d"][0] - cf["dstar"])
        d1 = abs(q["d"][-1] - cf["dstar"])
        measured = d1 / d0 if d0 else float("nan")
        # linearising d' = (r - iL*d)(A - kappa*d) at d* gives f'(d*) = -kappa*rE*,
        # so a deviation should go as exp(-kappa*rE* t)
        predicted = math.exp(-p["kappa"] * rEstar * q["t"][-1])
        verdict = "returns to d*" if rEstar > 0 else "walks away from d*"
        print(f"  {m:8.4f} {rEstar:+9.5f} | {measured:9.3f} {predicted:10.3f}  {verdict}")
    print("  the eigenvalue is -kappa*rE*, so growth survives exactly while rE* > 0")

    if args.compare:
        compare(R, cf, f'~/minsky-models/{args.save}.mky')


def compare(R, cf, core_path):
    """The same margin sweep in both models, at the same horizon, on the same axis.

    One runner, loaded alternately: pyminsky holds one model per process.
    """
    FULL = "~/minsky-models/ShaikhMonetaryPolicy.mky"
    FW = ["r", "ipol", "iL", "dlev", "rE", "gacc", "K"]
    print("\n" + "=" * 74)
    print("THE CORE AGAINST THE FULL MODEL: how much growth does a point of margin buy?")
    print("=" * 74)
    print(f"  {'m':>7} | {'core g':>9} {'core rE':>9} {'core r':>8} | "
          f"{'full g':>9} {'full rE':>9} {'full r':>8}")
    rows = []
    for m in (0.04, 0.03, 0.02, 0.01, 0.00):
        c = R.use(core_path).go(12.0, ["r", "rE", "g", "d"], {"m": m}, samples=60)
        f = R.use(FULL).go(12.0, FW, {"rule": 1.0, "msh": m}, samples=60)
        rows.append((m, c["g"][-1], f["gacc"][-1]))
        print(f"  {m:7.3f} | {c['g'][-1]:9.5f} {c['rE'][-1]:9.5f} {c['r'][-1]:8.5f} | "
              f"{f['gacc'][-1]:9.5f} {f['rE'][-1]:9.5f} {f['r'][-1]:8.5f}")
    span = rows[0][0] - rows[-1][0]
    core = (rows[0][1] - rows[-1][1]) / span
    full = (rows[0][2] - rows[-1][2]) / span
    print(f"\n  dg/dm measured over that range:  core {core:.3f}   full {full:.3f}"
          f"   ({core/full if full else float('nan'):.0f}x)")
    print(f"  and on paper the core is exactly kappa*d* = {cf['dg_dm']:.3f}")
    print("\n  The core says a point of margin is worth about a point of growth. The full")
    print("  model delivers a fraction of that, because there r is not a given: it moves")
    print("  with policy, and the movement offsets the mechanism.")


if __name__ == "__main__":
    main()
