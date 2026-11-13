"""Replay benchmark: how long replay and the state digest of each checkpoint take as a ledger grows.

Not part of the unittest suite (its name does not start with `test`). It builds synthetic ledgers with the
stub verifier of `tests.test_strict` (the "signature" of an entry is the key that must sign it), so no time
goes into Ed25519, and replays each one from nothing, timing every state digest a checkpoint asks for.

The ledgers are lawful under the rules of replay, with two limits of the genesis widened in this process
only (the number of founders and the size of the genesis entry), so that one genesis founds `--members`
Master Builders. Seven of them stay active; the others fall dormant after a year and stay electors of
every ballot, which is the largest state the protocol can reach for a number of members and of ballots.
The seven then run `--ballots` amendment ballots (each passes and pins a new path) while a witness posts a
checkpoint about every `--every` entries (and never twice within 72 minutes: at most 20 a day).

Run:  PYTHONPATH=src python3 tests/bench_replay.py [--members 100 1000 5000] [--ballots N] [--every N]
"""
from __future__ import annotations

import argparse
import hashlib
import resource
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from openmasonry import canon, ledger  # noqa: E402
from openmasonry.ledger import REVEAL_GAP, State, apply, commitment  # noqa: E402
from tests.test_protocol import salt_of  # noqa: E402
from tests.test_strict import Fast, by_key  # noqa: E402

CORE = 7                                  # the founders who stay active
MINUTE = timedelta(minutes=1)
URL = "https://example.org/work"


def widened(members: int):
    """The two limits a genesis of `members` founders needs, widened while the genesis is applied."""
    class Ctx:
        def __enter__(self):
            self.saved = canon.FOUNDING_MASTERS, ledger.MAX_GENESIS_BYTES
            canon.FOUNDING_MASTERS, ledger.MAX_GENESIS_BYTES = max(members, 7), 400 * members + 32 * 1024

        def __exit__(self, *exc):
            canon.FOUNDING_MASTERS, ledger.MAX_GENESIS_BYTES = self.saved
    return Ctx()


class Builder:
    def __init__(self, members: int, every: int):
        from tests.test_protocol import genesis_body, gid
        self.c, self.every = Fast(), every
        self.since_cp, self.last_cp = 0, None
        logins = [f"f{i:05d}" for i in range(members)]
        self.core = logins[:CORE]
        body = genesis_body(self.c, founders=[], witnesses=("tyler",))
        body["founders"] = [{"login": x, "key": self.c.key(x), "github_id": gid(x)} | ({"proof": self.c.key(x)} if i else {})
                            for i, x in enumerate(logins)]
        with widened(members):
            self.add("genesis", logins[0], body)

    def add(self, typ, actor, body, minutes: float = 1):
        self.c.now += minutes * MINUTE
        e = self.c.add(typ, actor, body)
        if typ == "genesis":
            self.st = State()
        apply(self.st, e, by_key)
        self.since_cp += 1
        if typ != "witness" and self.since_cp >= self.every and (
                self.last_cp is None or self.c.now - self.last_cp >= timedelta(minutes=72)):
            self.checkpoint()
        return e

    def checkpoint(self):
        self.since_cp, self.last_cp = 0, self.c.now + MINUTE
        st = self.st
        self.add("witness", "tyler", {"upto_seq": st.seq, "head": st.head, "state_sha256": st.digest(),
                                      "state_version": ledger.STATE_VERSION})

    def run(self, ballots: int):
        for day in range(0, 380, 20):              # a year and more: every founder outside the core is dormant
            for x in self.core:
                self.add("work", x, {"ref": f"{URL}/{day}/{x}"})
            self.c.now += timedelta(days=20)
        n = 0
        while n < ballots:
            ids = []
            for x in self.core:
                for _ in range(3):
                    if n < ballots:
                        bid = f"b{n}"
                        self.add("ballot_open", x, {"id": bid, "kind": "amendment", "commit_days": 2, "reveal_days": 1,
                                                    "subject": {"path": f"docs/bench/b{n}.md",
                                                                "new_sha256": hashlib.sha256(bid.encode()).hexdigest()}})
                        ids.append(bid)
                        n += 1
            for bid in ids:
                for x in self.core:
                    self.add("ballot_commit", x, {"id": bid, "commitment": commitment(bid, x, "yes", salt_of(x))})
            self.c.now = self.st.ballots[ids[0]].commit_until + REVEAL_GAP
            for bid in ids:
                for x in self.core:
                    self.add("ballot_reveal", x, {"id": bid, "vote": "yes", "salt": salt_of(x)})
            self.c.now = self.st.ballots[ids[-1]].reveal_until
            for bid in ids:
                self.add("ballot_close", self.core[0], {"id": bid})
        self.checkpoint()
        return self.c.entries


def replay_timed(entries, members: int):
    spent: list[float] = []
    real = State.digest

    def timed(self):
        t = time.perf_counter()
        try:
            return real(self)
        finally:
            spent.append(time.perf_counter() - t)
    State.digest = timed
    try:
        t0 = time.perf_counter()
        st = State()
        with widened(members):
            apply(st, entries[0], by_key)
        t1 = time.perf_counter()
        for e in entries[1:]:
            apply(st, e, by_key)
        t2 = time.perf_counter()
    finally:
        State.digest = real
    return st, t1 - t0, t2 - t1, spent


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--members", type=int, nargs="+", default=[100, 1000, 5000])
    ap.add_argument("--ballots", type=int, default=1000)
    ap.add_argument("--every", type=int, default=100, help="entries between two checkpoints (at least)")
    a = ap.parse_args()
    print(f"state version {ledger.STATE_VERSION}")
    print(f"{'members':>7} {'ballots':>7} {'entries':>7} {'ckpts':>5} {'build s':>8} {'genesis s':>9} "
          f"{'replay s':>8} {'digest ms mean':>14} {'max':>8} {'last':>8} {'scratch ms':>10} {'rss MB':>7}")
    for members in a.members:
        t = time.perf_counter()
        entries = Builder(members, a.every).run(a.ballots)
        build = time.perf_counter() - t
        st, gen, rep, spent = replay_timed(entries, members)
        scratch = getattr(ledger, "state_digest", None)
        if scratch is not None:
            t = time.perf_counter()
            assert scratch(st) == st.digest()
            scratch_ms = f"{(time.perf_counter() - t) * 1000:10.1f}"
        else:
            scratch_ms = f"{spent[-1] * 1000:10.1f}" if spent else "-"
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1 << 20 if sys.platform == "darwin" else 1 << 10)
        print(f"{members:7d} {a.ballots:7d} {len(entries):7d} {len(spent):5d} {build:8.1f} {gen:9.1f} {rep:8.1f} "
              f"{sum(spent) / len(spent) * 1000:14.1f} {max(spent) * 1000:8.1f} {spent[-1] * 1000:8.1f} "
              f"{scratch_ms} {rss:7.0f}", flush=True)


if __name__ == "__main__":
    main()
