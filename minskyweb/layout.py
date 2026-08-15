"""Layered auto-layout for a Minsky canvas.

Pure geometry: this module knows nothing about pyminsky. It is handed a set of boxes and
the edges between them and returns where each box should go, so it can be tested without
an engine and reasoned about without a model loaded.

The shape is the usual Sugiyama pipeline -- break cycles, assign layers, insert dummy
nodes, reduce crossings, assign coordinates -- with one domain decision that matters more
than all the tuning put together, documented on `break_cycles` below.
"""
from collections import defaultdict

GAP_X = 55.0      # horizontal space between layers
GAP_Y = 26.0      # vertical space between boxes within a layer
PAD = 40.0        # margin around the whole diagram
SWEEPS = 8        # crossing-reduction passes
RELAX = 12        # coordinate-relaxation passes


class Box:
    """One thing to place: a key, a size, and where it ended up."""
    __slots__ = ("key", "w", "h", "x", "y", "layer", "order", "dummy")

    def __init__(self, key, w, h, dummy=False):
        self.key = key
        self.w = max(float(w), 1.0)
        self.h = max(float(h), 1.0)
        self.x = self.y = 0.0
        self.layer = self.order = 0
        self.dummy = dummy


# --------------------------------------------------------------------------- cycles
def break_cycles(keys, edges, sources=()):
    """Reverse a feedback arc set so the rest of the pipeline sees a DAG.

    `sources` names boxes that should be treated as origins even though edges point into
    them. For a Minsky model those are the integrals, and the choice is not cosmetic.

    An integral holds STATE. At the start of a timestep that state is already known -- it
    is an input to the derivative calculation, not a result of it. So the edge that closes
    a feedback loop is the derivative arriving back at the integral, and cutting there
    gives a depth equal to the real computational depth of the derivative.

    Cutting anywhere else is measurably worse. Letting a plain depth-first search choose
    put the cut at the integral's OUTPUT on GoodwinLinear, which pushed every downstream
    box a layer further right and turned a 9-layer model into 17 -- 2110px wide for 22
    icons. It also points the feedback edges rightward, so the diagram reads backwards.
    """
    sources = set(sources)
    reversed_ = {(a, b) for a, b in edges if b in sources}

    adj = defaultdict(list)
    for a, b in edges:
        if (a, b) not in reversed_:
            adj[a].append(b)

    # whatever is still cyclic after that cut is an algebraic loop; fall back to DFS
    WHITE, GREY, BLACK = 0, 1, 2
    color = defaultdict(int)
    for start in keys:
        if color[start] != WHITE:
            continue
        color[start] = GREY
        stack = [(start, iter(adj[start]))]
        while stack:
            node, it = stack[-1]
            advanced = False
            for nxt in it:
                c = color[nxt]
                if c == GREY:
                    reversed_.add((node, nxt))
                elif c == WHITE:
                    color[nxt] = GREY
                    stack.append((nxt, iter(adj[nxt])))
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                stack.pop()

    acyclic = []
    for a, b in edges:
        acyclic.append((b, a) if (a, b) in reversed_ else (a, b))
    return acyclic, reversed_


def topo(keys, edges):
    succ = defaultdict(list)
    indeg = defaultdict(int)
    for a, b in edges:
        succ[a].append(b)
        indeg[b] += 1
    q = [k for k in keys if indeg[k] == 0]
    out = []
    while q:
        n = q.pop()
        out.append(n)
        for m in succ[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)
    if len(out) < len(keys):
        seen = set(out)
        out += [k for k in keys if k not in seen]
    return out


# --------------------------------------------------------------------------- layers
def assign_layers(keys, edges):
    succ = defaultdict(list)
    for a, b in edges:
        succ[a].append(b)

    layer = {k: 0 for k in keys}
    order = topo(keys, edges)
    for n in order:
        for m in succ[n]:
            if layer[m] < layer[n] + 1:
                layer[m] = layer[n] + 1

    # A box with successors need not sit at its longest-path depth; pulling it as far
    # right as its earliest consumer allows keeps sources next to what consumes them
    # instead of banking every parameter into one tall column at layer 0.
    for n in reversed(order):
        if succ[n]:
            layer[n] = min(layer[m] for m in succ[n]) - 1

    lo = min(layer.values()) if layer else 0
    return {k: v - lo for k, v in layer.items()}


def add_dummies(boxes, edges, layer):
    """Split edges spanning more than one layer so long wires have anchors to route by."""
    out = []
    n = 0
    for a, b in edges:
        if layer[b] - layer[a] <= 1:
            out.append((a, b))
            continue
        prev = a
        for L in range(layer[a] + 1, layer[b]):
            key = ("__dummy", n)
            n += 1
            boxes[key] = Box(key, 1.0, 1.0, dummy=True)
            layer[key] = L
            out.append((prev, key))
            prev = key
        out.append((prev, b))
    return out


# --------------------------------------------------------------- crossing reduction
def _crossings_if(boxes, side, u, v):
    """Crossings contributed by u and v's edges when u sits immediately above v."""
    c = 0
    for adj in side:
        pu = sorted(boxes[m].order for m in adj[u])
        pv = sorted(boxes[m].order for m in adj[v])
        for a in pu:
            for b in pv:
                if b < a:
                    c += 1
    return c


def order_layers(boxes, edges, layer):
    by_layer = defaultdict(list)
    for k in boxes:
        by_layer[layer[k]].append(k)
    for L in by_layer:
        by_layer[L].sort(key=str)
        for i, k in enumerate(by_layer[L]):
            boxes[k].order = i

    succ, pred = defaultdict(list), defaultdict(list)
    for a, b in edges:
        succ[a].append(b)
        pred[b].append(a)
    maxL = max(by_layer) if by_layer else 0

    def median(k, adj):
        near = adj[k]
        if not near:
            return -1.0
        pos = sorted(boxes[m].order for m in near)
        mid = len(pos) // 2
        return float(pos[mid]) if len(pos) % 2 else (pos[mid - 1] + pos[mid]) / 2.0

    for s in range(SWEEPS):
        down = s % 2 == 0
        rng = range(1, maxL + 1) if down else range(maxL - 1, -1, -1)
        adj = pred if down else succ
        for L in rng:
            row = by_layer[L]
            med = {k: median(k, adj) for k in row}
            row.sort(key=lambda k: med[k] if med[k] >= 0 else boxes[k].order)
            for i, k in enumerate(row):
                boxes[k].order = i
        # transpose: swap neighbours while it helps
        for _ in range(4):
            improved = False
            for L in range(maxL + 1):
                row = by_layer[L]
                for i in range(len(row) - 1):
                    u, v = row[i], row[i + 1]
                    if _crossings_if(boxes, (pred, succ), u, v) > \
                       _crossings_if(boxes, (pred, succ), v, u):
                        row[i], row[i + 1] = v, u
                        boxes[u].order, boxes[v].order = i + 1, i
                        improved = True
            if not improved:
                break
    return by_layer


# ---------------------------------------------------------------------- coordinates
def assign_coords(boxes, by_layer, edges):
    x = PAD
    for L in sorted(by_layer):
        row = by_layer[L]
        wmax = max((boxes[k].w for k in row), default=1.0)
        for k in row:
            boxes[k].x = x + (wmax - boxes[k].w) / 2.0
        x += wmax + GAP_X

    for L in sorted(by_layer):
        y = PAD
        for k in sorted(by_layer[L], key=lambda k: boxes[k].order):
            boxes[k].y = y
            y += boxes[k].h + GAP_Y

    succ, pred = defaultdict(list), defaultdict(list)
    for a, b in edges:
        succ[a].append(b)
        pred[b].append(a)

    def mid(k):
        return boxes[k].y + boxes[k].h / 2.0

    for it in range(RELAX):
        adj = pred if it % 2 == 0 else succ
        for L in sorted(by_layer, reverse=(it % 2 == 1)):
            row = sorted(by_layer[L], key=lambda k: boxes[k].order)
            for k in row:
                near = adj[k]
                if near:
                    want = sum(mid(m) for m in near) / len(near)
                    boxes[k].y += (want - mid(k)) * 0.5
            row.sort(key=lambda k: boxes[k].y)
            # re-separate; this is what guarantees nothing can overlap
            for i in range(1, len(row)):
                a, b = row[i - 1], row[i]
                floor = boxes[a].y + boxes[a].h + GAP_Y
                if boxes[b].y < floor:
                    boxes[b].y = floor
            for i, k in enumerate(row):
                boxes[k].order = i
            by_layer[L] = row

    top = min((b.y for b in boxes.values()), default=0.0)
    for b in boxes.values():
        b.y += PAD - top


# --------------------------------------------------------------------------- driver
def arrange(sizes, edges, sources=()):
    """Place boxes.

    sizes:   {key: (width, height)}
    edges:   [(src_key, dst_key), ...]  -- keys not in `sizes` are ignored
    sources: keys to treat as origins when breaking cycles (Minsky's integrals)

    Returns ({key: (x, y)} top-left corners, report dict).
    """
    boxes = {k: Box(k, w, h) for k, (w, h) in sizes.items()}
    edges = [(a, b) for a, b in edges if a in boxes and b in boxes and a != b]
    edges = list(dict.fromkeys(edges))

    # Boxes with no edge at all are not part of the dataflow, and layering drops every
    # one of them into layer 0. On LoanableFunds that stacked 55 unwired icons into a
    # single column and made the result 4725px tall. Hold them out and grid-pack them
    # underneath, so the wired part keeps its true shape.
    touched = {a for a, _ in edges} | {b for _, b in edges}
    loose = [k for k in boxes if k not in touched]
    for k in loose:
        del boxes[k]

    pos = {}
    report = dict(boxes=len(boxes), edges=len(edges), loose=len(loose),
                  layers=0, reversed=0, dummies=0)

    if boxes:
        acyclic, rev = break_cycles(list(boxes), edges, set(sources) & set(boxes))
        layer = assign_layers(list(boxes), acyclic)
        with_dummies = add_dummies(boxes, acyclic, layer)
        by_layer = order_layers(boxes, with_dummies, layer)
        assign_coords(boxes, by_layer, with_dummies)
        for k, b in boxes.items():
            if not b.dummy:
                pos[k] = (b.x, b.y)
        report.update(layers=(max(by_layer) + 1 if by_layer else 0),
                      reversed=len(rev),
                      dummies=sum(1 for b in boxes.values() if b.dummy))

    if loose:
        base = max((y + sizes[k][1] for k, (x, y) in pos.items()), default=0.0)
        right = max((x + sizes[k][0] for k, (x, y) in pos.items()), default=900.0)
        cx, cy, row_h = PAD, base + GAP_Y * 3, 0.0
        for k in sorted(loose, key=lambda k: (-sizes[k][0], str(k))):
            w, h = sizes[k]
            if cx > PAD and cx + w > right:
                cx, cy, row_h = PAD, cy + row_h + GAP_Y, 0.0
            pos[k] = (cx, cy)
            cx += w + GAP_X
            row_h = max(row_h, h)

    report["width"] = max((x + sizes[k][0] for k, (x, y) in pos.items()), default=0.0)
    report["height"] = max((y + sizes[k][1] for k, (x, y) in pos.items()), default=0.0)
    return pos, report
