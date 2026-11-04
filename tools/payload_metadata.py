"""Final outgoing payload generation time. Never verification or approval time."""
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo


def stamp_payload_generation(payload, *, generated_at=None):
    """Return outgoing content with only root generatedAt changed.

    Invoke after the final approved content diff, immediately before serialization.
    A prepared payload is not evidence it was uploaded. Callers own write/readback.
    Keep updatedAt and all per-record verification fields exactly as supplied.
    """
    now = generated_at or datetime.now(ZoneInfo('America/Los_Angeles'))
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('generation time must be timezone aware')
    result = deepcopy(payload)
    result['generatedAt'] = now.isoformat(timespec='seconds')
    return result
