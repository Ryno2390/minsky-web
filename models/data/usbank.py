"""US banking aggregates, mapped onto Shaikh's classical theory of the interest rate.

    python3 models/data/usbank.py

WHAT THIS IS FOR
----------------
Shaikh (Capitalism, ch. 10, sec. II) treats the loan rate as the PRICE OF PRODUCTION of
the banking sector: unit operating cost plus the normal profit rate on the capital a bank
must advance to make a loan. Imposing equalization of the bank profit rate with the general
rate on his bank-profit-rate identity gives a competitive loan rate that is linear in the
general profit rate,

    i_N  =  c  +  lam * r

    c   = nominal operating cost per dollar of loans      (his p*(ucrD*d + ucrL))
    lam = capital advanced per dollar of loans            (his p*kappa_fB + rd*d)

with lam < 1 required for the rate to be feasible -- which is also what delivers i_N < r,
and so a positive profit rate of enterprise, WITHOUT assuming it.

Every term is an accounting quantity a bank actually reports, so unlike a Wicksellian
natural rate the benchmark is observable:

    c   = total noninterest expense / net loans and leases
    lam = (bank premises and fixed assets + cash and balances due) / net loans and leases
    d   = total deposits / net loans and leases
    i   = interest income ON LOANS AND LEASES / net loans and leases
    rB  = net income / total equity          -- to check the equalization premise itself

SOURCE AND ITS SEAMS
--------------------
FDIC's public API, `summary` endpoint, which reports call-report aggregates by state and
charter class per year; those are summed to national totals here. Two seams are real and
are flagged rather than smoothed:

  1. A DEFINITIONAL BREAK at 1965/66. Operating cost per dollar of loans triples between
     those two years, from 0.012 to 0.037, and interest income on loans does the same --
     a reporting change, not an economic event. `usable()` therefore starts at 1966.
  2. EQUITY IS NOT REPORTED in these aggregates before about 1984, so the bank profit rate
     -- the thing whose equalization the whole theory turns on -- can only be checked from
     then on.

`CHBAL` (cash and balances due from depository institutions) stands in for Shaikh's
reserves RS. It is broader than required reserves, so `lam` is an upper bound on the
capital genuinely tied up per loan; since lam enters multiplied by r, and r is around 0.08,
the resulting overstatement of i_N is at most a few tenths of a point.
"""
import collections
import json
import subprocess
from pathlib import Path

CACHE = Path(__file__).parent / "cache"
CACHE.mkdir(exist_ok=True)

API = "https://banks.data.fdic.gov/api/summary"
FIELDS = ["YEAR", "ASSET", "LNLSNET", "DEP", "EQ", "NONIX", "BKPREM", "CHBAL",
          "ILNLS", "INTINC", "EINTEXP", "NETINC"]

MEANING = {
    "ASSET":   "total assets",
    "LNLSNET": "net loans and leases            -- the denominator throughout",
    "DEP":     "total deposits                  -- d = DEP/LNLSNET",
    "EQ":      "total equity capital            -- rB = NETINC/EQ",
    "NONIX":   "total noninterest expense       -- c = NONIX/LNLSNET",
    "BKPREM":  "bank premises and fixed assets  -- fixed capital in lam",
    "CHBAL":   "cash and balances due           -- stands in for reserves in lam",
    "ILNLS":   "interest income on loans/leases -- i = ILNLS/LNLSNET",
    "INTINC":  "total interest income           -- includes securities; NOT used for i",
    "EINTEXP": "total interest expense          -- what banks pay for funding",
    "NETINC":  "net income",
}
BREAK_YEAR = 1966          # reporting definitions change at 1965/66; see module docstring


def _fetch():
    path = CACHE / "fdic_summary.json"
    if path.exists() and path.stat().st_size:
        return json.loads(path.read_text())
    url = f"{API}?fields={','.join(FIELDS)}&limit=10000&format=json"
    for _ in range(3):
        r = subprocess.run(["curl", "-sSL", "--max-time", "180", url, "-o", str(path)],
                           capture_output=True)
        if r.returncode == 0 and path.exists() and path.stat().st_size:
            break
    else:
        raise RuntimeError("could not fetch FDIC summary")
    return json.loads(path.read_text())


def national():
    """National totals by year, taken from the endpoint's OWN aggregate row.

    DO NOT sum every row. The summary endpoint returns ids of the form
    `<charter>_<year>_<region>`, and the regions include national aggregates alongside the
    states: for commercial banks in 2023 the 63 rows are 59 states and territories summing
    to $11,611.3bn of net loans, plus a `USA` row carrying that same 11,611.3, plus a `US`
    row carrying 11,566.4, plus `OT` and `PI`. Summing the lot gives $34,835.7bn -- about
    three times the real loan book -- because the national total is counted twice more.

    Ratios like c and lam survive that (numerator and denominator inflate together) but
    nothing else does, and it is not worth relying on the inflation being uniform across
    fields when `US` and `USA` demonstrably differ. So the `USA` row is used directly, and
    charter classes (CB commercial banks, SI savings institutions) are summed across, since
    Shaikh's banking sector is depository institutions rather than commercial banks alone.
    """
    raw = _fetch()
    agg = collections.defaultdict(lambda: collections.defaultdict(float))
    seen = collections.defaultdict(set)
    for row in raw["data"]:
        x = row["data"]
        year = x.get("YEAR")
        ident = x.get("ID", "")
        if not year or not ident.endswith("_USA"):
            continue
        charter = ident.split("_", 1)[0]
        if charter in seen[year]:          # one row per charter class per year
            continue
        seen[year].add(charter)
        for f in FIELDS[1:]:
            v = x.get(f)
            if v is not None:
                agg[year][f] += float(v)
    return {int(y): dict(v) for y, v in sorted(agg.items())}


def required_reserves():
    """{year: required reserves in $thousands}, to match the FDIC units.

    Shaikh's lam is p*kappa_fB + rd*d -- fixed capital plus REQUIRED reserves per dollar of
    loans. It is emphatically not total cash and balances due. `CHBAL` is 91% of the naive
    measure and swings 0.067 (2007) to 0.322 (2021) as QE inflates reserve balances at the
    Fed; those are voluntary holdings earning IOR, not capital a bank must tie up to make a
    loan, and using them makes lam a QE artefact rather than a technical coefficient.

    Required reserves were abolished in March 2020, so this is zero from then on and the
    series is discontinued. That is a real fact about the coefficient, not missing data.
    """
    import fred                                                  # noqa: PLC0415
    s = fred.series("REQRESNS")                                  # $bn, monthly
    if s is None:
        return {}
    b = {}
    for dt, v in zip(s["date"], s["value"]):
        b.setdefault(int(dt[:4]), []).append(v)
    return {y: (sum(v) / len(v)) * 1e6 for y, v in b.items()}     # $bn -> $thousands


def coefficients(nat=None):
    """Shaikh's banking coefficients, year by year. None where an input is unreported."""
    nat = nat or national()
    try:
        rr = required_reserves()
    except Exception:                                            # noqa: BLE001
        rr = {}
    out = {}
    for y, a in nat.items():
        L = a.get("LNLSNET", 0.0)
        if L <= 0 or a.get("NONIX", 0.0) <= 0:
            continue
        eq = a.get("EQ", 0.0)
        prem = a.get("BKPREM", 0.0)
        req = rr.get(y, 0.0 if y >= 2021 else None)
        out[y] = {
            "c":   a["NONIX"] / L,
            # Shaikh's lam: fixed capital + REQUIRED reserves, per dollar of loans
            "lam": (prem + req) / L if req is not None else None,
            "lamPrem": prem / L,
            "lamReq": req / L if req is not None else None,
            # the naive measure that was used before, kept ONLY to show how far off it is
            "lamCash": (prem + a.get("CHBAL", 0.0)) / L,
            "d":   a.get("DEP", 0.0) / L,
            "i":   a["ILNLS"] / L if a.get("ILNLS") else None,
            "iAll": a.get("INTINC", 0.0) / L,
            "rB":  a["NETINC"] / eq if eq else None,
            "eqRatio": eq / a["ASSET"] if eq and a.get("ASSET") else None,
            "loans": L / 1e6,
        }
    return out


def usable(coef=None):
    """The coefficients over the span where the definitions are stable and complete."""
    coef = coef or coefficients()
    return {y: v for y, v in coef.items() if y >= BREAK_YEAR and v["i"] is not None}


def provenance():
    print("FDIC call-report aggregates (summary endpoint), summed across states")
    for f in FIELDS[1:]:
        print(f"  {f:8s} {MEANING.get(f, '')}")
    print(f"  definitional break flagged at {BREAK_YEAR}; equity unreported before ~1984")


def main():
    provenance()
    coef = coefficients()
    ys = sorted(coef)
    print(f"\n{len(ys)} years, {ys[0]} to {ys[-1]}")

    print("\nTHE 1969/70 BREAK, shown rather than asserted")
    print(f"  {'year':>6} {'c':>8} {'i(loans)':>9} {'i(all)':>8}")
    for y in (1965, 1966, 1967, 1968, 1969, 1970, 1971, 1972):
        if y in coef:
            v = coef[y]
            iv = f"{v['i']:9.4f}" if v["i"] is not None else f"{'--':>9}"
            print(f"  {y:>6} {v['c']:8.4f} {iv} {v['iAll']:8.4f}")

    u = usable(coef)
    ys = sorted(u)
    print(f"\nSHAIKH'S COEFFICIENTS, {ys[0]}-{ys[-1]}, five-year averages")
    print(f"  {'years':>9} {'c':>8} {'lam':>8} {'  prem':>8} {'  req':>8} {'lamCash':>8} "
          f"{'d':>7} {'i':>8} {'rB':>8}")
    for k in range(0, len(ys) - 4, 5):
        blk = ys[k:k + 5]
        def av(f):
            g = [u[y][f] for y in blk if u[y].get(f) is not None]
            return sum(g) / len(g) if g else float("nan")
        print(f"  {blk[0]}-{str(blk[-1])[2:]} {av('c'):8.4f} {av('lam'):8.4f} "
              f"{av('lamPrem'):8.4f} {av('lamReq'):8.4f} {av('lamCash'):8.4f} "
              f"{av('d'):7.3f} {av('i'):8.4f} {av('rB'):8.4f}")

    lam = [u[y]["lam"] for y in ys if u[y]["lam"] is not None]
    cash = [u[y]["lamCash"] for y in ys]
    print(f"\n  lam (Shaikh's: fixed capital + REQUIRED reserves) {min(lam):.4f} to "
          f"{max(lam):.4f}")
    print(f"  lamCash (the naive fixed capital + ALL cash)      {min(cash):.4f} to "
          f"{max(cash):.4f}")
    print("\n  The gap between those two rows is the whole correction. lamCash is about ten")
    print("  times lam and is dominated by reserve balances at the Fed, which swing with QE")
    print("  rather than with anything technical about lending. Shaikh's lam is a technical")
    print("  coefficient -- what a bank must tie up to make a loan -- and it is small and")
    print("  falling. Required reserves went to zero outright in March 2020, so from then on")
    print("  lam is just premises.")
    print("\n  Either way lam < 1 with enormous room, which is what makes i_N < r fall out of")
    print("  the theory rather than being assumed. But the PROFIT TERM lam*r shrinks by an")
    print("  order of magnitude, and that is a real change to the theory's content: at")
    print(f"  lam = {sum(lam)/len(lam):.4f} and r = 0.08, lam*r is "
          f"{sum(lam)/len(lam)*0.08*1e4:.0f} basis points, not 157.")


if __name__ == "__main__":
    main()
