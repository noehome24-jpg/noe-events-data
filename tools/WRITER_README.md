# NPLH events.json writer (tools/)

Status (Nov 4, 2026): committed to this repo and unit-tested. NOT yet proven by a live write: the first genuine, authorized content write through this tool is the end-to-end proof. NOT wired to any automatic runner: it runs only when a person or agent invokes it by hand. It does not touch the RSS workflow.

What it does: one guarded path for publishing approved events.json content.
GET current remote (main) -> approved-diff GUARD -> compare content EXCLUDING root generatedAt -> if equal, NO-OP skip (never publish just to freshen the footer) -> otherwise stamp root generatedAt with the write time (PT, aware) and nothing else -> PUT with the remote sha -> read back and verify. A sha conflict aborts without retry.

Approved-diff guard (mandatory for every real write): the write needs --guard ARTIFACT. The semantic diff live->payload must equal the artifact's changes[] exactly: (section, record id, field) AND old value AND new value, no extra, no missing; order of existing records unchanged; no duplicate ids; destination must be this repo/main/events.json; generatedAt cannot be an authorized change. Any mismatch aborts with zero writes. If the diff is empty and every authorized new value is already live, it reports ALREADY APPLIED and does not write; if the diff is empty but an authorized change is not live, it aborts. Without --guard only a read-only --dry-run is allowed, and a real write is refused before any network call. The guard checks payload vs live vs artifact consistency only. It does NOT verify the owner approval the artifact cites: the executor must check that original message independently.

Rules enforced in code:
- Identical content never produces a commit.
- Root updatedAt and every per-record field (checkedAt, status, etc.) pass through untouched.
- generatedAt is publish time, never verification or approval time.
- Output keeps the live byte format (indent=2, non-ASCII kept, trailing newline) so a write changes only the lines that really changed.
- Token comes from the GH_TOKEN environment variable only and is never printed.
- Content approval happens upstream; the tool publishes exactly the input file it is given.

Invocation (manual, supported):
  GH_TOKEN=... python3 tools/push_events.py --guard artifact.json [--message "..."] --dry-run   # first
  GH_TOKEN=... python3 tools/push_events.py --guard artifact.json [--message "..."]             # real write
  GH_TOKEN=... python3 tools/push_events.py --input events.json --dry-run                        # read-only, no guard
The payload is artifact["payload"] (the full approved events.json). changes[] entries are
{"section": "events|recurring|happyHours|__root__", "record_id": "<id or empty>", "fields": [{"field": "...", "from": <old>, "to": <new>}]};
a new record lists every field from null; a removed record uses field "__removed__" with the old record as from and null as to.

Tests (from the repo root):
  python3 tools/test_push_events.py
Fourteen fake-client tests: no-op, guard-required refusal, dry-run, exact guarded write (preservation, non-ASCII, ordering), already-applied, unapplied authorization, stale remote delta, from/to mismatch, extra/missing/name-only changes, add/remove, reorder/duplicates, root metadata, destination/approval checks, base conflict. They do not touch GitHub.

Files: tools/push_events.py, tools/payload_metadata.py (stamp helper), tools/test_push_events.py, this file.

Open items: automatic runner ownership and wiring (none yet), and retiring any older ad hoc edit scripts once this path has done a real write.
