# NPLH supported feed writer - PRIVATE LOCAL STAGE (rebuilt Nov 4, 2026, 4:08am PT)

Status: PATCHED by deploy agent Nov 4 2026 4:10am PT (serialize() matches live byte format; branch main; GET ref=main). Not committed, not wired.

Contents:
- tools/payload_metadata.py - sourcing's reviewed stamp helper (unchanged from generatedat-private-stage-v2).
- tools/push_events.py - single supported writer for events.json: GET Contents -> JSON roundtrip assert -> content compare EXCLUDING root generatedAt -> enforced no-op skip -> stamp -> PUT with sha -> readback verify. Conflict aborts without retry. Token from GH_TOKEN env only, never printed. Content approval is upstream; this publishes exactly its input.
- test_push_events.py - 5 unit tests with a fake client (no-op, write+preserve, idempotency, dry-run, conflict). ALL PASS on this rebuild. Also validated against the real live 128/22/10 payload (no-op + one-change write path, IDs/order/stamps/updatedAt preserved).

Open before any wiring: decision where this lives versioned (proposal: tools/ in noe-events-data beside the RSS workflow); retiring ad-hoc /tmp writer scripts (deploy side); who runs it (sourcing publish flow).
