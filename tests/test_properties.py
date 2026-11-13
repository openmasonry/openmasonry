"""Properties of replay, checked over random runs of well-formed actions (seeded: every run is repeatable).

A small cast (seven founders, two custodians, a witness and some newcomers) acts at random: each step picks,
from what the state allows at that moment, an invitation, a petition, a vote, a reveal, a close, an exam, a
correction, a recovery and so on, and now and then bends it into something unlawful. Signatures are the
stub of `tests.test_strict` (the "signature" is the key that must sign), so the signer rule is exercised and
no time goes into Ed25519.

After every entry that is offered:

* a refusal leaves the state untouched (its digest is the one before);
* an acceptance is held against the properties below, each written from the entries and the stored facts,
  not from the rule that enforces it.

And at the end of a run the whole ledger is replayed from nothing: after each entry the digest must be the
one recorded when that entry was accepted, which is replay determinism for every prefix. Every digest of the
run, which hashes again only the leaves of the records that changed, is also held against the digest computed
from nothing (`ledger.state_digest`).

Run: PYTHONPATH=src python3 -m unittest tests.test_properties -v
"""
from __future__ import annotations

import copy
import random
import time
import unittest
from unittest import mock
from datetime import timedelta

from openmasonry import canon, ledger
from openmasonry.ledger import (BEACON_DELAY_ROUNDS, CUSTODIAN_SIGNED, CUSTODIAN_SILENCE_DAYS, NOTICE_DAYS,
                                RECOVER_NOTICE_DAYS, REVEAL_GAP, Invalid, Member, State, apply, commitment, decide,
                                drand_round, drand_time, iso, replay, sponsorships)
from openmasonry.ledger import _signer
import tests.test_custodian as custodian_tests          # the module, so that its test cases are not collected here again
from tests.test_custodian import REASON, SEVEN, lodge
from tests.test_protocol import DECL, T0, checkpoint, gid, salt_of
from tests.test_strict import DAY, SEC, by_key, fake_key, hand_state

URL = "https://example.org/work"
HOUR = timedelta(hours=1)
SEEDS = (11, 23, 37, 58, 71)
STEPS = 520                          # entries offered in one run
SECONDS = 600                        # far above what the runs take: see `test_the_runs_were_not_vacuous`
# How often each kind of act is chosen among those the state allows: voting, examining and the second steps of
# a correction or a recovery need several people in a short time, so they are offered more often than the acts
# anybody can make at any moment.
WEIGHT = {"ballot_commit": 8, "ballot_reveal": 10, "ballot_close": 4, "vouch": 4, "petition": 4, "exam_open": 6,
          "exam_draw": 6, "exam_report": 8, "exam_recuse": 4, "correction_cosign": 6, "correction_apply": 10,
          "ballot_open:admission": 5, "ballot_open:advancement": 9,
          "rekey_cosign": 5, "rekey_recover_apply": 6, "rekey_recover": 3, "work": 0.5, "witness": 0.5,
          "custodian_alive": 0.5, "custodian_revoke": 3, "correction_object": 2, "rekey_object": 2,
          "correction:freeze_key": 0.8, "correction:halt": 0.2, "correction:hold_room": 0.5, "correction:note": 0.4,
          "correction:freeze_witness": 0.9, "correction:stay": 0.6, "correction:void_ballot": 0.8,
          "correction:undo_ballot": 1.4}
NEWCOMERS = [f"n{i}" for i in range(8)]
CUSTODIANS = ("warden", "keeper")
CORRECTION_TYPES = ("correction", "correction_cosign", "correction_apply", "correction_withdraw", "correction_object",
                    "custodian_alive", "custodian_revoke")
ALL_TYPES = set(ledger.HANDLERS)


class Run:
    """One seeded run: the ledger so far, the clock, and what the cast remembers (its sealed votes)."""

    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        c = lodge(custodians=(("warden", "gus"), ("keeper", "fay")), founders=SEVEN, witnesses=("tyler",),
                  custodian_threshold=2)
        self.entries, self.now = list(c.entries), c.now
        self.st = c.state()
        self.digests = [self.st.digest()]
        self.votes: dict[tuple[str, str], str] = {}
        self.keys = 0
        self.ballots = 0
        self.late = False
        self.patience = 0
        self.digest = self.digests[0]                         # of `st`, kept up to date so that it is computed once
        self.flat = copy.deepcopy(self.st)                    # the same state, never retiring a ballot (invariant 59)

    # -- what could lawfully happen now -------------------------------------------------------------------

    def fresh_key(self, who: str) -> str:
        self.keys += 1
        return fake_key(f"{who}-key-{self.keys}")

    def new_key(self, who: str) -> dict:
        key = self.fresh_key(who)
        return {"key": key, "proof": key}                     # under the stub, the proof of a key is the key

    def options(self) -> list[tuple[str, str, dict]]:
        st, now, rng = self.st, self.now, self.rng
        out: list[tuple[str, str, dict]] = []
        active, masters = st.active(now), st.masters(now)
        if not active:
            return out
        one = lambda xs: rng.choice(sorted(xs))
        out.append(("work", one(active), {"ref": f"{URL}/{rng.randrange(1000)}"}))
        with_root = rng.random() < 0.5                         # a body that costs something is built only when it is chosen
        out.append(("witness", "tyler", lambda: checkpoint(st, **({"root": ledger.merkle_root(st.hashes)} if with_root else {}))))
        for name in CUSTODIANS:
            out.append(("custodian_alive", name, {}))
        if masters:
            free = [n for n in NEWCOMERS if not st.invited(n, now) and not st.reserved(n, now)
                    and ledger.may_return(st.members.get(n), now)]
            if free:
                who = one(free)
                out.append(("invite", one(masters), {"login": who, "github_id": gid(who)}))
            for cand in st.invitations:
                if st.invited(cand, now):
                    out.append(("petition", cand, lambda cand=cand: {"key": self.fresh_key(cand), "declaration_sha256": DECL}))
            for cand, p in st.petitions.items():
                if st.live(cand, now) and st.open_ballot_on("admission", cand) is None:
                    rest = [m for m in masters if m not in p["vouches"]]
                    if rest and len(p["vouches"]) < 2:
                        out.append(("vouch", one(rest), {"candidate": cand}))
                    elif p["vouches"]:
                        out.append(self.opening("admission", p["vouches"][0], {"candidate": cand}, "ballot_open:admission"))
            quiet = sum(b.result is None for b in st.ballots.values()) < 3
            if quiet and rng.random() < 0.5:
                target = one(active)
                out.append(self.opening("sanction", one(masters), {"member": target, "measure": rng.choice(("admonish", "admonish", "suspend", "expel", "reinstate"))}))
            if quiet and rng.random() < 0.5:
                out.append(self.opening("amendment", one(masters), {"path": rng.choice(("CONSTITUTION.md", "docs/governance/ROOMS.md")),
                                                                   "new_sha256": f"{rng.randrange(4):064x}"}))
            if quiet and rng.random() < 0.3:
                name = f"node{rng.randrange(2, 5)}"
                subject = {"action": "remove", "name": name} if name in st.witnesses else \
                    {"action": "add", "name": name, "key": fake_key(name), "proof": fake_key(name)}
                out.append(self.opening("witness", one(masters), subject))
            if rng.random() < 0.08:
                out.append(self.opening("custodian", one(masters), {"remove": rng.choice(CUSTODIANS)}))
        for b in st.ballots.values():
            if b.result is not None:
                continue
            if st.void_pending(b.id, now) is not None and rng.random() < 0.85:
                continue                                       # paused: the cast mostly waits (a vote would be refused)
            clock = st.ballot_time(b, now)
            if clock <= b.commit_until:
                for who in sorted(x for x in b.electors if x not in b.commits):
                    vote = "yes" if rng.random() < 0.9 else "no"
                    self.votes.setdefault((b.id, who), vote)
                    out.append(("ballot_commit", who, {"id": b.id, "commitment": commitment(b.id, who, self.votes[(b.id, who)], salt_of(who))}))
            elif clock <= b.reveal_until:
                for who in sorted(b.commits):
                    if who not in b.reveals or rng.random() < 0.05:              # now and then a second reveal
                        out.append(("ballot_reveal", who, {"id": b.id, "vote": self.votes.get((b.id, who), "yes"), "salt": salt_of(who)}))
            else:
                out.append(("ballot_close", rng.choice(("tyler", one(active))), {"id": b.id}))
        for m in st.members.values():
            ex = st.exams.get((m.login, m.degree + 1))
            if m.is_active(now) and m.degree < 3 and (ex is None or ex.ended(now, st)):   # again at once
                out.append(("exam_open", m.login, {"candidate": m.login, "degree": m.degree + 1, "work_ref": URL,
                                                   "beacon_round": drand_round(now) + BEACON_DELAY_ROUNDS}))
        for (cand, degree), ex in st.exams.items():
            if ex.lapsed or ex.consumed or ex.timed_out(now, st):
                continue
            if ex.examiners is None:
                out.append(("exam_draw", "tyler", {"candidate": cand, "degree": degree, "beacon": f"{ex.beacon_round + rng.randrange(3):064x}"}))
            elif ex.passed():
                out.append(self.opening("advancement", cand, {"member": cand, "degree": degree}, "ballot_open:advancement"))
            else:
                for who in ex.examiners:
                    if who not in ex.reports:
                        typ = "exam_recuse" if rng.random() < 0.15 else "exam_report"
                        body = {"candidate": cand, "degree": degree} | ({"verdict": "pass" if rng.random() < 0.9 else "fail"} if typ == "exam_report" else {})
                        out.append((typ, who, body))
        if rng.random() < 0.03:
            out.append(("depart", one(active), {}))
        if rng.random() < 0.06:
            who = one(active)
            out.append(("rekey", who, lambda: self.new_key(who)))
        self.custodian_options(out, active, masters)
        return out

    def opening(self, kind: str, by: str, subject: dict, label: str = "ballot_open") -> tuple[str, str, dict]:
        self.ballots += 1
        return label, by, {"id": f"{kind[:3]}-{self.ballots}", "kind": kind, "subject": subject}

    def custodian_options(self, out, active, masters) -> None:
        st, now, rng = self.st, self.now, self.rng
        one = lambda xs: rng.choice(sorted(xs))
        ground = rng.choice(ledger.GROUNDS[:4]) if rng.random() < 0.9 else ledger.NOTE_GROUND     # now and then the wrong one
        open_ballots = [b.id for b in st.ballots.values() if b.result is None]
        # A ballot is stayed, or its voiding posted, only before its reveal window opens: mostly those are offered.
        early = [b.id for b in st.ballots.values() if b.result is None and not ledger.sunset_ballot(b)
                 and st.ballot_time(b, now) < b.commit_until + ledger.REVEAL_GAP]
        passed = [b.id for b in st.ballots.values() if b.result == "passed" and b.kind in ("admission", "advancement", "witness")]
        # What an undo reaches: an admission, or an advancement the Sunset does not count, closed in the last 90 days.
        undoable = [b.id for b in st.ballots.values() if b.result == "passed" and b.kind in ledger.UNDO_KINDS
                    and not ledger.sunset_ballot(b) and now - b.closed <= ledger.UNDO_WINDOW_DAYS * DAY]
        if undoable and rng.random() < 0.9:
            passed = undoable
        acts = {"freeze_key": ({"login": one(active)}, "key_compromised"), "halt": ({}, "attack_in_progress"),
                "hold_room": ({"login": one(active)}, ground),
                "note": ({"action": "hide", "target": "issue:1", "rule": "ROOMS.md"},
                         ledger.NOTE_GROUND if rng.random() < 0.9 else ground),
                "freeze_witness": ({"name": one(st.witnesses)}, ground)}
        if open_ballots:
            targets = early if early and rng.random() < 0.9 else open_ballots
            acts |= {"stay": ({"ballot": one(targets)}, ground), "void_ballot": ({"id": one(targets)}, ground)}
        if passed:
            acts["undo_ballot"] = ({"id": one(passed)}, ground)
        for act, (target, why) in acts.items():               # each act is a kind of its own in the choice
            out.append((f"correction:{act}", rng.choice(CUSTODIANS),
                        {"act": act, "target": target, "ground": why, "reason_sha256": REASON}))
        for k in st.corrections.values():
            if st.pending(k, now):
                other = [x for x in CUSTODIANS if x not in k.signers]
                if other:
                    out.append(("correction_cosign", other[0], {"seq": k.seq}))
                if now >= st.notice_end(k):
                    out.append(("correction_apply", rng.choice(CUSTODIANS), {"seq": k.seq}))
            if (st.in_force(k, now) or st.pending(k, now)) and rng.random() < 0.12:
                out.append(("correction_withdraw", rng.choice(CUSTODIANS), {"seq": k.seq}))
            if k.class_ != "note" and k.void is None and masters and rng.random() < 0.06:
                out.append(("correction_object", one(masters), {"seq": k.seq}))
        for login in active:
            if st.frozen(login, now) is not None and st.recovering(login, now) is None and rng.random() < 0.6:
                out.append(("rekey_recover", login, lambda login=login: self.new_key(login)))
        for login, r in st.recoveries.items():
            if st.recovering(login, now) is None:
                continue
            rest = [m for m in masters if m != login and m not in r.cosigners]
            if rest and len(r.cosigners) < 3:
                out.append(("rekey_cosign", one(rest), {"login": login}))
            if now >= r.time + RECOVER_NOTICE_DAYS * DAY:
                out.append(("rekey_recover_apply", login, {}))
            if rng.random() < 0.3:
                out.append(("rekey_object", login, {}))
        live = [name for name in CUSTODIANS if st.custodian_status(st.custodians[name], now) == "live"]
        if self.late and live:                                # near the end of a run: a revoke key removes its custodian key
            name = rng.choice(live)
            out.append(("custodian_revoke", name, {"name": name}))

    def moments(self) -> list:
        """The next times at which something becomes possible, as things stand."""
        st, now = self.st, self.now
        out = []
        for b in st.ballots.values():
            if b.result is None:
                out += [st.ballot_due(b, b.commit_until + REVEAL_GAP) + SEC, st.ballot_due(b, b.reveal_until) + SEC]
        for ex in st.exams.values():
            if ex.examiners is None and not ex.lapsed:
                out.append(drand_time(ex.beacon_round))
        for k in st.corrections.values():
            if st.pending(k, now):
                out.append(st.notice_end(k))
        for login, r in st.recoveries.items():
            if st.recovering(login, now) is not None:
                out.append(r.time + RECOVER_NOTICE_DAYS * DAY)
        for m in st.members.values():
            if m.degree < 3 and m.status == "active":
                out.append(m.since[m.degree] + st.degree(m.degree + 1).wait_days * DAY)
        return sorted(t for t in out if now < t <= now + 45 * DAY)

    def busy(self) -> bool:
        """Somebody has a sealed vote to reveal right now: the cast does not let the three days run out on them
        (for a while: a stay or a freeze may be what keeps them from it)."""
        st, now = self.st, self.now
        return any(b.result is None and b.commit_until + REVEAL_GAP < st.ballot_time(b, now) <= b.reveal_until
                   and any(who not in b.reveals for who in b.commits) for b in st.ballots.values())

    def tick(self) -> None:
        rng, roll = self.rng, self.rng.random()
        if self.busy() and self.patience < 14:
            self.patience += 1
            if roll > 0.9:
                self.now += rng.choice((1, 60, 600)) * SEC
            return
        self.patience = 0
        if roll < 0.74:
            return
        if roll < 0.86:
            self.now += rng.choice((1, 60, 600, 3600, 3600, 6 * 3600, 86400)) * SEC
            return
        later = self.moments()
        if later:
            self.now = later[0] if rng.random() < 0.7 else rng.choice(later)
        else:
            self.now += rng.choice((1, 3, 8, 20, 31)) * DAY

    def offer(self) -> dict | None:
        """The next entry: something the state allows, and one time in seven bent into something else."""
        self.tick()
        options = self.options()
        if not options:
            return None
        kinds = sorted({o[0] for o in options})
        turnout = self.rng.random()                           # a vote that can be revealed or sealed now usually is
        if "ballot_reveal" in kinds and turnout < 0.6:
            kind = "ballot_reveal"
        elif "ballot_commit" in kinds and turnout < 0.75:
            kind = "ballot_commit"
        else:
            kind = self.rng.choices(kinds, [WEIGHT.get(k, 1) for k in kinds])[0]
        _, actor, body = self.rng.choice([o for o in options if o[0] == kind])
        typ, body = kind.split(":")[0], body() if callable(body) else body
        e = {"seq": self.st.seq + 1, "prev": self.st.head, "time": iso(self.now), "type": typ, "actor": actor, "body": body}
        bend = self.rng.random()
        if bend < 0.03:
            e["actor"] = self.rng.choice(SEVEN + NEWCOMERS + ["tyler", "warden", "nobody"])
        elif bend < 0.05:
            e["time"] = iso(self.now - self.rng.choice((1, 86400)) * SEC)
        elif bend < 0.07:
            e["body"] = body | {"extra": 1}
        elif bend < 0.08:
            e["prev"] = "0" * 64
        try:
            e["sig"] = _signer(self.st, e, self.now)[0]
        except Exception:
            e["sig"] = "nobody may sign this"
        if 0.08 <= bend < 0.10:
            e["sig"] = fake_key("somebody-else")
        return e


def ballot_record(b) -> dict:
    """Every stored fact of a ballot, copied: what must never change once the ballot is closed."""
    return ledger._plain(ledger._ballot_facts(b))


class Before:
    """What the properties need of the state before an entry, taken before the entry is applied (the state
    itself is changed in place: a refusal must leave it as it was, and that is one of the properties)."""

    def __init__(self, st: State, e: dict, digest: str):
        body = e.get("body") if isinstance(e.get("body"), dict) else {}
        self.digest = digest
        self.seq, self.head, self.entries = st.seq, st.head, len(st.hashes)
        self.members = {login: (m.since[1], m.degree, m.status) for login, m in st.members.items()}
        self.facts = custodian_tests.NeverGrant.facts(st) if e.get("type") in CORRECTION_TYPES else None
        b = st.ballots.get(body.get("id")) if isinstance(body.get("id"), str) else None
        self.electors = b.electors if b is not None else frozenset()
        k = st.corrections.get(body.get("seq")) if type(body.get("seq")) is int else None
        self.undoes = k.target["id"] if k is not None and k.act == "undo_ballot" else None


class Properties(unittest.TestCase):
    accepted: dict[str, int] = {}
    applied: dict[str, int] = {}
    refused = 0
    seconds = 0.0

    # -- the properties, each over one accepted entry: `pre` is what was noted before it, `st` the state after ----

    def hold(self, run: Run, pre: Before, st: State, e: dict, shadow: dict) -> None:
        typ, actor, body, now = e["type"], e["actor"], e["body"], run.now
        what = f"entry {e['seq']} ({typ} {body} by {actor} at {e['time']})"
        ballot = st.ballots.get(body.get("id")) if typ in ledger.BALLOT_TYPES else None

        # One member, one vote: no login commits or reveals twice, and a close counts the reveals of electors.
        if typ == "ballot_commit":
            self.assertNotIn(actor, shadow["commits"].setdefault(body["id"], {}), what)
            self.assertIn(actor, pre.electors, what)
            shadow["commits"][body["id"]][actor] = body["commitment"]
        if typ == "ballot_reveal":
            self.assertNotIn(actor, shadow["reveals"].setdefault(body["id"], {}), what)
            self.assertEqual(shadow["commits"][body["id"]][actor], commitment(body["id"], actor, body["vote"], body["salt"]), what)
            shadow["reveals"][body["id"]][actor] = body["vote"]
        for bid, b in st.ballots.items():
            self.assertEqual(dict(b.reveals), shadow["reveals"].get(bid, {}), what)
            self.assertEqual(dict(b.commits), shadow["commits"].get(bid, {}), what)
        if typ == "ballot_close":
            cast = list(shadow["reveals"].get(ballot.id, {}).values())        # every vote cast, whatever became of the elector
            yes, no = cast.count("yes"), cast.count("no")
            self.assertLessEqual(yes + no, len(ballot.electors), what)
            self.assertIn(ballot.result, ("passed", "failed", "lapsed"), what)
            n = ballot.quorum_base()                                          # the present electors
            self.assertLessEqual(n, len(ballot.electors), what)
            decided = ledger.quorate(yes + no, n) and not (ballot.frozen.get("master") and yes + no < 2)   # a Master sanction needs two votes
            self.assertEqual(ballot.result == "lapsed", not decided, what)
            if ballot.result == "passed":
                self.assertTrue(decide(ballot.kind, yes, no, n), what)
            if decided and not decide(ballot.kind, yes, no, n):
                self.assertEqual(ballot.result, "failed", what)

        # A closed ballot is a fact: nothing changes it but the application of its own undo. `shadow["closed"]`
        # holds a copy of every ballot as it stood when it ended (closed, or voided).
        undone = pre.undoes if typ == "correction_apply" else None
        now = ledger.ts(e["time"])
        for bid, was in list(shadow["closed"].items()):
            if bid in st.retired:                                 # it left the state (C14r), and only once no rule reads it
                self.assertNotIn(bid, st.ballots, what)
                self.assertGreater(now - shadow["ended"][bid], ledger.BALLOT_RETIRE_DAYS * DAY, what)
                del shadow["closed"][bid]
                shadow["retired"] += 1
                continue
            self.assertLessEqual(now - shadow["ended"][bid], ledger.BALLOT_RETIRE_DAYS * DAY, what)   # …and promptly
            is_ = ballot_record(st.ballots[bid])
            if bid == undone:
                self.assertEqual((was["result"], is_["result"], is_["corrected"]), ("passed", "undone", body["seq"]), what)
                shadow["closed"][bid] = was = is_                 # undone once, and from now on as final as any other
            self.assertEqual(was, is_, f"{what}: the closed ballot {bid} changed")
        for bid, b in st.ballots.items():
            if b.result is not None and bid not in shadow["closed"]:
                self.assertIn(typ, ("ballot_close", "correction_apply"), what)
                self.assertEqual(bid, body.get("id") if typ == "ballot_close" else st.corrections[body["seq"]].target["id"], what)
                shadow["closed"][bid] = ballot_record(b)
                shadow["ended"][bid] = now

        # Membership and degrees: by genesis, by a passed admission, by a passed advancement, one degree at a time.
        for login, m in st.members.items():
            admitted, degree, status = pre.members.get(login, (None, 0, ""))
            if admitted != m.since[1]:
                self.assertEqual(typ, "ballot_close", what)
                self.assertEqual((ballot.kind, ballot.subject["candidate"], ballot.result, m.degree), ("admission", login, "passed", 1), what)
                self.assertIn(status, ("", "departed", "expelled", "voided"), what)
                shadow["admitted"] += 1
            elif m.degree > degree:
                self.assertEqual(typ, "ballot_close", what)
                self.assertEqual((ballot.kind, ballot.subject["member"], ballot.result, m.degree),
                                 ("advancement", login, "passed", degree + 1), what)
                self.assertEqual(ballot.subject["degree"], m.degree, what)
                shadow["advanced"] += 1
        self.assertLessEqual(set(pre.members), set(st.members), what)           # and no record is ever removed

        # Corrections never grant (Landmark VI), with the checker of tests.test_custodian.
        if typ in CORRECTION_TYPES:
            custodian_tests.NeverGrant.never_granted(self, pre.facts, custodian_tests.NeverGrant.facts(st), what)

        # A custodian key that lapsed, was revoked or was removed never signs again. `shadow` follows each key
        # from the entries alone: its last sign of life, and the first second at which it was no longer live.
        for name, life in shadow["custodians"].items():
            if life["dead"] is None and now - life["alive"] > CUSTODIAN_SILENCE_DAYS * DAY:
                life["dead"] = life["alive"] + CUSTODIAN_SILENCE_DAYS * DAY + SEC
        if typ in CUSTODIAN_SIGNED:
            life = shadow["custodians"][actor]
            self.assertTrue(life["dead"] is None or now < life["dead"], f"{what}: the key of {actor} was dead since {life['dead']}")
            if typ == "custodian_alive":
                life["alive"] = now
            if typ == "custodian_revoke":
                life["dead"] = now
        if typ == "ballot_close" and ballot.kind == "custodian" and ballot.result == "passed":
            shadow["custodians"][ballot.subject["remove"]]["dead"] = now
        if st.sunset is not None:
            for life in shadow["custodians"].values():
                life["dead"] = st.sunset if life["dead"] is None else min(life["dead"], st.sunset)
        for name, life in shadow["custodians"].items():
            self.assertEqual(st.custodian_status(st.custodians[name], now) == "live", life["dead"] is None or now < life["dead"], what)

        # The Council never exceeds 33 seats, and no sponsor's budget exceeds 4.
        for t in (now, now + 400 * DAY):
            self.assertLessEqual(len(st.seats(t)), canon.COUNCIL_SEATS, what)
        for login in st.members:
            self.assertLessEqual(sponsorships(st, login, now), canon.SPONSOR_BUDGET_PER_YEAR, f"{what}: the budget of {login}")

    def run_one(self, seed: int) -> Run:
        run = Run(seed)
        shadow = {"commits": {}, "reveals": {}, "closed": {}, "ended": {}, "retired": 0, "admitted": 0, "advanced": 0,
                  "custodians": {name: {"alive": run.now, "dead": None} for name in CUSTODIANS}}
        cls = type(self)
        for step in range(STEPS):
            run.late = step > STEPS * 0.9
            e = run.offer()
            if e is None:
                break
            offered = ledger.canonical(e)
            pre = Before(run.st, e, run.digest)
            # Retirement is invisible to the rules (invariant 59): a state that keeps every ballot accepts the same.
            # Its digest is not this state's (it holds more ballots): a checkpoint is held to this state's digest.
            run.flat.digest = lambda d=pre.digest: d
            with mock.patch.object(ledger, "_retire", lambda st, now: None):
                try:
                    apply(run.flat, e, by_key)
                    kept = True
                except Invalid:
                    kept = False
            del run.flat.digest
            try:
                apply(run.st, e, by_key)
            except Invalid:
                self.assertFalse(kept, f"seed {seed}: a {e['type']} refused only because a ballot retired")
                st = run.st                                           # a refusal leaves no trace
                self.assertEqual(st.digest(), pre.digest, f"seed {seed}: a refused {e['type']} changed the state")
                self.assertEqual(ledger.state_digest(st), pre.digest, f"seed {seed}: a refused {e['type']}")
                self.assertEqual((st.seq, st.head, len(st.hashes)), (pre.seq, pre.head, pre.entries))
                self.assertEqual(ledger.canonical(e), offered)        # and no rule changes the entry itself
                cls.refused += 1
                continue
            self.assertEqual(ledger.canonical(e), offered)
            self.assertTrue(kept, f"seed {seed}: a {e['type']} accepted only because a ballot retired")
            run.digest = run.st.digest()
            self.assertNotEqual(run.digest, pre.digest)               # an accepted entry always moves the head
            # The digest of a state whose leaves were cached entry after entry is the digest from nothing.
            self.assertEqual(run.digest, ledger.state_digest(run.st), f"seed {seed}: incremental digest after {e['type']}")
            self.hold(run, pre, run.st, e, shadow)
            run.entries.append(e)
            run.digests.append(run.digest)
            cls.accepted[e["type"]] = cls.accepted.get(e["type"], 0) + 1
            if e["type"] == "correction":
                cls.accepted["act " + e["body"]["act"]] = cls.accepted.get("act " + e["body"]["act"], 0) + 1
            if e["type"] == "correction_apply":
                act = run.st.corrections[e["body"]["seq"]].act
                cls.applied[act] = cls.applied.get(act, 0) + 1
        for name in ("admitted", "advanced", "retired"):
            cls.accepted["member " + name] = cls.accepted.get("member " + name, 0) + shadow[name]   # "member retired": ballots
        return run

    def test_random_runs_hold_every_property(self):
        started = time.monotonic()
        for seed in SEEDS:
            with self.subTest(seed=seed):
                run = self.run_one(seed)
                # Replay determinism, for every prefix: one replay from nothing, compared entry by entry with the
                # digest each entry left when it was accepted among refusals, copies and questions about time.
                st = State()
                for i, e in enumerate(run.entries):
                    apply(st, e, by_key)
                    self.assertEqual(st.digest(), run.digests[i], f"seed {seed}: entry {i}")
                self.assertEqual(replay(run.entries, by_key).digest(), run.st.digest())
                self.assertEqual(st.document(), run.st.document())
        type(self).seconds = time.monotonic() - started

    def test_the_runs_were_not_vacuous(self):
        """Every kind of entry was accepted at least once, and so was each act of a correction; and many were
        refused. (The two entries of the Council lot are exercised by `Council` below: no random run reaches the
        32nd degree.)"""
        if not self.accepted:
            self.test_random_runs_hold_every_property()
        # `rekey_oppose` follows an open recovery, which no run asks: tests.test_bounds. The founder's claim
        # needs no live custodian key and the succession no active Master, which no run reaches: tests.test_liveness.
        missing = sorted(t for t in ALL_TYPES - {"genesis", "council_call", "council_draw", "rekey_oppose",
                                                 "custodian_claim", "custodian_claim_object", "custodian_claim_apply",
                                                 "succession_claim"}
                         if not self.accepted.get(t))
        self.assertEqual(missing, [], self.accepted)
        for act in ledger.ACTS:
            self.assertGreater(self.accepted.get("act " + act, 0), 0, (act, self.accepted))
        for act in ledger.NOTICED_ACTS:
            self.assertGreater(self.applied.get(act, 0), 0, (act, self.applied))
        for what in ("member admitted", "member advanced", "member retired"):
            self.assertGreater(self.accepted.get(what, 0), 0, (what, self.accepted))
        self.assertGreater(self.refused, 100)
        self.assertGreater(sum(n for t, n in self.accepted.items() if t in ALL_TYPES), 600)
        # The runs are linear in their length: well under a minute on an ordinary machine. The bound is loose on
        # purpose (a loaded machine is several times slower); it catches a run that stopped being linear.
        self.assertLess(self.seconds, SECONDS)


class Council(unittest.TestCase):
    """The lot of the Supreme Council over years of calls and draws: never more than 33 seats."""

    def test_the_council_never_exceeds_33_seats(self):
        for seed in SEEDS[:3]:
            rng = random.Random(seed)
            far = T0 + 9000 * DAY                              # nobody goes dormant in this run
            members = [Member(f"m{i:02d}", fake_key(f"m{i:02d}"), 32, {1: T0, 32: T0}, activity=[far]) for i in range(90)]
            st = hand_state(*members, witnesses={"tyler": fake_key("tyler")}, seq=0, head="1" * 64, time=T0, hashes=["1" * 64])
            now, calls, draws, most = T0 + 730 * DAY, 0, 0, 0
            for _ in range(160):
                now += rng.choice((0, 3600, 86400, 30 * 86400, 200 * 86400, 400 * 86400)) * SEC
                if st.council_call is None or ledger.council_lapsed(st, now):   # a call not drawn in 7 days lapsed
                    typ, actor, body = "council_call", rng.choice(members).login, {"beacon_round": drand_round(now) + BEACON_DELAY_ROUNDS}
                else:
                    now = max(now, drand_time(st.council_call)) if rng.random() < 0.8 else now
                    typ, actor, body = "council_draw", "tyler", {"beacon": f"{rng.randrange(10 ** 9):064x}"}
                e = {"seq": st.seq + 1, "prev": st.head, "time": iso(now), "type": typ, "actor": actor, "body": body}
                try:
                    e["sig"] = _signer(st, e, now)[0]
                except Invalid:
                    e["sig"] = "nobody"
                before = st.digest()
                try:
                    apply(st, e, by_key)
                except Invalid:
                    self.assertEqual(st.digest(), before)
                    continue
                calls, draws = calls + (typ == "council_call"), draws + (typ == "council_draw")
                for t in (now, now + DAY, now + 500 * DAY, now + canon.COUNCIL_TERM_DAYS * DAY):
                    self.assertLessEqual(len(st.seats(t)), canon.COUNCIL_SEATS, (seed, e))
                most = max(most, len(st.seats(now)))
                self.assertTrue(all(m.past_seats <= 1 for m in st.members.values()))
            self.assertEqual(most, canon.COUNCIL_SEATS, seed)                # the Council was full at some point…
            self.assertGreater(draws, 2, seed)                               # …and seats were filled again after they ended
            self.assertGreater(sum(m.past_seats for m in st.members.values()), canon.COUNCIL_SEATS, seed)


if __name__ == "__main__":
    unittest.main()
