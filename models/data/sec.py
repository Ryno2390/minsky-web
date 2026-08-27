"""Firm-level financials from SEC XBRL, for the private return to R&D.

WHY THIS EXISTS
---------------
spillover.py established that research moved out of vertically integrated firms and into
firms that own little else, and observed that the theory makes one checkable prediction it
could not reach: if the mechanism is EXCLUDABILITY, the private return to R&D should have
held up while the social return collapsed. Testing that needs firm accounts.

Compustat is not free. SEC's XBRL "frames" API is, needs no key, and returns every filer
reporting a given concept in a given period:

    https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/USD/CY{year}.json      flows
    https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/USD/CY{year}Q4I.json   stocks

Duration concepts (R&D expense, revenue, operating income) use the plain CY form.
Instantaneous ones (assets, net PP&E, equity) need the Q4I form -- asking for the plain
form returns an error, which is what a first pass here read as "no coverage".

THE COVERAGE LIMIT, WHICH IS THE BINDING ONE
--------------------------------------------
XBRL was phased in from 2009, so this reaches 2010-2024 and no further back. The
prediction being tested is about a CHANGE since the 1960s, and fifteen recent years cannot
show a change over sixty. What they can do is measure the private return NOW and set it
against the social return NOW, which is a real test of the wedge even though it is not a
test of when the wedge opened. Nothing here should be read as establishing a trend.

SEC asks for a declarative User-Agent and rate-limits to ten requests a second. The agent
below identifies the tool and carries no personal contact details.
"""
import json
import subprocess
import time
from pathlib import Path

CACHE = Path(__file__).parent / "cache" / "sec"
CACHE.mkdir(parents=True, exist_ok=True)

BASE = "https://data.sec.gov/api/xbrl/frames/us-gaap"
UA = "minsky-web-research/1.0 (capital stock and productivity research)"

#: concept -> is it instantaneous (a stock) rather than a flow over the year?
CONCEPTS = {
    "ResearchAndDevelopmentExpense": False,
    "Revenues": False,
    "OperatingIncomeLoss": False,
    "NetIncomeLoss": False,
    "Assets": True,
    "PropertyPlantAndEquipmentNet": True,
    "StockholdersEquity": True,
}


def _get(concept, year):
    inst = CONCEPTS[concept]
    period = f"CY{year}Q4I" if inst else f"CY{year}"
    path = CACHE / f"{concept}_{period}.json"
    if path.exists() and path.stat().st_size > 200:
        return json.loads(path.read_text())
    url = f"{BASE}/{concept}/USD/{period}.json"
    out = subprocess.run(["curl", "-s", "--max-time", "120", "-H", f"User-Agent: {UA}",
                          url], capture_output=True, text=True, timeout=180)
    time.sleep(0.2)                                   # SEC asks for <= 10 req/s
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        return None
    if "data" not in data or not data["data"]:
        return None
    path.write_text(out.stdout)
    return data


def frame(concept, year):
    """{cik: value} for one concept in one year, or {} if the frame does not exist."""
    d = _get(concept, year)
    if d is None:
        return {}
    return {int(r["cik"]): float(r["val"]) for r in d["data"]
            if r.get("val") is not None}


def names(year=2020):
    d = _get("Assets", year)
    return {} if d is None else {int(r["cik"]): r["entityName"] for r in d["data"]}


def panel(years):
    """{year: {cik: {concept: value}}}, only firms reporting R&D that year."""
    out = {}
    for y in years:
        rd = frame("ResearchAndDevelopmentExpense", y)
        if not rd:
            continue
        row = {}
        cols = {c: frame(c, y) for c in CONCEPTS if c != "ResearchAndDevelopmentExpense"}
        for cik, v in rd.items():
            rec = {"rd": v}
            for c, m in cols.items():
                if cik in m:
                    rec[c] = m[cik]
            row[cik] = rec
        out[y] = row
    return out
