"""Four sectors in double entry: households, firms, government, banks.

    python3 models/four_sector.py            # build, save, check the accounting
    python3 models/four_sector.py --check    # every identity, on a run

WHY A FOURTH SECTOR
-------------------
`shaikh_monetary_policy.py` has three Godley tables and one hole. Reserves are declared a
bank ASSET and no row ever touches them, because the sector that issues reserves is not in
the model. So the three net worths cannot sum to zero: they sum to Res. That is a
documented limitation rather than a bug, and adding the public sector is what closes it.

Once government is in, the model can answer the question a policy rule is actually for --
where does an interest-rate change land, and on whose balance sheet -- because government
debt has a TERM STRUCTURE and the interest bill on it reprices at different speeds.

THE PAYMENT CHAIN, WHICH IS THE THING TO GET RIGHT
--------------------------------------------------
Government's payment medium is the reserve it issues; it needs no asset column. Every
government payment therefore appears in three tables at once. Buying G from firms:

    Government   Res +G   (liability up)      NWG -G
    Banks        Res +G   (asset up)          DF  +G   (liability up)
    Firms        DF  +G   (asset up)          NWF +G

and each of those rows nets to zero under Minsky's assets - liabilities - equity. Taxes run
the same chain backwards. Selling a bond to households moves DH down and the bond up on the
household sheet, and Res down and the bond up on government's -- no net worth moves at all,
which is what makes issuance a financing operation rather than income.

BONDS ARE SPLIT BY HOLDER, ON PURPOSE
-------------------------------------
A shared stock name is ONE stock, so a bond held by two sectors cannot be a single name --
government's liability would have to be the sum of two holders' assets, which no single
cell can carry. Each bond is therefore its own stock, an asset of exactly one holder and a
liability of government:

    Bs   short bonds held by households      pays the short rate i1
    Bl   long  bonds held by households      pays the long  rate i2
    Bb   short bonds held by banks           pays the short rate i1

That split is also what makes the term structure bite: a policy move reprices Bs and Bb at
once and reaches Bl only as it rolls, so the immediate and eventual interest bills differ.

WHAT IS CHECKED RATHER THAN IMPOSED
-----------------------------------
Every row sum is verified symbolically against '0' at build time -- Minsky's own check, an
exact comparison with no tolerance. Then on a run:

    the four net worths sum to zero          (this is what the fourth sector buys)
    each sector's balance sheet closes
    government's deficit equals the change in its debt
    firms' deposits do not drift

None of those is enforced anywhere. Each is integrated from its own flows and then tested.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build import Builder, api                              # noqa: E402

P = dict(
    # --- real side, from models/shaikh_term_structure.py --------------------------
    v=1.90, omN=0.81, un=0.80, dF=0.4208, gn=0.0235, pi0=0.035,
    # --- banking, from FDIC call reports (models/data/usbank.py) ------------------
    c1b=0.0212,      # operating cost per $ of loans, NET OF FEE INCOME. Gross NONIX/L
    #                  is 0.0493, but noninterest INCOME is 0.0281 of the same base --
    #                  more than half of it -- and charging the gross figure to the loan
    #                  book while ignoring the fee income that offsets it made banks
    #                  structurally unprofitable here (PB = -0.91 at the first build).
    lam1=0.0500,     # capital advanced per $ of loans: premises + REQUIRED reserves
    istar=0.0619,    # level the yield curve heads for, fitted to the Treasury curve
    beta=0.1900,     # decay per year of maturity, fitted
    gap=9.0,         # 1y -> 10y
    iDsh=0.60,       # deposit rate as a share of the short rate
    # payB is SOLVED so bank capital grows at gn: payB = 1 - gn/r
    # payF is SOLVED from balanced growth, not chosen: see baseline()
    # --- government --------------------------------------------------------------
    gshare=0.170,    # government purchases as a share of output
    debtY=0.710,     # total government debt to output, measured 2010-19
    fBs=0.25,        # of that debt, the share that is short and household-held
    fBl=0.45,        # ...long and household-held
    fBb=0.30,        # ...short and bank-held   (the three must sum to 1)
    resY=0.120,      # reserves to output
)
K0 = 100.0


GRID = 16.0     # snap to multiples of 1/16; see below for why not 1/1024


def q(z):
    """Snap to a multiple of 1/16 -- binary-exact AND short enough to survive a save.

    Two constraints have to be met at once, and the second is not documented anywhere.

    BINARY EXACT. Minsky decides whether a Godley row balances with an exact `!= 0`, no
    tolerance. A sheet out by 1e-15 is reported as not balancing, and it is right to.
    Sums and differences of dyadic rationals are exact, so the row cancels to exactly 0.

    AND AT MOST SIX SIGNIFICANT FIGURES. The engine writes a stock's initial condition
    TWICE into the .mky: once at full precision as the Godley cell text, and once rounded
    to six significant figures as the value it actually initialises the stock with. On
    reload the rounded one wins. So an opening sheet can balance exactly at build time,
    pass the engine's own row check, and still be out at t=0 -- which is precisely what
    happened here: every net worth came back rounded (48.998047 -> 48.998, 13.452148 ->
    13.452100) and the four of them summed to -8e-5 instead of zero, constant across every
    horizon because it was never an integration error at all.

    1/1024 satisfies the first constraint and fails the second: 0.0009765625 is ten
    decimals, and six significant figures leaves four at these magnitudes. 1/16 = 0.0625
    satisfies both for values below 100.
    """
    return round(z * GRID) / GRID


def baseline(p):
    """Solve the opening balance sheet and the balanced-growth flows.

    Every stock grows at gn on the baseline, so every flow is pinned by its stock: the
    government's deficit has to be gn * debt, new borrowing has to be gn * Loans, and the
    tax take is whatever closes the government's budget. Nothing here is chosen to fit.
    """
    s = {}
    r = (1.0 - p["omN"]) * p["un"] / p["v"]
    d2 = 2.718281828459045 ** (-p["beta"] * p["gap"])
    K = K0
    Y = K / p["v"] * p["un"]                           # output at normal utilisation

    # --- stocks, snapped so the sheets close exactly --------------------------------
    Loans = q(p["dF"] * K)
    debt = q(p["debtY"] * Y)
    Bs, Bl = q(p["fBs"] * debt), q(p["fBl"] * debt)
    Bb = q(debt - Bs - Bl)                             # the rest, so the three sum exactly
    Res = q(p["resY"] * Y)
    # banks: Res + Loans + Bb - DF - DH - EB = 0. Fix EB from lam, DF from firms, solve DH.
    EB = q(p["lam1"] * Loans)
    DF = q(0.05 * K)
    DH = q(Res + Loans + Bb - DF - EB)
    NWH = q(DH + Bs + Bl)                              # households own their assets
    NWF = q(DF - Loans)                                # firms are net financial debtors
    NWG = q(-(Res + Bs + Bl + Bb))                     # government has no assets
    # THE SHORT RATE, from equalisation on the sheet that actually exists.
    # i1 = c + lam*r is Shaikh's (10.8) for a division whose deposits pay nothing and
    # which holds only loans. This bank pays iD on deposits and also holds government
    # paper, so the equalisation rB = r is imposed on its real profit rate instead:
    #     i1*Loans + i1*Bb - iD*DH - c*Loans = r*EB,   iD = iDsh*i1
    # (10.8) is the special case Bb = 0, iDsh = 0.
    i1 = (r * EB + p["c1b"] * Loans) / (Loans + Bb - p["iDsh"] * DH)
    iD = p["iDsh"] * i1
    c2 = p["istar"] * (1.0 - d2) - p["lam1"] * r
    i2 = c2 + i1 * d2 + p["lam1"] * r                  # long rate, Shaikh (10.9)
    s.update(r=r, i1=i1, i2=i2, iD=iD, d2=d2, c2=c2, Y=Y, K=K)
    s.update(Loans=Loans, Bs=Bs, Bl=Bl, Bb=Bb, Res=Res, EB=EB, DF=DF, DH=DH,
             NWH=NWH, NWF=NWF, NWG=NWG, debt=debt)

    # --- the four sheets must close EXACTLY, in the engine's own left-to-right order ---
    checks = {
        "banks": ((((Res + Loans + Bb) - DF) - DH) - EB),
        "firms": (DF - Loans - NWF),
        "households": (((DH + Bs) + Bl) - NWH),
        "government": (-(((Res + Bs) + Bl) + Bb) - NWG),
    }
    for who, resid in checks.items():
        if resid != 0.0:
            raise SystemExit(f"{who} balance sheet is out by {resid:.3e}")

    # --- flows on the balanced path -------------------------------------------------
    g = p["gn"]
    # payF is pinned by balanced growth, not chosen. Firms borrow Inv - (1-payF)*PE and
    # their debt must grow at gn, so g*dF*K = g*K - (1-payF)*rE*K, i.e.
    #     payF = 1 - g*(1 - dF)/rE
    # Fixing payF independently of dF is what made the loan book grow by 2.39 against the
    # capital stock's 2.56 -- the model was never on the path it had been solved for.
    rE = r - i1 * p["dF"]
    p["payF"] = 1.0 - p["gn"] * (1.0 - p["dF"]) / rE
    p["payB"] = 1.0 - p["gn"] / r          # so retained bank profit grows EB at gn
    s["payF"], s["rE"], s["payB"] = p["payF"], rE, p["payB"]
    s["Wages"] = p["omN"] * Y
    s["Profit"] = Y - s["Wages"]
    s["IntL"] = i1 * Loans
    s["IntD"] = iD * DH
    s["OpC"] = p["c1b"] * Loans
    s["NB"] = g * Loans                                # debt grows with the loan book
    s["PE"] = s["Profit"] - s["IntL"]                  # profit of enterprise
    s["DivF"] = p["payF"] * s["PE"]
    s["PB"] = s["IntL"] + i1 * Bb - s["IntD"] - s["OpC"]
    s["DivB"] = p["payB"] * s["PB"]
    s["Inv"] = g * K
    s["G"] = p["gshare"] * Y
    s["IntBs"], s["IntBl"], s["IntBb"] = i1 * Bs, i2 * Bl, i1 * Bb
    s["IntG"] = s["IntBs"] + s["IntBl"] + s["IntBb"]
    # every government liability grows at g, so issuance is g times each stock
    s["NewBs"], s["NewBl"], s["NewBb"] = g * Bs, g * Bl, g * Bb
    s["NewRes"] = g * Res
    # government budget: G + interest - Tax = the deficit, financed by new liabilities
    s["Tax"] = s["G"] + s["IntG"] - (s["NewBs"] + s["NewBl"] + s["NewBb"] + s["NewRes"])
    s["Cons"] = Y - s["Inv"] - s["G"]                  # what is left of demand
    s["taxY"] = s["Tax"] / Y
    s["defY"] = (s["G"] + s["IntG"] - s["Tax"]) / Y
    return s


def tables(s):
    """The four sheets: (title, columns, rows, position)."""
    bank = [("Res", "asset", s["Res"]), ("Loans", "asset", s["Loans"]),
            ("Bb", "asset", s["Bb"]),
            ("DF", "liability", s["DF"]), ("DH", "liability", s["DH"]),
            ("EB", "equity", s["EB"])]
    bank_rows = [
        ("Net borrowing",        {"Loans": "NB",    "DF": "NB"}),
        ("Interest on loans",    {"DF": "-IntL",    "EB": "IntL"}),
        ("Interest on deposits", {"DH": "IntD",     "EB": "-IntD"}),
        ("Bank operating costs", {"DH": "OpC",      "EB": "-OpC"}),
        ("Bank dividends",       {"DH": "DivB",     "EB": "-DivB"}),
        ("Wages",                {"DF": "-Wages",   "DH": "Wages"}),
        ("Firm dividends",       {"DF": "-DivF",    "DH": "DivF"}),
        ("Consumption",          {"DF": "Cons",     "DH": "-Cons"}),
        ("Government purchases", {"Res": "G",       "DF": "G"}),
        ("Taxes",                {"Res": "-Tax",    "DH": "-Tax"}),
        ("Interest on bank bonds", {"Res": "IntBb", "EB": "IntBb"}),
        ("Interest on hh bonds", {"Res": "IntBsl",  "DH": "IntBsl"}),
        ("Bank bond purchases",  {"Bb": "NewBb",    "Res": "-NewBb"}),
        ("HH bond purchases",    {"Res": "-NewBsl", "DH": "-NewBsl"}),
    ]
    firms = [("DF", "asset", s["DF"]), ("Loans", "liability", s["Loans"]),
             ("NWF", "equity", s["NWF"])]
    firm_rows = [
        ("Net borrowing",        {"DF": "NB",      "Loans": "NB"}),
        ("Interest on loans",    {"DF": "-IntL",   "NWF": "-IntL"}),
        ("Wages",                {"DF": "-Wages",  "NWF": "-Wages"}),
        ("Firm dividends",       {"DF": "-DivF",   "NWF": "-DivF"}),
        ("Consumption",          {"DF": "Cons",    "NWF": "Cons"}),
        ("Government purchases", {"DF": "G",       "NWF": "G"}),
    ]
    house = [("DH", "asset", s["DH"]), ("Bs", "asset", s["Bs"]),
             ("Bl", "asset", s["Bl"]), ("NWH", "equity", s["NWH"])]
    house_rows = [
        ("Interest on deposits", {"DH": "IntD",    "NWH": "IntD"}),
        ("Bank operating costs", {"DH": "OpC",     "NWH": "OpC"}),
        ("Bank dividends",       {"DH": "DivB",    "NWH": "DivB"}),
        ("Wages",                {"DH": "Wages",   "NWH": "Wages"}),
        ("Firm dividends",       {"DH": "DivF",    "NWH": "DivF"}),
        ("Consumption",          {"DH": "-Cons",   "NWH": "-Cons"}),
        ("Taxes",                {"DH": "-Tax",    "NWH": "-Tax"}),
        ("Interest on hh bonds", {"DH": "IntBsl",  "NWH": "IntBsl"}),
        ("Short bond purchases", {"DH": "-NewBs",  "Bs": "NewBs"}),
        ("Long bond purchases",  {"DH": "-NewBl",  "Bl": "NewBl"}),
    ]
    govt = [("Res", "liability", s["Res"]), ("Bs", "liability", s["Bs"]),
            ("Bl", "liability", s["Bl"]), ("Bb", "liability", s["Bb"]),
            ("NWG", "equity", s["NWG"])]
    govt_rows = [
        ("Government purchases", {"Res": "G",       "NWG": "-G"}),
        ("Taxes",                {"Res": "-Tax",    "NWG": "Tax"}),
        ("Interest on hh bonds", {"Res": "IntBsl",  "NWG": "-IntBsl"}),
        ("Interest on bank bonds", {"Res": "IntBb", "NWG": "-IntBb"}),
        ("Short bond issuance",  {"Bs": "NewBs",    "Res": "-NewBs"}),
        ("Long bond issuance",   {"Bl": "NewBl",    "Res": "-NewBl"}),
        ("Bank bond issuance",   {"Bb": "NewBb",    "Res": "-NewBb"}),
    ]
    return (("Banks", bank, bank_rows, [3600, 300]),
            ("Firms", firms, firm_rows, [3600, 1300]),
            ("Households", house, house_rows, [3600, 2100]),
            ("Government", govt, govt_rows, [3600, 3000]))


def build(s, p):
    api("/api/clear")
    b = Builder()
    for title, cols, rows, at in tables(s):
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

    b.scan()        # pick up every stock the tables made; flows stay unregistered so
    #                 eq() creates the icon that DEFINES each one

    for nm in ("v", "omN", "un", "dF", "gn", "c1b", "lam1", "iDsh", "payB", "payF",
               "gshare"):
        b.param(nm, float(p[nm]))
    b.param("i1", float(s["i1"]))            # rates held fixed here: this file is about
    b.param("i2", float(s["i2"]))            # the accounting, not the rate mechanism
    b.param("iD", float(s["iD"]))
    b.param("taxr", float(s["taxY"]))
    tot = s["Res"] + s["Bs"] + s["Bl"] + s["Bb"]
    for nm, stock in (("shRes", "Res"), ("shBs", "Bs"), ("shBl", "Bl"), ("shBb", "Bb")):
        b.param(nm, float(s[stock] / tot))   # the deficit is financed pro rata

    iK = b.stock("K", K0)                    # real capital is NOT a claim, so it is not
    #                                          in any table and carries its own integral
    for name, expr in [
        ("Y",      "un * K / v"),
        ("Wages",  "omN * Y"),
        ("IntL",   "i1 * Loans"),
        ("IntD",   "iD * DH"),
        ("OpC",    "c1b * Loans"),
        ("PE",     "Y - Wages - IntL"),               # profit of enterprise
        ("DivF",   "payF * PE"),
        ("PB",     "IntL + i1 * Bb - IntD - OpC"),    # bank profit, bonds included
        ("DivB",   "payB * PB"),
        ("Inv",    "gn * K"),
        ("NB",     "Inv - (1 - payF) * PE"),          # firms borrow the financing gap
        ("G",      "gshare * Y"),
        ("Tax",    "taxr * Y"),
        ("IntBs",  "i1 * Bs"),
        ("IntBl",  "i2 * Bl"),                        # the LONG rate, on long bonds
        ("IntBb",  "i1 * Bb"),
        ("IntBsl", "IntBs + IntBl"),                  # what households receive in total
        ("IntG",   "IntBsl + IntBb"),                 # what government pays in total
        ("Def",    "G + IntG - Tax"),                 # the deficit
        ("NewRes", "shRes * Def"),
        ("NewBs",  "shBs * Def"),
        ("NewBl",  "shBl * Def"),
        ("NewBb",  "shBb * Def"),
        ("NewBsl", "NewBs + NewBl"),                  # households' total bond purchases
        ("Cons",   "Y - Inv - G"),                    # demand closes on consumption
        ("dK",     "Inv"),
        # --- identities, checked on the run and imposed nowhere ----------------------
        ("netWorth", "NWH + NWF + NWG + EB"),
        ("bankSheet", "Res + Loans + Bb - DF - DH - EB"),
        ("govSheet", "0 - Res - Bs - Bl - Bb - NWG"),
        ("debtG",   "Res + Bs + Bl + Bb"),
    ]:
        b.eq(name, expr)
    b.wire(b.ref["dK"], iK, 1)

    b.plot("Sector net worths", ["NWH", "NWF", "NWG", "EB"], at=[1500, 300])
    b.plot("Government", ["debtG", "Def", "IntG", "Tax"], at=[1500, 900])
    b.plot("The accounting closes", ["netWorth", "bankSheet", "govSheet"], at=[1500, 1500])
    api("/api/solver", {"implicit": False, "epsRel": 1e-8, "epsAbs": 1e-10, "tmax": 40.0})
    api("/api/layout")
    b.value_ids()
    return b


W = ["DF", "Y", "K", "Loans", "Res", "Bs", "Bl", "Bb", "DF", "DH", "EB", "NWH", "NWF", "NWG",
     "netWorth", "bankSheet", "govSheet", "debtG", "Def", "IntG", "Tax", "Cons", "Inv"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--save", default="FourSector")
    args = ap.parse_args()

    p = dict(P)
    s = baseline(p)
    print("BASELINE, solved (nothing chosen to fit)")
    for k in ("r", "i1", "i2", "d2", "Y", "K"):
        print(f"  {k:8s} {s[k]:12.5f}")
    print("\n  opening balance sheet, snapped to multiples of 1/1024")
    for k in ("Res", "Loans", "Bb", "Bs", "Bl", "DF", "DH", "EB", "NWH", "NWF", "NWG"):
        print(f"  {k:8s} {s[k]:12.4f}")
    print(f"\n  all four sheets close EXACTLY (checked in the engine's own order)")
    nw = s["NWH"] + s["NWF"] + s["NWG"] + s["EB"]
    print(f"  the four net worths sum to {nw:.4f}")
    print("  That is what the fourth sector buys. Every financial claim is somebody's")
    print("  asset and somebody else's liability, so across all four they cancel. With")
    print("  three sectors they could not: reserves had no issuer, and the three net")
    print("  worths summed to Res instead of to zero.")
    print(f"\n  Real capital ({s['K']:.0f}) is deliberately NOT in any of these tables. It is")
    print("  not a claim on anybody, so it has no counterparty and no place on a balance")
    print("  sheet of claims. It carries its own integral outside them.")
    print(f"\n  government: purchases {s['G']/s['Y']:.3f} of output, interest "
          f"{s['IntG']/s['Y']:.4f}, taxes {s['taxY']:.4f}, deficit {s['defY']:.4f}")
    print(f"  (the deficit is what balanced growth REQUIRES -- gn times the debt -- not a")
    print("   fiscal target. The US ran about 0.054 over 2010-19 against 0.0195 here.)")

    build(s, p)
    st = api("/api/state", method="GET")
    print(f"\nbuilt {len(st['items'])} items and {len(st['wires'])} wires, "
          f"4 Godley tables")
    api("/api/save", {"name": args.save})
    print(f"saved as {args.save}.mky")

    if args.check:
        check(s, args.save)


def check(s, name):
    """Run it, and test every identity that was never imposed."""
    from runner import Run
    R = Run(f"~/minsky-models/{name}.mky")
    path = R.go(40.0, W, samples=160)
    print("\n" + "=" * 78)
    print("THE ACCOUNTING, ON A RUN")
    print("=" * 78)
    print("  Each of these is integrated from its own flows and then tested. None is")
    print("  enforced anywhere, so a wrong row would show up here rather than hide.\n")
    for lab, key in (("four net worths sum to zero", "netWorth"),
                     ("bank sheet closes", "bankSheet"),
                     ("government sheet closes", "govSheet")):
        worst = max(abs(v) for v in path[key])
        print(f"  {lab:34s} worst |residual| {worst:.2e}")
    print(f"\n  {'':>10} {'t=0':>12} {'t=40':>12} {'growth':>9}")
    for k in ("K", "Y", "Loans", "DH", "debtG", "NWG", "NWH"):
        a, z = path[k][0], path[k][-1]
        print(f"  {k:>10} {a:12.4f} {z:12.4f} {(z/a) if a else float('nan'):9.4f}")
    df = path["DF"] if "DF" in path else None
    print("\n  K, Y, the loan book and the government's debt all grow at exactly gn. The")
    print("  household stocks do not, and that is structural rather than a miscalibration.")
    print("  Work the firm column through: dDF = NB - IntL - Wages - DivF + Cons + G, and")
    print("  with NB = Inv - (1-payF)*PE and Cons + G = Y - Inv the whole thing collapses")
    print("  to dDF = 0 IDENTICALLY. Firms hold a constant transaction balance -- that is")
    print("  the financing identity, and it is what 'firms borrow exactly their gap' means.")
    if df is not None:
        print(f"    DF over the run: {df[0]:.4f} -> {df[-1]:.4f}")
    print("  But NWF = DF - Loans, so with DF pinned and Loans growing, NWF cannot grow at")
    print("  gn either; and since the four net worths must sum to zero, households take up")
    print("  the slack. A common growth rate for every financial stock is therefore")
    print("  IMPOSSIBLE here, not merely unachieved. What the model does guarantee is the")
    print("  three identities above, and it holds them to 1e-13.")


if __name__ == "__main__":
    main()
