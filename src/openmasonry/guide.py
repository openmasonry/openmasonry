"""The Guide: what is due for one person, right now.

In a lodge, a Deacon conducts the candidate through each step.
Here it is a pure function over the ledger state: given a login and a time, it
lists the person's next actions with the reason, the deadline and the exact `om`
command, so any agent in any harness can guide a member step by step.

Commands are argv lists, never shell strings: ledger text (ballot ids, logins,
URLs) can never become shell syntax. A step whose command needs something only
the person can give lists it in `needs` (appended in order) and, when the value
is constrained, in `choices`.

Beside the steps there are `notices`: what is in force and concerns the person
(a halt, a freeze of their key, a room hold, a recovery of their key and how the last one ended, a
correction they may object to, an applied correction or an undone admission that concerns them, an exam
of theirs that lapsed or timed out, a ballot on the custodian key they hold, a ballot of theirs that lapsed
and may be re-run, that they count as silent, and, for a Master Builder, another member's recovery that waits for co-signatures). A notice states what exists and what the person
may do. It is never a step, and the Guide never proposes an objection, the
co-signature of a recovery, the removal of a custodian or a correction, nor
whom to act against. `custodian_steps` lists the two duties of the holder of a
custodian key, and nothing else.

Pure: no I/O, no clock.
"""
from __future__ import annotations

import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from . import canon
from .ledger import (CUSTODIAN_SILENCE_DAYS, EXAM_EXPIRY_DAYS, EXAM_RETRY_DAYS, INVITE_EXPIRY_DAYS, OBJECTION_DAYS,
                     PETITION_EXPIRY_DAYS, RECOVER_COSIGNERS, RECOVER_NOTICE_DAYS, REJOIN_AFTER_DAYS,
                     EXPELLED_REPETITION_DAYS, REVEAL_GAP, Correction, State, closable, cosigners_needed, drand_time,
                     expired, iso, may_sponsor, objections_needed, sponsors_required, wait_ok, waited)
from .ledger import (DAY, LOT_DRAW_DAYS, RECOVER_FINAL_COSIGNERS, RECOVER_INTERVAL_DAYS, SPONSOR_WAIVE_DAYS,
                     SPONSOR_YEAR_DAYS, _stand_aside, cosigned, sponsorships, standing_cosigners)
from .ledger import (CLAIM_EXPIRY_DAYS, CLAIM_MASTERS, CLAIM_NOTICE_DAYS, SUCCESSION_DAYS, SUCCESSION_MASTERS, Invalid,
                     _claim_conditions)
from .ledger import (RECOVER_LOWERED_NOTICE_DAYS, RERUN_DAYS, SILENT_CALLS, SILENT_DAYS, UNSTOPPABLE_KINDS, full_call,
                     membership)
from .ledger import _council_pool, council_lapsed

DORMANCY_WARNING_DAYS = 300
# What the ledger still accepts while it is halted (`ledger.HALT_ALLOWED` and `ledger._unstoppable`), in words.
HALT_ACCEPTS = ("custodian entries, objections, departures, key replacements, the entries of a key recovery, witness "
                "checkpoints, amendment ballots and the ballot that removes a custodian")
REASONS = "ledger/reasons"          # where the public reason of a correction is archived (govern.REASONS_DIR)
ALIVE_WARNING_DAYS = 30             # a custodian is reminded of the sign of life when fewer days than this remain
OM = "bin\\om.cmd" if sys.platform == "win32" else "bin/om"      # the launcher, as this platform runs it
# Where a person who is not a member introduces themselves. Applications live outside the ledger.
APPLY_URL = f"https://github.com/{canon.CANONICAL_REPO}/issues/new?template=application.yml"


@dataclass(frozen=True)
class Step:
    action: str            # apply, join, find_sponsors, sponsor, open_admission, vote, reveal, close, draw, report,
                           # study, exam, advance, call_council, keep_alive, recover_apply, recuse, depart, wait;
                           # for a custodian key: alive,
                           # apply_correction. Inviting is never a step: whom a Master Builder invites is theirs
                           # alone to decide. Neither is objecting to a correction, co-signing a key recovery,
                           # removing a custodian or making a correction: those are stated in `notices`, or not at all.
    why: str               # one plain sentence for the person
    argv: list[str] = field(default_factory=list)      # exact command, without the person's own inputs
    needs: list[str] = field(default_factory=list)     # inputs the person supplies, appended in order
    choices: list[str] = field(default_factory=list)   # allowed values when the single need is constrained
    due_by: str | None = None      # act before this time
    opens_at: str | None = None    # possible only from this time
    public: bool = False   # True if approving it signs and publishes something

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Notice:
    """Something that exists and concerns the person, with what they may do about it. Never a step: nothing
    here is due, and nothing here is advice."""
    kind: str              # halt, frozen, room_hold, recovery, correction; recovery_stopped, recovery_voided,
                           # recovery_canceled, recovery_expired (the last recovery of the person's key ended);
                           # voided (their admission was undone), correction_applied, exam_lapsed, exam_timed_out,
                           # custodian_removal (a ballot on the custodian key they hold), recovery_cosign (a
                           # Master Builder: another member's recovery waits for co-signatures); custodian_claim (a
                           # founder may take up the Custodian office again), claim_pending (a claim of that office
                           # is pending: to its founder, and to the Masters who are not founders), succession (no
                           # active Master Builder is left: a succession claim exists or may be made),
                           # ballot_lapsed (a ballot the person opened, elects in or is about lapsed and may be
                           # re-run once), silent (the person counts as silent: called and never answered)
    why: str               # plain sentences for the person
    correction: int | None = None      # the seq of the correction, when the notice is about one
    until: str | None = None           # when it ends as things stand (a noticed act: when its notice ends and,
                                       # once it has, the last time at which it can be applied)
    concerns_you: bool = False         # it is aimed at the person, or at a ballot about them
    may_object: bool = False           # the person is a Master Builder who may object to it now
    object_until: str | None = None    # …until this time

    def to_dict(self) -> dict:
        return asdict(self)


def _iso(t: datetime | None) -> str | None:
    return iso(t) if t else None


def _about(kind: str, subject: dict) -> str:
    return {"admission": lambda s: f"admission of {s['candidate']}",
            "advancement": lambda s: f"advancement of {s['member']} to the {s['degree']}°",
            "amendment": lambda s: f"amendment of {s['path']}",
            "sanction": lambda s: f"{s['measure']} of {s['member']}",
            "witness": lambda s: f"{s['action']} witness {s['name']}",
            "custodian": lambda s: f"removal of the custodian key of {s['remove']}"}[kind](subject)


def can_sponsor(st: State, login: str, now: datetime) -> bool:
    """Whether the ledger would take an invitation or a vouch of `login` now, as far as the sponsor goes: a
    Master Builder (or a successor) under no ban, with room in the sponsorship budget (four at a time, `ledger._sponsor_checks`)."""
    return may_sponsor(st, login, now) and sponsorships(st, login, now) < canon.SPONSOR_BUDGET_PER_YEAR


def sponsorship_budget(st: State, login: str, now: datetime) -> dict:
    """What counts in the sponsor's sponsorship budget (four at a time, `ledger.sponsorships`), and when the first use that counts
    frees, as things stand: an admitted member one year after admission, a petition when it lapses, an
    invitation when it lapses (a petition under an open ballot frees when the ballot ends: no time is known)."""
    frees = [m.since[1] + SPONSOR_YEAR_DAYS * DAY for m in st.members.values()
             if login in m.sponsors and not expired(m.since[1], now, SPONSOR_YEAR_DAYS)]
    frees += [st.due(q["time"], PETITION_EXPIRY_DAYS * DAY) for cand, q in st.petitions.items()
              if login in q["vouches"] and st.live(cand, now) and st.open_ballot_on("admission", cand.casefold()) is None]
    invitations = [{"login": cand, "expires_at": iso(st.due(i["time"], INVITE_EXPIRY_DAYS * DAY))}
                   for cand, i in sorted(st.invitations.items()) if i["by"] == login and st.invited(cand, now)]
    frees += [st.due(st.invitations[i["login"]]["time"], INVITE_EXPIRY_DAYS * DAY) for i in invitations]
    return {"used": sponsorships(st, login, now), "allowed": canon.SPONSOR_BUDGET_PER_YEAR,
            "next_free_at": _iso(min(frees)) if frees else None, "invitations": invitations}


def recusal_replacement(st: State, ex, login: str, now: datetime) -> str | None:
    """Who would take `login`'s seat in the exam if they stood aside now: the ledger's own rule
    (`ledger._stand_aside`) run on a copy of the exam. None: nobody, and the exam would lapse."""
    from copy import copy
    trial = copy(ex)
    _stand_aside(st, trial, login, now)
    return None if trial.lapsed else next((x for x in trial.examiners if x not in ex.examiners), None)


def recusal_outcome(st: State, ex, login: str, now: datetime) -> str:
    """What happens, as things stand, if `login` steps aside from the exam: one sentence."""
    nxt = recusal_replacement(st, ex, login, now)
    if nxt is not None:
        return f"the next examiner in the lot's order ({nxt}) takes your place."
    return (f"nobody is left in the lot's order to take your place, so the exam lapses, with no penalty to "
            f"{ex.candidate}, who may open a new one at once.")


def recovery_opens(st: State, login: str) -> datetime | None:
    """From when the ledger takes a new key-recovery request of `login`, as far as the last one goes
    (`ledger._rekey_recover`): RECOVER_INTERVAL_DAYS after it was requested and after the old key stopped it.
    None when there was none."""
    r = st.recoveries.get(login)
    if r is None:
        return None
    return max(t + RECOVER_INTERVAL_DAYS * DAY for t in (r.time, r.objected) if t is not None)


def _ballot_status(st: State, b, now: datetime) -> str:
    """Where a ballot stands. Its windows are read where they fall as things stand (`State.ballot_due`): a
    halt or a stay moves them, and the stored deadlines never change."""
    stay = st.stayed(b.id, now)
    if stay is not None:
        return f"it is stayed until {_iso(st.span(stay)[1])} (correction {stay.seq}), and its windows are extended by that time"
    commit_until, reveal_until = st.ballot_due(b, b.commit_until), st.ballot_due(b, b.reveal_until)
    if now <= commit_until:
        return f"electors seal their votes until {_iso(commit_until)}"
    if now <= reveal_until:
        return f"votes are being revealed until {_iso(reveal_until)}"
    return "voting has ended and anyone can close it"


def _ballot_steps(st: State, b, login: str, now: datetime) -> list[Step]:
    """What one open ballot asks of the person now: to vote, to reveal, to close it, or to wait."""
    steps: list[Step] = []
    about = _about(b.kind, b.subject)
    commit_until, reveal_until = st.ballot_due(b, b.commit_until), st.ballot_due(b, b.reveal_until)
    stay = st.stayed(b.id, now)
    if stay is not None:
        if login in b.electors or (b.subject.get("member") or b.subject.get("candidate") or "").casefold() == login.casefold():
            steps.append(Step("wait", f"Ballot {b.id} ({about}): {_ballot_status(st, b, now)}.",
                              opens_at=_iso(st.span(stay)[1])))
        return steps
    void = st.void_pending(b.id, now)
    if void is not None:                        # the ledger takes no vote and no close while that correction is pending
        if login in b.electors or (b.subject.get("member") or b.subject.get("candidate") or "").casefold() == login.casefold():
            steps.append(Step("wait", f"Ballot {b.id} ({about}) is paused while the correction that would void it is "
                              f"pending (correction {void.seq}): it takes no vote and is not closed meanwhile.",
                              opens_at=_iso(st.apply_end(void))))
        return steps
    if closable(st, b, now):
        why = (f"Ballot {b.id} ({about}) has ended; any active member can close it to apply the result."
               if now > reveal_until else
               f"Every elector of ballot {b.id} ({about}) has revealed; any active member can close it now.")
        steps.append(Step("close", why, [OM, "close", b.id], public=True))
        return steps
    subject_login = b.subject.get("member") or b.subject.get("candidate")
    if subject_login and subject_login.casefold() == login.casefold():
        steps.append(Step("wait", f"Ballot {b.id} on the {about} concerns you: {_ballot_status(st, b, now)}."
                          + (" You may answer in writing before the vote (Constitution Art. X.3)."
                             if b.kind == "sanction" else ""), due_by=_iso(reveal_until)))
    if login not in b.electors:
        return steps
    if login not in b.commits and now <= commit_until:
        steps.append(Step("vote", f"You are an elector in ballot {b.id} ({about}). You choose Yes or No in the "
                          "approval dialog; your vote stays sealed until the reveal window.", [OM, "vote", b.id],
                          due_by=_iso(commit_until), public=True))
    elif login in b.commits and login not in b.reveals:
        opens = st.ballot_due(b, b.commit_until + REVEAL_GAP)
        if now < opens:
            steps.append(Step("wait", f"Reveal your vote in {b.id} once the reveal window opens.",
                              opens_at=_iso(opens)))
        else:
            steps.append(Step("reveal", f"Reveal your sealed vote in {b.id}; an unrevealed vote counts as abstention.",
                              [OM, "reveal", b.id], due_by=_iso(reveal_until), public=True))
    return steps


def next_steps(st: State, login: str, now: datetime) -> list[Step]:
    steps: list[Step] = []
    m = st.members.get(login)
    expiry = timedelta(days=PETITION_EXPIRY_DAYS)
    halt = st.halted(now)
    halted = ([Step("wait", f"The ledger is halted until {_iso(st.span(halt)[1])} (correction {halt.seq}). Meanwhile "
                    f"it accepts only {HALT_ACCEPTS}; other ballots, exams, invitations and petitions lose no time.",
                    opens_at=_iso(st.span(halt)[1]))] if halt else [])

    # -- not a member (yet, or any more) -----------------------------------
    if m is None or m.status in ("departed", "expelled", "voided"):
        p = st.petitions.get(login)
        ballot = st.open_ballot_on("admission", login.casefold())
        if halt:
            return halted
        if ballot:
            closes = st.ballot_due(ballot, ballot.reveal_until)
            steps.append(Step("wait", f"Your admission ballot {ballot.id}: {_ballot_status(st, ballot, now)}"
                              + (" (any member can close it)." if now > closes else "."), due_by=_iso(closes)))
        elif p and st.live(login, now):
            have, need = sum(may_sponsor(st, v, now) for v in p["vouches"]), sponsors_required(st, now, p)
            lapse = st.due(p["time"], expiry)
            others = [x for x in st.members if x != login and x not in p["vouches"] and can_sponsor(st, x, now)]
            waive = st.due(p["time"], timedelta(days=SPONSOR_WAIVE_DAYS))
            waives = (f" While fewer than {canon.FOUNDING_MASTERS} Master Builders are present (neither dormant nor "
                      f"silent), one sponsor suffices from {_iso(waive)}, as things stand."
                      if have >= 1 and need > 1 and len(st.present_masters(now)) < canon.FOUNDING_MASTERS and now < waive else "")
            if have >= need:
                why = f"Your petition has {have} of {need} sponsors; one of your sponsors can now open your admission ballot."
            elif others:
                why = (f"Your petition has {have} of {need} sponsors; ask another Master Builder who knows you to "
                       f"sponsor you (they run: bin/om vouch {login})." + waives)
            else:
                why = (f"Your petition has {have} of {need} sponsors, and nobody else can sponsor you now (every other "
                       "Master Builder already sponsors you, has used the sponsorship budget (four at a time) or is barred from "
                       f"sponsoring). Your petition waits; it lapses at {_iso(lapse)} unless enough sponsors come."
                       + waives)
            steps.append(Step("find_sponsors" if have < need and others else "wait", why, due_by=_iso(lapse)))
        else:
            failed = [b for b in st.ballots.values() if b.kind == "admission" and b.result == "failed"
                      and b.subject.get("candidate", "").casefold() == login.casefold()]
            if m is not None and m.status == "departed" and not waited(m.status_since, now, REJOIN_AFTER_DAYS):
                when = m.status_since + timedelta(days=REJOIN_AFTER_DAYS)
                steps.append(Step("wait", f"You left on {_iso(m.status_since)}; a Master Builder may invite you again "
                                  f"from {_iso(when)}; you would return at the 1st degree.", opens_at=_iso(when)))
            elif m is not None and m.status == "voided" and not waited(m.status_since, now, REJOIN_AFTER_DAYS):
                when = m.status_since + timedelta(days=REJOIN_AFTER_DAYS)
                steps.append(Step("wait", f"Your admission was undone on {_iso(m.status_since)}; a Master Builder may "
                                  f"invite you again from {_iso(when)}.", opens_at=_iso(when)))
            elif m is not None and m.status == "expelled" and not waited(m.status_since, now, EXPELLED_REPETITION_DAYS):
                when = m.status_since + timedelta(days=EXPELLED_REPETITION_DAYS)
                steps.append(Step("wait", f"You were expelled on {_iso(m.status_since)}; a Master Builder may invite "
                                  f"you again from {_iso(when)}.", opens_at=_iso(when)))
            elif st.invited(login, now):
                inv = st.invitations[login]
                steps.append(Step("join", f"{inv['by']} invited you. Read the Declaration; if you agree, petition for "
                                  "admission before the invitation lapses.", [OM, "join"],
                                  due_by=_iso(st.due(inv["time"], timedelta(days=INVITE_EXPIRY_DAYS))), public=True))
            else:
                reason = (f"Your invitation lapsed after {INVITE_EXPIRY_DAYS} days without a petition. "
                          if login in st.invitations else
                          "Your last admission ballot was not approved. " if failed else
                          "Your petition lapsed after 180 days without a ballot. " if p else "")
                steps.append(Step("apply", reason + "OpenMasonry admits by invitation. Introduce yourself in a public "
                                  f"issue ({APPLY_URL}); a Master Builder who comes to answer for you may invite you, "
                                  f"and then you petition with {OM} join."))
        return steps

    if not m.is_active(now):
        steps.append(Step("wait", f"You are suspended until {_iso(m.suspended_until)}.", opens_at=_iso(m.suspended_until)))
        steps.append(Step("depart", "You may still leave at any time, suspended or not (Landmark VII).",
                          [OM, "depart"], public=True))
        return steps

    frozen, recovery = st.frozen(login, now), st.recovering(login, now)
    if halt or frozen or recovery:
        may = (f"you may only replace your key ({OM} rekey), leave, vote in the ballots you are an elector of, take part "
               "in an amendment ballot or a ballot that removes a custodian, or stop a recovery of your key")
        if frozen:
            end = st.span(frozen)[1]
            under_way = ""
            if recovery:                           # the key stays frozen while the recovery is under way (FK4)
                end = max(end, st.recovery_end(recovery))
                under_way = (f" A recovery of your key is under way (entry {recovery.seq}): the key stays frozen until "
                             f"it is completed, stopped or expires ({_iso(st.recovery_end(recovery))} at the latest).")
            steps.append(Step("wait", f"Your key is frozen until {_iso(st.span(frozen)[1])} (correction {frozen.seq}, "
                              f"ground {frozen.ground}).{under_way} Meanwhile {may}.", opens_at=_iso(end)))
        elif recovery:
            until = _iso(st.recovery_end(recovery))
            steps.append(Step("wait", f"A recovery of your key is under way (entry {recovery.seq}); your present key "
                              f"stays frozen until it is completed, stopped or expires ({until} at the latest). "
                              f"Meanwhile {may}.", opens_at=until))
        if recovery and st.recovery_status(recovery, now) == "ready" and cosigned(st, recovery, recovery.cosigners, now):
            steps.append(Step("recover_apply", f"The recovery of your key (entry {recovery.seq}) has passed its notice "
                              "and has its co-signatures; if you asked for it, the new key completes it, and from "
                              "then on only the new key signs for you.", [OM, "recover-apply"],
                              due_by=_iso(st.recovery_end(recovery)),
                              opens_at=_iso(st.recovery_notice_end(recovery, now)), public=True))
        steps += halted
        # A frozen member still votes in every ballot (a freeze never changes who decides one), and closes none.
        for b in sorted(st.ballots.values(), key=lambda b: b.commit_until) if not halt else ():
            if b.result is None and b.kind not in UNSTOPPABLE_KINDS:
                steps += [x for x in _ballot_steps(st, b, login, now) if x.action in ("vote", "reveal")]
        # An amendment ballot and the ballot that removes a custodian go on through a halt and a freeze: their
        # steps are the usual ones.
        for b in sorted(st.ballots.values(), key=lambda b: b.commit_until):
            if b.result is None and b.kind in UNSTOPPABLE_KINDS:
                steps += _ballot_steps(st, b, login, now)
        steps.append(Step("depart", "You may still leave at any time (Landmark VII).", [OM, "depart"], public=True))
        return steps

    # -- ballots ------------------------------------------------------------
    for b in sorted(st.ballots.values(), key=lambda b: b.commit_until):
        if b.result is None:
            steps += _ballot_steps(st, b, login, now)

    # -- lots anyone can perform ----------------------------------------------
    for ex in st.exams.values():
        if ex.examiners is None and not ex.lapsed and now >= drand_time(ex.beacon_round) and not ex.expired(now, st):
            steps.append(Step("draw", f"The lot for {ex.candidate}'s {ex.degree}° examiners can be drawn now "
                              "(public drand beacon).", [OM, "draw", "--candidate", ex.candidate], public=True))
    if st.council_call is not None and now >= drand_time(st.council_call) and not council_lapsed(st, now):
        steps.append(Step("draw", "The Supreme Council lot can be drawn now.", [OM, "draw"], public=True))

    # -- examinations you must grade -----------------------------------------
    for ex in st.exams.values():
        if ex.examiners and login in ex.examiners and login not in ex.reports and not ex.lapsed \
                and not ex.expired(now, st):
            steps.append(Step("report", f"You were drawn to examine {ex.candidate} for the {ex.degree}°. Read their "
                              f"work ({ex.work_ref}) against the degree's requirement and give a reasoned verdict.",
                              [OM, "report", ex.candidate, str(ex.degree)], ["verdict"], ["pass", "fail"],
                              due_by=_iso(st.due(ex.opened, timedelta(days=EXAM_EXPIRY_DAYS))), public=True))
            if not (ex.consumed or ex.passed() or ex.failed(now, st)):
                steps.append(Step("recuse", f"If you have a conflict of interest with {ex.candidate}, or cannot judge, "
                                  f"step aside instead: {recusal_outcome(st, ex, login, now)}",
                                  [OM, "recuse", ex.candidate, str(ex.degree)],
                                  due_by=_iso(st.due(ex.opened, timedelta(days=EXAM_EXPIRY_DAYS))), public=True))

    # -- candidates (Master Builders) ------------------------------------------
    for cand, p in sorted(st.petitions.items()):
        if not st.live(cand, now) or st.open_ballot_on("admission", cand.casefold()):
            continue
        need = sponsors_required(st, now, p)
        valid = [v for v in p["vouches"] if may_sponsor(st, v, now)]
        if login in valid and len(valid) >= need:
            steps.append(Step("open_admission", f"{cand} has the {need} sponsor(s) required; as a sponsor you can "
                              "open the ballot.", [OM, "open", "admission", cand], due_by=_iso(st.due(p["time"], expiry)),
                              public=True))
        elif can_sponsor(st, login, now) and login not in p["vouches"] and len(valid) < need:
            steps.append(Step("sponsor", f"{cand} is looking for sponsors ({len(valid)} of {need}). Sponsor only "
                              "someone you know and vouch for.", [OM, "vouch", cand],
                              due_by=_iso(st.due(p["time"], expiry)), public=True))

    # -- your own path --------------------------------------------------------
    target = m.degree + 1
    if m.degree < 32:
        ex = st.exams.get((login, target))
        adv = st.open_ballot_on("advancement", login.casefold())
        if adv:
            pass                                    # already reported above as a ballot that concerns you
        elif ex and ex.examiners is None and not ex.ended(now, st):
            if now < drand_time(ex.beacon_round):
                steps.append(Step("wait", f"Your {target}° exam waits for the lot.",
                                  opens_at=_iso(drand_time(ex.beacon_round))))
        elif ex and ex.passed() and not ex.consumed:
            steps.append(Step("advance", f"You passed the {target}° examination; open your advancement ballot.",
                              [OM, "open", "advancement", login], public=True))
        elif ex and not ex.ended(now, st) and not ex.passed() and not ex.failed(now, st):
            steps.append(Step("wait", f"Your examiners ({', '.join(ex.examiners or ())}) are reading your work.",
                              due_by=_iso(st.due(ex.opened, timedelta(days=EXAM_EXPIRY_DAYS)))))
        else:
            d = st.degree(target)
            retry_at = st.due(ex.opened, timedelta(days=EXAM_RETRY_DAYS)) if ex and ex.failed(now, st) else None
            if retry_at and not st.waited(ex.opened, now, EXAM_RETRY_DAYS):
                steps.append(Step("study", f"Your {target}° attempt did not pass. Keep working on it; you may seek the "
                                  f"degree again from {_iso(retry_at)}. Required work: {d.work}.",
                                  [OM, "learn", str(target)], opens_at=_iso(retry_at)))
            elif wait_ok(st, m, target, now):
                steps.append(Step("exam", f"You may seek the {target}° ({d.title}). Required work: {d.work}.",
                                  [OM, "exam", str(target), "--work"], ["work_url"], public=True))
            else:
                ready = m.since[m.degree] + timedelta(days=d.wait_days)
                steps.append(Step("study", f"Study the {target}° ({d.title}; art: {d.art}). The waiting period ends on "
                                  f"{_iso(ready)}; prepare: {d.work}.", [OM, "learn", str(target)], opens_at=_iso(ready)))

    # -- the Supreme Council lot ---------------------------------------------
    # Any active member may call it (Constitution VIII.1), and a call that lapsed undrawn may be made again.
    if (st.council_call is None or council_lapsed(st, now)) and len(st.seats(now)) < canon.COUNCIL_SEATS:
        eligible = _council_pool(st, now)
        if eligible:
            steps.append(Step("call_council", f"{len(eligible)} member(s) are eligible for the Supreme Council and "
                              "seats are vacant; any member can call the lot.", [OM, "call-council"], public=True))

    last = m.last_active()
    if m.dormant(now):
        steps.append(Step("keep_alive", f"You are dormant: your last signed activity was at {_iso(last)}, more than "
                          f"{canon.DORMANT_AFTER_DAYS} days ago. Recording a work brings you back.", [OM, "work"],
                          ["work_url"], public=True))
    elif expired(last, now, DORMANCY_WARNING_DAYS):
        steps.append(Step("keep_alive", f"You will become dormant after {canon.DORMANT_AFTER_DAYS} days without signed "
                          "activity; recording a work keeps you in the electorate.", [OM, "work"], ["work_url"],
                          due_by=_iso(last + timedelta(days=canon.DORMANT_AFTER_DAYS)), public=True))
    return steps


# -- notices: what exists, and what the person may do ---------------------------------------------------

def _barred(st: State, c: Correction) -> set[str]:
    """Who never objects to the correction: its subject, and the members of the custodians who signed it."""
    return {c.subject, *(st.custodians[x].member for x in (c.by, *c.signers))}


def objectors(st: State, c: Correction, now: datetime) -> list[str]:
    """The Master Builders counted when the correction is objected to, as things stand: every active one
    except its subject and the members of the custodians who signed it (what `ledger._correction_object`
    counts; one fifth of them, and at least one, void the correction)."""
    barred = _barred(st, c)
    return [x for x in st.masters(now) if x not in barred]


def may_object(st: State, c: Correction, login: str, now: datetime) -> bool:
    """Whether the ledger would accept an objection of `login` to the correction at `now`."""
    m = st.members.get(login)
    return (m is not None and m.is_active(now) and m.degree >= canon.SPONSOR_MIN_DEGREE
            and c.void is None and login not in c.objections and login not in _barred(st, c)
            and not expired(c.applied or c.time, now, OBJECTION_DAYS) and not st.key_frozen(login, now))


def _target(c: Correction) -> str:
    about = ", ".join(str(v) for v in c.target.values())
    return f"{c.act}{' of ' + about if about else ''}"


def notices(st: State, login: str, now: datetime) -> list[Notice]:
    """What is in force or under notice and concerns the person, or that they may object to; a halt, which
    concerns everyone; and their own freeze, room hold and key recovery. It states; it never advises."""
    out: list[Notice] = []
    m = st.members.get(login)
    gone = m is not None and m.status in ("departed", "expelled", "voided")
    for c in st.corrections.values():
        status = st.correction_status(c, now)
        if status not in ("active", "pending", "ready"):
            continue
        mine = bool(c.subject) and c.subject == login
        if mine and gone and not (c.act == "freeze_key" and m.left):
            mine = False                    # a record that left: what was aimed at it no longer concerns anyone
        objecting = may_object(st, c, login, now)
        if not (mine or objecting or c.act == "halt"):
            continue
        by = f"correction {c.seq}, ground {c.ground}, by the custodian {c.by}"
        if c.class_ == "noticed":
            until = st.notice_end(c) if status == "pending" else st.apply_end(c)
            where = (f"is under notice until {_iso(until)}; then a custodian may apply it until {_iso(st.apply_end(c))}, "
                     "or it expires" if status == "pending" else
                     f"has passed its notice, and a custodian may apply it until {_iso(until)}")
        else:
            until = st.span(c)[1]
            where = f"is in force until {_iso(until)}"
        kind = ("halt" if c.act == "halt" else "frozen" if mine and c.act == "freeze_key" else
                "room_hold" if mine and c.act == "hold_room" else "correction")
        if kind == "halt":
            why = (f"The ledger is halted until {_iso(until)} ({by}). Meanwhile it accepts only {HALT_ACCEPTS}; other "
                   "ballots, exams, invitations and petitions lose no time.")
        elif kind == "frozen":
            why = (f"Your key is frozen until {_iso(until)} ({by}). Meanwhile you may only replace your key "
                   f"({OM} rekey --new-key PATH, if you still hold it), leave, vote in the ballots you are an elector "
                   "of, take part in an amendment ballot or a ballot that removes a custodian, or stop a recovery of "
                   "your key. ")
            alive, opens, last = st.recovery_alive(login, now), recovery_opens(st, login), st.recoveries.get(login)
            if alive is not None:
                why += f"A recovery of your key was requested already (entry {alive.seq})."
            elif opens is not None and now < opens:       # the ledger takes no new request before then
                why += (f"A new recovery of your key is accepted only from {_iso(opens)}: the last one (entry "
                        f"{last.seq}) was requested at {_iso(last.time)}"
                        + (f" and stopped by the key the ledger holds at {_iso(last.objected)}; the next one needs "
                           f"{RECOVER_FINAL_COSIGNERS} co-signers (or as many others as exist), and the old key cannot "
                           "stop it." if last.objected else "."))
            else:
                final = last is not None and last.objected is not None and last.admitted == membership(m)
                nominal = RECOVER_FINAL_COSIGNERS if final else RECOVER_COSIGNERS
                need = min(nominal, len([x for x in st.masters(now) if x != login]))
                days = RECOVER_LOWERED_NOTICE_DAYS if need < nominal else RECOVER_NOTICE_DAYS
                why += (f"If the key is lost or in other hands, you may ask to go on with a new one ({OM} recover "
                        f"--new-key PATH): as things stand {need} Master Builder(s) co-sign it and its notice is "
                        f"{days} days"
                        + (f" (fewer other Master Builders than {nominal} exist, so all of them are enough and the "
                           "notice is the longer one)" if need < nominal else "")
                        + ("; the old key cannot stop it." if final else "."))
        elif kind == "room_hold":
            why = (f"You are held out of the rooms until {_iso(until)} ({by}). Nothing else changes: you vote, sign "
                   "and advance as before.")
        else:
            why = f"A correction ({_target(c)}; {by}) {where}." + (" It concerns you." if mine else "")
        obj = None
        if objecting:
            obj = (c.applied or c.time) + timedelta(days=OBJECTION_DAYS)
            why += (f" As a Master Builder you may object to it until {_iso(obj)} ({OM} object {c.seq}); it has "
                    f"{len(c.objections)} of the {objections_needed(len(objectors(st, c, now)))} objection(s) that "
                    "would void it.")
        elif mine and kind != "halt":
            why += " You cannot object to a correction aimed at you; other Master Builders may."
        elif login in c.objections:
            why += " You objected to it."
        out.append(Notice(kind, why, c.seq, _iso(until), mine, objecting, _iso(obj)))
    rec = st.recovering(login, now) if m is not None else None
    if rec is not None:
        ready, last = st.recovery_notice_end(rec, now), st.recovery_end(rec)
        out.append(Notice("recovery",
                          f"A recovery of your key was requested (entry {rec.seq}). It has {len(rec.cosigners)} of the "
                          f"{cosigners_needed(st, rec, now)} co-signatures of Master Builders it needs, is under notice until "
                          f"{_iso(ready)} and expires at {_iso(last)}; the key the ledger holds stays frozen meanwhile. "
                          f"If you asked for it, the new key completes it from {_iso(ready)} ({OM} recover-apply). If "
                          f"you did not, the key the ledger holds stops it ({OM} recover-object).",
                          None, _iso(last), True))
    out += _recovery_ended(st, login, now) if m is not None and (not gone or m.left) else []
    out += _later_notices(st, login, m, now) if not (gone and m.status != "voided") else []
    out += _rerun_notices(st, login, now)
    out += _claim_notices(st, login, now)
    out += _silence_notices(st, m, now) if m is not None and m.is_active(now) else []
    return out


def _silence_notices(st: State, m, now: datetime) -> list[Notice]:
    """A member who counts as silent (`Member.silent`: called to SILENT_CALLS examinations or ballots in
    SILENT_DAYS, and answered none) is told so, what it changes, and what ends it: a revealed vote or a report,
    never a `work`."""
    if not m.silent(now):
        return []
    since = min(t for t in m.missed if not expired(t, now, SILENT_DAYS))
    until = since + timedelta(days=SILENT_DAYS)
    return [Notice("silent",
                   f"You count as silent: you were called to {SILENT_CALLS} examinations or ballots that ended in the "
                   f"last {SILENT_DAYS} days and answered none of them. You keep every vote, but you are not waited "
                   "for: you are not present for a succession (and your entries do not cancel a succession claim), "
                   "the examiner lot, an admission and an advancement leave you out, and a successor who is silent is no "
                   "successor. "
                   f"A work does not end it. One vote revealed in any ballot you are an elector of, or one report in "
                   f"an examination you were drawn for, ends it at once ({OM} vote, then {OM} reveal; or {OM} "
                   f"report); if no ballot is open, a Master Builder may open an amendment ballot and reveal a vote in it (a no: a ballot that fails changes nothing). "
                   f"Otherwise it ends by itself at {_iso(until)} unless you are called and miss again.",
                   None, _iso(until), True)]


# Who may open a ballot of each kind (section 6.4 of the SPEC), and so its re-run, in words.
OPENERS = {
    "admission": "a sponsor of the petition",
    "advancement": "the candidate or an examiner of the passed exam",
    "sanction": "an Arbiter (7°+), or any Master Builder while fewer than three active Arbiters exist, never the "
                "member it concerns",
    "amendment": "any active Master Builder",
    "witness": "any active Master Builder",
    "custodian": "any active Master Builder but the custodian's own member",
}


def _rerun_notices(st: State, login: str, now: datetime) -> list[Notice]:
    """A ballot that lapsed for want of quorum and may still be re-run (`ledger._rerun_of`: once, within
    RERUN_DAYS of its close, never a re-run itself): told to its opener, its electors and the person it is
    about. It states who may open the re-run and until when; whether anyone does is theirs to decide."""
    out: list[Notice] = []
    rerun = {b.rerun for b in st.ballots.values() if b.rerun}
    for b in st.ballots.values():
        if b.result != "lapsed" or b.rerun or b.id in rerun or b.closed is None or expired(b.closed, now, RERUN_DAYS) \
                or not full_call(b):         # a ballot that gave less than 7 days to commit is never re-run
            continue
        about = b.subject.get("member") or b.subject.get("candidate") or ""
        concerns = about.casefold() == login.casefold()
        if not (concerns or login == b.opened_by or login in b.electors):
            continue
        until = b.closed + timedelta(days=RERUN_DAYS)
        out.append(Notice("ballot_lapsed",
                          f"Ballot {b.id} ({_about(b.kind, b.subject)}) lapsed at {_iso(b.closed)} for want of quorum: "
                          f"it decided nothing and penalizes nobody. It may be re-run once, until {_iso(until)}, by a "
                          f"ballot of the same kind and subject ({OM} open {b.kind} ... --rerun {b.id}, with at least 7 "
                          f"days to commit), while the conditions of its kind still hold. Who may open it: "
                          f"{OPENERS[b.kind]}. The re-run does not wait again for the electors who did not vote in this "
                          "one, who keep their vote.", None, _iso(until), concerns))
    return out


def _claim_notices(st: State, login: str, now: datetime) -> list[Notice]:
    """The founder's fallback and the succession, stated as information and never as steps: a founder who may
    take up the Custodian office again (the ledger's own conditions, `_claim_conditions`), a pending claim (to
    its founder, and to the Master Builders who are not founders and may object to it), and, for a member below
    the 3rd degree where no active Master Builder is left, the succession claim that exists or may be made."""
    out: list[Notice] = []
    m = st.members.get(login)
    if m is None or not m.is_active(now):
        return out
    pending = st.claim_pending(now)
    if m.founder and pending is None and not st.key_frozen(login, now):
        try:
            _claim_conditions(st, login, now, st.seq + 1)
        except Invalid:
            pass
        else:
            out.append(Notice("custodian_claim",
                              f"No custodian key is live, the Sunset has not been reached and fewer than {CLAIM_MASTERS} "
                              "active Master Builders who are not founders exist: as a founder you may take up the "
                              "Custodian office again, with a new custodian key and a new revoke key, both new to the "
                              f"ledger ({OM} claim-custodian NAME --custodian-key PATH --revoke-key PATH). The claim is "
                              f"public for {CLAIM_NOTICE_DAYS} days of notice, during which one active Master Builder who "
                              "is not a founder can stop it; then you apply it yourself, not later than day "
                              f"{CLAIM_EXPIRY_DAYS}.", None, None, True))
    if pending is not None:
        c, status = pending, st.claim_status(pending, now)
        ready, last = c.time + timedelta(days=CLAIM_NOTICE_DAYS), c.time + timedelta(days=CLAIM_EXPIRY_DAYS)
        where = (f"is under notice until {_iso(ready)}; then it may be applied until {_iso(last)}, or it expires"
                 if status == "pending" else f"has passed its notice and may be applied until {_iso(last)}, or it expires")
        if c.founder == login:
            out.append(Notice("claim_pending", f"Your claim of the Custodian office as {c.name} (entry {c.seq}) {where}. "
                              f"You apply it yourself from {_iso(ready)} ({OM} apply-claim {c.seq}). Until then, one "
                              "objection of an active Master Builder who is not a founder voids it.",
                              None, _iso(ready if status == "pending" else last), True))
        elif not m.founder and m.degree >= canon.SPONSOR_MIN_DEGREE and not st.key_frozen(login, now):
            out.append(Notice("claim_pending", f"The founder {c.founder} claims the Custodian office as {c.name} (entry "
                              f"{c.seq}): the claim {where}. As a Master Builder who is not a founder you may object to "
                              f"it until it is applied, and at the latest until {_iso(last)} ({OM} object-claim "
                              f"{c.seq}); one objection voids it for good.",
                              None, _iso(last), False, True, _iso(last)))
    if m.degree < canon.SPONSOR_MIN_DEGREE and not st.masters(now):
        s, status = st.succession, st.succession_status(now)
        if status == "pending":
            force = s.time + timedelta(days=SUCCESSION_DAYS)
            why = (f"No active Master Builder is left. A succession claim was made by {s.by} at {_iso(s.time)} (entry "
                   f"{s.seq}): any entry a Master Builder signs before {_iso(force)} cancels it; after that it is in "
                   f"force until {SUCCESSION_MASTERS} active Master Builders exist.")
            until = _iso(force)
        elif status == "in_force":
            why = (f"No active Master Builder is left, and the succession claim of {s.by} (entry {s.seq}) is in force "
                   f"until {SUCCESSION_MASTERS} active Master Builders exist: the members of the highest degree present "
                   "stand in for Master Builders in the lot of examiners, the advancement electorate, invitations and "
                   "sponsorship, and in nothing else." + (" You are one of them." if login in st.successors(now) else ""))
            until = None
        else:
            why = ("No active Master Builder is left (every Master left, is suspended or is dormant). A member below "
                   f"the 3rd degree may claim the succession ({OM} claim-succession): any entry a Master Builder signs "
                   f"within {SUCCESSION_DAYS} days cancels it; after them, until {SUCCESSION_MASTERS} active Master "
                   "Builders exist, the members of the highest degree present may examine, elect an advancement, "
                   "invite and sponsor, and nothing else.")
            until = None
        out.append(Notice("succession", why, None, until, False))
    return out


def _recovery_ended(st: State, login: str, now: datetime) -> list[Notice]:
    """The last recovery of the person's key ended without being completed: stopped by the key the ledger
    holds, voided by oppositions, canceled with the freeze it followed, or expired. Told until a new
    request is accepted (`recovery_opens`)."""
    r = st.recoveries.get(login)
    status = st.recovery_status(r, now) if r is not None else None
    if status not in ("objected", "opposed", "canceled", "expired"):
        return []
    opens = recovery_opens(st, login)
    if now >= opens:
        return []
    head = f"The recovery of your key requested at {_iso(r.time)} (entry {r.seq})"
    kind, why = {
        "objected": ("recovery_stopped", f"{head} was stopped at {_iso(r.objected)} by the key the ledger holds for you."),
        "opposed": ("recovery_voided", f"{head} was voided at {_iso(r.void)} by the opposition of {len(r.opposed)} "
                                       "Master Builder(s)."),
        "canceled": ("recovery_canceled", f"{head} ended with the freeze it followed (correction {r.freeze}), which was "
                                            "withdrawn or voided, or with your earlier membership."),
        "expired": ("recovery_expired", f"{head} expired at {_iso(st.recovery_end(r))} without being completed."),
    }[status]
    why += (f" The key the ledger holds is unchanged. A new recovery request is accepted from {_iso(opens)}"
            + (f"; it needs {RECOVER_FINAL_COSIGNERS} co-signers (or as many others as exist), and the old key cannot "
               "stop it." if status == "objected" else "."))
    return [Notice(kind, why, None, _iso(opens), True)]


def _later_notices(st: State, login: str, m, now: datetime) -> list[Notice]:
    """An admission undone; a noticed correction applied that concerns the person (told for OBJECTION_DAYS);
    an exam of theirs that lapsed or timed out; a ballot that would remove a custodian key they hold; and, for
    a Master Builder, the recoveries of other members' keys that wait for co-signatures. It states."""
    out: list[Notice] = []
    for c in st.corrections.values():
        if c.class_ != "noticed" or st.noticed_status(c, now) != "applied":
            continue
        b = st.ballots.get(c.target.get("id"))
        about = (b.subject.get("member") or b.subject.get("candidate") or "") if b is not None else ""
        if login.casefold() not in (c.subject.casefold(), about.casefold()):
            continue
        reason = f"{REASONS}/{c.reason_sha256}.md"
        by = f"correction {c.seq}, ground {c.ground}, by the custodian {c.by}, applied at {_iso(c.applied)}"
        if m is not None and m.status == "voided" and c.act == "undo_ballot" and b is not None and b.kind == "admission":
            out.append(Notice("voided", f"Your admission was undone ({by}): it no longer counts, and your record is "
                              f"voided. The public reason is {reason}. A Master Builder may invite you again from "
                              f"{_iso(m.status_since + timedelta(days=REJOIN_AFTER_DAYS))}.", c.seq, None, True))
            continue
        until = c.applied + timedelta(days=OBJECTION_DAYS)
        if now > until:
            continue
        what = (f"ballot {b.id} ({_about(b.kind, b.subject)}) ended with no effect" if c.act == "void_ballot" else
                f"ballot {b.id} ({_about(b.kind, b.subject)}) was undone") if b is not None else _target(c)
        out.append(Notice("correction_applied", f"Correction {c.seq} was applied ({by}): {what}. The public reason "
                          f"is {reason}. Objections to it are still recorded until {_iso(until)}, and no longer "
                          "change it.", c.seq, _iso(until), True))
    if m is None or m.status in ("departed", "expelled", "voided"):
        return out
    ex = st.exams.get((login, m.degree + 1))
    if ex is not None and ex.ended(now, st):
        if ex.lapsed:
            cause = ("the advancement it supported was undone by a correction" if ex.consumed else
                     "an examiner stood aside (a recusal, a frozen key or an undone admission) and nobody was left "
                     "in the lot's order to take the seat" if ex.recused else "it no longer counts")
            out.append(Notice("exam_lapsed", f"Your {ex.degree}° exam lapsed: {cause}. It carries no penalty; you "
                              "may open a new one at once.", None, None, True))
        else:
            silent = ex.silent(now, st)
            cause = (f"its lot was not drawn within {LOT_DRAW_DAYS} days of its beacon round" if ex.examiners is None
                     else f"no majority verdict came within {EXAM_EXPIRY_DAYS} days"
                     + (f" ({', '.join(silent)} never reported, and the next lot leaves them out)" if silent else ""))
            out.append(Notice("exam_timed_out", f"Your {ex.degree}° exam timed out: {cause}. It carries no penalty; "
                              "you may open a new one at once.", None, None, True))
    for c in st.custodians.values():
        if c.member != login:
            continue
        for b in st.ballots.values():
            if b.result is None and b.kind == "custodian" and b.subject.get("remove") == c.name:
                out.append(Notice("custodian_removal", f"Ballot {b.id}, on the removal of the custodian key {c.name} "
                                  f"that you hold, is open: {_ballot_status(st, b, now)}.", None,
                                  _iso(st.ballot_due(b, b.reveal_until)), True))
    if m.is_active(now) and m.degree >= canon.SPONSOR_MIN_DEGREE:
        for r in st.recoveries.values():
            if r.login == login or st.recovery_status(r, now) not in ("requested", "pending", "ready"):
                continue
            have, need = len(standing_cosigners(st, r.cosigners, now)), cosigners_needed(st, r, now)
            if have >= need:
                continue
            why = (f"A recovery of the key of {r.login} (entry {r.seq}) has {have} of the {need} co-signatures of "
                   f"Master Builders it needs, until {_iso(st.recovery_end(r))}.")
            why += (" You co-signed it." if login in r.cosigners else " You opposed it." if login in r.opposed else
                    " Whether to co-sign it, or to leave it, is yours alone to decide.")
            out.append(Notice("recovery_cosign", why, None, _iso(st.recovery_end(r))))
    return out


def custodian_steps(st: State, name: str, now: datetime) -> list[Step]:
    """What is due for the holder of a live custodian key, and nothing else: the sign of life when its
    deadline is near, and the application of a noticed correction they signed, once it can be applied. Whether
    to correct, co-sign or withdraw anything is theirs alone to decide, and is never listed."""
    c = st.custodians.get(name)
    if c is None or st.custodian_status(c, now) != "live":
        return []
    steps: list[Step] = []
    deadline = c.alive + timedelta(days=CUSTODIAN_SILENCE_DAYS)
    if deadline - now < timedelta(days=ALIVE_WARNING_DAYS):
        steps.append(Step("alive", f"The custodian key {name} lapses for good without a sign of life by "
                          f"{_iso(deadline)} (the last was at {_iso(c.alive)}).", [OM, "alive", "--as", name],
                          due_by=_iso(deadline), public=True))
    for k in st.corrections.values():
        if k.class_ == "noticed" and name in k.signers and st.noticed_status(k, now) == "ready" \
                and len(st.live_signers(k, now)) >= st.custodian_threshold:
            steps.append(Step("apply_correction", f"Correction {k.seq} ({_target(k)}), which you signed, has passed "
                              f"its notice and has the {st.custodian_threshold} custodian signature(s) it needs. It "
                              "takes effect only if a custodian applies it in time.",
                              [OM, "apply-correction", str(k.seq), "--as", name], due_by=_iso(st.apply_end(k)),
                              public=True))
    return steps


# -- the door: the steps of a person who is not a member, once `om me` knows their key and application -----

def onboarding_steps(steps: list[Step], info: dict, login: str, asked: bool = True) -> list[Step]:
    """The steps of `next_steps` for a person who is not a member, with what `om me` found outside the ledger
    (`info`, the `onboarding` field of om.me/2: their key, whether GitHub lists it, their newest application).
    Pure: the I/O that fills `info` is the caller's. The `apply` step becomes `bin/om apply`, or a `wait` once
    they applied; a `setup` step comes first when their key is missing or not listed on GitHub."""
    key, app = info.get("key"), info.get("application")
    setup: list[Step] = []
    if key is None:                                # asked about a login by name: no key of theirs to look at
        pass
    elif not key.get("fingerprint"):
        setup.append(Step("setup", f"You have no signing key yet (om looked for {key.get('path')}). You need one only to "
                          "petition, once invited; set it up now or later.", [OM, "onboard", "--create-key"]))
    elif key.get("listed") is False:
        setup.append(Step("setup", f"Your key {key['fingerprint']} is not listed at https://github.com/{login}.keys: the "
                          "judge refuses a petition whose key is not listed there. Adding it asks you first.",
                          [OM, "onboard", "--upload"], public=True))
    out: list[Step] = []
    for s in steps:
        if s.action == "apply":
            reason = s.why.split("OpenMasonry admits by invitation.", 1)[0]
            if app and app.get("state", "open") == "open":      # a closed application: they may apply again
                out.append(Step("wait", f"{reason}You applied on {str(app.get('created_at') or '')[:10]} ({app.get('url')}). "
                                "An application gives no right to an invitation: a Master Builder who comes to answer for "
                                "you may invite you. Meanwhile you may take part in the public work."))
            else:
                out += setup
                setup = []
                out.append(Step("apply", ("Could not check GitHub for an earlier application of yours. "
                                          if asked and not info.get("application_checked") else "") + reason
                                + "OpenMasonry admits by invitation. Introduce yourself, in your own words, in a public "
                                f"application: write it in a file and publish it (you approve it in a dialog), or use the "
                                f"form at {APPLY_URL}. Membership is a public roll under the name OpenMasonry; adults "
                                "only; no personal data.", [OM, "apply", "--text"], ["FILE"], public=True))
        elif s.action == "join":
            due = s.due_by
            if setup and due:
                last = setup[-1]
                setup[-1] = Step(last.action, f"{last.why} Your invitation lapses at {due}.", last.argv, public=last.public,
                                 due_by=due)
            out += setup
            setup = []
            inv = s.why.split(" invited you.", 1)[0]
            out.append(Step("join", f"Invited by {inv} — join before {due}. Read the Declaration; if you agree, petition "
                            "for admission.", s.argv, due_by=due, public=True))
        else:
            out.append(s)
    return out
