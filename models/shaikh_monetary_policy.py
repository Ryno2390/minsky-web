"""A monetary policy model on Shaikh's profit-rate-of-enterprise principle.

    python3 models/shaikh_monetary_policy.py            # build and save
    python3 models/shaikh_monetary_policy.py --run      # build, save, and compare rules

THE ARGUMENT
------------
What drives a capitalist economy is not the profit rate but the profit rate NET OF
INTEREST -- the rate of profit of enterprise. Shaikh writes it

    rE = r - iL * d           r  = pre-interest profit rate, P/pK
                              iL = the rate firms borrow at
                              d  = leverage, L/pK

Net investment is financed out of what is left after the creditor is paid, so
accumulation keys off rE, not r. That gives monetary policy an observable anchor. If the
interest rate is pushed towards r there is nothing left for enterprise, accumulation
stops, and growth chokes. So a consistent policy takes its cue from the aggregate,
pre-interest profit rate:

    SHAIKH RULE     ip = r - m         preserve an enterprise margin m below r

against the usual alternative, which has no information about r at all:

    TAYLOR RULE     ip = r* + inf + aInf*(inf - inf*) + aU*(u - u*)

The second Shaikh condition is that banking is a business like any other, so competition
turbulently equalises ITS profit rate with the general rate. That pins the spread rather
than the level: the difference between what banks pay and what they charge, net of
operating costs, has to earn banking the going rate on its own capital.

    rB = (iL*L - iD*DH - OpC) / EB       and    d(spread)/dt = ths * (r - rB)

Written as a tendency, not an identity, because that is Shaikh's actual claim: rates are
equalised by capital moving in and out, always overshooting, never exactly equal.

WHAT IS AND IS NOT IN A GODLEY TABLE
------------------------------------
Every financial stock and every payment lives in double-entry Godley tables -- one per
sector, sharing the stocks they hold against each other. Real capital K does not: it is
not a financial claim on anybody, so it has no counterparty and no place in a balance
sheet of claims. It is an ordinary integral, which is also what Keen's own Minsky models
do.

The accounting is not decoration. Two identities fall out of it and are checked against
the run in `--run`:

    DF is constant        firms borrow exactly their financing gap, so their deposits
                          never drift. Any drift is an accounting error.
    Res + Loans = DF + DH + EB      the banking balance sheet closes at every step.

Neither is imposed anywhere. They hold because the flows were written down consistently,
so if either breaks, the model is wrong.
"""
import argparse
import asyncio
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build import Builder, api, BuildError          # noqa: E402

# --------------------------------------------------------------------------- parameters
P = dict(
    # production and growth
    v=3.0,              # capital to capacity-output ratio
    alpha=0.015,        # labour productivity growth
    beta=0.010,         # labour force growth
    # Accumulation out of the profit rate of enterprise:
    #     g_target = gnorm + kappa * (rE - rEnorm)
    # The LEVEL and the RESPONSE are separate on purpose. Written as g = kappa*rE they
    # are the same number, and it has to do two incompatible jobs: it sets leverage (a
    # firm that invests more than it retains must borrow the difference) and it sets the
    # gain of the accelerator. Tying them together forced kappa=1.2, and the accelerator
    # gain kappa*d(rE)/d(g) = 1.76 -- above one, so the balanced path was a Harrod
    # knife-edge that a 1e-7 rounding error was enough to push into a debt deflation.
    # Split apart, leverage is set by dlevTarget and kappa is free to be stable.
    kappa=0.20,         # how strongly accumulation responds to rE
    dlevTarget=0.80,    # loans per unit of capital on the balanced path
    thg=2.0,            # how fast investment plans catch up to the target
    payF=0.75,          # share of profit of enterprise paid out to households
    # consumption
    c1=0.88,            # out of income
    c2=0.06,            # out of deposits
    # labour market and prices
    # Phillips curve, Keen's nonlinear form: phi(lam) = phi1/(1-lam)^2 - phi0. It goes
    # vertical as employment approaches the labour force, which a linear curve does not
    # -- and without that barrier the model happily ran employment past 100%.
    lamStar=0.875,      # employment rate on the balanced path
    lamZero=0.80,       # employment rate at which money wages stop rising
    gam=0.60,           # wage indexation to inflation
    etap=0.40,          # speed of price adjustment
    mu=1.35,            # target markup; wage share 1/mu leaves inflation at zero
    # banking
    omegaB=0.012,       # bank operating cost per unit of loans
    dshare=0.60,        # deposit rate as a share of the policy rate
    ths=0.50,           # speed the spread equalises banking's profit rate on to r
    payB=None,          # bank payout ratio -- SOLVED, so bank capital grows with the rest
    # policy
    thi=1.50,           # how fast the policy rate moves to its target
    msh=0.030,          # SHAIKH RULE: enterprise margin held below r
    aInfl=1.50,         # TAYLOR RULE: response to inflation
    aU=0.50,            #              response to the utilisation gap
    rule=1.0,           # 1 = Shaikh, 0 = Taylor, in between = a blend
)
#: Calibration targets. The baseline is put ON a balanced growth path so that anything
#: that moves afterwards moves because the model made it move.
CAL = dict(K0=100.0, ustar=0.80, DF0=5.0)


def steady_state(p, cal):
    """Solve for a balanced growth path. Nothing here is imposed that the theory decides.

    The spread is SOLVED, not chosen. That is Shaikh's second condition doing its work:
    banking is a business, so competition drives its own profit rate on to the general
    rate, and what that pins is the difference between the borrowing and lending rates
    net of operating costs. Choosing the spread by hand would have thrown the claim away
    and then quietly assumed it back.

    Levels are homogeneous of degree one, so everything scales off K. Solved jointly:

      r        the aggregate pre-interest profit rate
      spread   from banking's profit rate equalising on to r
      DH       household deposits, growing at g and no faster
      EB       bank capital, at the level where banking earns exactly r

    One parameter is not free either: payB, the bank payout ratio, is what leaves bank
    capital growing at g rather than at r, so leverage does not drift.
    """
    from scipy.optimize import fsolve

    s = dict(p)
    s["omega"] = omega = 1.0 / p["mu"]          # zero-inflation wage share
    s["gacc"] = gacc = p["alpha"] + p["beta"]   # balanced growth needs g = alpha + beta
    s["gnorm"] = gacc
    # Leverage is chosen, and the enterprise profit rate that sustains it follows: loans
    # grow at g only if firms borrow exactly the gap between what they invest and what
    # they retain, which is dlev = 1 - (1-payF)*rE/g.
    s["dlev"] = dlev = p["dlevTarget"]
    if not 0.0 < dlev < 1.0:
        raise SystemExit(f"dlevTarget must be between 0 and 1, not {dlev}")
    s["rE"] = s["rEnorm"] = rE = gacc * (1.0 - dlev) / (1.0 - p["payF"])
    K = cal["K0"]
    s["lam"] = p["lamStar"]                 # money wages rise with productivity here
    # phi0, phi1 are what put the Phillips curve through (lamZero, 0) and (lamStar, alpha)
    ratio = ((1.0 - p["lamZero"]) / (1.0 - p["lamStar"])) ** 2
    if ratio <= 1.0:
        raise SystemExit("lamZero must be below lamStar")
    s["phi0"] = phi0 = p["alpha"] / (ratio - 1.0)
    s["phi1"] = phi0 * (1.0 - p["lamZero"]) ** 2
    A = omega + p["payF"] * (1.0 - omega)
    Loans = dlev * K

    def unpack(x):
        r, spread, DH, EB = x
        ipol = r - p["msh"]                     # the Shaikh rule, at rest
        # proportional, not a fixed subtraction: a fixed one drives the deposit rate
        # through zero whenever policy is low, which is not a deposit market
        iL, iD = ipol + spread, p["dshare"] * ipol
        pY = r * K / (1.0 - omega)              # from the definition of r
        Wages = omega * pY
        IntL, IntD = iL * Loans, iD * DH
        OpC = p["omegaB"] * Loans
        PB = IntL - IntD - OpC
        payB = 1.0 - gacc / r                   # so (1-payB)*rB = g when rB = r
        DivB = payB * PB
        PE = (pY - Wages) - IntL
        DivF = p["payF"] * PE
        Binc = OpC + IntD - p["payF"] * IntL + DivB
        YD = Wages + OpC + IntD + DivF + DivB
        return locals()

    def residual(x):
        d = unpack(x)
        return [
            # accumulation: the enterprise profit rate that sustains g
            (d["r"] - d["iL"] * dlev) - rE,
            # banking earns the general rate on its own capital
            d["PB"] - d["r"] * d["EB"],
            # demand determines output, and it must be the output r was defined on
            d["pY"] * (1.0 - p["c1"] * A)
            - (p["c1"] * d["Binc"] + p["c2"] * d["DH"] + gacc * K),
            # households' deposits grow at g, no faster
            (1.0 - p["c1"]) * d["YD"] - (p["c2"] + gacc) * d["DH"],
        ]

    x, _info, ok, msg = fsolve(residual, [0.07, 0.02, 0.5 * K, 0.1 * K],
                               full_output=True)[0:4]
    if ok != 1 or max(abs(v) for v in residual(x)) > 1e-9:
        raise SystemExit(f"no consistent steady state for these parameters: {msg}")

    s.update({k: v for k, v in unpack(x).items()
              if isinstance(v, float) and k not in ("x",)})
    s["Loans"] = Loans
    s["u"] = s["Y"] = s["pY"]                   # price is 1 at the baseline
    s["u"] = s["pY"] * p["v"] / K               # capacity utilisation
    s["Y"] = s["pY"]
    s["Profit"] = s["pY"] - s["Wages"]
    s["Cons"] = s["pY"] - gacc * K
    s["InvN"] = gacc * K
    s["NB"] = gacc * K - (1.0 - p["payF"]) * s["PE"]
    # Minsky decides whether a row balances with `i->second != 0` -- an EXACT comparison,
    # no tolerance (model/godleyTable.cc). A balance sheet that is out by 1e-15 is
    # therefore reported as not balancing, and it is right to: the accounting either
    # closes or it does not. So the opening figures are snapped to multiples of 1/1024,
    # which are exact in binary, and the residual column is computed from those. Sums and
    # differences of such numbers at this magnitude are exact, so the row cancels to
    # exactly zero rather than nearly zero.
    q = lambda z: round(z * 1024.0) / 1024.0                    # noqa: E731
    s["DH"], s["EB"] = q(s["DH"]), q(s["EB"])
    s["Loans"] = Loans = q(Loans)
    s["DF"] = DF = q(cal["DF0"])
    s["Res"] = Res = DF + s["DH"] + s["EB"] - Loans     # closes the bank balance sheet
    if Res < 0:
        raise SystemExit(f"reserves come out negative ({Res:.2f}); raise DF0")
    resid = ((((Res + Loans) - DF) - s["DH"]) - s["EB"])         # the engine's own order
    if resid != 0.0:
        raise SystemExit(f"the opening balance sheet is out by {resid:.2e}")
    s["NWF"] = DF - Loans                       # firms are net financial debtors
    s["NWH"] = s["DH"]
    s["ell"] = s["pY"]                          # productivity is 1 at the baseline
    s["Nlab"] = s["pY"] / s["lam"]
    s["wage"] = omega
    s["K0"] = K
    return s


# ------------------------------------------------------------------------------- build
def build(s, p):
    """Lay the model out: three Godley tables, then the equations that drive them."""
    api("/api/clear")
    b = Builder()

    # ---- the money system, in double entry -------------------------------------------
    # Every payment appears twice, and each row nets to zero:
    # assets - liabilities - equity = 0. That is the whole discipline.
    bank = [
        ("Res", "asset", s["Res"]), ("Loans", "asset", s["Loans"]),
        ("DF", "liability", s["DF"]), ("DH", "liability", s["DH"]),
        ("EB", "equity", s["EB"]),
    ]
    bank_rows = [
        ("Net borrowing",     {"Loans": "NB",     "DF": "NB"}),
        ("Interest on loans", {"DF": "-IntL",     "EB": "IntL"}),
        ("Interest on deposits", {"DH": "IntD",   "EB": "-IntD"}),
        ("Bank operating costs", {"DH": "OpC",    "EB": "-OpC"}),
        ("Bank dividends",    {"DH": "DivB",      "EB": "-DivB"}),
        ("Wages",             {"DF": "-Wages",    "DH": "Wages"}),
        ("Firm dividends",    {"DF": "-DivF",     "DH": "DivF"}),
        ("Consumption",       {"DF": "Cons",      "DH": "-Cons"}),
    ]
    firms = [("DF", "asset", s["DF"]), ("Loans", "liability", s["Loans"]),
             ("NWF", "equity", s["NWF"])]
    firm_rows = [
        ("Net borrowing",     {"DF": "NB",      "Loans": "NB"}),
        ("Interest on loans", {"DF": "-IntL",   "NWF": "-IntL"}),
        ("Wages",             {"DF": "-Wages",  "NWF": "-Wages"}),
        ("Firm dividends",    {"DF": "-DivF",   "NWF": "-DivF"}),
        ("Consumption",       {"DF": "Cons",    "NWF": "Cons"}),
    ]
    house = [("DH", "asset", s["DH"]), ("NWH", "equity", s["NWH"])]
    house_rows = [
        ("Interest on deposits", {"DH": "IntD", "NWH": "IntD"}),
        ("Bank operating costs", {"DH": "OpC",  "NWH": "OpC"}),
        ("Bank dividends",    {"DH": "DivB",    "NWH": "DivB"}),
        ("Wages",             {"DH": "Wages",   "NWH": "Wages"}),
        ("Firm dividends",    {"DH": "DivF",    "NWH": "DivF"}),
        ("Consumption",       {"DH": "-Cons",   "NWH": "-Cons"}),
    ]

    # well clear of the equation blocks: Minsky refuses to wire items that overlap, and
    # the tables are large enough to sit on top of a whole column of them
    for title, cols, rows, at in (("Banks", bank, bank_rows, [3400, 300]),
                                  ("Firms", firms, firm_rows, [3400, 1100]),
                                  ("Households", house, house_rows, [3400, 1800])):
        g = str(api("/api/item", {"kind": "godley", "name": title, "at": at})["index"])
        api(f"/api/godley/{g}/resize", {"rows": 2 + len(rows), "cols": 1 + len(cols)})
        for c, (nm, cls, ic) in enumerate(cols, start=1):
            api(f"/api/godley/{g}/cell", {"row": 0, "col": c, "value": nm})
            api(f"/api/godley/{g}/cell", {"row": 1, "col": c, "value": f"{ic:.17g}"})
            api(f"/api/godley/{g}/class", {"col": c, "cls": cls})
        for rix, (label, entries) in enumerate(rows, start=2):
            api(f"/api/godley/{g}/cell", {"row": rix, "col": 0, "value": label})
            for c, (nm, _cls, _ic) in enumerate(cols, start=1):
                if nm in entries:
                    api(f"/api/godley/{g}/cell",
                        {"row": rix, "col": c, "value": entries[nm]})
        t = api(f"/api/godley/{g}", method="GET")
        bad = [i for i, v in enumerate(t["rowSums"]) if v not in (None, "0")]
        if bad:
            raise SystemExit(f"{title}: rows {bad} do not balance: {t['rowSums']}")

    b.scan()        # pick up every stock and flow the tables just created

    # ---- parameters -------------------------------------------------------------------
    for nm in ("v", "alpha", "beta", "kappa", "thg", "payF", "c1", "c2", "phi1",
               "gam", "etap", "mu", "omegaB", "dshare", "ths", "payB", "thi",
               "msh", "aInfl", "aU", "phi0", "phi1", "gnorm", "rEnorm"):
        b.param(nm, float(p.get(nm) if p.get(nm) is not None else s[nm]))
    # a rule dial rather than two models: 1 = Shaikh, 0 = Taylor, in between = a blend
    # the dial runs a little past each end because the engine refuses slider bounds the
    # current value sits exactly on, and the value starts at 1
    b.param("rule", p["rule"], slider=(-0.25, 1.25))
    # the two rules are made to AGREE at the baseline, so any difference between them
    # later is a difference in how they respond, not in where they start
    b.param("rstar", s["ipol"])
    b.param("inflstar", 0.0)
    b.param("ustar", s["u"])

    # ---- states ------------------------------------------------------------------------
    ints = {}
    for nm, init in (("K", s["K0"] if "K0" in s else CAL["K0"]),
                     ("prod", 1.0), ("Nlab", s["Nlab"]), ("wage", s["wage"]),
                     ("price", 1.0), ("gacc", s["gacc"]), ("spread", s["spread"]),
                     ("ipol", s["ipol"])):
        ints[nm] = b.stock(nm, float(init))

    # ---- equations ---------------------------------------------------------------------
    # Order matters: Minsky wires values forward, so nothing may be used before it is
    # defined. There are no algebraic loops -- the policy rate, the spread and the
    # accumulation rate are all states that adjust towards their targets, which is both
    # realistic and what keeps the right-hand side explicit.
    EQNS = [
        ("omega",  "wage / (price * prod)"),                 # wage share
        ("iL",     "ipol + spread"),                         # lending rate
        ("iD",     "dshare * ipol"),                         # deposit rate
        ("IntL",   "iL * Loans"),
        ("IntD",   "iD * DH"),
        ("OpC",    "omegaB * Loans"),
        ("PB",     "IntL - IntD - OpC"),                     # bank profit
        ("DivB",   "payB * PB"),
        ("Amul",   "omega + payF * (1 - omega)"),            # income share of output
        ("Binc",   "OpC + IntD - payF * IntL + DivB"),       # income not tied to output
        # demand determines output; the multiplier is explicit rather than iterated
        ("pY",     "(c1 * Binc + c2 * DH + price * gacc * K) / (1 - c1 * Amul)"),
        ("Y",      "pY / price"),
        ("Wages",  "omega * pY"),
        ("Profit", "pY - Wages"),                            # pre-interest profit
        ("PE",     "Profit - IntL"),                         # PROFIT OF ENTERPRISE
        ("DivF",   "payF * PE"),
        ("Cons",   "c1 * (Amul * pY + Binc) + c2 * DH"),
        ("InvN",   "price * gacc * K"),
        ("NB",     "InvN - (1 - payF) * PE"),                # net borrowing
        ("ell",    "Y / prod"),
        ("lam",    "ell / Nlab"),
        ("u",      "Y * v / K"),                             # capacity utilisation
        ("r",      "Profit / (price * K)"),                  # AGGREGATE PROFIT RATE
        ("dlev",   "Loans / (price * K)"),
        ("rE",     "r - iL * dlev"),                         # RATE OF PROFIT OF ENTERPRISE
        ("rB",     "PB / EB"),                               # banking's own profit rate
        ("infl",   "etap * (mu * omega - 1)"),
        ("ipT",    "rstar + infl + aInfl * (infl - inflstar) + aU * (u - ustar)"),
        ("ipS",    "r - msh"),                               # THE SHAIKH RULE
        ("ipTgt",  "rule * ipS + (1 - rule) * ipT"),
        # derivatives
        ("dK",      "gacc * K"),
        ("dprod",   "alpha * prod"),
        ("dNlab",   "beta * Nlab"),
        # vertical as lam -> 1: the labour force is a real barrier, not a slope
        ("dwage",   "wage * (phi1 / (1 - lam) ** 2 - phi0 + gam * infl)"),
        ("dprice",  "infl * price"),
        # investment plans adjust towards what the enterprise profit rate supports
        ("dgacc",   "thg * (gnorm + kappa * (rE - rEnorm) - gacc)"),
        ("dspread", "ths * (r - rB)"),                       # profit rates equalise
        ("dipol",   "thi * (ipTgt - ipol)"),                 # policy rate moves to target
    ]
    for name, expr in EQNS:
        b.eq(name, expr)

    for state, deriv in (("K", "dK"), ("prod", "dprod"), ("Nlab", "dNlab"),
                         ("wage", "dwage"), ("price", "dprice"), ("gacc", "dgacc"),
                         ("spread", "dspread"), ("ipol", "dipol")):
        b.wire(b.ref[deriv], ints[state], 1)

    # Minsky's defaults -- implicit, epsRel 1e-8, epsAbs 1e-10 -- take 0.0005-long steps
    # at 45ms each on this model, so a 60-period run would take about an hour. The
    # explicit method at 1e-6/1e-8 takes steps 140x longer at a thirtieth of the cost and
    # lands in the same place (see --check). Saved that way so the model is usable the
    # moment it is opened.
    api("/api/solver", {"implicit": False, "order": 4, "epsRel": 1e-6, "epsAbs": 1e-8,
                        "tmax": 60.0})
    api("/api/layout")
    b.value_ids()
    return b


# --------------------------------------------------------------------------------- run
WATCH = ["r", "rE", "rB", "ipol", "iL", "gacc", "u", "infl", "dlev", "lam", "omega",
         "K", "Loans", "DH", "EB", "DF", "Res", "PE", "Profit", "IntL"]


def audit(path):
    """The two identities the model never imposed, checked against what it did.

    Both follow from writing the flows down consistently. Neither is enforced anywhere,
    so either one drifting means the accounting is wrong, not merely imprecise.
    """
    bal = max(abs(Res + L - DF - DH - EB) / max(abs(L), 1.0)
              for Res, L, DF, DH, EB in zip(path["Res"], path["Loans"], path["DF"],
                                            path["DH"], path["EB"]))
    df0 = path["DF"][0]
    drift = max(abs(x - df0) for x in path["DF"]) / max(abs(df0), 1.0)
    return bal, drift


def show(label, path, note=""):
    t = path["t"]
    ix = [0, len(t) // 3, 2 * len(t) // 3, len(t) - 1]
    print(f"\n  {label}{('  -- ' + note) if note else ''}")
    print(f"    {'t':>6} {'r':>8} {'ip':>8} {'rE':>8} {'g':>8} {'u':>7} {'infl':>8} "
          f"{'lev':>7} {'lam':>7}")
    for k in ix:
        print(f"    {t[k]:6.1f} {path['r'][k]:8.4f} {path['ipol'][k]:8.4f} "
              f"{path['rE'][k]:8.4f} {path['gacc'][k]:8.4f} {path['u'][k]:7.3f} "
              f"{path['infl'][k]:8.4f} {path['dlev'][k]:7.3f} {path['lam'][k]:7.3f}")
    bal, drift = audit(path)
    grow = path["K"][-1] / path["K"][0]
    minrE = min(path["rE"])
    print(f"    K x{grow:.3f} over the run; lowest rE {minrE:+.4f}; "
          f"{'ENTERPRISE PROFIT WENT NEGATIVE' if minrE <= 0 else 'rE stayed positive'}")
    print(f"    accounting: balance sheet {bal:.1e}, DF drift {drift:.1e} "
          f"({path['steps']} steps)")
    return dict(K=grow, minrE=minrE, rE=path["rE"][-1], g=path["gacc"][-1],
                ip=path["ipol"][-1], r=path["r"][-1], bal=bal, drift=drift)


def stability(save_name):
    """How long does the balanced path last, as the accelerator is turned up?

    The path is a REST POINT -- every derivative sits on its balanced-growth value to
    1e-7 -- but it is not a stable one. The initial conditions are snapped to multiples
    of 1/1024 so the opening balance sheet cancels exactly, and that 5e-4 nudge is enough
    to start the departure. It is not a numerical artefact: the departure time scales as
    1/kappa, which is what an unstable eigenvalue proportional to kappa looks like.

    The loop is the accelerator running through the wage-price spiral. Setting either
    etap (price adjustment) or kappa (investment response) to zero removes the
    instability outright; damping wage indexation only delays it.
    """
    from runner import Run
    R = Run(f"~/minsky-models/{save_name}.mky")
    print("\n" + "=" * 79)
    print("HOW LONG DOES THE BALANCED PATH LAST?")
    print("=" * 79)
    print("  Leverage is 10% away from where it started at t = ...")
    print(f"  {'kappa':>7} {'gam=0.6':>10} {'gam=0.3':>10}")
    for kappa in (0.40, 0.30, 0.20, 0.10, 0.05):
        row = []
        for gam in (0.60, 0.30):
            row.append(_departs(R, {"kappa": kappa, "gam": gam}))
        print(f"  {kappa:7.2f} {row[0]:>10} {row[1]:>10}", flush=True)
    print("\n  and with each loop cut in turn (kappa 0.20, gam 0.60):")
    for label, over in (("nothing cut", {}),
                        ("no price adjustment  etap=0", {"etap": 0.0}),
                        ("no investment response kappa=0", {"kappa": 0.0}),
                        ("no wage indexation   gam=0", {"gam": 0.0})):
        print(f"    {label:34s} {_departs(R, over):>10}")


def _departs(R, over, tmax=200.0):
    try:
        p = R.go(tmax, ["dlev"], over, samples=400, max_steps=120_000)
    except SystemExit:
        return "stalled"
    d0 = p["dlev"][0]
    for tt, d in zip(p["t"], p["dlev"]):
        if abs(d - d0) / d0 > 0.10:
            return f"t={tt:.0f}"
    return "never"


def report(tmax, save_name):
    from runner import Run
    R = Run(f"~/minsky-models/{save_name}.mky")
    out = {}

    print("\n" + "=" * 79)
    print("1. DOES THE BASELINE SIT STILL?  (it was solved to, so anything moving is a bug)")
    print("=" * 79)
    base = R.go(tmax, WATCH)
    out["baseline"] = show("Shaikh rule, no shock", base)
    moved = max(abs(base[k][-1] - base[k][0]) for k in ("r", "rE", "gacc", "u", "dlev"))
    print(f"    every rate moved by at most {moved:.1e} over {tmax:g} periods")

    print("\n" + "=" * 79)
    print("2. A DISTRIBUTIVE SHOCK: money wages jump 2%")
    print("=" * 79)
    print("  It cuts the profit rate and raises inflation at the same time, so the two")
    print("  rules pull in opposite directions. Shaikh follows r DOWN to protect the")
    print("  enterprise margin. Taylor sees the inflation and tightens INTO a falling")
    print("  profit rate. Watch the gap between ip and r.")
    w0 = 1.0 / P["mu"]
    for label, rule in (("Shaikh  ip = r - m", 1.0), ("Taylor  ip = f(infl, u)", 0.0)):
        out[f"wage shock / {label}"] = show(label, R.go(
            tmax, WATCH, {"rule": rule, "wage": w0 * 1.02}))

    print("\n" + "=" * 79)
    print("3. THE CLAIM ITSELF: squeeze the margin between the policy rate and r")
    print("=" * 79)
    print("  Under the Shaikh rule the central bank holds ip exactly m below the")
    print("  aggregate pre-interest profit rate. Take m to zero and policy sets ip = r:")
    print("  every penny of profit goes to the creditor and none is left to enterprise.")
    print("  Nothing here is assumed -- accumulation is driven by rE, and rE is whatever")
    print("  r minus the interest bill turns out to be.")
    print(f"    {'margin m':>9} {'ip':>8} {'r':>8} {'rE':>9} {'g':>9} "
          f"{'K by t=12':>9}")
    # read at t=12, well inside the window where the balanced path is still flat: a
    # WIDE margin leaves more profit to enterprise, which drives accumulation harder and
    # trips the accelerator, so a long run here would be measuring the instability
    # rather than the mechanism
    for msh in (0.04, 0.03, 0.02, 0.01, 0.005, 0.0, -0.01):
        p = R.go(12.0, WATCH, {"rule": 1.0, "msh": msh})
        k = -1
        tag = ("nothing left to enterprise" if p["rE"][k] <= 0 else
               "thin" if p["rE"][k] < 0.005 else "")
        print(f"    {msh:9.3f} {p['ipol'][k]:8.4f} {p['r'][k]:8.4f} "
              f"{p['rE'][k]:9.4f} {p['gacc'][k]:9.4f} "
              f"{p['K'][k]/p['K'][0]:9.3f}  {tag}")

    print("\n" + "=" * 79)
    print("SUMMARY")
    print("=" * 79)
    print(f"  {'experiment':34s} {'K growth':>9} {'final g':>9} {'final rE':>9} "
          f"{'lowest rE':>10} {'final ip':>9}")
    for k, v in out.items():
        print(f"  {k:34s} {v['K']:9.3f} {v['g']:9.4f} {v['rE']:9.4f} "
              f"{v['minrE']:10.4f} {v['ip']:9.4f}")
    worst = max(v["bal"] for v in out.values()), max(v["drift"] for v in out.values())
    print(f"\n  across every run: balance sheet off by at most {worst[0]:.1e}, "
          f"DF drift at most {worst[1]:.1e}")
    print("  (both are consequences of the accounting, imposed nowhere)")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="simulate and compare the rules")
    ap.add_argument("--tmax", type=float, default=50.0)
    ap.add_argument("--stability", action="store_true",
                    help="how long the balanced path survives, against kappa and gam")
    ap.add_argument("--save", default="ShaikhMonetaryPolicy")
    args = ap.parse_args()

    p = dict(P)
    s = steady_state(p, CAL)
    p["payB"] = s["payB"]

    print("baseline, solved so the model starts on a balanced growth path")
    for k in ("r", "rE", "spread", "ipol", "iL", "iD", "dlev", "u", "omega", "gacc",
              "lam", "payB"):
        print(f"  {k:8s} {s[k]:10.5f}")
    print(f"  {'rB':8s} {s['PB']/s['EB']:10.5f}   (equalised on to r)")
    print(f"  interest takes {s['IntL']/s['Profit']*100:.1f}% of pre-interest profit")
    print(f"  opening balance sheet residual {s['Res']+s['Loans']-s['DF']-s['DH']-s['EB']:.1e}")

    build(s, p)
    st = api("/api/state", method="GET")
    print(f"\nbuilt {len(st['items'])} items and {len(st['wires'])} wires "
          f"across 3 Godley tables")
    api("/api/save", {"name": args.save})
    print(f"saved as {args.save}.mky")

    if args.run:
        report(args.tmax, args.save)
    if args.stability:
        stability(args.save)


if __name__ == "__main__":
    main()
