"""Rung 2: firms can issue equity, so leverage becomes a financing choice.

    python3 models/enterprise_equity.py            # build, save, check the baseline
    python3 models/enterprise_equity.py --compare  # what equity finance does to the mechanism

WHY THIS RUNG, AND NOT THE ONE I FIRST CLAIMED
----------------------------------------------
The write-up said bank deposits were only 0.47 of the loan book "because households hold
no equity claim on firms' capital", and that giving them one would raise the deposit base
and let more of a policy move reach enterprise. That was wrong, and the arithmetic of
rung 1 says so plainly. There the bank balance sheet is an identity, DH = L - EB, and bank
capital is pinned by profit-rate equalisation:

    EB/L = (iL - iD - omegaB) / (r - iD)                = 0.562 at the baseline

which is a function of the lending rate, the deposit rate, operating costs and r, and of
NOTHING ELSE. No household portfolio enters it. Handing households a second asset cannot
move it. Bank leverage is high in this model because banks earn a fat net margin, 3.9% of
the loan book, and equalisation then demands the capital to match. Getting EB/L down to a
realistic 0.1 needs iL near 0.040, not a different asset for households to hold.

So corporate equity does not do what was claimed. It does something else, and the something
else is more interesting.

WHAT IT ACTUALLY DOES
---------------------
Firms meet the gap between what they invest and what they retain by borrowing OR by
issuing shares. Let psi be the share met by issuance:

    gap   = Inv - (1-payF)*PE       what has to be financed from outside
    Issue = psi * gap               shares
    NB    = (1-psi) * gap           debt

Leverage then settles at

    d* = (1-psi) * (1 - (1-payF)/kappa)

so the whole external financing requirement (1 - (1-payF)/kappa) is SPLIT by psi between
debt and equity, and only the debt half carries an interest bill. Since the mechanism runs
entirely through that bill,

    dg/dm = kappa * d* * pass-through = kappa * (1-psi) * d*_1 * pass-through

the strength of the enterprise-margin channel is PROPORTIONAL TO LEVERAGE, and equity
finance dilutes it one for one. An economy that funds accumulation by issuing shares is one
where the profit rate of enterprise barely responds to policy; a debt-funded one is where
Shaikh's mechanism bites hardest.

THE ACCOUNTING, WHICH IS NOT IMPOSED
------------------------------------
Real capital is financed by debt, outside equity, and accumulated retained earnings:

    K = L + E + RE

Each of the four is integrated separately from its own flow, and the identity is checked
against the run rather than enforced. It holds because Inv = retained + NB + Issue by
construction, so K' = RE' + L' + E'.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build import Builder, api                              # noqa: E402
import enterprise_banking as BANK                           # noqa: E402
import enterprise_core as CORE                              # noqa: E402

P = dict(BANK.P)
P.update(psi=0.0)       # share of the financing gap met by issuing shares
K0 = CORE.K0


def baseline(p):
    """Closed form. Only bank capital and the bank payout are solved; the rest is algebra."""
    cf = CORE.closed_form(p)
    r, g = cf["r"], cf["g"]
    d1 = cf["dstar"]                             # leverage with no equity finance at all
    dstar = (1.0 - p["psi"]) * d1                # split by psi between debt and equity
    ip = r - p["m"]
    iL, iD = ip + p["s"], p["dshare"] * ip
    rE = r - iL * dstar
    g = p["kappa"] * rE
    L, E = dstar * K0, p["psi"] * d1 * K0
    RE = K0 - L - E                              # the rest of the capital is retained earnings
    EB = L * (iL - iD - p["omegaB"]) / (r - iD)  # banking earns exactly r
    out = dict(cf)
    out.update(d1=d1, dstar=dstar, ip=ip, iL=iL, iD=iD, rE=rE, g=g, L=L, E=E, RE=RE,
               EB=EB, DH=L - EB, payB=1.0 - g / r,
               PB=iL * L - iD * (L - EB) - p["omegaB"] * L)
    out["rB"] = out["PB"] / EB if EB else float("nan")
    out["dg_dm"] = p["kappa"] * dstar             # before banking damps it
    return out


def build(p, bl):
    api("/api/clear")
    b = Builder()
    for nm in ("v", "omega", "u", "kappa", "payF", "omegaB", "dshare", "ths"):
        b.param(nm, float(p[nm]))
    b.param("payB", float(bl["payB"]))
    b.param("psi", float(p["psi"]), slider=(-0.05, 0.95))
    b.param("m", float(p["m"]), slider=(-0.02, 0.06))

    st = {"K": b.stock("K", K0), "L": b.stock("L", bl["L"]),
          "E": b.stock("E", bl["E"]), "RE": b.stock("RE", bl["RE"]),
          "EB": b.stock("EB", bl["EB"]), "s": b.stock("s", float(p["s"]))}

    for name, expr in [
        ("r",     "(1 - omega) * u / v"),
        ("ip",    "r - m"),                   # THE SHAIKH RULE
        ("iL",    "ip + s"),
        ("iD",    "dshare * ip"),
        ("d",     "L / K"),                   # leverage: only the DEBT half of financing
        ("rE",    "r - iL * d"),              # THE RATE OF PROFIT OF ENTERPRISE
        ("g",     "kappa * rE"),
        ("DH",    "L - EB"),
        ("IntL",  "iL * L"),
        ("IntD",  "iD * DH"),
        ("OpC",   "omegaB * L"),
        ("PB",    "IntL - IntD - OpC"),
        ("rB",    "PB / EB"),
        ("Inv",   "g * K"),
        ("PE",    "rE * K"),
        ("gap",   "Inv - (1 - payF) * PE"),   # what has to come from outside
        ("Issue", "psi * gap"),               # ...as shares
        ("NB",    "(1 - psi) * gap"),         # ...or as debt
        ("wealth", "DH + E"),                 # what households hold, for the record
        ("check", "K - L - E - RE"),          # an identity, imposed nowhere
        ("dK",    "Inv"),
        ("dL",    "NB"),
        ("dE",    "Issue"),
        ("dRE",   "(1 - payF) * PE"),
        ("dEB",   "(1 - payB) * PB"),
        ("ds",    "ths * (r - rB)"),
    ]:
        b.eq(name, expr)
    for state, deriv in (("K", "dK"), ("L", "dL"), ("E", "dE"), ("RE", "dRE"),
                         ("EB", "dEB"), ("s", "ds")):
        b.wire(b.ref[deriv], st[state], 1)

    b.plot("Rates", ["r", "iL", "ip", "rE"], at=[1800, 300])
    b.plot("How capital is financed", ["d", "g"], at=[1800, 800])
    api("/api/solver", {"implicit": False, "epsRel": 1e-8, "epsAbs": 1e-10, "tmax": 60.0})
    api("/api/layout")
    b.value_ids()
    return b


W = ["r", "ip", "iL", "iD", "d", "rE", "g", "rB", "s", "K", "L", "E", "RE", "EB",
     "DH", "wealth", "check"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--save", default="EnterpriseEquity")
    args = ap.parse_args()

    p = dict(P)
    bl = baseline(p)
    print("baseline at psi = 0 (no equity issued, so this must reproduce rung 1)")
    for k in ("r", "ip", "iL", "dstar", "rE", "g", "rB", "payB"):
        print(f"  {k:8s} {bl[k]:11.6f}")
    for k in ("L", "E", "RE", "EB", "DH"):
        print(f"  {k:8s} {bl[k]:11.4f}")

    build(p, bl)
    stt = api("/api/state", method="GET")
    print(f"\nbuilt {len(stt['items'])} items and {len(stt['wires'])} wires")
    api("/api/save", {"name": args.save})
    print(f"saved as {args.save}.mky")

    from runner import Run
    R = Run(f"~/minsky-models/{args.save}.mky")
    path = R.go(60.0, W, samples=200)
    print("\nis it a rest point, and does the financing identity hold?")
    drift = max(abs(path[k][-1] - path[k][0]) for k in ("r", "iL", "rE", "g", "d", "rB"))
    print(f"  rates drift at most {drift:.1e} over 60 periods")
    print(f"  K - L - E - RE stays at {max(abs(x) for x in path['check']):.1e} "
          f"(imposed nowhere)")
    print(f"  K x{path['K'][-1]/path['K'][0]:.4f}, L x{path['L'][-1]/path['L'][0]:.4f}, "
          f"EB x{path['EB'][-1]/path['EB'][0]:.4f}  (all must match)")

    if args.compare:
        compare(R, f"~/minsky-models/{args.save}.mky")


def compare(R, this_path):
    """Turn the equity dial and watch the mechanism weaken."""
    print("\n" + "=" * 78)
    print("EQUITY FINANCE DILUTES THE MECHANISM, ONE FOR ONE WITH LEVERAGE")
    print("=" * 78)
    print(f"  {'psi':>5} {'d*':>7} {'E/K':>7} {'DH/L':>7} | {'g at m=.04':>11} "
          f"{'g at m=.00':>11} {'dg/dm':>8} | {'kappa*d*':>9} {'ratio':>6}")
    for psi in (0.0, 0.25, 0.50, 0.75):
        p = dict(P); p["psi"] = psi
        bl = baseline(p)
        res = {}
        for m in (0.04, 0.00):
            q = R.use(this_path).go(12.0, W, {
                "m": m, "psi": psi, "payB": bl["payB"], "EB": bl["EB"],
                "L": bl["L"], "E": bl["E"], "RE": bl["RE"], "s": p["s"]}, samples=60)
            res[m] = (q["g"][-1], q["d"][-1], q["E"][-1] / q["K"][-1],
                      q["DH"][-1] / q["L"][-1])
        dg = (res[0.04][0] - res[0.00][0]) / 0.04
        print(f"  {psi:5.2f} {res[0.04][1]:7.4f} {res[0.04][2]:7.4f} {res[0.04][3]:7.4f} | "
              f"{res[0.04][0]:11.5f} {res[0.00][0]:11.5f} {dg:8.4f} | "
              f"{P['kappa']*bl['dstar']:9.4f} {dg/(P['kappa']*bl['dstar']):6.3f}")
    print("\n  d* falls one for one with psi, and dg/dm falls with it. The last column is")
    print("  the pass-through, and it does not move -- because DH/L does not move either.")
    print("  Corporate equity changes the STRENGTH of the mechanism, through leverage.")
    print("  It does not change the TRANSMISSION, which is the bank's business.")


if __name__ == "__main__":
    main()
