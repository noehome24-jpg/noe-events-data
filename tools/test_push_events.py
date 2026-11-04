import json, sys, pathlib, copy
sys.path.insert(0, str(pathlib.Path(__file__).parent / "tools"))
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import push_events
from push_events import publish, GuardError, serialize, semantic_changes, enforce_guard

J = lambda x: json.loads(json.dumps(x))

class FakeClient:
    def __init__(self, remote):
        self.remote = remote; self.writes = []; self.gets = 0
    def get_file(self):
        self.gets += 1
        return J(self.remote), "sha-" + str(len(self.writes))
    def put_file(self, payload, sha, message):
        self.writes.append((payload, sha, message)); self.remote = J(payload)

BASE = {"generatedAt": "2026-10-07T13:44:30-07:00", "updatedAt": "2026-10-23T09:07:30-07:00", "note": "n",
        "events": [{"id": "e1", "title": "Caf\u00e9 A", "checkedAt": "2026-09-28T13:11:00-07:00", "time": "10:30am \u2013 11:15am"},
                   {"id": "e2", "title": "B", "time": "noon"}, {"id": "e3", "title": "C"}],
        "recurring": [{"id": "r1", "title": "R"}], "happyHours": [{"id": "h1"}]}

def art(changes, payload, message_id="phonemsg-TEST"):
    return {"destination": {"repo": push_events.REPO, "branch": "main", "path": push_events.PATH},
            "approval": {"message_id": message_id}, "changes": changes, "payload": payload}

def ch(section, rid, *fields):
    return {"section": section, "record_id": rid, "fields": [{"field": f, "from": a, "to": b} for f, a, b in fields]}

def raises(fn, text=None):
    try: fn()
    except GuardError as e:
        assert text is None or text in str(e), str(e); return str(e)
    raise SystemExit("FAIL: GuardError not raised")

# change used below: e2.title B -> B2
new = J(BASE); new["events"][1]["title"] = "B2"
GOOD = [ch("events", "e2", ("title", "B", "B2"))]

# 1. no-op / dry-run behavior without guard
c = FakeClient(J(BASE)); r = publish(c, J(BASE), "m", dry_run=True)
assert r["written"] is False and r["reason"] == "no-op" and not c.writes
print("PASS 1 read-only dry-run without guard: no-op, no write")

# 2. real write without guard is refused BEFORE any GET (missing guard input cannot bypass)
c = FakeClient(J(BASE)); raises(lambda: publish(c, new, "m"), "refusing to write"); assert not c.writes and c.gets == 0
print("PASS 2 write without guard refused, zero GETs, zero writes")

# 3. unguarded dry-run on a real change never writes
c = FakeClient(J(BASE)); r = publish(c, new, "m", dry_run=True); assert r["reason"] == "dry-run" and not c.writes and r["guard"] is None
print("PASS 3 unguarded dry-run: reports would-write, never writes")

# 4. guarded write: exact match -> write; only generatedAt stamped; preservation, non-ASCII, ordering
c = FakeClient(J(BASE)); r = publish(c, new, "m", artifact=art(GOOD, new)); assert r["written"] and len(c.writes) == 1
w = c.writes[0][0]
assert w["updatedAt"] == BASE["updatedAt"] and w["events"][0]["checkedAt"] == BASE["events"][0]["checkedAt"]
assert [e["id"] for e in w["events"]] == ["e1", "e2", "e3"] and w["events"][0]["title"] == "Caf\u00e9 A"
assert w["generatedAt"] != BASE["generatedAt"] and w["events"][1]["title"] == "B2"
raw = serialize(w); assert "Caf\u00e9" in raw and "\\u00e9" not in raw and raw.endswith("}\n") and raw.startswith('{\n  "')
d = semantic_changes(BASE, w); assert list(d) == [("events", "e2", "title")]
print("PASS 4 guarded write: exact diff only, root/per-record fields preserved, non-ASCII kept, order kept")

# 5. idempotent re-run after the write: ALREADY_APPLIED, no new write
r = publish(c, new, "m", artifact=art(GOOD, new)); assert r["reason"] == "already-applied" and len(c.writes) == 1
print("PASS 5 already-applied: second run reports it, no extra write")

# 6. empty diff but authorized change NOT present (wrong/stale payload) -> GuardError, no write
c = FakeClient(J(BASE)); raises(lambda: publish(c, J(BASE), "m", artifact=art(GOOD, J(BASE))), "not applied"); assert not c.writes
print("PASS 6 empty diff with unapplied authorization: abort, not treated as license")

# 7. stale payload: remote gained an unrelated change after base -> guard aborts, zero writes
remote2 = J(BASE); remote2["events"][2]["title"] = "C-newer-remote"
c = FakeClient(remote2); msg = raises(lambda: publish(c, new, "m", artifact=art(GOOD, new)), "extra"); assert not c.writes
assert "e3" in msg
print("PASS 7 unrelated remote delta (would be reverted): abort, zero writes")

# 8. value mismatch: right field, wrong to-value
bad = [ch("events", "e2", ("title", "B", "OTHER"))]
c = FakeClient(J(BASE)); raises(lambda: publish(c, new, "m", artifact=art(bad, new)), "value_mismatch"); assert not c.writes
bad2 = [ch("events", "e2", ("title", "WRONG-OLD", "B2"))]
c = FakeClient(J(BASE)); raises(lambda: publish(c, new, "m", artifact=art(bad2, new)), "value_mismatch"); assert not c.writes
print("PASS 8 from/to equality enforced (wrong new value or wrong old value): abort")

# 9. extra and missing change; field names alone rejected
two = J(new); two["events"][2]["title"] = "C2"
c = FakeClient(J(BASE)); raises(lambda: publish(c, two, "m", artifact=art(GOOD, two)), "extra"); assert not c.writes
miss = GOOD + [ch("events", "e3", ("title", "C", "C2"))]
c = FakeClient(J(BASE)); raises(lambda: publish(c, new, "m", artifact=art(miss, new)), "missing"); assert not c.writes
nameonly = [{"section": "events", "record_id": "e2", "fields": ["title"]}]
c = FakeClient(J(BASE)); raises(lambda: publish(c, new, "m", artifact=art(nameonly, new)), "field, from, to"); assert not c.writes
print("PASS 9 extra change, missing change, name-only fields: abort")

# 10. add / remove record
add = J(BASE); add["events"].insert(1, {"id": "e9", "title": "New"})
addch = [ch("events", "e9", ("id", None, "e9"), ("title", None, "New"))]
c = FakeClient(J(BASE)); assert publish(c, add, "m", artifact=art(addch, add))["written"] and [e["id"] for e in c.writes[0][0]["events"]] == ["e1", "e9", "e2", "e3"]
rem = J(BASE); del rem["events"][2]
remch = [ch("events", "e3", ("__removed__", BASE["events"][2], None))]
c = FakeClient(J(BASE)); assert publish(c, rem, "m", artifact=art(remch, rem))["written"]
print("PASS 10 add (exact fields, position free) and remove (exact old record) work")

# 11. order change and duplicate ids rejected
swap = J(BASE); swap["events"][0], swap["events"][1] = swap["events"][1], swap["events"][0]
c = FakeClient(J(BASE)); raises(lambda: publish(c, swap, "m", artifact=art(GOOD, swap)), "order"); assert not c.writes
dup = J(BASE); dup["events"].append({"id": "e1"})
c = FakeClient(J(BASE)); raises(lambda: publish(c, dup, "m", artifact=art(GOOD, dup)), "duplicate"); assert not c.writes
print("PASS 11 reorder and duplicate ids: abort")

# 12. root metadata: updatedAt change must be authorized; generatedAt cannot be authorized
up = J(new); up["updatedAt"] = "2026-11-04T00:00:00-08:00"
c = FakeClient(J(BASE)); raises(lambda: publish(c, up, "m", artifact=art(GOOD, up)), "extra"); assert not c.writes
gen = GOOD + [ch("__root__", "", ("generatedAt", BASE["generatedAt"], "2026-11-04T00:00:00-08:00"))]
c = FakeClient(J(BASE)); raises(lambda: publish(c, new, "m", artifact=art(gen, new)), "generatedAt"); assert not c.writes
print("PASS 12 unauthorized updatedAt change and authorized generatedAt both rejected")

# 13. destination / approval sanity
a = art(GOOD, new); a["destination"]["branch"] = "dev"
c = FakeClient(J(BASE)); raises(lambda: publish(c, new, "m", artifact=a), "destination"); assert not c.writes
c = FakeClient(J(BASE)); raises(lambda: publish(c, new, "m", artifact=art(GOOD, new, message_id="")), "approval.message_id"); assert not c.writes
print("PASS 13 wrong destination / missing approval reference: abort")

# 14. base conflict on PUT aborts, no retry
class ConflictClient(FakeClient):
    def put_file(self, payload, sha, message):
        raise push_events.RemoteConflict("remote sha changed mid-write; aborting without retry")
c = ConflictClient(J(BASE))
try: publish(c, new, "m", artifact=art(GOOD, new)); raise SystemExit("FAIL: conflict not raised")
except push_events.RemoteConflict: print("PASS 14 base conflict on write: aborts, no retry")

print("ALL WRITER TESTS PASS")
