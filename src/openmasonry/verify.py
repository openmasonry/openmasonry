"""`python -P -m openmasonry.verify` — the verifier's entry point: what the judge and the audit run.

  --ledger DIR         the entries to replay (default: this repository's ledger/entries)
  --tree [--root DIR]  governed files of the tree must match the ratified pins, and every degree table
                       the ledger ever pinned must be archived (with --since: a pull request that holds
                       only entries of amendment ballots is let through a tree that does not, and the
                       reasons of its own corrections must be in the tree). Without --root, the reasons
                       of a ledger other than this repository's are read from reasons/ beside its
                       entries directory (DIR/../reasons), not from the repository's. With --root (also
                       without --tree), every replay of the run finds degree tables in DIR/canon/history/
                       too, each by its digest
  --base-root DIR      with --tree and --since: DIR is the tree of the base branch; what is unlawful in
                       the tree and unchanged from DIR is a warning (an unratified main is an alarm, not
                       a lock on the entries of a pull request)
  --candidate-root DIR replay the same ledger with the protocol core of the tree DIR (a candidate core, run
                       as a separate program) and require the same entries, head and state digest
  --online             the last entry is not dated ahead of this clock (more than FUTURE_TOLERANCE), and
                       every drand beacon the lot used is re-fetched (with --since: those of the new
                       entries)
  --clock-since SEQ    entries from SEQ on must be stamped close to the real time: at most
                       CLOCK_TOLERANCE behind it and JUDGE_FUTURE_TOLERANCE ahead
  --pr-author LOGIN --since SEQ [--pr-author-id N]
                       entries from SEQ on come from the GitHub account of their actor (the numeric
                       id N of the pull request's author is the member's; witness and custodian acts,
                       depart and rekey_object excepted), the key of a petition and the new key of a
                       rekey or of a key recovery are listed at github.com/<login>.keys, an invited
                       login is the GitHub account with the id its invitation states, a petition
                       comes from the invited account, and a genesis from the founder's account.
                       The entries before SEQ are taken on trust (their signatures and checkpoint
                       digests were verified when they were merged; a run without --since verifies
                       everything)
  --anchors-changed FILE
                       with --since: FILE holds `git diff --no-renames --name-status` of the pull
                       request for ledger/anchors/; each change must belong to a checkpoint
  --json               print the report as JSON (schema om.verify/1)

Exit status: 0 when every requested check passes, 1 otherwise, 2 for a malformed command line.

This module is part of the pinned core (`src/openmasonry/protocol.manifest`). It imports only pinned modules and
the standard library, and nothing in it depends on the command line `om`, which calls it for `om verify`.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import canon
from .ledger import (CLOCK_TOLERANCE, FUTURE_TOLERANCE, JUDGE_FUTURE_TOLERANCE, STATE_VERSION, Invalid, future_head,
                     iso, load, replay, ts)

CANDIDATE_TIMEOUT = 3600                # seconds a candidate core may take to replay the ledger

DEFAULT_LEDGER = canon.ROOT / "ledger" / "entries"


def verify_report(a, clock=None) -> dict:
    """Run every requested check; return {valid, message, problems, warnings, …} (schema om.verify/1). `clock`
    gives the real time to the two checks that read one (default: this machine's clock, in UTC); it is read
    once, before the replay, so the time a long replay takes is never held against a fresh entry."""
    now_real = (clock or (lambda: datetime.now(timezone.utc)))()
    out = {"schema": "om.verify/1", "valid": False, "entries": 0, "head": None, "state_sha256": None,
           "state_version": STATE_VERSION, "message": "", "problems": [], "warnings": []}
    since = getattr(a, "since", None)
    if any(type(n) is int and n < 0 for n in (a.clock_since, since)):
        return out | {"message": "USAGE — --clock-since and --since count entries from 0; a negative value is an error",
                      "problems": ["usage"]}
    try:
        entries = load(a.ledger)
        if not entries:
            return out | {"valid": True, "message": "ledger is empty (no genesis yet)"}
        # Entries before --since were verified when they were merged, and are verified in full by every run
        # without --since (the audit): here their signatures and checkpoint digests are taken on trust. The tree
        # named by --root may carry the archived degree table its new degree amendment names: every replay of
        # this run (also the identity step's) looks tables up there too, by digest, so it can add a table and
        # never change one.
        extra = [Path(a.root) / "canon" / "history"] if a.root is not None else []
        with canon.archives(*extra):
            st = replay(entries, trusted=since or 0)
    except Invalid as err:
        return out | {"message": f"INVALID — {err}", "problems": [str(err)]}
    out |= {"entries": st.seq + 1, "head": st.head, "state_sha256": st.digest()}
    if a.clock_since is not None:
        # New entries (seq >= N) must be stamped within [now - CLOCK_TOLERANCE, now + JUDGE_FUTURE_TOLERANCE].
        # Time is monotonic along the chain, so this keeps every claimed time honest when it is merged.
        late = [f"entry {e['seq']} claims {e['time']}" for e in entries[a.clock_since:]
                if not (now_real - CLOCK_TOLERANCE <= ts(e["time"]) <= now_real + JUDGE_FUTURE_TOLERANCE)]
        if late:
            return out | {"message": "STALE OR FUTURE TIME — " + late[0], "problems": late}
    if getattr(a, "pr_author_id", None) is not None and getattr(a, "pr_author", None) is None:
        return out | {"message": "USAGE — --pr-author-id goes with --pr-author and --since", "problems": ["usage"]}
    if getattr(a, "pr_author", None) is not None or since is not None:
        if a.pr_author is None or since is None:
            return out | {"message": "USAGE — --pr-author and --since go together", "problems": ["usage"]}
        from .identity import pr_problems
        with canon.archives(*extra):
            bad = pr_problems(entries, since, a.pr_author, author_id=getattr(a, "pr_author_id", None))
        if bad:
            return out | {"message": "WRONG AUTHOR OR KEY — " + bad[0], "problems": bad}
    changed = getattr(a, "anchors_changed", None)
    if changed is not None:
        if since is None:
            return out | {"message": "USAGE — --anchors-changed goes with --pr-author and --since", "problems": ["usage"]}
        from .govern import anchor_problems, parse_changes
        try:
            changes = parse_changes(Path(changed).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as err:
            return out | {"message": f"USAGE — cannot read {changed}: {err}", "problems": ["usage"]}
        bad = anchor_problems(entries, since, changes, a.root)
        if bad:
            return out | {"message": "UNLAWFUL ANCHOR — " + bad[0], "problems": bad}
    if a.online:
        # The audit of a ledger that is already merged: its last entry (the latest time, since time never goes
        # backwards) must not be dated ahead of the clock. Notice periods rest on honest timestamps.
        if future_head(st.time, now_real):
            ahead = (f"entry {st.seq} is dated {iso(st.time)}, more than {FUTURE_TOLERANCE.seconds // 60} minutes "
                     f"ahead of this clock ({iso(now_real)})")
            return out | {"message": "FUTURE HEAD — " + ahead, "problems": [ahead]}
        from .beacon import audit
        # Every beacon, or with --since those of the new entries: each lot entry recorded exactly one.
        old_beacons = sum(1 for e in entries[:since or 0] if e["type"] in ("exam_draw", "council_draw"))
        bad = audit(lot_beacons(entries)[old_beacons:])
        if bad:
            return out | {"message": "FORGED BEACON — " + bad[0], "problems": bad}
    note = ""
    candidate = getattr(a, "candidate_root", None)
    if candidate is not None:
        bad = candidate_problems(a.ledger, Path(candidate), out)
        if bad:
            return out | {"message": "CANDIDATE DIFFERS — " + bad[0], "problems": bad}
    base_root = getattr(a, "base_root", None)
    if base_root is not None and (not a.tree or since is None):
        return out | {"message": "USAGE — --base-root goes with --tree and --since", "problems": ["usage"]}
    if a.tree and base_root is not None and since is not None and Path(base_root).is_dir():
        from .govern import added_tables
        # The degree tables a pull request adds, the genesis pull request included: never let through as part of
        # an amendment-only pull request.
        bad = added_tables(Path(a.root) if a.root is not None else canon.ROOT, Path(base_root), entries, since)
        if bad:
            return out | {"message": "UNLAWFUL ARCHIVE — " + bad[0], "problems": bad}
    if a.tree:
        from .govern import REASONS_DIR, amendment_only, tree_report
        # Without --root, the reasons of a ledger other than this repository's are read beside its entries.
        reasons = (Path(a.ledger).resolve().parent / "reasons"
                   if a.root is None and Path(a.ledger).resolve() != DEFAULT_LEDGER.resolve() else None)
        problems, warnings = tree_report(st, a.root, entries, since, base_root, reasons)
        out["warnings"] = out["warnings"] + warnings
        # The public reasons (`correction …` and the names under the reasons directory) are never let through: an
        # amendment needs no file there, and a pull request of entries merges without review.
        folder = (reasons.name if reasons is not None else REASONS_DIR) + "/"
        if problems and since is not None and amendment_only(entries, since) \
                and not any(p.startswith(("correction ", folder)) for p in problems):
            # Only entries of amendment ballots: let through, so that the amendment that repairs the tree can pass.
            out["warnings"] = problems + out["warnings"]
            note = ("\nnote: the tree does not match the ratified pins; accepted because every new entry belongs "
                    "to an amendment ballot")
        elif problems:
            return out | {"message": "UNRATIFIED — " + problems[0], "problems": problems}
    now = st.time
    return out | {"valid": True, "message": (
        f"VALID — {st.name}: {st.seq + 1} entries, head {st.head[:16]}…\n"
        f"members {len(st.members)} · active {len(st.active(now))} · masters {len(st.masters(now))}"
        f" · founding phase {'yes' if st.founding_phase(now) else 'no'} · checkpoints {st.history['checkpoints'][0]}" + note)}


def lot_beacons(entries: list[dict]) -> list[dict]:
    """Every `{round, beacon}` a lot of a ledger that replays used, in order, read from its entries: an
    `exam_draw` uses the round of the latest `exam_open` of its candidate and degree, a `council_draw` the
    round of the latest `council_call`. The state keeps none of them (SPEC §4.11: the history of beacons)."""
    rounds: dict = {}
    out = []
    for e in entries:
        typ, body = e["type"], e["body"]
        if typ == "exam_open":
            rounds[(body["candidate"], body["degree"])] = body["beacon_round"]
        elif typ == "council_call":
            rounds["council"] = body["beacon_round"]
        elif typ == "exam_draw":
            out.append({"round": rounds[(body["candidate"], body["degree"])], "beacon": body["beacon"]})
        elif typ == "council_draw":
            out.append({"round": rounds["council"], "beacon": body["beacon"]})
    return out


def candidate_problems(ledger: Path, root: Path, mine: dict) -> list[str]:
    """replay `ledger` with the protocol core of the tree `root`, as a separate program (`python -P -m
    openmasonry.verify --json` with `root/src` as its only path), and compare its report with `mine`: it must
    be valid, with the same number of entries and the same head, and, when its state document has the same
    version, the same state digest. A core that changes the document (a new `state_version`) is held to the
    same head and is reported as a warning in `mine`. Nothing of `root` runs in this process."""
    src = Path(root) / "src"
    if not (src / "openmasonry" / "verify.py").is_file():
        return [f"{root} holds no protocol core (src/openmasonry/verify.py)"]
    env = {"PYTHONPATH": str(src.resolve()), "OM_NO_CACHE": "1", "PATH": os.environ.get("PATH", "")}
    try:
        run = subprocess.run([sys.executable, "-P", "-m", "openmasonry.verify", "--ledger", str(Path(ledger).resolve()),
                              "--json"], capture_output=True, text=True, env=env, cwd=str(Path(root).resolve()),
                             timeout=CANDIDATE_TIMEOUT)
        theirs = json.loads(run.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as err:
        return [f"the candidate core of {root} gave no report ({type(err).__name__}: {err})"]
    if type(theirs) is not dict:
        return [f"the candidate core of {root} gave no report"]
    if theirs.get("valid") is not True:
        return [f"the candidate core refuses the ledger: {theirs.get('message')}"]
    for name in ("entries", "head"):
        if theirs.get(name) != mine.get(name):
            return [f"the candidate core reaches {name} {theirs.get(name)!r}, the pinned core {mine.get(name)!r}"]
    version = theirs.get("state_version", 1)
    if version != mine.get("state_version"):
        mine["warnings"] = mine.get("warnings", []) + [
            f"the candidate core writes version {version} of the state document (this core: "
            f"{mine.get('state_version')}): the heads agree, the state digests were not compared"]
    elif theirs.get("state_sha256") != mine.get("state_sha256"):
        return [f"the candidate core reaches the state digest {theirs.get('state_sha256')}, the pinned core "
                f"{mine.get('state_sha256')} (a rule change must not change the replay of the entries already "
                "merged: branch it on a fixed future time or entry number written in the code, never on the protocol "
                "epoch alone)"]
    return []


def add_arguments(p: argparse.ArgumentParser) -> None:
    """The flags of the verifier, shared with `om verify`."""
    p.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    p.add_argument("--tree", action="store_true", help="also check governed files against ratified hashes")
    p.add_argument("--online", action="store_true",
                   help="also refuse a last entry dated ahead of this clock, and re-fetch every drand beacon used by "
                        "the lot")
    p.add_argument("--clock-since", type=int, metavar="SEQ",
                   help="entries from SEQ on must be stamped within CLOCK_TOLERANCE of now (CI: base branch length)")
    p.add_argument("--root", type=Path, default=None,
                   help="tree to check with --tree (default: this repository); the replay also finds degree tables "
                        "archived in its canon/history/, by digest")
    p.add_argument("--base-root", type=Path, default=None, metavar="DIR",
                   help="with --tree and --since: the base branch's tree; what is unlawful in --root and unchanged "
                        "from DIR is reported as a warning (an unratified main is an alarm, not a lock)")
    p.add_argument("--candidate-root", type=Path, default=None, metavar="DIR",
                   help="replay the ledger with the protocol core of the tree DIR too (a separate program) and "
                        "require the same entries, head and state digest")
    p.add_argument("--pr-author", metavar="LOGIN",
                   help="judge a pull request by LOGIN: new entries must come from the GitHub account of their actor "
                        "(witness and custodian acts, depart and rekey_object excepted), the key of a petition and "
                        "the new key of a rekey must be listed at github.com/<login>.keys, an invited login must be "
                        "the GitHub account its invitation states, a petition must come from the invited account and "
                        "a genesis from the founder's (network; fails closed)")
    p.add_argument("--since", type=int, metavar="SEQ", help="with --pr-author: entries from SEQ on are the PR's")
    p.add_argument("--pr-author-id", type=int, metavar="N",
                   help="with --pr-author: the numeric GitHub user id of the PR author, as the pull request event "
                        "gives it (looked up on GitHub when absent)")
    p.add_argument("--anchors-changed", type=Path, metavar="FILE",
                   help="with --since: the output of `git diff --no-renames --name-status` of the pull request for "
                        "ledger/anchors/; every change there must belong to a checkpoint")
    p.add_argument("--json", action="store_true", help="machine-readable result (schema om.verify/1)")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="openmasonry.verify", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(p)
    return p


def run(a) -> int:
    """Print the report for parsed arguments; return the exit status."""
    return show(a, verify_report(a))


def show(a, r: dict) -> int:
    """Print a report; return the exit status."""
    if a.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
    else:
        print(r["message"])
        for extra in r["problems"][1:]:
            print(f"  also: {extra}")
        for warning in r.get("warnings", []):
            print(f"  warning: {warning}")
    return 0 if r["valid"] else 1


def main(argv=None) -> int:
    return run(parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
