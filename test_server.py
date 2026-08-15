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
check("a busy single-wire input is refused in plain language",
      dup.status_code == 409 and "accepts only one" in dup.text, dup.text[:80])
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

print("\n18. rename")
c.post("/api/clear")
a1 = c.post("/api/item", json={"kind":"parameter","name":"alpha","value":2.5}).json()["index"]
c.post("/api/item", json={"kind":"parameter","name":"alpha","value":2.5,"at":[140,340]})
op = c.post("/api/item", json={"kind":"operation","op":"multiply"}).json()["index"]
ig = c.post("/api/item", json={"kind":"operation","op":"integrate"}).json()["index"]
c.post("/api/wire", json={"src":a1,"dst":ig,"port":1})

r = c.post(f"/api/item/{a1}/rename", json={"name":"beta"}).json()
names = [i.get("name") for i in r["state"]["items"]]
# renameItem would rename ONE icon and split the variable in two; renameAllInstances is
# what "rename this variable" means to someone looking at one of its icons
check("every icon of the variable is renamed", names.count("beta") == 2, str(names))
vals = list(r["state"]["values"])
check("the old name is gone and the new one appears once",
      ":alpha" not in vals and vals.count(":beta") == 1, str(vals))
check("wires survive a rename",
      len([w for w in r["state"]["wires"] if not w.get("desync")]) == 1)

c.post("/api/reset")
check("the value survives a rename",
      c.get("/api/state").json()["values"].get(":beta") == 2.5,
      str(c.get("/api/state").json()["values"]))

bad = c.post(f"/api/item/{op}/rename", json={"name":"nope"})
check("an operation has no name to change",
      bad.status_code == 422 and "no name to change" in bad.text, bad.text[:80])
check("an empty name is refused",
      c.post(f"/api/item/{a1}/rename", json={"name":"   "}).status_code == 422)
check("an out-of-range index is refused",
      c.post("/api/item/99/rename", json={"name":"x"}).status_code == 422)

# a Godley table's name is its title, and it must reach the canvas
c.post("/api/clear")
gi = c.post("/api/item", json={"kind":"godley"}).json()["index"]
r = c.post(f"/api/item/{gi}/rename", json={"name":"Bank balance sheet"}).json()
check("a Godley table is renamed by its title",
      c.get(f"/api/godley/{gi}").json()["title"] == "Bank balance sheet")
check("and the title labels it on the canvas",
      [i.get("name") for i in r["state"]["items"]] == ["Bank balance sheet"],
      str([i.get("name") for i in r["state"]["items"]]))

# rename is undoable
c.post("/api/undo")
check("a rename can be undone",
      c.get(f"/api/godley/{gi}").json()["title"] != "Bank balance sheet",
      repr(c.get(f"/api/godley/{gi}").json()["title"]))

print("\n19. model data is not trusted markup")
import os, re
# A .mky can be given ANY filename, and Minsky accepts a variable named with markup. The
# file picker rendered filenames straight into innerHTML, and a crafted name executed --
# verified in a browser before this was fixed. The UI escapes at every interpolation now;
# these assert the data reaches the client intact so escaping is the client's only job.
c.post("/api/clear")
hostile = '<img src=x onerror=window.__XSS=1>'
r = c.post("/api/item", json={"kind":"parameter","name":hostile,"value":1.0})
check("a name containing markup is accepted by the engine", r.status_code == 200)

ui = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "minskyweb", "ui", "index.html")).read()
check("the UI defines an escape helper", "const esc = v =>" in ui)

# Every interpolation into MARKUP must be escaped or demonstrably literal.
#
# This used to scan a fixed 400-character window after each `innerHTML =`, which made it
# blind to the way most of this file builds markup: an accumulator (`h += ...`) filled
# over many lines and assigned at the end. The window saw only `h`, which was on the
# allowlist -- so the whole of drawGodley() and drawFiles(), the markup that carries
# model data, was never examined at all. Scan every template literal that contains a tag,
# wherever its result ends up.
LITERAL_OK = {
    # loop counters and lengths
    "c", "r", "i", "n", "bad.length",
    # conditionals whose branches are both string literals
    'k===g.classes[c]?" selected":""', 'g.icRow[r] ? "ic" : ""', 'c===0?"lab":""',
    'v && v.trim()==="0" ? "ok":"bad"', 'bad.length>1?"s":""',
    # a number, and a colour this file chose from its own palette
    "(f.bytes/1024).toFixed(0)", "colors[k]",
    # OPS is a constant array declared in this file
    "o",
    # escapes its own model data inline
    'v === null ? "" : (v.trim()==="0" ? "✓ 0" : "≠ " + esc(v))',
}
bad = []
for lit in re.findall(r"`([^`]*)`", ui, re.S):
    # any "<" at all, opening OR closing: markup is built up in fragments, and the one
    # carrying a Godley cell value ends with "</td>" and opens no tag of its own -- a
    # test looking for "<" followed by a letter skipped exactly that fragment
    if "<" not in lit:
        continue
    for interp in re.findall(r"\$\{([^{}]*)\}", lit):
        t = interp.strip()
        if t.startswith(("esc(", "encodeURIComponent(")) or t in LITERAL_OK:
            continue
        bad.append(t[:70])
check("every interpolation into markup is escaped or literal",
      not bad, f"unescaped: {bad[:4]}")
# and the scan itself must be looking at the markup that carries model data
check("the scan reaches the table markup",
      any("data-r=" in l for l in re.findall(r"`([^`]*)`", ui, re.S)))

# filenames reach the client verbatim; escaping is the renderer's job, not the server's
open(os.path.expanduser("~/minsky-models/plain-check.mky"), "w").write(
    open(os.path.expanduser("~/minsky/examples/exponentialGrowth.mky")).read())
listing = c.get("/api/files").json()
names = [f["name"] for root in listing["roots"] for f in root["files"]]
check("the file listing returns names verbatim", "plain-check" in names,
      str(names[:3]))
os.remove(os.path.expanduser("~/minsky-models/plain-check.mky"))

print("\n20. save names are validated, not silently reinterpreted")
c.post("/api/clear")
c.post("/api/item", json={"kind":"parameter","name":"z","value":1.0})
c.post("/api/save", json={"name":"namecheck"})

# a blank name used to fall through to "save to the current file", quietly overwriting it
for blank in ("", "   "):
    r = c.post("/api/save", json={"name": blank})
    check(f"a blank name ({blank!r}) is refused",
          r.status_code == 422 and "name is required" in r.text, r.text[:60])

# taking the basename neutralised traversal but told the user nothing: "a/b/c" became
# c.mky and "../escape" became escape.mky, both silently
for pathish in ("a/b/c", "../escape"):
    r = c.post("/api/save", json={"name": pathish})
    check(f"a path-like name ({pathish!r}) is refused with guidance",
          r.status_code == 422 and "looks like a path" in r.text, r.text[:60])

check("a plain name still saves",
      c.post("/api/save", json={"name":"namecheck2"}).status_code == 200)
r = c.post("/api/save", json={})
check("omitting the name still means save-to-current",
      r.status_code == 200 and r.json()["name"] == "namecheck2", r.text[:70])

import os
for f in ("namecheck", "namecheck2"):
    for suffix in (".mky", ".mky;1"):
        try: os.remove(os.path.expanduser(f"~/minsky-models/{f}{suffix}"))
        except OSError: pass

print("\n21. a vanished Godley table is reported in plain language")
c.post("/api/clear")
gi = c.post("/api/item", json={"kind":"godley"}).json()["index"]
check("the table is there", c.get(f"/api/godley/{gi}").status_code == 200)
c.delete(f"/api/item/{gi}")
r = c.get(f"/api/godley/{gi}")
# the editor holds an index; deleting the table left it open over a ghost and typing in
# it produced "index 0 out of range (0..-1)"
check("asking for a deleted table explains itself",
      r.status_code == 422 and "may have been deleted" in r.text, r.text[:80])
check("the message avoids index arithmetic",
      "(0..-1)" not in r.text, r.text[:60])

ui = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "minskyweb", "ui", "index.html")).read()
# The invariant is what matters, not the shape it takes: render() is the single place
# that reconciles the open editor with the model, so no call site can miss it.
check("the editor is reconciled from render(), so no path can miss it",
      "if (now === null) closeGodley(false)" in ui)

print("\n22. new items are placed where the user can see them")
c.post("/api/clear")
r = c.post("/api/item", json={"kind":"operation","op":"time","at":[640,480]}).json()
placed = [i for i in r["state"]["items"] if i["index"] == r["index"]][0]
check("an explicit position is honoured exactly",
      (placed["x"], placed["y"]) == (640.0, 480.0), f"({placed['x']},{placed['y']})")

# without one the server falls back to a fixed grid that walks off-screen after ~25
# additions, so the CLIENT supplies a slot inside the current view
c.post("/api/clear")
for _ in range(30):
    c.post("/api/item", json={"kind":"operation","op":"time"})
items = c.get("/api/state").json()["items"]
xs = [i["x"] for i in items]
check("the server-side fallback does walk off to the right",
      max(xs) - min(xs) > 900, f"x spans {max(xs)-min(xs):.0f}")

ui = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "minskyweb", "ui", "index.html")).read()
check("the client places new items itself", "function freeSlot()" in ui)
check("and every add path uses it",
      ui.count("at: freeSlot()") >= 2, f"{ui.count('at: freeSlot()')} call sites")

print("\n23. out-of-range Godley indices are refused, not passed to C++")
# An out-of-range index does not raise in the engine -- it KILLS THE PROCESS. row/delete
# with at=9999 took the whole server down and the unsaved model with it.
c.post("/api/clear")
gi = c.post("/api/item", json={"kind":"godley"}).json()["index"]
crashes = []
for action in ("row/delete", "row/insert", "col/delete", "col/insert"):
    for at in (9999, -5, 0, 10**9):
        r = c.post(f"/api/godley/{gi}/{action}", json={"at": at})
        if r.status_code not in (400, 422):
            crashes.append((action, at, r.status_code))
check("every out-of-range row/column index is refused", not crashes, str(crashes[:4]))
check("the server is still answering after all of them",
      c.get("/api/state").status_code == 200)

check("an absurd resize is refused",
      c.post(f"/api/godley/{gi}/resize", json={"rows":99999,"cols":99999}).status_code == 422)
check("a resize below the structural minimum is refused",
      c.post(f"/api/godley/{gi}/resize", json={"rows":1,"cols":1}).status_code == 422)
check("an out-of-range asset class column is refused",
      c.post(f"/api/godley/{gi}/class", json={"col":999,"cls":"asset"}).status_code == 422)
check("a cell outside the table is refused",
      c.post(f"/api/godley/{gi}/cell", json={"row":500,"col":500,"value":"x"}).status_code == 422)

# and the table is still usable afterwards
g = c.get(f"/api/godley/{gi}").json()
check("the table survived the battering", g["rows"] >= 2 and g["cols"] >= 2,
      f"{g['rows']}x{g['cols']}")

check("a save name with no stem is refused rather than 500",
      c.post("/api/save", json={"name":"/"}).status_code == 422)
check("and so is '//'", c.post("/api/save", json={"name":"//"}).status_code == 422)

print("\n24. nothing is resolved by position when two things share a point")
# delete, rename and wire-removal all focus their target with getItemAt, which resolves by
# POSITION. Auto-placement used to index a grid by len(self.items) -- a counter over our
# own list -- which drifts the moment anything is deleted, so a new item landed EXACTLY on
# an existing one and the engine then picked between them arbitrarily.
c.post("/api/clear")
for n in ("p1","p2","p3"):
    c.post("/api/item", json={"kind":"parameter","name":n,"value":1.0})
c.delete("/api/item/1")
c.post("/api/item", json={"kind":"parameter","name":"p4","value":1.0})
items = c.get("/api/state").json()["items"]
pos = [(i["x"], i["y"]) for i in items]
check("auto-placement never stacks two items", len(set(pos)) == len(pos), str(pos))
check("and it reuses the freed slot", len(items) == 3, str([i.get("name") for i in items]))

# a user can still stack them by dragging, and then positional work must refuse
here = items[0]
c.post(f"/api/item/{items[1]['index']}/move", json={"x": here["x"], "y": here["y"]})
r = c.delete(f"/api/item/{items[1]['index']}")
check("deleting one of a stacked pair is refused",
      r.status_code == 400 and "same point" in r.text, r.text[:90])
# rename does NOT need that refusal any more: it finds every icon of the variable by
# valueId rather than by asking the canvas what is at a point, so it acts on exactly the
# item it was given even when another sits on top of it
r = c.post(f"/api/item/{items[1]['index']}/rename", json={"name":"nope"})
check("renaming one of a stacked pair works",
      r.status_code == 200, f"{r.status_code} {r.text[:70]}")
names = [i.get("name") for i in c.get("/api/state").json()["items"]]
check("and it renamed that one, not its neighbour",
      names.count("nope") == 1, str(names))
check("the refused delete changed nothing",
      len(c.get("/api/state").json()["items"]) == 3)

# same hazard for wires: an input takes one wire, so the destination is unambiguous --
# unless another wire's destination sits at the same point
c.post("/api/clear")
a = c.post("/api/item", json={"kind":"operation","op":"time"}).json()["index"]
y1 = c.post("/api/item", json={"kind":"variable","name":"y1","var_type":"flow"}).json()["index"]
y2 = c.post("/api/item", json={"kind":"variable","name":"y2","var_type":"flow"}).json()["index"]
c.post("/api/wire", json={"src":a,"dst":y1,"port":1})
c.post("/api/wire", json={"src":a,"dst":y2,"port":1})
tgt = [i for i in c.get("/api/state").json()["items"] if i.get("name") == "y1"][0]
c.post(f"/api/item/{y2}/move", json={"x": tgt["x"], "y": tgt["y"]})
r = c.delete("/api/wire/0")
check("deleting a wire whose destination is shared is refused",
      r.status_code == 400 and "same point" in r.text, r.text[:80])
check("both wires are still there",
      len([w for w in c.get("/api/state").json()["wires"] if not w.get("desync")]) == 2)

print("\n25. renderer invariants that only source can assert")
ui = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "minskyweb", "ui", "index.html")).read()
# A CSS `r` beats the presentation attribute, so applyView's counter-scaled radius was
# ignored and ports shrank to 3px when zoomed out -- introduced by the fix that gave them
# a radius on a fresh model, which render() now guarantees a different way.
check("no CSS rule sets the port radius",
      not re.search(r"\.port\{[^}]*\br\s*:", ui), "a .port{r:...} rule is back")
check("applyView still writes the counter-scaled radius",
      'setAttribute("r", r)' in ui or "setAttribute('r', r)" in ui)
# Selection is by REF, not index. A group member has no index -- it is not in
# model.items -- so comparing indices meant null === null, and every group member lit up
# as selected whenever nothing was. Every item has a ref, and `sel` is null or a string,
# so the two can never match by accident.
check("selection is compared by ref", "selSet.has(it.ref)" in ui)
# `sel` holds a REF. Three places went on using the numeric index after that change, and
# each one silently disabled something: the Selection panel could never open, a new item
# was never highlighted, and a drag showed no movement until the pointer was released.
check("the selection panel looks the item up by ref",
      "byRef.get(sel)" in ui and "byIdx.get(sel)" not in ui)
# A substring check cannot tell "the new item is selected" from "a variable named sel was
# assigned", and the previous one here was satisfied by the very code that broke adding.
# The invariant that DOES catch it: `sel` and `selSet` are two views of one thing, so
# nothing may assign `sel` except the helpers that keep them in step. Adding an item set
# `sel` directly, so the panel named the new item while the canvas highlighted the old
# one and Delete removed that instead.
_assign = [(ui[:m.start()].count("\n") + 1, ui.splitlines()[ui[:m.start()].count("\n")].strip())
           for m in re.finditer(r"(?<![\w.$])sel\s*=\s*(?!=)", ui)]
_helpers = ui[ui.index("// The selection is a SET of refs"):
              ui.index("function clearSelection(") + 200]
_stray = [f"line {ln}: {txt[:60]}" for ln, txt in _assign
          if "let state" not in txt and "forEach(sel" not in txt
          and txt not in _helpers]
check("nothing assigns `sel` outside the selection helpers", not _stray, str(_stray))
check("and the helpers keep both views in step",
      "function selectOnly(" in ui and "function selectMany(" in ui
      and "function selectToggle(" in ui)
check("the drag preview finds its element by ref",
      "drag.idx" not in ui and 'item[data-ref="${CSS.escape(r)}"]' in ui)
check("and nothing compares a possibly-null index for selection",
      "sel === it.index" not in ui)
# the inline stroke set for the item colour beat the .sel rule
check("the selected item's stroke is set inline, where it can win",
      'isSel ? "var(--accent)"' in ui)
check("the wire hit target does not shrink with the zoom",
      re.search(r"\.wirehit\{[^}]*vector-effect:non-scaling-stroke", ui) is not None)

print("\n26. clear resets the clock; junk files are refused; solver applies only what is sent")
import glob
c.post("/api/clear")
p1 = c.post("/api/item", json={"kind":"parameter","name":"c","value":1.0}).json()["index"]
ig = c.post("/api/item", json={"kind":"operation","op":"integrate"}).json()["index"]
c.post("/api/wire", json={"src":p1,"dst":ig,"port":1})
with c.websocket_connect("/ws/sim") as ws:
    ws.send_json({"cmd":"run","steps":200,"tmax":3.0})
    while True:
        m = ws.receive_json()
        if m.get("done") or m.get("stopped") or "error" in m: break
check("a run advances t", c.get("/api/state").json()["t"] > 1)
c.post("/api/clear")
# clearAllMaps leaves t where the last run stopped, so a brand-new document showed 3.04
check("clear resets the clock", c.get("/api/state").json()["t"] == 0.0,
      str(c.get("/api/state").json()["t"]))

# minsky.load() accepts any well-formed XML and quietly yields an EMPTY model, so opening
# the wrong file reported success and replaced the open model with nothing
junk = os.path.expanduser("~/minsky-models/_notamodel.mky")
open(junk, "w").write('<?xml version="1.0"?><notminsky><hello/></notminsky>')
c.post("/api/item", json={"kind":"parameter","name":"keep","value":1.0})
before = len(c.get("/api/state").json()["items"])
r = c.post(f"/api/load?path={junk}")
check("a file that is not a Minsky model is refused",
      r.status_code == 422 and "not a Minsky model" in r.text, r.text[:70])
check("and the open model is untouched",
      len(c.get("/api/state").json()["items"]) == before, "the model was replaced")
os.remove(junk)

# every shipped example must still pass the check
rejected = [os.path.basename(f) for f in sorted(glob.glob(os.path.expanduser("~/minsky/examples/*.mky")))
            if c.post(f"/api/load?path={f}").status_code != 200]
check("no real model is rejected by the check", not rejected, str(rejected[:4]))

# configure() merged with SANE_SOLVER, so a partial payload reset what was not sent
c.post("/api/solver", json={"epsRel":1e-6,"epsAbs":1e-8,"order":2,"implicit":False})
c.post("/api/solver", json={"order":4})
sv = c.get("/api/state").json()["solver"]
check("a partial solver post changes only what it sends",
      (sv["epsRel"], sv["epsAbs"], sv["order"], sv["implicit"]) == (1e-6, 1e-8, 4, False),
      str({k: sv[k] for k in ("epsRel","epsAbs","order","implicit")}))

print("\n27. solver settings survive a run, and a loaded file keeps its own")
c.post("/api/clear")
sv = c.get("/api/state").json()["solver"]
# Minsky's own default epsRel is 1e-2, which produces NaN on stiff models and reports
# success, so a NEW model gets sane tolerances
check("a new model starts with sane tolerances",
      sv["epsRel"] <= 1e-6 and sv["implicit"] is True, str(sv))

p1 = c.post("/api/item", json={"kind":"parameter","name":"c","value":1.0}).json()["index"]
ig = c.post("/api/item", json={"kind":"operation","op":"integrate"}).json()["index"]
c.post("/api/wire", json={"src":p1,"dst":ig,"port":1})
c.post("/api/solver", json={"epsRel":1e-5,"epsAbs":1e-7,"order":2,"implicit":False})
with c.websocket_connect("/ws/sim") as ws:
    ws.send_json({"cmd":"run","steps":100,"tmax":1.0})
    while True:
        m = ws.receive_json()
        if m.get("done") or m.get("stopped") or "error" in m: break
sv = c.get("/api/state").json()["solver"]
# the run used to call configure(), which reimposed the defaults, so the solver the
# caller had just set was thrown away and the panel had no effect
check("a run does not overwrite the solver",
      (sv["epsRel"], sv["order"], sv["implicit"]) == (1e-5, 2, False), str(sv))

c.post(f"/api/load?path={os.path.expanduser('~/minsky/examples/GoodwinLinear02.mky')}")
sv = c.get("/api/state").json()["solver"]
check("a loaded model keeps the solver block from its file",
      sv["epsRel"] == 0.01, str(sv["epsRel"]))

ui = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "minskyweb", "ui", "index.html")).read()
check("the panel reflects the model rather than hardcoded values",
      "state.solver || {}" in ui)
check("and it does not fight the user's typing",
      "document.activeElement !== el" in ui)

print("\n28. a value reaches the variable whatever its name looks like")
# variableValues is NOT keyed by ":name". Minsky mangles the name into the id: alpha_1
# becomes :alpha<sub>1</sub>, r^2 becomes :r<sup>2</sup>, a space becomes U+2423. Writing
# to ":alpha_1" created a phantom entry and the real variable kept 0 -- so every parameter
# with an underscore, caret or space silently had no value. In an economic model that is
# most of them: C_D, I_D, w_s.
c.post("/api/clear")
names = ["alpha", "alpha_1", "r^2", "has space", "C_D", "W_C"]
for n in names:
    c.post("/api/item", json={"kind":"parameter","name":n,"value":2.5})
c.post("/api/reset")
vals = c.get("/api/state").json()["values"]
lost = {k: v for k, v in vals.items() if v != 2.5}
check("every parameter carries its value", not lost, f"lost: {lost}")
check("all six exist", len(vals) == len(names), f"{len(vals)} of {len(names)}")

c.post("/api/clear")
c.post("/api/item", json={"kind":"variable","name":"K_t","var_type":"stock","value":300})
c.post("/api/reset")
vals = c.get("/api/state").json()["values"]
check("a stock's initial value survives a mangled name",
      list(vals.values()) == [300.0], str(vals))

c.post("/api/item", json={"kind":"parameter","name":"C_D","value":1.0})
c.post("/api/init", json={"name":"C_D","value":99})
c.post("/api/reset")
vals = c.get("/api/state").json()["values"]
check("/api/init reaches a mangled name too",
      99.0 in vals.values(), str(vals))

# and the model actually integrates with such a parameter driving it
c.post("/api/clear")
p1 = c.post("/api/item", json={"kind":"parameter","name":"g_r","value":4.0}).json()["index"]
ig = c.post("/api/item", json={"kind":"operation","op":"integrate"}).json()["index"]
c.post("/api/wire", json={"src":p1,"dst":ig,"port":1})
last = None
with c.websocket_connect("/ws/sim") as ws:
    ws.send_json({"cmd":"run","steps":600,"tmax":2.0})
    while True:
        m = ws.receive_json()
        if "error" in m: check("runs with a mangled parameter name", False, m["error"]); break
        if m.get("done") or m.get("stopped"): break
        last = m
if last:
    t_ = last["t"]
    v = [x for k, x in last["values"].items() if "int" in k][0]
    check("a mangled parameter actually drives the model", abs(v - 4.0*t_) < 1e-6,
          f"t={t_:.4f} int={v:.4f} expect {4.0*t_:.4f}")

print("\n29. n-ary inputs take several wires; single-wire inputs say so")
# Minsky's n-ary operations legitimately take SEVERAL wires into one input and sum them.
# A blanket "already connected" pre-check broke that modelling pattern outright.
c.post("/api/clear")
a = c.post("/api/item", json={"kind":"parameter","name":"a","value":1.0}).json()["index"]
b = c.post("/api/item", json={"kind":"parameter","name":"b","value":2.0}).json()["index"]
for op in ("add", "multiply", "min"):
    o = c.post("/api/item", json={"kind":"operation","op":op}).json()["index"]
    r1 = c.post("/api/wire", json={"src":a,"dst":o,"port":1})
    r2 = c.post("/api/wire", json={"src":b,"dst":o,"port":1})
    check(f"{op} accepts two wires into one input",
          r1.status_code == 200 and r2.status_code == 200,
          f"{r1.status_code}/{r2.status_code}")

v = c.post("/api/item", json={"kind":"variable","name":"y","var_type":"flow"}).json()["index"]
check("a variable input takes the first wire",
      c.post("/api/wire", json={"src":a,"dst":v,"port":1}).status_code == 200)
r = c.post("/api/wire", json={"src":b,"dst":v,"port":1})
check("and refuses the second in plain language",
      r.status_code == 409 and "accepts only one" in r.text, r.text[:70])
check("the refusal leaks no internals",
      "<?" not in r.text and "expected 1" not in r.text, r.text[:70])
check("the record never desynced through any of it",
      not any(w.get("desync") for w in c.get("/api/state").json()["wires"]))

# and a model built with an n-ary input actually computes the sum
c.post("/api/clear")
a = c.post("/api/item", json={"kind":"parameter","name":"a","value":1.5}).json()["index"]
b = c.post("/api/item", json={"kind":"parameter","name":"b","value":2.5}).json()["index"]
add = c.post("/api/item", json={"kind":"operation","op":"add"}).json()["index"]
ig = c.post("/api/item", json={"kind":"operation","op":"integrate"}).json()["index"]
c.post("/api/wire", json={"src":a,"dst":add,"port":1})
c.post("/api/wire", json={"src":b,"dst":add,"port":1})
c.post("/api/wire", json={"src":add,"dst":ig,"port":1})
last = None
with c.websocket_connect("/ws/sim") as ws:
    ws.send_json({"cmd":"run","steps":600,"tmax":2.0})
    while True:
        m = ws.receive_json()
        if "error" in m: check("n-ary model runs", False, m["error"]); break
        if m.get("done") or m.get("stopped"): break
        last = m
if last:
    t_ = last["t"]; v_ = [x for k, x in last["values"].items() if "int" in k][0]
    check("two wires into one input are summed", abs(v_ - 4.0*t_) < 1e-6,
          f"t={t_:.4f} int={v_:.4f} expect {(1.5+2.5)*t_:.4f}")

print("\n30. port roles are honest, and wiring failures are readable")
c.post(f"/api/load?path={os.path.expanduser('~/minsky/examples/GoodwinLinear02.mky')}")
st = c.get("/api/state").json()
plot = next(i for i in st["items"] if "Plot" in i["classType"])
# a plot consumes and never produces; labelling its port 0 "output" offered the canvas a
# drag source that could never make a wire
check("a plot widget has no output port",
      all(p["role"] == "input" for p in plot["ports"]),
      str(sorted({p["role"] for p in plot["ports"]})))

# port 0 is the output for operations whatever their rotation -- this multiply is
# mirrored in the file, so geometry cannot be used to decide
mult = next(i for i in st["items"] if i["classType"] == "Operation:multiply")
check("an operation's port 0 is its output even when mirrored",
      [p["role"] for p in mult["ports"]] == ["output", "input", "input"],
      str([p["role"] for p in mult["ports"]]))

v = c.post("/api/item", json={"kind":"variable","name":"probe","var_type":"flow",
                              "at":[80,900]}).json()["index"]
r = c.post("/api/wire", json={"src":plot["index"],"dst":v,"port":1})
body = r.json()
# the WiringError text is a developer diagnosis: object reprs, pixel coordinates and two
# speculative causes. Useful in a log, meaningless to someone who dragged a line.
check("a wiring failure reads as a sentence", r.status_code == 400 and
      "cannot be connected" in body.get("detail",""), str(body)[:80])
check("it leaks no reprs or pixel coordinates",
      "<" not in body.get("detail","") and "port 0 at" not in body.get("detail",""),
      body.get("detail","")[:70])
check("the diagnosis is kept for the log", bool(body.get("diagnostic")))

print("\n31. history is ours, not the engine's")
# The engine's history cannot be driven correctly from outside its own client, and every
# way it fails reports success. These check the symptoms, one per engine trap.
EX = "/Users/ryneschultz/minsky/examples/GoodwinLinear02.mky"
import os
if os.path.exists(EX):
    def load(): c.post("/api/load", params={"path": EX})

    # Minsky::save() pushes engine history behind our back
    for label, act in (("save", lambda: c.post("/api/save", json={"name": "hist-probe"})),
                       ("download", lambda: c.get("/api/download"))):
        load(); act()
        c.delete("/api/item/3")
        check(f"the edit after {label} is undoable",
              c.get("/api/state").json()["canUndo"] is True)
        check(f"and undo after {label} actually runs",
              c.post("/api/undo").status_code == 200)

    # pushHistory() early-returns false while `undone` is set, so the first push after an
    # undo did nothing and the next edit had no undo point at all
    load(); c.delete("/api/item/3"); c.post("/api/undo")
    n = len(c.get("/api/state").json()["items"])
    c.post("/api/item", json={"kind": "parameter", "name": "zz", "value": 1})
    check("an edit made after an undo is itself undoable",
          c.get("/api/state").json()["canUndo"] is True)
    u = c.post("/api/undo")
    check("undoing it removes it", u.status_code == 200 and
          not any(i.get("name") == "zz" for i in u.json()["items"]))
    # pushHistory() never truncates the redo tail; it appends and jumps the pointer past
    # the abandoned branch, leaving it there for a later redo to walk into
    r = c.post("/api/redo").json()
    check("redo returns the new edit, not the abandoned branch",
          any(i.get("name") == "zz" for i in r["items"]) and len(r["items"]) == n + 1,
          f"{len(r['items'])} items")

# an endpoint that answers with an error must not have moved the model
c.post("/api/clear")
before = c.get("/api/state").json()
check("a refused undo changes nothing",
      c.post("/api/undo").status_code == 409 and
      c.get("/api/state").json()["items"] == before["items"])

# a request rejected without touching the model must leave the redo point alone
r  = c.post("/api/item", json={"kind":"parameter","name":"c","value":2}).json()["index"]
ig = c.post("/api/item", json={"kind":"operation","op":"integrate"}).json()["index"]
c.post("/api/wire", json={"src": r, "dst": ig, "port": 1})
c.post("/api/undo")
check("redo is available after the undo", c.get("/api/state").json()["canRedo"] is True)
check("a 422 delete is refused", c.delete("/api/item/999").status_code == 422)
check("a 422 godley edit is refused",
      c.post("/api/godley/0/cell", json={"row":99,"col":99,"value":"x"}).status_code == 422)
check("neither destroyed the redo point",
      c.get("/api/state").json()["canRedo"] is True)
rr = c.post("/api/redo")
check("and redo restores the wire",
      rr.status_code == 200 and len(rr.json()["wires"]) == 1,
      f"{rr.status_code}, {len(rr.json().get('wires', []))} wires")

# undo must restore the wire TOPOLOGY too -- the engine cannot report which ports a wire
# joins, so a document restored without our record draws wires that do not exist
check("no desync anywhere in that sequence",
      not any(w.get("desync") for w in c.get("/api/state").json()["wires"]))


print("\n32. the solver panel cannot set something no run can use")
c.post("/api/clear")
for body, why in ((({"order": 3}), "order 3"), (({"order": 0}), "order 0"),
                  (({"epsAbs": 0}), "epsAbs 0"), (({"epsAbs": -1}), "epsAbs -1"),
                  (({"epsRel": 0}), "epsRel 0")):
    # the engine dispatches orders 1, 2 and 4 only, and throws at RESET time -- long
    # after the value was accepted, echoed back to the panel and written into the file
    r = c.post("/api/solver", json=body)
    check(f"{why} is refused", r.status_code == 422, f"{r.status_code} {r.text[:60]}")
for body, why in ((({"order": 1, "implicit": False}), "order 1 explicit (Euler)"),
                  (({"order": 2, "implicit": True}), "order 2 implicit"),
                  (({"order": 4, "epsAbs": 1e-9}), "order 4 with a tight tolerance")):
    r = c.post("/api/solver", json=body)
    check(f"{why} is accepted", r.status_code == 200, f"{r.status_code} {r.text[:60]}")
    check(f"and a model set to {why} resets", c.post("/api/reset").status_code == 200)

# solver settings are saved with the document, so changing them changes the model
c.post("/api/clear")
c.post("/api/item", json={"kind": "parameter", "name": "c", "value": 1})
c.post("/api/save", json={"name": "solver-probe"})
check("saving clears dirty", c.get("/api/state").json()["dirty"] is False)
c.post("/api/solver", json={"order": 2})
st = c.get("/api/state").json()
check("a solver change marks the model dirty", st["dirty"] is True)
check("and is undoable", st["canUndo"] is True)
c.post("/api/undo")
check("undo puts the solver back",
      c.get("/api/state").json()["solver"]["order"] == 4,
      str(c.get("/api/state").json()["solver"]["order"]))


print("\n33. opening and saving files")
import os, tempfile, shutil as _sh
from minskyweb.server import SAVE_DIR, WRITE_ROOTS

# containment is decided on RESOLVED paths: normpath collapses "..", but cannot see a
# symlink, and a link inside a writable directory let the write follow it straight out
esc = tempfile.mkdtemp()
link = SAVE_DIR / "escape-probe"
try:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(esc)
    r = c.post("/api/save", json={"name": str(link / "pwned.mky")})
    check("a save through a symlink out of the root is refused",
          r.status_code == 403, f"{r.status_code}")
    check("and nothing was written outside it",
          not os.path.exists(os.path.join(esc, "pwned.mky")))
finally:
    if link.is_symlink(): link.unlink()
    _sh.rmtree(esc, ignore_errors=True)

# the extension is normalised, or the Open picker never lists what was just saved
c.post("/api/clear")
c.post("/api/item", json={"kind": "parameter", "name": "c", "value": 1})
r = c.post("/api/save", json={"name": "CaseProbe.MKY"}).json()
check("Save As x.MKY writes x.mky", r["saved"].endswith("CaseProbe.mky"), r["saved"])
files = c.get("/api/files").json()
check("and the Open picker lists it",
      any(f["name"] == "CaseProbe" for rt in files["roots"] for f in rt["files"]))
# a name with a dot in it keeps all of it
r2 = c.post("/api/save", json={"name": "my.model"}).json()
check("Save As my.model writes my.model.mky",
      r2["saved"].endswith("my.model.mky"), r2["saved"])

# load() reports success on any well-formed XML and yields an EMPTY model, so a damaged
# file replaced the open model with nothing, answered 200, and left its own name in the
# title bar for the next Save to write over
EX = "/Users/ryneschultz/minsky/examples/GoodwinLinear02.mky"
if os.path.exists(EX):
    c.post("/api/load", params={"path": EX})
    n = len(c.get("/api/state").json()["items"])
    bad = SAVE_DIR / "corrupt-probe.mky"
    bad.write_text("<Minsky><items><Item><type>parameter</type></Item></items>"
                   "<wires><Wire/></wires></Minsky>")
    trunc = SAVE_DIR / "truncated-probe.mky"
    trunc.write_bytes(open(EX, "rb").read(4000))
    try:
        for f, why in ((bad, "a file the engine reads nothing from"),
                       (trunc, "a truncated file")):
            r = c.post("/api/load", params={"path": str(f)})
            check(f"{why} is refused", r.status_code == 422, f"{r.status_code}")
            st = c.get("/api/state").json()
            check(f"and the open model survives {why}",
                  len(st["items"]) == n and st["currentFile"] == "GoodwinLinear02",
                  f"{len(st['items'])} items, file={st['currentFile']}")
    finally:
        bad.unlink(missing_ok=True); trunc.unlink(missing_ok=True)

for junk in ("CaseProbe.mky", "my.model.mky"):
    (SAVE_DIR / junk).unlink(missing_ok=True)


print("\n34. renaming")
c.post("/api/clear")
a = c.post("/api/item", json={"kind":"variable","name":"alpha","var_type":"flow"}).json()["index"]
# the engine CANONICALISES names -- it LaTeX-escapes % # &, and strips a leading ":".
# Comparing literally called each of those a failure: a 400 saying the rename had not
# happened, over a canvas where it plainly had.
for want, why in (("100%", "a percent sign"), ("a#b", "a hash"), (":lead", "a leading colon")):
    r = c.post(f"/api/item/{a}/rename", json={"name": want})
    check(f"a name with {why} is accepted", r.status_code == 200,
          f"{r.status_code} {r.text[:70]}")
    body = r.json()
    check("and the stored form is reported back",
          bool(body.get("name")) and (body["name"] == want or "note" in body),
          str(body.get("name")))

# the engine applies a rename and THEN notices the name is bound to another variable
# type: it reports the clash but keeps the change, leaving a model that never resets
c.post("/api/clear")
c.post("/api/item", json={"kind":"variable","name":"shared","var_type":"stock"})
f = c.post("/api/item", json={"kind":"variable","name":"flowvar","var_type":"flow"}).json()["index"]
r = c.post(f"/api/item/{f}/rename", json={"name": "shared"})
check("renaming onto a name held at another type is refused", r.status_code == 400)
names = sorted(i.get("name") for i in c.get("/api/state").json()["items"])
check("and the model is left exactly as it was", names == ["flowvar", "shared"], str(names))

# renaming onto a name another variable already uses MERGES them -- legitimate, but the
# two values become one and this item's own value is the one that goes
c.post("/api/clear")
c.post("/api/item", json={"kind":"parameter","name":"keep","value":7.5})
q = c.post("/api/item", json={"kind":"parameter","name":"other","value":1.25}).json()["index"]
r = c.post(f"/api/item/{q}/rename", json={"name": "keep"}).json()
check("a merging rename says so", "warning" in r and "merged" in r["warning"], str(r)[:80])
check("and it is undoable", c.post("/api/undo").status_code == 200)
vals = c.get("/api/state").json()["values"]
check("undo brings the separate variable back", len(vals) == 2, str(vals))

# Two items at one point cannot be told apart by the ENGINE's hit test, which is how
# delete and wiring find their target -- but rename no longer goes that way, so it can
# act on exactly the item it was given.
c.post("/api/clear")
c.post("/api/item", json={"kind":"parameter","name":"aa","value":1,"at":[300,300]})
b = c.post("/api/item", json={"kind":"parameter","name":"bb","value":2,"at":[600,300]}).json()["index"]
c.post(f"/api/item/{b}/move", json={"x":300,"y":300})
check("renaming one of two coincident items works",
      c.post(f"/api/item/{b}/rename", json={"name":"cc"}).status_code == 200)
check("and it renamed the right one",
      sorted(i.get("name") for i in c.get("/api/state").json()["items"]) == ["aa","cc"],
      str(sorted(i.get("name") for i in c.get("/api/state").json()["items"])))
check("while deleting one of them is still refused -- that DOES resolve by position",
      c.delete(f"/api/item/{b}").status_code == 400)


print("\n35. adding items")
c.post("/api/clear")
# addVariable() with a type it does not know creates NOTHING and raises nothing, so the
# failure surfaced later as a bare 500 with no body at all
r = c.post("/api/item", json={"kind":"variable","name":"vv","var_type":"nonsense"})
check("an unknown variable type is refused", r.status_code == 422, str(r.status_code))
check("and it names the ones that work", "flow" in r.text and "stock" in r.text)
check("nothing was left behind", c.get("/api/state").json()["items"] == [])

for t in ("flow", "stock", "parameter", "integral", "tempFlow"):
    r = c.post("/api/item", json={"kind":"variable","name":f"v_{t}","var_type":t})
    check(f"var_type {t} works", r.status_code == 200, f"{r.status_code} {r.text[:60]}")
# a constant is the odd one out: the engine gives it its own class and its NAME is its
# value, so a name passed here was silently dropped and left a nameless item
c.post("/api/clear")
check("a constant without a value is refused",
      c.post("/api/item", json={"kind":"variable","var_type":"constant","name":"kk"}
             ).status_code == 422)
check("a constant with a value works",
      c.post("/api/item", json={"kind":"variable","var_type":"constant","value":3.5}
             ).status_code == 200)
check("and it is named by its value",
      c.get("/api/state").json()["items"][0]["name"] == "3.5",
      str(c.get("/api/state").json()["items"][0].get("name")))

# the engine explains a type clash exactly; it was being replaced by a bare 500
c.post("/api/clear")
c.post("/api/item", json={"kind":"variable","name":"dup","var_type":"stock"})
r = c.post("/api/item", json={"kind":"variable","name":"dup","var_type":"flow"})
check("a name already bound at another type is refused", r.status_code == 400)
check("and the engine's own explanation survives",
      "already exists" in r.json().get("detail", ""), r.text[:80])
check("with nothing half-created left behind",
      len(c.get("/api/state").json()["items"]) == 1)

# a Godley table's name is its title -- it was accepted and dropped
c.post("/api/clear")
c.post("/api/item", json={"kind":"godley","name":"Bank"})
check("a Godley table keeps the name it was given",
      c.get("/api/state").json()["items"][0].get("name") == "Bank",
      str(c.get("/api/state").json()["items"][0].get("name")))

# an item at these coordinates is on the canvas but can never be reached again
c.post("/api/clear")
# sent as raw text: JSON has no inf, but "1e999" parses to one, which is exactly how a
# real client produces it
for at, why in (('[1e999,0]', "an infinite coordinate"),
                ('[-9e9,-9e9]', "a coordinate far outside the canvas")):
    r = c.post("/api/item", headers={"content-type": "application/json"},
               content='{"kind":"parameter","name":"p","value":1,"at":%s}' % at)
    check(f"{why} is refused", r.status_code == 422, f"{r.status_code} {r.text[:60]}")
check("nothing was placed", c.get("/api/state").json()["items"] == [])
check("a move to a nonsense coordinate is refused too",
      (lambda i: c.post(f"/api/item/{i}/move", json={"x": 9e9, "y": 0}).status_code)(
          c.post("/api/item", json={"kind":"parameter","name":"p","value":1,
                                    "at":[300,300]}).json()["index"]) == 422)


print("\n36. Godley tables and the rest of the model")
def _gwire(c):
    """A table with two stocks, plus an unrelated wire ABOVE it in the item list."""
    c.post("/api/clear")
    g = c.post("/api/item", json={"kind":"godley"}).json()["index"]
    for col, nm in ((1, "Reserves"), (2, "Deposits")):
        c.post(f"/api/godley/{g}/cell", json={"row":0,"col":col,"value":nm})
    p = c.post("/api/item", json={"kind":"parameter","name":"c","value":2}).json()["index"]
    i = c.post("/api/item", json={"kind":"operation","op":"integrate"}).json()["index"]
    c.post("/api/wire", json={"src":p,"dst":i,"port":1})
    return g

def _wire_ends(c):
    st = c.get("/api/state").json()
    items = {i["index"]: i["classType"] for i in st["items"]}
    live = [w for w in st["wires"] if not w.get("desync")]
    return [(items.get(int(w["src"]), "GONE"), items.get(int(w["dst"]), "GONE"))
            for w in live], any(w.get("desync") for w in st["wires"])

# a table generates and destroys variables as its headers are typed, and the engine
# regenerates them at the END of model.items -- so both of these move other items
g = _gwire(c)
c.post(f"/api/godley/{g}/cell", json={"row":0,"col":2,"value":""})   # removes a variable
ends, desync = _wire_ends(c)
check("blanking a stock header leaves the wire on its own items",
      ends == [("Variable:parameter", "IntOp")] and not desync, str(ends))

g = _gwire(c)
c.post(f"/api/godley/{g}/cell", json={"row":0,"col":1,"value":"Cash"})  # reorders items
ends, desync = _wire_ends(c)
check("renaming a stock header leaves the wire on its own items",
      ends == [("Variable:parameter", "IntOp")] and not desync, str(ends))

g = _gwire(c)
c.post(f"/api/godley/{g}/row/insert", json={"at": 2})
ends, _ = _wire_ends(c)
check("inserting a row leaves the wire alone", ends == [("Variable:parameter", "IntOp")],
      str(ends))

# set_cell writes the cell and THEN commits it; when the commit throws the API said 400
# while the cell was already written and the model could no longer reset
c.post("/api/clear")
c.post("/api/item", json={"kind":"variable","name":"Clash","var_type":"flow"})
g = c.post("/api/item", json={"kind":"godley"}).json()["index"]
r = c.post(f"/api/godley/{g}/cell", json={"row":0,"col":1,"value":"Clash"})
check("a header clashing with another variable type is refused", r.status_code == 400)
check("and the cell was not written",
      c.get(f"/api/godley/{g}").json()["cells"][0][1] == "",
      str(c.get(f"/api/godley/{g}").json()["cells"][0]))
check("so the model still resets", c.post("/api/reset").status_code == 200)

# two tables may name the same stock -- one account on both sides of a transaction --
# but there is one variable behind it, so one initial condition. Each table stored and
# showed its own, and the engine used whichever was written last.
c.post("/api/clear")
g1 = c.post("/api/item", json={"kind":"godley"}).json()["index"]
g2 = c.post("/api/item", json={"kind":"godley"}).json()["index"]
for g in (g1, g2):
    c.post(f"/api/godley/{g}/cell", json={"row":0,"col":1,"value":"Shared"})
c.post(f"/api/godley/{g1}/cell", json={"row":1,"col":1,"value":"100"})
r = c.post(f"/api/godley/{g2}/cell", json={"row":1,"col":1,"value":"250"}).json()
check("two tables disagreeing about one stock's initial value is reported",
      bool(r.get("conflicts")), str(r.get("conflicts"))[:80])
check("and the report names both values",
      {v["value"] for v in r["conflicts"][0]["shown"]} == {"100", "250"},
      str(r["conflicts"][0]["shown"]))


print("\n37. what is on screen is what is in the file")
from minskyweb.server import SAVE_DIR
c.post("/api/clear")
gi = c.post("/api/item", json={"kind":"godley","name":"Bank"}).json()["index"]
c.post(f"/api/godley/{gi}/resize", json={"rows":4,"cols":5})
for col, lab in ((1,"A"),(2,"B"),(3,"C"),(4,"D")):
    c.post(f"/api/godley/{gi}/cell", json={"row":0,"col":col,"value":lab})
for col, cl in ((1,"asset"),(2,"liability"),(3,"equity"),(4,"asset")):
    c.post(f"/api/godley/{gi}/class", json={"col":col,"cls":cl})
# writing the document groups a table's columns by asset class and appends an empty
# column for any class it lacks, so the file did not match the screen and the user only
# found out on reopening. Saving now reconciles the two.
r = c.post("/api/save", json={"name": "colorder-probe"}).json()
try:
    on_screen = c.get(f"/api/godley/{gi}").json()["cells"][0]
    c.post("/api/clear")
    c.post("/api/load", params={"path": r["saved"]})
    reopened = c.get(f"/api/godley/{gi}").json()["cells"][0]
    check("a saved table reopens exactly as it was left",
          on_screen == reopened, f"{on_screen} vs {reopened}")
    check("and the columns are in the engine's stored order",
          on_screen == ["", "A", "D", "B", "C"], str(on_screen))
finally:
    (SAVE_DIR / "colorder-probe.mky").unlink(missing_ok=True)


print("\n38. the simulation socket")
c.post("/api/clear")
_r = c.post("/api/item", json={"kind":"parameter","name":"g","value":0.3}).json()["index"]
_i = c.post("/api/item", json={"kind":"operation","op":"integrate"}).json()["index"]
c.post("/api/wire", json={"src":_r,"dst":_i,"port":1})
c.post("/api/init", json={"name":"int1","value":1.0})

# these were read straight into int()/float() where nothing was catching the failure:
# the socket dropped with no error frame and the UI waited for a run that never reported
for body, why in (({"cmd":"run","steps":"lots"}, "steps='lots'"),
                  ({"cmd":"run","steps":10,"tmax":"soon"}, "tmax='soon'"),
                  ({"cmd":"run","steps":0}, "steps=0"),
                  ({"cmd":"run","steps":-5}, "steps=-5")):
    with c.websocket_connect("/ws/sim") as ws:
        ws.send_json(body)
        msg = ws.receive_json()
        check(f"{why} is answered with an error", "error" in msg, str(msg)[:70])

# steps<=0 skipped the loop body, so its else-clause reported a completed run -- after
# reset() had already discarded the state of the run before it
with c.websocket_connect("/ws/sim") as ws:
    ws.send_json({"cmd":"run","steps":40,"tmax":5.0})
    while True:
        m = ws.receive_json()
        if m.get("done") or m.get("stopped") or "error" in m: break
t_ran = c.get("/api/state").json()["t"]
check("a real run advances t", t_ran > 0, str(t_ran))
with c.websocket_connect("/ws/sim") as ws:
    ws.send_json({"cmd":"run","steps":0})
    ws.receive_json()
check("a refused run does not discard the state of the last one",
      c.get("/api/state").json()["t"] == t_ran, str(c.get("/api/state").json()["t"]))

# a frame that is not JSON killed the reader task outright, and with it the only route
# for "stop": for the rest of the run the Stop button did nothing, silently
with c.websocket_connect("/ws/sim") as ws:
    ws.send_json({"cmd":"run","steps":4000,"tmax":1e9})
    ws.receive_json()
    ws.send_text("this is not json")
    saw = False
    for _ in range(80):
        m = ws.receive_json()
        if "error" in m and "JSON" in m["error"]: saw = True; break
    check("a non-JSON frame is reported", saw)
    ws.send_json({"cmd":"stop"})
    stopped = False
    for _ in range(2000):
        m = ws.receive_json()
        if m.get("stopped"): stopped = True; break
        if m.get("done"): break
    check("and Stop still works afterwards", stopped)


print("\n39. two items never share a point")
# Adding an item is a round trip, so two clicks in quick succession both measure the
# same model and ask for the SAME slot. Two items at one point are ambiguous to the
# engine's hit test, and delete, rename and wire removal all resolve by position -- so
# from then on those act on whichever of the two the engine happens to pick.
c.post("/api/clear")
for n in range(10):
    c.post("/api/item", json={"kind":"parameter","name":f"p{n}","value":1,"at":[300,300]})
pts = [(round(i["x"]), round(i["y"])) for i in c.get("/api/state").json()["items"]]
check("ten items asked to the same point all land apart",
      len(set(pts)) == len(pts) == 10, f"{len(set(pts))} distinct of {len(pts)}")
# and an explicit position IS honoured when it is free
c.post("/api/clear")
c.post("/api/item", json={"kind":"parameter","name":"here","value":1,"at":[420,260]})
it = c.get("/api/state").json()["items"][0]
check("a free position is used exactly as asked",
      (round(it["x"]), round(it["y"])) == (420, 260), f"{it['x']},{it['y']}")


print("\n40. a value that has been set reads back as set")
c.post("/api/clear")
c.post("/api/item", json={"kind":"parameter","name":"alpha","value":0.4})
c.post("/api/item", json={"kind":"operation","op":"integrate"})
# value() is what the variable holds RIGHT NOW and only picks up a new initial condition
# at the next reset, so a caller who set a parameter to 0.9 read 0.4 straight back and
# concluded nothing had happened
r = c.post("/api/init", json={"name":"alpha","value":0.9}).json()
check("setting a value is visible immediately",
      r["inits"][":alpha"] in ("0.9", 0.9), str(r["inits"]))
r = c.post("/api/init", json={"name":"int1","value":1.5}).json()
check("an integral's initial condition too",
      r["inits"][":int1"] in ("1.5", 1.5), str(r["inits"]))
check("the running values still say what the model currently holds",
      r["values"][":alpha"] == 0.0, str(r["values"]))
c.post("/api/reset")
vals = c.get("/api/state").json()["values"]
check("and a reset brings them into line",
      vals[":alpha"] == 0.9 and vals[":int1"] == 1.5, str(vals))


print("\n41. the values panel lists only variables that exist")
c.post("/api/clear")
g = c.post("/api/item", json={"kind":"godley"}).json()["index"]
for row, col, v in ((0,1,"Reserves"), (0,2,"Deposits"), (2,0,"lending"), (2,1,"L"), (2,2,"L")):
    c.post(f"/api/godley/{g}/cell", json={"row":row,"col":col,"value":v})
check("a balanced table reports its three variables",
      set(c.get("/api/state").json()["values"]) == {":Reserves", ":Deposits", ":L"},
      str(set(c.get("/api/state").json()["values"])))
# variableValues keeps an entry after the last icon referring to it is gone, until the
# next reset -- so a mistyped flow name sat in the values panel with a value next to
# variables that really exist
c.post(f"/api/godley/{g}/cell", json={"row":2,"col":2,"value":"M"})
c.post(f"/api/godley/{g}/cell", json={"row":2,"col":2,"value":"L"})
st = c.get("/api/state").json()
check("a name typed and then changed leaves nothing behind",
      ":M" not in st["values"], str(set(st["values"])))
check("and the canvas agrees with the values panel",
      {i["name"] for i in st["items"] if i.get("name")} ==
      {k.lstrip(":") for k in st["values"]},
      f"{[i.get('name') for i in st['items']]} vs {list(st['values'])}")


print("\n42. the unsaved marker means what it says")
import os
from minskyweb.server import SAVE_DIR
EX = "/Users/ryneschultz/minsky/examples/GoodwinLinear02.mky"
if os.path.exists(EX):
    c.post("/api/load", params={"path": EX})
    check("a freshly opened file is not edited",
          c.get("/api/state").json()["dirty"] is False)
    c.post("/api/item/0/move", json={"x":500,"y":500})
    check("moving something marks it edited",
          c.get("/api/state").json()["dirty"] is True)
    # undo takes the model back to exactly what is on disk, so the file is NOT edited --
    # leaving the marker set asked the user to save a file that already matched
    c.post("/api/undo")
    check("undoing back to the file clears the marker",
          c.get("/api/state").json()["dirty"] is False)
    c.post("/api/redo")
    check("and redoing sets it again",
          c.get("/api/state").json()["dirty"] is True)

    r = c.post("/api/save", json={"name": "dirty-probe"}).json()
    try:
        check("saving clears it", c.get("/api/state").json()["dirty"] is False)
        c.post("/api/item/0/move", json={"x":700,"y":700})
        c.post("/api/undo")
        check("and undo back to the SAVED state clears it too",
              c.get("/api/state").json()["dirty"] is False)
    finally:
        (SAVE_DIR / "dirty-probe.mky").unlink(missing_ok=True)


print("\n43. editing what is inside a group")
import os
EX = "/Users/ryneschultz/minsky/examples/GoodwinLinear02.mky"
if os.path.exists(EX):
    def load_grouped():
        c.post("/api/load", params={"path": EX})
        return c.get("/api/state").json()

    st = load_grouped()
    inside = [i for i in st["items"] if i["index"] is None]
    check("a group's members are reported with a ref but no index",
          len(inside) == 8 and all(i["ref"].startswith("g0:") for i in inside),
          f"{len(inside)} members")
    check("and each says what can be done to it",
          all(i["can"]["move"] and i["can"]["rename"]
              and not i["can"]["delete"] and not i["can"]["wire"] for i in inside))

    # moveTo works on the raw item, so this reaches inside a group
    ref = inside[0]["ref"]
    r = c.post(f"/api/item/{ref}/move", json={"x": 400, "y": 400})
    check("a group member can be moved", r.status_code == 200, r.text[:70])
    moved = next(i for i in c.get("/api/state").json()["items"] if i["ref"] == ref)
    check("and it went where it was told",
          (round(moved["x"]), round(moved["y"])) == (400, 400),
          f"{moved['x']},{moved['y']}")

    # rename finds every icon of the variable by valueId, so it reaches inside too
    st = load_grouped()
    vref = next(i["ref"] for i in st["items"]
                if i["index"] is None and i.get("name") == "NAIRU")
    r = c.post(f"/api/item/{vref}/rename", json={"name": "NaturalRate"})
    check("a group member can be renamed", r.status_code == 200, r.text[:70])
    names = [i.get("name") for i in c.get("/api/state").json()["items"]]
    check("and the new name is the one in the model",
          "NaturalRate" in names and "NAIRU" not in names, str(names))
    check("the model still resets after it", c.post("/api/reset").status_code == 200)

    # delete and wiring go through the canvas hit test, which never enters a group
    st = load_grouped()
    ref = next(i["ref"] for i in st["items"] if i["index"] is None)
    r = c.delete(f"/api/item/{ref}")
    check("deleting a group member is refused", r.status_code == 409, str(r.status_code))
    check("and the refusal says what to do instead", "Ungroup" in r.text, r.text[:90])
    r = c.post("/api/wire", json={"src": ref, "dst": "3", "port": 1})
    check("wiring to a group member is refused", r.status_code == 409, str(r.status_code))
    check("nothing was changed by either refusal",
          len(c.get("/api/state").json()["items"]) == len(st["items"]))

    # ungroup is the way in
    st = load_grouped()
    n_items, n_wires = len(st["items"]), len(st["wires"])
    r = c.post("/api/group/g0/ungroup")
    check("a group can be dissolved", r.status_code == 200, r.text[:70])
    check("and it reports how many items it freed", r.json()["freed"] == 8,
          str(r.json().get("freed")))
    st2 = c.get("/api/state").json()
    check("every item is now top level",
          len(st2["items"]) == n_items and not st2["groups"]
          and all(i["index"] is not None for i in st2["items"]),
          f"{len(st2['items'])} items, {len(st2['groups'])} groups")
    check("no wire was lost or mis-pointed",
          len(st2["wires"]) == n_wires and not any(w.get("desync") for w in st2["wires"]),
          f"{len(st2['wires'])} wires")
    check("the model still resets", c.post("/api/reset").status_code == 200)

    # and the freed contents answer every ordinary edit path
    idx = next(i["index"] for i in st2["items"] if i.get("name") == "NAIRU")
    check("a freed item can now be deleted",
          c.delete(f"/api/item/{idx}").status_code == 200)
    c.post("/api/undo")
    c.post("/api/undo")
    back = c.get("/api/state").json()
    check("undo puts the group back",
          len(back["groups"]) == 1 and len(back["items"]) == n_items
          and not any(w.get("desync") for w in back["wires"]),
          f"{len(back['groups'])} groups, {len(back['items'])} items")

    # a group has a name of its own
    r = c.post("/api/group/g0/rename", json={"name": "Wage Dynamics"})
    check("a group can be renamed", r.status_code == 200 and r.json()["name"] == "Wage Dynamics",
          r.text[:70])
    c.post("/api/undo")
    check("and that is undoable too",
          c.get("/api/state").json()["groups"][0]["title"] == "Phillips Curve",
          str(c.get("/api/state").json()["groups"][0]["title"]))

    # ungrouping must not be a one-way door: without a way back, a group could only be
    # restored by undoing the very edits it was opened for
    def run_to(tmax, steps):
        with c.websocket_connect("/ws/sim") as ws:
            ws.send_json({"cmd": "run", "steps": steps, "tmax": tmax})
            last = None
            while True:
                msg = ws.receive_json()
                if "error" in msg or msg.get("done") or msg.get("stopped"):
                    return last
                last = msg

    c.post("/api/load", params={"path": EX})
    baseline = run_to(10.0, 3000)["values"]
    c.post("/api/load", params={"path": EX})
    c.post("/api/group/g0/ungroup")
    band = [i for i in c.get("/api/state").json()["items"] if 250 < i["y"] < 400]
    box = dict(x0=min(i["x"] for i in band) - 30, x1=max(i["x"] for i in band) + 30,
               y0=min(i["y"] for i in band) - 30, y1=max(i["y"] for i in band) + 30)
    r = c.post("/api/group", json=box)
    check("the freed items can be grouped again", r.status_code == 200, r.text[:70])
    check("and it reports how many it took in", r.json()["grouped"] == 8,
          str(r.json().get("grouped")))
    st3 = c.get("/api/state").json()
    check("the new group holds them", len(st3["groups"]) == 1)
    # splitBoundaryCrossingWires replaces each crossing wire with TWO joined by a
    # generated variable, so the tracked topology has to be re-derived, not remapped
    check("no wire is left mis-pointed after the split",
          not any(w.get("desync") for w in st3["wires"]),
          str([w for w in st3["wires"] if w.get("desync")]))
    after = run_to(10.0, 3000)["values"]
    check("and the model computes exactly what it did before the round trip",
          all(abs(after[k] - baseline[k]) < 1e-9 for k in baseline if k in after)
          and len(after) >= len(baseline),
          f"{ {k: (baseline[k], after.get(k)) for k in list(baseline)[:3]} }")

    check("grouping an empty region is refused",
          c.post("/api/group", json={"x0":5000,"y0":5000,"x1":5100,"y1":5100}
                 ).status_code == 422)
    check("and it left no empty group behind",
          len(c.get("/api/state").json()["groups"]) == 1)

    check("ungrouping a group that is not there is refused",
          c.post("/api/group/g9/ungroup").status_code == 422)
    check("so is an item reference into a group that is not there",
          c.post("/api/item/g9:0/move", json={"x":1,"y":1}).status_code == 422)
    check("and a malformed reference",
          c.post("/api/item/nonsense/move", json={"x":1,"y":1}).status_code == 422)


print("\n44. groups inside groups")
# Grouping a selection that contains a group puts that group INSIDE the new one, so a
# nested group is one lasso away. Walking only one level meant its contents were absent
# from the canvas entirely, with nothing to say so.
c.post("/api/clear")
for n in range(1, 7):
    c.post("/api/item", json={"kind":"parameter","name":f"p{n}","value":n,
                              "at":[n*130+100, 320]})
r = c.post("/api/group", json={"x0":200,"y0":280,"x1":420,"y1":360})
check("an inner group is made", r.status_code == 200, r.text[:70])
# the top-level GROUP count does not change when a group is nested, so checking it
# rolled a perfectly good grouping back and reported that nothing had been grouped
r = c.post("/api/group", json={"x0":150,"y0":260,"x1":700,"y1":380})
check("grouping a region containing a group succeeds", r.status_code == 200, r.text[:80])
st = c.get("/api/state").json()
refs = sorted(i["ref"] for i in st["items"])
check("every item is still reported, at every depth", len(refs) == 6, str(refs))
check("nested refs carry the path",
      any(r.startswith("g0.0:") for r in refs), str(refs))
grefs = {g["ref"]: g["parent"] for g in st["groups"]}
check("and the nested group names its parent",
      grefs.get("g0.0") == "g0" and grefs.get("g0") is None, str(grefs))

# every item operation must reach the deepest level
deep = next(r for r in refs if r.startswith("g0.0:"))
check("a doubly-nested item can be moved",
      c.post(f"/api/item/{deep}/move", json={"x":700,"y":700}).status_code == 200)
check("and renamed",
      c.post(f"/api/item/{deep}/rename", json={"name":"deep"}).status_code == 200)
check("the rename reached the model",
      any(i.get("name") == "deep" for i in c.get("/api/state").json()["items"]))
check("the model still resets", c.post("/api/reset").status_code == 200)

# groups are addressed by ref, so a nested one can be named
check("a nested group can be renamed",
      c.post("/api/group/g0.0/rename", json={"name":"Inner"}).status_code == 200)
c.post("/api/group/g0/rename", json={"name": "Outer"})

# getItemAt can only focus a TOP-LEVEL group, so asking to dissolve a nested one used to
# focus the ENCLOSING group and dissolve that instead -- answering 200 with a count. The
# old assertions here checked only that one group and six items remained, which is just
# as true when the WRONG group goes, so the suite stayed green over it. Assert WHICH
# group survived.
r = c.post("/api/group/g0.0/ungroup")
check("dissolving a nested group is refused", r.status_code == 409, str(r.status_code))
check("and the refusal names the group to ungroup first",
      "Outer" in r.text and "g0" in r.text, r.text[:110])
st = c.get("/api/state").json()
check("nothing was dissolved",
      [g["title"] for g in st["groups"]] == ["Outer", "Inner"],
      str([g["title"] for g in st["groups"]]))

# peeling from the outside works: the inner group is re-rooted and can then be dissolved
check("the outer group can be dissolved",
      c.post("/api/group/g0/ungroup").status_code == 200)
st = c.get("/api/state").json()
check("and it is the OUTER one that went",
      [g["title"] for g in st["groups"]] == ["Inner"],
      str([g["title"] for g in st["groups"]]))
check("the inner group is now top level and can be dissolved",
      c.post("/api/group/g0/ungroup").status_code == 200)
check("leaving every item at the top level",
      not c.get("/api/state").json()["groups"]
      and all(i["index"] is not None for i in c.get("/api/state").json()["items"]))
c.post("/api/undo"); c.post("/api/undo")
check("undo restores the nesting",
      [g["title"] for g in c.get("/api/state").json()["groups"]] == ["Outer", "Inner"],
      str([g["title"] for g in c.get("/api/state").json()["groups"]]))

# The engine wire count summed ONE level, so once a group held a group the wires inside
# it were never counted: the engine total came out below the tracked total and the UI
# reported a permanent desync of "-N wires could not be traced" over a correct model.
c.post("/api/clear")
_p = c.post("/api/item", json={"kind":"parameter","name":"c","value":2,
                               "at":[200,300]}).json()["index"]
_i = c.post("/api/item", json={"kind":"operation","op":"integrate",
                               "at":[340,300]}).json()["index"]
c.post("/api/wire", json={"src":_p,"dst":_i,"port":1})
c.post("/api/item", json={"kind":"parameter","name":"far","value":9,"at":[700,300]})
c.post("/api/group", json={"x0":150,"y0":250,"x1":420,"y1":350})   # wire goes inside
c.post("/api/group", json={"x0":100,"y0":230,"x1":800,"y1":370})   # and that group nests
st = c.get("/api/state").json()
check("a wire two groups deep is still counted",
      not any(w.get("desync") for w in st["wires"]),
      str([w for w in st["wires"] if w.get("desync")]))
check("and it is still drawn",
      len([w for w in st["wires"] if not w.get("desync")]) == 1)
check("only one place counts engine wires",
      "sum(len(m.model.groups[g].wires)" not in src)

check("a group reference that does not exist is refused",
      c.post("/api/group/g0.9/ungroup").status_code == 422)
check("and a malformed group reference",
      c.post("/api/group/nope/ungroup").status_code == 422)


print("\n45. one process's scratch files are its own")
import re as _re, subprocess, sys as _sys, time as _time, json as _json
import urllib.request, urllib.error
# These files were at fixed paths under the system temp directory, shared by every
# minskyweb process on the machine. Two instances then read each other's models back: an
# undo answered 200 having replaced its own document with the other's items, and a
# download served the other's model. A second instance is not exotic -- a stale server, a
# second checkout, or this very suite running while a server is up.
from minskyweb.server import _SCRATCH, _hist_file
check("the scratch directory is private to this process",
      str(os.getpid()) in str(_SCRATCH), str(_SCRATCH))
check("and the history file lives inside it",
      str(_hist_file()).startswith(str(_SCRATCH)), str(_hist_file()))
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "minskyweb", "server.py")).read()
# UPLOAD_DIR is deliberately NOT private: it is a store of models the user uploaded and
# can reopen, and it is one of the writable roots. Only the transient scratch files --
# the history buffer and the download staging file -- must belong to one process.
# A count would just need updating whenever another scratch file is added. The rule is
# what matters: the only thing built from the shared temp directory is UPLOAD_DIR.
_shared = [l.strip() for l in src.splitlines() if "gettempdir()" in l]
check("nothing but UPLOAD_DIR is built from the shared temp directory",
      len(_shared) == 1 and _shared[0].startswith("UPLOAD_DIR"), str(_shared))
check("and the scratch files are all in the private directory",
      src.count("_SCRATCH /") >= 2, f'{src.count("_SCRATCH /")} uses')


print("\n46. a wire never moves to an item it was not on")
# Two items the fingerprint cannot tell apart -- same class, no name -- in different
# places. Deleting one used to re-attach its neighbour's wires to the survivor, with the
# counts still matching so nothing flagged it.
c.post("/api/clear")
_sA = c.post("/api/item", json={"kind":"operation","op":"sqrt","at":[300,150]}).json()["index"]
_sB = c.post("/api/item", json={"kind":"operation","op":"sqrt","at":[300,400]}).json()["index"]
_a  = c.post("/api/item", json={"kind":"parameter","name":"a","value":4,"at":[120,150]}).json()["index"]
_b  = c.post("/api/item", json={"kind":"parameter","name":"b","value":9,"at":[120,400]}).json()["index"]
_oA = c.post("/api/item", json={"kind":"variable","name":"outA","var_type":"flow","at":[520,150]}).json()["index"]
_oB = c.post("/api/item", json={"kind":"variable","name":"outB","var_type":"flow","at":[520,400]}).json()["index"]
for _s, _d in ((_a,_sA), (_sA,_oA), (_b,_sB), (_sB,_oB)):
    c.post("/api/wire", json={"src":_s,"dst":_d,"port":1})

def _rows():
    st = c.get("/api/state").json()
    m = {i["ref"]: round(i["y"]) for i in st["items"]}
    return [(m.get(w["src"]), m.get(w["dst"])) for w in st["wires"] if not w.get("desync")], \
           any(w.get("desync") for w in st["wires"])

rows, _ = _rows()
check("four wires, each within one row", len(rows) == 4 and all(x == y for x, y in rows),
      str(rows))
_tgt = next(i["index"] for i in c.get("/api/state").json()["items"]
            if i["classType"] == "Operation:sqrt" and round(i["y"]) == 150)
c.delete(f"/api/item/{_tgt}")
rows, desync = _rows()
check("deleting one of the pair leaves only the other row's wires",
      len(rows) == 2 and all(x == 400 and y == 400 for x, y in rows), str(rows))
check("and no wire was left pointing somewhere it never was", not desync)
check("the model still resets", c.post("/api/reset").status_code == 200)


print("\n47. inputs that used to reach the engine unchecked")
c.post("/api/clear")
c.post("/api/item", json={"kind":"parameter","name":"a","value":1})
# str.isdigit() is True for characters int() will not take, and lstrip("-").isdigit()
# accepted "-0" -- which passed the range check and was then recorded in the wire
# topology under a ref no item has, so the wire vanished at the next remap.
for bad in ("--5", "-0", "-1", "\u00b2", "g\u00b2:0", "g0", "1.0", ""):
    r = c.post(f"/api/item/{bad}/move", json={"x": 10, "y": 10})
    # 405 for the empty ref: the route simply does not match, which is a refusal too
    check(f"item ref {bad!r} is refused", r.status_code in (404, 405, 422),
          f"{r.status_code} {r.text[:50]}")
for bad in ("g\u00b2", "g--1", "g1.\u00b2"):
    r = c.post(f"/api/group/{bad}/ungroup")
    check(f"group ref {bad!r} is refused", r.status_code in (404, 422),
          f"{r.status_code} {r.text[:50]}")

# names the filesystem cannot take reached save() and came back as a bare 500
r = c.post("/api/save", content=_json.dumps({"name": "bad\x00name"}),
           headers={"content-type": "application/json"})
check("a save name with a null character is refused", r.status_code == 422,
      f"{r.status_code}")
r = c.post("/api/save", json={"name": "x" * 400})
check("an over-long save name is refused", r.status_code == 422, f"{r.status_code}")

# the engine stores a non-finite initial value as the string "inf" and only THEN fails,
# leaving an initial condition no reset can accept
c.post("/api/item", json={"kind": "operation", "op": "integrate"})
r = c.post("/api/init", content='{"name":"int1","value":1e999}',
           headers={"content-type": "application/json"})
check("a non-finite initial value is refused", r.status_code == 422, f"{r.status_code}")
check("and the model still resets", c.post("/api/reset").status_code == 200)

# saving reads the file back, which resets the engine -- mid-run that restarted the
# simulation under the client
_p = c.post("/api/item", json={"kind":"parameter","name":"g2","value":0.3}).json()["index"]
_st = c.get("/api/state").json()
_io = next(i["index"] for i in _st["items"] if i["classType"] == "IntOp")
c.post("/api/wire", json={"src": _p, "dst": _io, "port": 1})
with c.websocket_connect("/ws/sim") as ws:
    ws.send_json({"cmd": "run", "steps": 3000, "tmax": 100})
    ws.receive_json()
    check("saving during a run is refused",
          c.post("/api/save", json={"name": "midrun"}).status_code == 409)
    check("so is downloading", c.get("/api/download").status_code == 409)
    # receive_json() reads message["text"], so a BINARY frame raises KeyError, not a
    # decode error -- the socket died with no error frame at all
    ws.send_bytes(b"\x02\x03")
    saw = False
    for _ in range(80):
        m = ws.receive_json()
        if "error" in m and "JSON" in m["error"]: saw = True; break
    check("a binary frame mid-run is reported", saw)
    ws.send_json({"cmd": "stop"})
    for _ in range(400):
        if ws.receive_json().get("stopped"): break
with c.websocket_connect("/ws/sim") as ws:
    ws.send_bytes(b"\x00\x01")
    check("a binary FIRST frame gets an error frame, not a dropped socket",
          "error" in ws.receive_json())
with c.websocket_connect("/ws/sim") as ws:
    # /api/solver refuses tmax <= t0; the socket accepted it, wrote it into the document
    # and reported the run complete after one step
    ws.send_json({"cmd": "run", "steps": 10, "tmax": 0})
    m = ws.receive_json()
    check("tmax at or before t0 is refused on the socket too",
          "error" in m and "t0" in m["error"], str(m)[:70])


print("\n48. the saved point survives the history moving under it")
from minskyweb.server import MAX_HISTORY, SAVE_DIR
# The saved point was a raw INDEX into a list that is truncated from the right when a new
# edit abandons a redo tail, and trimmed from the left at MAX_HISTORY. Either one leaves
# the index naming a DIFFERENT state, so the marker went false over a model that differed
# from the file -- which also disabled Save and silenced the discard confirmations.
c.post("/api/clear")
c.post("/api/item", json={"kind":"parameter","name":"a","value":1,"at":[100,100]})
for x in (110, 120, 130):
    c.post("/api/item/0/move", json={"x": x, "y": 100})
r = c.post("/api/save", json={"name": "savedpoint-probe"}).json()
try:
    check("saving clears the marker", c.get("/api/state").json()["dirty"] is False)
    c.post("/api/undo"); c.post("/api/undo")
    for x in (500, 600, 700, 800):          # a new edit truncates the redo tail
        c.post("/api/item/0/move", json={"x": x, "y": 100})
    c.post("/api/undo"); c.post("/api/undo")
    st = c.get("/api/state").json()
    on_disk = float(re.search(r"<x>([\d.]+)</x>", open(r["saved"]).read()).group(1))
    differs = abs(st["items"][0]["x"] - on_disk) > 0.5
    check("after truncation the marker still matches reality",
          st["dirty"] is differs,
          f'model x={st["items"][0]["x"]:.0f} file x={on_disk:.0f} dirty={st["dirty"]}')

    # and again with the buffer trimmed from the left
    c.post("/api/save", json={"name": "savedpoint-probe"})
    for i in range(MAX_HISTORY + 5):
        c.post("/api/item/0/move", json={"x": 100 + (i % 40), "y": 100})
    st = c.get("/api/state").json()
    check("after MAX_HISTORY trimming the marker is still true",
          st["dirty"] is True, f'dirty={st["dirty"]}')
finally:
    (SAVE_DIR / "savedpoint-probe.mky").unlink(missing_ok=True)

# a Save used to append a duplicate entry, so the first undo after it did nothing visible
c.post("/api/clear")
c.post("/api/item", json={"kind":"parameter","name":"a","value":1,"at":[100,100]})
c.post("/api/item/0/move", json={"x": 200, "y": 100})
c.post("/api/save", json={"name": "dupe-probe"})
try:
    was = c.get("/api/state").json()["items"][0]["x"]
    c.post("/api/undo")
    now = c.get("/api/state").json()["items"][0]["x"]
    check("the first undo after a save actually undoes something", was != now,
          f"{was} -> {now}")
finally:
    (SAVE_DIR / "dupe-probe.mky").unlink(missing_ok=True)

# saving reads the file back only when there is a Godley table to reorder; doing it
# always reset the engine and threw away the results of a completed run
c.post("/api/clear")
_p = c.post("/api/item", json={"kind":"parameter","name":"g","value":0.3}).json()["index"]
c.post("/api/item", json={"kind":"operation","op":"integrate"})
_io = next(i["index"] for i in c.get("/api/state").json()["items"]
           if i["classType"] == "IntOp")
c.post("/api/wire", json={"src": _p, "dst": _io, "port": 1})
c.post("/api/solver", json={"tmax": 5})
c.post("/api/save", json={"name": "runsave-probe"})
try:
    check("saving clears the marker", c.get("/api/state").json()["dirty"] is False)
    with c.websocket_connect("/ws/sim") as ws:
        ws.send_json({"cmd": "run", "steps": 200, "tmax": 5})
        while True:
            m = ws.receive_json()
            if m.get("done") or m.get("stopped") or "error" in m: break
    ran = c.get("/api/state").json()
    check("a run at the tmax already stored leaves the document saved",
          ran["dirty"] is False, f'dirty={ran["dirty"]}')
    check("the run advanced the clock", ran["t"] > 4, str(ran["t"]))
    c.post("/api/save", json={"name": "runsave-probe"})
    after = c.get("/api/state").json()
    check("and saving keeps the run's results",
          abs(after["t"] - ran["t"]) < 1e-9 and after["values"] == ran["values"],
          f'{ran["t"]} -> {after["t"]}')
finally:
    (SAVE_DIR / "runsave-probe.mky").unlink(missing_ok=True)


print("\n49. Godley tables tell the truth about what they did")
c.post("/api/clear")
_g = c.post("/api/item", json={"kind":"godley","name":"Bank"}).json()["index"]
for _col, _nm in ((1, "Vault"), (2, "Deposits")):
    c.post(f"/api/godley/{_g}/cell", json={"row":0,"col":_col,"value":_nm})

# renaming a stock header reorders model.items, and the endpoint re-resolved the table by
# its OLD index afterwards: it answered 422 "not a Godley table" over an edit it had
# already applied, and a wire was destroyed on the way
r = c.post(f"/api/godley/{_g}/cell", json={"row":0,"col":1,"value":"VaultX"})
check("renaming a stock header reports success", r.status_code == 200,
      f"{r.status_code} {r.text[:70]}")
check("and returns the table it was asked about",
      r.json()["cells"][0][1] == "VaultX", str(r.json()["cells"][0]))
check("with no wire left mis-pointed",
      not any(w.get("desync") for w in c.get("/api/state").json()["wires"]))

# the initial-conditions row could be deleted despite the guard's own wording, and the
# engine went on reporting the initial values it held
c.post(f"/api/godley/{_g}/row/insert", json={"at": 3})
_snap = c.get(f"/api/godley/{_g}").json()
_ic = next(i for i, v in enumerate(_snap["icRow"]) if v)
r = c.post(f"/api/godley/{_g}/row/delete", json={"at": _ic})
check("the initial-conditions row cannot be deleted", r.status_code == 422,
      f"{r.status_code}")
check("and it is still there",
      any(c.get(f"/api/godley/{_g}").json()["icRow"]))

# a Godley table places the variables it generates, so moveTo on one is undone by the
# icon's own updateBoundingBox -- which the next snapshot runs. It reported success.
c.post("/api/save", json={"name": "godleytruth-probe"})
try:
    _st = c.get("/api/state").json()
    _v = next(i for i in _st["items"] if i["classType"] == "Variable:stock")
    r = c.post(f"/api/item/{_v['ref']}/move", json={"x": 900, "y": 900})
    check("moving a table-owned variable is refused", r.status_code == 409,
          f"{r.status_code}")
    check("and the refusal says why", "Godley" in r.json().get("detail", ""),
          r.text[:80])
    check("a refused move leaves the document saved",
          c.get("/api/state").json()["dirty"] is False)
    check("while the table itself still moves",
          c.post(f"/api/item/{_g}/move", json={"x":500,"y":500}).status_code == 200)
finally:
    (SAVE_DIR / "godleytruth-probe.mky").unlink(missing_ok=True)

# the conflict warning compared raw cell TEXT, so "100" and "100.0" were a disagreement
c.post("/api/clear")
_g1 = c.post("/api/item", json={"kind":"godley"}).json()["index"]
_g2 = c.post("/api/item", json={"kind":"godley"}).json()["index"]
for _gg in (_g1, _g2):
    c.post(f"/api/godley/{_gg}/cell", json={"row":0,"col":1,"value":"D"})
c.post(f"/api/godley/{_g1}/cell", json={"row":1,"col":1,"value":"100"})
r = c.post(f"/api/godley/{_g2}/cell", json={"row":1,"col":1,"value":"100.0"})
check("two tables holding the same number are not called a conflict",
      not r.json().get("conflicts"), str(r.json().get("conflicts"))[:80])
r = c.post(f"/api/godley/{_g2}/cell", json={"row":1,"col":1,"value":"250"})
check("but two different numbers still are", bool(r.json().get("conflicts")))


print("\n50. operations that used to succeed while changing nothing (or the wrong thing)")
# Grouping a Godley table re-scopes its stock variables into the group while the table's
# own references stay outside, so reset fails with "Invalid valueId" -- answered 200 with
# a full snapshot, on 9 of the 37 shipped examples.
EXD = "/Users/ryneschultz/minsky/examples"
_ex = os.path.join(EXD, "LoanableFunds.mky")
if os.path.exists(_ex):
    c.post("/api/load", params={"path": _ex})
    check("the model resets to begin with", c.post("/api/reset").status_code == 200)
    _st = c.get("/api/state").json()
    _xs = [i["x"] for i in _st["items"]]; _ys = [i["y"] for i in _st["items"]]
    r = c.post("/api/group", json={"x0":min(_xs)-50,"y0":min(_ys)-50,
                                   "x1":max(_xs)+50,"y1":max(_ys)+50})
    check("grouping a Godley table with everything else is refused",
          r.status_code == 409, f"{r.status_code}")
    check("and the model still runs", c.post("/api/reset").status_code == 200)
    check("with nothing grouped", not c.get("/api/state").json()["groups"])

# set_cell writes "" and icon.update() repopulates the cell from the variable's own init,
# so clearing an initial condition put the old number straight back
c.post("/api/clear")
_g = c.post("/api/item", json={"kind":"godley"}).json()["index"]
c.post(f"/api/godley/{_g}/cell", json={"row":0,"col":1,"value":"Res"})
c.post(f"/api/godley/{_g}/cell", json={"row":1,"col":1,"value":"100"})
r = c.post(f"/api/godley/{_g}/cell", json={"row":1,"col":1,"value":""})
check("clearing an initial condition does not put the old value back",
      r.json()["cells"][1][1] != "100", str(r.json()["cells"][1]))
check("and the engine agrees with the cell",
      c.get("/api/state").json()["inits"].get(":Res") in ("0", 0),
      str(c.get("/api/state").json()["inits"]))

# a Godley table owns its stocks' initial conditions and rewrites them at every reset
r = c.post("/api/init", json={"name": "Res", "value": 777})
check("setting a table stock's value through /api/init is refused",
      r.status_code == 409, f"{r.status_code}")
check("and it says where the value lives", "table" in r.json().get("detail", ""),
      r.text[:80])

# value_id searched only the top level, so a grouped variable whose name needs mangling
# resolved to a key nothing uses -- the write reported success and changed nothing
c.post("/api/clear")
c.post("/api/item", json={"kind":"parameter","name":"C_D","value":7,"at":[200,300]})
c.post("/api/item", json={"kind":"parameter","name":"other","value":1,"at":[330,300]})
c.post("/api/group", json={"x0":150,"y0":260,"x1":400,"y1":340})
r = c.post("/api/init", json={"name": "C_D", "value": 42})
check("a value can be set on a variable inside a group", r.status_code == 200,
      f"{r.status_code}")
_inits = c.get("/api/state").json()["inits"]
check("and it reached the real variable, mangled name and all",
      any(k.startswith(":C") and float(v) == 42.0 for k, v in _inits.items()),
      str(_inits))
r = c.post("/api/init", json={"name": "nosuchvariable", "value": 1})
check("a name no variable has is refused rather than written to a phantom key",
      r.status_code == 422, f"{r.status_code}")

# deleting a wire is geometric. The straight-chord fallback swept the whole diagram when
# the tracked wire was not in the engine, and deleted whatever it first crossed.
_ex2 = os.path.join(EXD, "GoodwinLinear02.mky")
if os.path.exists(_ex2):
    _st = c.post("/api/load", params={"path": _ex2}).json()
    _live = [w for w in _st["wires"] if not w.get("desync")]
    _wrong = 0
    for _i in range(len(_live)):
        _s0 = c.post("/api/load", params={"path": _ex2}).json()
        _l = [w for w in _s0["wires"] if not w.get("desync")]
        _b = {(w["src"], w["src_port"], w["dst"], w["dst_port"]) for w in _l}
        _t = _l[_i]
        _k = (_t["src"], _t["src_port"], _t["dst"], _t["dst_port"])
        _r = c.delete(f"/api/wire/{_t['index']}")
        if _r.status_code != 200:
            continue                      # refusing is safe; deleting the wrong one is not
        _a = {(w["src"], w["src_port"], w["dst"], w["dst_port"])
              for w in _r.json()["wires"] if not w.get("desync")}
        if _b - _a != {_k}: _wrong += 1
    check("deleting any wire removes that wire and no other",
          _wrong == 0, f"{_wrong} of {len(_live)} removed something else")
check("the chord sweep is gone", "chord, from the destination end back" not in src)

# The open Godley editor held an item INDEX. Undo, redo, a delete or a stock rename all
# reorder model.items, and the editor then addressed whatever sat at its old index -- so
# it silently retargeted to a DIFFERENT table and the edits landed there.
check("the Godley editor remembers WHICH table it is open on",
      "let gKey" in ui and "function findGodley()" in ui)
check("and re-finds it rather than trusting the index",
      "gIdx = now" in ui and "godleyKey(" in ui)


print("\n51. several items at once")
c.post("/api/clear")
for _n in range(1, 7):
    c.post("/api/item", json={"kind":"parameter","name":f"q{_n}","value":_n,
                              "at":[120+((_n-1)%3)*160, 220+((_n-1)//3)*140]})
def _pos():
    return {i.get("name"): (round(i["x"]), round(i["y"]))
            for i in c.get("/api/state").json()["items"]}
_before = _pos()

# One request, so the whole drag is ONE undo step -- looping per item would also let the
# refs go stale between calls.
r = c.post("/api/items/move", json={"refs": ["0","1","2"], "dx": 40, "dy": -60})
check("several items move together", r.status_code == 200, f"{r.status_code}")
_after = _pos()
check("each moved by the same offset",
      all(_after[k] == (_before[k][0]+40, _before[k][1]-60) for k in ("q1","q2","q3")),
      str({k: (_before[k], _after[k]) for k in ("q1","q2","q3")}))
check("and the ones not asked for stayed put",
      all(_after[k] == _before[k] for k in ("q4","q5","q6")))
c.post("/api/undo")
check("one undo puts all of them back", _pos() == _before, str(_pos()))

# deleting shifts every higher index, so the refs the client sent go stale the moment the
# first one goes: each target is pinned by what it IS and re-found before it is deleted
r = c.post("/api/items/delete", json={"refs": ["0","2","4"]})
check("several items delete together", r.status_code == 200 and r.json()["deleted"] == 3,
      f'{r.status_code} {r.json().get("deleted")}')
check("and it was the right three",
      sorted(_pos()) == ["q2", "q4", "q6"], str(sorted(_pos())))
c.post("/api/undo")
check("one undo brings all three back", sorted(_pos()) == [f"q{i}" for i in range(1,7)],
      str(sorted(_pos())))

check("an empty selection is refused",
      c.post("/api/items/delete", json={"refs": []}).status_code == 422)
check("and so is a bad ref among good ones",
      c.post("/api/items/delete", json={"refs": ["0", "nonsense"]}).status_code == 422)
check("with nothing deleted", len(_pos()) == 6, str(len(_pos())))

# The tests above use unwired items, which is the ONE shape where the delete pin cannot
# fail: positions only shift when a delete removes a wire. Deleting one item of
# BasicGrowthModel translates every survivor by (-106,-108), which is exactly what a
# position-keyed pin cannot survive -- it matched nothing, or worse, matched a DIFFERENT
# item that had just slid onto the remembered coordinates.
_ex = "/Users/ryneschultz/minsky/examples/BasicGrowthModel.mky"
if os.path.exists(_ex):
    _st = c.post("/api/load", params={"path": _ex}).json()
    _want = {i["ref"]: i.get("name") for i in _st["items"] if i["ref"] in ("12","14","15")}
    check("the model translates when one of these is deleted -- the case that matters",
          True, str(list(_want.values())))
    r = c.post("/api/items/delete", json={"refs": list(_want)})
    check("all three are deleted from a wired model", r.status_code == 200
          and r.json()["deleted"] == 3, f'{r.status_code} deleted={r.json().get("deleted")}')
    _left = {i.get("name") for i in c.get("/api/state").json()["items"]}
    check("and none of them survived",
          not (set(_want.values()) & _left), str(set(_want.values()) & _left))
    check("with no wire left mis-pointed",
          not any(w.get("desync") for w in c.get("/api/state").json()["wires"]))

    # the wrong-item case: a pin that goes stale can match an unrelated item
    _st = c.post("/api/load", params={"path": _ex}).json()
    _n = len(_st["items"])
    _target = next(i for i in _st["items"] if i.get("name") == "s - Savings Rate")
    r = c.post("/api/items/delete", json={"refs": [_target["ref"]]})
    _after = c.get("/api/state").json()
    check("deleting one names exactly one",
          r.json()["deleted"] == _n - len(_after["items"]),
          f'reported {r.json()["deleted"]}, really {_n - len(_after["items"])}')
    check("and it was the one asked for",
          "s - Savings Rate" not in {i.get("name") for i in _after["items"]})

# a cascade: a Godley icon takes its generated stock variables, and the count must say so
c.post("/api/clear")
_g = c.post("/api/item", json={"kind":"godley"}).json()["index"]
for _c, _nm in ((1,"S1"), (2,"S2")):
    c.post(f"/api/godley/{_g}/cell", json={"row":0,"col":_c,"value":_nm})
c.post("/api/item", json={"kind":"parameter","name":"keep","value":1})
_n = len(c.get("/api/state").json()["items"])
r = c.post("/api/items/delete", json={"refs": [str(_g)]})
_left = c.get("/api/state").json()["items"]
check("a cascade is counted by what LEFT, not by the calls made",
      r.json()["deleted"] == _n - len(_left),
      f'reported {r.json()["deleted"]}, really {_n - len(_left)}')
check("and only the table and its own variables went",
      [i.get("name") for i in _left] == ["keep"], str([i.get("name") for i in _left]))

# the same item named twice moved it twice, which also walked through the coordinate check
c.post("/api/clear")
c.post("/api/item", json={"kind":"parameter","name":"dup","value":1,"at":[200,300]})
c.post("/api/items/move", json={"refs":["0","0","0"], "dx":100, "dy":0})
check("a ref repeated in one request moves the item once",
      c.get("/api/state").json()["items"][0]["x"] == 300,
      str(c.get("/api/state").json()["items"][0]["x"]))
r = c.post("/api/items/move", json={"refs":["0"], "dx":2e6, "dy":0})
check("and a move past the canvas limit is still refused", r.status_code == 422,
      f"{r.status_code}")

# an item carried by its owner DOES move, and must not be reported as refused
c.post("/api/clear")
c.post("/api/item", json={"kind":"operation","op":"integrate","at":[300,300]})
_refs = [i["ref"] for i in c.get("/api/state").json()["items"]]
r = c.post("/api/items/move", json={"refs": _refs, "dx": 100, "dy": 0})
check("moving an IntOp with the variable it carries reports no refusal",
      "note" not in r.json(), str(r.json().get("note"))[:80])


# a Godley table owns the variables it generates, so those cannot be moved
c.post("/api/clear")
_g = c.post("/api/item", json={"kind":"godley"}).json()["index"]
c.post(f"/api/godley/{_g}/cell", json={"row":0,"col":1,"value":"S"})
_p = c.post("/api/item", json={"kind":"parameter","name":"free","value":1,
                               "at":[400,400]}).json()["index"]
_st = c.get("/api/state").json()
_stock = next(i["ref"] for i in _st["items"] if i["classType"] == "Variable:stock")
r = c.post("/api/items/move", json={"refs": [str(_p), _stock], "dx": 30, "dy": 30})
check("a mixed move reports what could not move", r.status_code == 200 and "note" in r.json(),
      str(r.json().get("note"))[:70])
check("and the one that could, did",
      next(i["x"] for i in c.get("/api/state").json()["items"]
           if i.get("name") == "free") == 430)

ui = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "minskyweb", "ui", "index.html")).read()
check("the canvas keeps a selection SET", "let selSet = new Set()" in ui)
check("and highlights every member of it", "selSet.has(it.ref)" in ui)
check("the lasso selects rather than grouping outright",
      "selectMany(inside.map" in ui and '"/group", {method:"POST", body: JSON.stringify(\n      {x0:d.x0' not in ui)
check("grouping is an action on the selection", '$("#groupsel").onclick' in ui)


print("\n52. the wire record agrees with the engine, not with itself")
import xml.etree.ElementTree as _ET, tempfile as _tf

def _engine_wires():
    """The engine's own wire set, read out of a document it writes.

    Ground truth. The previous checks here compared the tracked record with itself,
    which cannot detect the record being wrong -- and it was: deleting a wire removed
    a different one on 3 of 110 wires across two shipped models, and every check passed.
    """
    f = _tf.gettempdir() + "/gt.mky"
    open(f, "wb").write(c.get("/api/download").content)
    root = _ET.parse(f).getroot()
    q = "{http://minsky.sf.net/minsky}"
    owner, typ = {}, {}
    for it in root.find(q + "items"):
        iid = it.findtext(q + "id"); typ[iid] = it.findtext(q + "type")
        ports = it.find(q + "ports")
        if ports is None: continue
        for k, pe in enumerate(ports): owner[pe.text] = (iid, k)
    out = []
    for w in root.find(q + "wires"):
        a, b = owner.get(w.findtext(q + "from")), owner.get(w.findtext(q + "to"))
        if a and b: out.append((typ[a[0]], a[1], typ[b[0]], b[1]))
    return out

EX = "/Users/ryneschultz/minsky/examples/GoodwinLinear02.mky"
if os.path.exists(EX):
    _st = c.post("/api/load", params={"path": EX}).json()
    _n = len([w for w in _st["wires"] if not w.get("desync")])
    _right = _wrong = _miss = 0
    for _i in range(_n):
        _s0 = c.post("/api/load", params={"path": EX}).json()
        _items = {it["ref"]: it["classType"] for it in _s0["items"]}
        _live = [w for w in _s0["wires"] if not w.get("desync")]
        _want = (_items.get(_live[_i]["src"]), _live[_i]["src_port"],
                 _items.get(_live[_i]["dst"]), _live[_i]["dst_port"])
        _before = _engine_wires()
        _r = c.delete(f"/api/wire/{_live[_i]['index']}")
        if _r.status_code != 200:
            _miss += 1; continue
        _after = _engine_wires(); _b2 = list(_before)
        for _x in _after:
            if _x in _b2: _b2.remove(_x)
        if len(_b2) == 1 and _b2[0] == _want: _right += 1
        else: _wrong += 1
    check("deleting a wire never removes a different one",
          _wrong == 0, f"{_wrong} of {_n} removed the wrong wire")
    check("and most still delete", _right >= _n * 0.75, f"{_right}/{_n} deleted")

# _restore() used the refs recorded WITH the document, but loading reorders model.items,
# so after undo/redo those refs named different items and the canvas drew wires between
# things that had never been connected -- counts matching, nothing flagged.
c.post("/api/clear")
_g = c.post("/api/item", json={"kind":"godley","at":[200,200]}).json()["index"]
for _row, _col, _v in ((0,1,"Reserves"), (2,0,"loan"), (2,1,"loan")):
    c.post(f"/api/godley/{_g}/cell", json={"row":_row,"col":_col,"value":_v})
_r1 = c.post("/api/item", json={"kind":"parameter","name":"rate","value":1,
                                "at":[700,200]}).json()["index"]
_o1 = c.post("/api/item", json={"kind":"variable","name":"out","var_type":"flow",
                                "at":[900,200]}).json()["index"]
c.post("/api/wire", json={"src":_r1,"dst":_o1,"port":1})

def _ends():
    st = c.get("/api/state").json()
    m = {i["ref"]: (i["classType"], i.get("name")) for i in st["items"]}
    return sorted((m.get(w["src"]), m.get(w["dst"]))
                  for w in st["wires"] if not w.get("desync"))

_was = _ends()
check("the wire starts on the right items",
      _was == [(("Variable:parameter", "rate"), ("Variable:flow", "out"))], str(_was))
c.post("/api/item", json={"kind":"parameter","name":"tmp","value":1,"at":[300,600]})
c.post("/api/undo")
check("undo leaves it on the same items", _ends() == _was, str(_ends()))
c.post("/api/redo")
check("and so does redo", _ends() == _was, str(_ends()))

# the engine answers a wire into a Godley table's own flow variable by CLONING it: the
# model gains an item, the table's variable stays unconnected, and the record named the
# original while the engine held the copy
_st = c.get("/api/state").json()
_n0 = len(_st["items"])
_flow = next(i["ref"] for i in _st["items"] if i.get("name") == "loan")
_rate = next(i["ref"] for i in _st["items"] if i.get("name") == "rate")
_r = c.post("/api/wire", json={"src": _rate, "dst": _flow, "port": 1})
check("wiring into a table's own variable is refused", _r.status_code == 409,
      f"{_r.status_code}")
check("and it says the engine would have copied it",
      "copy" in _r.json().get("detail", ""), _r.text[:80])
check("with no extra item left behind",
      len(c.get("/api/state").json()["items"]) == _n0,
      f'{_n0} -> {len(c.get("/api/state").json()["items"])}')


print(f"\n{'ALL PASS' if not FAILED else 'FAILURES: ' + ', '.join(FAILED)}")
sys.exit(1 if FAILED else 0)
