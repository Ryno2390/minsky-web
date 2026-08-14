"""End-to-end tests for the HTTP/WebSocket layer.

The model is built entirely over HTTP -- no direct engine calls -- and then checked
against an analytic solution, so a server that wires the wrong ports fails loudly
rather than streaming plausible numbers.
"""
import math, sys
from fastapi.testclient import TestClient
from minskyweb.server import app, require_idle, _RUNNING
from fastapi import HTTPException

c = TestClient(app)
FAILED = []
def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}{'  ' + detail if detail else ''}")
    if not cond: FAILED.append(name)

print("1. build dS/dt = r*S entirely over HTTP")
assert c.post("/api/clear").status_code == 200
r  = c.post("/api/item", json={"kind": "parameter", "name": "r", "value": 0.10}).json()
mu = c.post("/api/item", json={"kind": "operation", "op": "multiply"}).json()
ig = c.post("/api/item", json={"kind": "operation", "op": "integrate"}).json()
check("items created", all(x["index"] >= 0 for x in (r, mu, ig)),
      f"r={r['index']} mul={mu['index']} int={ig['index']}")
for src, dst, port in ((r["index"], mu["index"], 1),
                       (mu["index"], ig["index"], 1),
                       (ig["index"], mu["index"], 2)):
    resp = c.post("/api/wire", json={"src": src, "dst": dst, "port": port})
    assert resp.status_code == 200, resp.text
st = c.post("/api/init", json={"name": "int1", "value": 1.0}).json()
check("3 wires", len(st["wires"]) == 3, f"{len(st['items'])} items, {len(st['wires'])} wires")

print("\n2. /api/state exposes ports with roles")
s = c.get("/api/state").json()
mul = next(i for i in s["items"] if i["classType"] == "Operation:multiply")
roles = [p["role"] for p in mul["ports"]]
check("port 0 output, rest inputs", roles == ["output", "input", "input"], str(roles))
check("solver reported", "epsRel" in s["solver"], str(s["solver"])[:60])

print("\n3. websocket streams a run that matches exp(rt)")
frames = []
with c.websocket_connect("/ws/sim") as ws:
    ws.send_json({"cmd": "run", "steps": 400, "tmax": 5.0})
    while True:
        m = ws.receive_json()
        if "error" in m: check("no stream error", False, m["error"]); break
        if m.get("done") or m.get("stopped"): break
        frames.append(m)
check("frames streamed", len(frames) > 10, f"{len(frames)} frames")
if frames:
    last = frames[-1]
    S, t = last["values"][":int1"], last["t"]
    exact = math.exp(0.10 * t)
    check("final value matches analytic", abs(S - exact) / exact < 1e-8,
          f"t={t:.4f} S={S:.6f} exact={exact:.6f} rel={abs(S-exact)/exact:.2e}")
    mono = all(b["t"] > a["t"] for a, b in zip(frames, frames[1:]))
    check("t strictly increasing", mono)

print("\n4. stop mid-run is honoured")
with c.websocket_connect("/ws/sim") as ws:
    ws.send_json({"cmd": "run", "steps": 100000})
    for _ in range(5): ws.receive_json()
    ws.send_json({"cmd": "stop"})
    stopped, seen = False, 0
    for _ in range(500):
        m = ws.receive_json(); seen += 1
        if m.get("stopped"): stopped = True; break
        if m.get("done"): break
    check("stream stopped early", stopped, f"after {seen} more frames")
check("running flag cleared", not _RUNNING.is_set())

print("\n5. errors surface with a diagnosis, not a 500")
bad = c.post("/api/wire", json={"src": 0, "dst": 0, "port": 0})
check("port-0 wire -> 400", bad.status_code == 400, f"{bad.status_code} {bad.text[:70]}")
oor = c.post("/api/wire", json={"src": 0, "dst": 99, "port": 1})
check("out-of-range -> 422", oor.status_code == 422, str(oor.status_code))
# NOTE: an unwired integral RESETS FINE and fails on step -- the inverse of the
# documented hazard. Both directions exist, so the stream must report step failures.
c.post("/api/clear")
c.post("/api/item", json={"kind": "operation", "op": "integrate"})
rr = c.post("/api/reset")
check("unwired integral resets OK", rr.status_code == 200, str(rr.status_code))
with c.websocket_connect("/ws/sim") as ws:
    ws.send_json({"cmd": "run", "steps": 5})
    msg = ws.receive_json()
check("unwired integral errors on STEP", "error" in msg and "not wired" in msg["error"],
      str(msg)[:80])

print("\n6. mutation is refused while a run streams")
_RUNNING.set()
try:
    require_idle(); check("require_idle raises 409", False)
except HTTPException as e:
    check("require_idle raises 409", e.status_code == 409)
finally:
    _RUNNING.clear()

print("\n7. Godley table over HTTP, then simulate it")
c.post("/api/clear")
gi = c.post("/api/item", json={"kind":"godley"}).json()["index"]
c.post(f"/api/godley/{gi}/resize", json={"rows":3,"cols":4})
for r,cc,v in ((0,0,"Flows V / Stock Variables ->"),(0,1,"Reserves"),(0,2,"Deposits"),
               (0,3,"Equity"),(1,0,"Initial Conditions"),(1,1,"100"),(1,2,"60"),(1,3,"40"),
               (2,0,"Lending"),(2,1,"Lend"),(2,2,"Lend")):
    assert c.post(f"/api/godley/{gi}/cell", json={"row":r,"col":cc,"value":v}).status_code == 200
for col,cl in ((1,"asset"),(2,"liability"),(3,"equity")):
    c.post(f"/api/godley/{gi}/class", json={"col":col,"cls":cl})
g = c.get(f"/api/godley/{gi}").json()
check("classes set", g["classes"] == ["noAssetClass","asset","liability","equity"], str(g["classes"]))
check("every row balances", all(v=="0" for v in g["rowSums"][1:]), str(g["rowSums"]))

# break it, confirm the imbalance is symbolic and detected, then repair
c.post(f"/api/godley/{gi}/cell", json={"row":2,"col":2,"value":"-Lend"})
g = c.get(f"/api/godley/{gi}").json()
check("imbalance detected symbolically", g["rowSums"][2] not in ("0",""), repr(g["rowSums"][2]))
c.post(f"/api/godley/{gi}/cell", json={"row":2,"col":2,"value":"Lend"})

# guard rails
check("row 0 undeletable", c.post(f"/api/godley/{gi}/row/delete",
      json={"at":0}).status_code == 422)
check("col 0 has no class", c.post(f"/api/godley/{gi}/class",
      json={"col":0,"cls":"asset"}).status_code == 422)
check("bad class rejected", c.post(f"/api/godley/{gi}/class",
      json={"col":1,"cls":"nonsense"}).status_code == 422)
check("non-godley item rejected", c.post("/api/item",
      json={"kind":"operation","op":"time"}).status_code == 200 and
      c.get("/api/godley/1").status_code == 422)

# drive the flow from the canvas and run
rate = c.post("/api/item", json={"kind":"parameter","name":"rate","value":5.0,
                                 "at":[140,400]}).json()["index"]
lend = c.post("/api/item", json={"kind":"variable","name":"Lend","var_type":"flow",
                                 "at":[420,400]}).json()["index"]
assert c.post("/api/wire", json={"src":rate,"dst":lend,"port":1}).status_code == 200
last = None
with c.websocket_connect("/ws/sim") as ws:
    ws.send_json({"cmd":"run","steps":900,"tmax":4.0})
    while True:
        msg = ws.receive_json()
        if "error" in msg: check("godley model runs", False, msg["error"]); break
        if msg.get("done") or msg.get("stopped"): break
        last = msg
if last:
    t_, R, D = last["t"], last["values"][":Reserves"], last["values"][":Deposits"]
    check("Reserves integrates correctly", abs(R-(100+5*t_)) < 1e-6,
          f"t={t_:.4f} R={R:.4f} expect {100+5*t_:.4f}")
    check("Deposits integrates correctly", abs(D-(60+5*t_)) < 1e-6,
          f"D={D:.4f} expect {60+5*t_:.4f}")

print("\n8. file picker: listing, path guard, load fidelity, upload")
import glob, os
roots = c.get("/api/files").json()["roots"]
check("lists model directories", any(r["files"] for r in roots),
      f"{sum(len(r['files']) for r in roots)} models across {len(roots)} dirs")

check("refuses non-.mky", c.post("/api/load?path=/etc/passwd").status_code == 422)
check("refuses traversal", c.post(
    "/api/load?path=/Users/ryneschultz/minsky/examples/../../../etc/hosts"
    ).status_code in (403, 404))
check("refuses .mky outside roots", c.post(
    f"/api/load?path=/tmp/nope.mky").status_code == 404)

# every shipped example must load with EXACT wire topology -- a desync means the file
# parser lost wires and the canvas would draw an incomplete model
ex = sorted(glob.glob(os.path.expanduser("~/minsky/examples/*.mky")))
bad, tested = [], 0
for f in ex:
    r = c.post(f"/api/load?path={f}")
    if r.status_code != 200:
        bad.append((os.path.basename(f), r.status_code)); continue
    tested += 1
    d = [w for w in r.json()["wires"] if w.get("desync")]
    if d: bad.append((os.path.basename(f), f"{d[0]['tracked']}/{d[0]['engine']}"))
check(f"all {tested} shipped examples load with exact topology", not bad,
      "" if not bad else f"failures: {bad[:4]}")

# upload round-trip
src = os.path.expanduser("~/minsky/examples/GoodwinLinear02.mky")
with open(src, "rb") as fh:
    up = c.post("/api/upload", files={"file": ("GoodwinLinear02.mky", fh, "application/xml")})
check("upload accepted", up.status_code == 200, str(up.status_code))
if up.status_code == 200:
    st = up.json()["state"]
    check("uploaded model has exact topology",
          not any(w.get("desync") for w in st["wires"]),
          f"{len(st['items'])} items, {len(st['wires'])} wires")
    check("group members marked read-only",
          any(i.get("readOnly") for i in st["items"]),
          f"{sum(1 for i in st['items'] if i.get('readOnly'))} nested items")
bad_up = c.post("/api/upload", files={"file": ("x.txt", b"nope", "text/plain")})
check("upload rejects non-.mky", bad_up.status_code == 422, str(bad_up.status_code))

print(f"\n{'ALL PASS' if not FAILED else 'FAILURES: ' + ', '.join(FAILED)}")
sys.exit(1 if FAILED else 0)
