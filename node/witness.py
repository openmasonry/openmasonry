"""OpenMasonry witness node — the Tyler that never sleeps.

Every cycle:
  1. pull the canonical repository (fast-forward only);
  2. replay the full ledger; on failure, raise a capture alarm and stop. The same when its last entry
     is dated ahead of this node's clock (FUTURE HEAD), and when the canonical `main` no longer holds
     the entry this node verified earlier (ROLLBACK): the node remembers the head it verified in a
     small file outside the clone, and a `main` that is only shorter (BEHIND) makes it wait;
  3. close any pull request of its own that can no longer merge (another entry took
     its place in the sequence); while a live one is open, only verify, so the chain
     never forks;
  4. compare the governed files with the ratified pins (capture alarm on a difference),
     and its own code (the files its own copy of `protocol.manifest` lists) with the
     ledger's `@protocol` pin: a witness running anything but the ratified core
     verifies and raises alarms, and signs nothing;
  5. execute what the protocol says is due (`ledger.due_actions`): close ballots
     whose reveal window ended and perform pending lots with the drand beacon;
  6. if entries that are not checkpoints exist since its last checkpoint, and that
     one is at least an hour old, sign a `witness` checkpoint with the Merkle root
     of all entry hashes, and anchor it with OpenTimestamps;
  7. push a branch and open an auto-merging PR (the Tyler re-verifies it).

This file is not part of the pinned core, and the only modules of `openmasonry` it
imports are: every rule it applies and every byte it signs comes from the core.

Environment:
  OM_WITNESS_REPO       path to the clone            (default /data/openmasonry)
  OM_WITNESS_NAME       witness name in the genesis  (required)
  OM_WITNESS_KEY        SSH private key path         (default /keys/witness)
  OM_WITNESS_INTERVAL   seconds between cycles       (default 3600; 0 = run once)
  OM_WITNESS_PUSH       "pr" | "direct" | "none"     (default pr)
  OM_WITNESS_HEADS      where the verified head is remembered (default: witness-heads.json beside the clone)
  OM_WITNESS_ACCEPT_GENESIS   the entry hash of a genesis to follow from now on, though the node verified
                        another history before (a fork, or another fraternity); set it once, then remove it
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(os.environ.get("OM_WITNESS_REPO", "/data/openmasonry"))
# Import the verifier baked into the image (OM_WITNESS_VERIFIER), never the code we just pulled.
sys.path.insert(0, os.environ.get("OM_WITNESS_VERIFIER") or str(REPO / "src"))

from openmasonry.beacon import fetch  # noqa: E402
from openmasonry.govern import check_tree, protocol_digest  # noqa: E402
from openmasonry.ledger import (PROTOCOL_PIN, STATE_VERSION, Invalid, append_signed, checkpoint_due, due_actions,  # noqa: E402
                                entry_hash, entry_order, future_head, head_verdict, iso, load, remember_head, replay,
                                strict_json, ts)

NAME = os.environ.get("OM_WITNESS_NAME", "")
KEY = Path(os.environ.get("OM_WITNESS_KEY", "/keys/witness"))
LEDGER = REPO / "ledger" / "entries"
ANCHORS = REPO / "ledger" / "anchors"
MODE = os.environ.get("OM_WITNESS_PUSH", "pr")
HEADS = Path(os.environ.get("OM_WITNESS_HEADS") or REPO.parent / "witness-heads.json")   # never inside the clone
ACCEPT_GENESIS = os.environ.get("OM_WITNESS_ACCEPT_GENESIS", "")
MAIN = "refs/remotes/origin/main"      # the canonical branch by its full name: a tag called origin/main can never stand for it


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {msg}", flush=True)


def git(*args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    if r.returncode != 0:
        if check:
            raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
        log(f"git {args[0]} failed (continuing with local copy): {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def gh(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], cwd=REPO, capture_output=True, text=True)


def sync() -> bool:
    """Fetch and fast-forward to the canonical main. False when the local copy may be stale."""
    ok = True
    for args in (("fetch", "--quiet", "origin"), ("pull", "--ff-only", "--quiet")):
        ok &= subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True).returncode == 0
    return ok


def own_prs() -> list[dict] | None:
    """Our open pull requests, or None when they cannot be listed (the caller then fails closed)."""
    if MODE != "pr" or not shutil.which("gh"):
        return []
    # GitHub search's `head:` qualifier is not a reliable prefix match, so list the open PRs and filter
    # by branch prefix here. Only branches of this repository count: a fork cannot pause the witness.
    r = gh("pr", "list", "--state", "open", "--limit", "500", "--json", "number,headRefName,isCrossRepository,mergeable")
    try:
        prs = json.loads(r.stdout) if r.returncode == 0 else None
    except ValueError:
        prs = None
    if not isinstance(prs, list):
        log(f"cannot list our PRs ({r.stderr.strip()[:120]}); assuming one is open (fail closed)")
        return None
    prefix = f"witness/{NAME}/"
    return [p for p in prs if isinstance(p, dict) and not p.get("isCrossRepository")
            and str(p.get("headRefName", "")).startswith(prefix)]


def lost_its_place(pr: dict) -> bool:
    """True when a pull request of ours can no longer merge: another entry took its seq.

    Two signs, either is enough: GitHub reports a conflict, or the branch no longer only *adds* entries
    on top of the canonical main (an entry file differs, or main holds entries the branch lacks, or
    nothing is left to add). When neither can be established the PR is left alone.
    """
    if pr.get("mergeable") == "CONFLICTING":
        return True
    try:
        diff = git("diff", "--no-renames", "--name-status", MAIN, f"refs/remotes/origin/{pr['headRefName']}", "--",
                   "ledger/entries")
    except RuntimeError as err:
        log(f"cannot compare {pr.get('headRefName')} with main ({str(err)[:120]}); leaving it open")
        return False
    changes = [line for line in diff.splitlines() if line.strip()]
    return not changes or any(not line.startswith("A") for line in changes)


def withdraw(pr: dict) -> bool:
    """Close a pull request of ours that lost its place, and remove its branch. False if it stays open."""
    number, branch = str(pr.get("number")), str(pr.get("headRefName"))
    r = gh("pr", "close", number, "--comment",
           f"Witness `{NAME}`: these entries no longer extend the head of the ledger (another entry took "
           "their place in the sequence). Closing; the work is redone on the new head.")
    if r.returncode != 0:
        log(f"could not close our stale PR #{number} ({r.stderr.strip()[:120]}); verifying only")
        return False
    log(f"closed our stale PR #{number} ({branch}): its entries no longer extend the ledger")
    git("push", "-q", "origin", "--delete", branch, check=False)
    return True


def anchor(root: str, seq: int) -> str | None:
    if not shutil.which("ots"):
        return None
    ANCHORS.mkdir(parents=True, exist_ok=True)
    f = ANCHORS / f"{seq:06d}.root"
    f.write_text(root + "\n")
    r = subprocess.run(["ots", "stamp", str(f)], capture_output=True, text=True)
    if r.returncode != 0:
        log(f"ots stamp failed: {r.stderr.strip()}")
        return None
    # A merged proof is never changed (the judge refuses it): upgrade a copy, outside the repository.
    return f"ledger/anchors/{f.name}.ots"


def canonical_entries() -> list[dict] | None:
    """The entries of the canonical `main` as last fetched, read from git and never from the working copy
    (which may hold entries of ours that are not merged). None when there is no such branch to read. Raises
    Invalid when what is there is not a ledger (the rules of the loader, SPEC section 2.7)."""
    try:
        listing = git("ls-tree", "-r", MAIN, "ledger/entries/")
    except RuntimeError:
        return None
    blobs = {}
    for line in listing.splitlines():
        meta, _, path = line.partition("\t")
        if len(meta.split()) == 3 and path.startswith("ledger/entries/"):
            blobs[path.removeprefix("ledger/entries/")] = meta.split()
    names = entry_order(blobs)
    if not names:
        return None
    for i, name in enumerate(names):
        if blobs[name][0] not in ("100644", "100755"):
            raise Invalid(i, f"ledger file {name} of origin/main must be a regular file, not a symlink or a directory")
    r = subprocess.run(["git", "-C", str(REPO), "cat-file", "--batch"], capture_output=True,
                       input="".join(blobs[n][2] + "\n" for n in names).encode())
    out, at, entries = r.stdout, 0, []
    for i, name in enumerate(names):               # each record: "<id> blob <size>", a line feed, the bytes, a line feed
        try:
            end = out.index(b"\n", at)
            size = int(out[at:end].split()[2])
            e = strict_json(out[end + 1:end + 1 + size])
            at = end + 2 + size
        except (ValueError, IndexError) as err:
            raise Invalid(i, f"cannot read {name} of origin/main: {err}") from None
        if type(e) is not dict or type(e.get("seq")) is not int or e["seq"] != i:
            raise Invalid(i, f"{name} of origin/main does not hold entry {i}")
        entries.append(e)
    return entries


def verified_head(st, now: datetime) -> tuple[str, str]:
    """Hold the canonical `main` against the head this node verified earlier (SPEC section 9.7), and remember
    its head when it stands. Returns ("ok", ""), ("wait", why) when `main` is only shorter than what was
    verified, or ("alarm", why): it does not verify, is dated ahead of the clock, no longer holds the entry
    this node verified, or starts from another genesis."""
    try:
        entries = canonical_entries()
        if not entries:
            return "ok", ""                          # nothing to compare: no branch to read
        hashes = [entry_hash(e) for e in entries]
        if st.hashes[:len(hashes)] != hashes:
            replay(entries)                          # not the ledger just replayed: verify it from its own genesis
    except Invalid as err:
        return "alarm", f"the canonical main does not verify: {err}"
    if future_head(ts(entries[-1]["time"]), now):
        return "alarm", (f"FUTURE HEAD — entry {len(entries) - 1} of the canonical main is dated {entries[-1]['time']}, "
                         f"ahead of this node's clock ({iso(now)})")
    try:
        store = json.loads(HEADS.read_text())
    except (OSError, ValueError):
        store = {}
    verdict, seq, h = head_verdict(store, hashes, st.hashes)
    if verdict in ("first", "ok") or ACCEPT_GENESIS == hashes[0]:
        new = remember_head(store, hashes)
        if new != store:
            tmp = HEADS.with_name(HEADS.name + ".tmp")
            tmp.write_text(json.dumps(new, indent=2) + "\n")
            os.replace(tmp, HEADS)
        return "ok", ""
    if verdict == "behind":
        return "wait", (f"BEHIND — the canonical main has {len(hashes)} entries, and this node verified entry {seq} "
                        f"(hash {h}) earlier: a shorter copy of the same history; verifying only until it holds that "
                        "entry again")
    if verdict == "rollback":
        return "alarm", (f"ROLLBACK — the canonical ledger no longer contains entry {seq} (hash {h}) that this witness "
                         "verified earlier")
    return "alarm", (f"DIFFERENT GENESIS — the canonical main starts from the genesis {hashes[0]}, which this witness "
                     "never verified (set OM_WITNESS_ACCEPT_GENESIS to that hash once to follow it)")


def alarm(err: Exception) -> None:
    log(f"CAPTURE ALARM — {err}")
    if shutil.which("gh"):
        r = gh("issue", "list", "--state", "open", "--label", "capture-alarm", "--json", "number", "--jq", "length")
        if r.returncode == 0 and r.stdout.strip() not in ("", "0"):
            return                                   # one open alarm is enough; do not spam every hour
        gh("issue", "create", "--title", f"Capture alarm from witness {NAME}", "--label", "capture-alarm",
           "--body", f"Witness `{NAME}` could not vouch for the ledger:\n\n" + "\n".join("    " + l for l in str(err).splitlines()))


def cycle() -> None:
    synced = sync()
    try:
        entries = load(LEDGER)
    except Invalid as err:
        alarm(err)
        return
    if not entries:
        log("no genesis yet")
        return
    try:
        st = replay(entries)
    except Invalid as err:
        alarm(err)
        return
    now = datetime.now(timezone.utc)
    if future_head(st.time, now):                  # the judge refuses such an entry: one that is merged did not pass it
        alarm(RuntimeError(f"FUTURE HEAD — entry {st.seq} is dated {iso(st.time)}, ahead of this node's clock ({iso(now)}): "
                           "notice periods rest on honest timestamps"))
        return
    verdict, why = verified_head(st, now)
    if verdict == "alarm":
        alarm(RuntimeError(why))
        return
    if verdict == "wait":
        log(why)
        return
    if NAME not in st.witnesses:
        log(f"'{NAME}' is not a witness of this ledger; verifying only")
        return
    if MODE != "none" and not synced:
        log("could not sync with origin; verifying only (writing on a stale copy would fork the chain)")
        return
    prs = own_prs()
    if prs is None:
        return
    # A PR of ours that lost a sequence race would keep us silent forever: withdraw it and start again
    # from the new head. Any PR of ours still open after that means the chain could fork: only verify.
    still_open = [p for p in prs if not lost_its_place(p)]
    for p in prs:
        if p not in still_open and not withdraw(p):
            still_open.append(p)
    if still_open:
        log("our previous PR is not merged yet; verifying only")
        return
    problems = check_tree(st, REPO, entries)
    if problems:
        alarm(RuntimeError("governed files differ from the ratified versions: " + "; ".join(problems)))
        return
    try:
        own = protocol_digest()                      # the code this process imported: what its own manifest lists
        shown = own[:12] + "…"
    except ValueError as err:                        # a listed file is missing or not a plain file, or the manifest is malformed
        own, shown = None, f"it cannot read ({err})"
    pinned = st.pins.get(PROTOCOL_PIN)
    if own != pinned:
        log(f"refusing to sign: this witness runs code {shown}, but the ledger's {PROTOCOL_PIN} pin is "
            f"{str(pinned)[:12]}… (rebuild the image from the ratified code); verifying only")
        return

    wrote = []
    now = datetime.now(timezone.utc)
    if st.time and now < st.time:
        log("the ledger holds entries stamped after our clock; waiting for the clock to catch up")
        return
    stop = st.witness_frozen(NAME, now)
    if stop is not None:                           # the protocol would refuse every entry of ours: sign nothing
        log(f"signing nothing: this witness is frozen until {st.span(stop)[1]:%Y-%m-%dT%H:%M:%SZ} "
            f"(correction {stop.seq}); verifying only")
        return
    halt = st.halted(now)
    if halt is not None:                           # the protocol lists no lot and no close as due, except the close of a
        log(f"the ledger is halted until {st.span(halt)[1]:%Y-%m-%dT%H:%M:%SZ} (correction {halt.seq}): "   # ballot that
            "no lot is drawn and no ordinary ballot closed; checkpoints go on")    # removes a custodian; checkpoints are accepted
    for typ, body in due_actions(st, now):         # the protocol decides what is due; we only execute
        try:
            if "_round" in body:
                body = {k: v for k, v in body.items() if k != "_round"} | {"beacon": fetch(body["_round"])}
            e, st = append_signed(LEDGER, st, typ, NAME, body, KEY)
        except (Invalid, RuntimeError) as err:   # drand unreachable, nothing to draw yet…: try next cycle
            log(f"{typ} skipped this cycle: {err}")
            continue
        wrote.append(e)
        log(f"{typ} #{e['seq']}")

    # The protocol says when a checkpoint is due: an entry that is not a checkpoint since our last one, and
    # that one at least an hour old (`ledger.checkpoint_due`). Anything else it would refuse.
    if checkpoint_due(st, NAME, max(datetime.now(timezone.utc), st.time)):
        root = st.entries_root()
        proof = anchor(root, st.seq)     # entries carry no null: without a proof the field is left out
        e, st = append_signed(LEDGER, st, "witness", NAME,      # the checkpoint covers every entry before it, and
                              {"upto_seq": st.seq, "head": st.head, "state_sha256": st.digest(),
                               "state_version": STATE_VERSION, "root": root}   # states their state
                              | ({"anchor": proof} if proof else {}), KEY)
        wrote.append(e)
        log(f"checkpoint up to {e['body']['upto_seq']} root {root[:16]}…")

    if not wrote:
        log(f"valid, head {st.head[:16]}… — nothing to do")
        return
    publish(wrote)


def publish(wrote: list[dict]) -> None:
    if MODE == "none":
        return
    git("add", "ledger")
    msg = f"witness({NAME}): " + ", ".join(f"{e['type']}#{e['seq']}" for e in wrote)
    if MODE == "direct":
        git("commit", "-q", "-m", msg)
        git("push", "-q", "origin", "HEAD")
        return
    branch = f"witness/{NAME}/{wrote[-1]['seq']:06d}-{int(time.time())}"
    try:
        git("checkout", "-q", "-b", branch)
        git("commit", "-q", "-m", msg)
        git("push", "-q", "origin", branch)
    except RuntimeError as err:
        log(f"could not publish: {err}")
        git("checkout", "-q", "main", check=False)
        git("reset", "-q", "--hard", MAIN, check=False)
        return
    for label, color in (("witness", "1D76DB"), ("capture-alarm", "B60205")):
        gh("label", "create", label, "--color", color, "--force")       # idempotent; needs Issues: write
    r = gh("pr", "create", "--fill", "--head", branch, "--label", "witness")
    if r.returncode != 0:
        log(f"could not open the PR ({r.stderr.strip()[:200]}); the branch {branch} stays pushed for a human")
    else:
        m = gh("pr", "merge", branch, "--auto", "--merge")
        if m.returncode != 0:
            log("auto-merge is unavailable (repository settings or plan); a maintainer must merge "
                f"{r.stdout.strip()} — until then this witness only verifies")
    git("checkout", "-q", "main")
    git("fetch", "--quiet", "origin", check=False)
    git("reset", "-q", "--hard", MAIN)            # our entries live on the PR branch until it merges


def main() -> int:
    if not NAME:
        print("set OM_WITNESS_NAME to this node's witness name", file=sys.stderr)
        return 2
    interval = int(os.environ.get("OM_WITNESS_INTERVAL", "3600"))
    while True:
        try:
            cycle()
        except Exception as err:  # keep the node alive; every failure is logged
            log(f"cycle error: {err!r}")
        if interval <= 0:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
