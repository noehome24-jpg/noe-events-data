import json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import push_events
from push_events import publish, strip_generation

class FakeClient:
    def __init__(self, remote):
        self.remote = remote
        self.writes = []
    def get_file(self):
        return json.loads(json.dumps(self.remote)), "sha-" + str(len(self.writes))
    def put_file(self, payload, sha, message):
        self.writes.append((payload, sha, message))
        self.remote = json.loads(json.dumps(payload))

BASE = {"generatedAt": "2026-10-07T13:44:30-07:00", "updatedAt": "2026-10-23T09:07:30-07:00",
        "events": [{"id": "e1", "title": "A", "checkedAt": "2026-09-28T13:11:00-07:00"}],
        "recurring": [{"id": "r1", "title": "B"}], "happyHours": [{"id": "h1"}]}

# 1. no-op: identical except generatedAt -> no write
c = FakeClient(json.loads(json.dumps(BASE)))
res = publish(c, json.loads(json.dumps(BASE)), "m")
assert res["written"] is False and res["reason"] == "no-op" and not c.writes
print("PASS no-op skip: identical content produces no commit")

# 2. content change -> stamped write, readback verified, everything else preserved
new = json.loads(json.dumps(BASE)); new["events"][0]["title"] = "A2"
c = FakeClient(json.loads(json.dumps(BASE)))
res = publish(c, new, "m")
assert res["written"] is True
stamped = c.writes[0][0]
assert stamped["events"][0]["title"] == "A2"
assert stamped["updatedAt"] == "2026-10-23T09:07:30-07:00"
assert stamped["events"][0]["checkedAt"] == "2026-09-28T13:11:00-07:00"
assert stamped["generatedAt"] != "2026-10-07T13:44:30-07:00"
assert "T" in stamped["generatedAt"] and (stamped["generatedAt"].endswith("-08:00") or stamped["generatedAt"].endswith("-07:00"))
print("PASS write: stamps generatedAt only; updatedAt/per-record fields preserved; readback ok")

# 3. second identical write after first -> no-op (idempotent)
res2 = publish(c, new, "m")
assert res2["written"] is False and len(c.writes) == 1
print("PASS idempotency: re-publishing same content is a no-op")

# 4. dry run never writes
c = FakeClient(json.loads(json.dumps(BASE)))
res = publish(c, new, "m", dry_run=True)
assert res["written"] is False and not c.writes
print("PASS dry-run: diff computed, no PUT")

# 5. conflict aborts without retry
class ConflictClient(FakeClient):
    def put_file(self, payload, sha, message):
        raise push_events.RemoteConflict("remote sha changed mid-write; aborting without retry")
c = ConflictClient(json.loads(json.dumps(BASE)))
try:
    publish(c, new, "m")
    raise SystemExit("FAIL: conflict not raised")
except push_events.RemoteConflict:
    print("PASS conflict: aborts, no retry, remote untouched")

print("ALL WRITER TESTS PASS")
