"""The canon: degrees, houses and the constants of the protocol.

Everything here is read from files that are themselves under constitutional
control (canon/*.toml). Code never invents a rule the canon does not state.
"""
from __future__ import annotations

import contextlib
import hashlib
import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "canon"

# --- protocol constants (Whitepaper §5–§8) ---------------------------------
# Durations are exact (SPEC §1.4): a wait of N days is complete when N × 86,400 seconds have passed;
# something that lasts N days expires when more than that has passed.
NAMESPACE = "openmasonry"          # ssh-keygen -Y signature namespace
LIGHT_HALF_LIFE_DAYS = 180         # half-life of the Light score
LIGHT_WINDOW_DAYS = 1800           # ten half-lives: a member record keeps no activity point older than this
                                   # before its newest one (such a point weighs less than 0.001 in Light)
DORMANT_AFTER_DAYS = 365           # dormant when more than 365 days have passed since the last activity
SPONSORS_REQUIRED = 2              # proposer + seconder
SPONSOR_MIN_DEGREE = 3             # only Master Builders may sponsor
SPONSOR_BUDGET_PER_YEAR = 4        # sponsorships counted at once (members admitted in the last 365 days,
                                   # reserved petitions, own invitations live or lapsed less than 90 days ago)
FOUNDING_MASTERS = 7               # bootstrap ends when this many active Masters exist
COUNCIL_SEATS = 33
COUNCIL_TERM_DAYS = 3 * 365        # a seat is held through the last second of its 1,095 days
WAIT_DAYS_MAX = 3650               # bounds of a degree table: 0..3650 days of waiting…
EXAMINERS_MAX = 33                 # …and 0..33 examiners (at least 1 for the degrees reached by examination)
CANON_MAX_BYTES = 256 * 1024       # a degree table larger than this is not one
ZERO_HASH = "0" * 64
# Where the canonical fraternity lives, and which GitHub account founds it. Clones and forks verify against
# the repository and publish into it; the identity gate lets the genesis in only from the founder's account.
_NETWORK = tomllib.loads((Path(__file__).with_name("network.toml")).read_text(encoding="utf-8"))
CANONICAL_REPO = __import__("os").environ.get("OM_CANONICAL") or _NETWORK["repository"]
# The numeric GitHub id of the account that opens the genesis pull request and is its first founder. 0 means
# "not set": the gate then refuses every genesis (SPEC §9.3).
FOUNDER_GITHUB_ID = _NETWORK.get("founder_github_id", 0)
if type(FOUNDER_GITHUB_ID) is not int or FOUNDER_GITHUB_ID < 0:
    FOUNDER_GITHUB_ID = 0


@dataclass(frozen=True)
class Degree:
    n: int
    house: str
    title: str
    historical: str
    virtue: str
    art: str
    lesson: str
    work: str
    wait_days: int
    examiners: int
    unlocks: str
    tincture: str
    ordinary: str
    charge: str


@dataclass(frozen=True)
class House:
    id: str
    name: str
    range: tuple[int, int]
    purpose: str


class MalformedCanon(ValueError):
    """A degree table that is not exactly 33 well-formed degrees."""


_DEGREE_TEXT = ("house", "title", "historical", "virtue", "art", "lesson", "work", "unlocks", "tincture",
                "ordinary", "charge")
_DEGREE_FIELDS = frozenset(("n", "wait_days", "examiners") + _DEGREE_TEXT)
_HOUSE_TEXT = ("id", "name", "purpose")
_HOUSE_FIELDS = frozenset(_HOUSE_TEXT + ("range",))

# The one form of a canon file (SPEC §8.4): lines ended by a line feed, each of them blank, a comment, one of
# the two table headers or `key = value`. It is a small subset of TOML, read here character by character, so
# that the verdict on a table depends on its bytes alone and never on the TOML library of a runtime.
_COMMENT_RE = re.compile(r"#[^\x00-\x08\x0a-\x1f\x7f]*")
_PAIR_RE = re.compile(r"([a-z_]{1,32}) = (.*)")
_STRING_RE = re.compile(r'"([^"\\\x00-\x1f\x7f]*)"')            # no escape, no quote, no control character
_INT_RE = re.compile(r"0|[1-9][0-9]{0,3}")                      # 0 to 9999, no sign, no leading zero
_RANGE_RE = re.compile(r"\[(0|[1-9][0-9]{0,3}), (0|[1-9][0-9]{0,3})\]")
_HEADERS = {"[[degree]]": "degree", "[[house]]": "house"}


def _parse_tables(raw: bytes) -> dict[str, list[dict]]:
    """The tables of a canon file: `{"degree": [row, …], "house": [row, …]}`. Raises MalformedCanon unless
    the bytes have the one form above. No recursion and no number longer than four digits: the same verdict
    on every runtime."""
    if len(raw) > CANON_MAX_BYTES:
        raise MalformedCanon(f"larger than {CANON_MAX_BYTES} bytes")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise MalformedCanon("not UTF-8") from None
    if text.startswith("﻿"):
        raise MalformedCanon("a byte order mark is not allowed")
    if text and not text.endswith("\n"):
        raise MalformedCanon("the last line must end with a line feed")
    tables: dict[str, list[dict]] = {"degree": [], "house": []}
    row: dict | None = None
    kind = ""
    for n, line in enumerate(text.split("\n")[:-1], 1):
        if line == "" or _COMMENT_RE.fullmatch(line):
            continue
        if line in _HEADERS:
            kind, row = _HEADERS[line], {}
            tables[kind].append(row)
            continue
        m = _PAIR_RE.fullmatch(line)
        if m is None or row is None:
            raise MalformedCanon(f"line {n}: only blank lines, comments, [[degree]], [[house]] and `key = value` "
                                 "inside one of the two (no top-level key, no other table)")
        key, value = m.groups()
        if key in row:
            raise MalformedCanon(f"line {n}: the key {key} appears twice in one table")
        s = _STRING_RE.fullmatch(value)
        if s is not None:
            row[key] = s.group(1)
        elif _INT_RE.fullmatch(value):
            row[key] = int(value)
        elif kind == "house" and key == "range" and _RANGE_RE.fullmatch(value):
            row[key] = [int(x) for x in _RANGE_RE.fullmatch(value).groups()]
        else:
            raise MalformedCanon(f"line {n}: a value is a string between double quotes without escapes, or an "
                                 "integer of one to four digits (and `range = [a, b]` in a house)")
    return tables


def _degrees_of(tables: dict[str, list[dict]]) -> dict[int, Degree]:
    rows = tables["degree"]
    if len(rows) != 33:
        raise MalformedCanon("the canon must define exactly 33 degrees")
    out: dict[int, Degree] = {}
    for row in rows:
        if set(row) != _DEGREE_FIELDS:
            raise MalformedCanon("every degree has exactly the fields " + ", ".join(sorted(_DEGREE_FIELDS)))
        n, wait, examiners = row["n"], row["wait_days"], row["examiners"]
        if type(n) is not int or not 1 <= n <= 33 or n in out:
            raise MalformedCanon("degree numbers are the integers 1 to 33, each exactly once")
        if type(wait) is not int or not 0 <= wait <= WAIT_DAYS_MAX:
            raise MalformedCanon(f"degree {n}: wait_days is an integer from 0 to {WAIT_DAYS_MAX}")
        if type(examiners) is not int or not (1 if 2 <= n <= 32 else 0) <= examiners <= EXAMINERS_MAX:
            raise MalformedCanon(f"degree {n}: examiners is an integer up to {EXAMINERS_MAX}, at least 1 for degrees 2 to 32")
        if any(type(row[k]) is not str for k in _DEGREE_TEXT):
            raise MalformedCanon(f"degree {n}: every field but n, wait_days and examiners is a string")
        out[n] = Degree(**row)
    return out


def _houses_of(tables: dict[str, list[dict]]) -> dict[str, House]:
    out: dict[str, House] = {}
    for row in tables["house"]:
        if set(row) != _HOUSE_FIELDS or any(type(row[k]) is not str for k in _HOUSE_TEXT) \
                or type(row["range"]) is not list:
            raise MalformedCanon("every house has exactly the fields id, name, purpose (strings) and range = [a, b]")
        lo, hi = row["range"]
        if not 1 <= lo <= hi <= 33 or row["id"] in out:
            raise MalformedCanon("a house has its own id and a range of degrees within 1 to 33")
        out[row["id"]] = House(row["id"], row["name"], (lo, hi), row["purpose"])
    return out


def parse_degrees(raw: bytes) -> dict[int, Degree]:
    """The degree table of a canon file, validated strictly. Raises MalformedCanon.

    The file is UTF-8 text in the one form of `_parse_tables`: nothing at the top level, and no table but
    `[[degree]]` and `[[house]]`. It holds exactly 33 `[[degree]]` tables. Each has exactly the fields of
    `Degree`: `n` an integer, 1 to 33, each once; `wait_days` an integer, 0 to WAIT_DAYS_MAX; `examiners`
    an integer, 0 to EXAMINERS_MAX and at least 1 for degrees 2 to 32 (the degrees reached by examination);
    every other field a string. Each `[[house]]` table has exactly `id`, `name`, `purpose` and `range`.
    """
    tables = _parse_tables(raw)
    _houses_of(tables)                            # a table with a malformed house is not a table
    return _degrees_of(tables)


@lru_cache(maxsize=1)
def degrees() -> dict[int, Degree]:
    return parse_degrees((CANON / "degrees.toml").read_bytes())


@lru_cache(maxsize=1)
def houses() -> dict[str, House]:
    return _houses_of(_parse_tables((CANON / "degrees.toml").read_bytes()))


def degrees_for(digest: str) -> dict[int, Degree]:
    """The degree table ratified under `digest`.

    Replay must not depend on today's file: each ratified version is archived as
    canon/history/<sha256>.toml (the current file also answers for its own digest).
    """
    return _degrees_for(digest)


# More directories in which a degree table is looked up by its digest, after canon/history/ (`archives`).
_ARCHIVES: list[Path] = []


@contextlib.contextmanager
def archives(*dirs: Path):
    """Also look up degree tables in `dirs` while the block runs: the judge replays a pull request that adds
    the archived table its degree amendment names (`canon/history/<sha256>.toml` of the tree it judges). A
    table is found only under its own digest, so a directory can add tables and never change one."""
    _ARCHIVES[:] = [Path(d) for d in dirs]
    try:
        yield
    finally:
        _ARCHIVES.clear()
        _degrees_for.cache_clear()


@lru_cache(maxsize=None)
def _degrees_for(digest: str) -> dict[int, Degree]:
    for path in (CANON / "history" / f"{digest}.toml", *(d / f"{digest}.toml" for d in _ARCHIVES),
                 CANON / "degrees.toml"):
        if path.is_file() and not path.is_symlink() and path.stat().st_size <= CANON_MAX_BYTES:
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() == digest:
                return parse_degrees(raw)        # the bytes are the ratified ones; they must also be a table
    raise LookupError(f"degree canon {digest[:12]}… is not archived in canon/history/")


def canon_status(digest: str) -> str:
    """"ok", "missing" (this clone lacks the text ratified under `digest`) or "malformed" (it has the
    text, and the text is not a valid degree table: no clone will ever replay it)."""
    try:
        _degrees_for(digest)
        return "ok"
    except MalformedCanon:
        return "malformed"
    except LookupError:
        return "missing"


def canon_status_of(raw: bytes) -> str:
    """"ok" if `raw` is a well-formed degree table, else "malformed"."""
    try:
        parse_degrees(raw)
        return "ok"
    except MalformedCanon:
        return "malformed"


def canon_archived(digest: str) -> bool:
    """True if the degree table ratified under `digest` is available to replay."""
    return canon_status(digest) == "ok"


def declaration_digest(root: Path | None = None) -> str:
    """sha256 of the Declaration text (UTF-8, exactly as in canon/eternal.toml) — what a petition commits to.

    Replay never calls this: genesis records the digest and petitions are compared with the state. It is
    for the tools that draft a genesis or show the Declaration, and for the tree gate (govern.check_tree).
    """
    path = (CANON if root is None else Path(root) / "canon") / "eternal.toml"
    text = tomllib.loads(path.read_text(encoding="utf-8"))["declaration"]["text"]
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def minimum_days_to(n: int) -> int:
    """Shortest possible path (in days) from initiation to degree n."""
    return sum(degrees()[k].wait_days for k in range(2, n + 1))
