"""`python -m openmasonry <command>` — the Tyler's toolbox.

  verify  [--ledger DIR] [--tree]        replay the ledger from genesis; exit 1 if invalid
                                         (the pinned verifier: the same as `python -m openmasonry.verify`)
                                         --tree: governed files must match ratified hashes
                                         --online: re-check drand beacons; --clock-since SEQ: fresh timestamps
                                         --pr-author LOGIN --since SEQ [--pr-author-id N]: entries from SEQ on
                                         are the PR author's (witness acts excepted), petition keys are listed on
                                         GitHub, invited logins and petitioners are the invited GitHub accounts
                                         on this repository's own ledger it also holds the canonical ledger against
                                         the head this clone verified earlier (ROLLBACK, BEHIND, FUTURE HEAD);
                                         --accept-genesis HASH: follow another genesis, or a fork, from now on
  state   [--ledger DIR] [--json]        print members, degrees, open ballots, witnesses, custodians and corrections
  corrections [--ledger DIR] [--json]    every correction (act, target, ground, reason digest, status, signers,
                                         objections and how many void it, notice, apply and lapse times), the
                                         custodians and their sign-of-life deadlines, the halt, key recoveries,
                                         the founders' claims of the Custodian office and the succession
  witnesses [--ledger DIR] [--json]      the named witnesses: key fingerprint, freeze, latest checkpoint
  rooms   [--ledger DIR] [--json]        the roll of every room as the ledger derives it (om.rooms/1)
  metrics [--ledger DIR] [--json]        the Observatory's numbers, aggregates only (om.metrics/1)
  timeline [--ledger DIR] [--json]       every entry as one described line (om.timeline/1)
  observatory --out DIR [--ledger DIR] [--rooms-actual FILE]
                                         write the Observatory: index.html, metrics.json, timeline.json, rooms.json
  append  TYPE --actor L --key K --body JSON [--time ISO] [--ledger DIR]
                                         sign and append one entry
  commit  BALLOT LOGIN VOTE SALT         print the commitment for a ballot vote
  arms    [--out DIR] [--member LOGIN]   regenerate the 33 degree arms, or print a member's personal arms
  docs                                   regenerate the degree catalog (docs/degrees/)
  digest  [--root DIR]                   print the @protocol digest (the pinned core: protocol.manifest)
  declaration                            print the Declaration's sha256 (what a petition commits to)
  proof   witness NAME --key K            sign the proof of possession a witness key needs (genesis, witness ballot)
  proof   founder LOGIN --github-id N --key K     …and the one the key of a founder after the first needs (genesis)
"""
from __future__ import annotations

import argparse
import os
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import canon, heraldry, verify
from .crypto import SigningError
from .ledger import (ACTS, CLAIM_EXPIRY_DAYS, CLAIM_NOTICE_DAYS, CUSTODIAN_SILENCE_DAYS, DAY, GROUNDS,
                     INVITE_EXPIRY_DAYS, NOTE_ACTIONS, OBJECTION_DAYS, SUCCESSION_DAYS,
                     Invalid, _checkpoint_facts, _plain, append_signed, commitment, cosigners_needed, entry_path,
                     founder_message, iso, load, objections_needed, replay, room_hold_until, strict_json, ts,
                     witness_message)
from .verify import DEFAULT_LEDGER


def witness_rows(st, now: datetime, entries: list[dict] | None = None) -> list[dict]:
    """The named witnesses: the fingerprint of each key, the freeze in force on it, and its latest checkpoint
    (its seq and time, read from `entries` when the caller has them; the state keeps only the time)."""
    from .actions import fingerprint
    last = {e["actor"]: e for e in entries or () if e["type"] == "witness"}
    return [{"name": name, "key_fingerprint": fingerprint(key),
             "frozen_until": iso(st.span(f)[1]) if (f := st.witness_frozen(name, now)) is not None else None,
             "last_checkpoint_seq": last[name]["seq"] if name in last else None,
             "last_checkpoint_time": (last[name]["time"] if name in last else
                                      iso(st.witness_marks[name]["time"]) if name in st.witness_marks else None)}
            for name, key in sorted(st.witnesses.items())]


def state_report(st, now: datetime, entries: list[dict] | None = None) -> dict:
    """The state as data (schema om.state/2). Never crashes on a pinned canon this clone lacks. The state keeps
    no checkpoint (only their count and hash chain): they are read from `entries`, when the caller has them."""
    from .ledger import CanonPending
    pending = st.canon_pending() if st.pins else None

    def title(n: int):
        try:
            return (st.degree if st.pins else (lambda k: canon.degrees()[k]))(n).title
        except CanonPending:
            return None
    iso_ = lambda t: iso(t) if t else None
    end_of = lambda c: st.span(c)[1] if c is not None else None
    rows = [{"login": m.login, "degree": m.degree, "title": title(m.degree),
             "founding_architect": m.founder, "github_id": m.github_id,
             "status": m.status, "dormant": m.dormant(now), "light": round(m.light(now), 2),
             "last_activity": iso_(m.last_active()),
             "frozen_until": iso_(end_of(st.frozen(m.login, now))), "room_hold_until": iso_(room_hold_until(st, m, now)),
             "recovering": st.recovering(m.login, now) is not None}
            for m in sorted(st.members.values(), key=lambda m: (-m.degree, m.login))]
    # The windows of a ballot are shown where they fall as things stand: a halt or a stay moves them, and
    # the stored deadlines never change (`State.ballot_due`).
    open_b = [{"id": b.id, "kind": b.kind, "subject": b.subject, "commit_until": iso(st.ballot_due(b, b.commit_until)),
               "reveal_until": iso(st.ballot_due(b, b.reveal_until)), "stayed_until": iso_(end_of(st.stayed(b.id, now)))}
              for b in st.ballots.values() if b.result is None]
    exams = [{"candidate": e.candidate, "degree": e.degree, "opened": iso_(e.opened), "work_ref": e.work_ref,
              "examiners": list(e.examiners) if e.examiners is not None else None,
              "reports": dict(e.reports), "passed": e.passed(), "lapsed": e.lapsed, "timed_out": e.timed_out(now, st)}
             for e in st.exams.values()]
    petitions = [{"login": l, "vouches": list(p["vouches"]), "time": iso_(p["time"]), "github_id": p["github_id"]}
                 for l, p in st.petitions.items()]
    invitations = [{"login": l, "by": i["by"], "github_id": i["github_id"], "time": iso(i["time"]),
                    "expires_at": iso(st.due(i["time"], INVITE_EXPIRY_DAYS * DAY))}
                   for l, i in st.invitations.items() if st.invited(l, now)]
    removal = lambda c: next((b.id for b in st.ballots.values()
                              if b.result is None and b.kind == "custodian" and b.subject["remove"] == c.name), None)
    custodians = [{"name": c.name, "member": c.member, "status": st.custodian_status(c, now), "last_alive": iso(c.alive),
                   "silence_deadline": iso(c.alive + CUSTODIAN_SILENCE_DAYS * DAY), "removal_ballot": removal(c),
                   "ended_at": None if st.custodian_status(c, now) == "live" else iso(st.custodian_end(c))}
                  for c in st.custodians.values()]
    # A noticed act shows its notice and the time in which it can be applied; `ends` is for an immediate act.
    noticed = lambda c: c.class_ == "noticed"
    corrections = [{"seq": c.seq, "by": c.by, "act": c.act, "class": c.class_, "target": c.target, "ground": c.ground,
                    "reason_sha256": c.reason_sha256, "time": iso(c.time), "status": st.correction_status(c, now),
                    "objections": list(c.objections), "ends": iso_(st.span(c)[1] if c.until is not None else None),
                    "signers": list(c.signers), "signers_needed": st.custodian_threshold if noticed(c) else None,
                    "notice_until": iso_(st.notice_end(c) if noticed(c) else None),
                    "apply_until": iso_(st.apply_end(c) if noticed(c) else None), "applied": iso_(c.applied)}
                   for c in st.corrections.values()]
    # A note is no correction record (it has no effect): the newest the state keeps are listed with them.
    corrections += [{"seq": n["seq"], "by": n["by"], "act": "note", "class": "note",
                     "target": {k: n[k] for k in ("action", "target", "rule")}, "ground": "moderation",
                     "reason_sha256": n["reason_sha256"], "time": iso(n["time"]), "status": "recorded",
                     "objections": [], "ends": None, "signers": [], "signers_needed": None, "notice_until": None,
                     "apply_until": None, "applied": None} for n in st.notes]
    corrections.sort(key=lambda k: k["seq"])
    recoveries = [{"login": r.login, "seq": r.seq, "time": iso(r.time), "status": st.recovery_status(r, now),
                   "cosigners": list(r.cosigners), "cosigners_needed": cosigners_needed(st, r, now), "freeze": r.freeze,
                   "notice_until": iso_(st.recovery_notice_end(r, now)),
                   "expires_at": iso(st.recovery_end(r, now))} for r in st.recoveries.values()]
    halt = st.halted(now)
    return {"schema": "om.state/2", "name": st.name, "head": st.head, "entries": st.seq + 1,
            "founding_phase": st.founding_phase(now), "masters": len(st.masters(now)), "canon_pending": pending,
            "members": rows, "open_ballots": open_b, "exams": exams, "invitations": invitations, "petitions": petitions,
            "checkpoints": [_plain(_checkpoint_facts(e["body"], e["actor"])) for e in entries or () if e["type"] == "witness"],
            "witnesses": witness_rows(st, now, entries),
            "custodians": custodians, "custodian_threshold": st.custodian_threshold,
            "sunset": iso_(st.sunset), "corrections": corrections, "recoveries": recoveries,
            "halt": {"halted": halt is not None, "correction": halt.seq if halt else None,
                     "since": iso_(halt.time if halt else None), "until": iso_(end_of(halt))}}


def _iso_or_none(t: datetime | None) -> str | None:
    return iso(t) if t else None


def claim_rows(st, now: datetime) -> list[dict]:
    """Every founder's claim of the Custodian office (SPEC §6.31 to §6.33), in the order of the entries."""
    return [{"seq": c.seq, "founder": c.founder, "name": c.name, "time": iso(c.time), "status": st.claim_status(c, now),
             "notice_until": iso(c.time + CLAIM_NOTICE_DAYS * DAY), "apply_until": iso(c.time + CLAIM_EXPIRY_DAYS * DAY),
             "objected": _iso_or_none(c.objected), "objector": c.objector or None,
             "applied": _iso_or_none(c.applied)}
            for c in st.claims.values()]


def succession_row(st, now: datetime) -> dict | None:
    """The succession claim (SPEC §6.34), if one was ever made: its status and, while it is in force, the
    successors."""
    s = st.succession
    if s is None:
        return None
    return {"seq": s.seq, "by": s.by, "time": iso(s.time), "status": st.succession_status(now),
            "in_force_from": iso(s.time + SUCCESSION_DAYS * DAY), "end": _iso_or_none(s.end),
            "canceled_by": s.canceled_by or None, "successors": st.successors(now)}


def corrections_report(st, now: datetime) -> dict:
    """Custodians, corrections and key recoveries as data (schema om.corrections/1): the rows of the state
    report, and for each correction where its public reason is archived, how many objections void it as
    things stand and until when one is accepted; then the founders' claims of the Custodian office and the
    succession."""
    from .guide import objectors
    rep = state_report(st, now)
    rows = []
    for row in rep["corrections"]:
        c = st.corrections.get(row["seq"])        # none for a note: it has no effect, and takes no objection
        rows.append(row | {
            "reason_file": f"ledger/reasons/{row['reason_sha256']}.md",
            "objections_needed": None if c is None else objections_needed(len(objectors(st, c, now))),
            "objection_until": None if c is None else iso((c.applied or c.time) + OBJECTION_DAYS * DAY)})
    return {"schema": "om.corrections/1", "name": st.name, "head": st.head, "entries": st.seq + 1, "time": iso(now),
            "custodians": rep["custodians"], "custodian_threshold": rep["custodian_threshold"], "sunset": rep["sunset"],
            "halt": rep["halt"], "corrections": rows,
            "recoveries": rep["recoveries"], "claims": claim_rows(st, now), "succession": succession_row(st, now)}


def _custodian_line(c: dict) -> str:
    if c["status"] != "live":                    # a key that is not live never signs again: no deadline is due
        return (f"custodian {c['name']} (member {c['member']}) {c['status']} since {c['ended_at']} · last sign of life "
                f"{c['last_alive']}")
    return (f"custodian {c['name']} (member {c['member']}) {c['status']} · last sign of life {c['last_alive']}, "
            f"due again by {c['silence_deadline']}"
            + (f" · removal ballot {c['removal_ballot']} is open" if c["removal_ballot"] else ""))


def _correction_line(k: dict) -> str:
    """One correction in words; the fields of om.corrections/1 are added when the row has them."""
    target = ", ".join(str(v) for v in k["target"].values())
    line = f"correction {k['seq']} by {k['by']}: {k['act']}{' ' + target if target else ''} [{k['ground']}] {k['status']}"
    if k["class"] == "noticed":
        line += (f" · notice until {k['notice_until']}, applied by {k['apply_until']} or never · signers "
                 f"{len(k['signers'])} of {k['signers_needed']}" + (f" · applied {k['applied']}" if k["applied"] else ""))
    elif k["ends"]:
        line += f" · {'until' if k['status'] == 'active' else 'ended'} {k['ends']}"
    if k["class"] != "note":
        line += f" · objections {len(k['objections'])}" + (
            f" of {k['objections_needed']} (accepted until {k['objection_until']})" if "objections_needed" in k else "")
    if "reason_file" in k:
        line += f" · reason {k['reason_sha256'][:12]}… ({k['reason_file']})"
    return line


def _recovery_line(r: dict) -> str:
    return (f"key recovery of {r['login']} {r['status']} · notice until {r['notice_until']}, expires "
            f"{r['expires_at']} · co-signers {len(r['cosigners'])}" + (f" of {r['cosigners_needed']}" if "cosigners_needed" in r else ""))


def _claim_line(c: dict) -> str:
    line = f"claim {c['seq']} of the Custodian office by the founder {c['founder']}, as {c['name']}: {c['status']}"
    if c["status"] in ("pending", "ready"):
        line += f" · notice until {c['notice_until']}, applied by {c['apply_until']} or never"
    if c["objected"]:
        line += f" · objected by {c['objector']} at {c['objected']}"
    if c["applied"]:
        line += f" · applied {c['applied']}"
    return line


def _succession_line(s: dict) -> str:
    line = f"succession claim {s['seq']} by {s['by']} at {s['time']}: {s['status'].replace('_', ' ')}"
    if s["status"] == "pending":
        line += f" · in force from {s['in_force_from']} unless a Master Builder signs an entry before"
    elif s["status"] == "in_force":
        line += " · successors " + (", ".join(s["successors"]) or "none present")
    elif s["status"] == "canceled":
        line += f" · canceled by {s['canceled_by']} at {s['end']}"
    elif s["status"] == "ended":
        line += f" · ended at {s['end']}"
    return line


def _halt_line(halt: dict) -> str:
    return f"HALTED until {halt['until']} (correction {halt['correction']})"


def _now(a) -> datetime:
    return ts(a.time) if getattr(a, "time", None) else datetime.now(timezone.utc)


EMPTY_LEDGER = "The ledger is empty: the fraternity has not been founded yet."
EMPTY_STATE = {"schema": "om.state/2", "name": "", "head": None, "entries": 0, "founding_phase": None, "masters": 0,
               "canon_pending": None, "members": [], "open_ballots": [], "exams": [], "invitations": [], "petitions": [],
               "checkpoints": [], "witnesses": [], "custodians": [], "custodian_threshold": 0, "sunset": None,
               "corrections": [], "recoveries": [],
               "halt": {"halted": False, "correction": None, "since": None, "until": None}}


def _witness_line(w: dict) -> str:
    return (f"witness {w['name']} key {w['key_fingerprint']} · "
            + (f"last checkpoint #{w['last_checkpoint_seq']} at {w['last_checkpoint_time']}"
               if w["last_checkpoint_seq"] is not None else
               f"last checkpoint at {w['last_checkpoint_time']}" if w["last_checkpoint_time"] else "no checkpoint yet")
            + (f" · frozen until {w['frozen_until']}" if w["frozen_until"] else ""))


def cmd_witnesses(a) -> int:
    """Read-only: the named witnesses, their keys, freezes and latest checkpoints (schema om.witnesses/1)."""
    try:
        entries = load(a.ledger)
        st = replay(entries) if entries else None
    except Invalid as err:
        print(f"INVALID — {err}")
        return 1
    now = _now(a)
    rows = witness_rows(st, now, entries) if st is not None else []
    if a.json:
        print(json.dumps({"schema": "om.witnesses/1", "name": st.name if st else "", "head": st.head if st else None,
                          "entries": len(entries), "time": iso(now), "witnesses": rows}, indent=2, ensure_ascii=False))
        return 0
    if st is None:
        print(EMPTY_LEDGER)
        return 0
    for w in rows:
        print(_witness_line(w))
    if not rows:
        print("No witness is named.")
    return 0


def cmd_state(a) -> int:
    try:
        entries = load(a.ledger)  # may raise Invalid too
        st = replay(entries)
    except Invalid as err:
        print(f"INVALID — {err}")
        return 1
    if not entries:
        print(json.dumps(EMPTY_STATE) if a.json else EMPTY_LEDGER)
        return 0
    rep = state_report(st, _now(a), entries)
    if a.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        return 0
    print(f"founding phase: {'yes' if rep['founding_phase'] else 'no'} · masters {rep['masters']}")
    if rep["canon_pending"]:
        print(f"canon text pending: canon/history/{rep['canon_pending']}.toml is not in this clone (git pull)")
    for r in rep["members"]:
        print(f"{r['degree']:>2}°  {r['login']:<24} {r['title'] or '(canon text pending)':<44}{' ✦' if r['founding_architect'] else '  '} {r['status']}{' (dormant)' if r['dormant'] else ''}  light={r['light']}")
    for b in rep["open_ballots"]:
        print(f"open ballot {b['id']} [{b['kind']}] {b['subject']}"
              + (f" · stayed until {b['stayed_until']}" if b["stayed_until"] else ""))
    for w in rep["witnesses"]:
        print(_witness_line(w))
    if rep["custodians"] or rep["corrections"]:
        live = [k for k in rep["corrections"] if k["status"] in ("active", "pending", "ready")]
        print(f"Custodians and corrections (a noticed correction needs {rep['custodian_threshold']} custodian key(s); "
              f"{len(rep['corrections'])} correction(s) so far, {len(live)} in force or pending: bin/om corrections)")
        for c in rep["custodians"]:
            print("  " + _custodian_line(c))
        for k in live:
            print("  " + _correction_line(k))
        for r in rep["recoveries"]:
            if r["status"] in ("pending", "ready"):
                print("  " + _recovery_line(r))
        if rep["halt"]["halted"]:
            print("  " + _halt_line(rep["halt"]))
    return 0


def cmd_corrections(a) -> int:
    """Read-only: every correction, the custodians, the halt, the key recoveries, the founders' claims of the
    Custodian office and the succession (schema om.corrections/1)."""
    try:
        entries = load(a.ledger)
        st = replay(entries) if entries else None
    except Invalid as err:
        print(f"INVALID — {err}")
        return 1
    if st is None:
        print(json.dumps({"schema": "om.corrections/1", "name": "", "head": None, "entries": 0, "time": iso(_now(a)),
                          "custodians": [], "custodian_threshold": 0, "sunset": None,
                          "halt": {"halted": False, "correction": None, "since": None, "until": None},
                          "corrections": [], "recoveries": [], "claims": [], "succession": None}) if a.json else
              "The ledger is empty: the fraternity has not been founded yet.")
        return 0
    rep = corrections_report(st, _now(a))
    if a.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        return 0
    if not rep["custodians"]:
        print("No custodian was named, at genesis or by a founder's claim, so no correction exists.")
    else:
        print(f"A noticed correction needs {rep['custodian_threshold']} custodian key(s)."
              + (f" The Sunset was reached at {rep['sunset']}: no custodian key signs any more." if rep["sunset"] else ""))
    for c in rep["custodians"]:
        print(_custodian_line(c))
    if rep["halt"]["halted"]:
        print(_halt_line(rep["halt"]))
    for k in rep["corrections"]:
        print(_correction_line(k))
    if rep["custodians"] and not rep["corrections"]:
        print("No correction was ever made.")
    for r in rep["recoveries"]:
        print(_recovery_line(r))
    for c in rep["claims"]:
        print(_claim_line(c))
    if rep["succession"]:
        print(_succession_line(rep["succession"]))
    return 0


def cmd_append(a) -> int:
    try:
        entries = load(a.ledger)
        st = replay(entries) if entries else None
        try:
            body = strict_json(a.body)
        except ValueError as err:
            raise Invalid(len(entries), f"--body is not strict JSON: {err}") from None
        e, _ = append_signed(a.ledger, st, a.type, a.actor, body, Path(a.key), a.time)
    except Invalid as err:
        print(f"REFUSED — {err}")
        return 1
    except SigningError as err:
        print(f"NOT SIGNED — {err}")
        return 1
    print(entry_path(a.ledger, e["seq"]))
    return 0


CANDIDATE_WARNING = (
    "--candidate-root DIR executes the Python code of DIR on this machine, as you, with everything you can read: "
    "your SSH keys, your ssh-agent, ~/.config/openmasonry. The code of a pull request is untrusted until it is "
    "ratified. Rely on the `candidate` job of the pull request's checks (tyler.yml), or run this in a disposable "
    "container or VM that holds no keys (docs/operations/RECOVERY.md, section 6).")


def cmd_verify(a) -> int:
    """The pinned verifier, and then the rule of a client (SPEC §9.7) on this repository's own ledger."""
    from .actions import verify_client
    if a.candidate_root is not None and not a.i_trust_this_code:
        print(CANDIDATE_WARNING, file=sys.stderr)
        answer = ""
        if sys.stdin is not None and sys.stdin.isatty():
            try:
                answer = input(f"Run the code of {a.candidate_root} here? Type RUN to run it: ")
            except EOFError:
                answer = ""
        if answer.strip() != "RUN":
            print("Nothing was run. In a disposable sandbox with no keys, pass --i-trust-this-code.", file=sys.stderr)
            return 2
    return verify.show(a, verify_client(a, verify.verify_report(a)))


def cmd_declaration(a) -> int:
    print(canon.declaration_digest())
    return 0


def cmd_digest(a) -> int:
    from .govern import protocol_digest
    print(protocol_digest(a.root))
    return 0


def cmd_proof(a) -> int:
    """Sign a proof of possession with the key itself: of a witness key (for the genesis, or for the ballot
    that adds the witness) or of the key of a founder after the first (for the genesis). A proof is not an
    entry: it binds a key to one name and can be used for nothing else."""
    from .actions import bare_public_key
    from .crypto import sign
    key = Path(a.key).expanduser()
    public = bare_public_key(key)
    if a.what == "founder":
        if a.github_id is None:
            print("a founder's proof needs --github-id N (the numeric GitHub user id of that founder)")
            return 1
        message = founder_message(a.name, a.github_id, public)
    else:
        message = witness_message(a.name, public)
    try:
        proof = sign(message, key)
    except SigningError as err:
        print(f"NOT SIGNED — {err}")
        return 1
    if a.out:
        a.out.write_text(proof, encoding="utf-8")
        print(a.out)
    else:
        print(proof, end="")
    return 0


def cmd_commit(a) -> int:
    print(commitment(a.ballot, a.login, a.vote, a.salt))
    return 0


def cmd_arms(a) -> int:
    if a.member:
        st = replay(load(a.ledger))
        m = st.members.get(a.member)
        if m is None:
            print(f"no member {a.member}")
            return 1
        print(heraldry.personal_arms(m.login, m.key, m.degree))
        return 0
    a.out.mkdir(parents=True, exist_ok=True)
    for d in canon.degrees().values():
        (a.out / f"degree-{d.n:02d}.svg").write_text(heraldry.degree_arms(d), encoding="utf-8")
    print(f"wrote 33 coats of arms to {a.out}")
    return 0


def _from_admission(n: int) -> str:
    """How long degree n takes from admission at the least: the waiting periods are exact, the time an examination
    and a ballot take is not (it depends on the beacon, the examiners and the voters)."""
    if n == 1:
        return "conferred by the admission ballot itself"
    lot = " and the lot of the Supreme Council" if n == 33 else ""
    return (f"at least {canon.minimum_days_to(n):,} days of waiting, plus the time the examinations and ballots on the way "
            f"take{lot}")


def cmd_docs(a) -> int:
    out = canon.ROOT / "docs" / "degrees"
    out.mkdir(parents=True, exist_ok=True)
    hs = canon.houses()
    index = ["# The 33 Degrees", "",
             "> Generated from [`canon/degrees.toml`](../../canon/degrees.toml) by `python -m openmasonry docs`. Do not edit by hand.", "",
             "| ° | Arms | Title | House | Virtue | Historical reference (AASR-SJ) | Days of waiting from admission (at least) |",
             "|---:|:---:|---|---|---|---|---:|"]
    for d in canon.degrees().values():
        days = canon.minimum_days_to(d.n)
        index.append(f"| {d.n} | <img src=\"../../heraldry/degree-{d.n:02d}.svg\" width=\"28\"> | "
                     f"[{d.title}](degree-{d.n:02d}.md) | {hs[d.house].name} | {d.virtue} | {d.historical} | {days:,} |")
        (out / f"degree-{d.n:02d}.md").write_text("\n".join([
            f"# {d.n}°: {d.title}", "",
            f"<img src=\"../../heraldry/degree-{d.n:02d}.svg\" width=\"120\" align=\"right\">", "",
            f"**House:** {hs[d.house].name}. {hs[d.house].purpose}  ",
            f"**Historical reference:** {d.historical} *(Ancient and Accepted Scottish Rite, Southern Jurisdiction; reference only; no ritual reproduced)*  ",
            f"**Virtue:** {d.virtue}  ",
            f"**Art (field of study):** {d.art}", "",
            f"> {d.lesson}", "",
            "## Requirements", "",
            f"- **Masterwork:** {d.work}",
            f"- **Waiting period:** at least {d.wait_days:,} days in the previous degree",
            f"- **Examiners drawn by lot:** {d.examiners}",
            f"- **From admission:** {_from_admission(d.n)}", "",
            "## What it unlocks", "", f"{d.unlocks}. Degrees grant *duties and eligibility*, never extra votes (Landmark IV).", "",
            "## Blazon", "", f"Field *{d.tincture}*, ordinary *{d.ordinary}*, charge *{d.charge}* (rendered as the degree numeral).", "",
            f"← [{d.n - 1}°](degree-{d.n - 1:02d}.md) · [all degrees](README.md) · [{d.n + 1}°](degree-{d.n + 1:02d}.md) →"
            if 1 < d.n < 33 else "[all degrees](README.md)", ""]), encoding="utf-8")
    (out / "README.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    return 0


def _member_parsers(sub) -> dict:
    """Member commands. Acts are only DRAFTED; `approve` asks the person in a system dialog."""
    from . import actions as A
    table = {}

    def add(name, fn, help_, drafts=True):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
        p.add_argument("--login", help="GitHub login (default: gh api user, or $OM_LOGIN)")
        p.add_argument("--key", help="private key path (default: $OM_KEY, the key `om rekey` configured, "
                                     "or ~/.ssh/id_ed25519)")
        p.add_argument("--time", help=argparse.SUPPRESS)
        if drafts:
            p.add_argument("--json", action="store_true", help="print the draft as JSON (schema om.draft/1)")
        table[name] = fn
        return p

    def add_custodian(name, fn, help_):
        """A custodian act: no member login and no member key; the custodian key signs it."""
        p = sub.add_parser(name, help=help_)
        p.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
        p.add_argument("--as", dest="as_custodian", metavar="NAME", help="the custodian who signs (default: $OM_CUSTODIAN)")
        p.add_argument("--custodian-key", metavar="PATH",
                       help="private key file (or hardware-key handle) of that custodian key (default: "
                            "$OM_CUSTODIAN_KEY); never a member key")
        p.add_argument("--time", help=argparse.SUPPRESS)
        p.add_argument("--json", action="store_true", help="print the draft as JSON (schema om.draft/1)")
        table[name] = fn
        return p

    add("doctor", A.cmd_doctor, "check tools, login, key and ledger", drafts=False)
    from . import onboard as O
    ob = add("onboard", O.cmd_onboard, "for a person who is not a member yet: check this computer, the GitHub login "
             "and the member key, set the key up, and say the next step (schema om.onboard/1)", drafts=False)
    ob.add_argument("--json", action="store_true", help="print the report as JSON (schema om.onboard/1)")
    ob.add_argument("--create-key", nargs="?", const=True, default=None, metavar="PATH",
                    help="create the member key in your own terminal (default ~/.ssh/openmasonry_ed25519) and record it")
    ob.add_argument("--hardware", action="store_true", help="with --create-key: a key held by a FIDO2 token (ed25519-sk)")
    ob.add_argument("--use-key", metavar="PATH", help="record an existing Ed25519 key as the member key (non-members)")
    ob.add_argument("--upload", action="store_true",
                    help="add the public key to your GitHub account as an authentication key, after you approve")
    ap_ = add("apply", O.cmd_apply, "publish your own application text as a public issue, after you approve it in a "
              "dialog (schema om.apply/1)", drafts=False)
    ap_.add_argument("--text", required=True, metavar="FILE", help="your application, in your own words (UTF-8, at "
                                                                   "most 1,200 characters, no personal data)")
    ap_.add_argument("--check", action="store_true", help="validate and print the exact title and body; open nothing")
    ap_.add_argument("--web", action="store_true", help="open the application form in the browser, prefilled, instead")
    ap_.add_argument("--json", action="store_true", help="print the result as JSON (schema om.apply/1)")
    me = add("me", A.cmd_me, "your degree and everything that is due for you now", drafts=False)
    me.add_argument("--json", action="store_true")
    me.add_argument("--as", dest="as_custodian", metavar="NAME",
                    help="also show what is due for the custodian key you hold (default: $OM_CUSTODIAN)")
    ln = add("learn", A.cmd_learn, "read the page of a degree (default: your next one)", drafts=False)
    ln.add_argument("degree", type=int, nargs="?")
    ln.add_argument("--json", action="store_true")
    ru = add("rules", A.cmd_rules, "find the sources of a rule (Landmarks, whitepaper, Constitution)", drafts=False)
    ru.add_argument("topic")
    ru.add_argument("--json", action="store_true")
    g = add("genesis", A.cmd_genesis, "draft the Founding Ceremony (entry 0)")
    g.add_argument("--name", default="OpenMasonry: Open Lodge No. 1", help="1 to 120 printable ASCII characters")
    g.add_argument("--github-id", type=int, metavar="N", help="your numeric GitHub user id (default: asked of GitHub with gh)")
    g.add_argument("--cofounder", action="append", metavar="LOGIN:KEY.pub[:ID]",
                   help="a cofounder, with their numeric GitHub user id (default: asked of GitHub with gh)")
    g.add_argument("--witness", action="append", metavar="NAME:KEY.pub")
    g.add_argument("--cofounder-proof", action="append", metavar="LOGIN:FILE",
                   help="the proof of possession of a cofounder's key, made by that cofounder with "
                        "`om proof founder LOGIN --github-id N --key PATH` (not needed when the private key is beside "
                        "KEY.pub: it then signs the proof when you approve)")
    g.add_argument("--witness-proof", action="append", metavar="NAME:FILE",
                   help="the proof of possession of a witness key, made with `om proof witness NAME --key PATH` (not "
                        "needed when the private key is beside KEY.pub)")
    g.add_argument("--custodian", action="append", metavar="NAME:KEY.pub:REVOKE.pub[:MEMBER_LOGIN]",
                   help="a custodian: its key, its revoke key and the founder it is linked to (default: you). Both "
                        "private keys (KEY, REVOKE) must be present when you approve: each signs its proof of "
                        "possession. Afterwards store the revoke key separately and offline")
    g.add_argument("--custodian-threshold", type=int, metavar="N",
                   help="custodian keys a noticed correction needs (default: 1 with one custodian; required with more)")
    iv = add("invite", A.cmd_invite, "draft an invitation to petition (3°+); you become the first sponsor")
    iv.add_argument("candidate", metavar="LOGIN", help="the GitHub login of the person you answer for")
    iv.add_argument("--github-id", type=int, metavar="N", help="their numeric GitHub user id (default: asked of GitHub with gh)")
    add("join", A.cmd_join, "draft your petition for admission, once a Master Builder has invited you (shows the Declaration)")
    add("vouch", A.cmd_vouch, "draft a sponsorship of an invited candidate, as a further sponsor (3°+)").add_argument("candidate")
    v = add("vote", A.cmd_vote, "draft a sealed vote; you choose Yes or No in the approval dialog")
    v.add_argument("ballot")
    add("reveal", A.cmd_reveal, "draft the reveal of your sealed vote").add_argument("ballot")
    o = add("open", A.cmd_open, "draft the opening of a ballot")
    o.add_argument("kind", choices=["admission", "advancement", "sanction", "amendment", "witness", "custodian"])
    o.add_argument("target", help="candidate, member, file path, witness name, or the custodian whose key the ballot "
                                  "would remove")
    o.add_argument("--measure", help="sanction measure, or witness action add|remove")
    o.add_argument("--sha256", help="new text hash for an amendment")
    o.add_argument("--witness-key", help="public key of a new witness (ssh-ed25519 or sk-ssh-ed25519@openssh.com)")
    o.add_argument("--witness-proof", metavar="FILE",
                   help="the proof that the new witness holds that key: the file `om proof witness NAME --key PATH` wrote")
    o.add_argument("--id", help="ballot id (default: generated)")
    o.add_argument("--rerun", metavar="ID", help="re-run the ballot ID, which lapsed for want of quorum: the same kind "
                                                 "and subject, once, within 30 days of its close")
    o.add_argument("--commit-days", type=int, metavar="N", help="amendment only: days to commit (2 to 30; default 7; "
                                                                "a re-run at least 7)")
    o.add_argument("--reveal-days", type=int, metavar="N", help="amendment only: days to reveal (1 to 14; default 3)")
    add("close", A.cmd_close, "draft the closing of an ended ballot").add_argument("ballot")
    e = add("exam", A.cmd_exam, "draft the opening of your examination for the next degree")
    e.add_argument("degree", type=int)
    e.add_argument("--work", required=True, help="URL of your masterwork")
    r = add("report", A.cmd_report, "draft your verdict as a drawn examiner")
    r.add_argument("candidate")
    r.add_argument("degree", type=int)
    r.add_argument("verdict", choices=["pass", "fail"])
    r.add_argument("--reason", help="URL of your published, reasoned verdict")
    rc = add("recuse", A.cmd_recuse, "draft your recusal as a drawn examiner (conflict of interest)")
    rc.add_argument("candidate")
    rc.add_argument("degree", type=int)
    d = add("draw", A.cmd_draw, "draft a due lot (examiners or Supreme Council) with the public drand beacon")
    d.add_argument("--candidate")
    d.add_argument("--beacon", metavar="HEX", help="the round's randomness (64 lowercase hex), fetched elsewhere when "
                                                   "this machine cannot reach the public drand beacon")
    add("call-council", A.cmd_call_council, "draft the call of the Supreme Council lot")
    add("work", A.cmd_work, "draft the record of a masterwork or contribution").add_argument("ref")
    add("depart", A.cmd_depart, "draft your departure (a Master Builder may invite you again after 90 days)")
    rk = add("rekey", A.cmd_rekey, "draft the replacement of your signing key (the current key signs, the new key proves)")
    rk.add_argument("--new-key", required=True, metavar="PATH",
                    help="private key file (or hardware-key handle) of the new key; PATH.pub must exist")
    ob = add("object", A.cmd_object, "draft your objection to a correction (3°+); enough objections void it")
    ob.add_argument("seq", type=int, metavar="SEQ", help="the entry number of the correction")
    rv = add("recover", A.cmd_recover, "draft the request to go on with a NEW key for a lost or stolen one, after a "
                                       "freeze or with none in force (the new key signs; after a freeze min(2, others) "
                                       "Master Builders co-sign and 21 days of notice run, without one min(3, others) "
                                       "and 30 days; one that follows a recovery the old key stopped needs min(3, "
                                       "others); 45 days whenever fewer co-signers are enough)")
    rv.add_argument("--new-key", required=True, metavar="PATH",
                    help="private key file (or hardware-key handle) of the new key; PATH.pub must exist")
    add("recover-cosign", A.cmd_recover_cosign, "draft your co-signature of a member's key recovery (3°+)"
        ).add_argument("member", metavar="LOGIN")
    add("recover-oppose", A.cmd_recover_oppose, "draft your opposition to an open key recovery, one asked with no "
                                                "freeze in force (3°+); enough oppositions void it").add_argument("member", metavar="LOGIN")
    add("recover-object", A.cmd_recover_object, "draft the stop of a recovery of your key, signed with the key the "
                                                "ledger holds (--key PATH if it is not the configured one)")
    ra = add("recover-apply", A.cmd_recover_apply, "draft the completion of your key recovery, after its notice")
    ra.add_argument("--new-key", metavar="PATH", help="the new key of the recovery (default: the one `om recover` used "
                                                      "on this machine)")
    cl = add("claim-custodian", A.cmd_claim_custodian, "FOUNDER: draft a claim of the Custodian office where no "
                                                       "custodian key is live (30 days of notice; applied by day 60)")
    cl.add_argument("name", metavar="NAME", help="the custodian's name: a login nobody holds")
    cl.add_argument("--custodian-key", required=True, metavar="PATH",
                    help="private key file of the new custodian key; PATH.pub must exist")
    cl.add_argument("--revoke-key", required=True, metavar="PATH",
                    help="private key file of the new revoke key; PATH.pub must exist. Both private keys sign their "
                         "proof of possession when you approve; afterwards store the revoke key separately and offline")
    add("object-claim", A.cmd_object_claim, "draft your objection to a pending claim of the Custodian office (3°+, not "
                                            "a founder); one objection voids it"
        ).add_argument("seq", type=int, metavar="SEQ", help="the entry number of the claim")
    add("apply-claim", A.cmd_apply_claim, "FOUNDER: draft the application of your claim of the Custodian office, after "
                                          "its 30 days of notice"
        ).add_argument("seq", type=int, metavar="SEQ", help="the entry number of the claim")
    add("claim-succession", A.cmd_claim_succession, "draft a succession claim (below the 3rd degree, where no active "
                                                    "Master Builder is left)")
    co = add_custodian("correct", A.cmd_correct, "CUSTODIAN: draft a correction (one act, one ground, a public reason)")
    co.add_argument("act", choices=sorted(ACTS))
    co.add_argument("--ground", choices=GROUNDS, help="required unless the act takes one ground only (freeze_key, halt)")
    co.add_argument("--reason", required=True, metavar="FILE",
                    help="the public reason: a UTF-8 text of at most 64 KiB, published as ledger/reasons/<sha256>.md "
                         "in the same pull request as the entry")
    co.add_argument("--login", dest="target_login", metavar="LOGIN", help="freeze_key, hold_room: the member")
    co.add_argument("--name", dest="target_name", metavar="NAME", help="freeze_witness: the witness")
    co.add_argument("--ballot", dest="target_ballot", metavar="ID", help="stay, void_ballot, undo_ballot: the ballot")
    co.add_argument("--action", dest="target_action", choices=NOTE_ACTIONS, help="note: what was done outside the ledger")
    co.add_argument("--target", dest="target_target", metavar="WHAT", help="note: what it touched (a thread, an account)")
    co.add_argument("--rule", dest="target_rule", metavar="RULE", help="note: the published rule it applied")
    for name, fn, help_ in (("cosign-correction", A.cmd_cosign_correction, "CUSTODIAN: draft your co-signature of a pending noticed correction"),
                            ("apply-correction", A.cmd_apply_correction, "CUSTODIAN: draft the application of a noticed correction, after its notice"),
                            ("withdraw-correction", A.cmd_withdraw_correction, "CUSTODIAN: draft the withdrawal of a correction in force or pending")):
        add_custodian(name, fn, help_).add_argument("seq", type=int, metavar="SEQ", help="the entry number of the correction")
    add_custodian("alive", A.cmd_alive, "CUSTODIAN: draft the sign of life that keeps your custodian key from lapsing")
    rc2 = sub.add_parser("revoke-custodian", help="draft the removal of a custodian key, signed with its revoke key")
    rc2.add_argument("name", metavar="NAME")
    rc2.add_argument("--revoke-key", required=True, metavar="PATH", help="private key file of the custodian's revoke key")
    rc2.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    rc2.add_argument("--time", help=argparse.SUPPRESS)
    rc2.add_argument("--json", action="store_true", help="print the draft as JSON (schema om.draft/1)")
    table["revoke-custodian"] = A.cmd_revoke_custodian
    ap = add("approve", A.cmd_approve, "the PERSON approves a draft in a system dialog; signs it and opens the PR")
    ap.add_argument("digest")
    ap.add_argument("--no-submit", action="store_true", help="sign locally only; publish later with `submit`")
    ap.add_argument("--test-vote", choices=["Yes", "No"], help=argparse.SUPPRESS)
    add("drafts", A.cmd_drafts, "list pending drafts")
    add("discard", A.cmd_discard, "discard a pending draft").add_argument("digest")
    pe = add("pending", A.cmd_pending, "your signed entries still waiting for their pull request")
    pe.add_argument("--drop", type=int, metavar="SEQ", help="forget an abandoned entry (and free its vote)")
    pe.add_argument("--rebase", type=int, nargs="?", const=-1, metavar="SEQ",
                    help="re-draft a stale entry (it lost its seq) on top of the ledger; approve it again")
    pe.add_argument("--publish", type=int, metavar="SEQ",
                    help="publish a signed entry whose push or pull request failed: push its branch again and open "
                         "the pull request (asks the person)")
    al = add("alarm", A.cmd_alarm, "open a public issue on the canonical repository (asks the person)")
    al.add_argument("title")
    al.add_argument("body")
    add("submit", A.cmd_submit, "publish signed entries kept local with --no-submit (asks the person)")
    return table


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):      # UTF-8 also into a pipe (Windows writes a code page there)
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower().replace("-", "") != "utf8":
            stream.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(prog="openmasonry", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    vp = sub.add_parser("verify")
    verify.add_arguments(vp)                            # the pinned verifier's own flags, and one of the client's
    vp.add_argument("--i-trust-this-code", action="store_true",
                    help="with --candidate-root: run the code of that tree without asking. It runs as you, with your "
                         "keys in reach: use it only in a disposable sandbox or VM that holds no keys")
    vp.add_argument("--accept-genesis", metavar="HASH",
                    help="follow the canonical ledger as it stands from now on, though it starts from another genesis "
                         "than this clone verified before, or no longer holds the head it verified (a fork): HASH is "
                         "the entry hash of its genesis. The person decides this, never an agent")
    for name in ("state", "corrections", "witnesses", "append"):
        s = sub.add_parser(name)
        s.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
        if name in ("state", "corrections", "witnesses"):
            s.add_argument("--json", action="store_true")
            s.add_argument("--time", help=argparse.SUPPRESS)      # read the ledger as of this time (tests)
        if name == "append":
            s.add_argument("type")
            s.add_argument("--actor", required=True)
            s.add_argument("--key", required=True)
            s.add_argument("--body", default="{}")
            s.add_argument("--time")
    for name in ("rooms", "metrics", "timeline", "observatory"):
        s = sub.add_parser(name)
        s.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
        s.add_argument("--time", help=argparse.SUPPRESS)      # read the ledger as of this time (tests)
        if name == "observatory":
            s.add_argument("--out", type=Path, required=True, metavar="DIR")
            s.add_argument("--rooms-actual", type=Path, metavar="FILE",
                           help="the access GitHub grants (om.rooms-actual/1), compared with the derived roll")
        else:
            s.add_argument("--json", action="store_true")
    c = sub.add_parser("commit")
    for f in ("ballot", "login", "vote", "salt"):
        c.add_argument(f)
    ar = sub.add_parser("arms")
    ar.add_argument("--out", type=Path, default=canon.ROOT / "heraldry")
    ar.add_argument("--member", help="print the personal coat of arms (SVG) of a member instead")
    ar.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    sub.add_parser("docs")
    pf = sub.add_parser("proof", help="sign the proof of possession of a witness key, or of a cofounder's key")
    pf.add_argument("what", choices=["witness", "founder"])
    pf.add_argument("name", metavar="NAME", help="the witness name, or the cofounder's GitHub login")
    pf.add_argument("--key", required=True, metavar="PATH", help="private key file (or hardware-key handle); PATH.pub must exist")
    pf.add_argument("--github-id", type=int, metavar="N", help="founder: their numeric GitHub user id")
    pf.add_argument("--out", type=Path, metavar="FILE", help="write the proof to FILE instead of printing it")
    sub.add_parser("declaration", help="print the sha256 a petition must commit to")
    dg = sub.add_parser("digest", help="print the @protocol digest (for genesis and protocol amendments)")
    dg.add_argument("--root", type=Path, default=None)
    members = _member_parsers(sub)
    a = p.parse_args(argv)
    from .actions import UserError
    try:
        if a.cmd in members:
            return members[a.cmd](a)
        return _tools(a)
    except UserError as err:
        print(json.dumps({"error": str(err)}) if getattr(a, "json", False) else f"✘ {err}")
        return 1
    except Invalid as err:
        print(f"INVALID — {err}")
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted; nothing was signed")
        return 130
    except Exception as err:                 # never a raw traceback for a person; OM_DEBUG=1 shows it
        if os.environ.get("OM_DEBUG"):
            raise
        print(f"✘ unexpected error: {err!r} (run with OM_DEBUG=1 for details)")
        return 1


def _tools(a) -> int:
    if a.cmd in ("rooms", "metrics", "timeline", "observatory"):
        from . import observatory
        return getattr(observatory, f"cmd_{a.cmd}")(a)
    return {"verify": cmd_verify, "state": cmd_state, "corrections": cmd_corrections, "witnesses": cmd_witnesses,
            "append": cmd_append, "commit": cmd_commit,
            "arms": cmd_arms, "docs": cmd_docs, "digest": cmd_digest, "declaration": cmd_declaration,
            "proof": cmd_proof}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
