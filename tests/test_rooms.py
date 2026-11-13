"""The rooms rule (SPEC section 15): who reads which room, and the plan that makes the teams match it.

Pure functions over a state and plain dicts: no GitHub, no network.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from datetime import timedelta
from pathlib import Path

from openmasonry import rooms
from openmasonry.rooms import readers, room_access, sync_plan, team, team_degree
from tests.test_custodian import correct, lodge, withdraw
from tests.test_protocol import T0
from tests.test_strict import hand_state, mk, tmpdir, write_ledger

REPO = Path(__file__).resolve().parents[1]
DAY = timedelta(days=1)


def ops(plan) -> list[tuple]:
    return [(a["op"], a["id"], a.get("team"), tuple(a.get("from", ()))) for a in plan]


class Access(unittest.TestCase):
    def test_active_members_read_their_degree_and_dormant_ones_too(self):
        old = T0 - 800 * DAY
        st = hand_state(mk("amy", 5), mk("bo", 1), mk("cy", 3, t=old, activity=[old]))
        self.assertTrue(st.members["cy"].dormant(T0))
        self.assertEqual(room_access(st, T0), {"amy": 5, "bo": 1, "cy": 3})

    def test_suspended_expelled_departed_and_voided_members_read_nothing(self):
        st = hand_state(mk("amy", 5), mk("bo", 2, status="suspended", suspended_until=T0 + DAY),
                        mk("cy", 3, status="expelled"), mk("di", 3, status="departed"), mk("ed", 1, status="voided"))
        self.assertEqual(room_access(st, T0), {"amy": 5})
        self.assertEqual(room_access(st, T0 + DAY), {"amy": 5, "bo": 2})      # a served suspension: access returns

    def test_a_room_hold_removes_access_while_it_is_in_force(self):
        c = lodge()
        h = correct(c, "hold_room", {"login": "carol"}, "identity_fraud", days=1)
        st = c.state()
        self.assertEqual(room_access(st, c.now), {"ada": 3, "hiram": 3})
        self.assertEqual(room_access(st, c.now + 14 * DAY), {"ada": 3, "carol": 3, "hiram": 3})   # it lapses
        withdraw(c, h, days=2)
        self.assertIn("carol", room_access(c.state(), c.now))

    def test_room_k_is_read_by_every_degree_from_k_up(self):
        r = readers({"amy": 5, "bo": 1, "cy": 33})
        self.assertEqual(len(r), 33)
        self.assertEqual(r[1], ["amy", "bo", "cy"])
        self.assertEqual(r[2], ["amy", "cy"])
        self.assertEqual(r[5], ["amy", "cy"])
        self.assertEqual(r[6], ["cy"])
        self.assertEqual(r[33], ["cy"])

    def test_team_names(self):
        self.assertEqual(team(1), "degree-01")
        self.assertEqual(team(33), "degree-33")
        for bad in (0, 34, "1", True):
            with self.assertRaises(ValueError):
                team(bad)
        self.assertEqual(team_degree("degree-07"), 7)
        for bad in ("degree-7", "degree-34", "degree-00", "Degree-01", "admins", "degree-01x", 3):
            self.assertIsNone(team_degree(bad))

    def test_last_signed_reads_member_entries_only(self):
        c = lodge()
        correct(c, "hold_room", {"login": "carol"}, "identity_fraud", days=1)
        c.add("work", "ada", {"ref": "https://example.org/w"}, days=1)
        st = c.state()
        got = rooms.last_signed(st, c.entries)
        self.assertEqual(set(got), {"hiram", "ada"})                # warden (a custodian) is not a member
        self.assertEqual(got["ada"], c.now)


class Plan(unittest.TestCase):
    IDS = {"amy": 11, "bo": 12, "cy": 13}

    def plan(self, desired, actual=None, pending=(), history=None, protected=(), ids=None, signed=None):
        return sync_plan(desired, actual or {}, list(pending), history or {}, set(protected), ids or self.IDS, signed)

    def test_newcomers_are_invited_by_id_with_their_team(self):
        p = self.plan({"amy": 3, "bo": 1})
        self.assertEqual(ops(p), [("invite", 11, "degree-03", ()), ("invite", 12, "degree-01", ())])

    def test_a_member_in_the_right_team_is_left_alone(self):
        self.assertEqual(self.plan({"amy": 3}, {11: {"login": "amy", "teams": [3], "member": True}}), [])

    def test_an_advance_adds_the_new_team_before_leaving_the_old(self):
        p = self.plan({"amy": 4}, {11: {"login": "amy", "teams": [3], "member": True}})
        self.assertEqual(ops(p), [("move", 11, "degree-04", ("degree-03",))])
        p = self.plan({"amy": 4}, {11: {"login": "amy", "teams": [], "member": True}})    # in the org, no team
        self.assertEqual(ops(p), [("move", 11, "degree-04", ())])
        p = self.plan({"amy": 4}, {11: {"login": "amy", "teams": [2, 4, 9], "member": True}})
        self.assertEqual(ops(p), [("move", 11, "degree-04", ("degree-02", "degree-09"))])

    def test_whoever_is_not_on_the_roll_is_removed_from_the_organization(self):
        p = self.plan({"amy": 3}, {11: {"login": "amy", "teams": [3], "member": True},
                                   99: {"login": "zed", "teams": [5], "member": True},
                                   98: {"login": "yo", "teams": [], "member": True}})
        self.assertEqual(ops(p), [("remove", 98, None, ()), ("remove", 99, None, ("degree-05",))])

    def test_protected_accounts_are_never_touched(self):
        actual = {1: {"login": "Owner", "teams": [], "member": True}, 2: {"login": "robot[bot]", "teams": [7], "member": True},
                  3: {"login": "openmasonry", "teams": [1], "member": True}}
        self.assertEqual(self.plan({}, actual, protected={"owner", "robot[bot]", "OpenMasonry"}), [])
        self.assertEqual(self.plan({}, actual, protected={1, 2, 3}), [])                # …by id too
        # A member who is also an owner is held, never moved or invited.
        p = self.plan({"amy": 3}, {11: {"login": "amy", "teams": [1], "member": True}}, protected={"amy"})
        self.assertEqual(ops(p), [("hold", 11, None, ())])
        pending = [{"invitation": 5, "id": None, "login": "owner", "role": "direct_member"},
                   {"invitation": 6, "id": None, "login": "x", "role": "admin"}]
        self.assertEqual(self.plan({}, pending=pending, protected={"owner"}), [])

    def test_a_renamed_login_is_matched_by_id(self):
        """amy renamed her account to amy2; somebody else took the login `amy` (id 77)."""
        actual = {11: {"login": "amy2", "teams": [3], "member": True}, 77: {"login": "amy", "teams": [3], "member": True}}
        p = self.plan({"amy": 3}, actual)
        self.assertEqual(ops(p), [("remove", 77, None, ("degree-03",))])
        self.assertEqual(p[0]["login"], "amy")
        p = self.plan({"amy": 4}, actual)
        move = next(a for a in p if a["op"] == "move")
        self.assertEqual((move["login"], move["member"]), ("amy2", "amy"))      # the call names GitHub's login

    def test_a_pending_invitation_is_waited_for_and_a_stale_one_canceled(self):
        pending = [{"invitation": 501, "id": 11, "login": "amy", "role": "direct_member"},
                   {"invitation": 502, "id": 12, "login": "bo", "role": "direct_member"},
                   {"invitation": 503, "id": None, "login": "stranger", "role": "direct_member"}]
        p = self.plan({"amy": 3}, pending=pending)
        self.assertEqual([(a["op"], a.get("invitation")) for a in p], [("cancel", 502), ("cancel", 503), ("hold", None)])
        self.assertEqual(p[0]["why"], "no longer on the roll")
        self.assertEqual(p[1]["why"], "not sent by the sync program")
        self.assertEqual(p[2]["why"], "an invitation is pending")

    def test_a_declined_or_expired_invitation_is_not_retried_until_the_member_asks(self):
        failed = T0
        history = {11: {"failed_at": failed, "reason": "declined"}}
        p = self.plan({"amy": 3}, history=history)
        self.assertEqual(ops(p), [("hold", 11, None, ())])
        self.assertIn("declined", p[0]["why"])
        self.assertEqual(ops(self.plan({"amy": 3}, history=history, signed={"amy": failed})), [("hold", 11, None, ())])
        self.assertEqual(ops(self.plan({"amy": 3}, history=history, signed={"amy": failed - DAY})), [("hold", 11, None, ())])
        self.assertEqual(ops(self.plan({"amy": 3}, history=history, signed={"amy": failed + timedelta(seconds=1)})),
                         [("invite", 11, "degree-03", ())])

    def test_a_member_without_a_github_id_is_held(self):
        p = self.plan({"amy": 3}, ids={"amy": 0})
        self.assertEqual(p, [{"op": "hold", "id": 0, "login": "amy", "member": "amy",
                              "why": "the ledger records no GitHub id for this member"}])

    def test_one_id_for_two_members_is_a_bug(self):
        with self.assertRaises(ValueError):
            self.plan({"amy": 3, "bo": 1}, ids={"amy": 11, "bo": 11})

    def test_the_order_is_remove_cancel_move_invite_hold(self):
        p = self.plan({"amy": 4, "bo": 1, "cy": 2},
                      {11: {"login": "amy", "teams": [3], "member": True}, 99: {"login": "zed", "teams": [1], "member": True}},
                      pending=[{"invitation": 9, "id": 98, "login": "old", "role": "direct_member"}],
                      history={13: {"failed_at": T0, "reason": "expired"}})
        self.assertEqual([a["op"] for a in p], ["remove", "cancel", "move", "invite", "hold"])

    def test_the_plan_is_deterministic(self):
        args = ({"bo": 1, "amy": 4, "cy": 2}, {99: {"login": "zed", "teams": [1], "member": True},
                                                11: {"login": "amy", "teams": [3], "member": True}})
        self.assertEqual(self.plan(*args), self.plan(dict(reversed(list(args[0].items()))),
                                                     dict(reversed(list(args[1].items())))))


class Command(unittest.TestCase):
    def om(self, *args, ledger_dir):
        env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
        return subprocess.run([sys.executable, "-m", "openmasonry", *args, "--ledger", str(ledger_dir)],
                              capture_output=True, text=True, env=env, cwd=REPO)

    def test_om_rooms_prints_the_roll_of_every_room(self):
        from tests.test_strict import by_key
        c = lodge()
        correct(c, "hold_room", {"login": "carol"}, "identity_fraud", days=1)
        led = write_ledger(tmpdir(self) / "entries", c.entries)
        from unittest import mock
        from openmasonry import __main__ as cli, ledger, observatory
        fake = lambda entries: ledger.replay(entries, verifier=by_key)
        out = []
        with mock.patch.object(observatory, "replay", fake), mock.patch("builtins.print", lambda *a, **k: out.append(a[0])):
            code = cli.main(["rooms", "--json", "--ledger", str(led), "--time", c.entries[-1]["time"]])
        self.assertEqual(code, 0)
        doc = json.loads(out[0])
        self.assertEqual(doc["schema"], "om.rooms/1")
        self.assertEqual(len(doc["rooms"]), 33)
        self.assertEqual(doc["rooms"][0], {"room": "degree-01", "degree": 1, "readers": ["ada", "hiram"], "count": 2})
        self.assertEqual(doc["rooms"][2]["readers"], ["ada", "hiram"])
        self.assertEqual(doc["rooms"][3]["readers"], [])
        self.assertEqual(doc["counts"], {"with_access": 2, "without_access": 1, "rooms_open": 3})
        out.clear()
        with mock.patch.object(observatory, "replay", fake), mock.patch("builtins.print", lambda *a, **k: out.append(a[0])):
            self.assertEqual(cli.main(["rooms", "--ledger", str(led), "--time", c.entries[-1]["time"]]), 0)
        self.assertIn("degree-01  2 readers: ada, hiram", out)

    def test_om_rooms_on_an_empty_ledger(self):
        r = self.om("rooms", "--json", ledger_dir=tmpdir(self))
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(r.stdout)
        self.assertEqual((doc["entries"], doc["counts"]["with_access"], len(doc["rooms"])), (0, 0, 33))


if __name__ == "__main__":
    unittest.main()
