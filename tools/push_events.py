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

Usage:
  GH_TOKEN=... python3 tools/push_events.py --input approved_events.json [--dry-run]
"""
import argparse, base64, json, os, sys, urllib.request, urllib.error

from payload_metadata import stamp_payload_generation

REPO = "noehome24-jpg/noe-events-data"
PATH = "events.json"
API = f"https://api.github.com/repos/{REPO}/contents/{PATH}"


class RemoteConflict(Exception):
    pass


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


def assert_same_records(a, b):
    for key in ("events", "recurring", "happyHours"):
        ra, rb = a.get(key, []), b.get(key, [])
        assert [r.get("id") for r in ra] == [r.get("id") for r in rb], f"{key} id/order changed by stamping"


def publish(client, approved, message, dry_run=False):
    remote, sha = client.get_file()
    if strip_generation(remote) == strip_generation(approved):
        print("NO-OP: remote content identical except generatedAt; skipping write")
        return {"written": False, "reason": "no-op"}
    stamped = stamp_payload_generation(approved)
    assert_same_records(stamped, approved)
    assert stamped.get("updatedAt") == approved.get("updatedAt"), "updatedAt must pass through untouched"
    if dry_run:
        print("DRY RUN: would write stamped payload with sha", sha[:7])
        return {"written": False, "reason": "dry-run", "stamped_generatedAt": stamped["generatedAt"]}
    client.put_file(stamped, sha, message)
    readback, new_sha = client.get_file()
    assert strip_generation(readback) == strip_generation(stamped), "readback content mismatch"
    assert readback["generatedAt"] == stamped["generatedAt"], "readback generatedAt mismatch"
    print(f"WROTE events.json commit-sha {new_sha[:7]} generatedAt {stamped['generatedAt']}")
    return {"written": True, "commit_sha": new_sha, "generatedAt": stamped["generatedAt"]}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, help="approved events.json payload")
    p.add_argument("--message", default="Publish approved event content")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    token = os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("GH_TOKEN not set; refusing to run unauthenticated")
    approved = json.load(open(a.input))
    publish(GitHubContentsClient(token), approved, a.message, dry_run=a.dry_run)


if __name__ == "__main__":
    main()
