"""Idempotency utilities for sync operations.

Builds deterministic idempotency keys and ensures operations are never duplicated.
"""

def generate_idempotency_key(
    user_id: int | str,
    movie_id: int | str,
    source_provider: str,
    destination_provider: str,
    operation: str,
    content_hash: str,
) -> str:
    """Generate deterministic idempotency key.
    
    Format: {user}:{movie}:{source}:{destination}:{operation}:{content_hash}
    Strictly excludes timestamps and random UUIDs.
    """
    return f"{user_id}:{movie_id}:{source_provider.lower()}:{destination_provider.lower()}:{operation.lower()}:{content_hash}"
