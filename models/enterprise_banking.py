"""Rung 1 of the ladder: the enterprise-margin core, plus a banking sector.

    python3 models/enterprise_banking.py            # build, save, check the baseline
    python3 models/enterprise_banking.py --compare  # core vs +banking vs the full model

The core (`enterprise_core.py`) says a point of margin is worth 0.95 points of growth. The
full model delivers 0.078. This model is the first step between them: the same two stocks,
plus the one thing Shaikh's second condition needs -- a banking sector whose own profit
rate is equalised on to the general rate, so the SPREAD stops being a parameter and starts
responding.

Still absent, deliberately: employment, prices, demand, capacity utilisation. The profit
rate is still taken as given. So whatever this rung explains of the gap is attributable to
banking alone.

WHAT IS ADDED
-------------
Banks fund loans with deposits and their own capital, which is an identity rather than a
behavioural story -- no household sector is needed for it:

    DH = L - EB                     deposits are whatever the loan book is not own-funded
    PB = iL*L - iD*DH - omegaB*L    bank profit
    rB = PB / EB                    banking's own profit rate
    s' = ths * (r - rB)             Shaikh's second condition, as a tendency
    EB' = (1 - payB) * PB           retained bank profit

WHAT THAT DOES TO THE ANSWER
----------------------------
Easing the margin lowers the policy rate, which lowers what banks pay on deposits AND
what they charge on loans. Which effect wins on their profit rate decides whether the
spread then widens or narrows -- that is, whether banking amplifies the margin's effect on
enterprise or works against it. Nothing here assumes an answer; the run reports it.

One thing the rung establishes on its own: equalisation does NOT pin the spread. It pins a
RELATION between the spread and bank capital -- for any spread there is a level of bank
capital at which banking earns exactly r. What pins the pair is that bank capital must
also grow at g, which is what `payB` is solved for.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build import Builder, api                              # noqa: E402
import enterprise_core as CORE                              # noqa: E402

P = dict(CORE.P)
P.update(
    omegaB=0.012,       # bank operating cost per unit of loans
    dshare=0.60,        # deposit rate as a share of the policy rate
    ths=0.50,           # speed banking's profit rate is equalised on to r
)
K0 = CORE.K0


def baseline(p):
    """The rest point. `payB` and bank capital are solved; nothing else is chosen."""
    cf = CORE.closed_form(p)                     # d*, rE*, g* are unchanged by banking
    r, dstar, g = cf["r"], cf["dstar"], cf["g"]
    ip = r - p["m"]
    iL, iD = ip + p["s"], p["dshare"] * ip
    L = dstar * K0
    # banking earns exactly r on its own capital: r*EB = iL*L - iD*(L-EB) - omegaB*L
    EB = L * (iL - iD - p["omegaB"]) / (r - iD)
    # and that capital has to grow at g, not at r, or leverage drifts
    payB = 1.0 - g / r
    out = dict(cf)
    out.update(ip=ip, iL=iL, iD=iD, L=L, EB=EB, DH=L - EB, payB=payB,
               PB=iL * L - iD * (L - EB) - p["omegaB"] * L)
    out["rB"] = out["PB"] / EB
    return out


def build(p, bl):
    api("/api/clear")
    b = Builder()
    for nm in ("v", "omega", "u", "kappa", "payF", "omegaB", "dshare", "ths"):
        b.param(nm, float(p[nm]))
    b.param("payB", float(bl["payB"]))
    b.param("m", float(p["m"]), slider=(-0.02, 0.06))

    iK = b.stock("K", K0)
    iL_ = b.stock("L", bl["L"])
    iEB = b.stock("EB", bl["EB"])
    iS = b.stock("s", float(p["s"]))

    for name, expr in [
        ("r",    "(1 - omega) * u / v"),
        ("ip",   "r - m"),                    # THE SHAIKH RULE
        ("iL",   "ip + s"),                   # the spread is a state now, not a parameter
        ("iD",   "dshare * ip"),
        ("d",    "L / K"),
        ("rE",   "r - iL * d"),               # THE RATE OF PROFIT OF ENTERPRISE
        ("g",    "kappa * rE"),
        ("DH",   "L - EB"),                   # banks' funding, as an identity
        ("IntL", "iL * L"),
        ("IntD", "iD * DH"),
        ("OpC",  "omegaB * L"),
        ("PB",   "IntL - IntD - OpC"),
        ("rB",   "PB / EB"),                  # banking's own profit rate
        ("Inv",  "g * K"),
        ("PE",   "rE * K"),
        ("NB",   "Inv - (1 - payF) * PE"),
        ("dK",   "Inv"),
        ("dL",   "NB"),
        ("dEB",  "(1 - payB) * PB"),
        ("ds",   "ths * (r - rB)"),           # SHAIKH'S SECOND CONDITION
    ]:
        b.eq(name, expr)
    for state, deriv in (("K", "dK"), ("L", "dL"), ("EB", "dEB"), ("s", "ds")):
        b.wire(b.ref[deriv], {"K": iK, "L": iL_, "EB": iEB, "s": iS}[state], 1)

    b.plot("Rates", ["r", "iL", "ip", "rE"], at=[1600, 300])
    b.plot("Banking", ["rB", "s", "iD"], at=[1600, 800])
    b.plot("Leverage and growth", ["d", "g"], at=[1600, 1300])
    api("/api/solver", {"implicit": False, "epsRel": 1e-8, "epsAbs": 1e-10, "tmax": 60.0})
    api("/api/layout")
    b.value_ids()
    return b


W = ["r", "ip", "iL", "iD", "d", "rE", "g", "rB", "s", "K", "L", "EB", "DH", "PB"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--save", default="EnterpriseBanking")
    args = ap.parse_args()

    p = dict(P)
    bl = baseline(p)
    print("baseline (payB and bank capital solved, everything else chosen)")
    for k in ("r", "ip", "iL", "iD", "dstar", "rE", "g", "rB", "payB"):
        print(f"  {k:8s} {bl[k]:11.6f}")
    for k in ("L", "EB", "DH"):
        print(f"  {k:8s} {bl[k]:11.4f}")
    print(f"  banking earns {bl['rB']:.6f} against r = {bl['r']:.6f} "
          f"({abs(bl['rB']-bl['r']):.1e})")

    build(p, bl)
    st = api("/api/state", method="GET")
    print(f"\nbuilt {len(st['items'])} items and {len(st['wires'])} wires")
    api("/api/save", {"name": args.save})
    print(f"saved as {args.save}.mky")

    from runner import Run
    R = Run(f"~/minsky-models/{args.save}.mky")
    path = R.go(60.0, W, samples=200)
    drift = {k: abs(path[k][-1] - path[k][0]) for k in ("r", "iL", "rE", "g", "d", "rB", "s")}
    print("\nis the baseline a rest point? drift over 60 periods:")
    print("  " + "  ".join(f"{k} {v:.1e}" for k, v in drift.items()))
    print(f"  bank capital grew x{path['EB'][-1]/path['EB'][0]:.4f}, "
          f"capital x{path['K'][-1]/path['K'][0]:.4f}  (they must match)")

    if args.compare:
        compare(R, f"~/minsky-models/{args.save}.mky")


def compare(R, this_path):
    """The same margin sweep on all three rungs, over the same twelve periods."""
    CORE_PATH = "~/minsky-models/EnterpriseCore.mky"
    FULL_PATH = "~/minsky-models/ShaikhMonetaryPolicy.mky"
    FW = ["r", "ipol", "iL", "dlev", "rE", "gacc"]
    print("\n" + "=" * 78)
    print("HOW MUCH OF THE GAP DOES BANKING EXPLAIN?")
    print("=" * 78)
    print(f"  {'m':>6} | {'core g':>8} {'core r':>8} | {'+bank g':>8} {'+bank r':>8} "
          f"{'+bank iL':>8} | {'full g':>8} {'full r':>8}")
    rows = []
    for m in (0.04, 0.03, 0.02, 0.01, 0.00):
        c = R.use(CORE_PATH).go(12.0, ["r", "rE", "g"], {"m": m}, samples=60)
        b = R.use(this_path).go(12.0, W, {"m": m}, samples=60)
        f = R.use(FULL_PATH).go(12.0, FW, {"rule": 1.0, "msh": m}, samples=60)
        rows.append((m, c["g"][-1], b["g"][-1], f["gacc"][-1]))
        print(f"  {m:6.3f} | {c['g'][-1]:8.5f} {c['r'][-1]:8.5f} | {b['g'][-1]:8.5f} "
              f"{b['r'][-1]:8.5f} {b['iL'][-1]:8.5f} | {f['gacc'][-1]:8.5f} "
              f"{f['r'][-1]:8.5f}")
    span = rows[0][0] - rows[-1][0]
    core = (rows[0][1] - rows[-1][1]) / span
    bank = (rows[0][2] - rows[-1][2]) / span
    full = (rows[0][3] - rows[-1][3]) / span
    print(f"\n  dg/dm    core {core:.3f}    +banking {bank:.3f}    full {full:.3f}")
    if core != full:
        share = (core - bank) / (core - full)
        print(f"  banking accounts for {share*100:.0f}% of the distance from the core to "
              f"the full model")
        print(f"  the remaining {100-share*100:.0f}% is the demand side, which is what "
              f"makes r move")
    passthrough(R, this_path, core)


def passthrough(R, this_path, core_slope):
    """What banking does to the margin, in one number: how much of a policy move lands.

    The lending rate is what enterprise actually pays, and it does not move with the
    policy rate one for one. Equalisation sees to that: a rise in rates is profitable for
    a bank whose loan book is bigger than its deposit base, so competition then narrows
    the spread and absorbs part of the move.
    """
    print("\n" + "=" * 78)
    print("WHAT BANKING DOES, IN ONE NUMBER: HOW MUCH OF A POLICY MOVE LANDS")
    print("=" * 78)
    print(f"  {'deposits pay':>12} {'DH/L':>6} | {'ip moves':>9} {'iL moves':>9} "
          f"{'pass-through':>13} | {'dg/dm':>7} {'kappa*d* x pt':>14}")
    for dshare in (0.0, 0.3, 0.6, 0.9):
        p = dict(P); p["dshare"] = dshare
        bl = baseline(p)
        res = {}
        for m in (0.04, 0.00):
            q = R.use(this_path).go(12.0, W, {"m": m, "dshare": dshare,
                                              "payB": bl["payB"], "EB": bl["EB"],
                                              "s": p["s"]}, samples=60)
            res[m] = (q["ip"][-1], q["iL"][-1], q["g"][-1], q["DH"][-1] / q["L"][-1])
        dip = res[0.00][0] - res[0.04][0]
        dil = res[0.00][1] - res[0.04][1]
        dg = (res[0.04][2] - res[0.00][2]) / 0.04
        pt = dil / dip if dip else float("nan")
        print(f"  {dshare:12.2f} {res[0.04][3]:6.2f} | {dip:9.4f} {dil:9.4f} "
              f"{pt:13.2f} | {dg:7.3f} {core_slope*pt:14.3f}")
    print("\n  The last two columns are the point: banking's whole contribution is the")
    print("  pass-through, and the core's elasticity is simply multiplied by it.")
    print("  Deposits here are 0.47 of the loan book, against something nearer 0.9 for a")
    print("  real bank -- so this model UNDERSTATES how much of a policy move reaches")
    print("  enterprise, and understates the mechanism with it.")


if __name__ == "__main__":
    main()
