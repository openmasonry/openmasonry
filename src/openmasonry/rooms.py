"""The rooms rule (SPEC section 15): who reads which room, derived from the ledger, and the plan that makes
the organization's teams match it.

Pure: no clock, no network, no file. Replay never reads this module and no verdict depends on it; it is
pinned because it is a rule (who is let in), not because the judge runs it. `om rooms` prints its roll and
the published sync program (`ops/rooms/sync.py`) applies its plan.

- `room_access(st, now)`: every member whose standing is active (a served suspension counts as active)
  and who is not under a room hold, with their degree. Dormant members keep their access.
- `readers(access)`: room k is read by every member of degree k or higher.
- `sync_plan(...)`: the ordered actions that make GitHub match `access`. People are matched by their
  numeric GitHub id, never by login, so a login renamed and taken by someone else never enters a room.
"""
from __future__ import annotations

from datetime import datetime

from .ledger import CUSTODIAN_SIGNED, State, fold, room_held, ts

ROOMS = 33                         # one room, one team and one private repository per degree
OPS = ("remove", "cancel", "move", "invite", "hold")   # the order of a plan; `hold` performs nothing


def team(n: int) -> str:
    """The slug of the team (and the name of the room repository) of degree `n`."""
    if not (type(n) is int and 1 <= n <= ROOMS):
        raise ValueError(f"no room for degree {n!r}")
    return f"degree-{n:02d}"


def team_degree(slug: str) -> int | None:
    """The degree of a team slug `degree-NN`, or None when the slug is not one of the 33 room teams."""
    if type(slug) is str and len(slug) == 9 and slug.startswith("degree-") and slug[7:].isdigit():
        n = int(slug[7:])
        if 1 <= n <= ROOMS and team(n) == slug:
            return n
    return None


def room_access(st: State, now: datetime) -> dict[str, int]:
    """login -> degree for every member who reads rooms at `now` (rooms 1 to that degree)."""
    return {m.login: m.degree for m in sorted(st.members.values(), key=lambda m: m.login)
            if m.standing(now) == "active" and not room_held(st, m, now)}


def readers(access: dict[str, int]) -> dict[int, list[str]]:
    """room -> the sorted logins that read it: room k is read by every member of degree k or higher."""
    return {k: sorted(login for login, d in access.items() if d >= k) for k in range(1, ROOMS + 1)}


def github_ids(st: State) -> dict[str, int]:
    """login -> the numeric GitHub user id the ledger records for each member (0 when none is recorded)."""
    return {m.login: m.github_id for m in st.members.values()}


def last_signed(st: State, entries: list[dict]) -> dict[str, datetime]:
    """login -> the time of the latest entry the member signed (custodian entries are not a member's)."""
    out: dict[str, datetime] = {}
    for e in entries:
        if e["actor"] in st.members and e["type"] not in CUSTODIAN_SIGNED:
            out[e["actor"]] = ts(e["time"])
    return out


def _protected(protected) -> tuple[set[int], set[str]]:
    ids = {p for p in protected if type(p) is int}
    logins = {fold(p) for p in protected if type(p) is str}
    return ids, logins


def sync_plan(desired: dict[str, int], actual: dict[int, dict], pending: list[dict], history: dict[int, dict],
              protected, github_ids: dict[str, int], signed: dict[str, datetime] | None = None) -> list[dict]:
    """The ordered actions that make the organization match `desired` (`room_access`).

    - `actual`: github id -> {"login": current GitHub login, "teams": [degrees of the room teams it is in],
      "member": in the organization}. Everyone in the organization or in a room team.
    - `pending`: the open invitations to the organization, each {"invitation": its id, "id": the github id
      it was sent to (None when the sync program did not send it), "login", "role"}.
    - `history`: github id -> {"failed_at": datetime, "reason": text}: the latest invitation that was
      declined, expired or failed.
    - `protected`: logins (str) and github ids (int) never touched: owners, applications, the custodian account.
    - `github_ids`: login -> github id, from the ledger.
    - `signed`: login -> the time of the member's latest signed entry (`last_signed`). A failed invitation
      is sent again only when the member signed an entry after it failed: that is how a member asks.

    Each action is a dict with `op` (in the order of `OPS`), `id` (github id), `login` (the GitHub login the
    call names) and, where it applies, `member` (the ledger login), `team`, `from`, `invitation`, `why`.
    """
    signed = signed or {}
    pid, plog = _protected(protected)
    is_protected = lambda gid, *logins: gid in pid or any(fold(x) in plog for x in logins if x)
    want: dict[int, tuple[str, int]] = {}
    out = {op: [] for op in OPS}
    for login, degree in sorted(desired.items()):
        team(degree)                                            # a degree outside 1..33 is a bug, not a plan
        gid = github_ids.get(login, 0)
        if type(gid) is not int or gid <= 0:
            out["hold"].append({"op": "hold", "id": 0, "login": login, "member": login,
                                "why": "the ledger records no GitHub id for this member"})
            continue
        if gid in want:
            raise ValueError(f"github id {gid} is claimed by both {want[gid][0]} and {login}")
        want[gid] = (login, degree)
    waiting = {p["id"] for p in pending if p.get("id") is not None}
    for gid, (login, degree) in sorted(want.items()):
        a = actual.get(gid)
        if is_protected(gid, login, a and a.get("login")):
            out["hold"].append({"op": "hold", "id": gid, "login": (a or {}).get("login") or login, "member": login,
                                "why": "a protected account: the sync program never touches it"})
            continue
        if a is not None and (a.get("member") or a.get("teams")):
            teams = set(a.get("teams") or ())
            if teams != {degree}:
                out["move"].append({"op": "move", "id": gid, "login": a["login"], "member": login,
                                    "team": team(degree), "from": [team(t) for t in sorted(teams - {degree})]})
            continue
        if gid in waiting:
            out["hold"].append({"op": "hold", "id": gid, "login": login, "member": login,
                                "why": "an invitation is pending"})
            continue
        failed = history.get(gid)
        if failed is not None and not (login in signed and signed[login] > failed["failed_at"]):
            out["hold"].append({"op": "hold", "id": gid, "login": login, "member": login,
                                "why": f"the invitation of {failed['failed_at'].strftime('%Y-%m-%dT%H:%M:%SZ')} was "
                                       f"{failed.get('reason') or 'not accepted'}; it is sent again once the member "
                                       "signs an entry after that"})
            continue
        out["invite"].append({"op": "invite", "id": gid, "login": login, "member": login, "team": team(degree)})
    for gid, a in sorted(actual.items()):
        if gid in want or is_protected(gid, a.get("login")):
            continue
        out["remove"].append({"op": "remove", "id": gid, "login": a["login"],
                              "from": [team(t) for t in sorted(set(a.get("teams") or ()))]})
    for p in sorted(pending, key=lambda p: p["invitation"]):
        gid = p.get("id")
        if is_protected(gid if type(gid) is int else -1, p.get("login")) or p.get("role", "direct_member") != "direct_member":
            continue                                             # an owner's invitation is the Console's business
        if gid is None or gid not in want:
            out["cancel"].append({"op": "cancel", "id": gid or 0, "login": p.get("login") or "",
                                  "invitation": p["invitation"],
                                  "why": "not sent by the sync program" if gid is None else "no longer on the roll"})
    return [x for op in OPS for x in out[op]]
