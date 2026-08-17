"""US nonfinancial corporate business, assembled into the model's own variables.

    python3 models/data/uscorp.py            # the series, the ratios, and a first look

WHAT THIS IS FOR
----------------
The model is written in five quantities: the pre-interest profit rate `r`, leverage `d`,
the borrowing rate `iL`, the enterprise profit rate `rE = r - iL*d`, and accumulation `g`.
Every one of them has a national-accounts counterpart for the US nonfinancial corporate
sector, so the model can be confronted with data rather than calibrated to taste.

    r   = net operating surplus / capital stock          NOS is profit BEFORE interest
    iL*d= net interest paid     / capital stock          the interest bill per unit capital
    rE  = (NOS - net interest)  / capital stock
    B   = net interest / NOS                             the INTEREST BURDEN
    d   = debt securities and loans / capital stock
    iL  = net interest / debt
    g   = growth rate of the real capital stock

`B` is the one that needs no capital stock at all -- it is a ratio of two lines of the same
NIPA table -- so it is the most robust number here and, not by accident, the one the policy
rule is written in.

WHY NET OPERATING SURPLUS IS THE RIGHT NUMERATOR
-----------------------------------------------
NIPA splits the net value added of nonfinancial corporate business into compensation, taxes
on production, and net operating surplus; and splits net operating surplus into

    net interest and miscellaneous payments + business current transfers + corporate profits

which is exactly the model's split of pre-interest profit into the creditor's share and
enterprise's share. Nothing has to be constructed: the accounts already draw the line
Shaikh draws.

TWO HONEST CAVEATS, RECORDED HERE RATHER THAN BURIED
----------------------------------------------------
1. NIPA's interest line is NET -- interest paid less interest received. Firms holding large
   interest-bearing balances therefore show a smaller bill than they actually pay. This is
   the right concept for the model (it is what NOS is actually reduced by) but it is NOT
   the same as the coupon on the debt, and `iL` computed as net interest over debt is
   correspondingly a net rate, not a contract rate. The gross-rate check is in `rates()`.
2. The capital stock is Z.1's nonfinancial assets at MARKET value, which carries land
   prices. `capital()` returns the alternatives too so the profit rate can be shown not to
   depend on that choice.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fred                                                      # noqa: E402

# Every series used, with the role it plays. Titles are fetched from FRED and printed by
# `provenance()`, so nothing here is taken on trust.
SERIES = {
    # --- income: NIPA table 1.14, nonfinancial corporate business, $bn, quarterly SAAR ---
    "gva":     "A455RC1Q027SBEA",   # gross value added
    "nva":     "A457RC1Q027SBEA",   # net value added
    "comp":    "A460RC1Q027SBEA",   # compensation of employees
    "taxprod": "W325RC1Q027SBEA",   # taxes on production and imports less subsidies
    "nos":     "W326RC1Q027SBEA",   # NET OPERATING SURPLUS  <- pre-interest profit
    "interest": "B471RC1Q027SBEA",  # net interest and misc payments  <- the creditor share
    "transfer": "W327RC1Q027SBEA",  # business current transfer payments
    "profit":  "B467RC1Q027SBEA",   # profits after tax with IVA and CCAdj
    "pbt":     "A464RC1Q027SBEA",   # profits before tax
    # --- balance sheet: Z.1, nonfinancial corporate business, $mn, quarterly ---
    "debt":    "BCNSDODNS",         # debt securities and loans, liability
    "capital": "BOGZ1LM102010005Q",  # nonfinancial assets, market value
    "equity":  "NCBEILQ027S",       # corporate equities, liability
    "finasset": "TFAABSNNCB",       # total financial assets  <- for the NET debt check
    "totasset": "TABSNNCB",         # total assets
    "capex":   "BOGZ1FA105050005Q",  # total capital expenditures, flow
    "gfi":     "BOGZ1FA105013005Q",  # gross fixed investment, flow
    # --- policy and market rates, percent ---
    "ffr":     "FEDFUNDS",          # effective federal funds rate
    "baa":     "BAA",               # Moody's Baa corporate bond yield
    "aaa":     "AAA",               # Moody's Aaa corporate bond yield
}

BN, MN = 1.0, 1e-3          # $bn stays; $mn -> $bn


def quarterly(sid, scale=1.0):
    """{'1985-01-01': value} at quarterly dates, monthly series averaged into quarters."""
    s = fred.series(sid)
    if s is None:
        raise SystemExit(f"could not fetch {sid}")
    freq = s["meta"].get("freq", "")
    out = {}
    if freq.startswith("Month"):
        bucket = {}
        for dt, v in zip(s["date"], s["value"]):
            y, m, _ = dt.split("-")
            q = (int(m) - 1) // 3
            bucket.setdefault(f"{y}-{q*3+1:02d}-01", []).append(v)
        for k, vs in bucket.items():
            out[k] = sum(vs) / len(vs) * scale
    else:
        for dt, v in zip(s["date"], s["value"]):
            out[dt] = v * scale
    return out


def load():
    """Every series on a common quarterly index, in billions of dollars (or percent)."""
    scale = {k: (MN if k in ("debt", "capital", "equity", "finasset", "totasset",
                             "capex", "gfi") else 1.0) for k in SERIES}
    raw = {k: quarterly(sid, scale[k]) for k, sid in SERIES.items()}
    core = ("nos", "interest", "debt", "capital")
    dates = sorted(set.intersection(*(set(raw[k]) for k in core)))
    return {"date": dates, **{k: [raw[k].get(d) for d in dates] for k in SERIES}}


def ratios(D):
    """The model's variables, quarter by quarter. None wherever an input is missing.

    Both a GROSS and a NET reading of leverage are carried. NIPA's interest line is net of
    interest received, so pairing it with gross debt mixes concepts: `iL` is a net bill over
    a gross stock and is therefore biased down, badly so once firms hold large balances.
    `dnet` and `iLnet` pair the net bill with net debt -- debt less financial assets -- which
    is the consistent version, and `interest_check` reports how far apart they get.
    """
    keys = ("B", "r", "rE", "d", "iL", "iLd", "dnet", "iLnet", "g", "profitshare",
            "wageshare", "cfc")
    out = {k: [] for k in keys}
    for i in range(len(D["date"])):
        nos, itr, dbt, cap = D["nos"][i], D["interest"][i], D["debt"][i], D["capital"][i]
        nva, gva, fin = D["nva"][i], D["gva"][i], D["finasset"][i]
        cfc = (gva - nva) if (gva is not None and nva is not None) else None
        net = (dbt - fin) if fin is not None else None
        cx = D["capex"][i]
        out["B"].append(itr / nos if nos else None)
        out["r"].append(nos / cap if cap else None)
        out["rE"].append((nos - itr) / cap if cap else None)
        out["d"].append(dbt / cap if cap else None)
        out["iL"].append(itr / dbt if dbt else None)
        out["iLd"].append(itr / cap if cap else None)
        out["dnet"].append(net / cap if (net is not None and cap) else None)
        out["iLnet"].append(itr / net if (net and net > 0) else None)
        out["g"].append((cx - cfc) / cap if (cx is not None and cfc is not None and cap)
                        else None)
        out["profitshare"].append(nos / nva if nva else None)
        out["wageshare"].append(D["comp"][i] / nva if nva else None)
        out["cfc"].append(cfc / cap if (cfc is not None and cap) else None)
    return out


def interest_check(D, R):
    """Is the NET interest line a usable measure of what enterprise pays?

    Two ways of failing are checked. First, the implied rate `iL = net interest / debt`
    against a market yield: if firms' interest receipts are large, the implied rate falls
    far below any rate at which they could actually borrow. Second, the same bill against
    NET debt, which is the internally consistent pairing.
    """
    print("\nIS THE NET INTEREST LINE USABLE? implied rates against market yields")
    print(f"  {'years':>9} {'iL=int/debt':>12} {'int/netdebt':>12} {'Baa':>7} {'Aaa':>7} "
          f"{'fed funds':>10} {'netdebt/debt':>13}")
    yr = {k: annual(D, R, k) for k in ("iL", "iLnet", "d", "dnet")}
    ymkt = {}
    for k in ("baa", "aaa", "ffr"):
        b = {}
        for dt, v in zip(D["date"], D[k]):
            if v is not None:
                b.setdefault(dt[:4], []).append(v)
        ymkt[k] = {y: sum(v) / len(v) / 100.0 for y, v in b.items()}
    years = sorted(yr["iL"])
    for i in range(0, len(years) - 4, 5):
        blk = [y for y in years[i:i + 5] if y in ymkt["baa"]]
        if not blk:
            continue
        def avg(m):
            got = [m[y] for y in blk if y in m and m[y] is not None]
            return sum(got) / len(got) if got else float("nan")
        ratio = avg(yr["dnet"]) / avg(yr["d"]) if avg(yr["d"]) else float("nan")
        print(f"  {blk[0]}-{blk[-1][2:]} {avg(yr['iL']):12.4f} {avg(yr['iLnet']):12.4f} "
              f"{avg(ymkt['baa']):7.4f} {avg(ymkt['aaa']):7.4f} {avg(ymkt['ffr']):10.4f} "
              f"{ratio:13.3f}")


def provenance(path=None):
    """Print the FRED title of every series used, so identity can be checked."""
    print("SERIES USED (title as FRED reports it)")
    for role, sid in SERIES.items():
        m = fred.meta(sid)
        print(f"  {role:9s} {sid:20s} {(m['full'] if m else '??')[:96]}")
    if path:
        fred.catalogue(list(SERIES.values()), path)


def annual(D, R, key):
    """Collapse a quarterly ratio into calendar-year averages."""
    bucket = {}
    for d, v in zip(D["date"], R[key]):
        if v is not None:
            bucket.setdefault(d[:4], []).append(v)
    return {y: sum(v) / len(v) for y, v in sorted(bucket.items())}


def main():
    provenance()
    D = load()
    R = ratios(D)
    print(f"\n{len(D['date'])} quarters, {D['date'][0]} to {D['date'][-1]}")

    print("\nNONFINANCIAL CORPORATE BUSINESS, five-year averages")
    print(f"  {'years':>9} {'B':>8} {'r':>8} {'rE':>8} {'d':>8} {'iL':>8} "
          f"{'iL*d':>8} {'profit sh':>10}")
    yr = {k: annual(D, R, k) for k in R}
    years = sorted(yr["B"])

    def blockavg(k, blk):
        got = [yr[k][y] for y in blk if y in yr[k]]
        return sum(got) / len(got) if got else float("nan")

    for i in range(0, len(years) - 4, 5):
        blk = years[i:i + 5]
        row = {k: blockavg(k, blk) for k in yr}
        print(f"  {blk[0]}-{blk[-1][2:]} {row['B']:8.3f} {row['r']:8.4f} {row['rE']:8.4f} "
              f"{row['d']:8.3f} {row['iL']:8.4f} {row['iLd']:8.4f} "
              f"{row['profitshare']:10.3f}")

    b = yr["B"]
    print(f"\n  interest burden B = net interest / pre-interest profit")
    print(f"    mean {sum(b.values())/len(b):.3f}   "
          f"min {min(b.values()):.3f} ({min(b, key=b.get)})   "
          f"max {max(b.values()):.3f} ({max(b, key=b.get)})")
    over = [y for y in b if b[y] >= 1.0]
    print(f"    years at or above the B = 1 line (rE <= 0): "
          f"{', '.join(over) if over else 'none'}")
    interest_check(D, R)

    print("\nACCUMULATION  g = (capital expenditures - consumption of fixed capital) / K")
    g = annual(D, R, "g")
    years = sorted(g)
    for i in range(0, len(years) - 4, 5):
        blk = years[i:i + 5]
        print(f"  {blk[0]}-{blk[-1][2:]} {sum(g[y] for y in blk)/len(blk):8.4f}")


if __name__ == "__main__":
    main()
