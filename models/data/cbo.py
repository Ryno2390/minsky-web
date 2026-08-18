"""CBO projections, from the agency's own published data repository.

WHY GITHUB AND NOT cbo.gov
--------------------------
cbo.gov answers this environment with 403 for every request, browser or not, so the
xlsx files behind the Budget and Economic Data page cannot be reached. CBO also publishes
the same series as tidy CSV at github.com/US-CBO/cbo-data, which raw.githubusercontent
serves without objection. Same agency, same numbers, machine-readable rather than
spreadsheet-shaped.

VINTAGE
-------
Everything here is the FEBRUARY 2026 vintage, which is the current one. Projections are
not measurements: this is what CBO believed in February 2026 under current law, and
"current law" does a great deal of work at the long end -- it assumes scheduled expiries
happen on schedule, which they historically do not. Nothing downstream should be read as
a forecast of what will happen. It is a forecast of what would happen if nothing changed.

FILES
-----
  long_term_budget      FY2026-FY2056  debt, primary deficit, net interest, GDP
  long_term_economic    1996-2056      effective rate on federal debt, nominal growth
  economic_projections  1996-2036      fed funds, 10y Treasury, personal interest income

The last one stops at 2036 because it is the ten-year window; beyond that only the
long-term files exist, and they carry no separate 10y rate.
"""
import csv
import io
import subprocess
from pathlib import Path

CACHE = Path(__file__).parent / "cache"
CACHE.mkdir(exist_ok=True)

VINTAGE = "2026-02"
BASE = "https://raw.githubusercontent.com/US-CBO/cbo-data/main/data"

FILES = {
    "budget": f"budget/long_term_budget/annual_fy_{VINTAGE}.csv",
    "ltecon": f"economic/long_term_economic/rates_{VINTAGE}.csv",
    "econ": f"economic/economic_projections/calendar_{VINTAGE}.csv",
}


def _get(url, path):
    """curl, for the same reason fred.py uses it: urllib stalls here and curl does not."""
    if path.exists():
        return path.read_text()
    out = subprocess.run(["curl", "-sL", "--max-time", "120", url],
                         capture_output=True, text=True, timeout=180)
    if out.returncode != 0 or not out.stdout.strip():
        raise RuntimeError(f"could not fetch {url}: rc={out.returncode}")
    if out.stdout.lstrip().startswith("<"):
        raise RuntimeError(f"{url} returned HTML, not CSV")
    path.write_text(out.stdout)
    return out.stdout


def table(which):
    """{variable: {year: value}} for one of the FILES keys. Years are ints."""
    txt = _get(f"{BASE}/{FILES[which]}", CACHE / f"cbo_{which}_{VINTAGE}.csv")
    out = {}
    for row in csv.DictReader(io.StringIO(txt)):
        d = row["date"]
        y = int("".join(ch for ch in d if ch.isdigit()))
        try:
            v = float(row["value"])
        except (ValueError, TypeError):
            continue
        out.setdefault(row["variable"], {})[y] = v
    return out


def series(which, name, scale=1.0):
    t = table(which)
    if name not in t:
        raise KeyError(f"{name} not in {which}; have {sorted(t)[:8]}...")
    return {y: v * scale for y, v in t[name].items()}
