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

print("\n9. save / save-as / download")
import os
c.post("/api/clear")
st = c.get("/api/state").json()
check("clean model is untitled and not dirty",
      st["currentFile"] is None and st["dirty"] is False)

r  = c.post("/api/item", json={"kind":"parameter","name":"c","value":2.5}).json()["index"]
ig = c.post("/api/item", json={"kind":"operation","op":"integrate"}).json()["index"]
c.post("/api/wire", json={"src":r,"dst":ig,"port":1})
c.post("/api/init", json={"name":"int1","value":7.0})
check("edits mark the model dirty", c.get("/api/state").json()["dirty"] is True)

check("plain Save with no file refuses",
      c.post("/api/save", json={}).status_code == 422)

sv = c.post("/api/save", json={"name":"roundtrip-test"})
check("Save As accepted", sv.status_code == 200, sv.text[:70])
saved = sv.json()["saved"]
check("saved under the writable dir", "minsky-models" in saved, saved)
st = c.get("/api/state").json()
check("saving clears dirty and names the file",
      st["dirty"] is False and st["currentFile"] == "roundtrip-test")

# writable roots are a SMALLER set than readable ones
check("refuses to overwrite a shipped example",
      c.post("/api/save", json={
          "name": os.path.expanduser("~/minsky/examples/Solow.mky")}).status_code == 403)
check("refuses to write outside the roots",
      c.post("/api/save", json={"name":"/etc/evil.mky"}).status_code == 403)

# edit again, plain Save should now work against the remembered path
c.post("/api/item", json={"kind":"operation","op":"time"})
check("re-dirtied after further edits", c.get("/api/state").json()["dirty"] is True)
check("plain Save works once a file is known",
      c.post("/api/save", json={}).status_code == 200)

# the round trip that matters: clear, reload, still exact and still runs
c.post("/api/clear")
check("cleared", c.get("/api/state").json()["currentFile"] is None)
ld = c.post(f"/api/load?path={saved}")
check("reopened the saved model", ld.status_code == 200, str(ld.status_code))
back = ld.json()
check("reopened topology is exact",
      not any(w.get("desync") for w in back["wires"]),
      f"{len(back['items'])} items, {len(back['wires'])} wires")
last = None
with c.websocket_connect("/ws/sim") as ws:
    ws.send_json({"cmd":"run","steps":600,"tmax":3.0})
    while True:
        msg = ws.receive_json()
        if "error" in msg: check("reopened model runs", False, msg["error"]); break
        if msg.get("done") or msg.get("stopped"): break
        last = msg
if last:
    t_, v = last["t"], last["values"][":int1"]
    check("reopened model integrates correctly", abs(v-(7.0+2.5*t_)) < 1e-6,
          f"t={t_:.4f} int1={v:.4f} expect {7.0+2.5*t_:.4f}")

dl = c.get("/api/download")
check("download returns a parseable .mky", dl.status_code == 200 and
      dl.content.lstrip().startswith(b"<Minsky"), f"{dl.status_code}, {dl.content[:24]!r}")
import xml.etree.ElementTree as _ET
try:
    _ET.fromstring(dl.content); ok_xml = True
except Exception: ok_xml = False
check("downloaded bytes parse as XML", ok_xml)

print("\n10. undo / redo")
c.post("/api/clear")
st = c.get("/api/state").json()
check("fresh model has nothing to undo",
      st["canUndo"] is False and st["canRedo"] is False)
check("undo with empty history is refused",
      c.post("/api/undo").status_code == 409)

r  = c.post("/api/item", json={"kind":"parameter","name":"c","value":2.5}).json()["index"]
ig = c.post("/api/item", json={"kind":"operation","op":"integrate"}).json()["index"]
st = c.post("/api/wire", json={"src":r,"dst":ig,"port":1}).json()
n_items, n_wires = len(st["items"]), len(st["wires"])
check("built 3 items + 1 wire", n_wires == 1, f"{n_items} items, {n_wires} wires")
check("canUndo is now true", c.get("/api/state").json()["canUndo"] is True)

# the wire must disappear from OUR record too, not just the engine's
u1 = c.post("/api/undo").json()
check("undo removes the wire", len(u1["wires"]) == 0, f"{len(u1['wires'])} wires")
check("no desync after undo",
      not any(w.get("desync") for w in u1["wires"]), str(u1["wires"])[:80])
u2 = c.post("/api/undo").json()
check("undo removes an item", len(u2["items"]) < n_items,
      f"{len(u2['items'])} items")
check("canRedo becomes true", u2["canRedo"] is True)

r1 = c.post("/api/redo").json()
r2 = c.post("/api/redo").json()
check("redo restores items and the wire",
      len(r2["items"]) == n_items and len(r2["wires"]) == n_wires,
      f"{len(r2['items'])} items, {len(r2['wires'])} wires")
check("no desync after redo",
      not any(w.get("desync") for w in r2["wires"]))

# and the restored model must still RUN -- a wire record that disagrees with the
# engine would produce a model that draws right and computes wrong
c.post("/api/init", json={"name":"int1","value":4.0})
last = None
with c.websocket_connect("/ws/sim") as ws:
    ws.send_json({"cmd":"run","steps":600,"tmax":2.0})
    while True:
        msg = ws.receive_json()
        if "error" in msg: check("model after redo runs", False, msg["error"]); break
        if msg.get("done") or msg.get("stopped"): break
        last = msg
if last:
    t_, v = last["t"], last["values"][":int1"]
    check("model after undo/redo integrates correctly", abs(v-(4.0+2.5*t_)) < 1e-6,
          f"t={t_:.4f} int1={v:.4f} expect {4.0+2.5*t_:.4f}")

# a new edit after undo must drop the redo tail
c.post("/api/undo")
c.post("/api/item", json={"kind":"operation","op":"time"})
check("new edit truncates the redo tail",
      c.get("/api/state").json()["canRedo"] is False)

# godley edits are undoable
c.post("/api/clear")
gi = c.post("/api/item", json={"kind":"godley"}).json()["index"]
c.post(f"/api/godley/{gi}/resize", json={"rows":3,"cols":3})
c.post(f"/api/godley/{gi}/cell", json={"row":0,"col":1,"value":"Reserves"})
c.post(f"/api/godley/{gi}/cell", json={"row":2,"col":1,"value":"Lend"})
check("godley cell set", c.get(f"/api/godley/{gi}").json()["cells"][2][1] == "Lend")
c.post("/api/undo")
check("godley cell edit undone",
      c.get(f"/api/godley/{gi}").json()["cells"][2][1] == "",
      repr(c.get(f"/api/godley/{gi}").json()["cells"][2][1]))

# loading resets the timeline
import os
c.post(f"/api/load?path={os.path.expanduser('~/minsky/examples/1Free.mky')}")
check("loading starts a fresh timeline",
      c.get("/api/state").json()["canUndo"] is False)

print("\n11. a saved model CONTAINING a Godley table reopens exactly")
# A Godley table's stock and flow variables are regenerated on load rather than stored,
# so the file has fewer items than the engine materialises. Requiring equal counts made
# the whole wire trace bail out and report zero wires -- found by using the app.
c.post("/api/clear")
p1 = c.post("/api/item", json={"kind":"parameter","name":"c","value":2.5}).json()["index"]
ig = c.post("/api/item", json={"kind":"operation","op":"integrate"}).json()["index"]
c.post("/api/wire", json={"src":p1,"dst":ig,"port":1})
gi = c.post("/api/item", json={"kind":"godley"}).json()["index"]
c.post(f"/api/godley/{gi}/resize", json={"rows":3,"cols":3})
for r,cc,v in ((0,1,"Reserves"),(0,2,"Deposits"),(1,0,"Initial Conditions"),
               (1,1,"100"),(1,2,"100"),(2,0,"Lending"),(2,1,"Lend"),(2,2,"Lend")):
    c.post(f"/api/godley/{gi}/cell", json={"row":r,"col":cc,"value":v})
saved = c.post("/api/save", json={"name":"godley-roundtrip"}).json()["saved"]
n_wires = len([w for w in c.get("/api/state").json()["wires"] if not w.get("desync")])
c.post("/api/clear")
back = c.post(f"/api/load?path={saved}").json()
check("godley model reopens with exact topology",
      not any(w.get("desync") for w in back["wires"]),
      f"{len(back['items'])} items, {len(back['wires'])} wires (saved with {n_wires})")
check("its wires survived", len(back["wires"]) == n_wires,
      f"{len(back['wires'])} vs {n_wires}")
g = c.get(f"/api/godley/{gi if gi < len(back['items']) else 0}").json()
check("its godley table survived", "Reserves" in str(g["cells"]), str(g["cells"][0])[:60])

print("\n12. item creation: messages and optional initial values")
c.post("/api/clear")
r = c.post("/api/item", json={"kind":"parameter","name":"p"})
check("missing value names the VALUE, not the name",
      r.status_code == 422 and "numeric value" in r.text, r.text[:70])
r = c.post("/api/item", json={"kind":"parameter","value":1.0})
check("missing name says so", r.status_code == 422 and "needs a name" in r.text,
      r.text[:60])
r = c.post("/api/item", json={"kind":"variable","var_type":"flow"})
check("variable without a name is refused",
      r.status_code == 422 and "needs a name" in r.text, r.text[:60])

# a stock may carry an optional initial value; a flow needs none
c.post("/api/clear")
c.post("/api/item", json={"kind":"variable","name":"S","var_type":"stock","value":42})
c.post("/api/item", json={"kind":"variable","name":"f","var_type":"flow"})
c.post("/api/reset")
vals = c.get("/api/state").json()["values"]
check("stock initial value applied", vals.get(":S") == 42.0, str(vals))
check("flow needs no value", ":f" in vals, str(vals))

# the same name twice is legitimate in Minsky: one variable, two icons
c.post("/api/clear")
c.post("/api/item", json={"kind":"parameter","name":"a","value":1.0})
st = c.post("/api/item", json={"kind":"parameter","name":"a","value":1.0}).json()["state"]
names = [i.get("name") for i in st["items"]]
check("a repeated name gives two icons, one variable",
      names.count("a") == 2 and len([k for k in st["values"] if k == ":a"]) == 1,
      f"icons={names} vars={list(st['values'])}")

print("\n13. a new Godley table is usable immediately")
c.post("/api/clear")
gi = c.post("/api/item", json={"kind":"godley"}).json()["index"]
g = c.get(f"/api/godley/{gi}").json()
n_ic = sum(1 for v in g["icRow"] if v)
check("a fresh table has a flow row to type into",
      g["rows"] - 1 - n_ic >= 1, f"{g['rows']} rows, {n_ic} initial-condition row(s)")
check("its columns are pre-classified",
      g["classes"][1:4] == ["asset","liability","equity"], str(g["classes"]))
check("the blank flow row balances", g["rowSums"][-1] == "0", repr(g["rowSums"]))

# and the seeded row is immediately usable end to end
for r,cc,v in ((0,1,"Reserves"),(0,2,"Deposits"),(1,1,"100"),(1,2,"100"),
               (2,0,"Lending"),(2,1,"Lend"),(2,2,"Lend")):
    assert c.post(f"/api/godley/{gi}/cell",
                  json={"row":r,"col":cc,"value":v}).status_code == 200, (r,cc)
g = c.get(f"/api/godley/{gi}").json()
check("filled straight in, with no extra rows added",
      all(v == "0" for v in g["rowSums"][1:]), repr(g["rowSums"]))
rate = c.post("/api/item", json={"kind":"parameter","name":"rate","value":5.0,
                                 "at":[140,420]}).json()["index"]
lend = c.post("/api/item", json={"kind":"variable","name":"Lend","var_type":"flow",
                                 "at":[420,420]}).json()["index"]
c.post("/api/wire", json={"src":rate,"dst":lend,"port":1})
last = None
with c.websocket_connect("/ws/sim") as ws:
    ws.send_json({"cmd":"run","steps":900,"tmax":3.0})
    while True:
        m = ws.receive_json()
        if "error" in m: check("seeded table runs", False, m["error"]); break
        if m.get("done") or m.get("stopped"): break
        last = m
if last:
    t_, R = last["t"], last["values"][":Reserves"]
    check("seeded table integrates correctly", abs(R-(100+5*t_)) < 1e-6,
          f"t={t_:.4f} Reserves={R:.4f} expect {100+5*t_:.4f}")

print("\n14. wires can be deleted, and a busy input says so")
c.post("/api/clear")
a = c.post("/api/item", json={"kind":"operation","op":"time"}).json()["index"]
b = c.post("/api/item", json={"kind":"variable","name":"y","var_type":"flow"}).json()["index"]
st = c.post("/api/wire", json={"src":a,"dst":b,"port":1}).json()
check("wired", len(st["wires"]) == 1)

dup = c.post("/api/wire", json={"src":a,"dst":b,"port":1})
check("a busy input is refused in plain language",
      dup.status_code == 409 and "already connected" in dup.text, dup.text[:80])
check("the refusal leaks no internals",
      "<?" not in dup.text and "expected 1" not in dup.text, dup.text[:80])

st = c.delete("/api/wire/0").json()
check("wire deleted", len(st["wires"]) == 0 and not any(w.get("desync") for w in st["wires"]),
      str(st["wires"]))
check("the input is free again",
      c.post("/api/wire", json={"src":a,"dst":b,"port":1}).status_code == 200)
check("out-of-range wire index refused",
      c.delete("/api/wire/9").status_code == 422)

# deleting a wire is undoable, and the topology comes back with it
st = c.delete("/api/wire/0").json()
check("deleted again", len(st["wires"]) == 0)
u = c.post("/api/undo").json()
check("undo restores the wire", len(u["wires"]) == 1 and not any(w.get("desync") for w in u["wires"]),
      str(u["wires"])[:80])

# and the restored wire still carries signal
c.post("/api/clear")
p1 = c.post("/api/item", json={"kind":"parameter","name":"k","value":3.0}).json()["index"]
ig = c.post("/api/item", json={"kind":"operation","op":"integrate"}).json()["index"]
c.post("/api/wire", json={"src":p1,"dst":ig,"port":1})
c.delete("/api/wire/0")
c.post("/api/undo")
c.post("/api/init", json={"name":"int1","value":0.0})
last = None
with c.websocket_connect("/ws/sim") as ws:
    ws.send_json({"cmd":"run","steps":600,"tmax":2.0})
    while True:
        m = ws.receive_json()
        if "error" in m: check("model runs after wire undo", False, m["error"]); break
        if m.get("done") or m.get("stopped"): break
        last = m
if last:
    t_, v = last["t"], last["values"][":int1"]
    check("a wire restored by undo still carries signal", abs(v - 3.0*t_) < 1e-6,
          f"t={t_:.4f} int1={v:.4f} expect {3.0*t_:.4f}")

print("\n15. wire deletion is exact or it refuses")
import os
# The invariant that matters is not how many delete, but that the engine and the tracked
# record never disagree. Deleting a top-level wire can take a group's internal wiring with
# it -- on GoodwinLinear02 the group's 8 wires once vanished across 16 deletions while the
# record kept them -- so the count spans wires inside groups and a cascade is rolled back.
c.post(f"/api/load?path={os.path.expanduser('~/minsky/examples/GoodwinLinear02.mky')}")
start = len([w for w in c.get("/api/state").json()["wires"] if not w.get("desync")])
deleted = refused = 0
desynced = False
for _ in range(80):
    st = c.get("/api/state").json()
    if any(w.get("desync") for w in st["wires"]): desynced = True; break
    live = [w for w in st["wires"] if not w.get("desync")]
    if not live: break
    moved = False
    for w in live:
        if c.delete(f"/api/wire/{w['index']}").status_code == 200:
            deleted += 1; moved = True; break
    if not moved: refused = len(live); break
check("the record never desynced while deleting", not desynced)
check("every wire either deleted or was refused", deleted + refused == start,
      f"{deleted} deleted + {refused} refused vs {start}")
check("most wires are deletable", deleted >= start * 0.8, f"{deleted}/{start}")
if refused:
    r = c.delete(f"/api/wire/0")
    check("a refusal explains itself and changes nothing",
          r.status_code == 400 and ("collapsed group" in r.text or "entangled" in r.text),
          r.text[:90])

# a model built by hand -- no groups, no plots -- deletes every wire
c.post("/api/clear")
ids = [c.post("/api/item", json=spec).json()["index"] for spec in (
    {"kind":"parameter","name":"a","value":1.0}, {"kind":"operation","op":"multiply"},
    {"kind":"operation","op":"integrate"}, {"kind":"parameter","name":"b","value":2.0})]
for s_, d_, p_ in ((ids[0],ids[1],1),(ids[3],ids[1],2),(ids[1],ids[2],1)):
    c.post("/api/wire", json={"src":s_,"dst":d_,"port":p_})
made = len([w for w in c.get("/api/state").json()["wires"] if not w.get("desync")])
gone = 0
while True:
    live = [w for w in c.get("/api/state").json()["wires"] if not w.get("desync")]
    if not live: break
    if c.delete(f"/api/wire/{live[0]['index']}").status_code != 200: break
    gone += 1
check("a hand-built model deletes every wire", gone == made and made == 3, f"{gone}/{made}")

print("\n16. Godley rows and columns can be removed, and removal is exact")
c.post("/api/clear")
gi = c.post("/api/item", json={"kind":"godley"}).json()["index"]
c.post(f"/api/godley/{gi}/resize", json={"rows":5,"cols":5})
for c_, lab in ((1,"A"),(2,"B"),(3,"C"),(4,"D")):
    c.post(f"/api/godley/{gi}/cell", json={"row":0,"col":c_,"value":lab})
for c_, cl in ((1,"asset"),(2,"liability"),(3,"equity"),(4,"asset")):
    c.post(f"/api/godley/{gi}/class", json={"col":c_,"cls":cl})
for r_, lab in ((2,"ROW2"),(3,"ROW3"),(4,"ROW4")):
    c.post(f"/api/godley/{gi}/cell", json={"row":r_,"col":0,"value":lab})

# rows: the engine's deleteRow is correct and 0-based
g = c.post(f"/api/godley/{gi}/row/delete", json={"at":3}).json()
check("the requested row is the one removed",
      [row[0] for row in g["cells"]] == ["", "Initial Conditions", "ROW2", "ROW4"],
      str([row[0] for row in g["cells"]]))

# columns: the engine's deleteCol swaps the LAST column into the gap and sometimes does
# not shrink at all, so removal is done by rewriting the grid
g = c.post(f"/api/godley/{gi}/col/delete", json={"at":2}).json()
check("the requested column is the one removed",
      g["cells"][0] == ["", "A", "C", "D"], str(g["cells"][0]))
check("later columns shift left rather than being swapped",
      g["cols"] == 4, f"{g['cols']} cols")
check("each surviving column keeps its own asset class",
      g["classes"] == ["noAssetClass","asset","equity","asset"], str(g["classes"]))

check("column 0 cannot be removed",
      c.post(f"/api/godley/{gi}/col/delete", json={"at":0}).status_code == 422)
check("row 0 cannot be removed",
      c.post(f"/api/godley/{gi}/row/delete", json={"at":0}).status_code == 422)

# down to a single stock column, removal stops
c.post(f"/api/godley/{gi}/col/delete", json={"at":3})
c.post(f"/api/godley/{gi}/col/delete", json={"at":2})
last = c.post(f"/api/godley/{gi}/col/delete", json={"at":1})
check("the last stock column is protected", last.status_code == 422, last.text[:70])

# a table survives removal and still runs
c.post("/api/clear")
gi = c.post("/api/item", json={"kind":"godley"}).json()["index"]
c.post(f"/api/godley/{gi}/resize", json={"rows":3,"cols":5})
for r_,c_,v in ((0,1,"Reserves"),(0,2,"Junk"),(0,3,"Deposits"),
                (1,0,"Initial Conditions"),(1,1,"100"),(1,3,"100"),
                (2,0,"Lending"),(2,1,"Lend"),(2,3,"Lend")):
    c.post(f"/api/godley/{gi}/cell", json={"row":r_,"col":c_,"value":v})
c.post(f"/api/godley/{gi}/class", json={"col":3,"cls":"liability"})
c.post(f"/api/godley/{gi}/col/delete", json={"at":2})          # drop the unused middle
g = c.get(f"/api/godley/{gi}").json()
check("balance survives the removal", all(v == "0" for v in g["rowSums"][1:]),
      f"{g['cells'][0]} sums={g['rowSums']}")
rate = c.post("/api/item", json={"kind":"parameter","name":"rate","value":5.0,
                                 "at":[140,420]}).json()["index"]
lend = c.post("/api/item", json={"kind":"variable","name":"Lend","var_type":"flow",
                                 "at":[420,420]}).json()["index"]
c.post("/api/wire", json={"src":rate,"dst":lend,"port":1})
last = None
with c.websocket_connect("/ws/sim") as ws:
    ws.send_json({"cmd":"run","steps":900,"tmax":2.0})
    while True:
        m = ws.receive_json()
        if "error" in m: check("runs after column removal", False, m["error"]); break
        if m.get("done") or m.get("stopped"): break
        last = m
if last:
    t_, R = last["t"], last["values"][":Reserves"]
    check("still integrates after column removal", abs(R-(100+5*t_)) < 1e-6,
          f"t={t_:.4f} Reserves={R:.4f} expect {100+5*t_:.4f}")

print("\n17. solver settings: applied or refused, never silently dropped")
c.post("/api/clear")
# A client computing parseFloat("abc") sends null. Dropping it silently meant the solver
# kept its old value while the field on screen showed the new one.
r = c.post("/api/solver", json={"epsRel": None})
check("an explicit null is refused", r.status_code == 422 and "not a number" in r.text,
      r.text[:70])
check("the refusal names the field", "epsRel" in r.text, r.text[:70])
check("omitting a field is still fine",
      c.post("/api/solver", json={"order": 2}).status_code == 200)

c.post("/api/solver", json={"epsRel": 1e-7, "epsAbs": 1e-9, "order": 2, "implicit": False})
sv = c.get("/api/state").json()["solver"]
check("valid settings are applied",
      sv["epsRel"] == 1e-7 and sv["order"] == 2 and sv["implicit"] is False, str(sv))

# a bad value must not leave a partially applied solver
c.post("/api/solver", json={"epsRel": 1e-8, "order": 4})
before = c.get("/api/state").json()["solver"]
c.post("/api/solver", json={"epsRel": 1e-6, "epsAbs": None})
after = c.get("/api/state").json()["solver"]
check("a rejected request changes nothing", before == after,
      f"{before} vs {after}")

print(f"\n{'ALL PASS' if not FAILED else 'FAILURES: ' + ', '.join(FAILED)}")
sys.exit(1 if FAILED else 0)
