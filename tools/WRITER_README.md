# NPLH events.json writer (tools/)

Status (Nov 4, 2026): committed to this repo and unit-tested. NOT yet proven by a live write: the first genuine, authorized content write through this tool is the end-to-end proof. NOT wired to any automatic runner: it runs only when a person or agent invokes it by hand. It does not touch the RSS workflow.

What it does: one guarded path for publishing approved events.json content.
GET current remote (main) -> parse -> compare content EXCLUDING root generatedAt -> if equal, NO-OP skip (never publish just to freshen the footer) -> otherwise stamp root generatedAt with the write time (PT, aware) and nothing else -> PUT with the remote sha -> read back and verify. A sha conflict aborts without retry.

Rules enforced in code:
- Identical content never produces a commit.
- Root updatedAt and every per-record field (checkedAt, status, etc.) pass through untouched.
- generatedAt is publish time, never verification or approval time.
- Output keeps the live byte format (indent=2, non-ASCII kept, trailing newline) so a write changes only the lines that really changed.
- Token comes from the GH_TOKEN environment variable only and is never printed.
- Content approval happens upstream; the tool publishes exactly the input file it is given.

Invocation (manual, supported):
  GH_TOKEN=... python3 tools/push_events.py --input approved_events.json [--message "..."] [--dry-run]
Use --dry-run first. The input must be the full approved events.json payload.

Tests (from the repo root):
  python3 tools/test_push_events.py
Five fake-client tests: no-op skip, write with preserved fields, idempotency, dry-run, conflict abort. They do not touch GitHub.

Files: tools/push_events.py, tools/payload_metadata.py (stamp helper), tools/test_push_events.py, this file.

Open items: automatic runner ownership and wiring (none yet), and retiring any older ad hoc edit scripts once this path has done a real write.
