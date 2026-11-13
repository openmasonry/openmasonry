"""The numbers of the Observatory (schema om.metrics/1), computed from the ledger alone.

Pure and outside the pinned core: `metrics(st, entries, now)` reads a verified state and the entries it was
replayed from, and returns the same document for the same inputs on every machine. Anyone can reproduce
every number from the public ledger.

Only aggregates are measured. Never, here or anywhere it is published (docs/governance/CONSOLE.md, section 3):
per-person rankings, streaks or lists sorted by Light; per-person voting profiles; per-examiner pass rates;
named lists of dormant, refused or sanctioned people; any room activity; hour-of-day or weekday histograms; IP
addresses, e-mail addresses, locations; growth targets. `NEVER_MEASURED` names the words a key of this document may not contain, and the tests hold every
document to it and to naming no login at all.
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import datetime

from . import canon, rooms
from .ledger import (CUSTODIAN_SILENCE_DAYS, DAY, INVITE_EXPIRY_DAYS, KINDS, PETITION_EXPIRY_DAYS, RESULTS, State, apply, iso, sponsorships, ts)

SCHEMA = "om.metrics/1"
STATUSES = ("active", "suspended", "expelled", "departed", "voided")
NEVER_MEASURED = ("rank", "streak", "light", "profile", "examiner", "pass_rate", "room_activity", "hour", "weekday",
                  "ip", "email", "location", "target", "goal", "login", "github")


def _month(t: datetime) -> str:
    return t.strftime("%Y-%m")


def _days(a: datetime, b: datetime) -> float:
    return round((b - a).total_seconds() / 86400, 2)


def _spread(values: list[float]) -> dict:
    return {"count": len(values), "median": round(statistics.median(values), 2) if values else None,
            "max": max(values) if values else None}


def _observe(entries: list[dict]) -> dict:
    """Replay the entries again, on trust (they were verified to reach the state given), and keep the
    records whose history a state does not keep: every ballot and every exam as it ended, and when."""
    st = State()
    ballots: list = []                      # every ballot ever opened, as the object replay keeps updating
    exams: list = []                        # every exam ever opened, likewise
    verdict: dict[int, datetime] = {}       # id(exam) -> the time its verdict was reached
    invites: list[tuple[str, datetime, bool]] = []    # (login, time, a petition followed)
    petitions: list[tuple[str, datetime, bool]] = []  # (login, time, an admission ballot followed)
    admissions, departures = Counter(), Counter()
    per_month: dict[str, Counter] = defaultdict(Counter)
    anchors = checkpoints = notes = 0
    for e in entries:
        apply(st, e, trusted=True)
        t, typ, b = ts(e["time"]), e["type"], e["body"]
        per_month[_month(t)][typ] += 1
        if typ == "genesis":
            admissions[_month(t)] += len(b.get("founders", ()))
        elif typ == "invite":
            invites.append([b["login"], t, False])
        elif typ == "petition":
            for row in invites:
                if row[0] == e["actor"] and not row[2]:
                    row[2] = True
            petitions.append([e["actor"], t, False])
        elif typ == "ballot_open":
            ballots.append(st.ballots[b["id"]])
            if b["kind"] == "admission":
                for row in petitions:
                    if row[0] == b["subject"]["candidate"] and not row[2]:
                        row[2] = True
        elif typ == "ballot_close":
            bal = st.ballots.get(b["id"])
            if bal is not None and bal.kind == "admission" and bal.result == "passed":
                admissions[_month(t)] += 1
        elif typ == "depart":
            departures[_month(t)] += 1
        elif typ == "exam_open":
            exams.append(st.exams[(b["candidate"], b["degree"])])
        elif typ == "exam_report":
            ex = st.exams.get((b["candidate"], b["degree"]))
            if ex is not None and id(ex) not in verdict and (ex.passed() or ex._fails()):
                verdict[id(ex)] = t
        elif typ == "witness":
            checkpoints += 1
            anchors += "anchor" in b
        elif typ == "correction" and b.get("act") == "note":
            notes += 1
    return {"state": st, "ballots": ballots, "exams": exams, "verdict": verdict, "invites": invites,
            "petitions": petitions, "admissions": admissions, "departures": departures, "per_month": per_month,
            "anchors": anchors, "checkpoints": checkpoints, "notes": notes}


def metrics(st: State, entries: list[dict], now: datetime) -> dict:
    """The Observatory's numbers at `now` (om.metrics/1). `st` must be the state `entries` replay to."""
    if not entries:
        return {"schema": SCHEMA, "name": "", "head": None, "time": iso(now), "founded": False}
    o = _observe(entries)
    if o["state"].head != st.head:
        raise ValueError("the state given is not the state these entries replay to")
    sorted_months = lambda c: {k: c[k] for k in sorted(c)}
    last = entries[-1]

    gone = {"departed", "expelled", "voided"}
    standing = Counter(m.standing(now) for m in st.members.values())
    of_record = [m for m in st.members.values() if m.standing(now) not in gone]
    by_degree = Counter(m.degree for m in of_record)
    active = st.active(now)

    by_kind = {k: dict.fromkeys(("open", *RESULTS), 0) for k in sorted(KINDS)}
    turnout, to_close = defaultdict(list), defaultdict(list)
    for bal in o["ballots"]:
        by_kind[bal.kind]["open" if bal.result is None else bal.result] += 1
        if bal.closed is not None and bal.opened is not None:
            to_close[bal.kind].append(_days(bal.opened, bal.closed))
            if bal.quorum_base():
                turnout[bal.kind].append(len(bal.reveals) / bal.quorum_base())

    exams = Counter()
    exam_days = []
    for ex in o["exams"]:
        if ex.passed():
            exams["passed"] += 1
        elif ex.failed(now, st):
            exams["failed"] += 1
        elif ex.lapsed:
            exams["lapsed"] += 1
        elif ex.timed_out(now, st):
            exams["timed_out"] += 1
        else:
            exams["open"] += 1
        if id(ex) in o["verdict"] and ex.opened is not None:
            exam_days.append(_days(ex.opened, o["verdict"][id(ex)]))

    adm = by_kind["admission"]
    masters = st.masters(now)
    used = sum(sponsorships(st, login, now) for login in masters)
    witness_frozen = sum(st.witness_frozen(name, now) is not None for name in st.witnesses)
    last_cp = next((e for e in reversed(entries) if e["type"] == "witness"), None)
    corrections = list(st.corrections.values())
    custodian_status = Counter(st.custodian_status(c, now) for c in st.custodians.values())
    live = [c for c in st.custodians.values() if st.custodian_status(c, now) == "live"]
    access = rooms.room_access(st, now)
    roll = rooms.readers(access)
    return {
        "schema": SCHEMA, "name": st.name, "head": st.head, "time": iso(now), "founded": True,
        "chain": {"height": len(entries), "head": st.head,
                  "last_entry": {"seq": last["seq"], "time": last["time"], "type": last["type"]},
                  "entries_per_month": {m: dict(sorted(o["per_month"][m].items())) for m in sorted(o["per_month"])}},
        "members": {"of_record": len(of_record), "by_degree": {str(d): by_degree[d] for d in sorted(by_degree)},
                    "by_status": {s: standing[s] for s in STATUSES}, "active": len(active),
                    "dormant": sum(1 for m in st.members.values() if m.is_active(now) and m.dormant(now)),
                    "masters": len(masters), "founding_phase": st.founding_phase(now),
                    "admissions_per_month": sorted_months(o["admissions"]),
                    "departures_per_month": sorted_months(o["departures"])},
        "ballots": {"open": sum(r["open"] for r in by_kind.values()), "by_kind": by_kind,
                    "turnout_by_kind": {k: {"closed": len(v), "mean": round(sum(v) / len(v), 3)}
                                        for k, v in sorted(turnout.items())},
                    "days_to_close_by_kind": {k: _spread(v) for k, v in sorted(to_close.items())}},
        "admission": {"invited": len(o["invites"]), "petitioned": len(o["petitions"]), "admitted": adm["passed"],
                      "refused": adm["failed"], "undone": adm["undone"],
                      "lapsed_invitations": sum(1 for _, t, followed in o["invites"]
                                                if not followed and st.expired(t, now, INVITE_EXPIRY_DAYS)),
                      "lapsed_petitions": sum(1 for _, t, followed in o["petitions"]
                                              if not followed and st.expired(t, now, PETITION_EXPIRY_DAYS))},
        "exams": {**{k: exams[k] for k in ("open", "passed", "failed", "timed_out", "lapsed")},
                  "days_to_verdict": _spread(exam_days)},
        "sponsorship": {"sponsors": len(masters), "budget": len(masters) * canon.SPONSOR_BUDGET_PER_YEAR, "used": used},
        "witnesses": {"count": len(st.witnesses), "frozen": witness_frozen, "checkpoints": o["checkpoints"],
                      "anchors": o["anchors"],
                      "last_checkpoint": ({"seq": last_cp["seq"], "time": last_cp["time"]} if last_cp else None)},
        "custodians": {"keys": len(st.custodians), "keys_by_status": dict(sorted(custodian_status.items())),
                       "threshold": st.custodian_threshold, "sunset": iso(st.sunset) if st.sunset else None,
                       "next_alive_due": min((iso(c.alive + CUSTODIAN_SILENCE_DAYS * DAY) for c in live), default=None),
                       "corrections": len(corrections),
                       "by_act": dict(sorted(Counter(c.act for c in corrections).items())),
                       "by_ground": dict(sorted(Counter(c.ground for c in corrections).items())),
                       "corrections_by_status": dict(sorted(Counter(st.correction_status(c, now)
                                                                    for c in corrections).items())),
                       "pending": sum(st.pending(c, now) for c in corrections),
                       "objected": sum(1 for c in corrections if c.objections),
                       "void_by_objection": sum(1 for c in corrections if c.void is not None),
                       "halts": sum(1 for c in corrections if c.act == "halt"),
                       "stays": sum(1 for c in corrections if c.act == "stay"),
                       "halted": st.halted(now) is not None, "notes": o["notes"]},
        "rooms": {"with_access": len(access),
                  "readers_per_room": {rooms.team(k): len(v) for k, v in roll.items()}},
    }
