"""Fetch FRED series with their TITLES, so a series is never used unidentified.

FRED's HTML pages and its JSON API (which needs a key) are both unavailable here.
Two endpoints do work, and between them they are enough:

    fredgraph.csv?id=X   the observations
    fredgraph.xls?id=X   an xlsx whose sharedStrings carry the title, units and frequency

Every series this project uses is fetched through `series()`, which returns the title
alongside the numbers and caches both on disk. `catalogue()` prints what was used so the
identity of every input can be checked against the source rather than taken on trust.
"""
import csv
import io
import json
import re
import subprocess
import zipfile
from pathlib import Path

CACHE = Path(__file__).parent / "cache"
CACHE.mkdir(exist_ok=True)
BASE = "https://fred.stlouisfed.org/graph/fredgraph"


def _get(url, path, binary=False):
    """curl, not urllib: FRED stalls on urllib's request but answers curl in under a second."""
    if path.exists() and path.stat().st_size:
        return path.read_bytes() if binary else path.read_text()
    for attempt in range(3):
        r = subprocess.run(["curl", "-sSL", "--max-time", "25", url, "-o", str(path)],
                           capture_output=True)
        if r.returncode == 0 and path.exists() and path.stat().st_size:
            break
    else:
        raise RuntimeError(f"could not fetch {url}")
    return path.read_bytes() if binary else path.read_text(errors="replace")


def meta(sid):
    """(title, units, frequency, adjustment) straight from FRED's own workbook."""
    raw = _get(f"{BASE}.xls?id={sid}", CACHE / f"{sid}.xlsx", binary=True)
    try:
        ss = zipfile.ZipFile(io.BytesIO(raw)).read("xl/sharedStrings.xml").decode("utf8", "replace")
    except (zipfile.BadZipFile, KeyError):
        return None
    vals = [re.sub(r"<[^>]+>", "", v) for v in re.findall(r"<t[^>]*>(.*?)</t>", ss, re.S)]
    for i, v in enumerate(vals):
        if v.strip() == sid and i + 1 < len(vals):
            parts = [p.strip() for p in vals[i + 1].split(",")]
            return {"id": sid, "full": vals[i + 1], "title": ", ".join(parts[:-3]) or vals[i + 1],
                    "units": parts[-3] if len(parts) > 3 else "",
                    "freq": parts[-2] if len(parts) > 3 else "",
                    "adj": parts[-1] if len(parts) > 3 else ""}
    return None


def series(sid):
    """{'meta': {...}, 'date': [...], 'value': [...]} with missing periods dropped."""
    txt = _get(f"{BASE}.csv?id={sid}", CACHE / f"{sid}.csv")
    rows = list(csv.reader(io.StringIO(txt)))
    if not rows or len(rows[0]) < 2:
        return None
    date, value = [], []
    for row in rows[1:]:
        if len(row) < 2 or row[1] in (".", ""):
            continue
        try:
            value.append(float(row[1]))
        except ValueError:
            continue
        date.append(row[0])
    if not date:
        return None
    return {"meta": meta(sid) or {"id": sid, "title": "(no title)"}, "date": date, "value": value}


def probe(ids):
    """Print id -> title for each candidate, so the right one can be picked by name."""
    out = {}
    for sid in ids:
        try:
            m = meta(sid)
        except Exception as e:                                   # noqa: BLE001
            print(f"  {sid:22s} ERROR {type(e).__name__}")
            continue
        if m is None:
            print(f"  {sid:22s} --")
            continue
        out[sid] = m
        print(f"  {sid:22s} {m['full'][:118]}")
    return out


def catalogue(ids, path=None):
    """Record every series actually used, with its title, for provenance."""
    rec = {}
    for sid in ids:
        m = meta(sid)
        if m:
            rec[sid] = m["full"]
    if path:
        Path(path).write_text(json.dumps(rec, indent=2, sort_keys=True))
    return rec
