"""Verifiable sortition (the lot).

draw(pool, k, beacon, purpose) ranks every candidate by
    r(x) = SHA-256(beacon || "|" || purpose || "|" || x)
and takes the k smallest. Anyone holding the same beacon gets the same draw.

The beacon must be a value nobody could know when the draw was requested:
the protocol uses a drand round (League of Entropy) declared in advance; the
offline verifier trusts the recorded value and `--online` re-fetches it.
"""
from __future__ import annotations

import hashlib


def rank(beacon: str, purpose: str, item: str) -> str:
    """64 lowercase hex characters; ranks are compared as strings."""
    return hashlib.sha256(f"{beacon}|{purpose}|{item}".encode("utf-8")).hexdigest()


def draw(pool: list[str], k: int, beacon: str, purpose: str) -> list[str]:
    """The first k distinct names of the pool in ascending rank. Depends on nothing but its arguments:
    not on the order of the pool, and not on the runtime (equal ranks, which would need a SHA-256
    collision, fall back to the names themselves)."""
    if type(k) is not int or k < 0 or k > len(pool):
        raise ValueError("k must be between 0 and len(pool)")
    return sorted(set(pool), key=lambda x: (rank(beacon, purpose, x), x))[:k]
