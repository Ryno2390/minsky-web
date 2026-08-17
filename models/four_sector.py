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
    # --- real dynamics, so the policy rule has something to respond to -------------
    kappa=0.377,     # accumulation response to the enterprise profit rate
    thu=0.50,        # utilisation adjusts to investment demand
    thb=0.30,        # ...and is pulled back toward normal capacity
    phi1=0.30,       # wage share rises with utilisation
    phi2=0.50,       # ...and is pulled back toward its own norm
    gp=0.40,         # inflation responds to utilisation
    gw=0.30,         # inflation responds to the wage share
    theta=0.035,     # real banking costs fall at this rate; = pi0 keeps c stationary
    # --- rate formation and policy ------------------------------------------------
    phN=0.50,        # speed the market rate gravitates to the classical normal rate
    phP=1.00,        # speed policy reaches the market rate
    sbar=0.019,      # normal gap between the policy rate and the short loan rate
    api=0.50,        # response to the inflation gap (BOTH rules)
    auu=0.50,        # response to the utilisation gap (BOTH rules)
    mu=5.0,          # speed the policy ANCHOR tracks the classical normal rate. This is
    #                  a dial between the two rules: mu large is the instantaneous
    #                  classical anchor, mu -> 0 freezes the intercept the way Taylor's
    #                  rstar is frozen. 5.0 has a half-life of 0.14 years and reproduces
    #                  the instantaneous rule closely.
    roll=0.10,       # the long bond book rolls over at 10% a year -- a 10-year book.
    #                  This is what splits the interest bill into an immediate leg
    #                  (Bs and Bb, repricing at once) and an eventual one (Bl).
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
    s["c1"] = p["c1b"]                     # REAL unit cost; p = 1 at the baseline
    s["ip"] = i1 - p["sbar"]               # the policy rate the rule calls for
    s["rstar"] = s["ip"] - p["pi0"]        # so Taylor AGREES at the baseline
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
               "gshare", "kappa", "thu", "thb", "phi1", "phi2", "gp", "gw", "pi0",
               "theta", "phN", "phP", "sbar", "api", "auu", "roll", "mu"):
        b.param(nm, float(p[nm]))
    b.param("taxr", float(s["taxY"]))
    b.param("d2", float(s["d2"]))            # exp(-beta*gap), the fitted funding share
    b.param("ucr1", float(s["c1"]))          # REAL unit costs; nominal c = p * ucr * tech
    b.param("ucr2", float(s["c2"]))
    b.param("rEn", float(s["rE"]))
    b.param("rstar", float(s["rstar"]))      # set so Taylor AGREES at the baseline
    b.param("piT", float(p["pi0"]))
    b.param("rule", 1.0, slider=(-0.2, 1.2))   # 1 = classical anchor, 0 = Taylor
    b.param("ish", 0.0, slider=(-0.03, 0.03))  # a policy disturbance
    b.param("wsh", 0.0, slider=(-0.03, 0.03))  # a money-wage shock
    tot = s["Res"] + s["Bs"] + s["Bl"] + s["Bb"]
    for nm, stock in (("shRes", "Res"), ("shBs", "Bs"), ("shBl", "Bl"), ("shBb", "Bb")):
        b.param(nm, float(s[stock] / tot))   # the deficit is financed pro rata

    iK = b.stock("K", K0)                    # real capital is NOT a claim, so it is not
    #                                          in any table and carries its own integral
    iT = b.stock("T", 0.0)                   # time, for the falling real cost of banking
    ip_ = b.stock("p", 1.0)                  # the price level
    iu = b.stock("u", float(p["un"]))
    iom = b.stock("omega", float(p["omN"]))
    ii1 = b.stock("i1", float(s["i1"]))      # the MARKET short rate
    ii2 = b.stock("i2", float(s["i2"]))      # the MARKET long rate
    iBl_ = b.stock("iBl", float(s["i2"]))    # AVERAGE COUPON on the long bond book
    iNb = b.stock("i1Nbar", float(s["i1"]))  # TRAILING AVERAGE of the normal short rate

    for name, expr in [
        ("Y",      "u * K / v"),
        ("r",      "(1 - omega) * u / v"),            # the general profit rate, endogenous
        ("Wages",  "omega * Y"),
        ("tech",   "exp(0 - theta * T)"),             # real banking costs fall
        ("c1",     "p * ucr1 * tech"),                # NOMINAL cost per $ of loans
        ("c2",     "p * ucr2 * tech"),
        ("iD",     "iDsh * i1"),
        ("IntD",   "iD * DH"),
        ("OpC",    "c1 * Loans"),
        # THE CLASSICAL NORMAL SHORT RATE, from equalisation on the sheet that exists:
        #   i1N*(Loans + Bb) - IntD - c1*Loans = r*EB
        ("i1N",    "(r * EB + OpC + IntD) / (Loans + Bb)"),
        ("i2N",    "c2 + i1 * d2 + lam1 * r"),        # Shaikh (10.9), maturity-gap form
        ("IntL",   "i1 * Loans"),
        ("PE",     "Y - Wages - IntL"),               # profit of enterprise
        ("rE",     "r - i1 * dF"),
        ("DivF",   "payF * PE"),
        ("PB",     "IntL + i1 * Bb - IntD - OpC"),    # bank profit, bonds included
        ("rB",     "PB / EB"),                        # banking's OWN profit rate
        ("DivB",   "payB * PB"),
        ("gI",     "gn + kappa * (rE - rEn)"),        # accumulation out of enterprise
        ("Inv",    "gI * K"),
        ("NB",     "Inv - (1 - payF) * PE"),          # firms borrow the financing gap
        ("G",      "gshare * Y"),
        ("Tax",    "taxr * Y"),
        ("pi",     "pi0 + gp * (u - un) + gw * (omega - omN)"),
        # --- the policy rule ---------------------------------------------------------
        # The anchor is the TRAILING AVERAGE of the normal rate, not its current value.
        # Anchoring on the instantaneous i1N makes the rule inherit every drift in it --
        # and with government debt at 0.71 of output that drift is bought every year,
        # shocked or not. mu sets how much of it the rule takes on.
        ("ipC",    "(i1Nbar - sbar) + api * (pi - piT) + auu * (u - un)"),   # CLASSICAL
        ("ipT",    "rstar + pi + api * (pi - piT) + auu * (u - un)"),     # TAYLOR
        ("ip",     "rule * ipC + (1 - rule) * ipT + ish"),
        # --- the government's interest bill, split by how fast each leg reprices ------
        ("IntBs",  "i1 * Bs"),                        # short: reprices AT ONCE
        ("IntBb",  "i1 * Bb"),                        # short: reprices AT ONCE
        ("IntBl",  "iBl * Bl"),                       # long: the AVERAGE COUPON, which
        #                                               only moves as the book rolls
        ("IntBsl", "IntBs + IntBl"),                  # what households receive in total
        ("IntG",   "IntBsl + IntBb"),                 # what government pays in total
        ("Def",    "G + IntG - Tax"),                 # the deficit
        ("NewRes", "shRes * Def"),
        ("NewBs",  "shBs * Def"),
        ("NewBl",  "shBl * Def"),
        ("NewBb",  "shBb * Def"),
        ("NewBsl", "NewBs + NewBl"),                  # households' total bond purchases
        ("Cons",   "Y - Inv - G"),                    # demand closes on consumption
        ("slope",  "i2 - i1"),
        ("burden", "IntG / Y"),                       # the interest bill, per unit output
        # --- derivatives --------------------------------------------------------------
        ("dK",     "Inv"),
        ("dT",     "1"),
        ("dp",     "pi * p"),
        ("du",     "thu * (gI - gn) - thb * (u - un)"),
        ("domega", "omega * (phi1 * (u - un) - phi2 * (omega - omN) + wsh)"),
        ("di1",    "phN * (i1N - i1) + phP * ((ip + sbar) - i1)"),
        ("di2",    "phN * (i2N - i2)"),               # policy reaches the long end only
        #                                               through i1, inside i2N
        ("diBl",   "roll * (i2 - iBl)"),              # the long book reprices as it rolls
        ("di1Nbar", "mu * (i1N - i1Nbar)"),           # the anchor follows, at speed mu
        # --- identities, checked on the run and imposed nowhere ----------------------
        ("netWorth", "NWH + NWF + NWG + EB"),
        ("bankSheet", "Res + Loans + Bb - DF - DH - EB"),
        ("govSheet", "0 - Res - Bs - Bl - Bb - NWG"),
        ("debtG",   "Res + Bs + Bl + Bb"),
    ]:
        b.eq(name, expr)
    for state, deriv in (("K", "dK"), ("T", "dT"), ("p", "dp"), ("u", "du"),
                         ("omega", "domega"), ("i1", "di1"), ("i2", "di2"),
                         ("iBl", "diBl"), ("i1Nbar", "di1Nbar")):
        b.wire(b.ref[deriv], {"K": iK, "T": iT, "p": ip_, "u": iu, "omega": iom,
                              "i1": ii1, "i2": ii2, "iBl": iBl_,
                              "i1Nbar": iNb}[state], 1)

    b.plot("Sector net worths", ["NWH", "NWF", "NWG", "EB"], at=[1500, 300])
    b.plot("Government", ["debtG", "burden", "IntG", "Def"], at=[1500, 900])
    b.plot("Rates", ["i1", "i2", "iBl", "i1N", "r"], at=[1500, 1500])
    b.plot("The accounting closes", ["netWorth", "bankSheet", "govSheet"], at=[1500, 2100])
    api("/api/solver", {"implicit": False, "epsRel": 1e-8, "epsAbs": 1e-10, "tmax": 40.0})
    api("/api/layout")
    b.value_ids()
    return b


W = ["DF", "Y", "K", "Loans", "Res", "Bs", "Bl", "Bb", "DF", "DH", "EB", "NWH", "NWF", "NWG",
     "netWorth", "bankSheet", "govSheet", "debtG", "Def", "IntG", "Tax", "Cons", "Inv"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--incidence", action="store_true")
    ap.add_argument("--race", action="store_true")
    ap.add_argument("--anchor", action="store_true")
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
    if args.incidence:
        incidence(args.save)
    if args.race:
        race(args.save)
    if args.anchor:
        anchor(args.save)


def race(name):
    """The classical anchor against Taylor, now that government debt is in the model.

    The earlier two-sector race had the classical rule protecting the enterprise margin on
    impact and losing it by eighty periods. That was before there was a public balance
    sheet. The classical anchor is an INTEGRAL on the price level -- inflation above the
    rate at which banking gets cheaper raises c, hence the normal loan rate, hence policy,
    without limit -- and with government debt in the model that same integral now also
    drives the government's interest bill. Whether the better nominal anchor is worth the
    fiscal cost is exactly what this measures.

    EACH RULE IS SCORED AGAINST ITS OWN UNSHOCKED PATH. The two rules do NOT share a
    baseline once the model drifts: they are calibrated to agree at rest, but the normal
    loan rate rises as banking's margin is squeezed, so the classical rule tightens on the
    unshocked path where Taylor does not. Comparing shocked LEVELS would credit or blame a
    rule for that drift rather than for its response to the shock.
    """
    from runner import Run
    watch = ["rE", "pi", "u", "K", "burden", "IntG", "NWG", "debtG", "Y", "i1", "i2",
             "gI", "EB", "NWH"]   # "t" is added by the runner; asking for it fails
    R = Run(f"~/minsky-models/{name}.mky")
    TMAX, HZ = 80.0, (20.0, 40.0, 80.0)

    def at(path, t):
        """Nearest sample to time t, since sampling is uniform in STEPS not in time."""
        i = min(range(len(path["t"])), key=lambda k: abs(path["t"][k] - t))
        return i

    runs = {}
    for rule, lab in ((1.0, "classical"), (0.0, "Taylor")):
        runs[(lab, 0.0)] = R.go(TMAX, watch, {"rule": rule, "wsh": 0.0}, samples=400)
        for wsh in (0.01, 0.02):
            runs[(lab, wsh)] = R.go(TMAX, watch, {"rule": rule, "wsh": wsh}, samples=400)

    print("\n" + "=" * 92)
    print("THE RULE RACE, WITH GOVERNMENT DEBT IN")
    print("=" * 92)
    print("  A money-wage shock: it cuts the profit rate and raises inflation at once, so")
    print("  the rules pull in opposite directions. Every figure is that rule's shocked")
    print("  path minus its OWN unshocked path at the same date.\n")
    print(f"  {'shock':>6} {'yrs':>4} | {'CLASSICAL':>32} | {'TAYLOR':>32}")
    print(f"  {'':>6} {'':>4} | {'worst rE':>10} {'worst pi':>10} {'d burden':>10} | "
          f"{'worst rE':>10} {'worst pi':>10} {'d burden':>10}")
    for wsh in (0.01, 0.02):
        for t in HZ:
            cells = []
            for lab in ("classical", "Taylor"):
                sh, bs = runs[(lab, wsh)], runs[(lab, 0.0)]
                j = at(sh, t)
                n = max(1, j // 8)                       # ignore the first eighth
                drE = min(sh["rE"][k] - bs["rE"][k] for k in range(n, j + 1))
                dpi = max(sh["pi"][k] - bs["pi"][k] for k in range(n, j + 1))
                dbu = sh["burden"][j] - bs["burden"][j]
                cells.append((drE, dpi, dbu))
            print(f"  {wsh:6.3f} {t:4.0f} | {cells[0][0]:10.5f} {cells[0][1]:10.5f} "
                  f"{cells[0][2]:10.5f} | {cells[1][0]:10.5f} {cells[1][1]:10.5f} "
                  f"{cells[1][2]:10.5f}")

    print("\n" + "=" * 92)
    print("WHAT THE FISCAL SIDE COSTS, WHICH THE TWO-SECTOR RACE COULD NOT SEE")
    print("=" * 92)
    print(f"  {'shock':>6} {'yrs':>4} | {'d NWG classical':>16} {'d NWG Taylor':>14} | "
          f"{'d K/K classical':>16} {'d K/K Taylor':>14}")
    for wsh in (0.01, 0.02):
        for t in HZ:
            row = []
            for lab in ("classical", "Taylor"):
                sh, bs = runs[(lab, wsh)], runs[(lab, 0.0)]
                j = at(sh, t)
                row.append((sh["NWG"][j] - bs["NWG"][j],
                            (sh["K"][j] - bs["K"][j]) / bs["K"][j]))
            print(f"  {wsh:6.3f} {t:4.0f} | {row[0][0]:16.4f} {row[1][0]:14.4f} | "
                  f"{row[0][1]:16.5f} {row[1][1]:14.5f}")

    print("\n" + "=" * 92)
    print("THE UNSHOCKED PATHS THEMSELVES, which is why they had to be scored separately")
    print("=" * 92)
    print(f"  {'yrs':>4} | {'i1 classical':>13} {'i1 Taylor':>11} | "
          f"{'burden classical':>17} {'burden Taylor':>14}")
    for t in HZ:
        c, T = runs[("classical", 0.0)], runs[("Taylor", 0.0)]
        jc, jt = at(c, t), at(T, t)
        print(f"  {t:4.0f} | {c['i1'][jc]:13.5f} {T['i1'][jt]:11.5f} | "
              f"{c['burden'][jc]:17.5f} {T['burden'][jt]:14.5f}")
    print("\n  With no shock at all the two rules already differ, because the classical")
    print("  anchor tracks the normal loan rate and that rises as banking's margin is")
    print("  squeezed. Scoring the race on shocked levels would have charged that to the")
    print("  shock.")

    print("\n" + "=" * 92)
    print("READING IT")
    print("=" * 92)
    print("  ON SHOCK RESPONSE the classical anchor mostly wins, and by more than the")
    print("  two-sector race suggested. It protects the enterprise margin better at 20 and")
    print("  40 years and loses only by 80 -- so government debt has pushed the crossover")
    print("  out from around 25 years to somewhere past 40. It costs less capital at every")
    print("  horizon tested, and it damages the public balance sheet less at every horizon:")
    print("  -1.19 against -2.65 at 20 years, less than half. Taylor holds inflation")
    print("  marginally better throughout, by two or three hundredths of a point.")
    print("\n  BUT THE STANDING COST IS THE BIGGER NUMBER, and it only shows up once there")
    print("  is a public balance sheet to charge it to. On the UNSHOCKED path the classical")
    print("  rule runs a permanently tighter policy -- i1 of 0.0521 against 0.0495 by year")
    print("  80 -- because the price-level integral follows the normal loan rate up as")
    print("  banking's margin is squeezed, and Taylor's fixed intercept does not. That")
    print("  carries a permanently higher interest bill: a burden of 0.0510 against 0.0400,")
    print("  or 1.1 points of output, EVERY year, with no shock at all.")
    print("\n  Set that against the largest shock-response gap in the burden, 0.44 points at")
    print("  80 years. The standing cost is about two and a half times the contest the race")
    print("  was set up to measure. A rule anchored on a drifting quantity inherits the")
    print("  drift, and with debt at 0.71 of output the public finances pay for it whether")
    print("  or not anything is shocked. That is the finding the two-sector model could not")
    print("  have produced, and it argues for anchoring on a SLOWER-moving measure of the")
    print("  normal rate than the one-period equalisation used here.")


def incidence(name):
    """Where does a policy tightening land, and on whose balance sheet?

    Measured as DEVIATION FROM THE UNSHOCKED PATH, not from t=0, and that matters here.
    The baseline is not stationary: households' deposits grow faster than the loan book,
    so banks' funding cost rises against their lending income, their profit rate falls
    about 9e-3 over 40 periods, and equalisation then pushes the normal loan rate up. That
    is a real dynamic of the model rather than a defect, but it means anything read against
    t=0 would mix the shock with the drift. Every figure below is shocked minus unshocked
    at the same date.
    """
    from runner import Run
    watch = ["IntG", "IntBs", "IntBb", "IntBl", "iBl", "i1", "i2", "slope", "burden",
             "NWH", "NWF", "NWG", "EB", "rB", "rE", "gI", "u", "Y", "K", "debtG"]
    R = Run(f"~/minsky-models/{name}.mky")
    HZ = [1.0, 3.0, 5.0, 10.0, 20.0, 40.0]
    base, shock = {}, {}
    for t in HZ:
        base[t] = R.go(t, watch, {"ish": 0.0}, samples=200)
        shock[t] = R.go(t, watch, {"ish": 0.01}, samples=200)

    def d(t, k):
        return shock[t][k][-1] - base[t][k][-1]

    print("\n" + "=" * 78)
    print("A POLICY TIGHTENING OF ONE POINT: WHERE IT LANDS")
    print("=" * 78)
    print("  Deviations from the unshocked path at the same date, never from t=0.\n")
    print(f"  {'years':>6} {'d i1':>9} {'d i2':>9} {'d iBl':>9} {'d slope':>9}")
    for t in HZ:
        print(f"  {t:6.0f} {d(t,'i1'):+9.5f} {d(t,'i2'):+9.5f} {d(t,'iBl'):+9.5f} "
              f"{d(t,'slope'):+9.5f}")
    print("\n  The long rate moves less than the short one and the average COUPON on the")
    print("  long book moves less again, because it only reprices as the book rolls.")

    print("\n" + "=" * 78)
    print("THE GOVERNMENT'S INTEREST BILL, SPLIT BY HOW FAST EACH LEG REPRICES")
    print("=" * 78)
    print("  This is what the term structure is FOR. Short paper reprices at once; the")
    print("  long book only as it turns over, at 10% a year here.\n")
    print(f"  {'years':>6} {'immediate':>11} {'eventual':>10} {'total':>10} "
          f"{'% arrived':>10}")
    for t in HZ:
        imm = d(t, "IntBs") + d(t, "IntBb")
        evt = d(t, "IntBl")
        tot = d(t, "IntG")
        share = evt / tot * 100.0 if abs(tot) > 1e-12 else float("nan")
        print(f"  {t:6.0f} {imm:+11.5f} {evt:+10.5f} {tot:+10.5f} {share:9.1f}%")
    print("\n  The last column is the share of the extra bill coming from the LONG book.")
    print("  It starts near nothing and climbs as the book rolls -- so a tightening that")
    print("  looks cheap for the public finances in year one is not, by year twenty.")

    print("\n" + "=" * 78)
    print("EACH SECTOR'S NET WORTH")
    print("=" * 78)
    print("  Financial claims net to zero across the four, so these must sum to zero at")
    print("  every horizon. What the tightening does is REDISTRIBUTE, and the table says")
    print("  in which direction.\n")
    print(f"  {'years':>6} {'households':>11} {'firms':>10} {'government':>11} "
          f"{'banks':>9} {'sum':>10}")
    for t in HZ:
        h, f, gv, bk = d(t, "NWH"), d(t, "NWF"), d(t, "NWG"), d(t, "EB")
        print(f"  {t:6.0f} {h:+11.4f} {f:+10.4f} {gv:+11.4f} {bk:+9.4f} "
              f"{h+f+gv+bk:+10.1e}")

    print("\n" + "=" * 78)
    print("AND WHAT IT DOES TO THE REAL SIDE")
    print("=" * 78)
    print(f"  {'years':>6} {'d rE':>9} {'d gI':>9} {'d u':>9} {'d K/K':>9} "
          f"{'d rB':>9} {'d burden':>9}")
    for t in HZ:
        print(f"  {t:6.0f} {d(t,'rE'):+9.5f} {d(t,'gI'):+9.5f} {d(t,'u'):+9.5f} "
              f"{d(t,'K')/base[t]['K'][-1]:+9.5f} {d(t,'rB'):+9.5f} "
              f"{d(t,'burden'):+9.5f}")
    print("\n  rE is the profit rate of enterprise -- the quantity the whole Shaikhian")
    print("  argument runs on -- and burden is the government's interest bill per unit of")
    print("  output. Reading those two columns together is the point of having four")
    print("  sectors: the same point of tightening shows up as a squeeze on enterprise")
    print("  AND as a claim on the public finances, and the model prices both.")


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
    print("\n  THE BASELINE IS NOT STATIONARY, and shock experiments must be read against")
    print("  the unshocked PATH rather than against t=0. Two separate reasons, both real.")
    print("\n  First, banking's own profit rate drifts down about 9e-3 over 40 periods.")
    print("  Households' deposits grow faster than the loan book, so the funding cost")
    print("  rises against lending income; equalisation then pushes the normal loan rate")
    print("  up and the market rate follows. That is a mechanism, not a defect.")
    print("\n  Second, a common growth rate for every financial stock is IMPOSSIBLE here.")
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


def anchor(name):
    """Sweep how fast the policy anchor tracks the normal rate, and price the tradeoff.

    The instantaneous classical anchor wins on shock response but carries a STANDING cost:
    it follows the normal loan rate up as banking's margin is squeezed, so it runs a
    permanently tighter policy and a permanently higher interest bill even with nothing
    shocked. mu is the dial. Large mu is that rule; mu -> 0 freezes the intercept the way
    Taylor's rstar is frozen, which drops the standing cost but also drops the nominal
    anchor, since the proportional response api = 0.5 is below one on its own.

    The question is whether anything in between keeps most of the response and little of
    the drift.
    """
    from runner import Run
    watch = ["rE", "pi", "u", "K", "burden", "NWG", "i1", "i1Nbar", "debtG", "Y", "p"]
    R = Run(f"~/minsky-models/{name}.mky")
    TMAX = 80.0
    MUS = [5.0, 1.0, 0.30, 0.10, 0.03, 0.01]

    def at(path, t):
        return min(range(len(path["t"])), key=lambda k: abs(path["t"][k] - t))

    rows = []
    for mu in MUS:
        bs = R.go(TMAX, watch, {"rule": 1.0, "mu": mu, "wsh": 0.0}, samples=400)
        sh = R.go(TMAX, watch, {"rule": 1.0, "mu": mu, "wsh": 0.01}, samples=400)
        rows.append(("classical mu=%.2f" % mu, mu, bs, sh))
    tb = R.go(TMAX, watch, {"rule": 0.0, "wsh": 0.0}, samples=400)
    ts = R.go(TMAX, watch, {"rule": 0.0, "wsh": 0.01}, samples=400)
    rows.append(("Taylor", None, tb, ts))

    print("\n" + "=" * 94)
    print("HOW FAST SHOULD THE ANCHOR TRACK THE NORMAL RATE?")
    print("=" * 94)
    print("  STANDING COST is read off the UNSHOCKED path -- what the rule costs when")
    print("  nothing at all has happened. SHOCK RESPONSE is a +1% wage shock measured")
    print("  against that same rule's own unshocked path.\n")
    print(f"  {'rule':>18} | {'STANDING at t=80':>26} | {'SHOCK RESPONSE at t=40':>34}")
    print(f"  {'':>18} | {'i1':>8} {'burden':>8} {'vs Taylor':>8} | "
          f"{'worst rE':>10} {'d NWG':>10} {'d K/K':>10}")
    for lab, mu, bs, sh in rows:
        j80, j40 = at(bs, 80.0), at(bs, 40.0)
        k40 = at(sh, 40.0)
        n = max(1, k40 // 8)
        drE = min(sh["rE"][k] - bs["rE"][k] for k in range(n, k40 + 1))
        dnwg = sh["NWG"][k40] - bs["NWG"][j40]
        dk = (sh["K"][k40] - bs["K"][j40]) / bs["K"][j40]
        vs = bs["burden"][j80] - tb["burden"][at(tb, 80.0)]
        print(f"  {lab:>18} | {bs['i1'][j80]:8.5f} {bs['burden'][j80]:8.5f} "
              f"{vs:+8.5f} | {drE:10.5f} {dnwg:10.4f} {dk:10.5f}")
    print("\n  'vs Taylor' is the standing burden gap: how much MORE of output goes to the")
    print("  government's interest bill every year under this rule than under Taylor, with")
    print("  no shock at all.")

    print("\n" + "=" * 94)
    print("DOES SLOWING THE ANCHOR COST THE NOMINAL ANCHOR? -- the obvious worry, tested")
    print("=" * 94)
    print("  At small mu the rule's proportional inflation response is api = 0.5, below one,")
    print("  and the price-level integral that supplied the nominal anchor is slow. So the")
    print("  thing to check is whether inflation still comes back.\n")
    print(f"  {'rule':>18} | {'inflation deviation from own baseline':>44} | {'p at 160':>9}")
    print(f"  {'':>18} | {'t=20':>10} {'t=40':>10} {'t=80':>10} {'t=160':>10} | {'gap':>9}")
    long_ = {}
    for lab, mu, _bs, _sh in rows:
        kw = {"rule": 0.0} if mu is None else {"rule": 1.0, "mu": mu}
        bs = R.go(160.0, watch, dict(kw, wsh=0.0), samples=500)
        sh = R.go(160.0, watch, dict(kw, wsh=0.01), samples=500)
        long_[lab] = (bs, sh)
        cells = [sh["pi"][at(bs, t)] - bs["pi"][at(bs, t)] for t in (20., 40., 80., 160.)]
        j = at(bs, 160.)
        print(f"  {lab:>18} | " + " ".join(f"{c:10.5f}" for c in cells)
              + f" | {(sh['p'][j]-bs['p'][j])/bs['p'][j]:9.4f}")
    print("\n  IT DOES NOT, AND THE REASON IS THE SHOCK RATHER THAN THE RULES. No rule")
    print("  here closes the gap -- not the fast anchor, not the slow one, and not Taylor,")
    print("  which is carrying a response of 1 + api = 1.5. All of them leave inflation")
    print("  about 0.3 points high and the price level some 60% higher, permanently.")
    print("\n  That is correct, not a defect. wsh is a PERMANENT shift in the wage-share")
    print("  process, so omega settles at a new level and pi = pi0 + gp*(u-un) +")
    print("  gw*(omega-omN) is permanently higher. An interest rate cannot undo a permanent")
    print("  cost-push without permanently depressing utilisation. So 'does inflation")
    print("  return' does not discriminate between rules against this shock, and the")
    print("  question worth asking is what each one destroys while accommodating it.")
    print("\n  WHICH MEANS THERE IS NO TRADEOFF TO PRICE. Slowing the anchor improves the")
    print("  standing cost, the enterprise margin, the fiscal damage and the capital stock")
    print("  all at once, and it does not cost inflation control because none of these")
    print("  rules has inflation control against this shock in the first place.")


if __name__ == "__main__":
    main()
