"""Fetch and check drand beacons (League of Entropy, quicknet chain).

The offline verifier trusts the beacon values recorded in the ledger. Witnesses
and `openmasonry verify --online` re-fetch every round and compare, so a
fabricated beacon is caught by anyone with an internet connection.
"""
from __future__ import annotations

import json
import urllib.request

from .ledger import DRAND_CHAIN

RELAYS = ("https://api.drand.sh", "https://api2.drand.sh", "https://drand.cloudflare.com")


def fetch(rnd: int, timeout: float = 10) -> str:
    last = None
    for relay in RELAYS:
        try:
            with urllib.request.urlopen(f"{relay}/{DRAND_CHAIN}/public/{rnd}", timeout=timeout) as r:
                return json.load(r)["randomness"]
        except Exception as err:  # try the next relay
            last = err
    raise RuntimeError(f"could not fetch drand round {rnd}: {last!r}")


def audit(beacons: list[dict], fetcher=None) -> list[str]:
    """Return mismatches between recorded beacons and the public drand chain."""
    fetcher = fetcher or fetch
    return [f"round {b['round']}: recorded {b['beacon'][:12]}… ≠ drand"
            for b in beacons if fetcher(b["round"]) != b["beacon"]]
