#!/usr/bin/env python3
"""Regenerate the logo path from the model it came from.

The M in the masthead is the raw trajectory of net investment in MinskyNonLinear over
one and a bit periods. This re-runs that model and prints the SVG path, so the mark can
always be checked against the thing it claims to be. See docs/LOGO.md.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MODEL = Path.home() / "minsky" / "examples" / "MinskyNonLinear.mky"
VARIABLE = "I_n"
TMAX = 60.0
EPS = 0.004          # simplification tolerance, in the normalised unit box
BOX = (200.0, 120.0, 6.0)   # width, height, padding


def turning_points(v):
    """(index, +1 for a maximum, -1 for a minimum)."""
    out = []
    for i in range(1, len(v) - 1):
        a, b, c = v[i - 1], v[i], v[i + 1]
        if None in (a, b, c):
            continue
        if b > a and b >= c:
            out.append((i, 1))
        elif b < a and b <= c:
            out.append((i, -1))
    return out


def rdp(pts, eps):
    """Ramer-Douglas-Peucker. 410 samples carry the same shape as 31."""
    if len(pts) < 3:
        return pts

    def perp(p, a, b):
        (x, y), (x1, y1), (x2, y2) = p, a, b
        dx, dy = x2 - x1, y2 - y1
        n = (dx * dx + dy * dy) ** 0.5
        if n == 0:
            return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
        return abs(dy * x - dx * y + x2 * y1 - y2 * x1) / n

    dmax, idx = 0.0, 0
    for i in range(1, len(pts) - 1):
        d = perp(pts[i], pts[0], pts[-1])
        if d > dmax:
            dmax, idx = d, i
    if dmax > eps:
        return rdp(pts[: idx + 1], eps)[:-1] + rdp(pts[idx:], eps)
    return [pts[0], pts[-1]]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variable", default=VARIABLE)
    ap.add_argument("--model", default=str(MODEL))
    ap.add_argument("--raw", action="store_true", help="every sample, unsimplified")
    ap.add_argument("--tmax", type=float, default=TMAX)
    args = ap.parse_args()

    from minskyweb import headless as H

    m = H.Model()
    mk = m.minsky
    if not Path(args.model).exists():
        sys.exit(f"no model at {args.model}")
    mk.load(args.model)

    key = None

    def walk(node):
        nonlocal key
        for i in range(len(node.items)):
            it = node.items[i]
            if not it.classType().startswith("Variable:"):
                continue
            try:
                if (it.name() or "").lstrip(":") == args.variable:
                    key = it.valueId()
            except Exception:
                pass
        for g in range(len(node.groups)):
            walk(node.groups[g])

    walk(mk.model)
    if not key:
        sys.exit(f"{args.variable!r} is not in {Path(args.model).name}")

    mk.reset()
    ts, vs, guard = [], [], 0
    while mk.t() < args.tmax and guard < 40000:
        mk.step()
        guard += 1
        ts.append(mk.t())
        try:
            vs.append(mk.variableValues[key].value())
        except Exception:
            vs.append(None)

    # the window: trough, peak, trough, peak, trough -- one M
    tp = turning_points(vs)
    maxes = [i for i, k in tp if k == 1]
    mins = [i for i, k in tp if k == -1]
    best = None
    for a in range(len(maxes) - 1):
        left = [i for i in mins if i < maxes[a]]
        right = [i for i in mins if i > maxes[a + 1]]
        if not left or not right:
            continue
        p1, p2 = vs[maxes[a]], vs[maxes[a + 1]]
        # a limit cycle repeats, so pick the pair whose peaks match most closely
        sym = 1 - abs(p1 - p2) / max(abs(p1), abs(p2), 1e-9)
        if best is None or sym > best[0]:
            best = (sym, left[-1], right[0], p1, p2)
    if not best:
        sys.exit(f"{args.variable} does not oscillate twice within t<{args.tmax}")

    sym, i0, i1, p1, p2 = best
    seg = [x for x in vs[i0 : i1 + 1] if x is not None]
    lo, hi = min(seg), max(seg)
    pts = [(i / (len(seg) - 1), (x - lo) / (hi - lo)) for i, x in enumerate(seg)]
    simp = pts if args.raw else rdp(pts, EPS)

    W, H, pad = BOX
    scr = [(pad + x * (W - 2 * pad), H - pad - y * (H - 2 * pad)) for x, y in simp]
    path = "M " + " L ".join(f"{x:.2f},{y:.2f}" for x, y in scr)

    print(f"# {Path(args.model).name}  {args.variable}", file=sys.stderr)
    print(f"# window    t {ts[i0]:.3f} .. {ts[i1]:.3f}", file=sys.stderr)
    print(f"# peaks     {p1:.4f} and {p2:.4f}   symmetry {sym:.4f}", file=sys.stderr)
    print(f"# points    {len(pts)} raw -> {len(simp)}", file=sys.stderr)
    print(path)


if __name__ == "__main__":
    main()
