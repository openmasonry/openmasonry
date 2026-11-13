"""Governed files: the working tree must match what the ledger ratified.

Genesis pins the degree canon, the eternal Landmarks, the Constitution, the charters of the Custodian
and of the rooms, and the protocol core (`@protocol`). A pinned path may only change through an
amendment ballot that pins the SHA-256 of its new bytes; the eternal Landmarks can never be re-pinned.

`@protocol` is the digest of the files listed in the manifest (`src/openmasonry/protocol.manifest`) and
of nothing else: the code that decides what is valid, the manifest itself, and the workflows of the
repository (the judge, which runs that code on every pull request, and the Tyler, which audits `main`).
Code outside the list (the command line, the agents' tools, the witness node) is not pinned: it changes
by code-owner review and can never change a verdict, because the listed modules import only each other
and the standard library.

The manifest is data, read from the tree being checked, never from the code that checks it. The judge
runs the base branch's code on a pull request's tree; because that code reads the pull request's own
manifest, a tree whose list changed (a new module, a new workflow) has one digest for the old code and
for the new, and an amendment that ratifies that digest lets it through. A tree whose manifest was
changed without such an amendment simply has a digest the ledger does not pin.

The set of workflows is closed: a tree that holds anything under `.github/workflows/` besides the
files its manifest lists is unlawful (`stray_workflows`), since a new workflow could carry a job that
answers to the judge's name.

Corrections pin their public reason by digest: a pull request that adds a correction must bring
`ledger/reasons/<sha256>.md` for its `reason_sha256`, with exactly those bytes (`missing_reasons`); a
reason of an older correction that a tree no longer holds is reported as a warning, and one whose bytes are
not its name is unlawful. The directory must hold nothing else (`stray_reasons`): a pull request that adds entries may add reason
files without a review, so only a text that a signed correction pins is let in. Replay never opens the
files; this gate does. The reasons of a ledger other than the repository's, checked without a tree root, are
read from the directory `reasons/` beside its entries directory (the `reasons` argument).
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path

from . import canon
from .crypto import sha256
from .ledger import BALLOT_TYPES, DEGREES_PATH, GENESIS_PINS, PROTOCOL_PIN, State, fold

MANIFEST = "src/openmasonry/protocol.manifest"       # the list of the pinned core, itself on the list
MANIFEST_REQUIRED = (MANIFEST, "src/openmasonry/govern.py")   # the list, and the code that reads it
MANIFEST_MAX_BYTES = 64 * 1024
# One path of the manifest: 1 to 10 segments of letters, digits, `.`, `_` and `-`, separated by `/`.
MANIFEST_PATH_RE = re.compile(r"[A-Za-z0-9._-]{1,100}(?:/[A-Za-z0-9._-]{1,100}){0,9}")
WORKFLOWS_DIR = ".github/workflows"     # nothing may exist here besides the workflows the manifest lists
REASONS_DIR = "ledger/reasons"          # the public reason of every correction, one file named after its sha256
REASONS_KEEP = ".gitkeep"               # the only other name allowed in that directory
REASON_MAX_BYTES = 64 * 1024            # a reason is a text for people to read, not an archive
ANCHORS_DIR = "ledger/anchors"          # the roots a witness anchored, and their proofs
HISTORY_DIR = "canon/history"           # every degree table ever pinned, named after its sha256
ANCHOR_MAX_BYTES = 16 * 1024            # a root is one line and a proof a few hundred bytes
# How an OpenTimestamps proof of a file begins: the header of the format, its major version (1) and the
# operation that hashed the file (0x08, SHA-256); the 32 bytes of that digest follow.
OTS_PREFIX = b"\x00OpenTimestamps\x00\x00Proof\x00\xbf\x89\xe2\xe8\x84\xe8\x92\x94" + b"\x01" + b"\x08"


class UnsafeTree(ValueError):
    """A governed or protocol path is missing, is not a regular file, is a symlink or escapes the tree, or
    the manifest of the pinned core is malformed."""


def _safe_file(root: Path, p: Path) -> Path:
    """Refuse symlinks anywhere on the path, and anything resolving outside the tree."""
    rel = p.relative_to(root)
    cur = root
    for part in rel.parts:
        cur = cur / part
        if cur.is_symlink():
            raise UnsafeTree(f"{rel.as_posix()} is (or passes through) a symlink")
    if not p.resolve().is_relative_to(root.resolve()):
        raise UnsafeTree(f"{rel.as_posix()} resolves outside the tree")
    return p


def _read(root: Path, rel: str) -> bytes:
    """The bytes of the regular file `rel` of the tree, reached through no symlink (`UnsafeTree` otherwise)."""
    path = _safe_file(root, root / rel)
    try:
        if not stat.S_ISREG(os.lstat(path).st_mode):
            raise UnsafeTree(f"{rel} is not a regular file")
        return path.read_bytes()
    except FileNotFoundError:
        raise UnsafeTree(f"{rel} is missing") from None
    except OSError as err:
        raise UnsafeTree(f"{rel} cannot be read: {err.strerror or err}") from None


def parse_manifest(data: bytes) -> tuple[str, ...]:
    """The paths a manifest lists, in its order. Pure. `UnsafeTree` unless the bytes have the one form:

    ASCII, one repository-relative path per line, every line ended by a line feed (no carriage return, no
    blank line, no comment, no space), paths in strictly ascending order of their bytes (so none twice), no
    two of them equal up to case, and among them the manifest itself and `src/openmasonry/govern.py`.
    """
    def bad(why: str) -> UnsafeTree:
        return UnsafeTree(f"{MANIFEST}: {why}")
    if len(data) > MANIFEST_MAX_BYTES:
        raise bad(f"larger than {MANIFEST_MAX_BYTES} bytes")
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        raise bad("holds a byte outside ASCII") from None
    if not text.endswith("\n"):
        raise bad("must end with a line feed (and cannot be empty)")
    lines = text[:-1].split("\n")
    for n, line in enumerate(lines, 1):
        if MANIFEST_PATH_RE.fullmatch(line) is None or any(part in (".", "..") for part in line.split("/")):
            raise bad(f"line {n} is not a safe relative path (segments of letters, digits, . _ - joined by /; "
                      "no blank line, comment, space or carriage return)")
        if n > 1 and not lines[n - 2] < line:
            raise bad(f"line {n} is not after line {n - 1} (paths are strictly sorted, so none is listed twice)")
    folded: dict[str, int] = {}
    for n, line in enumerate(lines, 1):
        if fold(line) in folded:
            raise bad(f"lines {folded[fold(line)]} and {n} differ only by case")
        folded[fold(line)] = n
    for rel in MANIFEST_REQUIRED:
        if rel not in lines:
            raise bad(f"does not list {rel}")
    return tuple(lines)


def read_manifest(root: Path | None = None) -> tuple[str, ...]:
    """The pinned core of the tree at `root` (default: this repository): the paths its own manifest lists."""
    root = canon.ROOT if root is None else Path(root)
    return parse_manifest(_read(root, MANIFEST))


def protocol_digest(root: Path | None = None) -> str:
    """The `@protocol` digest of the tree at `root` (default: this repository).

    One SHA-256 over the files the tree's manifest lists, in the manifest's order. Each file contributes
    four fields: the length of its path in bytes, the path, the length of its content in bytes, the content.
    Both lengths are unsigned 64-bit big-endian integers, so no two different trees give the same input.
    The manifest is one of the listed files, so the list itself is hashed. Every listed path must be a
    regular file reached through no symlink, and the manifest must be well formed (`UnsafeTree` otherwise).
    Nothing else is read: no directory is listed and no program is run.
    """
    root = canon.ROOT if root is None else Path(root)
    manifest = _read(root, MANIFEST)
    h = hashlib.sha256()
    for rel in parse_manifest(manifest):
        data = manifest if rel == MANIFEST else _read(root, rel)
        name = rel.encode("ascii")
        h.update(len(name).to_bytes(8, "big") + name + len(data).to_bytes(8, "big") + data)
    return h.hexdigest()


def stray_workflows(root: Path | None = None) -> list[str]:
    """Every name directly under `.github/workflows/` of the tree that the tree's manifest does not list,
    sorted: a file, a directory or a link alike. A manifest that cannot be read lists nothing, so every name
    is a stray. The listed files themselves are judged by `protocol_digest`."""
    root = canon.ROOT if root is None else Path(root)
    try:
        names = os.listdir(root / WORKFLOWS_DIR)
    except FileNotFoundError:
        return []                           # no directory: any listed workflow is missing, which the digest reports
    except OSError as err:
        return [f"{WORKFLOWS_DIR} ({err.strerror or err})"]
    try:
        listed = set(read_manifest(root))
    except UnsafeTree:
        listed = set()
    return sorted(rel for rel in (f"{WORKFLOWS_DIR}/{name}" for name in names) if rel not in listed)


def cited_reasons(st: State, entries: list[dict] | None = None) -> list[tuple[int, str]]:
    """`(seq, reason_sha256)` of every correction of the ledger, notes included, in order. Read from the
    entries when the caller holds them; from the state otherwise, which keeps only the newest notes."""
    if entries is not None:
        return [(e["seq"], e["body"]["reason_sha256"]) for e in entries
                if e.get("type") == "correction" and type(e.get("body")) is dict
                and type(e["body"].get("reason_sha256")) is str]
    return sorted([(seq, c.reason_sha256) for seq, c in st.corrections.items()]
                  + [(n["seq"], n["reason_sha256"]) for n in st.notes])


def _reasons_at(root: Path | None, reasons: Path | None) -> tuple[Path, str]:
    """`(base, rel)`: the reasons are the directory `base / rel`, and no path is followed out of `base`. The
    tree's `ledger/reasons/` (REASONS_DIR), or, given `reasons`, that directory (named `reasons/…`)."""
    if reasons is not None:
        return Path(reasons).parent, Path(reasons).name
    return (canon.ROOT if root is None else Path(root)), REASONS_DIR


def missing_reasons(st: State, root: Path | None = None, entries: list[dict] | None = None,
                    since: int | None = None, reasons: Path | None = None) -> tuple[list[str], list[str]]:
    """`(violations, warnings)` about the public reasons of the corrections of the ledger. The file
    `ledger/reasons/<reason_sha256>.md` must be a regular file, reached through no symlink, of at most
    REASON_MAX_BYTES bytes, whose SHA-256 is its name. A file that is there and is not that is a violation,
    whatever the age of its correction. A file that is missing is a violation for a correction added by the
    pull request being judged (`seq >= since`), and a warning for an older one, or when nothing is being
    judged (`since` is None): a reason need not be kept forever for a tree to be lawful. In the order of
    the corrections. `reasons`: read them from that directory instead of the tree's `ledger/reasons/` (the
    reasons of a ledger other than the repository's, archived beside its entries directory)."""
    root, folder = _reasons_at(root, reasons)
    problems, warnings = [], []
    for seq, digest in cited_reasons(st, entries):
        rel = f"{folder}/{digest}.md"
        try:
            path = _safe_file(root, root / rel)
            if (path.exists() or path.is_symlink()) and os.lstat(path).st_size > REASON_MAX_BYTES:
                problems.append(f"correction {seq}: {rel} is larger than {REASON_MAX_BYTES} bytes")
                continue
            actual = sha256(_read(root, rel))
        except UnsafeTree as err:
            if str(err).endswith("is missing"):
                new = since is not None and seq >= since
                (problems if new else warnings).append(
                    f"correction {seq}: {err} (the public reason of a correction is archived under its sha256)")
            else:
                problems.append(f"correction {seq}: {err}")
            continue
        if actual != digest:
            problems.append(f"correction {seq}: {rel} has sha256 {actual[:12]}…, which is not its name")
    return problems, warnings


def stray_reasons(st: State, root: Path | None = None, entries: list[dict] | None = None,
                  reasons: Path | None = None) -> list[str]:
    """Every name directly under `ledger/reasons/` of the tree (or the directory `reasons`, when given) that is
    not the reason of a correction of the ledger (`<reason_sha256>.md`), sorted: a file, a directory or a link
    alike; `.gitkeep` aside. A tree without the directory has none."""
    root, folder = _reasons_at(root, reasons)
    try:
        names = os.listdir(root / folder)
    except FileNotFoundError:
        return []
    except OSError as err:
        return [f"{folder} ({err.strerror or err})"]
    cited = {f"{digest}.md" for _, digest in cited_reasons(st, entries)}
    return sorted(f"{folder}/{name}" for name in names if name != REASONS_KEEP and name not in cited)


def amendment_only(entries: list[dict], since: int) -> bool:
    """The entries from `since` on exist, and every one of them is an entry of an amendment ballot: its
    opening, a commitment, a reveal or its close. A pull request of such entries is let through a tree that
    does not match the pins (SPEC §9.5): otherwise a tree that became unlawful (a pin moved, and the
    PRIOR_PIN_DAYS of the text before it ran out) could never be repaired by the amendment that corrects it."""
    kinds = {e["body"].get("id"): e["body"].get("kind") for e in entries
             if e.get("type") == "ballot_open" and type(e.get("body")) is dict}
    new = entries[since:]
    return bool(new) and all(e.get("type") in BALLOT_TYPES and type(e.get("body")) is dict
                             and kinds.get(e["body"].get("id")) == "amendment" for e in new)


def anchor_problems(entries: list[dict], since: int, changes: list[tuple[str, str]], root: Path | None = None) -> list[str]:
    """Violations among the files a pull request changes under `ledger/anchors/`. `changes` are the pairs
    `(status, path)` of `git diff --name-status` for that directory. A file may only be **added**, when a
    `witness` entry of the same pull request (`seq >= since`) names it in `anchor`, or names it with `.ots`
    appended (the root beside its proof); nothing is modified, deleted or renamed. Each file is a regular file,
    reached through no symlink, of at most ANCHOR_MAX_BYTES bytes, and holds exactly what the checkpoints of the
    pull request that name it determine (`anchor_mismatch`): whoever carries a checkpoint chooses none of its
    bytes."""
    root = canon.ROOT if root is None else Path(root)
    new = [e["body"] for e in entries[since:]
           if e.get("type") == "witness" and type(e.get("body")) is dict and type(e["body"].get("anchor")) is str]
    problems = []
    for status, rel in changes:
        if not rel.startswith(ANCHORS_DIR + "/"):
            continue
        naming = [b for b in new if b["anchor"] in (rel, rel + ".ots")]
        if status == "M":
            problems.append(f"{rel}: an anchor file is never changed once merged (a checkpoint's root and proof are "
                            "added with it, and an upgraded proof stays outside the repository)")
            continue
        if status != "A":
            problems.append(f"{rel}: an anchor is added, never changed, deleted or renamed")
            continue
        if not naming:
            problems.append(f"{rel}: no witness entry of this pull request names this anchor")
            continue
        try:
            path = _safe_file(root, root / rel)
            info = os.lstat(path)
            if not stat.S_ISREG(info.st_mode):
                problems.append(f"{rel} is not a regular file")
            elif info.st_size > ANCHOR_MAX_BYTES:
                problems.append(f"{rel} is larger than {ANCHOR_MAX_BYTES} bytes")
            else:
                data = path.read_bytes()
                bad = next((m for m in (anchor_mismatch(rel, b, data) for b in naming) if m), None)
                if bad:
                    problems.append(f"{rel}: {bad}")
        except UnsafeTree as err:
            problems.append(str(err))
        except OSError as err:
            problems.append(f"{rel} cannot be read: {err.strerror or err}")
    return problems


def anchor_mismatch(rel: str, body: dict, data: bytes) -> str | None:
    """Why `data` is not the anchor file `rel` of the checkpoint `body`, or None. Pure. The file the checkpoint
    names in `anchor` is its proof when that name ends in `.ots`, and the same name without `.ots` is the root
    beside it; any other file it names is a root. A root is exactly `body["root"]` and a newline. A proof is an
    OpenTimestamps proof of that root file: it begins with OTS_PREFIX and the SHA-256 of the root file."""
    if type(body.get("root")) is not str:
        return "the checkpoint that names it states no root, so it anchors no file"
    root_file = (body["root"] + "\n").encode("ascii", "replace")
    if rel == body["anchor"] and rel.endswith(".ots"):
        if not data.startswith(OTS_PREFIX + hashlib.sha256(root_file).digest()):
            return ("not an OpenTimestamps proof of the root the checkpoint signs (it must begin with the format's "
                    "header, version 1, the SHA-256 operation and the digest of the root file)")
        return None
    if data != root_file:
        return "not the root the checkpoint signs (a root file holds the root and a newline, nothing else)"
    return None


def parse_changes(text: str) -> list[tuple[str, str]]:
    """The pairs `(status, path)` of the lines `git diff --no-renames --name-status` prints: a status letter,
    a tab, a path. A line of any other form is kept with the status `?`, which no rule accepts."""
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        status, tab, rel = line.partition("\t")
        out.append((status, rel) if tab and len(status) == 1 and rel else ("?", line.strip()))
    return out


def genesis_pins(root: Path | None = None) -> dict[str, str]:
    """What a genesis founded on the tree at `root` pins: the digest of every path of `GENESIS_PINS`."""
    root = canon.ROOT if root is None else Path(root)
    return {rel: protocol_digest(root) if rel == PROTOCOL_PIN else sha256(_safe_file(root, root / rel).read_bytes())
            for rel in GENESIS_PINS}


def pinned_tables(st: State, entries: list[dict] | None = None) -> list[str]:
    """Every degree table the ledger ever pinned, in order and each once: the genesis pin (read from the
    entries when the caller holds them), every passed amendment of `canon/degrees.toml`, the prior pin and the
    pin in force. Replay reads each of them by its digest (section 8.4), so the tree must archive them all."""
    found: list[str] = []
    if entries:
        pins = entries[0].get("body", {}).get("pins") if type(entries[0]) is dict else None
        if type(pins) is dict and type(pins.get(DEGREES_PATH)) is str:
            found.append(pins[DEGREES_PATH])
    found += st.degree_tables
    found += [d for d in (st.prior_pins.get(DEGREES_PATH), st.pins.get(DEGREES_PATH)) if d]
    return list(dict.fromkeys(found))


def added_tables(root: Path, base: Path, entries: list[dict] | None, since: int | None) -> list[str]:
    """Problems of the degree tables a pull request adds to `canon/history/` (the names under it in `root` and
    not in `base`). Each must be content-addressed (its bytes hash to its name) and a well-formed table; a pull
    request that adds entries may add only the tables its new degree amendment ballots name, so that the
    ballot can be opened in the same pull request as its archive; the genesis pull request (`since` 0) only
    the table its genesis pins for `canon/degrees.toml`."""
    def names(tree: Path) -> set[str]:
        d = tree / HISTORY_DIR
        return {p.name for p in d.iterdir()} if d.is_dir() and not d.is_symlink() else set()
    new = sorted(names(root) - names(base))
    named = {e["body"]["subject"].get("new_sha256") for e in (entries or [])[since or 0:]
             if type(e) is dict and e.get("type") == "ballot_open" and type(e.get("body")) is dict
             and e["body"].get("kind") == "amendment" and type(e["body"].get("subject")) is dict
             and e["body"]["subject"].get("path") == DEGREES_PATH}
    if since == 0 and entries and type(entries[0]) is dict and type(entries[0].get("body")) is dict \
            and type(entries[0]["body"].get("pins")) is dict:
        named.add(entries[0]["body"]["pins"].get(DEGREES_PATH))      # the genesis archives the table it pins
    adds = since is not None and entries is not None and since < len(entries)
    problems = []
    for name in new:
        rel = f"{HISTORY_DIR}/{name}"
        digest = name.removesuffix(".toml")
        try:
            raw = _read(root, rel)
        except UnsafeTree as err:
            problems.append(f"{rel}: {err}")
            continue
        if not name.endswith(".toml") or sha256(raw) != digest:
            problems.append(f"{rel}: an archived degree table is named after the sha256 of its bytes "
                            f"({sha256(raw)[:12]}…)")
        elif canon.canon_status_of(raw) != "ok":
            problems.append(f"{rel}: not a well-formed degree table (33 degrees with exact fields)")
        elif adds and digest not in named:
            problems.append(f"{rel}: a pull request that adds entries archives only the degree table its new "
                            f"amendment ballot of {DEGREES_PATH} names (the genesis pull request: the one its "
                            "genesis pins)")
    return problems


def unarchived_tables(st: State, root: Path, entries: list[dict] | None = None) -> list[tuple[str, str]]:
    """`(path, problem)` for every degree table the ledger pinned that `canon/history/` of the tree does not
    hold byte for byte."""
    problems = []
    for digest in pinned_tables(st, entries):
        rel = f"{HISTORY_DIR}/{digest}.toml"
        try:
            actual = sha256(_read(root, rel))
        except UnsafeTree as err:
            problems.append((rel, f"{err} (every degree table the ledger ever pinned stays archived)"))
            continue
        if actual != digest:
            problems.append((rel, f"{rel} has sha256 {actual[:12]}…, which is not its name"))
    return problems


def _fingerprint(root: Path, rel: str) -> str:
    """What the governed path `rel` holds in the tree at `root`, to tell whether a pull request changed it:
    the `@protocol` digest, the sha256 of a file, or a word for what is not a readable regular file."""
    try:
        if rel == PROTOCOL_PIN:
            return protocol_digest(root)
        return sha256(_read(root, rel))
    except UnsafeTree as err:
        return f"({err})"


def tree_report(st: State, root: Path | None = None, entries: list[dict] | None = None, since: int | None = None,
                base: Path | None = None, reasons: Path | None = None) -> tuple[list[str], list[str]]:
    """`(violations, warnings)` of the tree at `root`: what `check_tree` and `tree_warnings` return.

    With `base`, the tree of the branch a pull request is judged against: a governed path, a degree table
    of `canon/history/`, the Declaration or a stray workflow that is unlawful in the tree, and is exactly as it
    is in `base` (the pull request did not change it), is reported as a warning. An unratified `main` is an
    alarm (the audit of the Tyler reports it), never a lock on the entries of a pull request. So is a stray
    name under `ledger/reasons/` (`stray_reasons`) that `base` holds the same. The public reasons of the
    corrections of the ledger (`missing_reasons`) are judged in full, whatever `base` holds. A genesis (`since`
    0) is judged without `base`: its pins must match the tree exactly. `reasons`: the
    directory the public reasons are read from instead of the tree's `ledger/reasons/` (`missing_reasons`)."""
    root = canon.ROOT if root is None else Path(root)
    reasons_dir = reasons
    if not root.is_dir():
        return [f"tree root {root} does not exist"], []
    # The genesis gets no such allowance: entry 0 is never corrected, so its pins must match the tree exactly.
    base = Path(base) if base is not None and Path(base).is_dir() and since != 0 else None
    problems: list[str] = []
    inherited: list[str] = []

    def judge(text: str, *rels: str) -> None:
        same = base is not None and all(_fingerprint(root, r) == _fingerprint(base, r) for r in rels)
        (inherited if same else problems).append(text + (" (unchanged by this pull request: an alarm, not a "
                                                          "refusal)" if same else ""))
    for rel, pinned in sorted(st.pins.items()):
        try:
            if rel == PROTOCOL_PIN:
                actual = protocol_digest(root)
            else:
                path = root / rel
                if path.exists() or path.is_symlink():
                    _safe_file(root, path)
                actual = sha256(path.read_bytes()) if path.is_file() else "(missing)"
        except UnsafeTree as err:
            judge(f"{rel}: {err}", rel)
            continue
        # Right after an amendment passes, the tree may still hold the previous ratified text for
        # PRIOR_PIN_DAYS of ledger time, until the PR that applies the new text merges.
        prior_ok = st.prior_pins.get(rel) == actual and st.time is not None \
            and st.time <= st.prior_until.get(rel, st.time)
        if actual != pinned and not prior_ok:
            judge(f"{rel}: tree sha256 {actual[:12]}… ≠ ratified {pinned[:12]}… — needs a passed amendment", rel)
    for rel, text in unarchived_tables(st, root, entries):
        judge(text, rel)
    for rel in stray_workflows(root):
        judge(f"{rel}: a workflow outside the pinned core ({MANIFEST}) — needs a passed amendment of {PROTOCOL_PIN}",
              rel)
    if st.declaration_sha256:
        # Petitions commit to the digest genesis recorded; it must be the Declaration of the pinned Landmarks.
        try:
            declared = canon.declaration_digest(root)
        except (OSError, KeyError, TypeError, ValueError):
            declared = "(unreadable)"
        if declared != st.declaration_sha256:
            judge(f"canon/eternal.toml: the Declaration's sha256 {declared[:12]}… ≠ the one recorded at genesis "
                  f"{st.declaration_sha256[:12]}…", "canon/eternal.toml")
    reasons, warnings = missing_reasons(st, root, entries, since, reasons_dir)
    problems += reasons
    for rel in stray_reasons(st, root, entries, reasons_dir):
        # A stray the base branch already holds, in the same bytes, is an alarm: otherwise one file merged around
        # the gate would refuse every later pull request of entries.
        judge(f"{rel}: no correction of the ledger pins this file ({REASONS_DIR}/ holds only the public reasons of "
              "corrections, each named after its sha256)", rel)
    return problems, inherited + warnings


def check_tree(st: State, root: Path | None = None, entries: list[dict] | None = None,
               since: int | None = None, base: Path | None = None) -> list[str]:
    """Every pinned path must match its ratified sha256 (or the one it is replacing), every degree table the
    ledger ever pinned must be archived in `canon/history/`, the tree must hold no workflow outside the pinned
    core, and `ledger/reasons/` must hold the public reason of every correction the pull request being judged
    adds (`seq >= since`), no reason whose bytes are not its name, and nothing else. The core is the one the
    tree's own manifest lists: a malformed manifest, or a listed file that is missing, makes the tree
    unlawful. `entries` are the entries `st` was replayed from, when the caller holds them (`cited_reasons`).
    `base`: see `tree_report`.

    Returns violations; empty = lawful. `tree_warnings` returns what is reported and is no violation.
    """
    return tree_report(st, root, entries, since, base)[0]


def tree_warnings(st: State, root: Path | None = None, entries: list[dict] | None = None,
                  since: int | None = None, base: Path | None = None) -> list[str]:
    """What `check_tree` finds and does not hold against the tree: the public reasons of older corrections
    that the tree no longer holds, and, with `base`, what was unlawful already in the base tree."""
    return tree_report(st, root, entries, since, base)[1]
