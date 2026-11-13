"""The Tracing Board: an append-only, hash-chained, signed ledger.

The ledger is a directory of JSON files (ledger/entries/0000/000000.json, ...). Each
entry commits to the hash of the previous one, is signed by its actor, and is
only valid if the state *before* it allows it. `replay()` folds the entire
history into the current state and raises `Invalid` at the first violation, so
any clone of the repository can verify the whole fraternity from genesis,
offline, with nothing but Python.

The rules implemented here are the normative core of the Whitepaper (§5–§8) and are
specified rule by rule in docs/whitepaper/SPEC.md. Three conventions hold everywhere:

* integers are exact (JSON integers within ±(2^53 − 1); no floats, no null);
* every string of an entry is ASCII (line feed and U+0020 to U+007E);
* durations are exact: a wait of N days is complete when `now − start >= N days`, and a
  thing that lasts N days expires when `now − start > N days`. Nothing is rounded to days.

Corrections (SPEC §6.19–§6.25) add intervals: a freeze, a stay, a halt or a hold is in force on
`[start, end)`, where `end` is computed from stored facts and never written back. The effective clock
(`State.effective`) is wall time minus the halted time, and for one ballot minus the time it was stayed
or under a pending void. Two acts need notice: `void_ballot` and `undo_ballot` are pending for
NOTICE_DAYS and take effect only by a `correction_apply`. The recovery of a lost key (SPEC §6.26–§6.30)
is no correction: Master Builders co-sign it, and the old key can stop it.

Nobody writes without bound (SPEC §5.4): an actor has ENTRIES_PER_DAY entries in a UTC day, a member
OPEN_BALLOTS_PER_OPENER ballots open at once, a witness one checkpoint per new entry and per hour, a
custodian one sign of life in 24 hours.

The stored facts of a state have one digest (`State.document`, `State.digest`, SPEC §4.11): a Merkle root per
section of records, the scalars, and a hash chain per history of what no rule reads any more. A witness
checkpoint states the digest of the state it covers, and replay refuses a wrong one, so two verifiers that
accept the same checkpoint hold the same state; a verifier hashes again only the records that changed. `head_verdict` and `remember_head`
(SPEC §9.7) are the pure half of a client rule: a clone remembers the head it verified and tells a rewound
history from a mirror that is only behind.
"""
from __future__ import annotations

import collections
import copy
import hashlib
import itertools
import json
import os
import re
import stat
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import canon
from .crypto import (canonical, key_bytes, merkle_append, merkle_frontier_root, merkle_root, merkle_root_bytes,
                     public_point, sha256, sign, valid_public_key, verify)
from .lot import draw

YES, NO = "yes", "no"
WITNESS_TYPES = {"witness", "ballot_close", "exam_draw", "council_draw"}
CUSTODIAN_TYPES = frozenset({"correction", "correction_cosign", "correction_apply", "correction_withdraw",
                             "custodian_alive"})              # signed by a custodian key
CUSTODIAN_SIGNED = CUSTODIAN_TYPES | {"custodian_revoke"}    # …or by a custodian's revoke key: any pull request may carry them
ENVELOPE = {"seq", "prev", "time", "type", "actor", "body", "sig"}
MEASURES = {"admonish", "suspend", "expel", "expel_for_fraud", "reinstate"}
KINDS = {"admission", "advancement", "amendment", "custodian", "sanction", "witness"}
BALLOT_TYPES = frozenset({"ballot_open", "ballot_commit", "ballot_reveal", "ballot_close"})
RECOVERY_TYPES = frozenset({"rekey_recover", "rekey_recover_apply"})    # signed by the new key of a recovery
RESULTS = ("passed", "failed", "lapsed", "voided", "undone")            # what a ballot that is no longer open became
DEGREES_PATH = "canon/degrees.toml"
ETERNAL_PREFIX = "canon/eternal.toml"
LEDGER_PREFIX = "ledger"            # nothing at or under this path can ever be pinned


class CanonPending(ValueError):
    """The ratified degree canon is not archived in this clone (canon/history/<sha256>.toml)."""

    def __init__(self, digest: str, msg: str):
        super().__init__(msg)
        self.digest = digest


class Invalid(Exception):
    """The ledger violates the protocol at a given sequence number."""

    def __init__(self, seq: int, msg: str):
        super().__init__(f"entry {seq}: {msg}")
        self.seq = seq


# ------------------------------------------------------------- grammars ------
# Every pattern is matched against the whole string (`fullmatch`) and names its characters
# explicitly: no \d, \w or \s, whose meaning follows the Unicode tables of the runtime.

HEX64 = re.compile(r"[0-9a-f]{64}")
BALLOT_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")          # never anything a shell would interpret
PATH_RE = re.compile(r"@protocol|[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}(?:/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}){0,9}")
URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]{1,300}")     # no spaces, quotes, controls
TIME_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z")
LOGIN_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")     # GitHub login rules
KEY_RE = re.compile(r"ssh-ed25519 [A-Za-z0-9+/]{68}|sk-ssh-ed25519@openssh\.com [A-Za-z0-9+/]{99}=")   # no comment
NAME_RE = re.compile(r"[\x20-\x7e]{1,120}")                    # the fraternity name: printable ASCII
SALT_RE = re.compile(r"[0-9a-f]{32,64}")                       # `om vote` draws 16 random bytes (32 hex)
WORK_KIND_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")         # a free label of a work: essay, code, …
ANCHOR_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}(?:/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}){0,9}")
ANCHOR_MAX = 200                    # a checkpoint's anchor: a repository-relative path of at most 200 characters
STRING_RE = re.compile(r"[\n\x20-\x7e]*")                      # every string of an entry, keys included
NOTE_TARGET_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/#@-]{0,119}")   # what a moderation act touched: a thread, an account
NOTE_RULE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/#-]{0,63}")       # the published rule it applied: a file, an article

MAX_SAFE_INT = 2 ** 53 - 1          # integers are exact in every language that reads JSON numbers as doubles
MAX_INT_DIGITS = 16                 # 2^53 − 1 has 16 digits: longer literals are refused before conversion
MAX_DEPTH = 6                       # the entry object is level 1; the protocol itself needs 4
MAX_ENTRY_BYTES = 8 * 1024          # size of an entry file (and of its canonical form)
MAX_GENESIS_BYTES = 32 * 1024       # …of the genesis entry, which carries the founders and witnesses
YEAR_MIN, YEAR_MAX = 2020, 9000     # entry times; leaves room for every window the protocol adds to a time

PRIOR_PIN_DAYS = 30                 # the replaced text stays lawful only until the new one lands (expires after)
PROTOCOL_PIN = "@protocol"          # digest of the pinned core: the files of src/openmasonry/protocol.manifest
# What genesis pins, no more and no fewer: the degree table, the eternal Landmarks, the Constitution,
# the protocol core and the two charters the Constitution relies on.
GENESIS_PINS = (DEGREES_PATH, ETERNAL_PREFIX, "CONSTITUTION.md", PROTOCOL_PIN,
                "docs/governance/CUSTODIAN.md", "docs/governance/ROOMS.md")
COMMIT_DAYS, REVEAL_DAYS = 7, 3     # the voting windows of every ballot; an amendment may ask for 2..30 and 1..14 days
OPENER_WINDOWS = frozenset({"amendment"})    # the kinds whose opener chooses the windows

DAY = timedelta(days=1)
SECOND = timedelta(seconds=1)       # the resolution of every time
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def ts(s: str) -> datetime:
    """Entry times are UTC, second precision, always written as YYYY-MM-DDTHH:MM:SSZ.

    A single format makes replay identical on every machine (no local time zones). The fields are
    range-checked here, one by one: no hour 24, no leap second, years 2020 to 9000.
    """
    m = TIME_RE.fullmatch(s) if type(s) is str else None
    if m is None:
        raise ValueError(f"time must be YYYY-MM-DDTHH:MM:SSZ, got {s!r}")
    year, month, day, hour, minute, second = (int(x) for x in m.groups())
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    if not (YEAR_MIN <= year <= YEAR_MAX and 1 <= month <= 12 and hour <= 23 and minute <= 59 and second <= 59
            and 1 <= day <= _MONTH_DAYS[month - 1] + (1 if leap and month == 2 else 0)):
        raise ValueError(f"time must be YYYY-MM-DDTHH:MM:SSZ, a real UTC time in the years {YEAR_MIN} to {YEAR_MAX}, "
                         f"got {s!r}")
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def iso(t: datetime) -> str:
    """The one text form of a time, also for times kept inside the state or frozen in a ballot. Written out
    field by field: the same characters on every platform, and several times faster than `strftime`, which
    matters to the state digest."""
    return f"{t.year:04d}-{t.month:02d}-{t.day:02d}T{t.hour:02d}:{t.minute:02d}:{t.second:02d}Z"


def waited(start: datetime, now: datetime, days: int) -> bool:
    """A waiting period of `days` is complete: the exact elapsed time is at least `days` days."""
    return now - start >= days * DAY


def expired(start: datetime, now: datetime, days: int) -> bool:
    """Something that lasts `days` has expired: the exact elapsed time is more than `days` days."""
    return now - start > days * DAY


# drand "quicknet" (League of Entropy): 3-second rounds, publicly verifiable.
DRAND_CHAIN = "52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971"
DRAND_GENESIS = 1692803367
DRAND_PERIOD = 3
# Entries carry their own claimed time. The Tyler only merges entries stamped within
# CLOCK_TOLERANCE of real time, so every delay that protects a secret must exceed it.
CLOCK_TOLERANCE = timedelta(hours=6)
JUDGE_FUTURE_TOLERANCE = timedelta(minutes=2)   # …and at most this far ahead of the judge's clock
FUTURE_TOLERANCE = timedelta(minutes=10)   # a merged head dated further ahead than this is a capture alarm (SPEC §9.7)
BEACON_DELAY_ROUNDS = 9600          # 8 hours: the lot's round is in the future even for a 6-hour backdated call
REVEAL_GAP = CLOCK_TOLERANCE + timedelta(minutes=15)   # reveals only after any backdated commit is impossible
SILENT_DAYS = 180                   # a Master Builder called to examinations and ballots that ended in the last
SILENT_CALLS = 2                    # …180 days, at least two, who answered none, counts as dormant where it says so
SILENT_APART_DAYS = 7               # …two calls count as two only when their ends are at least 7 days apart
EXAM_RETRY_DAYS = 90                # a failed exam may be repeated once 90 days have passed since it opened
EXAM_EXPIRY_DAYS = 60               # an exam without a majority verdict more than 60 days after it opened has timed out:
                                    # it lapses with no penalty, and its silent examiners are skipped by the next pool
LOT_DRAW_DAYS = 7                   # a lot (exam or council) not drawn more than 7 days after its beacon round lapses
SPONSOR_WAIVE_DAYS = 30             # fewer than 7 Masters present: one sponsor suffices once a petition has been live 30 days
RERUN_DAYS = 30                     # a lapsed ballot is re-run once, by a ballot opened within 30 days of its close
SANCTION_MASTER_VOTES = 2           # a sanction on a Master Builder is never decided by fewer than two votes
SUCCESSION_DAYS = 90                # a succession claim nobody of the 3rd degree answers takes effect after 90 days…
SUCCESSION_MASTERS = 3              # …and ends once this many active Master Builders exist
CLAIM_NOTICE_DAYS = 30              # a founder's claim of the Custodian office is under notice for 30 days…
CLAIM_EXPIRY_DAYS = 60              # …and is applied not more than 60 days after it, or never
CLAIM_MASTERS = 3                   # …while fewer than this many active Master Builders who are not founders exist
CLAIM_AGAIN_DAYS = 30               # after an objection voided a claim, the next claim of any founder waits 30 days
INVITE_EXPIRY_DAYS = 30             # an invitation lapses, and frees its inviter, more than 30 days after it was signed
PETITION_EXPIRY_DAYS = 180          # a petition lapses, and frees its sponsors, more than 180 days after it was filed
INVITE_COUNTED_DAYS = 90            # …and still counts in its inviter's budget until 90 days after it lapsed
REJOIN_AFTER_DAYS = 90              # a departed member, or one whose admission was undone, may be invited again once 90 days have passed
VOIDED_FRAUD_DAYS = 90              # a voided record may still be expelled for fraud by a ballot opened before 90 days of the undo
EXPELLED_REPETITION_DAYS = 365      # Constitution Art. X.4: an expelled member, once 365 days have passed
SUSPENSION_DAYS = 365               # Constitution Art. X.1: a suspension is served once 365 days have passed
SPONSOR_BAN_DAYS = 730              # Constitution Art. IV.4: the ban is served once 730 days have passed
FRAUD_WINDOW_DAYS = 730             # sponsors answer for a fraud found up to 730 days after admission (inclusive)
SPONSOR_YEAR_DAYS = 365             # an admitted member counts in the sponsor's budget for 365 days (inclusive)
WORK_INTERVAL = timedelta(hours=24)  # at most one `work` entry per member in any 24 hours
REKEY_INTERVAL_DAYS = 30            # a member may replace their key again once 30 days have passed since the last time
REKEY_DOMAIN = "openmasonry rekey v1"   # first line of the message a new key signs to take a member's place
WITNESS_DOMAIN = "openmasonry witness v1"   # first line of the message a witness key signs to be named or proposed
FOUNDER_DOMAIN = "openmasonry founder v1"   # first line of the message the key of a founder after the first signs at genesis
KEY_RULE = "keys must be ssh-ed25519 or sk-ssh-ed25519@openssh.com (application ssh:)"

# Rate limits (SPEC §5.4): nobody writes without bound.
ENTRIES_PER_DAY = 20                # entries one actor may have in one UTC calendar day, the exempt types aside
# Never counted, and never refused for the count (SPEC §5.4, the daily-exempt set): what must stay possible
# whatever else the actor signed (leaving, replacing or recovering a key, stopping a recovery of one's own
# key, removing a custodian key by its revoke key, objecting to a correction or to a founder's claim), the
# vote (one commitment and one reveal per elector per ballot), what happens once per ballot or per lot, and
# by `daily_exempt` every entry of an amendment ballot or of the ballot that removes a custodian. Each of
# these is bounded by its own rule: once per subject, per elector, per interval or per open ballot.
DAILY_EXEMPT = frozenset({"depart", "rekey", "rekey_object", "custodian_revoke", "correction_object",
                          "custodian_claim_object", "rekey_recover", "rekey_cosign", "rekey_oppose",
                          "rekey_recover_apply", "ballot_commit", "ballot_reveal", "ballot_close", "exam_draw",
                          "council_draw"})
UNSTOPPABLE_KINDS = frozenset({"amendment", "custodian"})   # ballots no halt, cap or cooldown stops (SPEC §5.4)
OPEN_BALLOTS_PER_OPENER = 3         # ballots one member may have open at once: of the other kinds together, and of
                                    # amendments apart (a removal ballot is never counted: one per custodian at most)
REOPEN_AFTER_DAYS = 90              # the same opener opens a ballot on the same subject again 90 days after one failed or lapsed
REOPEN_KINDS = frozenset({"sanction", "witness"})   # …for these kinds (a re-run aside, section 6.4)
CHECKPOINT_INTERVAL = timedelta(hours=1)    # at most one checkpoint per witness per hour of ledger time
ALIVE_INTERVAL = timedelta(hours=24)        # at most one sign of life per custodian in 24 hours

# Custodians and corrections (Landmark VI: a repair made by an office may undo, freeze or pause but never grant).
CUSTODIANS_MAX = 3                  # custodians a genesis may name
CUSTODIAN_SILENCE_DAYS = 180        # a custodian key lapses more than 180 days after its last sign of life
CUSTODIAN_TERM_DAYS = 2555          # …and every custodian key more than 2,555 days (7 years) after the genesis or the claim's application that named it
SUNSET_MASTERS = 7                  # the Sunset condition: this many active Master Builders who are not founders…
SUNSET_WITNESSES = 4                # …and this many witnesses; from then on no custodian signs
FREEZE_DAYS = 30                    # a frozen member key, or a frozen witness, is frozen for 30 days flat
REFREEZE_AFTER_DAYS = 90            # the same login is frozen again only once 90 days have passed since the last freeze began
FREEZE_CAP_DIVISOR = 10             # keys frozen at once: at most a tenth of the active members, and never fewer than 1
STAY_DAYS = 14                      # a stayed ballot is paused for at most 14 days, once
HALT_DAYS = 14                      # a halt lasts at most 14 days…
HALT_INTERVAL_DAYS = 90             # …and the next one begins only once 90 days have passed since the last began
HOLD_DAYS = 14                      # a room hold lasts at most 14 days
REHOLD_AFTER_DAYS = 90              # the same login is held again only once 90 days have passed since the last hold began
NOTES_PER_DAY = 10                  # notes one custodian may record in one UTC calendar day
NOTES_KEPT = 200                    # the state keeps the newest 200 notes; every note stays in its entry
CORRECTIONS_PER_30_DAYS = 5         # the backstop: restricting corrections of all custodians together…
CORRECTION_WINDOW_DAYS = 30         # …in any 30 days (a correction stops counting once 30 days have passed)
REPOST_AFTER_DAYS = 90              # the same act on the same target is posted again 90 days after objections voided it
OBJECTION_DAYS = 90                 # a correction may be objected to until 90 days after it, or after it was applied
NOTICE_DAYS = 14                    # a noticed act is pending for 14 days of wall time before it may be applied…
APPLY_WINDOW_DAYS = 7               # …and is applied within the 7 days after its notice, or never
UNDO_WINDOW_DAYS = 90               # a ballot is undone only by a correction posted within 90 days of its close
RECOVER_NOTICE_DAYS = 21            # a key recovery is applied only once 21 days have passed since it was requested…
RECOVER_EXPIRY_DAYS = 60            # …and not more than 60 days after it
RECOVER_INTERVAL_DAYS = 90          # one recovery request per member in 90 days; 90 days of rest after the old key stops one
RECOVER_COSIGNERS = 2               # Master Builders who co-sign a recovery that follows a freeze: 2, or as many other Masters as exist
RECOVER_OPEN_COSIGNERS = 3          # …an open recovery (no freeze in force): 3, or as many other Masters as exist
RECOVER_FINAL_COSIGNERS = 3         # …and the recovery that follows one the old key stopped: 3, or as many other Masters
                                    # (the other Masters counted are those who answered: ANSWER_DAYS)
RECOVER_OPEN_NOTICE_DAYS = 30       # the notice of a recovery asked without a freeze
RECOVER_DROP_DAYS = 30              # a request open this long without all its co-signatures needs only those given
DEPART_RECOVER_DAYS = 30            # a recovery asked within 30 days of a departure (or before it) reverses it…
DEPART_FOLLOW_DAYS = RECOVER_INTERVAL_DAYS + RECOVER_EXPIRY_DAYS   # …and so does the next one, asked within 150
                                    # days of that one's request, or of the old key's stop of it when later
RECOVER_LOWERED_NOTICE_DAYS = 45    # …and of any recovery whose co-signers were lowered to the Masters who exist
ANSWER_DAYS = 365                   # a recovery waits only for the Masters who answered, or reached the 3rd degree, in 365 days
OBJECTION_DIVISOR = 5               # a correction is void at max(1, ceil(E / 5)) objections
GROUNDS = ("key_compromised", "protocol_defect", "identity_fraud", "attack_in_progress", "moderation")
NOTE_GROUND = "moderation"          # the ground of a note, and of nothing else
NOTE_ACTIONS = ("hide", "lock", "block", "unblock", "limit", "other")
CUSTODIAN_DOMAIN = "openmasonry custodian v1"                 # first line of the message a custodian key signs at genesis
CUSTODIAN_REVOKE_DOMAIN = "openmasonry custodian-revoke v1"   # …and of the message its revoke key signs


def unix(t: datetime) -> int:
    """Whole seconds since 1970-01-01T00:00:00Z, by integer arithmetic."""
    d = t - EPOCH
    return d.days * 86400 + d.seconds


def drand_round(t: datetime) -> int:
    return (unix(t) - DRAND_GENESIS) // DRAND_PERIOD + 1


def drand_time(rnd: int) -> datetime:
    return EPOCH + timedelta(seconds=DRAND_GENESIS + (rnd - 1) * DRAND_PERIOD)


def fold(s: str) -> str:
    """Case folding of a name or path. Both are ASCII, so this is ASCII lowercasing."""
    return s.lower()


def same_login(a: str, b: str) -> bool:
    return fold(a) == fold(b)             # GitHub logins are case-insensitive


def ed25519(key: str) -> bool:
    """Only bare `ssh-ed25519 <base64>` and `sk-ssh-ed25519@openssh.com <base64>` keys: no options, comments or
    line breaks, the one text form of the key blob, and a valid curve point."""
    return type(key) is str and KEY_RE.fullmatch(key) is not None and valid_public_key(key)


def point(key: str) -> str:
    """The Ed25519 point of a valid key, as 64 hexadecimal characters. It is what makes two keys the same
    key: an `ssh-ed25519` key and an `sk-ssh-ed25519@openssh.com` key with one point are one key."""
    return public_point(key).hex()


def same_key(a: str, b: str) -> bool:
    """Two valid keys with the same point, whatever their types."""
    pa = public_point(a)
    return pa is not None and pa == public_point(b)


def holds(stored: str, raw: bytes | None) -> bool:
    """The key `stored`, which the state holds and which was validated when an entry registered it, has the
    point `raw`. The stored key is only decoded, never validated again: asking who holds a key costs no
    curve arithmetic, however many keys the state holds."""
    return raw is not None and key_bytes(stored) == raw


def rekey_message(login: str, old_key: str, new_key: str) -> bytes:
    """What the new key signs in a `rekey` (SPEC §6.18): four lines, each ended by a line feed. None of the
    three values can hold a line feed, so the message has one reading, and it is never the signed payload of
    an entry (which is a JSON object)."""
    return f"{REKEY_DOMAIN}\n{login}\n{old_key}\n{new_key}\n".encode("ascii")


def custodian_message(name: str, member: str, key: str) -> bytes:
    """What a custodian key signs to be named at genesis (SPEC §6.1): four lines, each ended by a line feed.
    It binds the custodian's name, the member account it is linked to and the key itself."""
    return f"{CUSTODIAN_DOMAIN}\n{name}\n{member}\n{key}\n".encode("ascii")


def custodian_revoke_message(name: str, key: str, revoke_key: str) -> bytes:
    """What a custodian's revoke key signs at genesis: the custodian's name, the key it can remove and
    the revoke key itself. Like `rekey_message`, neither message is ever the signed payload of an entry."""
    return f"{CUSTODIAN_REVOKE_DOMAIN}\n{name}\n{key}\n{revoke_key}\n".encode("ascii")


def witness_message(name: str, key: str) -> bytes:
    """What a witness key signs to be named at genesis, or proposed by a witness ballot (SPEC §6.4.5): three
    lines, each ended by a line feed. Nobody registers a witness key they do not hold."""
    return f"{WITNESS_DOMAIN}\n{name}\n{key}\n".encode("ascii")


def founder_message(login: str, github_id: int, key: str) -> bytes:
    """What the key of a founder after the first signs at genesis (SPEC §6.1): four lines, each ended by a
    line feed. The first founder signs the entry itself."""
    return f"{FOUNDER_DOMAIN}\n{login}\n{github_id}\n{key}\n".encode("ascii")


def objections_needed(eligible: int) -> int:
    """How many objections void a correction when `eligible` Masters may object: max(1, ceil(E / 5))."""
    return max(1, -(-eligible // OBJECTION_DIVISOR))


def valid_login(login) -> bool:
    return type(login) is str and LOGIN_RE.fullmatch(login) is not None


def entry_hash(entry: dict) -> str:
    return sha256(canonical(entry))


def signed_payload(entry: dict) -> bytes:
    return canonical({k: v for k, v in entry.items() if k != "sig"})


# ---------------------------------------------------------------- state ------

_VERSIONS = itertools.count(1)


class _Record:
    """A record of the state. Every assignment to one of its fields gives it a new version (`_v`, unique in
    the process), and so does `touch`, which follows a change made in place to a list or a map it holds. The
    version is not a fact: it only tells the digest which leaves to hash again (`State.digest`)."""

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
        object.__setattr__(self, "_v", next(_VERSIONS))

    def touch(self) -> None:
        object.__setattr__(self, "_v", next(_VERSIONS))


@dataclass
class Member(_Record):
    login: str
    key: str
    degree: int
    since: dict[int, datetime]
    sponsors: tuple[str, ...] = ()
    status: str = "active"          # active | suspended | expelled | departed | voided (the admission was undone)
    activity: list[datetime] = field(default_factory=list)   # at most one time per UTC day, none older than
                                                             # LIGHT_WINDOW_DAYS before the newest
    seat_until: datetime | None = None
    past_seats: int = 0
    status_since: datetime | None = None
    suspended_until: datetime | None = None
    sponsor_ban_until: datetime | None = None
    founder: bool = False            # honorary "Founding Architect": a title, never a power; it follows the login
    last_work: datetime | None = None                       # time of the member's latest `work` entry
    fraud_history: tuple[datetime, ...] = ()                 # when this login was expelled for fraud; survives re-admission
    github_id: int = 0                                       # the numeric GitHub user id: from genesis, or from the invitation
    last_rekey: datetime | None = None                       # time of the member's latest change of key: a `rekey`, or the application of a recovery
    left: dict | None = None                                 # for a `depart`: what the record held before it ({status,
                                                             # status_since, seat_until}), which a recovery puts back
    missed: tuple[datetime, ...] = ()                        # a Master Builder (or a successor): the ends of the newest
                                                             # SILENT_CALLS examinations and ballots of the last
                                                             # SILENT_DAYS, at least SILENT_APART_DAYS apart, they were
                                                             # called to and answered nothing in, ascending
    heard: datetime | None = None                            # …and the latest of their votes and reports, and of the
                                                             # ends of the calls they answered

    def standing(self, now: datetime) -> str:
        """The status that counts at `now`: a suspension that has been served is over by itself."""
        if self.status == "suspended" and self.suspended_until is not None and now >= self.suspended_until:
            return "active"
        return self.status

    def is_active(self, now: datetime) -> bool:
        """Active, or suspended with the suspension (max one year) already served."""
        return self.standing(now) == "active"

    def last_active(self) -> datetime:
        """The newest point of activity (the list is ascending), or the admission while there is none."""
        return self.activity[-1] if self.activity else self.since[1]

    def dormant(self, now: datetime) -> bool:
        return expired(self.last_active(), now, canon.DORMANT_AFTER_DAYS)

    def silent(self, now: datetime) -> bool:
        """Called to at least SILENT_CALLS examinations or ballots that ended in the last SILENT_DAYS, at least
        SILENT_APART_DAYS apart, and answered none of them; one vote revealed or one report ends it. A silent
        Master Builder counts as dormant for the succession and the all-Masters rungs of the examiner pool; a silent
        member is left out of the present lists of an admission and an advancement (keeping the vote), and a silent
        successor of the successors."""
        if self.heard is not None and not expired(self.heard, now, SILENT_DAYS):
            return False
        return sum(1 for t in self.missed if not expired(t, now, SILENT_DAYS)) >= SILENT_CALLS

    def called(self, end: datetime, answered: bool, now: datetime) -> None:
        """A call of this member (an examination or a ballot) ended at `end`: answered or not. Of the calls
        missed, the record keeps the newest SILENT_CALLS that are at least SILENT_APART_DAYS apart: two calls
        that end within that time are one absence, and the record stays the same size however many there are."""
        if answered:
            if self.heard is None or end > self.heard:
                self.heard = end
            return
        kept: list[datetime] = []
        for t in sorted((t for t in (*self.missed, end) if not expired(t, now, SILENT_DAYS)), reverse=True):
            if len(kept) < SILENT_CALLS and (not kept or kept[-1] - t >= SILENT_APART_DAYS * DAY):
                kept.append(t)
        self.missed = tuple(reversed(kept))

    def seated(self, now: datetime) -> bool:
        """Holds a Council seat: the seat is counted through its last second, whatever the member's standing."""
        return self.seat_until is not None and now <= self.seat_until

    def credit(self, now: datetime) -> None:
        """One point of activity per UTC day, kept at the time of the day's latest entry. A point more than
        LIGHT_WINDOW_DAYS older than the newest is dropped: the list stays bounded, dormancy reads the newest
        point alone, and a dropped point weighed less than 0.001 in Light."""
        if self.activity and self.activity[-1].date() == now.date():
            self.activity[-1] = now
        else:
            self.activity.append(now)
        while expired(self.activity[0], now, canon.LIGHT_WINDOW_DAYS):
            del self.activity[0]
        self.touch()

    def light(self, now: datetime) -> float:
        h = canon.LIGHT_HALF_LIFE_DAYS
        return sum(0.5 ** ((now - t).total_seconds() / 86400 / h) for t in self.activity)


@dataclass
class Ballot(_Record):
    id: str
    kind: str
    subject: dict
    electors: frozenset[str]
    commit_until: datetime
    reveal_until: datetime
    opened_by: str
    commits: dict[str, str] = field(default_factory=dict)
    reveals: dict[str, str] = field(default_factory=dict)
    result: str | None = None       # passed | failed | lapsed, by its close; voided | undone, by a correction
    frozen: dict = field(default_factory=dict)   # what the electors voted on: the petition, or which membership
    opened: datetime | None = None  # time of the ballot_open entry: where the ballot's own clock starts
    closed: datetime | None = None  # time of the ballot_close entry
    undo: dict = field(default_factory=dict)     # for a passed ballot that can be undone: field -> [before, after]
    corrected: int | None = None    # seq of the correction that voided or undid it
    base: int | None = None         # the electors its quorum and turnout count: those not dormant when it
                                    # opened, less the non-responders of the ballot it re-runs; None: all of them
    rerun: str = ""                 # the id of the lapsed ballot this one re-runs (once)

    def quorum_base(self) -> int:
        """How many electors the quorum and the turnout of this ballot count: every elector keeps the vote,
        and a dormant one, or one who did not vote in the ballot this one re-runs, is not waited for."""
        return len(self.electors) if self.base is None else self.base


@dataclass
class Exam(_Record):
    candidate: str
    degree: int
    examiners: tuple[str, ...] | None       # None until the beacon is drawn
    beacon_round: int = 0
    opened: datetime | None = None
    reports: dict[str, str] = field(default_factory=dict)
    pool: tuple[str, ...] = ()                # frozen at exam_open, before anyone can know the beacon
    work_ref: str = ""
    ranking: tuple[str, ...] = ()             # the whole pool in lot order; recusals take the next one
    recused: tuple[str, ...] = ()
    k: int = 0
    consumed: bool = False                    # an advancement ballot used this exam
    ballot_failed: bool = False               # …and that ballot was lost on the votes: the exam counts as failed
    lapsed: bool = False                      # ended through no fault of the candidate: a new exam may open at once
    skipped: tuple[str, ...] = ()             # the silent examiners of the exam before, left out of this pool

    def expired(self, now: datetime, st: "State | None" = None) -> bool:
        """No verdict is accepted any more. Counted on the effective clock of `st` (halted time does not
        count); without a state no halt is known, and it is wall time."""
        if st is not None:
            return st.expired(self.opened, now, EXAM_EXPIRY_DAYS)
        return expired(self.opened, now, EXAM_EXPIRY_DAYS)

    def draw_lapsed(self, now: datetime, st: "State | None" = None) -> bool:
        """The lot of this exam was not drawn in time: more than LOT_DRAW_DAYS after its beacon round (on the
        effective clock), no draw is accepted, and the exam has lapsed with no penalty (the beacon may be
        unavailable for good)."""
        if self.examiners is not None or self.lapsed:
            return False
        start = drand_time(self.beacon_round)
        return st.expired(start, now, LOT_DRAW_DAYS) if st is not None else expired(start, now, LOT_DRAW_DAYS)

    def timed_out(self, now: datetime, st: "State | None" = None) -> bool:
        """No verdict was reached before the exam expired, because an examiner never reported (or the lot was
        never drawn): the exam ends with no penalty, as a lapsed one does."""
        if self.lapsed or self.ballot_failed or self.passed() or self._fails():
            return False
        return self.expired(now, st) or self.draw_lapsed(now, st)

    def ended(self, now: datetime, st: "State | None" = None) -> bool:
        """Ended through no fault of the candidate: lapsed, or timed out. A new exam may open at once."""
        return self.lapsed or self.timed_out(now, st)

    def silent(self, now: datetime, st: "State | None" = None) -> tuple[str, ...]:
        """The drawn examiners who never reported in an exam that timed out: the next pool skips them."""
        if not self.timed_out(now, st) or not self.examiners:
            return ()
        return tuple(x for x in self.examiners if x not in self.reports)

    def _fails(self) -> bool:
        return bool(self.examiners) and sum(v == "fail" for v in self.reports.values()) * 2 >= len(self.examiners)

    def passed(self) -> bool:
        """A strict majority of `pass` among the examiners, standing: not lapsed, and not undone by a lost
        advancement ballot. An exam with no examiners never passes."""
        if self.lapsed or self.ballot_failed or not self.examiners:
            return False
        return sum(v == "pass" for v in self.reports.values()) * 2 > len(self.examiners)

    def failed(self, now: datetime, st: "State | None" = None) -> bool:
        """Half or more of fails, or an advancement ballot lost. An exam that only ran out of time did not fail:
        it timed out (`timed_out`), with no penalty. `now` and `st` are kept for the callers that ask both."""
        if self.lapsed:
            return False
        if self.ballot_failed:
            return True
        if self.passed():
            return False
        return self._fails()


@dataclass
class Custodian(_Record):
    name: str                       # the actor of its entries; never a member login or a witness name
    key: str                        # signs corrections, withdrawals and signs of life
    revoke_key: str                 # signs one thing: the removal of `key`
    member: str                     # the login of the member account of the person who holds the keys (recusal)
    alive: datetime                 # the last sign of life: genesis, then each `custodian_alive`
    genesis: bool = True            # named by the genesis: lapses at the Sunset, and at the end of the term
    revoked: datetime | None = None  # when its revoke key, or a ballot of the Master Builders, removed it
    removed: str = ""               # the id of that ballot, when a ballot did
    since: datetime | None = None   # the time of the genesis that named it, or of the claim's application: where the
                                    # term starts
    claim: int | None = None        # the seq of the founder's `custodian_claim` that named it; None at genesis

    @property
    def bounded(self) -> bool:
        """Bound by the Sunset and the term: every custodian, of the genesis or of a founder's claim."""
        return self.genesis or self.claim is not None


@dataclass
class Correction(_Record):
    seq: int                        # the seq of the `correction` entry: its id
    by: str                         # the custodian who signed it
    act: str
    target: dict
    ground: str
    reason_sha256: str
    time: datetime                  # the time of the entry: where an immediate act starts
    class_: str = "immediate"       # immediate | noticed (a note is not a correction record: `State.notes`)
    until: datetime | None = None   # an immediate act lapses by itself here (time + its days); None otherwise
    subject: str = ""               # the member the act is aimed at, if any: never counted among its objectors
    objections: tuple[str, ...] = ()
    void: datetime | None = None    # when its objections reached the number that voids it, for good
    withdrawals: tuple[str, ...] = ()   # the custodians who signed its withdrawal, in order
    withdrawn: datetime | None = None   # when it was withdrawn: by its poster, or by enough other custodians
    withdrawn_by: str = ""              # the custodian whose signature withdrew it
    signers: tuple[str, ...] = ()   # a noticed act: the custodian who posted it, then those who co-signed
    applied: datetime | None = None  # a noticed act: when a `correction_apply` gave it its effect
    applied_by: str = ""
    released: datetime | None = None  # a freeze_key: when the recovery of the frozen key was applied


@dataclass
class Recovery(_Record):
    login: str                      # the member whose key is being recovered
    key: str                        # the new key: it signed the request and will sign the application
    seq: int                        # the seq of the `rekey_recover` entry
    time: datetime                  # …and its time
    freeze: int | None = None       # the seq of the freeze_key that was in force then; None for a recovery asked
                                    # with no freeze in force (an "open" recovery)
    admitted: str = ""              # the membership of the login it was asked for: it never reaches a later one
    cosigners: tuple[str, ...] = ()  # the Master Builders who co-signed, in order
    objected: datetime | None = None  # when the old key stopped it
    applied: datetime | None = None   # when the new key took the member's place
    notice: datetime | None = None  # an open recovery: when the co-signatures it needs were complete, which is
                                    # where its notice starts (None until then, and for a recovery after a freeze)
    final: bool = False             # it follows a recovery the old key stopped: the old key cannot stop this one
    opposed: tuple[str, ...] = ()   # an open recovery: the Master Builders who opposed it, in order
    void: datetime | None = None    # …and when their number voided it
    dropped: int | None = None      # how many had co-signed when it had been open RECOVER_DROP_DAYS: recorded by the
                                    # first co-signature after that moment (None until then)
    departure: datetime | None = None   # the departure it was asked in time for, which it reverses when completed:
                                        # set by a request for a departed record, or by the `depart` of a member
                                        # whose latest recovery was in time for it (`_depart`); None otherwise

    def drop_time(self) -> datetime:
        return self.time + RECOVER_DROP_DAYS * DAY

    def given_at_drop(self) -> int:
        """The co-signatures given by the drop: recorded, or all of them while none came after it."""
        return self.dropped if self.dropped is not None else len(self.cosigners)


@dataclass
class Claim(_Record):
    """A founder's claim of the Custodian office (SPEC §6.31): pending for CLAIM_NOTICE_DAYS, voided by
    the objection of one active Master Builder who is not a founder, applied by the founder."""
    seq: int                        # the seq of the `custodian_claim` entry: its id
    founder: str                    # the founder who signed it with their member key
    name: str                       # the custodian it names: a login nobody holds
    key: str
    revoke_key: str
    time: datetime
    objected: datetime | None = None
    objector: str = ""
    applied: datetime | None = None


@dataclass
class Succession(_Record):
    """A succession claim (SPEC §6.34): signed by a member below the 3rd degree while no active Master
    Builder who is neither dormant nor silent exists. Any entry within SUCCESSION_DAYS of a Master Builder who is
    then active and neither dormant nor silent cancels it; after that, until SUCCESSION_MASTERS such Masters
    exist, the members of the highest degree present, neither dormant nor silent, stand in for Masters in the lot
    of examiners, the advancement electorate, invitations and sponsorship, and in nothing else."""
    seq: int
    by: str
    time: datetime
    end: datetime | None = None     # when it was canceled (by a Master's entry) or ended (three Masters exist)
    canceled_by: str = ""           # the Master Builder whose entry canceled it; empty when it ended


@dataclass
class State:
    name: str = ""
    head: str = canon.ZERO_HASH
    seq: int = -1
    time: datetime | None = None
    members: dict[str, Member] = field(default_factory=dict)
    witnesses: dict[str, str] = field(default_factory=dict)
    invitations: dict[str, dict] = field(default_factory=dict)   # login -> {by, github_id, time}, until the petition
    petitions: dict[str, dict] = field(default_factory=dict)     # login -> {key, vouches, time, github_id}
    ballots: dict[str, Ballot] = field(default_factory=dict)
    exams: dict[tuple[str, int], Exam] = field(default_factory=dict)
    hashes: list[str] = field(default_factory=list)
    pins: dict[str, str] = field(default_factory=dict)   # governed path -> sha256 last ratified
    prior_pins: dict[str, str] = field(default_factory=dict)  # the version before the last amendment
    prior_until: dict[str, datetime] = field(default_factory=dict)  # …lawful only until this ledger time
    council_call: int | None = None                       # drand round of a pending council draw
    council_pool: tuple[str, ...] = ()                    # frozen at council_call, emptied by the draw
    declaration_sha256: str = ""                          # digest of the Declaration, recorded at genesis
    known_keys: set[str] = field(default_factory=set)     # the point of every key an entry ever registered
    custodians: dict[str, Custodian] = field(default_factory=dict)   # every custodian ever named, live or not
    custodian_threshold: int = 0                          # custodian keys a noticed correction needs (genesis)
    corrections: dict[int, Correction] = field(default_factory=dict)  # seq -> every correction ever accepted
    sunset: datetime | None = None                        # time of the entry at which the Sunset condition first held
    recoveries: dict[str, Recovery] = field(default_factory=dict)     # login -> its latest key recovery, whatever became of it
    notes: list[dict] = field(default_factory=list)       # the newest NOTES_KEPT notes: {seq, by, action, target, rule, reason_sha256, time}
    day: str = ""                                         # the UTC calendar day (YYYY-MM-DD) of the last entry…
    day_entries: dict[str, int] = field(default_factory=dict)   # …and, for that day, actor -> entries counted (SPEC §5.4)
    acts: int = 0                                         # how many entries so far are not `witness` checkpoints
    witness_marks: dict[str, dict] = field(default_factory=dict)   # witness name -> {acts, time} at its latest checkpoint
    claims: dict[int, Claim] = field(default_factory=dict)  # seq -> every founder's claim of the Custodian office
    succession: Succession | None = None                  # the latest succession claim, whatever became of it
    epoch: int = 0                                        # how many amendments of @protocol passed (a rule change branches on a fixed time or seq, never on this alone)
    history: dict[str, tuple[int, str]] = field(default_factory=lambda: {h: (0, canon.ZERO_HASH) for h in HISTORY})
    # name -> (count, accumulator): the records that left the state, or never entered it (SPEC §4.11)
    retired: set[str] = field(default_factory=set)        # the id of every ballot the history absorbed (an index of it)
    degree_tables: list[str] = field(default_factory=list)  # every degree table a passed amendment pinned (an index)

    def __post_init__(self):
        # Not facts and not fields: an index of `corrections` (which only grows), so that the effective clock
        # never scans every correction. Filled as needed by `_pausing`; it holds keys of `corrections` only.
        self._indexed = 0                          # how many records of `corrections` the index has read
        self._halts: list[int] = []                # the seq of every halt, in order
        self._stays: dict[str, list[int]] = {}     # ballot id -> the seq of its stay and of every void_ballot of it
        self._trusted = False                      # not a fact: the entry being applied is below `replay`'s trusted bound
        # Not facts either: the leaf of every record as the last digest hashed it, and its section root
        # (`State.digest`); the ballots that ended, in the order they did (`_retire`); and the frontier of the
        # Merkle tree of `hashes` (`State.entries_root`).
        self._leaves: dict[str, _Leaves] = {}
        self._ended: collections.deque | None = None
        self._frontier: list[tuple[int, bytes]] = []
        self._frontier_n = 0

    def __deepcopy__(self, memo):
        """A copy holds the same facts and hashes its leaves again: what was cached is not copied."""
        new = object.__new__(State)
        memo[id(self)] = new
        for k, v in self.__dict__.items():
            new.__dict__[k] = {} if k == "_leaves" else copy.deepcopy(v, memo)
        return new

    # -- the stored facts, as one value ---------------------------------------
    def document(self) -> dict:
        """The state document (SPEC §4.11), version 2: the scalars of the state, the Merkle root of each
        section and the accumulator of each history. Small, whatever the size of the state: each section is
        committed to by one root."""
        return _document(self, {name: self._section_root(spec) for name, spec in SECTIONS.items()})

    def digest(self) -> str:
        """The state digest: the SHA-256 of the canonical JSON of `document()`. Equal for two states exactly
        when their stored facts are equal, on every runtime: nothing in it depends on the order in which a
        map or a set was filled, on a clock or on a floating-point value. Only the leaves of the records that
        changed since the last digest are hashed again; `state_digest` hashes them all and is always equal."""
        return sha256(canonical(self.document()))

    def _section_root(self, spec: "Section") -> str:
        cache = self._leaves.get(spec.name)
        if cache is None:
            cache = self._leaves[spec.name] = _Leaves()
        old_fp, old_leaf = cache.fp, cache.leaf
        fp, leaf, changed, added = {}, {}, False, False
        for k, v in spec.items(self):
            f = spec.fingerprint(v)
            if k in old_fp:
                if old_fp[k] == f:
                    leaf[k] = old_leaf[k]
                else:
                    leaf[k], changed = _leaf(k, spec.facts(v)), True
            else:
                leaf[k], changed, added = _leaf(k, spec.facts(v)), True, True
            fp[k] = f
        if added or len(fp) != len(old_fp) or cache.order is None:
            cache.order, changed = sorted(fp), True
        if changed or cache.root is None:
            cache.root = merkle_root_bytes([leaf[k] for k in cache.order])
        cache.fp, cache.leaf = fp, leaf
        return cache.root

    def entries_root(self) -> str:
        """`merkle_root(hashes)`, from a frontier that follows `hashes` (which only grows): O(log n)."""
        if self._frontier_n > len(self.hashes):  # never in replay: a state edited by hand
            self._frontier, self._frontier_n = [], 0
        for h in itertools.islice(self.hashes, self._frontier_n, None):
            merkle_append(self._frontier, bytes.fromhex(h))
        self._frontier_n = len(self.hashes)
        return merkle_frontier_root(self._frontier)

    # -- derived views ------------------------------------------------------
    def active(self, now: datetime, min_degree: int = 1, exclude: set[str] = frozenset()) -> list[str]:
        return sorted(
            m.login for m in self.members.values()
            if m.is_active(now) and m.degree >= min_degree
            and not m.dormant(now) and m.login not in exclude
        )

    def masters(self, now: datetime) -> list[str]:
        return self.active(now, canon.SPONSOR_MIN_DEGREE)

    def present_masters(self, now: datetime) -> list[str]:
        """The active Master Builders who are neither dormant nor silent: what the succession counts."""
        return [x for x in self.masters(now) if not self.members[x].silent(now)]

    def founding_phase(self, now: datetime) -> bool:
        return len(self.masters(now)) < canon.FOUNDING_MASTERS

    def seats(self, now: datetime) -> list[str]:
        """Who holds a Council seat. A suspended holder keeps the seat, so it is never filled twice."""
        return sorted(m.login for m in self.members.values() if m.seated(now))

    def degree(self, n: int) -> "canon.Degree":
        """Degree parameters as ratified *now* in this history (not as in today's file)."""
        digest = self.pins[DEGREES_PATH]
        try:
            return canon.degrees_for(digest)[n]
        except LookupError as err:
            raise CanonPending(digest, str(err)) from None

    def canon_pending(self) -> str | None:
        """The pinned degree-canon digest whose text this clone lacks (readers report it, never crash)."""
        digest = self.pins.get(DEGREES_PATH)
        return digest if digest and not canon.canon_archived(digest) else None

    def invited(self, login: str, now: datetime) -> bool:
        """The login, in exactly this spelling, holds an invitation that has not lapsed (lapse is a matter of
        time, not of an entry; the time is the effective clock)."""
        i = self.invitations.get(login)
        return i is not None and not self.expired(i["time"], now, INVITE_EXPIRY_DAYS)

    def live(self, login: str, now: datetime) -> bool:
        """The login has a petition that has not lapsed (lapse is a matter of time, not of an entry; the time
        is the effective clock)."""
        p = self.petitions.get(login)
        return p is not None and not self.expired(p["time"], now, PETITION_EXPIRY_DAYS)

    # -- custodians and corrections -------------------------------------------
    def custodian_end(self, c: Custodian) -> datetime:
        """The first second at which the custodian key is no longer live: the earliest of its revocation,
        the Sunset and the second after its term (for a key named at genesis), and the second after its
        silence deadline. Computed from stored facts alone, so it is the same whenever it is asked."""
        end = c.alive + CUSTODIAN_SILENCE_DAYS * DAY + SECOND
        if c.revoked is not None:
            end = min(end, c.revoked)
        if c.bounded and self.sunset is not None:
            end = min(end, self.sunset)
        if c.bounded and c.since is not None:
            end = min(end, c.since + CUSTODIAN_TERM_DAYS * DAY + SECOND)
        return end

    def custodians_live(self, now: datetime) -> list[str]:
        """The names of the custodians whose key is live at `now`, in ascending order."""
        return sorted(c.name for c in self.custodians.values() if self.custodian_status(c, now) == "live")

    def custodian_status(self, c: Custodian, now: datetime) -> str:
        """live | lapsed | revoked (by its revoke key) | removed (by a ballot), at `now`. A key that is not
        live never signs again."""
        if now < self.custodian_end(c):
            return "live"
        if c.revoked is None:
            return "lapsed"
        return "removed" if c.removed else "revoked"

    def span(self, c: Correction) -> tuple[datetime, datetime]:
        """The interval `[start, end)` on which an immediate act is in force. `end` is the earliest of its own
        lapse, its withdrawal, the objections that voided it and the end of its custodian's key. Nothing here
        is stored: the deadline of an act is never rewritten."""
        end = min(c.until, self.custodian_end(self.custodians[c.by]))
        for t in (c.withdrawn, c.void, c.released):
            if t is not None:
                end = min(end, t)
        return c.time, max(end, c.time)

    def in_force(self, c: Correction, now: datetime) -> bool:
        if c.class_ != "immediate":         # a noticed act has no effect before it is applied
            return False
        start, end = self.span(c)
        return start <= now < end

    def correction_status(self, c: Correction, now: datetime) -> str:
        """An immediate act: active | lapsed (ran its time) | withdrawn | void | released (the recovery of
        the frozen key was applied) | ended (its custodian's key lapsed or was removed first). A noticed
        act: `noticed_status`."""
        if c.class_ == "noticed":
            return self.noticed_status(c, now)
        end = self.span(c)[1]
        if now < end:
            return "active"
        if c.void is not None and c.void <= now:
            return "void"
        if c.withdrawn is not None and c.withdrawn <= now:
            return "withdrawn"
        if c.released is not None and c.released <= now:
            return "released"
        return "lapsed" if end == c.until else "ended"

    # -- the founder's fallback ----------------------------------------------
    def claim_status(self, c: Claim, now: datetime) -> str:
        """pending (under notice) | ready (the notice is over: the founder may apply it) | applied | objected
        (a Master Builder who is not a founder voided it) | expired (nobody applied it in time)."""
        if c.applied is not None and c.applied <= now:
            return "applied"
        if c.objected is not None and c.objected <= now:
            return "objected"
        if expired(c.time, now, CLAIM_EXPIRY_DAYS):
            return "expired"
        return "ready" if waited(c.time, now, CLAIM_NOTICE_DAYS) else "pending"

    def claim_pending(self, now: datetime) -> Claim | None:
        """The claim of the Custodian office that is pending or ready at `now`, if any (never two at once)."""
        for c in reversed(self.claims.values()):
            if expired(c.time, now, CLAIM_EXPIRY_DAYS):
                break                       # the records are in the order of time: nothing older is alive
            if self.claim_status(c, now) in ("pending", "ready"):
                return c
        return None

    def non_founder_masters(self, now: datetime) -> int:
        """The active Master Builders who are not founders: what the Sunset and the founder's fallback count."""
        return sum(1 for m in self.members.values()
                   if not m.founder and m.degree >= canon.SPONSOR_MIN_DEGREE and m.is_active(now) and not m.dormant(now))

    # -- succession ----------------------------------------------------
    def succession_status(self, now: datetime) -> str | None:
        """None (no claim was ever made) | pending (a claim waits SUCCESSION_DAYS for a Master Builder to show
        themselves) | in_force | canceled | ended. Canceling and ending are recorded at an entry."""
        s = self.succession
        if s is None:
            return None
        if s.end is not None and s.end <= now:
            return "canceled" if s.canceled_by else "ended"
        return "in_force" if waited(s.time, now, SUCCESSION_DAYS) else "pending"

    def successors(self, now: datetime) -> list[str]:
        """While a succession is in force and no Master Builder is present: the active members (neither dormant
        nor silent) of the highest degree present. They stand in for Master Builders as the last rung of the lot of
        examiners and the advancement electorate, and may invite and sponsor; nothing else."""
        if self.succession_status(now) != "in_force":
            return []
        present = [self.members[x] for x in self.active(now)]
        present = [m for m in present if not m.silent(now)]   # a silent member is left out, at any degree
        top = max((m.degree for m in present), default=0)
        return sorted(m.login for m in present if m.degree == top) if 0 < top < canon.SPONSOR_MIN_DEGREE else []

    def stands_in(self, login: str, now: datetime) -> bool:
        """`login` may invite and sponsor as a Master Builder does: a Master, or a successor."""
        m = self.members.get(login)
        return m is not None and (m.degree >= canon.SPONSOR_MIN_DEGREE or login in self.successors(now))

    # -- noticed acts -------------------------------------------------------------
    def notice_end(self, c: Correction) -> datetime:
        """The first second at which a noticed act may be applied."""
        return c.time + NOTICE_DAYS * DAY

    def apply_end(self, c: Correction) -> datetime:
        """The last second at which a noticed act may be applied."""
        return c.time + (NOTICE_DAYS + APPLY_WINDOW_DAYS) * DAY

    def noticed_status(self, c: Correction, now: datetime) -> str:
        """Where a noticed act stands at `now`: pending (under notice) | ready (the notice is over and the
        time to apply it is running) | applied | void (objections) | withdrawn | ended (the key of the
        custodian who posted it lapsed or was removed first) | expired (nobody applied it in time). Only a
        pending or a ready act can still be applied; the other five are final."""
        if c.applied is not None and c.applied <= now:
            return "applied"
        if c.void is not None and c.void <= now:
            return "void"
        if c.withdrawn is not None and c.withdrawn <= now:
            return "withdrawn"
        last = self.apply_end(c)
        if self.custodian_end(self.custodians[c.by]) <= min(now, last):
            return "ended"
        if now > last:
            return "expired"
        return "ready" if now >= self.notice_end(c) else "pending"

    def pending(self, c: Correction, now: datetime) -> bool:
        """A noticed act that can still be applied."""
        return c.class_ == "noticed" and self.noticed_status(c, now) in ("pending", "ready")

    def live_signers(self, c: Correction, now: datetime) -> list[str]:
        """The custodians who signed a noticed act and whose key is live at `now`."""
        return [x for x in c.signers if self.custodian_status(self.custodians[x], now) == "live"]

    def void_span(self, c: Correction) -> tuple[datetime, datetime]:
        """The interval `[start, end)` on which a `void_ballot` is pending, and so pauses its ballot: from
        its entry until it is applied, voided by objections, withdrawn, ended with the key of the custodian
        who posted it, or out of time. Exactly the times at which `pending(c, now)` holds."""
        last = self.apply_end(c)
        end = last + SECOND
        key_end = self.custodian_end(self.custodians[c.by])
        if key_end <= last:
            end = key_end
        for t in (c.applied, c.void, c.withdrawn):
            if t is not None:
                end = min(end, t)
        return c.time, max(end, c.time)

    def void_pending(self, ballot: str, now: datetime) -> Correction | None:
        """The pending `void_ballot` of a ballot, if any (never two at once: VB3)."""
        for c in reversed(self.corrections.values()):
            if expired(c.time, now, NOTICE_DAYS + APPLY_WINDOW_DAYS):
                break
            if c.act == "void_ballot" and c.target["id"] == ballot and self.pending(c, now):
                return c
        return None

    # -- key recoveries -----------------------------------------------------------
    def recovery_start(self, r: Recovery, now: datetime | None = None) -> datetime | None:
        """Where the notice of the recovery starts, as things stand at `now` (default: the time of the state):
        the request, after a freeze; for an open recovery the co-signature that completed the number it needs,
        and None until then. Once the request has been open RECOVER_DROP_DAYS without all its co-signatures
        (`dropped`), the notice starts at that moment: after a freeze always (the key stays frozen), and for an
        open recovery where the co-signatures already given are enough, otherwise at the co-signature that
        makes them enough (None until then)."""
        now = self.time if now is None else now
        if now is not None and dropped(self, r, now):
            if r.freeze is not None or cosigned(self, r, r.cosigners[:r.given_at_drop()], now):
                return r.drop_time()
            return r.notice
        return r.time if r.freeze is not None else r.notice

    def recovery_notice_days(self, r: Recovery, now: datetime | None = None) -> int:
        """The notice of the recovery as things stand at `now` (default: the time of the state): 21 days after a
        freeze, 30 without one, and RECOVER_LOWERED_NOTICE_DAYS whenever the co-signers it needs were lowered
        below its number, because fewer other Master Builders exist or because the request dropped (`dropped`)."""
        now = self.time if now is None else now
        if now is not None and (lowered(self, r, now) or dropped(self, r, now)):
            return RECOVER_LOWERED_NOTICE_DAYS
        return RECOVER_NOTICE_DAYS if r.freeze is not None else RECOVER_OPEN_NOTICE_DAYS

    def recovery_notice_end(self, r: Recovery, now: datetime | None = None) -> datetime | None:
        """The first second at which the recovery may be applied, as things stand at `now`; None while a
        recovery asked without a freeze still waits for the co-signatures that start its notice."""
        start = self.recovery_start(r, now)
        if start is None:
            return None
        return start + self.recovery_notice_days(r, now) * DAY

    def recovery_end(self, r: Recovery, now: datetime | None = None) -> datetime:
        """The last second at which the recovery is alive: RECOVER_EXPIRY_DAYS after its notice began, or
        after the request while its notice has not begun (as things stand at `now`)."""
        return (self.recovery_start(r, now) or r.time) + RECOVER_EXPIRY_DAYS * DAY

    def recovery_status(self, r: Recovery, now: datetime) -> str:
        """requested (an open recovery that waits for its co-signers: nothing is frozen yet) | pending (under
        notice, or after a freeze still short of its co-signatures) | ready (may be applied now) | applied | objected (the old key stopped it) | opposed (Master Builders voided it) |
        canceled (the freeze it followed was withdrawn or voided, or the login was admitted anew) | expired.
        A requested, a pending or a ready one is alive; a pending or a ready one is under way."""
        if r.applied is not None and r.applied <= now:
            return "applied"
        if r.objected is not None and r.objected <= now:
            return "objected"
        if r.void is not None and r.void <= now:
            return "opposed"
        m = self.members.get(r.login)
        if m is not None and r.admitted and iso(m.since[1]) != r.admitted and m.since[1] <= now:
            return "canceled"              # a new membership of the login began: the recovery was of the earlier one
        last = self.recovery_end(r, now)
        f = self.corrections.get(r.freeze) if r.freeze is not None else None
        cuts = [t for t in ((f.void, f.withdrawn) if f is not None else ()) if t is not None]
        if cuts and min(cuts) <= min(now, last):
            return "canceled"
        if now > last:
            return "expired"
        if self.recovery_start(r, now) is None:
            return "requested"
        if now < self.recovery_notice_end(r, now) or not cosigned(self, r, r.cosigners, now):
            return "pending"               # under notice, or (after a freeze) still short of its co-signatures
        return "ready"

    def recovery_alive(self, login: str, now: datetime) -> Recovery | None:
        """The recovery of this member's key that is alive at `now` (requested, pending or ready), if any.
        While there is one its new key is held, and it takes co-signatures, an objection and oppositions."""
        r = self.recoveries.get(login)
        return r if r is not None and self.recovery_status(r, now) in ("requested", "pending", "ready") else None

    def recovering(self, login: str, now: datetime) -> Recovery | None:
        """The recovery of this member's key that is under way at `now` (pending or ready), if any. While
        there is one the key the ledger holds stays frozen, also after the freeze that came before it has
        run its time."""
        r = self.recoveries.get(login)
        return r if r is not None and self.recovery_status(r, now) in ("pending", "ready") else None

    def key_frozen(self, login: str, now: datetime) -> bool:
        """The member's key signs nothing but what a frozen member may sign: a freeze is in force, or a
        recovery of the key is under way."""
        return self.frozen(login, now) is not None or self.recovering(login, now) is not None

    def frozen_keys(self, now: datetime) -> set[str]:
        """The logins whose key is frozen at `now`: by a freeze in force or by a recovery under way (FK4)."""
        return ({x.target["login"] for x in self.acting("freeze_key", now)}
                | {x for x in self.recoveries if self.recovering(x, now) is not None})

    def acting(self, act: str, now: datetime, **target) -> list[Correction]:
        """The corrections of one act in force at `now`, whose target has the given fields, in the order of
        their entries. No act lasts longer than MAX_ACT_DAYS, and the records are in the order of time, so the
        search stops at the first record too old to be in force."""
        found = []
        for c in reversed(self.corrections.values()):
            if now - c.time >= MAX_ACT_DAYS * DAY:
                break
            if c.act == act and all(c.target.get(k) == v for k, v in target.items()) and self.in_force(c, now):
                found.append(c)
        return found[::-1]

    def frozen(self, login: str, now: datetime) -> Correction | None:
        """The freeze in force on a member's key, if any (never two at once: REFREEZE_AFTER_DAYS)."""
        return next(iter(self.acting("freeze_key", now, login=login)), None)

    def witness_frozen(self, name: str, now: datetime) -> Correction | None:
        return next(iter(self.acting("freeze_witness", now, name=name)), None)

    def stayed(self, ballot: str, now: datetime) -> Correction | None:
        return next(iter(self.acting("stay", now, ballot=ballot)), None)

    def halted(self, now: datetime) -> Correction | None:
        return next(iter(self.acting("halt", now)), None)

    def room_hold(self, login: str, now: datetime) -> Correction | None:
        return next(iter(self.acting("hold_room", now, login=login)), None)

    # -- the effective clock ------------------------------------------------------
    def _pausing(self, ballot: str | None) -> list[Correction]:
        """Every halt, and for `ballot` also its stay and every `void_ballot` of it: the corrections whose
        intervals pause a clock. Read from an index that is brought up to date here, one record at a time,
        so no call scans `corrections`."""
        n = len(self.corrections)
        if n < self._indexed:                # never in replay (the map only grows): a state edited by hand
            self._indexed, self._halts, self._stays = 0, [], {}
        if n > self._indexed:
            for seq, c in itertools.islice(self.corrections.items(), self._indexed, None):
                if c.act == "halt":
                    self._halts.append(seq)
                elif c.act == "stay":
                    self._stays.setdefault(c.target["ballot"], []).append(seq)
                elif c.act == "void_ballot":
                    self._stays.setdefault(c.target["id"], []).append(seq)
            self._indexed = n
        seqs = self._halts + self._stays.get(ballot, []) if ballot is not None else self._halts
        return [self.corrections[s] for s in seqs]

    def pauses(self, ballot: str | None = None) -> list[tuple[datetime, datetime]]:
        """The intervals during which the effective clock stands still, merged and in order: every halt, and
        for `ballot` also its stay and the time a `void_ballot` of it was pending. Intervals that overlap
        are counted once."""
        b = self.ballots.get(ballot) if ballot is not None else None
        if b is not None and b.kind in UNSTOPPABLE_KINDS:
            return []                       # an amendment, and the ballot that removes a custodian, run on wall time
        spans = sorted(self.void_span(c) if c.act == "void_ballot" else self.span(c) for c in self._pausing(ballot))
        merged: list[tuple[datetime, datetime]] = []
        for a, b in spans:
            if b <= a:
                continue
            if merged and a <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], b))
            else:
                merged.append((a, b))
        return merged

    def paused(self, start: datetime, now: datetime, ballot: str | None = None) -> timedelta:
        """The paused time inside `[start, now)`."""
        return sum((min(b, now) - max(a, start) for a, b in self.pauses(ballot) if min(b, now) > max(a, start)),
                   timedelta(0))

    def effective(self, start: datetime, now: datetime, ballot: str | None = None) -> timedelta:
        """Elapsed wall time from `start` to `now` minus the halted time in between (and, for `ballot`, the
        time it was stayed or under a pending void). Only ballot windows, exam expiry and retry, the time in which
        a lot is drawn, the waiver of the second sponsor, and the expiry of invitations and petitions (and the time
        a lapsed invitation still counts in its inviter's budget) are counted on it; every other duration of the
        protocol is wall time."""
        return (now - start) - self.paused(start, now, ballot)

    def waited(self, start: datetime, now: datetime, days: int, ballot: str | None = None) -> bool:
        """`waited` on the effective clock."""
        return self.effective(start, now, ballot) >= days * DAY

    def expired(self, start: datetime, now: datetime, days: int, ballot: str | None = None) -> bool:
        """`expired` on the effective clock."""
        return self.effective(start, now, ballot) > days * DAY

    def due(self, start: datetime, span: timedelta, ballot: str | None = None) -> datetime:
        """The last wall time `t` with `effective(start, t) <= span`, as the pauses stand: where a deadline
        of `span` after `start` falls. A view for people and tools; the rules compare `effective` itself."""
        t = start + span
        for a, b in self.pauses(ballot):
            if b > start and a <= t:
                t += b - max(a, start)
        return t

    def ballot_due(self, b: "Ballot", deadline: datetime) -> datetime:
        """The wall time at which the ballot's own clock reaches `deadline` (one of its stored deadlines), as
        the pauses stand. Equal to `deadline` for a ballot that was never halted or stayed."""
        return deadline if b.opened is None else self.due(b.opened, deadline - b.opened, b.id)

    def ballot_time(self, b: "Ballot", now: datetime) -> datetime:
        """Where the ballot's own clock stands at `now`: its opening plus the effective time since. The rules
        compare it with `commit_until` and `reveal_until`, which never move."""
        start = b.opened if b.opened is not None else min(now, b.commit_until)
        return start + self.effective(start, now, b.id)

    def reserved(self, login: str, now: datetime) -> bool:
        """A petition that still holds its name, its key and its sponsors: live, or under an open ballot."""
        return login in self.petitions and (self.live(login, now)
                                            or self.open_ballot_on("admission", fold(login)) is not None)

    def name_holders(self, name: str, now: datetime) -> list[tuple[str, str]]:
        """Every (role, spelling) that holds `name` up to case: members of any status, witnesses, custodians
        (live or not), live invitations, reserved petitions and the subjects of open ballots that add a witness."""
        f = fold(name)
        return ([("member", x) for x in self.members if fold(x) == f]
                + [("witness", x) for x in self.witnesses if fold(x) == f]
                + [("custodian", x) for x in self.custodians if fold(x) == f]
                + [("invitation", x) for x in self.invitations if fold(x) == f and self.invited(x, now)]
                + [("petition", x) for x in self.petitions if fold(x) == f and self.reserved(x, now)]
                + [("ballot", b.subject["name"]) for b in self.ballots.values()
                   if b.result is None and b.kind == "witness" and b.subject["action"] == "add"
                   and fold(b.subject["name"]) == f]
                + [("claim", c.name) for c in self._live_claims(now) if fold(c.name) == f])

    def _live_claims(self, now: datetime) -> list[Claim]:
        c = self.claim_pending(now)
        return [c] if c is not None else []

    def key_holders(self, key: str, now: datetime) -> list[tuple[str, str]]:
        """Every (role, name) that holds the public key `key`: members, witnesses, custodians (the key and the
        revoke key of each, live or not), reserved petitions, proposed witnesses and the new key of a recovery
        that is alive (an invitation names no key). Keys are compared by their point, so the same key under the
        other key type is held too."""
        raw = public_point(key)             # validated once; the keys the state holds are only decoded (`holds`)
        if raw is None:
            return []
        return ([("member", m.login) for m in self.members.values() if holds(m.key, raw)]
                + [("witness", x) for x, k in self.witnesses.items() if holds(k, raw)]
                + [("custodian", c.name) for c in self.custodians.values()
                   if holds(c.key, raw) or holds(c.revoke_key, raw)]
                + [("petition", x) for x, p in self.petitions.items()
                   if holds(p["key"], raw) and self.reserved(x, now)]
                + [("ballot", b.subject["name"]) for b in self.ballots.values()
                   if b.result is None and b.kind == "witness" and b.subject["action"] == "add"
                   and holds(b.subject["key"], raw)]
                + [("recovery", x) for x, r in self.recoveries.items()
                   if holds(r.key, raw) and self.recovery_alive(x, now) is not None]
                + [("claim", c.name) for c in self._live_claims(now) if holds(c.key, raw) or holds(c.revoke_key, raw)])

    def id_holders(self, github_id: int, now: datetime) -> list[tuple[str, str]]:
        """Every (role, login) that holds the GitHub account `github_id`: members of any status (the founders
        among them), live invitations and reserved petitions."""
        return ([("member", m.login) for m in self.members.values() if m.github_id == github_id]
                + [("invitation", x) for x, i in self.invitations.items()
                   if i["github_id"] == github_id and self.invited(x, now)]
                + [("petition", x) for x, p in self.petitions.items()
                   if p["github_id"] == github_id and self.reserved(x, now)])

    def key_owner(self, key: str, now: datetime) -> str | None:
        """The member, witness, petitioner or proposed witness already using this public key, if any."""
        holders = self.key_holders(key, now)
        return holders[0][1] if holders else None

    def login_taken(self, login: str) -> str | None:
        """The existing member, witness or custodian name equal to `login` up to case, if any."""
        for other in list(self.members) + list(self.witnesses) + list(self.custodians):
            if same_login(other, login):
                return other
        return None

    def open_ballot_on(self, kind: str, key: str) -> "Ballot | None":
        for b in self.ballots.values():
            if b.result is None and b.kind == kind and subject_key(kind, b.subject) == key:
                return b
        return None

    def open_sanction_on(self, login: str) -> "Ballot | None":
        """The first open sanction ballot on the member `login` (exact), whatever its measure."""
        for b in self.ballots.values():
            if b.result is None and b.kind == "sanction" and b.subject["member"] == login:
                return b
        return None

    def open_by(self, login: str, kind: str | None = None) -> int:
        """How many ballots opened by `login` are open and share the count of a ballot of `kind`
        (OPEN_BALLOTS_PER_OPENER): amendments are counted apart, a removal ballot never; without `kind`, all."""
        def share(k: str) -> bool:
            return kind is None or (k != "custodian" and (k == "amendment") == (kind == "amendment"))
        return sum(1 for b in self.ballots.values() if b.result is None and b.opened_by == login and share(b.kind))


# ---------------------------------------------------------- state digest -----
# SPEC §4.11. Each record lists its stored fields by name, so a field added to a dataclass is not in the
# document until it is written here (and tests/test_digest.py fails until it is).

STATE_VERSION = 2                   # the `v` of the state document
# What leaves the state for good, in the order it does, kept as a count and a hash chain (`_absorb`): the
# ballots no rule reads any more, the notes beyond the newest NOTES_KEPT, and three kinds of record no rule
# ever reads (each checkpoint, each beacon a lot used, each passed amendment).
HISTORY = ("amendments", "ballots", "beacons", "checkpoints", "notes")
# A ballot that ended (closed, or voided) is read by no rule once this many days have passed (SPEC §4.11):
# an undo is posted within UNDO_WINDOW_DAYS of the close and applied within NOTICE_DAYS + APPLY_WINDOW_DAYS
# of its posting, a re-run opens within RERUN_DAYS and the opener's wait lasts REOPEN_AFTER_DAYS.
BALLOT_RETIRE_DAYS = UNDO_WINDOW_DAYS + NOTICE_DAYS + APPLY_WINDOW_DAYS


def _plain(v):
    """A stored value as JSON: a time in its text form, a set as an ascending array, a tuple as an array, and
    an object without its null members. Anything that is none of these is left as it is, and `canonical`
    refuses what JSON cannot carry (a float, for one)."""
    t = type(v)
    if t is str or t is int or t is bool:
        return v
    if t is datetime:
        return iso(v)
    if t is list or t is tuple:
        return [_plain(x) for x in v]
    if t is dict:
        return {k: _plain(x) for k, x in v.items() if x is not None}
    if t is set or t is frozenset:
        return sorted(v)
    return v


def _pairs(m: dict, facts=lambda v: v) -> list:
    """A map as an array of `[key, value]` pairs in ascending order of key: strings by code point, integers
    by value, and the `(login, degree)` key of an exam by login and then by degree, written as an array."""
    return [[list(k) if type(k) is tuple else k, facts(m[k])] for k in sorted(m)]


def _member_facts(m: Member) -> dict:
    return {"login": m.login, "key": m.key, "degree": m.degree, "since": _pairs(m.since), "sponsors": m.sponsors,
            "status": m.status, "activity": m.activity, "seat_until": m.seat_until, "past_seats": m.past_seats,
            "status_since": m.status_since, "suspended_until": m.suspended_until,
            "sponsor_ban_until": m.sponsor_ban_until, "founder": m.founder, "last_work": m.last_work,
            "fraud_history": m.fraud_history, "github_id": m.github_id, "last_rekey": m.last_rekey, "left": m.left,
            "missed": m.missed, "heard": m.heard}


def _ballot_facts(b: Ballot) -> dict:
    return {"id": b.id, "kind": b.kind, "subject": b.subject, "electors": b.electors, "commit_until": b.commit_until,
            "reveal_until": b.reveal_until, "opened_by": b.opened_by, "commits": _pairs(b.commits),
            "reveals": _pairs(b.reveals), "result": b.result, "frozen": b.frozen, "opened": b.opened,
            "closed": b.closed, "undo": b.undo, "corrected": b.corrected, "base": b.base, "rerun": b.rerun}


def _exam_facts(x: Exam) -> dict:
    return {"candidate": x.candidate, "degree": x.degree, "examiners": x.examiners, "beacon_round": x.beacon_round,
            "opened": x.opened, "reports": _pairs(x.reports), "pool": x.pool, "work_ref": x.work_ref,
            "ranking": x.ranking, "recused": x.recused, "k": x.k, "consumed": x.consumed,
            "ballot_failed": x.ballot_failed, "lapsed": x.lapsed, "skipped": x.skipped}


def _custodian_facts(c: Custodian) -> dict:
    return {"name": c.name, "key": c.key, "revoke_key": c.revoke_key, "member": c.member, "alive": c.alive,
            "genesis": c.genesis, "revoked": c.revoked, "removed": c.removed, "since": c.since, "claim": c.claim}


def _correction_facts(c: Correction) -> dict:
    return {"seq": c.seq, "by": c.by, "act": c.act, "target": c.target, "ground": c.ground,
            "reason_sha256": c.reason_sha256, "time": c.time, "class": c.class_, "until": c.until,
            "subject": c.subject, "objections": c.objections, "void": c.void, "withdrawals": c.withdrawals,
            "withdrawn": c.withdrawn, "withdrawn_by": c.withdrawn_by, "signers": c.signers, "applied": c.applied, "applied_by": c.applied_by,
            "released": c.released}


def _recovery_facts(r: Recovery) -> dict:
    return {"login": r.login, "key": r.key, "seq": r.seq, "time": r.time, "freeze": r.freeze,
            "admitted": r.admitted, "cosigners": r.cosigners, "objected": r.objected, "applied": r.applied,
            "notice": r.notice, "final": r.final, "opposed": r.opposed, "void": r.void,
            "dropped": r.dropped, "departure": r.departure}


def _claim_facts(c: Claim) -> dict:
    return {"seq": c.seq, "founder": c.founder, "name": c.name, "key": c.key, "revoke_key": c.revoke_key,
            "time": c.time, "objected": c.objected, "objector": c.objector, "applied": c.applied}


def _succession_facts(s: Succession) -> dict:
    return {"seq": s.seq, "by": s.by, "time": s.time, "end": s.end, "canceled_by": s.canceled_by}


def _checkpoint_facts(body: dict, actor: str) -> dict:
    return {"witness": actor, "upto_seq": body["upto_seq"], "head": body["head"], "state_sha256": body["state_sha256"],
            "state_version": body["state_version"], "root": body.get("root"), "anchor": body.get("anchor")}


def _snapshot(v):
    """A value held in a plain map or list, as a comparable value: what the digest compares to know whether a
    record of an invitation, a petition, a witness mark or a note changed in place."""
    t = type(v)
    if t is dict:
        return ("{",) + tuple(sorted((k, _snapshot(x)) for k, x in v.items()))
    if t is list or t is tuple:
        return ("[",) + tuple(_snapshot(x) for x in v)
    return v


def _same(v):
    return v


def _version(r: _Record) -> int:
    return r._v


@dataclass(frozen=True)
class Section:
    """A keyed collection of the state (SPEC §4.11): its records, how each is written, and what tells the
    digest that a record changed (its version, its value, or a snapshot of a plain map)."""
    name: str
    items: object                      # State -> iterable of (key, value)
    facts: object = _same              # value -> the record as stored facts
    fingerprint: object = _same        # value -> a value equal to the last one exactly while the record is unchanged


SECTIONS = {s.name: s for s in (
    Section("members", lambda st: st.members.items(), _member_facts, _version),
    Section("witnesses", lambda st: st.witnesses.items()),
    Section("custodians", lambda st: st.custodians.items(), _custodian_facts, _version),
    Section("corrections", lambda st: st.corrections.items(), _correction_facts, _version),
    Section("recoveries", lambda st: st.recoveries.items(), _recovery_facts, _version),
    Section("claims", lambda st: st.claims.items(), _claim_facts, _version),
    Section("invitations", lambda st: st.invitations.items(), fingerprint=_snapshot),
    Section("petitions", lambda st: st.petitions.items(), fingerprint=_snapshot),
    Section("ballots", lambda st: st.ballots.items(), _ballot_facts, _version),
    Section("exams", lambda st: st.exams.items(), _exam_facts, _version),
    Section("notes", lambda st: ((n["seq"], n) for n in st.notes), fingerprint=_snapshot),
    Section("pins", lambda st: st.pins.items()),
    Section("prior_pins", lambda st: st.prior_pins.items()),
    Section("prior_until", lambda st: st.prior_until.items()),
    Section("day_entries", lambda st: st.day_entries.items()),
    Section("witness_marks", lambda st: st.witness_marks.items(), fingerprint=_snapshot),
    Section("known_keys", lambda st: ((k, True) for k in st.known_keys)),
)}
# The fields of `State` that are neither a section nor a scalar: `hashes` (`head` and `seq` commit to it),
# `history` (written as itself) and the two indexes of the history, which are functions of what it absorbed.
NOT_SECTIONS = ("hashes", "history", "retired", "degree_tables")


class _Leaves:
    """The digest's memory of one section: per key, the fingerprint and the leaf it last hashed; the keys in
    order; and the root. Not a fact, and never copied (`State.__deepcopy__`)."""
    __slots__ = ("fp", "leaf", "order", "root")

    def __init__(self):
        self.fp, self.leaf, self.order, self.root = {}, {}, None, None


def _leaf(key, record) -> bytes:
    """The leaf of one record: SHA-256 of the canonical JSON of `[key, record]` (an exam's key as an array)."""
    return hashlib.sha256(canonical([list(key) if type(key) is tuple else key, _plain(record)])).digest()


SCALARS = ("name", "head", "seq", "time", "declaration_sha256", "custodian_threshold", "sunset", "day", "acts",
           "epoch", "council_call", "council_pool", "succession")     # the fields written inline, one value each


def _scalars(st: State) -> dict:
    out = {k: getattr(st, k) for k in SCALARS}
    if st.succession is not None:
        out["succession"] = _succession_facts(st.succession)
    return _plain(out)


def _document(st: State, roots: dict) -> dict:
    return {"v": STATE_VERSION, "scalars": _scalars(st), "sections": roots,
            "history": {h: {"count": n, "acc": acc} for h, (n, acc) in st.history.items()}}


def section_records(st: State, name: str) -> list:
    """The records of one section as the digest writes them: `[key, record]`, in ascending order of key."""
    spec = SECTIONS[name]
    return [[list(k) if type(k) is tuple else k, _plain(spec.facts(v))] for k, v in sorted(spec.items(st))]


def state_digest(st: State) -> str:
    """The state digest computed from nothing: every leaf hashed again, and no cache read or written. Equal to
    `st.digest()` for every state; the reference the incremental digest is tested against."""
    roots = {name: merkle_root_bytes([hashlib.sha256(canonical(r)).digest() for r in section_records(st, name)])
             for name in SECTIONS}
    return sha256(canonical(_document(st, roots)))


def _absorb(st: State, name: str, leaf: bytes) -> None:
    """One record leaves the state, or never enters it: `acc' = SHA-256(acc || leaf)`, and the count grows."""
    n, acc = st.history[name]
    st.history[name] = (n + 1, hashlib.sha256(bytes.fromhex(acc) + leaf).hexdigest())


def _record_leaf(record: dict) -> bytes:
    """The leaf of a record that never was in a section (a checkpoint, a beacon, an amendment)."""
    return hashlib.sha256(canonical(_plain(record))).digest()


def ballot_end(st: State, b: Ballot) -> datetime | None:
    """When a ballot stopped being open: its close, or the application of the correction that voided it.
    None while it is open."""
    if b.result is None:
        return None
    if b.closed is not None:
        return b.closed
    c = st.corrections.get(b.corrected)
    return c.applied if c is not None else None


def _ended(st: State, b: Ballot, now: datetime) -> None:
    if st._ended is not None:
        st._ended.append((now, b.id))


def _retire(st: State, now: datetime) -> None:
    """Every ballot that ended more than BALLOT_RETIRE_DAYS before `now` leaves `ballots` for the history of
    ballots, in ascending order of (end, id), with the leaf it had there; its id stays in `retired`."""
    q = st._ended
    if q is None:                            # rebuilt from the stored facts: a new or copied state, or one edited by hand
        ends = ((ballot_end(st, b), b.id) for b in st.ballots.values())
        q = st._ended = collections.deque(sorted(x for x in ends if x[0] is not None))
    batch = []
    while q and expired(q[0][0], now, BALLOT_RETIRE_DAYS):
        batch.append(q.popleft())
    cache = st._leaves.get("ballots")
    for _, bid in sorted(batch):
        b = st.ballots.pop(bid, None)
        if b is not None:                    # the leaf the digest last hashed, while the record is unchanged since
            fresh = cache is not None and cache.fp.get(bid) == b._v
            _absorb(st, "ballots", cache.leaf[bid] if fresh else _leaf(bid, _ballot_facts(b)))
            st.retired.add(bid)


# ------------------------------------------------------------ decisions -----

SUBJECT_FIELDS = {
    "admission": {"candidate": str},
    "advancement": {"member": str, "degree": int},
    "amendment": {"path": str, "new_sha256": str},
    "sanction": {"member": str, "measure": str},
    "witness": {"action": str, "name": str, "key": str, "proof": str},   # `key` and `proof` to add a witness, never to remove one
    "custodian": {"remove": str},                            # the one thing a ballot decides about a custodian
}
SUBJECT_KEYS = {kind: set(fields) for kind, fields in SUBJECT_FIELDS.items()}
# Which standing (Member.standing) a member must have for each measure, when the ballot opens and when it closes.
SANCTION_ON = {
    "admonish": {"active", "suspended", "expelled"},
    "suspend": {"active"},
    "expel": {"active", "suspended"},
    "expel_for_fraud": {"active", "suspended", "voided"},    # `voided`: only by a ballot opened within VOIDED_FRAUD_DAYS of the undo
    "reinstate": {"suspended", "expelled"},
}
# The statuses of a record that is no longer a membership: the member left, was expelled, or the admission
# was undone by a correction (`voided`, which is not a sanction).
GONE = frozenset({"departed", "expelled", "voided"})
# A member in one of these states cannot sign `depart`. Everyone else can, a suspended member included
# (Landmark VII). A frozen key and a halted ledger are not statuses and are not here: neither a freeze nor
# a halt ever stops a member from leaving.
DEPART_BLOCKED = GONE
# A member in one of these states cannot sign `rekey`, nor have their key recovered. A suspended member
# can: a suspension does not oblige anyone to keep a key they no longer trust. A frozen member can, and so
# can anyone during a halt. One exception, `recoverable`: a member whose departure a recovery may still reverse.
REKEY_BLOCKED = GONE
# What is still accepted while the ledger is halted (the unstoppable set): the custodians' own entries, the
# removal of a custodian key, objections, departures, key replacements, every entry of a key recovery and a
# witness's checkpoint; and, by `_unstoppable`, every entry of an amendment ballot and of a ballot that removes
# a custodian. Nothing else: no other ballot is closed and no lot is drawn.
HALT_ALLOWED = CUSTODIAN_SIGNED | RECOVERY_TYPES | {"correction_object", "depart", "rekey", "rekey_object",
                                                   "rekey_cosign", "rekey_oppose", "witness"}
# What a member whose key is frozen may still sign, whatever the entry says: `depart`, `rekey`, the
# objection to a recovery of their own key and their vote in any ballot (the commitment and the reveal: a
# freeze never changes who decides a ballot). By `_frozen_may` also every entry of an amendment ballot and of
# a ballot that removes a custodian. Not an objection to a correction, nor a co-signature or an opposition of
# a recovery: a frozen key may be in other hands, and it never vouches for anyone.
FREEZE_ALLOWED = frozenset({"depart", "rekey", "rekey_object", "ballot_commit", "ballot_reveal"})
# The acts of a correction: the exact fields of each target, how long each lasts by itself, and the one
# ground three of them require. `note` records an act done outside the ledger and has no effect here. The
# two NOTICED_ACTS take effect only when they are applied, after their notice.
TARGET_FIELDS: dict[str, dict[str, tuple[type, bool]]] = {
    "freeze_key": {"login": (str, True)},
    "freeze_witness": {"name": (str, True)},
    "stay": {"ballot": (str, True)},
    "halt": {},
    "hold_room": {"login": (str, True)},
    "note": {"action": (str, True), "target": (str, True), "rule": (str, True)},
    "void_ballot": {"id": (str, True)},
    "undo_ballot": {"id": (str, True)},
}
NOTICED_ACTS = ("void_ballot", "undo_ballot")
UNDO_KINDS = ("admission", "advancement")     # …of an advancement, never one to the 3rd degree (`sunset_ballot`)
ACT_DAYS = {"freeze_key": FREEZE_DAYS, "freeze_witness": FREEZE_DAYS, "stay": STAY_DAYS, "halt": HALT_DAYS,
            "hold_room": HOLD_DAYS}
MAX_ACT_DAYS = max(ACT_DAYS.values())     # no act is in force this long after its entry
ACT_GROUND = {"freeze_key": "key_compromised", "halt": "attack_in_progress", "note": NOTE_GROUND}
STAY_EXEMPT = frozenset({"amendment", "custodian"})     # kinds of ballot no custodian ever stays, voids or undoes


def subject_key(kind: str, subj: dict) -> str:
    """What a ballot is *about*: at most one open ballot per (kind, key). A sanction is about a member and a
    measure, so that no ballot on one measure holds the place of another."""
    k = {"admission": "candidate", "advancement": "member", "amendment": "path",
         "sanction": "member", "witness": "name", "custodian": "remove"}[kind]
    key = fold(str(subj.get(k, "")))
    if kind == "amendment":                 # one slot per text proposed, so nobody holds a path by squatting it
        return f"{key}|{subj.get('new_sha256', '')}"
    return f"{key}|{subj.get('measure', '')}" if kind == "sanction" else key


def sunset_ballot(b: "Ballot") -> bool:
    """A ballot the Sunset condition counts: one that adds a witness, or advances a member to the 3rd degree.
    No custodian stays, voids or undoes one (the office is recused from what would end it)."""
    return ((b.kind == "witness" and b.subject.get("action") == "add")
            or (b.kind == "advancement" and b.subject.get("degree") == canon.SPONSOR_MIN_DEGREE))


def quorum(n: int) -> int:
    """Q(N) = min(N, max(3, ceil(N/3))), in integers."""
    return min(n, max(3, -(-n // 3)))


def quorate(votes: int, electorate: int) -> bool:
    """The votes cast reach the quorum of the electorate. A ballot that is not quorate decides nothing: it
    lapses (section 6.7), and nobody is penalized."""
    return electorate > 0 and votes >= quorum(electorate)


def decide(kind: str, yes: int, no: int, electorate: int) -> bool:
    """The decision function D (Whitepaper §6.3). Pure; exhaustively tested."""
    if kind in ("admission", "advancement"):
        rule = "blackball"
    elif kind in ("amendment", "sanction", "witness"):
        rule = "two_thirds"
    elif kind == "custodian":
        rule = "majority"
    else:
        raise ValueError(f"unknown ballot kind {kind!r}")
    t = yes + no
    if not quorate(t, electorate):
        return False
    if rule == "blackball":
        # Rejected when black balls reach one fifth of the votes cast (5B >= T).
        return 5 * no < t
    if rule == "majority":
        # custodian: more yes than no among the votes cast; a tie fails.
        return yes > no
    # amendment / sanction / witness: two-thirds of votes cast, one-third turnout.
    return 3 * yes >= 2 * t and 3 * t >= electorate


def sponsors_required(st: State, now: datetime, petition: dict | None = None) -> int:
    """Sponsors an admission needs: while fewer than FOUNDING_MASTERS Master Builders are present (neither dormant
    nor silent: the Founding Phase, or a lodge whose other Masters answer nothing), as many Masters as exist (1 or
    2), and one once the petition has been live SPONSOR_WAIVE_DAYS (every Master still votes); else 2. Successors
    never count here."""
    if len(st.present_masters(now)) < canon.FOUNDING_MASTERS:
        if petition is not None and st.waited(petition["time"], now, SPONSOR_WAIVE_DAYS):
            return 1
        return max(1, min(canon.SPONSORS_REQUIRED, len(st.masters(now))))
    return canon.SPONSORS_REQUIRED


def may_sponsor(st: State, login: str, now: datetime) -> bool:
    """An active Master Builder, or a successor, under no sponsorship ban."""
    m = st.members.get(login)
    return (m is not None and m.is_active(now) and st.stands_in(login, now)
            and (m.sponsor_ban_until is None or now >= m.sponsor_ban_until))


def eligible(st: State, now: datetime, min_degree: int = 1, exclude: set[str] = frozenset()) -> list[str]:
    """`State.active` with the dormant members kept: everyone of these degrees who may vote."""
    return sorted(m.login for m in st.members.values()
                  if m.is_active(now) and m.degree >= min_degree and m.login not in exclude)


def electorate(st: State, kind: str, subject: dict, now: datetime) -> tuple[frozenset[str], int]:
    """`(electors, base)`. The rung of each kind is chosen on the members who are present (not dormant); the
    electors are then every active member of that rung, the dormant ones included, and the base, which the
    quorum and the turnout count, is the present ones (dormancy lowers the quorum and never removes a
    vote). An admission and an advancement do not wait for a silent member either (`Member.silent`): such a member
    keeps the vote and leaves the present list. Where no Master Builder is present, an advancement falls back on
    the successors."""
    def rung(low: int, excl=frozenset()) -> tuple[list[str], list[str]]:
        return st.active(now, low, excl), eligible(st, now, low, excl)
    def speaking(low: int, excl=frozenset()) -> tuple[list[str], list[str]]:   # a silent member is not waited for
        present, voters = rung(low, excl)
        return [x for x in present if not st.members[x].silent(now)], voters
    if kind == "admission":                 # the 1st-degree rung holds every voter of the 2nd: none loses the vote
        present, voters = speaking(2)
        if not present:
            present, voters = speaking(1)
    elif kind == "advancement":
        excl = {subject["member"]}
        present, voters = speaking(subject["degree"], excl)
        if len(present) < 3:                # the Masters decide; whoever had the vote on the first rung keeps it
            p3, v3 = speaking(3, excl)
            present, voters = p3, sorted({*voters, *v3})
        if not present:                     # no Master Builder present: the successors decide, the dormant keep the vote
            present = [x for x in st.successors(now) if x not in excl]
            voters = sorted({*voters, *present})
    elif kind in ("amendment", "witness"):
        present, voters = rung(3)
    elif kind == "sanction":  # Arbiters (7+), else Masters; never the accused
        excl = {subject["member"]}
        present, voters = rung(7, excl)
        if len(present) < 3:
            present, voters = rung(3, excl)
    elif kind == "custodian":  # the Master Builders, never the member the custodian is linked to
        present, voters = rung(3, {st.custodians[subject["remove"]].member})
    else:
        raise ValueError(f"unknown ballot kind {kind!r}")
    return frozenset(voters), len(present) if present else min(1, len(voters))


def electors_for(st: State, kind: str, subject: dict, now: datetime) -> frozenset[str]:
    return electorate(st, kind, subject, now)[0]


def wait_ok(st: State, m: Member, target: int, now: datetime) -> bool:
    return waited(m.since[m.degree], now, st.degree(target).wait_days)


def examiner_pool(st: State, m: Member, target: int, now: datetime, skip=frozenset(), wide=False) -> list[str]:
    """Peers of the target degree, never the candidate, sponsors only as a last resort.

    Ladder: (1) degree >= target, sponsors excluded; (2) any Master Builder,
    sponsors excluded; (3) any Master Builder except the candidate; (4) in a succession, the successors except
    the candidate. Rungs 2 and 3 leave out a silent Master Builder (`Member.silent`), as a dormant one. The first rung that can seat the required number of examiners is used, and otherwise
    everyone any rung holds, which then lowers the number: so no lot alternates between two members who never
    answer, each called too rarely to fall silent while the other is. `skip` are the silent examiners of the
    exam before: they are left out of every rung, unless nobody else is left. `wide` (the exam before timed
    out) seats everyone any rung holds, and never fewer than the first rung that seats the number: every member
    who never answers is called by the next lot, and so falls silent. The founding cohort's own rungs are the
    last resort of a founder's lot, except in a wide lot, which seats the cohort too.
    """
    k = st.degree(target).examiners
    excl = {m.login, *m.sponsors, *skip}
    def speaking(pool: list[str]) -> list[str]:          # the all-Masters rungs leave a silent Master out
        return [x for x in pool if not st.members[x].silent(now)]
    rungs = [st.active(now, target, excl), speaking(st.active(now, 3, excl)),
             speaking(st.active(now, 3, {m.login, *skip})),
             [x for x in st.successors(now) if x != m.login and x not in skip]]
    groups = [rungs]
    if m.founder and not wide:
        # The founding cohort never grades itself while enough other members exist (Whitepaper §9.3), except in
        # the lot after a timeout: every member who never answers is called, founders too, and so falls silent.
        cohort = {x.login for x in st.members.values() if x.founder}
        groups = [[[x for x in r if x not in cohort] for r in rungs], rungs]
    for group in groups:
        for pool in ([sorted({x for r in group for x in r})] if wide else group):
            if len(pool) >= k:
                return pool
    last = sorted({x for r in rungs for x in r})     # no rung seats k: everyone any rung holds is drawn
    if not last and skip:
        return examiner_pool(st, m, target, now, wide=wide)
    return last


def membership(m: Member) -> str:
    """Names one membership of a login: a ballot opened on it never touches a later one (re-admission)."""
    return iso(m.since[1])


# ------------------------------------------------------------- strict JSON ---

def strict_value(v, depth: int = 1) -> None:
    """Raise ValueError unless `v` is a value the protocol can carry.

    Objects with string keys, arrays, strings of ASCII (line feed, U+0020 to U+007E), booleans and
    integers within ±(2^53 − 1). No float, no null, at most MAX_DEPTH nested containers.
    """
    t = type(v)
    if t is str:
        if STRING_RE.fullmatch(v) is None:
            raise ValueError("a string holds a character outside ASCII (line feed, U+0020 to U+007E)")
    elif t is bool:
        pass
    elif t is int:
        if not -MAX_SAFE_INT <= v <= MAX_SAFE_INT:
            raise ValueError("an integer is outside ±(2^53 − 1)")
    elif t is dict or t is list:
        if depth > MAX_DEPTH:
            raise ValueError(f"values nest deeper than {MAX_DEPTH} levels")
        if t is dict:
            for k, x in v.items():
                if type(k) is not str:
                    raise ValueError("an object key is not a string")
                strict_value(k, depth)
                strict_value(x, depth + 1)
        else:
            for x in v:
                strict_value(x, depth + 1)
    else:
        raise ValueError("null is not allowed" if v is None else f"a value of type {t.__name__} is not allowed")


def _no_dupes(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError(f"duplicate key {k!r}")
        d[k] = v
    return d


def _no_constants(c):
    raise ValueError(f"non-standard JSON constant {c}")


def _no_float(s):
    raise ValueError(f"a number with a fraction or an exponent is not allowed ({s[:24]})")


def _strict_int(s: str) -> int:
    if len(s.lstrip("-")) > MAX_INT_DIGITS:          # judged on the text: no reliance on the runtime's limits
        raise ValueError("an integer is outside ±(2^53 − 1)")
    v = int(s)
    if not -MAX_SAFE_INT <= v <= MAX_SAFE_INT:
        raise ValueError("an integer is outside ±(2^53 − 1)")
    return v


def _nesting(text: str) -> int:
    """The deepest nesting of arrays and objects in a JSON text, scanned without recursion."""
    depth = deepest = 0
    in_string = escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
            deepest = max(deepest, depth)
        elif ch in "]}":
            depth -= 1
    return deepest


def strict_json(raw: bytes | str):
    """Parse one JSON text under the protocol's encoding rules. Raises ValueError."""
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("not UTF-8") from None
    else:
        text = raw
    if text.startswith("﻿"):
        raise ValueError("a byte order mark is not allowed")
    if _nesting(text) > MAX_DEPTH:
        raise ValueError(f"values nest deeper than {MAX_DEPTH} levels")
    try:
        value = json.loads(text, object_pairs_hook=_no_dupes, parse_constant=_no_constants, parse_float=_no_float,
                           parse_int=_strict_int)
    except RecursionError:                            # unreachable after the scan above; kept as a net
        raise ValueError(f"values nest deeper than {MAX_DEPTH} levels") from None
    strict_value(value)
    return value


# ---------------------------------------------------------------- shapes -----
# The exact body of each entry type: field -> (JSON type, required). An unknown field is refused. The
# patterns and ranges of the values are checked by each type's rule, with its own message.

_R, _O = True, False
BODY_FIELDS: dict[str, dict[str, tuple[type, bool]]] = {
    "genesis": {"name": (str, _R), "pins": (dict, _R), "declaration_sha256": (str, _R),
                "founders": (list, _R), "witnesses": (list, _R), "custodians": (list, _R),
                "custodian_threshold": (int, _R)},
    "invite": {"login": (str, _R), "github_id": (int, _R)},
    "petition": {"key": (str, _R), "declaration_sha256": (str, _R)},
    "vouch": {"candidate": (str, _R)},
    "ballot_open": {"id": (str, _R), "kind": (str, _R), "subject": (dict, _R), "commit_days": (int, _O),
                    "reveal_days": (int, _O), "rerun": (str, _O)},
    "ballot_commit": {"id": (str, _R), "commitment": (str, _R)},
    "ballot_reveal": {"id": (str, _R), "vote": (str, _R), "salt": (str, _R)},
    "ballot_close": {"id": (str, _R)},
    "exam_open": {"candidate": (str, _R), "degree": (int, _R), "work_ref": (str, _R), "beacon_round": (int, _R)},
    "exam_draw": {"candidate": (str, _R), "degree": (int, _R), "beacon": (str, _R)},
    "exam_report": {"candidate": (str, _R), "degree": (int, _R), "verdict": (str, _R), "reason": (str, _O)},
    "exam_recuse": {"candidate": (str, _R), "degree": (int, _R)},
    "council_call": {"beacon_round": (int, _R)},
    "council_draw": {"beacon": (str, _R)},
    "work": {"ref": (str, _R), "kind": (str, _O)},
    "depart": {},
    "witness": {"upto_seq": (int, _R), "head": (str, _R), "state_sha256": (str, _R), "state_version": (int, _R),
                "root": (str, _O), "anchor": (str, _O)},
    "rekey": {"key": (str, _R), "proof": (str, _R)},
    "correction": {"act": (str, _R), "target": (dict, _R), "ground": (str, _R), "reason_sha256": (str, _R)},
    "correction_withdraw": {"seq": (int, _R)},
    "correction_object": {"seq": (int, _R)},
    "custodian_alive": {},
    "custodian_revoke": {"name": (str, _R)},
    "correction_cosign": {"seq": (int, _R)},
    "correction_apply": {"seq": (int, _R)},
    "rekey_recover": {"key": (str, _R), "proof": (str, _R)},
    "rekey_cosign": {"login": (str, _R)},
    "rekey_object": {},
    "rekey_oppose": {"login": (str, _R)},
    "rekey_recover_apply": {},
    "custodian_claim": {"name": (str, _R), "key": (str, _R), "revoke_key": (str, _R), "proof": (str, _R),
                        "revoke_proof": (str, _R)},
    "custodian_claim_object": {"seq": (int, _R)},
    "custodian_claim_apply": {"seq": (int, _R)},
    "succession_claim": {},
}
PIN_FIELDS = {path: (str, _R) for path in GENESIS_PINS}
FOUNDER_FIELDS = {"login": (str, _R), "key": (str, _R), "github_id": (int, _R), "proof": (str, _O)}   # `proof`: every founder but the first
WITNESS_FIELDS = {"name": (str, _R), "key": (str, _R), "proof": (str, _R)}
CUSTODIAN_FIELDS = {"name": (str, _R), "key": (str, _R), "revoke_key": (str, _R), "member": (str, _R),
                    "proof": (str, _R), "revoke_proof": (str, _R)}
_JSON_NAME = {str: "a string", int: "an integer", list: "an array", dict: "an object", bool: "a boolean"}


def _need(cond: bool, seq: int, msg: str) -> None:
    if not cond:
        raise Invalid(seq, msg)


def _shape(obj, fields: dict, seq: int, what: str) -> None:
    """`obj` is an object with exactly the listed fields (optional ones may be absent), each of its JSON type."""
    _need(type(obj) is dict, seq, f"malformed {what}: not an object")
    for k in sorted(obj):
        _need(k in fields, seq, f"malformed {what}: unknown field {k!r}")
    for k, (typ, required) in fields.items():
        if k in obj:
            _need(type(obj[k]) is typ, seq, f"malformed {what}: field {k!r} must be {_JSON_NAME[typ]}")
        else:
            _need(not required, seq, f"malformed {what}: missing field {k!r}")


def _check_body(typ: str, body: dict, seq: int) -> None:
    _shape(body, BODY_FIELDS[typ], seq, f"{typ} entry")
    if typ == "genesis":
        _shape(body["pins"], PIN_FIELDS, seq, "genesis entry: pins")
        for f in body["founders"]:
            _shape(f, FOUNDER_FIELDS, seq, "genesis entry: founder")
        for w in body["witnesses"]:
            _shape(w, WITNESS_FIELDS, seq, "genesis entry: witness")
        for c in body["custodians"]:
            _shape(c, CUSTODIAN_FIELDS, seq, "genesis entry: custodian")


# ---------------------------------------------------------------- apply ------

def may_return(old: Member | None, now: datetime) -> bool:
    """No earlier record of the login stands in the way: none, or a departed member, a member whose
    admission a correction undid, or an expelled member, who has waited."""
    return (old is None
            or (old.status in ("departed", "voided") and waited(old.status_since, now, REJOIN_AFTER_DAYS))
            or (old.status == "expelled" and waited(old.status_since, now, EXPELLED_REPETITION_DAYS)))


def recoverable(m: Member | None) -> bool:
    """The key of this record can be recovered, and can stop a recovery: the record is a membership, or the
    member departed (`left`, frozen key or not), which a completed recovery asked in time reverses."""
    return m is not None and (m.status not in REKEY_BLOCKED or (m.status == "departed" and bool(m.left)))


def _petition_checks(st: State, actor: str, body: dict, now: datetime, seq: int) -> None:
    """P0 to P7: who may petition, under which name and with which key (evaluated before the signature)."""
    holders = st.name_holders(actor, now)
    for role, other in holders:
        _need(role != "invitation" or other == actor, seq,
              f"login {actor!r} collides with the invitation of {other!r} (a petition uses exactly the invited login)")
    _need(st.invited(actor, now), seq,
          f"no live invitation for {actor!r} (a Master Builder invites first, and an invitation lapses after "
          f"{INVITE_EXPIRY_DAYS} days)")
    _need(may_return(st.members.get(actor), now), seq,
          f"already a member (departed members, and members whose admission was undone, may petition again "
          f"once {REJOIN_AFTER_DAYS} days have passed, expelled members once {EXPELLED_REPETITION_DAYS} have)")
    for role, other in holders:
        _need(role != "member" or other == actor, seq,
              f"login {actor!r} collides with {other!r} (logins are case-insensitive)")
        _need(role != "witness", seq,
              f"login {actor!r} collides with the witness {other!r} (a witness name cannot become a member login, "
              "and names are case-insensitive)")
        _need(role != "petition" or other == actor, seq,
              f"login {actor!r} collides with the pending petition of {other!r}")
    _need(not st.live(actor, now), seq, "a petition is already pending")
    _need(st.open_ballot_on("admission", fold(actor)) is None, seq, "an admission ballot on this login is open")
    for role, other in holders:
        _need(role != "ballot", seq, f"login {actor!r} is the name proposed by an open witness ballot ({other!r})")
    _need(ed25519(body["key"]), seq, KEY_RULE)
    for role, other in st.key_holders(body["key"], now):
        _need((role, other) == ("member", actor), seq,
              f"this key is already used by {other} (one key per login: members, witnesses and petitions)")
    own = st.members.get(actor)
    mine = (own is not None and same_key(own.key, body["key"])) or any(
        same_login(x, actor) and same_key(q["key"], body["key"]) for x, q in st.petitions.items())
    _need(mine or point(body["key"]) not in st.known_keys, seq,
          "this key was used in this ledger before (a key that was ever registered here is never registered again; "
          "a returning member may keep the key of their own record, and a petitioner the key of their own lapsed "
          "petition)")


def _signer(st: State, e: dict, now: datetime) -> tuple[str, Member | None]:
    """Pure: the public key that must have signed this entry, and the member it belongs to, if any."""
    seq, typ, actor, body = e["seq"], e["type"], e["actor"], e["body"]
    if typ == "genesis":
        _need(len(body["founders"]) >= 1, seq, "genesis needs founders")
        return body["founders"][0]["key"], None
    halt = st.halted(now)
    if halt is not None and typ not in HALT_ALLOWED and not _unstoppable(st, typ, body):
        raise Invalid(seq, f"the ledger is halted {_until(st, halt)}: only custodian entries, custodian_revoke, "
                           "correction_object, depart, rekey, the entries of a key recovery, a witness checkpoint, "
                           "an amendment ballot and the ballot that removes a custodian are accepted")
    if typ in CUSTODIAN_SIGNED:
        _need(len(st.custodians) > 0, seq, "no custodian exists, so no correction exists")
        _need(typ != "custodian_revoke" or body["name"] == actor, seq,
              "the actor of a custodian_revoke is the custodian whose key it removes")
        c = st.custodians.get(actor)
        _need(c is not None, seq, f"{actor} is not a custodian")
        status = st.custodian_status(c, now)
        _need(status == "live", seq, f"the custodian key of {actor} is {status} and signs nothing (a lapsed, "
                                     "revoked or removed key never signs again)")
        return (c.revoke_key if typ == "custodian_revoke" else c.key), None
    if typ == "petition":
        _petition_checks(st, actor, body, now, seq)
        return body["key"], None
    if typ in WITNESS_TYPES and actor in st.witnesses:
        frozen = st.witness_frozen(actor, now)
        if frozen is not None:
            raise Invalid(seq, f"the witness {actor} is frozen {_until(st, frozen)}")
        return st.witnesses[actor], None       # a witness node may close ballots, draw lots and checkpoint
    _need(typ != "witness", seq, "unknown witness")
    m = st.members.get(actor)
    if typ in RECOVERY_TYPES:                  # the one case, besides a petition, in which a key the ledger does not hold signs
        _need(recoverable(m), seq,
              f"{actor} is not a member whose key can be recovered (not a member, departed, expelled or voided)")
        if typ == "rekey_recover":
            _need(ed25519(body["key"]), seq, KEY_RULE)
            return body["key"], None
        rec = st.recoveries.get(actor)
        _need(rec is not None and rec.applied is None and rec.objected is None and rec.void is None, seq,
              f"no recovery of the key of {actor} is pending")
        return rec.key, None
    if typ == "depart":                        # Landmark VII: leaving needs no good standing
        _need(m is not None and m.status not in DEPART_BLOCKED, seq,
              f"{actor} is not a member who can depart (not a member, already departed, expelled or voided)")
    elif typ == "rekey":                       # neither does replacing one's own key…
        _need(m is not None and m.status not in REKEY_BLOCKED, seq,
              f"{actor} is not a member who can replace their key (not a member, departed, expelled or voided)")
    elif typ == "rekey_object":                # …nor defending it, also after a departure signed with the old key
        _need(recoverable(m), seq,
              f"{actor} is not a member who can replace their key (not a member, departed, expelled or voided)")
    elif typ == "ballot_reveal" and m is not None and m.status == "voided" \
            and actor in getattr(st.ballots.get(body["id"]), "commits", ()):
        pass                                   # a vote sealed before the admission was undone is still revealed: it was cast
    else:
        _need(m is not None and m.is_active(now), seq, f"{actor} is not an active member")
    frozen, rec = st.frozen(actor, now), st.recovering(actor, now)
    if (frozen is not None or rec is not None) and not _frozen_may(st, typ, body):
        why = (f"is frozen {_until(st, frozen)}" if frozen is not None else
               f"stays frozen while its recovery is pending (entry {rec.seq}, until "
               f"{iso(st.recovery_end(rec, now))} at the latest)")
        raise Invalid(seq, f"the key of {actor} {why}: a frozen member may only depart, rekey, vote (commit and "
                           "reveal), take part in an amendment ballot or the ballot that removes a custodian, or "
                           "object to a recovery of their own key")
    return m.key, m


def _until(st: State, c: Correction) -> str:
    """How a refusal names the act in its way: when it ends as things stand, and which correction it is."""
    return f"until {iso(st.span(c)[1])} (correction {c.seq})"


def _unstoppable(st: State, typ: str, body: dict) -> bool:
    """The entry opens a ballot of an UNSTOPPABLE_KINDS kind (an amendment, or the removal of a custodian), or
    commits, reveals or closes in one."""
    if typ == "ballot_open":
        return body["kind"] in UNSTOPPABLE_KINDS
    if typ in BALLOT_TYPES:
        b = st.ballots.get(body["id"])
        return b is not None and b.kind in UNSTOPPABLE_KINDS
    return False


def _frozen_may(st: State, typ: str, body: dict) -> bool:
    """What a member signs while their key is frozen: `depart`, `rekey`, `rekey_object`, a vote in any ballot
    (`ballot_commit`, `ballot_reveal`) and every entry of an amendment ballot or of a ballot that removes a
    custodian."""
    return typ in FREEZE_ALLOWED or _unstoppable(st, typ, body)


def _trust(payload, sig, actor, key) -> bool:
    """The verifier of an entry taken on trust (`apply(…, trusted=True)`): its signatures were verified when
    it was merged, and are verified again by every full replay."""
    return True


def apply(st: State, e: dict, verifier=verify, trusted: bool = False) -> None:
    """Fold one entry into the state. `verifier` is the only I/O; tests may inject a stub.

    Whatever goes wrong, the outcome is `Invalid` for this entry: an entry is never a crash. A refusal
    raised by a rule leaves the state and the entry untouched. After any other failure the state must be
    discarded; replay stops at the first refusal, and tools apply an entry to a copy of the state.

    `trusted` is for a verifier that judges new entries on top of history it verified before (SPEC §9.1): the
    signatures of the entry and the state digest of a checkpoint are taken as they stand. Every other rule
    is evaluated all the same, so the state reached is the state a full replay reaches.
    """
    nxt = st.seq + 1
    st._trusted = trusted
    try:
        _apply(st, e, _trust if trusted else verifier)
    except Invalid:
        raise
    except CanonPending as err:
        raise Invalid(nxt, str(err)) from None
    except Exception as err:                 # KeyError, TypeError, OverflowError, RecursionError, OSError, …
        typ = e.get("type") if type(e) is dict else None
        what = f"{typ} entry" if type(typ) is str and typ in HANDLERS else "entry"
        raise Invalid(nxt, f"malformed {what}: {type(err).__name__}: {err}") from err
    finally:
        st._trusted = False


def _apply(st: State, e: dict, verifier) -> None:
    nxt = st.seq + 1
    _need(type(e) is dict and set(e) == ENVELOPE, nxt,
          "an entry has exactly the fields seq, prev, time, type, actor, body, sig")
    try:
        strict_value(e)
    except ValueError as err:
        raise Invalid(nxt, f"not strict JSON: {err}") from None
    seq, typ, actor, body = e["seq"], e["type"], e["actor"], e["body"]
    _need(type(seq) is int and seq == nxt, nxt, f"expected seq {nxt}")
    _need(type(body) is dict and type(typ) is str and type(e["sig"]) is str, seq, "malformed entry")
    limit = MAX_GENESIS_BYTES if seq == 0 else MAX_ENTRY_BYTES
    _need(len(canonical(e)) <= limit, seq, f"entry exceeds {limit} bytes")
    _need(valid_login(actor), seq, "actor must be a valid GitHub login")
    try:
        now = ts(e["time"])
    except ValueError as err:
        raise Invalid(seq, str(err)) from None
    _need(e["prev"] == st.head, seq, "prev does not match head (history was altered)")
    _need(st.time is None or now >= st.time, seq, "time goes backwards")

    _need((typ == "genesis") == (seq == 0), seq, "entry 0 is the genesis, and only entry 0")
    handler = HANDLERS.get(typ)
    _need(handler is not None, seq, f"unknown entry type {typ!r}")
    _check_body(typ, body, seq)
    key, member = _signer(st, e, now)
    _need(verifier(signed_payload(e), e["sig"], actor, key) is True, seq, "bad signature")
    day = e["time"][:10]                     # the UTC calendar day of the entry
    spent = st.day_entries.get(actor, 0) if st.day == day else 0
    exempt = daily_exempt(st, typ, body)
    _need(exempt or spent < ENTRIES_PER_DAY, seq,
          f"{actor} already has {ENTRIES_PER_DAY} entries dated {day} (at most {ENTRIES_PER_DAY} entries per actor "
          "per UTC day; a vote, a close, a lot, a departure, a key replacement or recovery, an objection, the entries "
          "of an amendment ballot or of the ballot that removes a custodian, and custodian_revoke are not counted)")

    if typ in PROVING:
        handler(st, e, now, seq, actor, body, verifier)
    else:
        handler(st, e, now, seq, actor, body)
    if member is not None and typ not in UNCREDITED and st.members.get(actor) is member:
        member.credit(now)                   # activity belongs to the member who signed, once per UTC day
    _succession_watch(st, member, now)
    if st.day != day:
        st.day, st.day_entries = day, {}     # a new day: yesterday's counts are no longer facts
    if not exempt:
        st.day_entries[actor] = spent + 1
    if typ != "witness":
        st.acts += 1                         # what a witness's next checkpoint must find more of
    if st.sunset is None and sunset_reached(st, now):
        st.sunset = now                      # recorded once, never undone: no custodian signs after it
    _retire(st, now)                         # what no rule reads any more leaves the state for its history

    st.hashes.append(entry_hash(e))
    st.head, st.seq, st.time = st.hashes[-1], seq, now


def daily_exempt(st: State, typ: str, body: dict) -> bool:
    """The entry is neither counted nor refused by ENTRIES_PER_DAY: a type of DAILY_EXEMPT, or the opening of an
    amendment ballot or of the ballot that removes a custodian (SPEC §5.4)."""
    return typ in DAILY_EXEMPT or (typ == "ballot_open" and body.get("kind") in UNSTOPPABLE_KINDS)


def sunset_reached(st: State, now: datetime) -> bool:
    """The Sunset condition: at least SUNSET_WITNESSES witnesses, and at least SUNSET_MASTERS active Master
    Builders who are not founders."""
    if len(st.witnesses) < SUNSET_WITNESSES:
        return False
    found = 0
    for m in st.members.values():            # stops at the SUNSET_MASTERS-th: evaluated at every entry until it holds
        if not m.founder and m.degree >= canon.SPONSOR_MIN_DEGREE and m.is_active(now) and not m.dormant(now):
            found += 1
            if found >= SUNSET_MASTERS:
                return True
    return False


def _genesis(st, e, now, seq, actor, body, verifier):
    founders, witnesses, custodians = body["founders"], body["witnesses"], body["custodians"]
    pins = {path: body["pins"][path] for path in GENESIS_PINS}      # exactly these keys (C10)
    _need(all(HEX64.fullmatch(h) for h in pins.values()), seq,
          "genesis must pin each governed path to a sha256 (64 lowercase hex)")
    _need(HEX64.fullmatch(body["declaration_sha256"]) is not None, seq,
          "genesis must record the sha256 of the Declaration (64 lowercase hex)")
    table = pins[DEGREES_PATH]
    status = canon.canon_status(table)       # the pinned table must be available (canon/history/<sha>.toml)
    _need(status != "missing", seq, f"degree canon {table[:12]}… is not archived in canon/history/")
    _need(status == "ok", seq, f"degree canon {table[:12]}… is malformed (33 degrees with exact fields)")
    _need(1 <= len(founders) <= canon.FOUNDING_MASTERS, seq, "1..7 founders")
    _need(founders[0]["login"] == actor, seq, "genesis must be signed by the first founder")
    names = [fold(f["login"]) for f in founders] + [fold(w["name"]) for w in witnesses]
    _need(len(set(names)) == len(names), seq, "duplicate founder or witness name (case-insensitive)")
    _need(all(valid_login(f["login"]) for f in founders), seq, "founder logins must be valid GitHub logins")
    _need(all(valid_login(w["name"]) for w in witnesses), seq, "witness names follow login rules")
    keys = [f["key"] for f in founders] + [w["key"] for w in witnesses]
    _need(all(ed25519(k) for k in keys), seq, KEY_RULE)
    points = {point(k) for k in keys}
    _need(len(points) == len(keys), seq, "founders and witnesses must use distinct keys (one key per login)")
    _need("proof" not in founders[0] and all("proof" in f for f in founders[1:]), seq,
          "the first founder signs the genesis itself and carries no proof; every other founder carries one")
    _need(NAME_RE.fullmatch(body["name"]) is not None, seq, "name: 1..120 printable ASCII characters")
    _need(all(f["github_id"] >= 1 for f in founders), seq,
          "founder github_id must be a positive integer (the numeric GitHub user id)")
    _need(len({f["github_id"] for f in founders}) == len(founders), seq,
          "founders must be distinct GitHub accounts (a github_id appears twice: one GitHub account, one member)")
    n = len(custodians)
    _need(n <= CUSTODIANS_MAX, seq, f"0..{CUSTODIANS_MAX} custodians")
    _need(body["custodian_threshold"] == 0 if n == 0 else 1 <= body["custodian_threshold"] <= n, seq,
          "custodian_threshold is 0 without custodians, and otherwise 1 to the number of custodians")
    _need(all(valid_login(c["name"]) for c in custodians), seq, "custodian names follow login rules")
    names += [fold(c["name"]) for c in custodians]
    _need(len(set(names)) == len(names), seq,
          "a custodian name must differ from every founder login, witness name and other custodian name "
          "(case-insensitive): it is never a member login")
    ckeys = [k for c in custodians for k in (c["key"], c["revoke_key"])]
    _need(all(ed25519(k) for k in ckeys), seq, KEY_RULE)
    points |= {point(k) for k in ckeys}
    _need(len(points) == len(keys) + len(ckeys), seq,
          "a custodian key and its revoke key must differ from each other and from every other key of the genesis")
    _need(all(c["member"] in {f["login"] for f in founders} for c in custodians), seq,
          "a custodian's member must be the login of a founder of this genesis")
    _need(len({c["member"] for c in custodians}) == n, seq,
          "custodians must be linked to distinct members (one person, one custodian key)")
    for f in founders[1:]:
        _need(verifier(founder_message(f["login"], f["github_id"], f["key"]), f["proof"], f["login"], f["key"]) is True,
              seq, f"bad founder proof: the key of {f['login']} must sign the founder message (login, github_id, key)")
    for w in witnesses:
        _need(verifier(witness_message(w["name"], w["key"]), w["proof"], w["name"], w["key"]) is True, seq,
              f"bad witness proof: the key of {w['name']} must sign the witness message (name, key)")
    for c in custodians:
        _need(verifier(custodian_message(c["name"], c["member"], c["key"]), c["proof"], c["name"], c["key"]) is True,
              seq, "bad custodian proof: the custodian key must sign the custodian message (name, member, key)")
        _need(verifier(custodian_revoke_message(c["name"], c["key"], c["revoke_key"]), c["revoke_proof"], c["name"],
                       c["revoke_key"]) is True, seq,
              "bad custodian revoke proof: the revoke key must sign the revoke message (name, key, revoke key)")
    st.pins = pins
    st.known_keys = points
    st.custodians = {c["name"]: Custodian(c["name"], c["key"], c["revoke_key"], c["member"], now, since=now)
                     for c in custodians}
    st.custodian_threshold = body["custodian_threshold"]
    st.declaration_sha256 = body["declaration_sha256"]
    st.name = body["name"]
    for f in founders:  # Founder's abdication: founders are Master Builders, never more.
        st.members[f["login"]] = Member(f["login"], f["key"], 3, {1: now, 2: now, 3: now}, activity=[now],
                                        founder=True, github_id=f["github_id"])
    st.witnesses = {w["name"]: w["key"] for w in witnesses}


def _invite(st, e, now, seq, actor, body):
    """A Master Builder invites a GitHub account to petition, and by that act is its first sponsor."""
    login = body["login"]
    _need(valid_login(login), seq, "login must be a valid GitHub login")
    _need(body["github_id"] >= 1, seq, "github_id must be a positive integer (the numeric GitHub user id)")
    _need(st.stands_in(actor, now), seq,
          "only Master Builders may invite (and, while a succession is in force, the members of the highest degree "
          "present)")
    _need(not same_login(login, actor), seq, "a Master Builder cannot invite themselves")
    for role, other in st.name_holders(login, now):
        if role == "member":
            _need(other == login, seq, f"login {login!r} collides with {other!r} (logins are case-insensitive)")
            _need(may_return(st.members[other], now), seq,
                  f"{login} is already a member (a departed member, or one whose admission was undone, may be "
                  f"invited again once {REJOIN_AFTER_DAYS} days have passed, an expelled member once "
                  f"{EXPELLED_REPETITION_DAYS} have)")
            ballot = st.open_sanction_on(other)
            _need(ballot is None, seq,
                  f"a sanction ballot on {login} is open ({ballot.id if ballot else ''}): the login is invited again "
                  "only once it has closed")
        _need(role != "witness", seq,
              f"login {login!r} collides with the witness {other!r} (a witness name cannot become a member login, "
              "and names are case-insensitive)")
        _need(role != "custodian", seq,
              f"login {login!r} collides with the custodian {other!r} (a custodian name cannot become a member "
              "login, and names are case-insensitive)")
        _need(role != "invitation" or other != login, seq, f"{login} already has a live invitation")
        _need(role != "invitation", seq, f"login {login!r} collides with the invitation of {other!r}")
        _need(role != "petition" or other != login, seq, f"{login} already has a pending petition")
        _need(role != "petition", seq, f"login {login!r} collides with the pending petition of {other!r}")
        _need(role != "ballot", seq, f"login {login!r} is the name proposed by an open witness ballot ({other!r})")
        _need(role != "claim", seq,
              f"login {login!r} collides with the custodian name of a pending claim ({other!r}): nobody is invited "
              "under it while the claim is pending")
    _sponsor_checks(st, actor, now, seq)
    for role, other in st.id_holders(body["github_id"], now):
        _need((role, other) == ("member", login), seq,
              f"the GitHub account with id {body['github_id']} is already the {role} {other!r} (one GitHub account, "
              "one member: a returning member keeps the same login, and no account comes in under another)")
    for other in [x for x in st.invitations if same_login(x, login)]:
        del st.invitations[other]            # only a lapsed one can be left here: the new one replaces it
    st.invitations[login] = {"by": actor, "github_id": body["github_id"], "time": now}


def _petition(st, e, now, seq, actor, body):
    _need(body["declaration_sha256"] == st.declaration_sha256, seq,
          "petition must commit to the sha256 of the Declaration (openmasonry declaration)")
    for other in [x for x in st.petitions if same_login(x, actor)]:
        del st.petitions[other]              # only lapsed ones can be left here (P3, P4): the new one replaces them
    inv = st.invitations.pop(actor)          # the invitation becomes the petition, and its inviter the first sponsor
    st.petitions[actor] = {"key": body["key"], "vouches": [inv["by"]], "time": now, "github_id": inv["github_id"]}
    st.known_keys.add(point(body["key"]))


def sponsorships(st: State, login: str, now: datetime) -> int:
    """What a sponsor's budget counts: members admitted in the last year who have not departed, petitions still
    reserved, and the sponsor's own invitations, live or lapsed less than INVITE_COUNTED_DAYS ago (so that
    nobody holds a login by inviting it again and again)."""
    return (sum(1 for m in st.members.values()
                if login in m.sponsors and m.status != "departed" and not expired(m.since[1], now, SPONSOR_YEAR_DAYS))
            + sum(1 for cand, q in st.petitions.items() if login in q["vouches"] and st.reserved(cand, now))
            + sum(1 for i in st.invitations.values()
                  if i["by"] == login and not st.expired(i["time"], now, INVITE_EXPIRY_DAYS + INVITE_COUNTED_DAYS)))


def _sponsor_checks(st: State, actor: str, now: datetime, seq: int) -> None:
    """What an invitation and a vouch both need of the sponsor: no ban, and room in the budget (at most
    SPONSOR_BUDGET_PER_YEAR sponsorships counted at once)."""
    ban = st.members[actor].sponsor_ban_until
    _need(ban is None or now >= ban, seq, "sponsorship suspended (a sponsored member was expelled for fraud)")
    _need(sponsorships(st, actor, now) < canon.SPONSOR_BUDGET_PER_YEAR, seq, "sponsorship budget exhausted")


def _vouch(st, e, now, seq, actor, body):
    cand = body["candidate"]
    _need(st.live(cand, now), seq, "no such petition (or it lapsed)")
    _need(st.open_ballot_on("admission", fold(cand)) is None, seq,
          "the admission ballot on this petition is already open (its sponsors are frozen)")
    p = st.petitions[cand]
    _need(st.stands_in(actor, now), seq,
          "only Master Builders may sponsor (and, while a succession is in force, the members of the highest degree "
          "present)")
    _need(actor not in p["vouches"], seq, "already a sponsor of this petition (the inviter sponsors by inviting)")
    _sponsor_checks(st, actor, now, seq)
    p["vouches"].append(actor)


# -- opening a ballot: each kind checks its subject and returns what the ballot freezes -----------------

def _open_admission(st, subj, now, seq, actor, verifier):
    cand = subj["candidate"]
    _need(st.live(cand, now), seq, "no live petition")
    p = st.petitions[cand]
    sponsors = [v for v in p["vouches"] if may_sponsor(st, v, now)]     # validated again, today
    _need(len(sponsors) >= sponsors_required(st, now, p), seq, "candidate lacks sponsors")
    _need(actor in sponsors, seq, "only a sponsor may open the candidate's admission ballot")
    _need(_admissible(st, cand, p["key"], p["github_id"], now), seq,
          f"{cand!r} collides with another name, key or GitHub account, or is a member again (one name, one key, "
          "one account, one role; logins are case-insensitive)")
    return {"key": p["key"], "vouches": sponsors, "github_id": p["github_id"]}, None


def _admissible(st: State, cand: str, key: str, github_id: int, now: datetime) -> bool:
    """The candidate's name, key and GitHub account are held by nobody else, and an earlier record of the
    login has left and waited (`may_return`)."""
    old = st.members.get(cand)
    own = (("member", cand), ("petition", cand))
    return (may_return(old, now)
            and all(h in own for h in st.name_holders(cand, now))
            and all(h in own for h in st.key_holders(key, now))
            and all(h in own for h in st.id_holders(github_id, now)))


def _open_advancement(st, subj, now, seq, actor, verifier):
    m = st.members.get(subj["member"])
    _need(m is not None and m.is_active(now), seq, "no such member")
    _need(subj["degree"] == m.degree + 1 <= 32, seq, "advancement is one degree at a time, up to 32")
    _need(wait_ok(st, m, subj["degree"], now), seq, "waiting period not complete")
    ex = st.exams.get((m.login, subj["degree"]))
    _need(ex is not None and ex.passed() and not ex.consumed, seq,
          "examination not passed (each passed exam supports one advancement ballot)")
    _need(actor == m.login or actor in ex.examiners, seq,
          "only the candidate, or an examiner of the passed examination, may open the advancement ballot")
    return {"admitted": membership(m)}, ex


def _master(st: State, actor: str, seq: int, what: str) -> None:
    _need(st.members[actor].degree >= canon.SPONSOR_MIN_DEGREE, seq, f"only Master Builders may open {what}")


def _open_amendment(st, subj, now, seq, actor, verifier):
    _master(st, actor, seq, "an amendment ballot")
    path = subj["path"]
    _need(PATH_RE.fullmatch(path) is not None, seq,
          "amendment path: letters, digits, _ . - and / only (or @protocol)")
    low = fold(path)
    _need(not low.startswith(ETERNAL_PREFIX), seq, "eternal landmarks cannot be amended")
    _need(low != LEDGER_PREFIX and not low.startswith(LEDGER_PREFIX + "/"), seq,
          "the ledger cannot be pinned: no amendment governs a path under ledger/")
    twin = _case_twin(st, path)
    _need(twin is None, seq, f"amendment path {path!r} collides with the pinned path {twin!r} (they differ only by case)")
    new = subj["new_sha256"]
    _need(HEX64.fullmatch(new) is not None, seq, "amendment must pin the new text's sha256 (64 lowercase hex)")
    if new == canon.ZERO_HASH:                # the removal of a pin that a passed amendment added
        _need(path in st.pins, seq, f"{path} is not pinned: there is no pin to remove (a new_sha256 of 64 zeros removes one)")
        _need(path not in GENESIS_PINS, seq, f"{path} is pinned by the genesis, and a genesis pin is never removed")
        return {"base": st.pins[path]}, None
    if path == DEGREES_PATH:
        # The degree canon is read during replay: its new text must be archived before anyone votes on it, so
        # that the ballot can always be closed, and replay never depends on when a clone received the file.
        status = canon.canon_status(new)
        _need(status != "missing", seq,
              f"the new degree canon {new[:12]}… is not archived: add canon/history/{new}.toml before opening this "
              "ballot (in an earlier pull request, or in the pull request that opens it)")
        _need(status == "ok", seq,
              f"the new degree canon {new[:12]}… is malformed (33 degrees with exact fields): it can never be ratified")
    return {"base": st.pins.get(path, "")}, None    # the pin it replaces; if that changes first, this one fails


def _case_twin(st: State, path: str) -> str | None:
    """A pinned path that equals `path` up to case without being `path` (pins are matched exactly)."""
    return next((p for p in st.pins if p != path and fold(p) == fold(path)), None)


def _open_sanction(st, subj, now, seq, actor, verifier):
    measure = subj["measure"]
    _need(measure in MEASURES, seq, f"measure must be one of {sorted(MEASURES)}")
    m = st.members.get(subj["member"])
    _need(m is not None and m.status != "departed" and (m.status != "voided" or measure == "expel_for_fraud"), seq,
          "no such member")
    _need(m.status != "voided" or not waited(m.status_since, now, VOIDED_FRAUD_DAYS), seq,
          f"the admission of {m.login} was undone {VOIDED_FRAUD_DAYS} days ago or more (a voided record is expelled "
          f"for fraud only by a ballot opened before {VOIDED_FRAUD_DAYS} days have passed since the undo; from then on "
          "the login may be invited again)")
    standing = m.standing(now)
    _need(standing in SANCTION_ON[measure], seq,
          f"{measure} applies only to a member who is {' or '.join(sorted(SANCTION_ON[measure]))}; "
          f"{m.login} is {standing}")
    _need(actor != m.login, seq, "a member cannot open a sanction ballot on themselves")
    # The opener is of the degree the electorate is drawn from: an Arbiter where three exist, else a Master.
    arbiters = len(st.active(now, 7, {m.login})) >= 3
    _need(st.members[actor].degree >= (7 if arbiters else canon.SPONSOR_MIN_DEGREE), seq,
          "only an Arbiter (7th degree or higher) may open a sanction ballot while three or more active Arbiters "
          "exist" if arbiters else
          "only Master Builders may open a sanction ballot (an Arbiter where three or more active Arbiters exist)")
    if m.degree >= canon.SPONSOR_MIN_DEGREE and measure != "reinstate":
        return {"admitted": membership(m), "master": True}, None   # never decided by a single elector
    return {"admitted": membership(m)}, None


def _open_witness(st, subj, now, seq, actor, verifier):
    _master(st, actor, seq, "a witness ballot")
    action, name = subj["action"], subj["name"]
    _need(action in ("add", "remove") and valid_login(name), seq, "witness ballot needs action and a valid name")
    _need(("key" in subj) == ("proof" in subj) == (action == "add"), seq,
          "a witness subject has action, name, key and proof to add a witness, and action and name only to remove one")
    if action == "remove":
        _need(name in st.witnesses, seq, "no such witness")
        return {}, None
    _need(not st.name_holders(name, now), seq,
          "a new witness name cannot equal a member login, a witness, a custodian, an invited login, a pending "
          "petition, the name of an open witness ballot, or the name of a pending claim of the Custodian office "
          "(case-insensitive)")
    _need(ed25519(subj["key"]), seq, KEY_RULE)
    owner = st.key_owner(subj["key"], now)
    _need(owner is None, seq, f"this key is already used by {owner} (one key per login)")
    _need(verifier(witness_message(name, subj["key"]), subj["proof"], name, subj["key"]) is True, seq,
          "bad witness proof: the proposed key must sign the witness message (name, key)")
    return {}, None


def _open_custodian(st, subj, now, seq, actor, verifier):
    """The one decision of the Master Builders about a custodian: to remove its key. Nothing appoints one."""
    name = subj["remove"]
    c = st.custodians.get(name)
    _need(c is not None, seq, "no such custodian")
    status = st.custodian_status(c, now)
    _need(status == "live", seq, f"the custodian key of {name} is already {status}")
    _need(st.members[actor].degree >= canon.SPONSOR_MIN_DEGREE, seq,
          "only Master Builders may open the ballot that removes a custodian")
    _need(not same_login(actor, c.member), seq,
          f"{actor} is the member of the custodian {name} and cannot open the ballot that removes it")
    return {}, None


OPENERS = {"admission": _open_admission, "advancement": _open_advancement, "amendment": _open_amendment,
           "sanction": _open_sanction, "witness": _open_witness, "custodian": _open_custodian}


def _reopen_wait(st: State, kind: str, key: str, actor: str, now: datetime, seq: int) -> None:
    """The opener of a ballot that failed or lapsed waits REOPEN_AFTER_DAYS before opening another on the same
    subject (another member may open one at once): nobody holds a subject by opening on it again and again."""
    if kind not in REOPEN_KINDS:
        return
    for b in st.ballots.values():
        if b.opened_by == actor and b.kind == kind and b.result in ("failed", "lapsed") \
                and subject_key(kind, b.subject) == key and not waited(b.closed, now, REOPEN_AFTER_DAYS):
            raise Invalid(seq, f"{actor} opened ballot {b.id} on this subject, and it {b.result} less than "
                               f"{REOPEN_AFTER_DAYS} days ago (the same member opens a ballot on the same subject "
                               f"again only {REOPEN_AFTER_DAYS} days after that close; another member may open one)")


def _ballot_open(st, e, now, seq, actor, body, verifier=verify):
    bid, kind, subj = body["id"], body["kind"], body["subject"]
    _need(kind in KINDS, seq, f"kind must be one of {sorted(KINDS)}")
    _need(BALLOT_ID_RE.fullmatch(bid) is not None, seq,
          "ballot id: 1..64 of a-z 0-9 . _ - starting with a letter or digit")
    _need(bid not in st.ballots and bid not in st.retired, seq, f"ballot id {bid!r} is already used")
    fields = SUBJECT_FIELDS[kind]
    _need(set(subj) <= set(fields) and set(subj) >= set(fields) - ({"key", "proof"} if kind == "witness" else set()),
          seq, f"{kind} subject has exactly the keys {sorted(fields)}")
    for k, v in subj.items():
        _need(type(v) is fields[k], seq, f"{kind} subject: {k!r} must be {_JSON_NAME[fields[k]]}")
    cd, rd = body.get("commit_days", COMMIT_DAYS), body.get("reveal_days", REVEAL_DAYS)
    _need(kind in OPENER_WINDOWS or ("commit_days" not in body and "reveal_days" not in body), seq,
          f"{'an' if kind[0] in 'a' else 'a'} {kind} ballot has fixed windows ({COMMIT_DAYS} days to commit, "
          f"{REVEAL_DAYS} to reveal): it takes "
          "no commit_days and no reveal_days (only an amendment ballot does)")
    _need(2 <= cd <= 30 and 1 <= rd <= 14, seq, "voting windows: 2..30 days to commit, 1..14 to reveal")
    rerun = _rerun_of(st, body, kind, subj, cd, now, seq) if "rerun" in body else None
    frozen, exam = OPENERS[kind](st, subj, now, seq, actor, verifier)
    key = subject_key(kind, subj)
    _need(st.open_ballot_on(kind, key) is None, seq, "a ballot on this subject is already open")
    if rerun is None:
        _reopen_wait(st, kind, key, actor, now, seq)
    _need(kind == "custodian" or st.open_by(actor, kind) < OPEN_BALLOTS_PER_OPENER, seq,
          f"{actor} has {OPEN_BALLOTS_PER_OPENER} ballots open (a member has at most {OPEN_BALLOTS_PER_OPENER} open "
          "ballots of their own at once, and apart from them at most "
          f"{OPEN_BALLOTS_PER_OPENER} amendment ballots; the ballot that removes a custodian is not counted)")
    electors, base = electorate(st, kind, subj, now)
    _need(len(electors) > 0, seq, "no electors")
    if rerun is not None:                    # whoever did not vote in the lapsed ballot is not waited for again
        silent = rerun.electors - set(rerun.reveals)
        present = set(st.active(now)) & electors
        base = max(1, len(present - silent))
    _need(base >= len(electors) or cd >= COMMIT_DAYS, seq,
          f"{len(electors) - base} of the {len(electors)} electors are not waited for (dormant, silent, or silent in "
          f"the ballot this one re-runs): the ballot gives at least {COMMIT_DAYS} days to commit, so that they can "
          "wake up and vote")
    _need(not frozen.get("master") or len(electors) >= SANCTION_MASTER_VOTES, seq,
          f"a sanction on a Master Builder is never decided by a single elector: this electorate has {len(electors)} "
          f"(at least {SANCTION_MASTER_VOTES} are needed)")
    # Every check has passed: only now does anything change.
    if exam is not None:
        exam.consumed = True
    if kind == "witness" and subj["action"] == "add":
        st.known_keys.add(point(subj["key"]))
    st.ballots[bid] = Ballot(bid, kind, dict(subj), electors, now + cd * DAY, now + cd * DAY + REVEAL_GAP + rd * DAY,
                             actor, frozen=frozen, opened=now, base=None if base == len(electors) else base,
                             rerun=rerun.id if rerun is not None else "")


def _rerun_of(st: State, body: dict, kind: str, subj: dict, cd: int, now: datetime, seq: int) -> Ballot:
    """the lapsed ballot this one re-runs, once. The same kind and the same subject, opened within RERUN_DAYS
    of its close, with a commit window of at least COMMIT_DAYS; a re-run is never re-run itself, and a ballot that
    gave less than COMMIT_DAYS to commit is never re-run (`full_call`)."""
    rid = body["rerun"]
    prev = st.ballots.get(rid)
    _need(rid not in st.retired, seq, _retired_text(rid))
    _need(prev is not None and prev.result == "lapsed", seq,
          f"ballot {rid} did not lapse: only a ballot that lapsed for want of quorum is re-run")
    _need(prev.kind == kind and prev.subject == subj, seq,
          f"a re-run has the kind and the subject of the ballot it re-runs ({rid})")
    _need(not prev.rerun, seq, f"ballot {rid} re-ran ballot {prev.rerun}: a ballot is re-run once, and a re-run never")
    other = next((b.id for b in st.ballots.values() if b.rerun == rid), None)
    _need(other is None, seq, f"ballot {rid} was re-run already, by ballot {other} (a ballot is re-run once)")
    _need(not expired(prev.closed, now, RERUN_DAYS), seq,
          f"ballot {rid} lapsed more than {RERUN_DAYS} days ago (a re-run is opened within {RERUN_DAYS} days of the "
          "close)")
    _need(full_call(prev), seq,
          f"ballot {rid} gave less than {COMMIT_DAYS} days to commit and is never re-run (open a new ballot, which "
          "waits for every elector)")
    _need(cd >= COMMIT_DAYS, seq, f"a re-run gives at least {COMMIT_DAYS} days to commit")
    return prev


def _retired_text(bid: str) -> str:
    return (f"ballot {bid} ended more than {BALLOT_RETIRE_DAYS} days ago and left the state (no rule reads a "
            "ballot after that)")


def _not_stayed(st: State, b: Ballot, now: datetime, seq: int) -> None:
    """A ballot that is stayed, or under a pending `void_ballot`, takes no commit, no reveal and no close:
    its clock stands still, so nobody learns a vote before the pause is over."""
    stay = st.stayed(b.id, now)
    if stay is not None:
        raise Invalid(seq, f"ballot {b.id} is stayed {_until(st, stay)}")
    void = st.void_pending(b.id, now)
    if void is not None:
        raise Invalid(seq, f"ballot {b.id} is paused while the correction that would void it is pending "
                           f"(correction {void.seq}, until {iso(st.apply_end(void))} at the latest)")


def commitment(ballot_id: str, login: str, vote: str, salt: str) -> str:
    return sha256(f"{ballot_id}|{login}|{vote}|{salt}")


def _ballot_commit(st, e, now, seq, actor, body):
    b = st.ballots.get(body["id"])
    _need(b is not None and b.result is None, seq, "no open ballot")
    _not_stayed(st, b, now, seq)
    _need(actor in b.electors, seq, "not an elector")
    _need(st.ballot_time(b, now) <= b.commit_until, seq, "commit window closed")
    _need(actor not in b.commits, seq, "already committed")
    _need(HEX64.fullmatch(body["commitment"]) is not None, seq, "commitment is 64 lowercase hex")
    b.commits[actor] = body["commitment"]
    b.touch()


def _ballot_reveal(st, e, now, seq, actor, body):
    b = st.ballots.get(body["id"])
    _need(b is not None and b.result is None, seq, "no open ballot")
    _not_stayed(st, b, now, seq)
    opens = b.commit_until + REVEAL_GAP
    _need(opens <= st.ballot_time(b, now) <= b.reveal_until, seq,
          f"not in the reveal window ({iso(st.ballot_due(b, opens))} to {iso(st.ballot_due(b, b.reveal_until))}, "
          "both included)")
    _need(body["vote"] in (YES, NO) and SALT_RE.fullmatch(body["salt"]) is not None, seq,
          "vote must be yes or no, salt 32..64 lowercase hex characters")
    _need(actor not in b.reveals, seq, "already revealed")
    _need(b.commits.get(actor) == commitment(b.id, actor, body["vote"], body["salt"]), seq,
          "reveal does not match commitment")
    b.reveals[actor] = body["vote"]
    b.touch()
    _heard(st, actor, now)


# -- closing a ballot: each kind returns True when the result was applied. Nothing here refuses the entry:
# -- a ballot that passed on the votes but can no longer be applied lawfully closes as failed.

def _close_admission(st, b, now, seq, ok):
    cand, frozen = b.subject["candidate"], b.frozen     # the key and sponsors the electors voted on
    old = st.members.get(cand)
    admit = ok and _admissible(st, cand, frozen["key"], frozen["github_id"], now)
    st.petitions.pop(cand, None)             # decided either way: a refused candidate must petition again
    if not admit:
        return False
    for k in [k for k in st.exams if k[0] == cand]:
        del st.exams[k]                      # the examinations of an earlier membership no longer count
    # A returning member starts again at 1°; what follows the person, not the membership, is kept: a founder
    # who returns is still a founder (and so never one of the Masters the Sunset counts), and a suspension
    # still running is still to be served. The person is the GitHub account: a login that comes back under
    # another account is another person, and inherits nothing.
    kept = old if old is not None and old.github_id == frozen["github_id"] else None
    serving = kept is not None and kept.suspended_until is not None and now < kept.suspended_until
    st.members[cand] = Member(cand, frozen["key"], 1, {1: now}, sponsors=tuple(frozen["vouches"]), activity=[now],
                              status="suspended" if serving else "active",
                              suspended_until=kept.suspended_until if serving else None,
                              founder=kept.founder if kept else False,
                              past_seats=kept.past_seats if kept else 0,
                              sponsor_ban_until=kept.sponsor_ban_until if kept else None,
                              fraud_history=kept.fraud_history if kept else (), github_id=frozen["github_id"])
    return True


def _close_advancement(st, b, now, seq, ok):
    s = b.subject
    m = st.members.get(s["member"])
    same = m is not None and membership(m) == b.frozen.get("admitted")
    ex = st.exams.get((s["member"], s["degree"])) if same else None
    if not ok:                               # lost on the votes: the member may try again after EXAM_RETRY_DAYS
        if ex is not None:
            ex.ballot_failed = True
        return False
    if not (same and m.is_active(now) and s["degree"] == m.degree + 1):
        if ex is not None:
            ex.lapsed = True                 # won on the votes, but the member is not there to advance: no penalty
        return False
    m.degree = s["degree"]
    m.since[m.degree] = now
    m.touch()
    return True


def _close_amendment(st, b, now, seq, ok):
    path, new = b.subject["path"], b.subject["new_sha256"]
    if not ok:
        return False
    if _case_twin(st, path) is not None:
        return False                         # M4 at the close: another ballot pinned the same path in another case
    if "base" in b.frozen and st.pins.get(path, "") != b.frozen["base"]:
        return False                         # the pin it would replace changed since it opened (another text won)
    if path == DEGREES_PATH and canon.canon_status(new) != "ok":
        return False                         # archived and well formed when the ballot opened (M6): a net, never a refusal
    _absorb(st, "amendments", _record_leaf({"ballot": b.id, "path": path, "new_sha256": new, "time": iso(now)}))
    if path == DEGREES_PATH:
        st.degree_tables.append(new)
    if path == PROTOCOL_PIN:
        st.epoch += 1                        # ratified here, merged later: a new rule branches on a fixed future time or seq
    if new == canon.ZERO_HASH:               # the path is governed no more
        del st.pins[path]
        st.prior_pins.pop(path, None)
        st.prior_until.pop(path, None)
        return True
    if path in st.pins:
        st.prior_pins[path] = st.pins[path]
        st.prior_until[path] = now + PRIOR_PIN_DAYS * DAY
    st.pins[path] = new
    return True


def _close_sanction(st, b, now, seq, ok):
    measure = b.subject["measure"]
    m = st.members.get(b.subject["member"])
    if not (ok and m is not None and membership(m) == b.frozen.get("admitted")
            and m.standing(now) in SANCTION_ON[measure]):
        return False                         # also: a member who left is out of reach of sanctions
    if measure == "admonish":
        return True
    if measure == "suspend":
        m.status, m.suspended_until = "suspended", now + SUSPENSION_DAYS * DAY
    elif measure == "reinstate":
        m.status, m.suspended_until = "active", None
    else:                                    # expel / expel_for_fraud
        m.status, m.seat_until, m.suspended_until = "expelled", None, None
        if measure == "expel_for_fraud":
            m.fraud_history = (*m.fraud_history, now)
            if not expired(m.since[1], now, FRAUD_WINDOW_DAYS):
                for sp in m.sponsors:        # Constitution Art. IV.4
                    if sp in st.members:
                        st.members[sp].sponsor_ban_until = now + SPONSOR_BAN_DAYS * DAY
    m.status_since = now
    return True


def _close_witness(st, b, now, seq, ok):
    s = b.subject
    if not ok:
        return False
    if s["action"] == "remove":
        return st.witnesses.pop(s["name"], None) is not None
    own = ("ballot", s["name"])              # this ballot itself reserved the name and the key
    if any(h != own for h in st.name_holders(s["name"], now) + st.key_holders(s["key"], now)):
        return False
    st.witnesses[s["name"]] = s["key"]
    return True


def _close_custodian(st, b, now, seq, ok):
    """A passed removal takes the custodian key at once, exactly as its revoke key would."""
    c = st.custodians.get(b.subject["remove"])
    if not (ok and c is not None and st.custodian_status(c, now) == "live"):
        return False                         # a key that already lapsed or was removed has nothing left to lose
    c.revoked, c.removed = now, b.id
    return True


CLOSERS = {"admission": _close_admission, "advancement": _close_advancement, "amendment": _close_amendment,
           "sanction": _close_sanction, "witness": _close_witness, "custodian": _close_custodian}


def full_call(b: Ballot) -> bool:
    """The ballot gave at least COMMIT_DAYS to commit. Only such a ballot calls its electors (a shorter one
    records no missed call) and only such a ballot is re-run: a short ballot that lapses is opened again as a new
    ballot, with its whole quorum."""
    return b.opened is None or b.commit_until - b.opened >= COMMIT_DAYS * DAY


def closable(st: State, b: Ballot, now: datetime) -> bool:
    """The ballot's reveal window has ended, or every elector has revealed: nothing more can change its votes."""
    return st.ballot_time(b, now) > b.reveal_until or len(b.reveals) == len(b.electors)


def _release_exam(st: State, b: Ballot) -> None:
    """An advancement ballot ended without deciding (it lapsed, or a correction voided it): the exam it was
    opened on is as it was before, passed and free to support another ballot."""
    if b.kind == "advancement":
        m = st.members.get(b.subject["member"])
        ex = st.exams.get((b.subject["member"], b.subject["degree"]))
        if m is not None and membership(m) == b.frozen.get("admitted") and ex is not None:
            ex.consumed = False


def _facts(st: State, b: Ballot) -> dict:
    """The stored facts a passed ballot of this kind sets, as they stand: what `undo_ballot` compares. Empty
    for a ballot that no correction undoes."""
    s = b.subject
    if b.kind == "admission":
        m = st.members.get(s["candidate"])
        return {"member.admitted": membership(m) if m else "", "member.status": m.status if m else "",
                "member.degree": m.degree if m else 0}
    if b.kind == "advancement":
        m = st.members.get(s["member"])
        return {"member.degree": m.degree if m else 0,
                "member.since": iso(m.since[s["degree"]]) if m and s["degree"] in m.since else ""}
    return {}


def _ballot_close(st, e, now, seq, actor, body):
    b = st.ballots.get(body["id"])
    _need(b is not None and b.result is None, seq, "no open ballot")
    _not_stayed(st, b, now, seq)
    _need(closable(st, b, now), seq, "ballot still open")
    yes = sum(v == YES for v in b.reveals.values())      # every vote cast stands, whatever became of the elector since
    no = sum(v == NO for v in b.reveals.values())
    b.closed = now
    _ended(st, b, now)
    if full_call(b):                         # the close ends the call of every elector: answered by a revealed vote
        for x in b.electors:
            _call(st, x, now, x in b.reveals, now)
    if not quorate(yes + no, b.quorum_base()) or (b.frozen.get("master") and yes + no < SANCTION_MASTER_VOTES):
        b.result = "lapsed"                  # too few voted to decide anything: no effect, and nobody is penalized
        _release_exam(st, b)
        return
    ok = decide(b.kind, yes, no, b.quorum_base())
    before = _facts(st, b)
    b.result = "passed" if CLOSERS[b.kind](st, b, now, seq, ok) else "failed"
    if b.result == "passed" and before:      # what an undo would compare, and what it would put back
        after = _facts(st, b)
        b.undo = {k: [before[k], after[k]] for k in before}


def _exam_open(st, e, now, seq, actor, body):
    m = st.members.get(body["candidate"])
    target = body["degree"]
    _need(m is not None and m.is_active(now), seq, "no such candidate")
    _need(actor == m.login, seq, "only the candidate may open their own examination")
    _need(target == m.degree + 1 <= 32, seq, "exams are for the next degree, up to 32")
    _need(wait_ok(st, m, target, now), seq, "waiting period not complete")
    _need(URL_RE.fullmatch(body["work_ref"]) is not None, seq,
          "work_ref must be an http(s) URL without spaces or quotes")
    prev = st.exams.get((m.login, target))
    if prev is not None:
        _need(prev.ended(now, st) or (prev.failed(now, st) and st.waited(prev.opened, now, EXAM_RETRY_DAYS)), seq,
              f"an exam for this degree exists; retry only after a failure and {EXAM_RETRY_DAYS} days (an exam that "
              "lapsed or timed out is opened again at once)")
    # The lot will use a drand round ~8 hours in the future: nobody can know it now.
    rnd = drand_round(now) + BEACON_DELAY_ROUNDS
    _need(rnd > 0 and body["beacon_round"] == rnd, seq,
          f"beacon_round must be {rnd} (now + {BEACON_DELAY_ROUNDS} rounds), a positive integer")
    k = st.degree(target).examiners
    silent = prev.silent(now, st) if prev is not None else ()
    carried = prev.skipped if prev is not None and prev.ended(now, st) else ()
    skip = frozenset(silent) | frozenset(carried)     # every silent examiner of the exams before, while others remain
    wide = prev is not None and prev.timed_out(now, st)    # timed out, its lot drawn or not: the next seats everyone
    pool = examiner_pool(st, m, target, now, skip, wide)  # frozen now, before the beacon exists
    if len(pool) < k:                        # the lowered lot (every rung together) lowers the number, in any phase
        _need(len(pool) > 0, seq, f"{k} examiners required, only {len(pool)} available")
        k = len(pool)
    if wide:                                 # never fewer than k: every member any rung holds is called
        k = len(pool)
    _need(k >= 1, seq, "an examination needs at least one examiner")
    if prev is not None and prev.timed_out(now, st) and prev.examiners:
        end = _timed_out_at(st, prev)        # the calls of the exam that timed out end with it
        for x in prev.examiners:
            _call(st, x, end, x in prev.reports, now)
    # Only a member the skip left out is carried. When nobody else was left, the lot calls the skipped again
    # (`examiner_pool` falls back), and one of them carried without being called would never fall silent.
    waived = not skip.isdisjoint(pool)
    st.exams[(m.login, target)] = Exam(m.login, target, None, rnd, now, pool=tuple(pool), k=k,
                                       work_ref=body["work_ref"],
                                       skipped=() if waived else tuple(sorted(x for x in skip if x not in pool)))


def _exam_draw(st, e, now, seq, actor, body):
    ex = st.exams.get((body["candidate"], body["degree"]))
    _need(ex is not None and ex.examiners is None and not ex.lapsed, seq, "no exam awaiting its draw")
    _need(not ex.expired(now, st), seq, "the exam has expired")
    _need(now >= drand_time(ex.beacon_round), seq, "the beacon round has not happened yet")
    _need(not ex.draw_lapsed(now, st), seq,
          f"the lot of this exam was not drawn within {LOT_DRAW_DAYS} days of its beacon round "
          f"({iso(drand_time(ex.beacon_round))}): the exam lapsed with no penalty, and a new one may be opened")
    _need(HEX64.fullmatch(body["beacon"]) is not None, seq,
          "beacon is the round's 32-byte randomness in lowercase hex")
    ranking = tuple(draw(list(ex.pool), len(ex.pool), body["beacon"],
                         f"exam:{ex.candidate}:{ex.degree}:{ex.beacon_round}"))
    ex.ranking, ex.examiners = ranking, ranking[:ex.k]
    _absorb(st, "beacons", _record_leaf({"round": ex.beacon_round, "beacon": body["beacon"]}))
    for x in ranking[:ex.k]:                 # a drawn examiner whose key is frozen counts as recused, at once
        if not ex.lapsed and st.key_frozen(x, now):
            _stand_aside(st, ex, x, now)


def _exam_report(st, e, now, seq, actor, body):
    ex = st.exams.get((body["candidate"], body["degree"]))
    _need(ex is not None, seq, "no such exam")
    _need(not ex.lapsed, seq, "the exam has lapsed")
    _need(ex.examiners is not None and actor in ex.examiners and actor not in ex.reports, seq,
          "not a drawn examiner, or already reported")
    _need(body["verdict"] in ("pass", "fail"), seq, "verdict is pass or fail")
    _need("reason" not in body or URL_RE.fullmatch(body["reason"]) is not None, seq,
          "reason must be the http(s) URL of the published, reasoned verdict")
    _need(not ex.expired(now, st), seq, "the exam has expired")
    decided = ex.passed() or ex._fails()
    ex.reports[actor] = body["verdict"]
    ex.touch()
    _heard(st, actor, now)
    if not decided and (ex.passed() or ex._fails()):
        for x in ex.examiners:               # the verdict ends the call of every examiner
            _call(st, x, now, x in ex.reports, now)


def _exam_recuse(st, e, now, seq, actor, body):
    """Constitution Art. V.5: a conflicted examiner steps aside; the next in the lot's order replaces them.

    When nobody is left to replace them the exam lapses: it ends without a verdict and without penalty,
    and the candidate may open a new one at once.
    """
    ex = st.exams.get((body["candidate"], body["degree"]))
    _need(ex is not None and ex.examiners is not None and not ex.lapsed, seq, "no drawn exam")
    _need(actor in ex.examiners and actor not in ex.reports, seq, "only a drawn examiner who has not reported may recuse")
    _need(not ex.expired(now, st), seq, "the exam has expired")
    _need(not ex.consumed and not ex.passed() and not ex.failed(now, st), seq, "the exam is already decided")
    _stand_aside(st, ex, actor, now)


def _stand_aside(st: State, ex: Exam, who: str, now: datetime) -> None:
    """The examiner `who` leaves the exam: the next in the lot's order who can serve today takes the seat
    (active, not dormant, key not frozen), and when there is nobody the exam lapses."""
    recused = (*ex.recused, who)
    nxt = next((x for x in ex.ranking if x not in ex.examiners and x not in recused and x in st.members
                and st.members[x].is_active(now) and not st.members[x].dormant(now)
                and not st.key_frozen(x, now)), None)
    ex.recused = recused
    ex.examiners = tuple(x for x in ex.examiners if x != who) + ((nxt,) if nxt is not None else ())
    ex.lapsed = nxt is None
    if ex.lapsed:
        for x in ex.examiners:               # the exam ends here: so does the call of every examiner left
            _call(st, x, now, x in ex.reports, now)


def _timed_out_at(st: State, ex: Exam) -> datetime:
    """The first second at which an exam that timed out had timed out: its lot lapsed, or its time ran out."""
    if ex.examiners is None:
        return st.due(drand_time(ex.beacon_round), LOT_DRAW_DAYS * DAY) + SECOND
    return st.due(ex.opened, EXAM_EXPIRY_DAYS * DAY) + SECOND


def _serves(st: State, m: Member | None, now: datetime) -> bool:
    """Whose calls are recorded: a Master Builder, and while a succession is in force any member (whoever
    is called then serves as a successor, and a silent one is left out of the successors)."""
    return m is not None and (m.degree >= canon.SPONSOR_MIN_DEGREE or st.succession_status(now) == "in_force")


def _call(st: State, login: str, end: datetime, answered: bool, now: datetime) -> None:
    """A call of `login` (an examination or a ballot) ended at `end`: recorded for whoever serves (`_serves`)."""
    m = st.members.get(login)
    if _serves(st, m, now):
        m.called(end, answered, now)


def _heard(st: State, login: str, now: datetime) -> None:
    """A revealed vote or a report of `login`: a member who answers is not silent."""
    m = st.members.get(login)
    if _serves(st, m, now):
        m.heard = now


def _recuse_frozen(st: State, login: str, now: datetime) -> None:
    """A member whose key was just frozen, or whose admission was just undone, cannot report: in every exam
    still undecided where they hold a seat and have not reported, they stand aside exactly as by an
    `exam_recuse` of their own."""
    for ex in st.exams.values():
        if (ex.examiners is not None and not ex.lapsed and login in ex.examiners and login not in ex.reports
                and not ex.expired(now, st) and not ex.consumed and not ex.passed() and not ex.failed(now, st)):
            _stand_aside(st, ex, login, now)


def _council_pool(st: State, now: datetime) -> list[str]:
    need = st.degree(33).wait_days
    return [l for l in st.active(now, 32, set(st.seats(now)))
            if st.members[l].degree == 32 and waited(st.members[l].since[32], now, need)
            and st.members[l].past_seats == 0]


def council_lapsed(st: State, now: datetime) -> bool:
    """The pending council call was not drawn within LOT_DRAW_DAYS of its beacon round: it lapsed, and a
    new call may be made."""
    return st.council_call is not None and st.expired(drand_time(st.council_call), now, LOT_DRAW_DAYS)


def _council_call(st, e, now, seq, actor, body):
    _need(st.council_call is None or council_lapsed(st, now), seq, "a council draw is already pending")
    _need(len(st.seats(now)) < canon.COUNCIL_SEATS, seq, "no vacancies")
    rnd = drand_round(now) + BEACON_DELAY_ROUNDS
    _need(rnd > 0 and body["beacon_round"] == rnd, seq, f"beacon_round must be {rnd}, a positive integer")
    pool = _council_pool(st, now)
    _need(len(pool) > 0, seq, "no eligible 32nd-degree members")
    st.council_call, st.council_pool = rnd, tuple(pool)


def _council_draw(st, e, now, seq, actor, body):
    rnd = st.council_call
    _need(rnd is not None and now >= drand_time(rnd), seq, "no council call whose beacon round has passed")
    _need(not council_lapsed(st, now), seq,
          f"the council call was not drawn within {LOT_DRAW_DAYS} days of its beacon round ({iso(drand_time(rnd))}): "
          "it lapsed, and a new call may be made")
    _need(HEX64.fullmatch(body["beacon"]) is not None, seq, "beacon is 32-byte lowercase hex")
    vacancies = canon.COUNCIL_SEATS - len(st.seats(now))       # never negative: a seat is held until it ends
    # The pool was frozen at the call. The whole pool is ranked by the lot; then, in that order, each name is
    # checked again today and skipped if it can no longer take a seat, until the vacancies are filled.
    seated: list[Member] = []
    for login in draw(list(st.council_pool), len(st.council_pool), body["beacon"], f"council:{rnd}"):
        m = st.members.get(login)
        if len(seated) < vacancies and m is not None and m.is_active(now) and not m.dormant(now) \
                and m.degree == 32 and m.past_seats == 0:
            seated.append(m)
    st.council_call, st.council_pool = None, ()
    _absorb(st, "beacons", _record_leaf({"round": rnd, "beacon": body["beacon"]}))
    for m in seated:
        m.degree, m.since[33] = 33, now
        m.touch()
        m.seat_until, m.past_seats = now + canon.COUNCIL_TERM_DAYS * DAY, m.past_seats + 1


def _work(st, e, now, seq, actor, body):
    _need(URL_RE.fullmatch(body["ref"]) is not None, seq,
          "work needs an http(s) URL (PR, commit or document) without spaces or quotes")
    _need("kind" not in body or WORK_KIND_RE.fullmatch(body["kind"]) is not None, seq,
          "work kind: 1..32 of a-z 0-9 _ - starting with a letter or digit")
    m = st.members[actor]
    _need(m.last_work is None or now - m.last_work >= WORK_INTERVAL, seq, "one work entry per member per 24 hours")
    m.last_work = now


def _depart(st, e, now, seq, actor, body):
    """Constitution Art. III.4 / Landmark VII: any member may leave at any time."""
    m = st.members[actor]
    # The ledger cannot tell the member from whoever else holds the key: the departure takes effect now, and is
    # reversed if a recovery asked in time for it completes: one asked within DEPART_RECOVER_DAYS of it, or one
    # that follows (`_rekey_recover`) a recovery asked in time for it. The latest recovery of this membership is
    # asked in time for it when it is alive now, or was not applied and was asked, stopped by the old key or
    # voided by the Masters at most RECOVER_INTERVAL_DAYS ago: it is marked now.
    rec = st.recoveries.get(actor)
    if rec is not None and rec.admitted == membership(m) and rec.applied is None and (
            st.recovery_alive(actor, now) is rec
            or not expired(max(t for t in (rec.time, rec.objected, rec.void) if t is not None), now,
                           RECOVER_INTERVAL_DAYS)):
        rec.departure = now
    m.left = _plain({"status": m.status, "status_since": m.status_since, "seat_until": m.seat_until})
    m.status, m.seat_until, m.status_since = "departed", None, now


def _rekey(st, e, now, seq, actor, body, verifier):
    """A member replaces their own key. The entry is signed by the key the ledger holds; the new key signs
    the proof, so nobody registers a key they do not hold."""
    m, new = st.members[actor], body["key"]
    _need(ed25519(new), seq, KEY_RULE)
    for role, other in st.key_holders(new, now):       # held by anyone at all: the first holder names the refusal
        _need((role, other) != ("member", actor), seq, "this is already your key")
        raise Invalid(seq, f"this key is already used by {other} (one key per login: members, witnesses and petitions)")
    _need(point(new) not in st.known_keys, seq,
          "this key was used in this ledger before (a key that was ever registered here is never registered again)")
    _need(m.last_rekey is None or waited(m.last_rekey, now, REKEY_INTERVAL_DAYS), seq,
          f"one rekey per member per {REKEY_INTERVAL_DAYS} days")
    _need(verifier(rekey_message(actor, m.key, new), body["proof"], actor, new) is True, seq,
          "bad proof: the new key must sign the rekey message (login, old key, new key)")
    m.key, m.last_rekey = new, now
    st.known_keys.add(point(new))


def nominal_cosigners(r: Recovery) -> int:
    """The co-signers a recovery asks for where enough Master Builders exist: RECOVER_FINAL_COSIGNERS for the
    recovery the old key cannot stop, RECOVER_COSIGNERS after a freeze, RECOVER_OPEN_COSIGNERS without one."""
    if r.final:
        return RECOVER_FINAL_COSIGNERS
    return RECOVER_COSIGNERS if r.freeze is not None else RECOVER_OPEN_COSIGNERS


def answering_masters(st: State, login: str, now: datetime) -> list[str]:
    """The active Master Builders other than `login` who answered (a vote revealed, a report: `Member.heard`) or
    reached the 3rd degree within the last ANSWER_DAYS: the co-signers a recovery waits for. A Master who signs
    a work a year and answers nothing keeps every other power, opposition included, but holds no recovery."""
    def answers(m: Member) -> bool:
        seen = max((t for t in (m.heard, m.since.get(canon.SPONSOR_MIN_DEGREE)) if t is not None), default=None)
        return seen is not None and not expired(seen, now, ANSWER_DAYS)
    return [x for x in st.masters(now) if x != login and answers(st.members[x])]


def _others(st: State, r: Recovery, now: datetime) -> int:
    return len(answering_masters(st, r.login, now))


def cosigners_needed(st: State, r: Recovery, now: datetime) -> int:
    """How many Master Builders must co-sign the recovery, as things stand at `now`: its nominal number, and
    never more than the active Master Builders other than the member who answered within ANSWER_DAYS
    (`answering_masters`; none, where the member is the only one).
    No requirement exceeds the people who exist, the final recovery included. Once the request has been open
    RECOVER_DROP_DAYS without all of them (`dropped`), only those already given, and never fewer than one where
    another Master Builder exists. A lowered number lengthens the notice (`State.recovery_notice_days`)."""
    others = _others(st, r, now)
    base = min(nominal_cosigners(r), others)
    if not dropped(st, r, now):
        return base
    return min(base, max(r.given_at_drop(), 1 if others else 0))


def dropped(st: State, r: Recovery, now: datetime) -> bool:
    """The request had been open RECOVER_DROP_DAYS without all the co-signatures it needed, and the drop to
    those given (never fewer than one where another Master Builder exists) lowers what it needs: an open
    recovery whose notice had not begun by then, or one after a freeze whose standing co-signers were too few
    then (counted as given, whoever they are now)."""
    if now < r.drop_time():
        return False
    others = _others(st, r, now)
    base = min(nominal_cosigners(r), others)
    if max(r.given_at_drop(), 1 if others else 0) >= base:
        return False                         # nothing to lower: the request keeps its number and its notice
    return r.freeze is not None or r.notice is None or r.notice > r.drop_time()


def lowered(st: State, r: Recovery, now: datetime) -> bool:
    """The recovery needs fewer co-signers at `now` than its nominal number: its notice is the longer one."""
    return cosigners_needed(st, r, now) < nominal_cosigners(r)


def standing_cosigners(st: State, cosigners, now: datetime) -> list[str]:
    """The co-signers who are active Master Builders at `now`."""
    return [x for x in cosigners if x in st.members and st.members[x].is_active(now)
            and st.members[x].degree >= canon.SPONSOR_MIN_DEGREE]


def only_sponsors(st: State, r: Recovery, cosigners, now: datetime) -> bool:
    """An open recovery whose standing co-signers are all sponsors of the member, though an active Master
    Builder who is not one exists: one of those must co-sign too. Not once the request has dropped (`dropped`):
    then the co-signatures given are enough, whoever gave them (the notice, the old key's objection and the
    Masters' opposition still stand)."""
    sponsors = set(st.members[r.login].sponsors)
    standing = standing_cosigners(st, cosigners, now)
    return (r.freeze is None and bool(standing) and set(standing) <= sponsors
            and any(x not in sponsors for x in answering_masters(st, r.login, now)) and not dropped(st, r, now))


def cosigned(st: State, r: Recovery, cosigners, now: datetime) -> bool:
    """The recovery has, in `cosigners`, the co-signatures it needs as things stand at `now`."""
    return (len(standing_cosigners(st, cosigners, now)) >= cosigners_needed(st, r, now)
            and not only_sponsors(st, r, cosigners, now))


def _freeze_room(st: State, login: str, now: datetime, seq: int) -> None:
    """FK4: the key of `login` may be frozen by a custodian only while fewer keys than the cap are frozen. A
    recovery is never held back by it: its notice starts whatever else is frozen, and it then counts in the cap."""
    active = len(st.active(now))
    cap = max(1, active // FREEZE_CAP_DIVISOR)
    _need(len(st.frozen_keys(now) - {login}) < cap, seq,
          f"too many keys are frozen at once: at most {cap} (a tenth of the {active} active members, never fewer than 1)")


def _rekey_recover(st, e, now, seq, actor, body, verifier):
    """A member whose key is lost or stolen asks for a new one. The entry is signed by the NEW key (the old
    one may be in other hands); the key the ledger holds changes only by `rekey_recover_apply`. After a
    freeze the notice starts here. Without a freeze (no custodian key is live, or no custodian answers: a
    recovery never needs a custodian) it is an open recovery, and its notice starts when the co-signatures
    it needs are there."""
    m, new = st.members[actor], body["key"]
    freeze = st.frozen(actor, now)          # a recovery never needs a custodian; without a freeze it is an open one
    last = st.recoveries.get(actor)
    departed = m.status == "departed" and bool(m.left) and m.status_since is not None
    # The recovery before this one was asked in time for this very departure, and ended (whatever ended it) not
    # long ago: this one follows it, and may still reverse the departure.
    follows = (departed and last is not None and last.admitted == membership(m) and last.departure == m.status_since
               and not expired(max(last.time, last.objected or last.time), now, DEPART_FOLLOW_DAYS))
    _need(m.status not in GONE or (departed and (not expired(m.status_since, now, DEPART_RECOVER_DAYS) or follows)),
          seq,
          f"{actor} departed more than {DEPART_RECOVER_DAYS} days ago (a recovery reverses a departure only when it "
          f"is asked before it or within {DEPART_RECOVER_DAYS} days of it, or follows one so asked within "
          f"{DEPART_FOLLOW_DAYS} days of that one's request, or of the old key's stop of it)")
    if last is not None:
        status = st.recovery_status(last, now)
        _need(status not in ("requested", "pending", "ready"), seq,
              f"a recovery of the key of {actor} is already pending (entry {last.seq})")
        _need(waited(last.time, now, RECOVER_INTERVAL_DAYS), seq,
              f"the last recovery of the key of {actor} was requested less than {RECOVER_INTERVAL_DAYS} days ago "
              f"(one request per member in {RECOVER_INTERVAL_DAYS} days)")
        _need(last.objected is None or waited(last.objected, now, RECOVER_INTERVAL_DAYS), seq,
              f"the old key of {actor} stopped a recovery less than {RECOVER_INTERVAL_DAYS} days ago (the next "
              f"request, {RECOVER_INTERVAL_DAYS} days after that, cannot be stopped by the old key and needs "
              f"{RECOVER_FINAL_COSIGNERS} co-signers, or as many other Master Builders as exist)")
    for role, other in st.key_holders(new, now):       # held by anyone at all: the first holder names the refusal
        _need((role, other) != ("member", actor), seq, "this is already your key")
        raise Invalid(seq, f"this key is already used by {other} (one key per login: members, witnesses and petitions)")
    _need(point(new) not in st.known_keys, seq,
          "this key was used in this ledger before (a key that was ever registered here is never registered again)")
    _need(verifier(rekey_message(actor, m.key, new), body["proof"], actor, new) is True, seq,
          "bad proof: the new key must sign the rekey message (login, old key, new key)")
    rec = Recovery(actor, new, seq, now, freeze.seq if freeze is not None else None, admitted=membership(m),
                   final=last is not None and last.objected is not None and last.admitted == membership(m),
                   departure=m.status_since if departed else None)
    if freeze is None and cosigned(st, rec, (), now):      # the only Master Builder: no co-signer exists, and the notice starts here
        rec.notice = now                                   # the cap on freezes (FK4) never holds back a recovery
    st.recoveries[actor] = rec
    st.known_keys.add(point(new))


def _alive_recovery(st: State, login, now: datetime, seq: int) -> Recovery:
    _need(valid_login(login), seq, "login must be a valid GitHub login")
    rec = st.recovery_alive(login, now)
    _need(rec is not None, seq, f"no recovery of the key of {login} is pending")
    return rec


def _rekey_cosign(st, e, now, seq, actor, body):
    """A Master Builder answers for a recovery: that the person asking is the member. The co-signature that
    completes an open recovery freezes the old key and starts its notice."""
    login = body["login"]
    rec = _alive_recovery(st, login, now, seq)
    _need(st.members[actor].degree >= canon.SPONSOR_MIN_DEGREE, seq, "only Master Builders may co-sign a key recovery")
    _need(actor != login, seq, "a member cannot co-sign the recovery of their own key")
    _need(actor not in rec.cosigners, seq, f"already co-signed the recovery of the key of {login}")
    _need(actor not in rec.opposed, seq, f"{actor} opposed the recovery of the key of {login} and cannot co-sign it")
    cosigners = (*rec.cosigners, actor)
    starts = st.recovery_start(rec, now) is None and cosigned(st, rec, cosigners, now)
    if rec.dropped is None and now >= rec.drop_time():
        rec.dropped = len(rec.cosigners)     # what had been given when the request had been open RECOVER_DROP_DAYS
    rec.cosigners = cosigners
    if starts:
        rec.notice = now


def _rekey_object(st, e, now, seq, actor, body):
    """The key the ledger holds for the member stops a recovery of it: the holder of the old key says no.
    Once: the recovery that follows one the old key stopped is not stopped by it again."""
    rec = st.recovery_alive(actor, now)
    _need(rec is not None, seq, f"no recovery of the key of {actor} is pending")
    _need(not rec.final, seq,
          f"the recovery of the key of {actor} follows one the old key stopped, and the old key cannot stop this one "
          f"(it needs {RECOVER_FINAL_COSIGNERS} co-signers, or as many other Master Builders as exist; Master Builders "
          "may object to the freeze it follows, or oppose a recovery asked without one)")
    rec.objected = now


def _rekey_oppose(st, e, now, seq, actor, body):
    """A Master Builder opposes an open recovery (one asked with no freeze in force). At max(1, ceil(E / 5))
    oppositions it is void. A recovery that follows a freeze is checked by objecting to the freeze."""
    login = body["login"]
    rec = _alive_recovery(st, login, now, seq)
    _need(rec.freeze is None, seq,
          f"the recovery of the key of {login} follows a freeze (correction {rec.freeze}): a Master Builder objects "
          "to that correction instead (correction_object)")
    _need(st.members[actor].degree >= canon.SPONSOR_MIN_DEGREE, seq, "only Master Builders may oppose a key recovery")
    _need(actor != login, seq, "a member stops the recovery of their own key with rekey_object, signed by the old key")
    _need(actor not in rec.cosigners, seq, f"{actor} co-signed the recovery of the key of {login} and cannot oppose it")
    _need(actor not in rec.opposed, seq, f"already opposed the recovery of the key of {login}")
    rec.opposed = (*rec.opposed, actor)
    others = [x for x in st.masters(now) if x != login]      # every other Master Builder, a co-signer or not: the
    if len(rec.opposed) >= objections_needed(len(others)):   # number does not move with the co-signatures
        rec.void = now


def _rekey_recover_apply(st, e, now, seq, actor, body):
    """The new key takes the member's place: after the notice, with its co-signers, and unopposed. A
    departure signed with the old key is reversed (the request was asked in time for it: `_rekey_recover`),
    and a Council seat it ended comes back only into a vacancy."""
    m, rec = st.members[actor], st.recoveries[actor]
    status = st.recovery_status(rec, now)
    _need(not rec.admitted or membership(m) == rec.admitted, seq,
          f"the recovery of the key of {actor} was asked for an earlier membership of the login, and ended with it")
    _need(status != "canceled", seq,
          f"the recovery of the key of {actor} ended when the freeze it followed (correction {rec.freeze}) was "
          "withdrawn or voided")
    _need(status != "expired", seq,
          f"the recovery of the key of {actor} expired at {iso(st.recovery_end(rec, now))} "
          f"({RECOVER_EXPIRY_DAYS} days after " + ("it was requested)" if st.recovery_start(rec, now) in (None, rec.time)
                                                    else "its notice began)"))
    needed = cosigners_needed(st, rec, now)
    standing = standing_cosigners(st, rec.cosigners, now)
    _need(status != "requested", seq,
          f"the recovery of the key of {actor} has {len(standing)} of the {needed} co-signatures of active Master "
          "Builders that start its notice" + (", and one of them must not be a sponsor of the member"
                                              if only_sponsors(st, rec, rec.cosigners, now) else ""))
    days = st.recovery_notice_days(rec, now)
    why = (f"; {days} because it was open {RECOVER_DROP_DAYS} days without all its co-signatures)"
           if dropped(st, rec, now) else
           f"; {days} because fewer Master Builders exist than the {nominal_cosigners(rec)} co-signers it asks for)"
           if days == RECOVER_LOWERED_NOTICE_DAYS else ")")
    _need(status == "ready" or now >= st.recovery_notice_end(rec, now), seq,
          f"the recovery of the key of {actor} is under notice until {iso(st.recovery_notice_end(rec, now))} "
          f"({days} days after its notice began" + why)
    _need(len(standing) >= needed, seq,
          f"the recovery of the key of {actor} has {len(standing)} of the {needed} co-signatures of "
          "active Master Builders it needs")
    _need(not only_sponsors(st, rec, rec.cosigners, now), seq,
          f"the co-signers of the recovery of the key of {actor} are all sponsors of {actor}: a Master Builder who "
          "is not one must co-sign too")
    freeze = st.corrections.get(rec.freeze) if rec.freeze is not None else None
    if freeze is not None and st.in_force(freeze, now):
        freeze.released = now                # the freeze has done its work: the new key signs from the next entry
    m.key, m.last_rekey = rec.key, now
    rec.applied = now
    if m.status == "departed" and m.left:    # the departure was signed with the key this recovery replaces
        m.status = m.left["status"]
        m.status_since = ts(m.left["status_since"]) if "status_since" in m.left else None
        # The seat comes back only into a vacancy: a draw may have filled it since the departure.
        m.seat_until = (ts(m.left["seat_until"]) if "seat_until" in m.left
                        and len(st.seats(now)) < canon.COUNCIL_SEATS else None)
        m.left = None


def checkpoint_due(st: State, name: str, now: datetime) -> bool:
    """Pure: the witness `name` may post a checkpoint at `now` (Z6, Z7): at least one entry that is not a
    checkpoint exists since its last one, and that one is at least CHECKPOINT_INTERVAL old."""
    mark = st.witness_marks.get(name)
    return mark is None or (st.acts > mark["acts"] and now - mark["time"] >= CHECKPOINT_INTERVAL)


def _witness(st, e, now, seq, actor, body):
    """A checkpoint covers every entry before it: it names the entry just before itself, the hash of that
    entry and the digest of the state as that entry left it, which is the state this entry is applied to."""
    upto = body["upto_seq"]
    _need(upto == seq - 1, seq,
          f"witness upto_seq must be {seq - 1} (a checkpoint covers every entry before it)")
    _need(body["head"] == st.head, seq, "witness head mismatch")
    mark = st.witness_marks.get(actor)
    _need(mark is None or st.acts > mark["acts"], seq,
          f"no entry but checkpoints since the last checkpoint of {actor} (a witness posts a checkpoint only when "
          "an entry that is not a checkpoint was added since its last one)")
    _need(mark is None or now - mark["time"] >= CHECKPOINT_INTERVAL, seq,
          f"the last checkpoint of {actor} is less than 1 hour old (at most one checkpoint per witness per hour)")
    _need("root" not in body or body["root"] == st.entries_root(), seq, "witness Merkle root mismatch")
    _need("anchor" not in body or (len(body["anchor"]) <= ANCHOR_MAX and ANCHOR_RE.fullmatch(body["anchor"]) is not None),
          seq, f"anchor: a repository-relative path (letters, digits, _ . - and /) of at most {ANCHOR_MAX} characters")
    _need(body["state_version"] == STATE_VERSION, seq,
          f"witness state_version must be {STATE_VERSION}: the version of the state document whose digest it states "
          "(a core that changes the document reads each checkpoint by its own version)")
    _need(st._trusted or body["state_sha256"] == st.digest(), seq, "witness state digest mismatch")
    st.witness_marks[actor] = {"acts": st.acts, "time": now}
    _absorb(st, "checkpoints", _record_leaf(_checkpoint_facts(body, actor)))


# -- corrections: each act checks its target and returns the member it is aimed at, if any -------------

def _recused(st: State, c: Custodian, login: str, seq: int) -> None:
    _need(not same_login(login, c.member), seq,
          f"recusal: the custodian {c.name} never corrects their own member ({c.member})")


def _act_freeze_key(st, c, target, ground, now, seq):
    """A custodian may freeze the key of the member they are linked to: it restricts nobody but themselves."""
    login = target["login"]
    m = st.members.get(login)
    _need(m is not None and m.status not in GONE, seq, "no such member")
    # A freeze that other custodians withdrew leaves no wait behind it: every other one does (and one that
    # objections voided also waits REPOST_AFTER_DAYS from that moment, N7).
    _need(all(waited(x.time, now, REFREEZE_AFTER_DAYS) for x in st.corrections.values()
              if x.act == "freeze_key" and x.target["login"] == login and not _overruled(x)), seq,
          f"the key of {login} was frozen less than {REFREEZE_AFTER_DAYS} days ago (the same key is frozen again "
          f"only {REFREEZE_AFTER_DAYS} days after the previous freeze began, unless other custodians withdrew that "
          "freeze)")
    _freeze_room(st, login, now, seq)
    return login


def _overruled(c: Correction) -> bool:
    """The correction was withdrawn by custodians other than the one who posted it. Such an act leaves no
    wait behind it and does not use up the one time a ballot may be its target: the custodian who posted it
    may post it again. An act its own poster withdrew is spent like any other."""
    return c.withdrawn is not None and c.withdrawn_by != c.by


def _act_freeze_witness(st, c, target, ground, now, seq):
    name = target["name"]
    _need(name in st.witnesses, seq, "no such witness")
    _need(st.witness_frozen(name, now) is None, seq, f"the witness {name} is already frozen")
    others = [w for w in st.witnesses if w != name and st.witness_frozen(w, now) is None]
    _need(len(others) > 0 or ground == "attack_in_progress", seq,
          "the last unfrozen witness is frozen only on the ground attack_in_progress")
    return ""


def party_to(st: State, b: Ballot, login: str) -> bool:
    """`login` is the subject of the ballot, opened it, or (for an admission) sponsors or invited its
    candidate: the ballots a custodian linked to that member never touches."""
    names = [b.opened_by, b.subject.get("member", ""), b.subject.get("candidate", "")]
    if b.kind == "admission":
        names += list(b.frozen.get("vouches", ()))
        names += st.petitions.get(b.subject.get("candidate", ""), {}).get("vouches", [])
    return any(same_login(x, login) for x in names if x)


def _act_stay(st, c, target, ground, now, seq):
    bid = target["ballot"]
    b = st.ballots.get(bid)
    _need(b is not None and b.result is None, seq, "no open ballot")
    _need(b.kind not in STAY_EXEMPT, seq, f"a ballot of kind {b.kind} is never stayed")
    _not_sunset(b, seq)
    _need(all(x.act != "stay" or x.target["ballot"] != bid for x in st.corrections.values()), seq,
          f"ballot {bid} was stayed once already (a ballot is stayed at most once)")
    _before_reveals(st, b, now, seq)
    _need(not party_to(st, b, c.member), seq,
          f"recusal: the custodian {c.name} never stays a ballot whose subject, opener or sponsor is their own "
          f"member ({c.member})")
    return b.subject.get("member", "")


def _act_halt(st, c, target, ground, now, seq):
    _need(all(waited(x.time, now, HALT_INTERVAL_DAYS) for x in st.corrections.values() if x.act == "halt"), seq,
          f"the ledger was halted less than {HALT_INTERVAL_DAYS} days ago (at most one halt in {HALT_INTERVAL_DAYS} "
          "days, start to start)")
    return ""


def _act_hold_room(st, c, target, ground, now, seq):
    login = target["login"]
    m = st.members.get(login)
    _need(m is not None and m.status not in GONE, seq, "no such member")
    _recused(st, c, login, seq)
    _need(st.room_hold(login, now) is None, seq, f"{login} is already under a room hold")
    _need(all(waited(x.time, now, REHOLD_AFTER_DAYS) for x in st.corrections.values()
              if x.act == "hold_room" and x.target["login"] == login and not _overruled(x)), seq,
          f"{login} was held less than {REHOLD_AFTER_DAYS} days ago (the same login is held again only "
          f"{REHOLD_AFTER_DAYS} days after the previous hold began, unless other custodians withdrew that hold; "
          "only a sanction ballot keeps a member out longer)")
    return login


def _not_sunset(b: Ballot, seq: int) -> None:
    _need(not sunset_ballot(b), seq,
          "recusal: a ballot that adds a witness, or that advances a member to the 3rd degree, is never stayed, "
          "voided or undone by a correction (the Sunset counts both, and the Sunset ends the custodians' keys)")


def _before_reveals(st: State, b: Ballot, now: datetime, seq: int) -> None:
    """A ballot is stayed, or its voiding posted, only before its reveal window opens: no custodian pauses
    or ends a ballot after reading a vote."""
    opens = b.commit_until + REVEAL_GAP
    _need(st.ballot_time(b, now) < opens, seq,
          f"the reveal window of ballot {b.id} opened at {iso(st.ballot_due(b, opens))}: a ballot is stayed, or its "
          "voiding posted, only before any vote can be revealed")


def _act_note(st, c, target, ground, now, seq):
    _need(target["action"] in NOTE_ACTIONS, seq, f"note action must be one of {sorted(NOTE_ACTIONS)}")
    _need(NOTE_TARGET_RE.fullmatch(target["target"]) is not None, seq,
          "note target: 1..120 of letters, digits and . _ : / # @ - starting with a letter or digit")
    _need(NOTE_RULE_RE.fullmatch(target["rule"]) is not None, seq,
          "note rule: 1..64 of letters, digits and . _ : / # - starting with a letter or digit")
    today = 0
    for x in reversed(st.notes):             # the newest first: the scan ends at the first note of an earlier day
        if x["time"].date() != now.date():
            break
        today += x["by"] == c.name
    _need(today < NOTES_PER_DAY, seq, f"at most {NOTES_PER_DAY} notes per custodian per UTC day")
    return ""


# -- the two noticed acts: each checks its ballot for every custodian who signs or applies it. With
# -- `posting` the checks of the day the correction is posted are added; they are not asked again later.

def _ballot_recusal(st: State, b: Ballot, custodians, seq: int) -> None:
    for c in custodians:
        _need(not party_to(st, b, c.member), seq,
              f"recusal: the custodian {c.name} never voids or undoes a ballot whose subject, opener or sponsor "
              f"is their own member ({c.member})")


def _once(st: State, act: str, bid: str, seq: int) -> None:
    earlier = next((x.seq for x in st.corrections.values()
                    if x.act == act and x.target["id"] == bid and not _overruled(x)), None)
    _need(earlier is None, seq,
          f"ballot {bid} was the target of a {act} once already (correction {earlier}): a ballot is the target "
          f"of a {act} at most once, unless other custodians withdrew it")


def _check_void(st: State, custodians, target: dict, now: datetime, seq: int, posting: bool) -> Ballot:
    bid = target["id"]
    b = st.ballots.get(bid)
    _need(b is not None and b.result is None, seq, "no open ballot")
    _need(b.kind not in STAY_EXEMPT, seq, f"a ballot of kind {b.kind} is never voided or undone by a correction")
    _not_sunset(b, seq)
    if posting:
        _once(st, "void_ballot", bid, seq)
        _before_reveals(st, b, now, seq)
    _ballot_recusal(st, b, custodians, seq)
    return b


def _check_undo(st: State, custodians, target: dict, now: datetime, seq: int, posting: bool) -> Ballot:
    bid = target["id"]
    b = st.ballots.get(bid)
    _need(bid not in st.retired, seq, _retired_text(bid))
    _need(b is not None, seq, "no such ballot")
    _need(b.kind in UNDO_KINDS, seq,
          f"only an admission or an advancement is undone by a correction (ballot {bid} is of kind {b.kind})")
    _not_sunset(b, seq)
    _need(b.corrected is None, seq, f"ballot {bid} was already voided or undone (correction {b.corrected})")
    _need(b.result == "passed", seq,
          f"only a ballot that passed is undone (ballot {bid} {'is still open' if b.result is None else b.result})")
    if b.kind == "advancement":
        m = st.members.get(b.subject["member"])
        _need(m is not None and m.status not in ("departed", "voided"), seq,
              f"the undo of ballot {bid} has nothing to undo: {b.subject['member']} left, and a record that left "
              "is not touched")
    if posting:
        _need(not expired(b.closed, now, UNDO_WINDOW_DAYS), seq,
              f"ballot {bid} closed more than {UNDO_WINDOW_DAYS} days ago (a ballot is undone only by a correction "
              f"posted within {UNDO_WINDOW_DAYS} days of its close)")
        _once(st, "undo_ballot", bid, seq)
    elif b.kind == "admission":
        sanction = st.open_sanction_on(b.subject["candidate"])
        _need(sanction is None, seq,
              f"the undo of ballot {bid} is not applied while a sanction ballot on {b.subject['candidate']} is open "
              f"(ballot {sanction.id if sanction else ''}): the members decide first")
    _ballot_recusal(st, b, custodians, seq)
    return b


def _act_void_ballot(st, c, target, ground, now, seq):
    return _check_void(st, [c], target, now, seq, True).subject.get("member", "")


def _act_undo_ballot(st, c, target, ground, now, seq):
    subj = _check_undo(st, [c], target, now, seq, True).subject
    return subj.get("member", "") or subj.get("candidate", "")


ACTS = {"freeze_key": _act_freeze_key, "freeze_witness": _act_freeze_witness, "stay": _act_stay, "halt": _act_halt,
        "hold_room": _act_hold_room, "note": _act_note, "void_ballot": _act_void_ballot,
        "undo_ballot": _act_undo_ballot}


def _correction(st, e, now, seq, actor, body):
    """A custodian's correction: one act of the closed menu, on one closed ground, with a public reason.
    An immediate act is in force from this entry and is ended by time alone, and one custodian key is
    enough for it. A noticed act (`void_ballot`, `undo_ballot`) has its effect only when it is applied (a
    pending `void_ballot` pauses its ballot). A `note` is recorded in `State.notes` and is no correction."""
    act, target, ground = body["act"], body["target"], body["ground"]
    c = st.custodians[actor]
    _need(act in ACTS, seq, f"act must be one of {sorted(ACTS)}")
    _need(ground in GROUNDS, seq, f"ground must be one of {sorted(GROUNDS)}")
    _need(HEX64.fullmatch(body["reason_sha256"]) is not None, seq,
          "reason_sha256 is the sha256 (64 lowercase hex) of the public reason, archived as ledger/reasons/<sha256>.md")
    _shape(target, TARGET_FIELDS[act], seq, f"correction entry: {act} target")
    _need(ACT_GROUND.get(act, ground) == ground, seq, f"{act} takes one ground only: {ACT_GROUND.get(act)}")
    _need(act == "note" or ground != NOTE_GROUND, seq,
          f"the ground {NOTE_GROUND} is the ground of a note, and of no other act")
    subject = ACTS[act](st, c, target, ground, now, seq)
    if act == "note":
        # Every check has passed: only now does anything change. A note is kept apart from the corrections
        # (it has no effect, takes no objection and counts against no allowance), and only the newest are kept.
        st.notes.append({"seq": seq, "by": actor, **target, "reason_sha256": body["reason_sha256"], "time": now})
        for old in st.notes[:-NOTES_KEPT]:   # the oldest leaves the state for the history of notes
            _absorb(st, "notes", _leaf(old["seq"], old))
        del st.notes[:-NOTES_KEPT]
        return
    voided = next((x for x in st.corrections.values() if x.act == act and x.target == target and x.void is not None
                   and not waited(x.void, now, REPOST_AFTER_DAYS)), None)
    _need(voided is None, seq,
          f"correction {voided.seq if voided else 0}, the same act on the same target, was voided by objections less "
          f"than {REPOST_AFTER_DAYS} days ago (it is posted again only {REPOST_AFTER_DAYS} days after that)")
    recent = [x.by for x in st.corrections.values() if not waited(x.time, now, CORRECTION_WINDOW_DAYS)]
    _need(len(recent) < CORRECTIONS_PER_30_DAYS, seq,
          f"at most {CORRECTIONS_PER_30_DAYS} corrections in any {CORRECTION_WINDOW_DAYS} days, all custodians "
          "together (notes aside)")
    live = len(st.custodians_live(now))
    share = -(-CORRECTIONS_PER_30_DAYS // live)
    _need(recent.count(actor) < share, seq,
          f"at most {share} corrections per custodian in any {CORRECTION_WINDOW_DAYS} days while {live} custodian "
          f"key(s) are live (each one's share of the {CORRECTIONS_PER_30_DAYS} of all custodians together; notes aside)")
    # Every check has passed: only now does anything change.
    noticed = act in NOTICED_ACTS
    st.corrections[seq] = Correction(seq, actor, act, dict(target), ground, body["reason_sha256"], now,
                                     class_="noticed" if noticed else "immediate",
                                     until=None if noticed else now + ACT_DAYS[act] * DAY,
                                     subject=subject, signers=(actor,) if noticed else ())
    if act == "freeze_key":
        _recuse_frozen(st, target["login"], now)


def _noticed(st: State, body: dict, now: datetime, seq: int, doing: str) -> Correction:
    """The noticed correction an entry names, which must still be pending."""
    c = st.corrections.get(body["seq"])
    _need(c is not None, seq, "no such correction")
    _need(c.class_ == "noticed", seq,
          f"correction {c.seq} is not a noticed act (an immediate act is the act of one custodian key and takes "
          "effect by itself)")
    status = st.noticed_status(c, now)
    _need(status != "applied", seq, f"correction {c.seq} was already applied (a correction is applied once)")
    _need(status in ("pending", "ready"), seq, f"correction {c.seq} is {status}: nothing to {doing}")
    return c


def _correction_cosign(st, e, now, seq, actor, body):
    """Another custodian key endorses a pending noticed act, until its signers reach the threshold."""
    c = _noticed(st, body, now, seq, "co-sign")
    _need(actor not in c.signers, seq, f"{actor} already signed correction {c.seq}")
    _need(len(st.live_signers(c, now)) < st.custodian_threshold, seq,
          f"correction {c.seq} already has the {st.custodian_threshold} custodian signature(s) it needs")
    _ballot_recusal(st, st.ballots[c.target["id"]], [st.custodians[actor]], seq)
    c.signers = (*c.signers, actor)


def _correction_apply(st, e, now, seq, actor, body):
    """A live custodian key gives a noticed act its effect: after the notice, within the time to apply it,
    with enough signers, and with every precondition of the act checked again as things stand now."""
    c = _noticed(st, body, now, seq, "apply")
    n = c.seq
    _need(now >= st.notice_end(c), seq,
          f"correction {n} is under notice until {iso(st.notice_end(c))} ({NOTICE_DAYS} days after it was posted)")
    signers = st.live_signers(c, now)
    _need(len(signers) >= st.custodian_threshold, seq,
          f"correction {n} has {len(signers)} of the {st.custodian_threshold} custodian signature(s) it needs")
    judges = {x: st.custodians[x] for x in (*signers, actor)}.values()     # the author, the co-signers, the one who applies
    if c.act == "void_ballot":
        b = _check_void(st, judges, c.target, now, seq, False)
    else:
        b = _check_undo(st, judges, c.target, now, seq, False)
        for name, (_, after) in b.undo.items():      # compare-and-swap: all of it, or nothing
            found = _facts(st, b)[name]
            _need(found == after, seq,
                  f"the undo of ballot {b.id} no longer applies: {name} is {found!r}, not {after!r} as the ballot "
                  "left it (nothing is undone unless everything the ballot changed still stands)")
    # Every check has passed: only now does anything change.
    c.applied, c.applied_by = now, actor
    b.corrected = n
    if c.act == "void_ballot":
        _void_ballot(st, b)
        _ended(st, b, now)
    else:
        _undo_ballot(st, b, now)


def _void_ballot(st: State, b: Ballot) -> None:
    """The ballot ends with no effect and nobody is penalized: what its opening changed is put back. Its
    commitments and revealed votes stay in the record and are never counted."""
    b.result = "voided"
    _release_exam(st, b)                     # the exam is as it was before the ballot opened: passed, and free


def _undo_ballot(st: State, b: Ballot, now: datetime) -> None:
    """A passed ballot is undone: each fact it set goes back, and nothing that was done since is touched.
    An admission is not put back to the record it replaced: the member becomes `voided`."""
    b.result = "undone"
    s = b.subject
    if b.kind == "advancement":
        m = st.members[s["member"]]
        m.degree = b.undo["member.degree"][0]
        del m.since[s["degree"]]
        m.touch()
        ex = st.exams.get((m.login, s["degree"]))
        if ex is not None:
            ex.lapsed = True                 # the exam no longer counts, with no retry wait: a new one may open at once
    else:
        login = s["candidate"]
        m = st.members[login]
        m.status, m.status_since, m.seat_until = "voided", now, None
        # The electorates of open ballots are not touched, and a vote the member sealed is still revealed
        # (`_signer`): it was cast. One not yet sealed can no longer be. No correction changes a vote.
        _recuse_frozen(st, login, now)       # an examiner's seat passes on, as by a recusal
        for q in st.petitions.values():      # no longer a sponsor of anyone
            if login in q["vouches"]:
                q["vouches"] = [v for v in q["vouches"] if v != login]
        for cand in [x for x, i in st.invitations.items() if i["by"] == login]:
            del st.invitations[cand]


def _correction_withdraw(st, e, now, seq, actor, body):
    """A custodian withdraws an act that is in force (the member is unfrozen, the ballot resumes) or a
    noticed act that is still pending. The custodian who posted it withdraws it alone; the others withdraw
    it together, as many of them as a noticed act needs keys (`custodian_threshold`)."""
    c = st.corrections.get(body["seq"])
    _need(c is not None, seq, "no such correction")
    _need(st.in_force(c, now) or st.pending(c, now), seq,
          f"correction {body['seq']} is not in force or pending (nothing to withdraw)")
    _need(actor not in c.withdrawals, seq, f"{actor} already signed the withdrawal of correction {c.seq}")
    c.withdrawals = (*c.withdrawals, actor)
    signed = [x for x in c.withdrawals if st.custodian_status(st.custodians[x], now) == "live"]
    if actor == c.by or len(signed) >= st.custodian_threshold:
        c.withdrawn, c.withdrawn_by = now, actor


def _correction_object(st, e, now, seq, actor, body):
    """A Master Builder objects. At max(1, ceil(E / 5)) objections the correction is void for good, unless
    it is a noticed act already applied: then the objection is on the record and reverses nothing."""
    c = st.corrections.get(body["seq"])
    _need(c is not None, seq, "no such correction")
    n = c.seq
    _need(st.members[actor].degree >= canon.SPONSOR_MIN_DEGREE, seq, "only Master Builders may object to a correction")
    linked = st.custodians[c.by].member
    _need(actor != linked, seq, f"{actor} is the member of the custodian who made correction {n} and cannot object to it")
    cosigned = {st.custodians[x].member for x in c.signers}
    _need(actor not in cosigned, seq,
          f"{actor} is the member of a custodian who co-signed correction {n} and cannot object to it")
    _need(actor != c.subject, seq, f"{actor} is the target of correction {n} and cannot object to it")
    _need(c.void is None, seq, f"correction {n} is already void")
    _need(not expired(c.applied or c.time, now, OBJECTION_DAYS), seq,
          f"objections to correction {n} closed {OBJECTION_DAYS} days after it"
          + (" was applied" if c.applied is not None else ""))
    _need(actor not in c.objections, seq, f"already objected to correction {n}")
    c.objections = (*c.objections, actor)
    eligible = [x for x in st.masters(now) if x != c.subject and x != linked and x not in cosigned]
    if c.applied is None and len(c.objections) >= objections_needed(len(eligible)):
        c.void = now


def _custodian_alive(st, e, now, seq, actor, body):
    """The sign of life that keeps a custodian key from lapsing. Nothing else counts as one."""
    c = st.custodians[actor]
    _need(now - c.alive >= ALIVE_INTERVAL, seq,
          f"the custodian {actor} gave a sign of life less than 24 hours ago (at most one custodian_alive per "
          "custodian in 24 hours)")
    c.alive = now


def _custodian_revoke(st, e, now, seq, actor, body):
    """Signed by the revoke key: the custodian key is removed at once, and with it whatever it had in force."""
    st.custodians[actor].revoked = now


# -- the founder's fallback (SPEC §6.31 to §6.33) ----------------------------------------------------

def _claim_conditions(st: State, founder: str, now: datetime, seq: int) -> None:
    """What a claim of the Custodian office needs, when it is signed and again when it is applied."""
    live = st.custodians_live(now)
    _need(not live, seq, f"the custodian key of {live[0] if live else ''} is live: the office is taken up again only "
                         "when no custodian key is live")
    _need(st.sunset is None, seq, f"the Sunset was reached at {iso(st.sunset) if st.sunset else ''}: no founder takes "
                                  "up the Custodian office after it")
    n = st.non_founder_masters(now)
    _need(n < CLAIM_MASTERS, seq,
          f"{n} active Master Builders who are not founders exist: with {CLAIM_MASTERS} or more the Custodian office "
          "is filled only by amendment")
    removed = next((c for c in st.custodians.values() if c.removed and same_login(c.member, founder)), None)
    _need(removed is None, seq,
          f"a removal ballot ({removed.removed if removed else ''}) passed against the custodian key "
          f"{removed.name if removed else ''} of {founder}: that founder never takes up the office again")


def _custodian_claim(st, e, now, seq, actor, body, verifier):
    """a founder takes up the Custodian office again, with a new custodian key and a new revoke key, both
    proved as at genesis. It is pending for CLAIM_NOTICE_DAYS; one objection of an active Master Builder who is
    not a founder voids it; the founder applies it within CLAIM_EXPIRY_DAYS (`custodian_claim_apply`)."""
    _need(st.members[actor].founder, seq, "only a founder may claim the Custodian office")
    _claim_conditions(st, actor, now, seq)
    other = st.claim_pending(now)
    _need(other is None, seq, f"a claim of the Custodian office is already pending (entry {other.seq if other else 0})")
    last = next(reversed(st.claims.values()), None)
    _need(last is None or last.objected is None or waited(last.objected, now, CLAIM_AGAIN_DAYS), seq,
          f"the claim of entry {last.seq if last else 0} was objected to less than {CLAIM_AGAIN_DAYS} days ago (after "
          f"an objection, the next claim of any founder waits {CLAIM_AGAIN_DAYS} days, so that no name is held out "
          "of invitations claim after claim)")
    name, key, revoke = body["name"], body["key"], body["revoke_key"]
    _need(valid_login(name), seq, "custodian names follow login rules")
    holders = st.name_holders(name, now)
    _need(not holders, seq,
          f"the custodian name {name!r} is held by the {holders[0][0] if holders else ''} "
          f"{holders[0][1] if holders else ''!r} (a custodian name is a login nobody holds, case-insensitive)")
    _need(ed25519(key) and ed25519(revoke), seq, KEY_RULE)
    _need(not same_key(key, revoke) and not st.key_holders(key, now) and not st.key_holders(revoke, now)
          and point(key) not in st.known_keys and point(revoke) not in st.known_keys, seq,
          "a claimed custodian key and its revoke key must differ from each other and be new keys (a key that was "
          "ever registered here is never registered again)")
    _need(verifier(custodian_message(name, actor, key), body["proof"], name, key) is True, seq,
          "bad custodian proof: the custodian key must sign the custodian message (name, member, key)")
    _need(verifier(custodian_revoke_message(name, key, revoke), body["revoke_proof"], name, revoke) is True, seq,
          "bad custodian revoke proof: the revoke key must sign the revoke message (name, key, revoke key)")
    st.claims[seq] = Claim(seq, actor, name, key, revoke, now)
    st.known_keys |= {point(key), point(revoke)}


def _claim_named(st: State, body: dict, now: datetime, seq: int) -> Claim:
    c = st.claims.get(body["seq"])
    _need(c is not None, seq, f"entry {body['seq']} is not a claim of the Custodian office")
    status = st.claim_status(c, now)
    _need(status in ("pending", "ready"), seq, f"the claim of entry {c.seq} is {status}")
    return c


def _custodian_claim_object(st, e, now, seq, actor, body):
    """One active Master Builder who is not a founder voids a pending claim: a stolen member key never mints
    the office against the Masters who are there."""
    c = _claim_named(st, body, now, seq)
    m = st.members[actor]
    _need(m.degree >= canon.SPONSOR_MIN_DEGREE and not m.founder, seq,
          "only a Master Builder who is not a founder may object to a claim of the Custodian office")
    c.objected, c.objector = now, actor


def _custodian_claim_apply(st, e, now, seq, actor, body):
    """The founder gives the claim its effect after the notice: a new custodian, bound like those of the genesis
    by silence, the Sunset, a term of CUSTODIAN_TERM_DAYS from now, its revoke key and the removal ballot. It is
    the only live custodian key, so a noticed act needs that one key."""
    c = _claim_named(st, body, now, seq)
    _need(c.founder == actor, seq, f"only {c.founder}, who signed the claim of entry {c.seq}, applies it")
    _need(waited(c.time, now, CLAIM_NOTICE_DAYS), seq,
          f"the claim of entry {c.seq} is under notice until {iso(c.time + CLAIM_NOTICE_DAYS * DAY)} "
          f"({CLAIM_NOTICE_DAYS} days after it)")
    _claim_conditions(st, actor, now, seq)
    st.custodians[c.name] = Custodian(c.name, c.key, c.revoke_key, actor, now, genesis=False, since=now, claim=c.seq)
    st.custodian_threshold = 1
    c.applied = now


# -- succession (SPEC §6.34) ---------------------------------------------------------------------

def _succession_claim(st, e, now, seq, actor, body):
    """A member below the 3rd degree states that no Master Builder is present. Any entry within SUCCESSION_DAYS
    of a Master Builder who is then present (active, neither dormant nor silent) cancels it (`_succession_watch`);
    otherwise it is in force until SUCCESSION_MASTERS present Master Builders exist."""
    _need(st.members[actor].degree < canon.SPONSOR_MIN_DEGREE, seq,
          "a Master Builder needs no succession (only a member below the 3rd degree claims it)")
    present = st.present_masters(now)
    _need(not present, seq, f"an active Master Builder who is neither dormant nor silent exists "
                            f"({present[0] if present else ''}): no succession")
    status = st.succession_status(now)
    _need(status not in ("pending", "in_force"), seq,
          f"a succession claim is already {status.replace('_', ' ') if status else ''} (entry "
          f"{st.succession.seq if st.succession else 0})")
    st.succession = Succession(seq, actor, now)


def _succession_watch(st: State, member: Member | None, now: datetime) -> None:
    """After every entry: a Master Builder who signed cancels a pending succession claim, and a succession ends
    for good once SUCCESSION_MASTERS active Master Builders exist."""
    s = st.succession
    if s is None or s.end is not None:
        return
    status = st.succession_status(now)
    if status == "pending" and member is not None and member.degree >= canon.SPONSOR_MIN_DEGREE \
            and member.is_active(now) and not member.dormant(now) and not member.silent(now) \
            and st.members.get(member.login) is member:
        s.end, s.canceled_by = now, member.login
    elif len(st.present_masters(now)) >= SUCCESSION_MASTERS:
        s.end = now


def room_held(st: State, member: Member, now: datetime) -> bool:
    """Pure: the member is under a room hold at `now` (read by the rooms rule; no rule of the ledger reads it)."""
    return st.room_hold(member.login, now) is not None


def room_hold_until(st: State, member: Member, now: datetime) -> datetime | None:
    """When the hold on the member ends as things stand; None when there is none."""
    hold = st.room_hold(member.login, now)
    return st.span(hold)[1] if hold is not None else None


HANDLERS = {
    "genesis": _genesis, "invite": _invite, "petition": _petition, "vouch": _vouch,
    "ballot_open": _ballot_open, "ballot_commit": _ballot_commit,
    "ballot_reveal": _ballot_reveal, "ballot_close": _ballot_close,
    "exam_open": _exam_open, "exam_draw": _exam_draw, "exam_report": _exam_report, "exam_recuse": _exam_recuse,
    "council_call": _council_call, "council_draw": _council_draw, "work": _work, "depart": _depart, "witness": _witness,
    "rekey": _rekey,
    "correction": _correction, "correction_withdraw": _correction_withdraw, "correction_object": _correction_object,
    "custodian_alive": _custodian_alive, "custodian_revoke": _custodian_revoke,
    "correction_cosign": _correction_cosign, "correction_apply": _correction_apply,
    "rekey_recover": _rekey_recover, "rekey_cosign": _rekey_cosign, "rekey_object": _rekey_object,
    "rekey_recover_apply": _rekey_recover_apply, "rekey_oppose": _rekey_oppose,
    "custodian_claim": _custodian_claim, "custodian_claim_object": _custodian_claim_object,
    "custodian_claim_apply": _custodian_claim_apply, "succession_claim": _succession_claim,
}
PROVING = frozenset({"genesis", "ballot_open", "rekey", "rekey_recover", "custodian_claim"})   # types whose rule checks further signatures: they get the verifier
UNCREDITED = frozenset({"depart", "rekey", "rekey_object"})  # types that add no activity to the member who signs them


# ------------------------------------------------------- building entries ---

def utc_now() -> str:
    return iso(datetime.now(timezone.utc))


def make_entry(st: State | None, typ: str, actor: str, body: dict, time: str | None = None) -> dict:
    """The unsigned envelope of the next entry (the caller adds `sig`)."""
    if time is None:                    # never before the head: one second after it when this clock is behind
        time = utc_now()
        if st is not None and st.time is not None and ts(time) <= st.time:
            time = iso(st.time + SECOND)
    return {"seq": st.seq + 1 if st else 0, "prev": st.head if st else canon.ZERO_HASH,
            "time": time, "type": typ, "actor": actor, "body": body}


def entry_text(entry: dict) -> str:
    """The file text the tools write for an entry. Raises Invalid if it would exceed the size cap."""
    text = json.dumps(entry, indent=2, ensure_ascii=False) + "\n"
    limit = MAX_GENESIS_BYTES if entry.get("seq") == 0 else MAX_ENTRY_BYTES
    _need(len(text.encode("utf-8")) <= limit, entry.get("seq", 0), f"entry exceeds {limit} bytes")
    return text


def append_signed(ledger_dir: Path, st: State | None, typ: str, actor: str, body: dict, key: Path,
                  time: str | None = None) -> tuple[dict, State]:
    """Sign the next entry, check it against a copy of the state, then write its file.

    Returns (entry, new_state). Raises Invalid when the protocol would refuse the entry, and
    crypto.SigningError when it cannot be signed; in both cases nothing is written.
    """
    e = make_entry(st, typ, actor, body, time)
    try:
        strict_value(e)                 # nothing is signed that the encoding rules would refuse
    except ValueError as err:
        raise Invalid(e["seq"], f"not strict JSON: {err}") from None
    e["sig"] = sign(signed_payload(e), key)
    nxt = copy.deepcopy(st) if st else State()
    apply(nxt, e)                       # refuse to write an entry the protocol would reject
    text = entry_text(e)                # …or a file larger than the loader accepts
    path = entry_path(ledger_dir, e["seq"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return e, nxt


def due_actions(st: State, now: datetime) -> list[tuple[str, dict]]:
    """Pure: the automatic work a witness owes at `now` (ballots to close, lots to draw).

    Lots return a body without `beacon`; the shell fills it from drand for the given round.
    """
    out: list[tuple[str, dict]] = []
    halted = st.halted(now) is not None      # a halted ledger closes only an amendment or the ballot that removes a custodian
    for b in st.ballots.values():
        if b.result is None and (not halted or b.kind in UNSTOPPABLE_KINDS) and st.stayed(b.id, now) is None \
                and st.void_pending(b.id, now) is None and closable(st, b, now):
            out.append(("ballot_close", {"id": b.id}))
    if halted:
        return out                           # …and no lot (a witness still checkpoints)
    for ex in st.exams.values():
        if ex.examiners is None and not ex.lapsed and now >= drand_time(ex.beacon_round) and not ex.expired(now, st) \
                and not ex.draw_lapsed(now, st):
            out.append(("exam_draw", {"candidate": ex.candidate, "degree": ex.degree, "_round": ex.beacon_round}))
    if st.council_call is not None and now >= drand_time(st.council_call) and not council_lapsed(st, now):
        out.append(("council_draw", {"_round": st.council_call}))
    return out


# ------------------------------------------------ the verified head ---------
# SPEC §9.7: a rule of clients, not of replay. A clone remembers the head of the canonical ledger it last
# verified, so a history that was rewound and written again is told from a mirror that is only behind.
# Everything here is pure. The memory is a JSON value the caller reads and writes, outside the repository:
#     {"v": 1, "heads": {genesis entry hash: [{"seq": n, "hash": entry hash}, …]}}
# with one mark per history of that genesis the clone verified, or accepted as a fork.

HEADS_VERSION = 1                   # the `v` of that value


def future_head(head_time: datetime, now: datetime) -> bool:
    """The last entry is dated more than FUTURE_TOLERANCE ahead of the clock `now`. The judge merges no entry
    dated more than JUDGE_FUTURE_TOLERANCE ahead of its own clock, so a head this far ahead did not pass it
    (the gap between the two keeps an honest clock a little behind from raising the alarm): a capture alarm
    condition, because every notice period of the protocol rests on honest timestamps."""
    return head_time - now > FUTURE_TOLERANCE


def head_marks(store, genesis: str) -> list[tuple[int, str]]:
    """The heads remembered for one genesis, as `(seq, entry hash)` in ascending order. Anything in the value
    that is not a well-formed mark is not a mark."""
    heads = store.get("heads") if type(store) is dict else None
    marks = heads.get(genesis) if type(heads) is dict else None
    return sorted({(m["seq"], m["hash"]) for m in (marks if type(marks) is list else [])
                   if type(m) is dict and type(m.get("seq")) is int and m["seq"] >= 0 and type(m.get("hash")) is str})


def head_verdict(store, hashes: list[str], known: list[str] = ()) -> tuple[str, int, str]:
    """How a verified history stands against what this clone verified earlier: `(verdict, seq, hash)`.

    `hashes` are the entry hashes of the history, from the genesis on (at least one). `known` are those of a
    history the clone still holds (its own working copy), used only to tell the two cases of a shorter one.

    * `first`: nothing is remembered at all. `(seq, hash)` is the head of the history.
    * `ok`: the history holds a remembered head at its seq (it is that history, perhaps longer).
    * `behind`: the history holds none, and ends before a remembered head that nothing shows it to have
      lost: the same entries, fewer of them, as far as this clone can tell. `(seq, hash)` is that head.
    * `rollback`: the history holds none, and every remembered head is lost: another entry stands at its
      seq, or the history ends before it and differs from `known`, which holds it. `(seq, hash)` is the
      highest lost head.
    * `genesis`: heads are remembered, and none for this genesis: another fraternity. `(seq, hash)` is
      `(0, the genesis hash)`.
    """
    n, marks = len(hashes), head_marks(store, hashes[0])
    if not marks:
        heads = store.get("heads") if type(store) is dict else None
        others = type(heads) is dict and any(head_marks(store, g) for g in heads)
        return ("genesis", 0, hashes[0]) if others else ("first", n - 1, hashes[-1])
    if any(seq < n and hashes[seq] == h for seq, h in marks):
        return "ok", n - 1, hashes[-1]
    differs = list(known[:n]) != list(hashes)
    beyond = [(seq, h) for seq, h in marks if seq >= n and not (differs and len(known) > seq and known[seq] == h)]
    return ("behind", *beyond[-1]) if beyond else ("rollback", *marks[-1])


def remember_head(store, hashes: list[str]) -> dict:
    """The memory after the history was verified and found `first` or `ok`, or was accepted by the person:
    its head replaces every remembered head it holds, and the heads it does not hold are kept, each the
    mark of another history of the same genesis that was accepted once."""
    n, heads = len(hashes), {}
    for genesis in (store.get("heads") if type(store) is dict and type(store.get("heads")) is dict else {}):
        if type(genesis) is str and head_marks(store, genesis):
            heads[genesis] = head_marks(store, genesis)
    kept = [(seq, h) for seq, h in heads.get(hashes[0], []) if not (seq < n and hashes[seq] == h)]
    heads[hashes[0]] = sorted(kept + [(n - 1, hashes[-1])])
    return {"v": HEADS_VERSION, "heads": {g: [{"seq": seq, "hash": h} for seq, h in marks] for g, marks in heads.items()}}


# ------------------------------------------------------------- io -----------
# SPEC §2.7. The entries directory holds shards, and each shard the entries of one thousand seqs:
#     ledger/entries/0000/000000.json … 0000/000999.json, 0001/001000.json, …, 10000/10000000.json
# The shard is seq // SHARD_SIZE in decimal, padded with zeros to four digits at least, and the file the seq,
# padded to six digits at least, so every entry has exactly one path and each shard holds SHARD_SIZE entries
# (the last one fewer). Nothing else may be there but one `.gitkeep` at the top.

KEEP_FILE = ".gitkeep"              # the only name allowed in the entries directory besides its shards (at the top)
SHARD_SIZE = 1000                   # entries per shard directory
SHARD_NAME_RE = re.compile(r"[0-9]{4,13}")              # the digits of a shard name (the seq is at most 16 digits)
ENTRY_FILE_RE = re.compile(r"([0-9]{6,16})\.json")      # …and of an entry file name


def entry_name(seq: int) -> str:
    """The path of entry `seq` inside the entries directory: `{seq // SHARD_SIZE:04d}/{seq:06d}.json`."""
    return f"{seq // SHARD_SIZE:04d}/{seq:06d}.json"


def entry_path(directory: Path, seq: int) -> Path:
    """The file of entry `seq` in the entries directory `directory`."""
    return Path(directory) / entry_name(seq)


def shard_number(name: str) -> int | None:
    """The number of a shard directory named `name`, or None when `name` is not the canonical name of a shard."""
    return int(name) if SHARD_NAME_RE.fullmatch(name) and name == f"{int(name):04d}" else None


def entry_seq(name: str) -> int | None:
    """The seq of the entry whose path inside the entries directory is `name` (`/` between shard and file), or
    None when `name` is not exactly the path of an entry: another padding, another shard, anything else."""
    shard, _, file = name.partition("/")
    m = ENTRY_FILE_RE.fullmatch(file)
    return int(m.group(1)) if m and shard_number(shard) is not None and entry_name(int(m.group(1))) == name else None


def entry_order(names) -> list[str]:
    """The paths of the entries, in seq order, of a listing of the entries directory. Pure.

    `names` are the paths, relative to the directory and with `/` between their parts, of everything the
    directory holds that is not a shard directory: the files of the shards, anything else found in a shard, and
    anything found at the top. The one `.gitkeep` at the top is ignored. Raises Invalid (SPEC §2.7, rules 3 and 4)
    at the first name, in the order of `(length, name)`, that is not the path of an entry, and then at the first
    seq that is missing: the entries are numbered from 0 with no gap."""
    seqs: dict[int, str] = {}
    for name in sorted((n for n in names if n != KEEP_FILE), key=lambda n: (len(n), n)):
        seq = entry_seq(name)
        if seq is not None:
            seqs[seq] = name
            continue
        parts = name.split("/")
        m = ENTRY_FILE_RE.fullmatch(parts[-1])
        file_seq = int(m.group(1)) if m and parts[-1] == f"{int(m.group(1)):06d}.json" else None
        if len(parts) == 1 and shard_number(name) is not None:
            raise Invalid(int(name) * SHARD_SIZE, f"ledger shard {name} must be a directory, not a symlink or a file")
        if len(parts) == 1 and file_seq is not None:
            raise Invalid(file_seq, f"ledger file {name} is not in its shard: entry {file_seq} is {entry_name(file_seq)}")
        if len(parts) == 2 and shard_number(parts[0]) is not None and file_seq is not None:
            raise Invalid(file_seq, f"ledger file {name} is in the wrong shard: entry {file_seq} is {entry_name(file_seq)}")
        if len(parts) >= 2 and shard_number(parts[0]) is None:
            raise Invalid(0, f"ledger directory {parts[0]} is not a shard (shards are named after seq // {SHARD_SIZE}, "
                             "in four digits at least: 0000, 0001, …)")
        at = int(parts[0]) * SHARD_SIZE if len(parts) >= 2 else 0
        raise Invalid(at, f"ledger file {name} is not an entry (the directory holds only the entries, each named "
                          f"after its seq in the shard of seq // {SHARD_SIZE}: 0000/000000.json, 0000/000001.json, …)")
    for i in range(len(seqs)):
        _need(i in seqs, i, f"ledger file {entry_name(i)} is missing (the entries are numbered from 0 without a gap)")
    return [seqs[i] for i in range(len(seqs))]


def load(directory: Path) -> list[dict]:
    """Strict loader (SPEC §2.7): the directory holds shard directories of regular entry files and nothing else
    (a `.gitkeep` at the top aside); JSON is unambiguous. Reported paths are relative to the directory."""
    directory = Path(directory)
    try:
        top = os.listdir(directory)
    except FileNotFoundError:
        return []                           # no directory yet: an empty ledger
    except OSError as err:
        raise Invalid(0, f"cannot read the ledger directory: {err.strerror or err}") from None
    names = []
    for name in sorted((n for n in top if n != KEEP_FILE), key=lambda n: (len(n), n)):
        at = shard_number(name)
        try:
            if not stat.S_ISDIR(os.lstat(directory / name).st_mode):
                names.append(name)          # a file or a link at the top: `entry_order` says what it is
                continue
            _need(at is not None, 0, f"ledger directory {name} is not a shard (shards are named after seq // "
                                     f"{SHARD_SIZE}, in four digits at least: 0000, 0001, …)")
            inner = os.listdir(directory / name)
        except OSError as err:
            raise Invalid(at * SHARD_SIZE if at else 0, f"cannot read {name}: {err.strerror or err}") from None
        _need(len(inner) > 0, at * SHARD_SIZE, f"ledger shard {name} holds no entry")
        names += [f"{name}/{n}" for n in inner]
    entries = []
    for i, name in enumerate(entry_order(names)):
        limit = MAX_GENESIS_BYTES if i == 0 else MAX_ENTRY_BYTES
        try:
            info = os.lstat(directory / name)
            _need(stat.S_ISREG(info.st_mode), i, f"ledger file {name} must be a regular file, not a symlink or a directory")
            _need(info.st_size <= limit, i, f"{name} exceeds {limit} bytes")
            raw = (directory / name).read_bytes()
        except OSError as err:
            raise Invalid(i, f"cannot read {name}: {err.strerror or err}") from None
        _need(len(raw) <= limit, i, f"{name} exceeds {limit} bytes")
        try:
            e = strict_json(raw)
        except ValueError as err:
            raise Invalid(i, f"{name} is not strict JSON: {err}") from None
        _need(type(e) is dict and type(e.get("seq")) is int and e["seq"] == i, i, f"{name} does not hold entry {i}")
        entries.append(e)
    return entries


def replay(entries: list[dict], verifier=verify, trusted: int = 0) -> State:
    """Fold the entries into a state. The first `trusted` entries are taken on trust (`apply`): a verifier
    that judges what was added to a history it verified before passes the length of that history."""
    st = State()
    for i, e in enumerate(entries):
        apply(st, e, verifier, trusted=i < trusted)
    return st
