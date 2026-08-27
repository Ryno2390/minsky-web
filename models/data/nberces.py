"""NBER-CES Manufacturing Industry Database: the long-run substitute for Compustat.

WHAT THIS IS AND IS NOT
-----------------------
private_return.py could only reach 2010-2024, because XBRL begins in 2009, and so could
measure the private return to R&D as a level but never as a trend. The test that would
settle the excludability thesis needs both sides of the private/social divergence tracked
over the sixty years it is supposed to have opened. Compustat would do it at firm level
and is a licensed WRDS product with no free route.

This is the best free substitute and it is worse in one way and better in another. Worse:
it is INDUSTRY level, not firm level, and covers MANUFACTURING only. Better: it runs
1958-2018 with the industries' own TFP already computed by the people who built the
database, so the social side needs no assembling.

    364 six-digit NAICS manufacturing industries, 1958-2018
    tfp5 / dtfp5   five-factor TFP level and growth
    vadd, pay      nominal value added and payroll, $mn
    cap            real capital stock, 1997 $mn -- NOT nominal, see below
    piship         shipments deflator, 1997 = 1

THE UNITS TRAP
--------------
vadd and pay are NOMINAL; cap, equip and plant are REAL in 1997 dollars. A profit rate
built as (vadd - pay)/cap therefore divides a nominal numerator by a real denominator and
drifts upward with the price level for sixty years, which would look exactly like a rising
return to capital and be nothing but inflation. The numerator is deflated by piship here
before the ratio is taken.
"""
import csv
import subprocess
from pathlib import Path

CACHE = Path(__file__).parent / "cache"
CACHE.mkdir(exist_ok=True)

URL = "https://data.nber.org/nberces/nberces5818v1/nberces5818v1_n2012.csv"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")

NUM = ("emp", "pay", "vship", "matcost", "vadd", "invest", "cap", "equip",
       "plant", "piship", "dtfp5", "tfp5")


def _download():
    path = CACHE / "nberces5818v1_n2012.csv"
    if path.exists() and path.stat().st_size > 1_000_000:
        return path
    out = subprocess.run(["curl", "-sL", "--max-time", "300", "-A", UA, "-o", str(path),
                          URL], capture_output=True, timeout=400)
    if out.returncode != 0 or not path.exists() or path.stat().st_size < 1_000_000:
        raise RuntimeError(f"could not fetch {URL}")
    return path


def rows():
    """One dict per industry-year, numerics parsed, blanks dropped."""
    out = []
    with _download().open() as fh:
        for r in csv.DictReader(fh):
            rec = {"naics": r["naics"], "year": int(r["year"])}
            for k in NUM:
                v = r.get(k, "")
                try:
                    rec[k] = float(v) if v not in ("", None) else None
                except ValueError:
                    rec[k] = None
            out.append(rec)
    return out


def by3():
    """Aggregate to three-digit NAICS, which is where BEA's industries live.

    Flows and stocks are summed. The deflator and TFP are weighted by value added,
    because an unweighted mean over six-digit industries would give a $200m niche the
    same say as a $200bn one.
    """
    acc = {}
    for r in rows():
        k = (r["naics"][:3], r["year"])
        a = acc.setdefault(k, {"vadd": 0.0, "pay": 0.0, "cap": 0.0, "emp": 0.0,
                               "vship": 0.0, "wsum": 0.0, "pi": 0.0, "tfp": 0.0,
                               "dtfp": 0.0, "dw": 0.0})
        for f in ("vadd", "pay", "cap", "emp", "vship"):
            if r.get(f) is not None:
                a[f] += r[f]
        w = r.get("vadd") or 0.0
        if w > 0 and r.get("piship"):
            a["pi"] += w * r["piship"]
            a["tfp"] += w * (r.get("tfp5") or 0.0)
            a["wsum"] += w
        if w > 0 and r.get("dtfp5") is not None:
            a["dtfp"] += w * r["dtfp5"]
            a["dw"] += w
    out = {}
    for (n3, y), a in acc.items():
        if a["wsum"] <= 0 or a["cap"] <= 0:
            continue
        out[(n3, y)] = {
            "vadd": a["vadd"], "pay": a["pay"], "cap": a["cap"], "emp": a["emp"],
            "piship": a["pi"] / a["wsum"],
            "tfp5": a["tfp"] / a["wsum"],
            "dtfp5": (a["dtfp"] / a["dw"]) if a["dw"] > 0 else None,
        }
    return out


def profit_rate(rec):
    """Real gross operating surplus over real capital.

    (vadd - pay) is nominal and cap is 1997 dollars, so the numerator is deflated first.
    Without that the series rises fivefold on inflation alone.
    """
    if not rec or rec["cap"] <= 0 or not rec["piship"]:
        return None
    return ((rec["vadd"] - rec["pay"]) / rec["piship"]) / rec["cap"]
