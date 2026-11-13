"""The room sync program (ops/rooms/sync.py) against a fake GitHub: no network, no `gh`."""
from __future__ import annotations

import importlib.util
import json
import re
import unittest
from datetime import timedelta
from pathlib import Path

from openmasonry import ledger
from tests.test_custodian import correct, lodge
from tests.test_strict import by_key, tmpdir, write_ledger

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("om_rooms_sync", REPO / "ops" / "rooms" / "sync.py")
sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync)
ORG = sync.ORG
DAY = timedelta(days=1)


class FakeGitHub:
    """The organization's teams, members and invitations, and the REST calls the program may make on them."""

    def __init__(self):
        self.teams = {f"degree-{n:02d}": 1000 + n for n in range(1, 34)} | {"admins": 999}
        self.users: dict[int, str] = {}                      # id -> current login
        self.org: dict[int, str] = {}                        # id -> role (member | admin)
        self.team_members: dict[str, set[int]] = {s: set() for s in self.teams}
        self.invitations: dict[int, dict] = {}               # invitation id -> {invitee, role, team_ids}
        self.failed: list[dict] = []
        self.apps: list[str] = ["openmasonry-rooms"]          # the slugs of the installed GitHub Apps
        self.calls: list[tuple[str, str, object]] = []
        self.script: list[tuple[int, dict, object]] = []     # responses served first, whatever the call
        self.next_inv = 500

    def user(self, uid: int, login: str, role: str | None = "member", *teams: int):
        self.users[uid] = login
        if role:
            self.org[uid] = role
        for t in teams:
            self.team_members[f"degree-{t:02d}"].add(uid)

    def by_login(self, login):
        return next((i for i, x in self.users.items() if x.lower() == login.lower()), None)

    def page(self, rows, path):
        n = int(re.search(r"[?&]page=([0-9]+)", path).group(1))
        return rows[(n - 1) * 100:n * 100]

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if self.script:
            return self.script.pop(0)
        u = lambda i: {"id": i, "login": self.users[i]}
        base = path.split("?")[0]
        if method == "GET":
            if base == f"orgs/{ORG}/teams":
                return 200, {}, self.page([{"slug": s, "id": i} for s, i in sorted(self.teams.items())], path)
            if m := re.fullmatch(rf"orgs/{ORG}/teams/([^/]+)/members", base):
                return 200, {}, self.page([u(i) for i in sorted(self.team_members[m.group(1)])], path)
            if base == f"orgs/{ORG}/members":
                admin = "role=admin" in path
                return 200, {}, self.page([u(i) for i, r in sorted(self.org.items()) if not admin or r == "admin"], path)
            if base == f"orgs/{ORG}/invitations":
                return 200, {}, self.page([{"id": k, "login": self.users.get(v["invitee"]), "role": v["role"],
                                            "created_at": "2027-01-01T00:00:00Z"}
                                           for k, v in sorted(self.invitations.items())], path)
            if base == f"orgs/{ORG}/failed_invitations":
                return 200, {}, self.page(self.failed, path)
            if base == f"orgs/{ORG}/installations":
                rows = [{"id": 70 + n, "app_id": 90 + n, "app_slug": s, "account": {"login": ORG, "id": 5}}
                        for n, s in enumerate(self.apps)]
                return 200, {}, {"total_count": len(rows), "installations": self.page(rows, path)}
            if m := re.fullmatch(rf"orgs/{ORG}/memberships/([^/]+)", base):
                i = self.by_login(m.group(1))
                return (200, {}, {"role": self.org[i], "user": u(i)}) if i in self.org else (404, {}, {"message": "Not Found"})
        if method == "POST" and base == f"orgs/{ORG}/invitations":
            self.next_inv += 1
            self.invitations[self.next_inv] = {"invitee": body["invitee_id"], "role": body["role"],
                                               "team_ids": body["team_ids"]}
            return 201, {}, {"id": self.next_inv}
        if m := re.fullmatch(rf"orgs/{ORG}/teams/([^/]+)/memberships/([^/]+)", base):
            i = self.by_login(m.group(2))
            if method == "PUT":
                self.team_members[m.group(1)].add(i)
                return 200, {}, {"state": "active"}
            self.team_members[m.group(1)].discard(i)
            return 204, {}, None
        if m := re.fullmatch(rf"orgs/{ORG}/memberships/([^/]+)", base):
            i = self.by_login(m.group(1))
            self.org.pop(i, None)
            for s in self.team_members.values():
                s.discard(i)
            return 204, {}, None
        if m := re.fullmatch(rf"orgs/{ORG}/invitations/([0-9]+)", base):
            self.invitations.pop(int(m.group(1)), None)
            return 204, {}, None
        return 404, {}, {"message": "Not Found"}

    def accept(self, inv: int):
        v = self.invitations.pop(inv)
        self.org[v["invitee"]] = "member"
        for slug, tid in self.teams.items():
            if tid in v["team_ids"]:
                self.team_members[slug].add(v["invitee"])

    def writes(self):
        return [(m, p) for m, p, _ in self.calls if m != "GET"]


class Harness(unittest.TestCase):
    def setUp(self):
        self.state = tmpdir(self) / "ops-state"
        self.gh = FakeGitHub()
        self.gh.user(1, "openmasonry", "admin")                    # the custodian account owns the organization
        self.out: list[str] = []
        self.c = lodge()                                           # hiram, ada, carol at the 3rd degree

    def ids(self):
        st = self.c.state()
        for login, m in st.members.items():
            self.gh.users.setdefault(m.github_id, login)
        return {login: m.github_id for login, m in st.members.items()}

    def run_sync(self, *args, when=None):
        led = write_ledger(tmpdir(self) / "entries", self.c.entries)
        now = when or ledger.iso(self.c.now + DAY)
        self.out = []
        return sync.run(["--state", str(self.state), "--ledger", str(led), "--custodian", "openmasonry",
                         "--now", now, "--pace", "0", *args],
                        transport=self.gh, replay_fn=lambda e: ledger.replay(e, verifier=by_key),
                        sleep=lambda s: None, out=self.out.append)

    def log(self):
        return [json.loads(x) for x in (self.state / "log.jsonl").read_text().splitlines()]

    def saved(self):
        return json.loads((self.state / "state.json").read_text())


class Sync(Harness):
    def test_a_dry_run_changes_nothing_and_says_what_it_would_do(self):
        ids = self.ids()
        self.assertEqual(self.run_sync(), 0, self.out)
        self.assertEqual(self.gh.writes(), [])
        self.assertIn("dry run", self.out[0])
        self.assertEqual(sum("invite" in line for line in self.out[1:]), 3)
        planned = [r for r in self.log() if r.get("result") == "planned"]
        self.assertEqual(sorted(r["id"] for r in planned), sorted(ids.values()))
        self.assertEqual(self.log()[-1]["result"], "dry-run")
        self.assertEqual(json.loads((self.state / "actual.json").read_text())["schema"], "om.rooms-actual/1")

    def test_apply_invites_by_id_into_the_team_and_then_waits(self):
        ids = self.ids()
        self.assertEqual(self.run_sync("--apply"), 0, self.out)
        posts = [b for m, p, b in self.gh.calls if m == "POST"]
        self.assertEqual(sorted(b["invitee_id"] for b in posts), sorted(ids.values()))
        self.assertTrue(all(b == {"invitee_id": b["invitee_id"], "role": "direct_member", "team_ids": [1003]}
                            for b in posts))
        self.assertEqual(len(self.saved()["invitations"]), 3)
        self.assertIn("last_success", self.saved())
        calls = len(self.gh.calls)
        self.assertEqual(self.run_sync("--apply"), 0, self.out)       # pending: nothing sent again
        self.assertEqual([c for c in self.gh.calls[calls:] if c[0] != "GET"], [])
        for inv in list(self.gh.invitations):
            self.gh.accept(inv)
        self.assertEqual(self.run_sync("--apply"), 0, self.out)
        self.assertEqual(self.saved()["invitations"], {})
        self.assertEqual(sum(r.get("result") == "accepted" for r in self.log()), 3)

    def test_protected_logins_are_never_touched(self):
        self.ids()
        self.gh.user(2, "owner2", "admin", 5)                     # an owner in a room team
        self.gh.user(3, "helper[bot]", "member", 7)                # an application's account
        self.gh.user(4, "custodian-x", "member", 1)
        self.assertEqual(self.run_sync("--apply", "--protect", "custodian-x", "--force-mass"), 0, self.out)
        touched = {p.rsplit("/", 1)[1] for _, p in self.gh.writes()}
        self.assertEqual(touched, {"invitations"})                 # three invitations, and nothing else
        self.assertEqual(len(self.gh.writes()), 3)

    def test_the_closed_list_refuses_anything_else(self):
        teams = {f"degree-{n:02d}": 1000 + n for n in range(1, 34)}
        ok = [("GET", f"orgs/{ORG}/teams?per_page=100&page=1", None),
              ("GET", f"orgs/{ORG}/teams/degree-05/members?per_page=100&page=2", None),
              ("GET", f"orgs/{ORG}/members?role=admin&per_page=100&page=1", None),
              ("GET", f"orgs/{ORG}/installations?per_page=100&page=1", None),
              ("POST", f"orgs/{ORG}/invitations", {"invitee_id": 5, "role": "direct_member", "team_ids": [1005]}),
              ("PUT", f"orgs/{ORG}/teams/degree-33/memberships/amy", {"role": "member"}),
              ("DELETE", f"orgs/{ORG}/teams/degree-01/memberships/amy", None),
              ("DELETE", f"orgs/{ORG}/memberships/amy", None),
              ("DELETE", f"orgs/{ORG}/invitations/77", None)]
        for m, p, b in ok:
            sync.check_call(m, p, b, ORG, teams, {"openmasonry"})
        bad = [("GET", f"repos/{ORG}/degree-01/issues", None),
               ("GET", f"repos/{ORG}/degree-01/contents/README.md", None),
               ("GET", f"orgs/{ORG}/teams/admins/members?per_page=100&page=1", None),
               ("GET", "orgs/other-org/members?per_page=100&page=1", None),
               ("GET", f"orgs/{ORG}/installations/70", None),
               ("DELETE", f"orgs/{ORG}/installations/70", None),
               ("POST", f"orgs/{ORG}/invitations", {"invitee_id": 5, "role": "admin", "team_ids": [1005]}),
               ("POST", f"orgs/{ORG}/invitations", {"invitee_id": 5, "role": "direct_member", "team_ids": [999]}),
               ("POST", f"orgs/{ORG}/invitations", {"email": "x@example.org", "role": "direct_member", "team_ids": [1005]}),
               ("POST", f"orgs/{ORG}/invitations", {"invitee_id": 5, "role": "direct_member", "team_ids": [1005, 1006]}),
               ("PUT", f"orgs/{ORG}/teams/degree-03/memberships/amy", {"role": "maintainer"}),
               ("PUT", f"orgs/{ORG}/teams/admins/memberships/amy", {"role": "member"}),
               ("PUT", f"orgs/{ORG}/memberships/amy", {"role": "admin"}),
               ("DELETE", f"orgs/{ORG}/memberships/openmasonry", None),
               ("DELETE", f"orgs/{ORG}/teams/degree-03/memberships/OpenMasonry", None),
               ("DELETE", f"orgs/{ORG}/teams/degree-03", None),
               ("PATCH", f"orgs/{ORG}", {"default_repository_permission": "read"}),
               ("PUT", f"orgs/{ORG}/teams/degree-03/repos/{ORG}/degree-04", {"permission": "pull"})]
        for m, p, b in bad:
            with self.assertRaises(sync.Refused, msg=f"{m} {p}"):
                sync.check_call(m, p, b, ORG, teams, {"openmasonry"})

    def test_a_rename_is_followed_by_id_and_a_squatter_is_removed(self):
        ids = self.ids()
        ada = ids["ada"]
        for login, i in ids.items():
            self.gh.user(i, login, "member", 3)
        self.gh.users[ada] = "ada-renamed"                          # ada renamed her account…
        self.gh.user(9001, "ada", "member", 3)                      # …and someone took the login `ada`
        self.assertEqual(self.run_sync("--apply"), 0, self.out)
        self.assertEqual(self.gh.writes(), [("DELETE", f"orgs/{ORG}/memberships/ada")])
        self.assertIn(ada, self.gh.team_members["degree-03"])
        self.assertNotIn(9001, self.gh.org)

    def test_an_advance_joins_the_new_team_before_leaving_the_old(self):
        ids = self.ids()
        for login, i in ids.items():
            self.gh.user(i, login, "member", 3 if login != "carol" else 2)
        self.assertEqual(self.run_sync("--apply"), 0, self.out)
        self.assertEqual(self.gh.writes(), [("PUT", f"orgs/{ORG}/teams/degree-03/memberships/carol"),
                                            ("DELETE", f"orgs/{ORG}/teams/degree-02/memberships/carol")])

    def test_a_move_checks_the_numeric_id_before_adding_to_a_team(self):
        """Between the plan and the request the member renames their account and another account takes the login:
        the account now behind the login is never added to a room team (GitHub would invite it)."""
        api = sync.Api(self.gh, ORG, pace=0, sleep=lambda s: None)
        api.team_ids = {s: i for s, i in self.gh.teams.items() if s != "admins"}
        move = lambda: {"op": "move", "id": 42, "login": "carol", "member": "carol", "team": "degree-03",
                        "from": ["degree-02"]}
        self.gh.user(42, "carol-renamed", "member", 2)
        for case in ("taken by a member", "taken by an outsider", "an owner"):
            if case == "taken by a member":
                self.gh.user(9002, "carol", "member")
            elif case == "taken by an outsider":
                self.gh.org.pop(9002)
            else:
                self.gh.users.pop(9002)
                self.gh.users[42] = "carol"
                self.gh.org[42] = "admin"
            with self.assertRaises(sync.Refused, msg=case):
                sync.perform(api, move())
            self.assertEqual(self.gh.writes(), [], case)
        self.gh.org[42] = "member"
        sync.perform(api, move())
        self.assertEqual(self.gh.writes(), [("PUT", f"orgs/{ORG}/teams/degree-03/memberships/carol"),
                                            ("DELETE", f"orgs/{ORG}/teams/degree-02/memberships/carol")])
        self.assertIn(42, self.gh.team_members["degree-03"])

    def test_a_hold_removes_and_does_not_reinvite_until_it_ends(self):
        ids = self.ids()
        for login, i in ids.items():
            self.gh.user(i, login, "member", 3)
        correct(self.c, "hold_room", {"login": "carol"}, "identity_fraud", days=1)
        self.assertEqual(self.run_sync("--apply", when=ledger.iso(self.c.now + DAY)), 0, self.out)
        self.assertEqual(self.gh.writes(), [("DELETE", f"orgs/{ORG}/memberships/carol")])

    def test_a_declined_invitation_is_not_sent_again_until_the_member_signs(self):
        ids = self.ids()
        for login in ("hiram", "ada"):
            self.gh.user(ids[login], login, "member", 3)
        self.assertEqual(self.run_sync("--apply"), 0, self.out)
        inv = next(iter(self.gh.invitations))
        del self.gh.invitations[inv]                              # carol declined
        self.assertEqual(self.run_sync("--apply"), 0, self.out)
        self.assertIn(str(ids["carol"]), self.saved()["failures"])
        self.assertEqual(len(self.gh.invitations), 0)
        self.assertTrue(any("sent again once the member signs" in line for line in self.out))
        self.assertEqual(self.run_sync("--apply", when=ledger.iso(self.c.now + 3 * DAY)), 0)
        self.assertEqual(len(self.gh.invitations), 0)              # still not retried
        self.c.add("work", "carol", {"ref": "https://example.org/w"}, days=4)   # carol asks, by a signed entry
        self.assertEqual(self.run_sync("--apply", when=ledger.iso(self.c.now + DAY)), 0, self.out)
        self.assertEqual(len(self.gh.invitations), 1)
        self.assertNotIn(str(ids["carol"]), self.saved()["failures"])

    def declined(self):
        ids = self.ids()
        for login in ("hiram", "ada"):
            self.gh.user(ids[login], login, "member", 3)
        self.assertEqual(self.run_sync("--apply"), 0, self.out)
        del self.gh.invitations[next(iter(self.gh.invitations))]  # carol declined
        self.assertEqual(self.run_sync("--apply"), 0, self.out)
        self.assertIn(str(ids["carol"]), self.saved()["failures"])
        return ids

    def test_a_failure_is_forgotten_when_the_member_leaves_the_roll(self):
        ids = self.declined()
        self.c.add("depart", "carol", {}, days=1)
        self.assertEqual(self.run_sync("--apply", when=ledger.iso(self.c.now + DAY)), 0, self.out)
        self.assertNotIn(str(ids["carol"]), self.saved()["failures"])

    def test_a_failure_is_forgotten_when_the_member_joins(self):
        ids = self.declined()
        self.gh.user(ids["carol"], "carol", "member", 3)           # an owner let her in by hand
        self.assertEqual(self.run_sync("--apply"), 0, self.out)
        self.assertEqual(self.saved()["failures"], {})

    def test_an_expired_invitation_reads_its_reason_from_github(self):
        ids = self.ids()
        for login in ("hiram", "ada"):
            self.gh.user(ids[login], login, "member", 3)
        self.run_sync("--apply")
        inv = next(iter(self.gh.invitations))
        del self.gh.invitations[inv]
        self.gh.failed.append({"id": inv, "login": "carol", "failed_at": "2027-01-09T00:00:00Z",
                               "failed_reason": "Invitation expired"})
        self.run_sync("--apply")
        self.assertEqual(self.saved()["failures"][str(ids["carol"])]["reason"], "invitation expired")

    def test_an_invitation_sent_by_hand_is_canceled(self):
        ids = self.ids()
        for login, i in ids.items():
            self.gh.user(i, login, "member", 3)
        self.gh.users[4242] = "friend"
        self.gh.invitations[77] = {"invitee": 4242, "role": "direct_member", "team_ids": [1033]}
        self.gh.invitations[78] = {"invitee": 4343, "role": "admin", "team_ids": []}      # an owner's: left alone
        self.assertEqual(self.run_sync("--apply"), 0, self.out)
        self.assertEqual(self.gh.writes(), [("DELETE", f"orgs/{ORG}/invitations/77")])


class Published(Harness):
    """What every run publishes for the Observatory: actual.json and runs.jsonl, naming no one the ledger does not."""

    def actual(self):
        return json.loads((self.state / "actual.json").read_text())

    def runs(self):
        return (self.state / "runs.jsonl").read_text().splitlines()

    def test_actual_lists_the_teams_the_owners_and_every_installed_app(self):
        ids = self.ids()
        for login, i in ids.items():
            self.gh.user(i, login, "member", 3)
        self.gh.users[ids["ada"]] = "ada-renamed"                  # named by the login the ledger records
        self.gh.user(2, "owner2", "admin", 5)
        self.gh.user(3, "helper[bot]", "member", 7)
        self.gh.user(4, "stranger", "member", 3, 9)                # not on the ledger: named by no login
        self.gh.apps = ["zeta-ci", "openmasonry-rooms"]
        self.assertEqual(self.run_sync(), 0, self.out)
        doc = self.actual()
        self.assertEqual(set(doc), {"schema", "time", "teams", "owners", "apps"})
        self.assertEqual(doc["owners"], ["openmasonry", "owner2"])
        self.assertEqual(doc["apps"], ["openmasonry-rooms", "zeta-ci"])
        self.assertEqual(doc["teams"]["degree-03"], ["(not on the ledger #1)", "ada", "carol", "hiram"])
        self.assertEqual(doc["teams"]["degree-09"], ["(not on the ledger #1)"])
        self.assertEqual((doc["teams"]["degree-05"], doc["teams"]["degree-07"]), (["owner2"], ["helper[bot]"]))
        text = (self.state / "actual.json").read_text()
        for absent in ("stranger", "ada-renamed", str(ids["ada"]), "github_id"):
            self.assertNotIn(absent, text)
        from openmasonry import observatory                        # the form the Observatory reads
        self.assertEqual(observatory.compare({k: [] for k in range(1, 34)}, doc)["apps"], doc["apps"])

    def test_more_than_a_page_of_installations_is_read(self):
        self.ids()
        self.gh.apps = [f"app-{n:03d}" for n in range(130)]
        self.assertEqual(self.run_sync(), 0, self.out)
        self.assertEqual(len(self.actual()["apps"]), 130)

    def test_installations_that_cannot_be_read_refuse_the_run(self):
        self.ids()
        real = self.gh.request
        self.gh.request = lambda m, p, b=None: ((403, {}, {"message": "Resource not accessible by integration"})
                                                if "/installations" in p else real(m, p, b))
        self.assertEqual(self.run_sync("--apply"), 1)
        self.assertIn("reading the organization", self.out[-1])
        self.assertEqual(self.gh.writes(), [])

    def test_the_run_log_is_appended_and_names_no_one(self):
        ids = self.ids()
        self.gh.user(2000, "stray0", "member", 1)
        self.assertEqual(self.run_sync(), 0, self.out)
        first = self.runs()
        self.assertEqual(len(first), 1)
        self.assertEqual(self.run_sync("--apply"), 0, self.out)
        for inv in list(self.gh.invitations):
            self.gh.accept(inv)
        self.assertEqual(self.run_sync("--apply"), 0, self.out)
        lines = self.runs()
        self.assertEqual(lines[:1], first)                         # appended: earlier lines are never rewritten
        self.assertEqual(len(lines), 3)
        runs = [json.loads(x) for x in lines]
        self.assertEqual([r["result"] for r in runs], ["dry-run", "applied", "applied"])
        self.assertEqual(runs[0]["actions"], {"invite": {"planned": 3}, "remove": {"planned": 1}})
        self.assertEqual(runs[1]["actions"], {"invite": {"done": 3}, "remove": {"done": 1}})
        self.assertEqual(runs[2]["actions"], {"invitation": {"accepted": 3}})
        self.assertEqual((runs[1]["additions"], runs[1]["removals"], runs[1]["apply"]), (3, 1, True))
        self.assertTrue(all(set(r) <= set(sync.PUBLIC_RUN) | {"actions"} for r in runs))
        text = "\n".join(lines)
        for absent in ("stray0", "hiram", "ada", "carol", "openmasonry-org", *map(str, ids.values()), "2000"):
            self.assertNotIn(f'"{absent}"', text)
            self.assertNotIn(f": {absent},", text)

    def test_a_refused_run_is_logged_without_its_reason(self):
        self.ids()
        del self.gh.teams["degree-17"]
        self.assertEqual(self.run_sync("--apply"), 1)
        run = json.loads(self.runs()[-1])
        self.assertEqual((run["result"], run["actions"]), ("refused", {}))
        self.assertNotIn("reason", run)
        self.assertNotIn("degree-17", self.runs()[-1])

    def test_the_run_line_counts_what_waits_for_a_later_run(self):
        self.ids()
        for i in range(5):
            self.gh.user(2000 + i, f"stray{i}", "member", 1)
        self.assertEqual(self.run_sync("--apply"), 0, self.out)
        run = json.loads(self.runs()[-1])
        self.assertEqual((run["removals"], run["deferred"], run["actions"]["remove"]), (5, 2, {"done": 3, "deferred": 2}))


class Guards(Harness):
    def test_removals_beyond_the_mass_guard_wait_for_a_later_run(self):
        self.ids()
        for i in (9, 3, 0, 7, 1, 5, 2, 8, 6, 4):
            self.gh.user(2000 + i, f"stray{i}", "member", 1 + i % 2)   # ten people who are not on the roll
        removed = lambda: sorted(p.rsplit("/", 1)[1] for m, p in self.gh.writes() if m == "DELETE")
        self.assertEqual(self.run_sync("--apply"), 0, self.out)
        self.assertEqual(removed(), ["stray0", "stray2", "stray4"])     # in order: team, then login
        self.assertEqual(len(self.gh.invitations), 3)                   # the additions were within the guard
        self.assertTrue(any("0 addition(s) and 7 removal(s) wait for a later run" in line for line in self.out), self.out)
        self.assertEqual(sum(r.get("result") == "deferred" for r in self.log()), 7)
        self.assertEqual(self.log()[-1]["result"], "applied")
        self.assertFalse(any(line.startswith("This run used --force-mass") for line in self.out))
        self.assertEqual(self.run_sync("--apply"), 0, self.out)        # the next run takes the next three
        self.assertEqual(removed(), ["stray0", "stray1", "stray2", "stray4", "stray6", "stray8"])
        self.assertEqual(self.run_sync("--apply", "--force-mass"), 0, self.out)
        self.assertEqual(len(removed()), 10)
        note = next(line for line in self.out if line.startswith("This run used --force-mass"))
        self.assertIn("bin/om correct note --action other --target openmasonry-org --rule ops/rooms/README.md#the-guards",
                      note)
        self.assertTrue(self.log()[-1]["note_required"])

    def test_additions_beyond_the_mass_guard_wait_for_a_later_run(self):
        ids = self.ids()
        from unittest import mock
        with mock.patch.object(sync, "MASS_FLOOR", 2):
            self.assertEqual(self.run_sync(), 0, self.out)             # a dry run shows the same split
            self.assertEqual({r["login"]: r["result"] for r in self.log() if r.get("op") == "invite"},
                             {"ada": "planned", "carol": "planned", "hiram": "deferred"})
            self.assertEqual(self.run_sync("--apply"), 0, self.out)
            self.assertEqual(sorted(v["invitee"] for v in self.gh.invitations.values()),
                             sorted([ids["ada"], ids["carol"]]))
            self.assertEqual(self.run_sync("--apply"), 0, self.out)
            self.assertEqual(len(self.gh.invitations), 3)

    def test_the_order_of_the_mass_guard_is_fixed(self):
        plan = [{"op": "invite", "team": "degree-05", "login": "bob", "id": 2},
                {"op": "invite", "team": "degree-03", "login": "Zed", "id": 3},
                {"op": "move", "team": "degree-03", "login": "amy", "from": []},
                {"op": "move", "team": "degree-04", "login": "kim", "from": ["degree-03"]},   # an advance: not counted
                {"op": "remove", "login": "x2", "id": 9}, {"op": "cancel", "login": "", "invitation": 4},
                {"op": "remove", "login": "x1", "id": 8}]
        self.assertEqual(sync.mass_defer(plan, 1), (2, 2))
        self.assertEqual([a["login"] for a in plan if not a.get("deferred")], ["amy", "kim", "", ])

    def test_the_limit_is_ten_percent_of_the_people_in_the_teams(self):
        self.assertEqual([sync.mass_limit(n) for n in (0, 10, 30, 31, 100, 1000)], [3, 3, 3, 4, 10, 100])

    def test_invitations_are_capped_per_run_and_per_day(self):
        state = {"invitations": {}}
        rows = [{"op": "invite", "result": "done", "time": ledger.iso(self.c.now - timedelta(hours=h))}
                for h in range(48)]
        self.assertEqual(sync.invites_today(state, rows, self.c.now), 24)

    def test_invitations_beyond_the_cap_wait_for_a_later_run(self):
        self.ids()
        from unittest import mock
        with mock.patch.object(sync, "INVITES_PER_RUN", 2):
            self.assertEqual(self.run_sync("--apply"), 0, self.out)
            self.assertEqual(len(self.gh.invitations), 2)
            self.assertTrue(any("1 invitation(s) wait for a later run" in line for line in self.out))
            self.assertEqual(sum(r.get("result") == "deferred" for r in self.log()), 1)
        with mock.patch.object(sync, "INVITES_PER_DAY", 2):           # two already sent in the last 24 hours
            self.assertEqual(self.run_sync("--apply"), 0, self.out)
            self.assertEqual(len(self.gh.invitations), 2)
        self.assertEqual(self.run_sync("--apply"), 0, self.out)
        self.assertEqual(len(self.gh.invitations), 3)

    def test_a_rollback_of_the_ledger_is_refused(self):
        self.ids()
        self.c.add("work", "ada", {"ref": "https://example.org/w"}, days=1)
        self.assertEqual(self.run_sync(), 0, self.out)
        self.c.entries.pop()                                      # the canonical ledger lost its last entry…
        self.c.add("work", "carol", {"ref": "https://example.org/x"})   # …and holds another one at its seq
        self.assertEqual(self.run_sync("--apply"), 1)
        self.assertIn("moved backwards (rollback", self.out[-1])
        self.assertEqual([c for c in self.gh.calls if c[0] != "GET"], [])
        self.c.entries.pop()                                       # a ledger that is merely shorter: behind
        self.assertEqual(self.run_sync("--apply"), 1)
        self.assertIn("moved backwards (behind", self.out[-1])

    def test_an_invalid_empty_or_future_ledger_is_refused(self):
        self.c.entries[0] = dict(self.c.entries[0], sig="forged")
        self.assertEqual(self.run_sync(), 1)
        self.assertIn("the ledger is invalid", self.out[-1])
        self.c.entries = []
        self.assertEqual(self.run_sync(), 1)
        self.assertIn("the ledger is empty", self.out[-1])
        self.c = lodge()
        self.assertEqual(self.run_sync(when=ledger.iso(self.c.now - DAY)), 1)
        self.assertIn("ahead of the clock", self.out[-1])
        self.assertEqual(self.gh.calls, [])

    def test_a_missing_room_team_is_refused(self):
        del self.gh.teams["degree-17"]
        self.assertEqual(self.run_sync(), 1)
        self.assertIn("lacks the room teams degree-17", self.out[-1])

    def test_retry_after_is_honored(self):
        waits = []
        api = sync.Api(self.gh, ORG, pace=1.0, sleep=waits.append, clock=lambda: 100.0)
        self.gh.script = [(429, {"retry-after": "7"}, {"message": "slow down"}),
                          (403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "130"}, {})]
        self.assertEqual(api.pages(f"orgs/{ORG}/teams")[0]["slug"], "admins")
        self.assertEqual(waits[:4], [7, 1.0, 31, 1.0])
        self.assertEqual(len(self.gh.calls), 3)

    def test_a_custodian_account_is_required(self):
        out = []
        self.assertEqual(sync.run(["--state", str(self.state)], transport=self.gh, out=out.append), 1)
        self.assertIn("--custodian", out[0])

    def test_gh_include_output_is_parsed(self):
        status, headers, data = sync.parse_include('HTTP/2.0 429 Too Many\r\nRetry-After: 3\r\n\r\n{"message":"x"}')
        self.assertEqual((status, headers["retry-after"], data), (429, "3", {"message": "x"}))
        self.assertEqual(sync.parse_include("HTTP/2.0 204 No Content\n\n")[:1], (204,))
        self.assertEqual(sync.parse_include("", "gh: not logged in")[0], 0)


class Templates(unittest.TestCase):
    """The two workflows kept as templates under ops/: what they may and may not do."""

    def test_the_ops_workflow(self):
        text = (REPO / "ops" / "rooms" / "ops-workflow.yml").read_text(encoding="utf-8")
        head = text.split("\njobs:\n", 1)[0]
        self.assertIn("  schedule:\n", head)
        self.assertIn("  workflow_dispatch:\n", head)
        self.assertNotIn("pull_request", text)
        self.assertEqual(re.findall(r"(?m)^permissions:\n((?:  .*\n)+)", text), ["  contents: write          # only to commit the state directory back to this repository\n"])
        self.assertEqual(re.findall(r"uses: (\S+)", text), ["actions/create-github-app-token@64ab729a6294000f5aa4a4bc0b73d1f32bc45510"])
        self.assertRegex(text, r"uses: actions/create-github-app-token@[0-9a-f]{40} # v\d+\.\d+\.\d+\n")
        self.assertIn("python3 -P ops/rooms/sync.py", text)
        self.assertIn("owner: openmasonry-org", text)
        for bad in ("upload-artifact", "actions/cache", "secrets.GITHUB_TOKEN", "GITHUB_SHA"):
            self.assertNotIn(bad, text)
        steps = dict(re.findall(r"(?ms)^      - name: ([^\n]+)\n(.*?)(?=^      - name: |\Z)", text.split("\njobs:\n", 1)[1]))
        ops = next(v for k, v in steps.items() if k.startswith("Check out ops"))
        self.assertIn('refs/heads/${REF}', ops)                         # the state at the tip of its branch
        canonical = next(v for k, v in steps.items() if k.startswith("Check out the canonical"))
        self.assertEqual(canonical.count("fetch --quiet --no-tags --depth 1 origin refs/heads/main"), 2)
        publish = next(v for k, v in steps.items() if k.startswith("Publish"))
        self.assertIn("if: always() && steps.commit.outcome == 'success' && vars.ROOMS_PUBLIC_REPO != ''", publish)
        self.assertIn("secrets.ROOMS_PUBLISH_TOKEN", publish)
        self.assertEqual(text.count("secrets.ROOMS_PUBLISH_TOKEN"), 1)  # no other step holds it
        self.assertEqual(sorted(set(re.findall(r"state/rooms/([A-Za-z.]+)", publish))), ["actual.json", "runs.jsonl"])
        for private in ("state.json", "log.jsonl", "state/rooms/*", "state/rooms/ ", "-r "):
            self.assertNotIn(private, publish)
        self.assertIn("cmp -s", publish)                                 # runs.jsonl only ever grows
        self.assertNotIn("--force", publish)

    def test_the_pages_workflow(self):
        text = (REPO / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        head, jobs = text.split("\njobs:\n", 1)
        triggers = head.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertEqual(re.findall(r"(?m)^  ([a-z_]+):", triggers), ["push", "schedule", "workflow_run", "workflow_dispatch"])
        self.assertIn("\npermissions: {}\n", head)
        build, deploy = jobs.split("\n  deploy:\n", 1)
        self.assertNotIn("pages: write", build)
        self.assertNotIn("id-token", build)
        self.assertIn("      pages: write\n      id-token: write\n", deploy)
        self.assertIn("git fetch --quiet --no-tags --depth 1 origin refs/heads/main", build)
        self.assertNotIn("head_sha", text)
        self.assertNotIn("head_branch", text)
        self.assertNotIn("judge:", jobs)
        self.assertIn('--rooms-actual "$RUNNER_TEMP/rooms/actual.json"', build)      # the sync's files, when published
        self.assertIn("vars.ROOMS_PUBLIC_REPO", build)
        for bad in ("secrets.", "extraheader", "github.token", "GH_TOKEN"):             # fetched with no credentials
            self.assertNotIn(bad, build)
        self.assertNotIn("<pin-by-sha>", text)                       # every action pinned by a full commit SHA
        self.assertEqual(re.findall(r"uses: ([\w./-]+)@([0-9a-f]{40}) # v\d+\.\d+\.\d+\n", text),
                         [("actions/upload-pages-artifact", "fc324d3547104276b827a68afc52ff2a11cc49c9"),
                          ("actions/deploy-pages", "368f82528645a54fb793d4d04e342629a3f51346")])
        self.assertEqual(text.count("uses: "), 2)
        self.assertFalse((REPO / "ops" / "observatory" / "pages-workflow.yml").exists())   # one source of truth


if __name__ == "__main__":
    unittest.main()
