#!/usr/bin/env python3
"""The room sync program: makes the 33 room teams of the organization match the roll the ledger derives.

    python3 -P ops/rooms/sync.py --state DIR --custodian LOGIN [--apply] [--force-mass] [--ledger DIR]

It runs hourly in the private `ops` repository (ops/rooms/ops-workflow.yml; setup in ops/rooms/README.md).
Its rule is `src/openmasonry/rooms.py` (pinned core; SPEC section 15); this file is only the shell around it:

1. Verify the canonical ledger (full replay) and refuse if it is invalid, empty, dated ahead of the clock,
   or if its head moved backwards against the mark kept in the state directory.
2. Read the organization through the GitHub REST API (`gh api`, with an installation token in GH_TOKEN):
   the 33 room teams and their members, the members, the owners, pending and failed invitations, and the
   GitHub Apps installed on it. Never a repository, never any content.
3. Compute `rooms.sync_plan` and print it. Without `--apply` nothing is changed (dry run).
4. With `--apply`, perform it, about one request per second, honoring Retry-After.

Guards:
- every request is checked against a closed list: reads of the organization's teams, members, invitations
  and App installations; writes only to the membership of the 33 `degree-NN` teams and of the organization,
  with the plain `member` / `direct_member` role, never for a protected login (owners, applications, the
  custodian account, --protect); anything else is refused, printed and logged, and the program exits 1;
- mass guard: a run makes at most max(3, 10% of the people in the room teams) additions, and as many
  removals, taken in a fixed order (team, then ledger login); the rest wait for the next run. `--force-mass`,
  which an owner sets by hand and records afterwards as a Custodian note (the program prints its text),
  lifts the limit for one run;
- at most 40 invitations a run and 50 in any 24 hours (GitHub's limit in an organization's first month);
  the rest wait for the next run.

The state directory (the private `ops` checkout) holds `state.json` (the anti-rollback mark, the invitations
the program sent and those that failed) and `log.jsonl` (one JSON line per action and per run), which stay
private, and the two files every run writes for the Observatory, which name no one the ledger does not:
`actual.json` (om.rooms-actual/1: who GitHub lets read the rooms: the members of each room team, the owners
and every installed App) and `runs.jsonl` (one line appended per run, in counts only: what the run did).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from openmasonry import rooms  # noqa: E402
from openmasonry.ledger import (Invalid, fold, future_head, head_verdict, iso, load, remember_head,  # noqa: E402
                                replay, ts)

ORG = "openmasonry-org"
STATE_VERSION = 1
INVITES_PER_RUN = 40
INVITES_PER_DAY = 50                # GitHub: 50 invitations a day in an organization's first month
MASS_FLOOR, MASS_SHARE = 3, 0.10    # the mass guard: max(3, 10% of the people in the room teams)
PACE = 1.0                          # seconds between requests
MAX_WAIT = 900                      # the longest Retry-After honored, in seconds
RETRIES = 4
LOGIN = r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}"
PAGE = r"\?(?:role=admin&)?per_page=100&page=[0-9]{1,4}"
NOTE_RULE = "ops/rooms/README.md#the-guards"
PUBLIC_RUN = ("time", "apply", "force_mass", "seq", "head", "result", "additions", "removals", "deferred",
              "note_required")
ACTION_OPS = ("invite", "move", "remove", "cancel", "invitation")


class Refused(Exception):
    """A request or a run outside what the program may do."""


# --------------------------------------------------------------------------------- the closed list ----

def check_call(method: str, path: str, body, org: str, team_ids: dict[str, int], protected: set[str]) -> None:
    """Raise Refused unless the request is one of the few the program may make (pure)."""
    o = re.escape(org)
    reads = (rf"orgs/{o}/teams{PAGE}", rf"orgs/{o}/teams/(degree-[0-9]{{2}})/members{PAGE}", rf"orgs/{o}/members{PAGE}",
             rf"orgs/{o}/invitations{PAGE}", rf"orgs/{o}/failed_invitations{PAGE}", rf"orgs/{o}/installations{PAGE}",
             rf"orgs/{o}/memberships/{LOGIN}")
    if method == "GET":
        for pat in reads:
            m = re.fullmatch(pat, path)
            if m and body is None and (not m.groups() or rooms.team_degree(m.group(1))):
                return
        raise Refused(f"GET {path}: not a read the sync program makes (organization teams, members, invitations "
                      "and installations only)")
    def unprotected(login: str) -> None:
        if fold(login) in protected:
            raise Refused(f"{method} {path}: {login} is protected")
    if method == "POST" and path == f"orgs/{org}/invitations":
        if (type(body) is dict and set(body) == {"invitee_id", "role", "team_ids"} and type(body["invitee_id"]) is int
                and body["invitee_id"] > 0 and body["role"] == "direct_member" and type(body["team_ids"]) is list
                and len(body["team_ids"]) == 1 and body["team_ids"][0] in team_ids.values()):
            return
        raise Refused(f"POST {path}: an invitation is by numeric id, as a plain member, to exactly one room team")
    m = re.fullmatch(rf"orgs/{o}/teams/(degree-[0-9]{{2}})/memberships/({LOGIN})", path)
    if m and rooms.team_degree(m.group(1)) and m.group(1) in team_ids:
        if (method == "PUT" and body == {"role": "member"}) or (method == "DELETE" and body is None):
            unprotected(m.group(2))
            return
    m = re.fullmatch(rf"orgs/{o}/memberships/({LOGIN})", path)
    if m and method == "DELETE" and body is None:
        unprotected(m.group(1))
        return
    if re.fullmatch(rf"orgs/{o}/invitations/[0-9]{{1,15}}", path) and method == "DELETE" and body is None:
        return
    raise Refused(f"{method} {path}: outside the 33 room teams and the organization's membership")


# ------------------------------------------------------------------------------------- the transport ----

class GhTransport:
    """`gh api`, authenticated by GH_TOKEN (an installation token of the sync App). Returns
    (status, headers, data)."""

    def request(self, method: str, path: str, body=None):
        cmd = ["gh", "api", "--include", "--method", method, path,
               "-H", "Accept: application/vnd.github+json", "-H", "X-GitHub-Api-Version: 2022-11-28"]
        if body is not None:
            cmd += ["--input", "-"]
        r = subprocess.run(cmd, input=json.dumps(body) if body is not None else None, capture_output=True, text=True)
        return parse_include(r.stdout, r.stderr)


def parse_include(text: str, stderr: str = ""):
    """Parse the output of `gh api --include`: a status line, headers, a blank line, the body."""
    text = text.replace("\r\n", "\n")
    head, _, body = text.partition("\n\n")
    lines = head.split("\n")
    m = re.match(r"HTTP/[0-9.]+ ([0-9]{3})", lines[0] if lines else "")
    if not m:
        return 0, {}, {"message": (stderr or text).strip()[:300]}
    headers = {k.strip().lower(): v.strip() for k, _, v in (ln.partition(":") for ln in lines[1:]) if k}
    try:
        data = json.loads(body) if body.strip() else None
    except ValueError:
        data = {"message": body.strip()[:300]}
    return int(m.group(1)), headers, data


class Api:
    """Paced, retrying, closed-list access to the API."""

    def __init__(self, transport, org: str, pace: float = PACE, sleep=time.sleep, clock=time.time):
        self.t, self.org, self.pace, self.sleep, self.clock = transport, org, pace, sleep, clock
        self.team_ids: dict[str, int] = {}
        self.protected: set[str] = set()
        self.last = None
        self.calls = 0

    def call(self, method: str, path: str, body=None):
        check_call(method, path, body, self.org, self.team_ids or {f"degree-{n:02d}": -n for n in range(1, 34)},
                   self.protected)
        for attempt in range(RETRIES + 1):
            if self.last is not None and self.pace:
                wait = self.last + self.pace - self.clock()
                if wait > 0:
                    self.sleep(wait)
            status, headers, data = self.t.request(method, path, body)
            self.last, self.calls = self.clock(), self.calls + 1
            limited = status == 429 or (status == 403 and ("retry-after" in headers
                                                           or headers.get("x-ratelimit-remaining") == "0"))
            if (limited or status >= 500 or status == 0) and attempt < RETRIES:
                if "retry-after" in headers and headers["retry-after"].isdigit():
                    wait = int(headers["retry-after"])
                elif headers.get("x-ratelimit-remaining") == "0" and headers.get("x-ratelimit-reset", "").isdigit():
                    wait = int(headers["x-ratelimit-reset"]) - int(self.clock()) + 1
                else:
                    wait = 2 ** attempt * 5
                self.sleep(min(max(wait, 1), MAX_WAIT))
                continue
            return status, data
        return status, data

    def get(self, path: str):
        status, data = self.call("GET", path)
        if status != 200:
            raise RuntimeError(f"GET {path}: HTTP {status}: {(data or {}).get('message', '') if isinstance(data, dict) else ''}")
        return data

    def pages(self, path: str, query: str = "", key: str | None = None) -> list:
        """Every page of a list; `key` names the list inside an object response (e.g. `installations`)."""
        out, page = [], 1
        while True:
            got = self.get(f"{path}?{query}per_page=100&page={page}")
            got = got[key] if key else got
            out += got
            if len(got) < 100:
                return out
            page += 1


# ---------------------------------------------------------------------------------------- reading ----

def read_org(api: Api) -> dict:
    """Everything the plan needs from GitHub, as plain data."""
    teams = {t["slug"]: t["id"] for t in api.pages(f"orgs/{api.org}/teams") if rooms.team_degree(t["slug"])}
    missing = [rooms.team(n) for n in range(1, rooms.ROOMS + 1) if rooms.team(n) not in teams]
    if missing:
        raise Refused(f"the organization lacks the room teams {', '.join(missing)}")
    api.team_ids = teams
    team_members = {slug: [{"id": u["id"], "login": u["login"]} for u in api.pages(f"orgs/{api.org}/teams/{slug}/members")]
                    for slug in sorted(teams)}
    members = [{"id": u["id"], "login": u["login"]} for u in api.pages(f"orgs/{api.org}/members")]
    owners = [{"id": u["id"], "login": u["login"]} for u in api.pages(f"orgs/{api.org}/members", "role=admin&")]
    pending = [{"invitation": i["id"], "login": i.get("login") or "", "role": i.get("role") or "",
                "created_at": i.get("created_at")} for i in api.pages(f"orgs/{api.org}/invitations")]
    failed = [{"invitation": i["id"], "login": i.get("login") or "", "failed_at": i.get("failed_at"),
               "reason": i.get("failed_reason") or "failed"} for i in api.pages(f"orgs/{api.org}/failed_invitations")]
    apps = sorted({i["app_slug"] for i in api.pages(f"orgs/{api.org}/installations", key="installations")})
    return {"teams": teams, "team_members": team_members, "members": members, "owners": owners,
            "pending": pending, "failed": failed, "apps": apps}


def actual_of(org: dict) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for u in org["members"]:
        out[u["id"]] = {"login": u["login"], "teams": [], "member": True}
    for slug, users in org["team_members"].items():
        for u in users:
            out.setdefault(u["id"], {"login": u["login"], "teams": [], "member": True})["teams"].append(rooms.team_degree(slug))
    return out


def actual_document(org: dict, now: datetime, on_ledger: dict[int, str]) -> dict:
    """om.rooms-actual/1, published: who GitHub lets read the rooms (pure). A team member is named by the login
    the ledger records for their GitHub id (`on_ledger`), an owner or an App's `[bot]` account by its login, and
    any other account only as `(not on the ledger #N)`: counted, never named. No id is written."""
    owner_ids = {u["id"] for u in org["owners"]}
    strangers: dict[int, str] = {}

    def name(u: dict) -> str:
        if u["id"] in on_ledger:
            return on_ledger[u["id"]]
        if u["id"] in owner_ids or u["login"].endswith("[bot]"):
            return u["login"]
        return strangers.setdefault(u["id"], f"(not on the ledger #{len(strangers) + 1})")
    teams = {slug: sorted(name(u) for u in org["team_members"][slug]) for slug in sorted(org["team_members"])}
    return {"schema": "om.rooms-actual/1", "time": iso(now), "teams": teams,
            "owners": sorted(u["login"] for u in org["owners"]), "apps": list(org["apps"])}


def reconcile(state: dict, org: dict, now: datetime) -> list[dict]:
    """What became of the invitations the program sent: accepted, failed (GitHub's list of failed
    invitations), or gone without trace (declined or canceled by hand). Updates `state`; returns log rows."""
    member_ids = {u["id"] for u in org["members"]}
    open_ids = {p["invitation"] for p in org["pending"]}
    failed = {f["invitation"]: f for f in org["failed"]}
    rows = []
    for inv, sent in sorted(state["invitations"].items()):
        if int(inv) in open_ids:
            continue
        gid = sent["github_id"]
        if gid in member_ids:
            outcome = {"result": "accepted"}
            state["failures"].pop(str(gid), None)
        else:
            f = failed.get(int(inv))
            when = f["failed_at"] if f and f.get("failed_at") else iso(now)
            reason = (f["reason"] if f else "declined, or canceled by hand").lower()
            state["failures"][str(gid)] = {"failed_at": when, "reason": reason, "invitation": int(inv)}
            outcome = {"result": "failed", "reason": reason}
        del state["invitations"][inv]
        rows.append({"time": iso(now), "op": "invitation", "invitation": int(inv), "id": gid,
                     "login": sent["login"], **outcome})
    return rows


def forget_failures(state: dict, roll_ids: set[int], member_ids: set[int]) -> None:
    """Keep a recorded failure only while it still guards something: forget it once the member leaves the roll
    or joins the organization (a new invitation forgets it as well, when it is sent)."""
    state["failures"] = {g: f for g, f in state["failures"].items() if int(g) in roll_ids and int(g) not in member_ids}


# --------------------------------------------------------------------------------------- the guards ----

def mass_limit(people: int) -> int:
    return max(MASS_FLOOR, math.ceil(people * MASS_SHARE))


def is_addition(a: dict) -> bool:
    """An invitation, or the join of a first team."""
    return a["op"] == "invite" or (a["op"] == "move" and not a["from"])


def is_removal(a: dict) -> bool:
    """A removal from the organization, or a canceled invitation."""
    return a["op"] in ("remove", "cancel")


def mass_count(plan: list[dict]) -> tuple[int, int]:
    """(additions, removals) of a plan."""
    return sum(map(is_addition, plan)), sum(map(is_removal, plan))


def mass_defer(plan: list[dict], limit: int) -> tuple[int, int]:
    """Mark the additions beyond `limit`, and the removals beyond `limit`, as deferred: they wait for a later
    run. The ones kept come first in a fixed order: team, then ledger login. Returns (additions, removals)
    deferred."""
    key = lambda a: (a.get("team") or min(a.get("from") or [""]), fold(a.get("member") or a.get("login") or ""),
                     a.get("id") or 0, a.get("invitation") or 0)
    counts = []
    for kind in (is_addition, is_removal):
        late = sorted((a for a in plan if kind(a)), key=key)[limit:]
        for a in late:
            a["deferred"] = True
        counts.append(len(late))
    return counts[0], counts[1]


def invites_today(state: dict, log_rows: list[dict], now: datetime) -> int:
    since = now - timedelta(hours=24)
    return sum(1 for r in log_rows if r.get("op") == "invite" and r.get("result") == "done" and ts(r["time"]) > since)


def note_text(now: datetime, adds: int, removals: int, limit: int, st) -> str:
    return (f"This run used --force-mass. Record it in the ledger as a Custodian note:\n\n"
            f"  bin/om correct note --action other --target {ORG} --rule {NOTE_RULE} --reason reason.md\n\n"
            f"with reason.md:\n\n"
            f"  The room sync of {iso(now)} made {adds} addition(s) and {removals} removal(s) in one run, above "
            f"the mass guard of {limit} a run, by an owner's dispatch with force_mass. It applied the roll that the "
            f"ledger derives at entry #{st.seq} (head {st.head}); its log is in the ops repository.\n")


# -------------------------------------------------------------------------------------------- state ----

def load_state(d: Path) -> dict:
    p = d / "state.json"
    if not p.exists():
        return {"v": STATE_VERSION, "org": ORG, "heads": {}, "invitations": {}, "failures": {}}
    s = json.loads(p.read_text(encoding="utf-8"))
    if s.get("v") != STATE_VERSION:
        raise Refused(f"{p}: unknown state version {s.get('v')!r}")
    for k in ("heads", "invitations", "failures"):
        s.setdefault(k, {})
    return s


def read_log(d: Path) -> list[dict]:
    p = d / "log.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []


def run_line(rows: list[dict]) -> dict:
    """The public line of a run (pure): its run row without the reason, and the count of its actions by
    operation and result. It names no person: no login, no id."""
    run = next(r for r in reversed(rows) if r.get("op") == "run")
    actions: dict[str, dict[str, int]] = {}
    for r in rows:
        if r.get("op") in ACTION_OPS and isinstance(r.get("result"), str):
            n = actions.setdefault(r["op"], {})
            n[r["result"]] = n.get(r["result"], 0) + 1
    return {k: run[k] for k in PUBLIC_RUN if k in run} | {"actions": actions}


def save(d: Path, state: dict, rows: list[dict], actual: dict | None) -> None:
    d.mkdir(parents=True, exist_ok=True)
    for name, doc in (("state.json", state), ("actual.json", actual)):
        if doc is None:
            continue
        tmp = d / f".{name}.tmp"
        tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(d / name)
    if rows:
        with (d / "log.jsonl").open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n")
        with (d / "runs.jsonl").open("a", encoding="utf-8") as f:     # appended only, never rewritten
            f.write(json.dumps(run_line(rows), sort_keys=True) + "\n")


# ---------------------------------------------------------------------------------------- performing ----

def perform(api: Api, action: dict) -> None:
    """One action of the plan, as one or more requests. Raises RuntimeError on a failed request."""
    def need(status, data, what, ok=(200, 201, 204)):
        if status not in ok:
            msg = data.get("message", "") if isinstance(data, dict) else ""
            raise RuntimeError(f"{what}: HTTP {status} {msg}".strip())
        return data
    org, op = api.org, action["op"]
    if op == "invite":
        body = {"invitee_id": action["id"], "role": "direct_member", "team_ids": [api.team_ids[action["team"]]]}
        data = need(*api.call("POST", f"orgs/{org}/invitations", body), "invite")
        action["invitation"] = data["id"]
    elif op == "move":
        # The PUT invites a login that is not in the organization: first make sure the login still names this
        # member, as a plain member (a rename and a taken login between the plan and now would add someone else).
        status, data = api.call("GET", f"orgs/{org}/memberships/{action['login']}")
        if status != 200 or type(data) is not dict:
            raise Refused(f"move {action['login']}: the login is not a member of the organization now (HTTP {status})")
        if data.get("role") != "member":
            raise Refused(f"move {action['login']}: the account's role is {data.get('role')!r}, not member")
        if (data.get("user") or {}).get("id") != action["id"]:
            raise Refused(f"move {action['login']}: the login now names another account")
        need(*api.call("PUT", f"orgs/{org}/teams/{action['team']}/memberships/{action['login']}", {"role": "member"}),
             f"add to {action['team']}")
        for old in action["from"]:
            need(*api.call("DELETE", f"orgs/{org}/teams/{old}/memberships/{action['login']}"), f"leave {old}",
                 ok=(204, 404))
    elif op == "remove":
        status, data = api.call("GET", f"orgs/{org}/memberships/{action['login']}")
        if status == 200 and data.get("role") != "member":
            raise Refused(f"remove {action['login']}: the account's role is {data.get('role')!r}, not member")
        if status == 200 and (data.get("user") or {}).get("id") not in (None, action["id"]):
            raise Refused(f"remove {action['login']}: the login now names another account")
        need(*api.call("DELETE", f"orgs/{org}/memberships/{action['login']}"), "remove", ok=(204, 404))
    elif op == "cancel":
        need(*api.call("DELETE", f"orgs/{org}/invitations/{action['invitation']}"), "cancel", ok=(204, 404))


def describe(a: dict) -> str:
    who = a["login"] + (f" (the member {a['member']})" if a.get("member") and fold(a["member"]) != fold(a["login"]) else "")
    return {"invite": lambda: f"invite {who} (GitHub id {a['id']}) into {a.get('team')}",
            "move": lambda: f"add {who} to {a['team']}" + (f", then remove from {', '.join(a['from'])}" if a["from"] else ""),
            "remove": lambda: f"remove {who} (GitHub id {a['id']}) from the organization",
            "cancel": lambda: f"cancel invitation {a['invitation']} of {a['login'] or '(unknown)'}: {a.get('why', '')}",
            "hold": lambda: f"leave {who}: {a.get('why', '')}"}[a["op"]]()


# ------------------------------------------------------------------------------------------- the run ----

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ops/rooms/sync.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--state", type=Path, required=True, metavar="DIR", help="the state directory (the ops checkout)")
    p.add_argument("--ledger", type=Path, default=ROOT / "ledger" / "entries")
    p.add_argument("--org", default=os.environ.get("OM_ORG", ORG))
    p.add_argument("--custodian", default=os.environ.get("OM_CUSTODIAN_ACCOUNT"), metavar="LOGIN",
                   help="the custodian account: never touched (required; env OM_CUSTODIAN_ACCOUNT)")
    p.add_argument("--protect", action="append", default=[], metavar="LOGIN", help="another login never touched")
    p.add_argument("--apply", action="store_true", help="perform the plan (default: dry run)")
    p.add_argument("--force-mass", action="store_true", help="allow more changes than the mass guard (an owner only)")
    p.add_argument("--now", help=argparse.SUPPRESS)
    p.add_argument("--pace", type=float, default=PACE, help=argparse.SUPPRESS)
    return p


def run(argv=None, transport=None, replay_fn=replay, sleep=time.sleep, clock=time.time, out=print) -> int:
    a = parser().parse_args(argv)
    now = ts(a.now) if a.now else datetime.now(timezone.utc).replace(microsecond=0)
    if not a.custodian:
        out("REFUSED — --custodian (or OM_CUSTODIAN_ACCOUNT) must name the custodian account")
        return 1
    run_row = {"time": iso(now), "op": "run", "apply": a.apply, "force_mass": a.force_mass}
    try:
        state = load_state(a.state)
        log_rows = read_log(a.state)
    except (OSError, ValueError, Refused) as err:
        out(f"REFUSED — the state directory cannot be read: {err}")
        return 1

    def refuse(msg: str, rows=(), actual=None) -> int:
        out(f"REFUSED — {msg}")
        save(a.state, state, [*rows, run_row | {"result": "refused", "reason": msg}], actual)
        return 1

    # 1. The ledger: verified, not empty, not ahead of the clock, not behind the mark.
    try:
        entries = load(a.ledger)
        st = replay_fn(entries) if entries else None
    except Invalid as err:
        return refuse(f"the ledger is invalid: {err}")
    if st is None:
        return refuse("the ledger is empty: no roll derives from it")
    if future_head(st.time, now):
        return refuse(f"the head of the ledger is dated {iso(st.time)}, ahead of the clock (a capture alarm)")
    verdict, seq, h = head_verdict(state, st.hashes)
    if verdict not in ("first", "ok"):
        return refuse(f"the canonical ledger moved backwards ({verdict} at entry #{seq}, {h[:12]}…): "
                      "nothing is changed until a person looks")
    state.update(remember_head(state, st.hashes))
    run_row |= {"seq": st.seq, "head": st.head}

    # 2. GitHub, read through the closed list.
    api = Api(transport or GhTransport(), a.org, pace=a.pace, sleep=sleep, clock=clock)
    api.protected = {fold(x) for x in (a.custodian, *a.protect)}
    try:
        org = read_org(api)
    except (Refused, RuntimeError, KeyError, TypeError) as err:
        return refuse(f"reading the organization: {err}")
    owners = {fold(u["login"]) for u in org["owners"]}
    bots = {fold(u["login"]) for users in (org["members"], *org["team_members"].values()) for u in users
            if u["login"].endswith("[bot]")}
    api.protected |= owners | bots
    protected = set(api.protected) | {u["id"] for u in org["owners"]}
    actual_doc = actual_document(org, now, {i: login for login, i in rooms.github_ids(st).items() if i})
    rows = reconcile(state, org, now)

    # 3. The plan.
    access = rooms.room_access(st, now)
    ids = rooms.github_ids(st)
    forget_failures(state, {ids[x] for x in access}, {u["id"] for u in org["members"]})
    pending = [{"invitation": p["invitation"], "login": p["login"], "role": p["role"],
                "id": state["invitations"].get(str(p["invitation"]), {}).get("github_id")} for p in org["pending"]]
    history = {int(g): {"failed_at": ts(f["failed_at"]), "reason": f["reason"]} for g, f in state["failures"].items()}
    plan = rooms.sync_plan(access, actual_of(org), pending, history, protected, ids,
                           rooms.last_signed(st, entries))
    people = len({u["id"] for users in org["team_members"].values() for u in users})
    limit = mass_limit(people)
    adds, removals = mass_count(plan)
    run_row |= {"additions": adds, "removals": removals}
    acting = [x for x in plan if x["op"] != "hold"]
    out(f"ledger #{st.seq} {st.head[:12]}… · {len(access)} member(s) on the roll · {people} in the room teams · "
        f"{len(acting)} change(s): {adds} addition(s), {removals} removal(s) (mass guard {limit}) · "
        + ("APPLY" if a.apply else "dry run"))
    for x in plan:
        out(("  " if x["op"] != "hold" else "  · ") + describe(x))
    if not a.force_mass:
        late_adds, late_removals = mass_defer(acting, limit)
        if late_adds or late_removals:
            out(f"  {late_adds} addition(s) and {late_removals} removal(s) wait for a later run (the mass guard of "
                f"{limit} a run; an owner may dispatch the run with force_mass, and records it as a Custodian note)")

    # 4. Invitation caps: the rest wait for a later run.
    room = min(INVITES_PER_RUN, max(0, INVITES_PER_DAY - invites_today(state, log_rows + rows, now)))
    invites = [x for x in plan if x["op"] == "invite" and not x.get("deferred")]
    for x in invites[room:]:
        x["deferred"] = True
    if len(invites) > room:
        out(f"  {len(invites) - room} invitation(s) wait for a later run (at most {INVITES_PER_RUN} a run and "
            f"{INVITES_PER_DAY} in 24 hours)")

    run_row["deferred"] = sum(1 for x in acting if x.get("deferred"))
    state["last_run"] = iso(now)
    if not a.apply:
        state["last_dry_run"] = iso(now)
        rows += [{"time": iso(now), **x, "result": "deferred" if x.get("deferred") else "planned"} for x in acting]
        save(a.state, state, [*rows, run_row | {"result": "dry-run", "changes": len(acting)}], actual_doc)
        return 0

    failed = False
    for x in acting:
        if x.get("deferred"):
            rows.append({"time": iso(now), **x, "result": "deferred"})
            continue
        try:
            perform(api, x)
        except Refused as err:
            out(f"REFUSED — {describe(x)}: {err}")
            rows.append({"time": iso(now), **x, "result": "refused", "reason": str(err)})
            failed = True
            break
        except (RuntimeError, KeyError, TypeError) as err:
            out(f"FAILED — {describe(x)}: {err}")
            rows.append({"time": iso(now), **x, "result": "failed", "reason": str(err)})
            failed = True
            break
        rows.append({"time": iso(now), **x, "result": "done"})
        if x["op"] == "invite":
            state["invitations"][str(x["invitation"])] = {"github_id": x["id"], "login": x["login"],
                                                          "team": x["team"], "time": iso(now)}
            state["failures"].pop(str(x["id"]), None)
    run_row |= {"result": "failed" if failed else "applied", "changes": len(acting), "requests": api.calls}
    if not failed:
        state["last_success"] = iso(now)
    if a.force_mass and (adds > limit or removals > limit):
        out(note_text(now, adds, removals, limit, st))
        run_row["note_required"] = True
    save(a.state, state, [*rows, run_row], actual_doc)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
