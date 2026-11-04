#!/usr/bin/env python3
"""Supported single writer for the public events feed (PRIVATE STAGE - NOT WIRED, NOT PUSHED).

One guarded path for publishing approved events.json content to noe-events-data:
  GET current remote -> JSON roundtrip assert -> compare content EXCLUDING root generatedAt
  -> no-op skip when equal (never publish just to freshen the footer)
  -> stamp_payload_generation (sets root generatedAt only) -> PUT with sha -> readback verify.

Rules enforced here:
- No-op check is code, not documentation: identical content never produces a commit.
- Root updatedAt and every per-record field pass through untouched.
- generatedAt is generation/publish time, never verification or approval time.
- Token comes from the GH_TOKEN environment variable only and is never printed.
- Content approval happens upstream: this tool publishes exactly the input file it is given.

Approved-diff guard (code, not checklist): every real write requires --guard ARTIFACT. After the remote GET and
BEFORE the no-op check, the semantic diff remote->payload must equal artifact["changes"] EXACTLY, entry by entry:
(section, record id, field) AND old value AND new value. Any extra, missing, or value-mismatched change aborts with
zero writes. The guard checks consistency between payload, live remote and the artifact. It does NOT verify the owner
approval named in the artifact: the executor must check that message independently before running.

Usage:
  python3 tools/push_events.py --input events.json --dry-run          # read-only; no guard needed, never writes
  GH_TOKEN=... python3 tools/push_events.py --guard artifact.json [--dry-run]   # payload is artifact["payload"]
"""
import argparse, base64, json, os, sys, urllib.request, urllib.error

from payload_metadata import stamp_payload_generation

REPO = "noehome24-jpg/noe-events-data"
PATH = "events.json"
API = f"https://api.github.com/repos/{REPO}/contents/{PATH}"


class RemoteConflict(Exception):
    pass


class GuardError(Exception):
    pass


SECTIONS = ("events", "recurring", "happyHours")


class GitHubContentsClient:
    def __init__(self, token):
        self.token = token

    def _req(self, method, url, body=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        try:
            with urllib.request.urlopen(r) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 409:
                raise RemoteConflict("remote sha changed mid-write; aborting without retry")
            raise

    def get_file(self):
        meta = self._req("GET", API + "?ref=main")
        raw = base64.b64decode(meta["content"]).decode()
        parsed = json.loads(raw)  # roundtrip assert: remote must parse
        self.last_raw = raw
        return parsed, meta["sha"]

    def put_file(self, payload, sha, message):
        body = {
            "message": message,
            "content": base64.b64encode(serialize(payload).encode()).decode(),
            "branch": "main",
            "sha": sha,
        }
        return self._req("PUT", API, body)


def serialize(payload):
    """Match the live file byte format (indent=2, non-ASCII kept, trailing newline) so a write never reformats unrelated lines."""
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def strip_generation(payload):
    return {k: v for k, v in payload.items() if k != "generatedAt"}


def _index(records, key):
    ids = [x.get("id") if isinstance(x, dict) else None for x in records]
    if any(i in (None, "") for i in ids):
        raise GuardError(f"{key}: record without an id")
    if len(set(ids)) != len(ids):
        raise GuardError(f"{key}: duplicate record ids")
    return {x["id"]: x for x in records}, ids


def semantic_changes(remote, outgoing):
    """Flat {(section, id, field): (old, new)}; root generatedAt excluded; raises GuardError on order changes.

    Added record: every field (None -> value). Removed record: ("__removed__") (record -> None).
    Relative order of records present on both sides must be unchanged (new records may sit anywhere).
    """
    diffs = {}
    for key in SECTIONS:
        r, rids = _index(remote.get(key, []), key)
        o, oids = _index(outgoing.get(key, []), key)
        common = set(r) & set(o)
        if [i for i in rids if i in common] != [i for i in oids if i in common]:
            raise GuardError(f"{key}: relative order of existing records changed")
        for rid in sorted(set(r) | set(o)):
            if rid not in r:
                for f, v in o[rid].items():
                    diffs[(key, rid, f)] = (None, v)
            elif rid not in o:
                diffs[(key, rid, "__removed__")] = (r[rid], None)
            else:
                for f in sorted(set(r[rid]) | set(o[rid])):
                    if r[rid].get(f, _MISSING) != o[rid].get(f, _MISSING):
                        diffs[(key, rid, f)] = (r[rid].get(f), o[rid].get(f))
    for f in sorted(set(remote) | set(outgoing)):
        if f in SECTIONS or f == "generatedAt":
            continue
        if remote.get(f, _MISSING) != outgoing.get(f, _MISSING):
            diffs[("__root__", "", f)] = (remote.get(f), outgoing.get(f))
    return diffs


_MISSING = object()


def authorized_changes(artifact):
    """Parse artifact changes[] into {(section, id, field): (from, to)}. Every field needs explicit from AND to."""
    dest = artifact.get("destination") or {}
    if (dest.get("repo"), dest.get("branch"), dest.get("path")) != (REPO, "main", PATH):
        raise GuardError("artifact destination does not match this writer's repo/branch/path")
    if not (artifact.get("approval") or {}).get("message_id"):
        raise GuardError("artifact has no approval.message_id (executor must still verify that message independently)")
    allowed = {}
    for c in artifact.get("changes") or []:
        section = c.get("section")
        rid = c.get("record_id", "")
        if section not in SECTIONS + ("__root__",):
            raise GuardError(f"bad section {section!r}")
        if (section == "__root__") != (rid == ""):
            raise GuardError("record_id must be empty exactly for __root__ changes")
        fl = c.get("fields")
        if not fl:
            raise GuardError("change entry without fields")
        for f in fl:
            if not (isinstance(f, dict) and "field" in f and "from" in f and "to" in f):
                raise GuardError("each field must be {field, from, to}; field names alone are not enough")
            k = (section, rid, f["field"])
            if k in allowed:
                raise GuardError(f"duplicate authorized change {k}")
            allowed[k] = (f["from"], f["to"])
    if not allowed:
        raise GuardError("artifact authorizes no changes")
    if "generatedAt" in {k[2] for k in allowed if k[0] == "__root__"}:
        raise GuardError("generatedAt is stamped by the writer; it cannot be an authorized change")
    return allowed


def enforce_guard(artifact, remote, outgoing):
    """Return "WRITE" when payload-vs-live diff equals authorized changes exactly.

    Return "ALREADY_APPLIED" only when the diff is empty AND every authorized `to` value is what remote already holds
    (genuine idempotent re-run): the caller must not write. Anything else raises GuardError.
    """
    allowed = authorized_changes(artifact)
    actual = semantic_changes(remote, outgoing)
    if not actual:
        for (sec, rid, f), (_old, new) in allowed.items():
            if sec == "__root__":
                cur = remote.get(f)
            else:
                rec = {x.get("id"): x for x in remote.get(sec, [])}.get(rid)
                cur = None if rec is None else (rec.get("id") if f == "__removed__" else rec.get(f))
                if f == "__removed__":
                    cur = None if rec is None else rec
            if cur != new:
                raise GuardError(f"GUARD FAIL: payload equals live but authorized change {(sec, rid, f)} is not applied "
                                 "(wrong or stale payload); reconcile with main")
        return "ALREADY_APPLIED"
    extra = sorted(map(str, set(actual) - set(allowed)))
    missing = sorted(map(str, set(allowed) - set(actual)))
    wrong = sorted(str(k) for k in set(actual) & set(allowed) if actual[k] != allowed[k])
    if extra or missing or wrong:
        raise GuardError(f"GUARD FAIL: payload-vs-live diff != authorized changes. extra={extra} missing={missing} value_mismatch={wrong}")
    return "WRITE"


def assert_same_records(a, b):
    for key in ("events", "recurring", "happyHours"):
        ra, rb = a.get(key, []), b.get(key, [])
        assert [r.get("id") for r in ra] == [r.get("id") for r in rb], f"{key} id/order changed by stamping"


def publish(client, approved, message, dry_run=False, artifact=None):
    """Real writes REQUIRE an artifact (guard). Without one, only dry_run is allowed and nothing is ever written."""
    if artifact is None and not dry_run:
        raise GuardError("refusing to write without --guard artifact (approved-diff gate is mandatory for writes)")
    remote, sha = client.get_file()
    verdict = None
    if artifact is not None:
        verdict = enforce_guard(artifact, remote, approved)  # BEFORE the no-op check
        if verdict == "ALREADY_APPLIED":
            print("ALREADY APPLIED: payload equals live and every authorized change is present; no write")
            return {"written": False, "reason": "already-applied"}
    if strip_generation(remote) == strip_generation(approved):
        print("NO-OP: remote content identical except generatedAt; skipping write")
        return {"written": False, "reason": "no-op"}
    stamped = stamp_payload_generation(approved)
    assert_same_records(stamped, approved)
    assert stamped.get("updatedAt") == approved.get("updatedAt"), "updatedAt must pass through untouched"
    if dry_run:
        print("DRY RUN: would write stamped payload with sha", sha[:7], "guard:", verdict or "not run")
        return {"written": False, "reason": "dry-run", "guard": verdict, "stamped_generatedAt": stamped["generatedAt"]}
    client.put_file(stamped, sha, message)
    readback, new_sha = client.get_file()
    assert strip_generation(readback) == strip_generation(stamped), "readback content mismatch"
    assert readback["generatedAt"] == stamped["generatedAt"], "readback generatedAt mismatch"
    print(f"WROTE events.json commit-sha {new_sha[:7]} generatedAt {stamped['generatedAt']}")
    return {"written": True, "commit_sha": new_sha, "generatedAt": stamped["generatedAt"]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--guard", help="approved-payload artifact JSON; payload = artifact['payload']; required for writes")
    p.add_argument("--input", help="bare events.json; only for read-only --dry-run without a guard")
    p.add_argument("--message", default="Publish approved event content")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    if a.guard and a.input:
        sys.exit("use either --guard (payload inside the artifact) or --input, not both")
    if not a.guard and not (a.input and a.dry_run):
        sys.exit("a real write needs --guard ARTIFACT; --input is only allowed with --dry-run")
    token = os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("GH_TOKEN not set; refusing to run unauthenticated")
    artifact = json.load(open(a.guard)) if a.guard else None
    approved = artifact["payload"] if artifact else json.load(open(a.input))
    try:
        publish(GitHubContentsClient(token), approved, a.message, dry_run=a.dry_run, artifact=artifact)
    except GuardError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
