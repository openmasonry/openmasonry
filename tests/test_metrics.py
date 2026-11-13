"""The Observatory: its numbers (om.metrics/1), its timeline, its page, and what it never measures."""
from __future__ import annotations

import contextlib
import io
import json
import re
import unittest
from datetime import timedelta
from unittest import mock

from openmasonry import __main__ as cli, ledger, observatory
from openmasonry.metrics import NEVER_MEASURED, metrics
from tests.test_custodian import correct, lodge
from tests.test_protocol import FOUNDERS, initiate, invite, petition
from tests.test_strict import by_key, tmpdir, write_ledger

DAY = timedelta(days=1)
REPO_URL = observatory.repo_url()


def busy():
    """A lodge with an admission, a refusal, a lapsed invitation, a departure, an exam, a hold and a note."""
    c = lodge()
    initiate(c, "alice")
    petition(c, "bob", days=1)
    c.add("vouch", "ada", {"candidate": "bob"})
    c.add("ballot_open", "hiram", {"id": "adm-bob", "kind": "admission", "subject": {"candidate": "bob"}})
    c.vote("adm-bob", {f: "no" for f in FOUNDERS})
    invite(c, "cid", days=1)                                          # never petitions
    c.exam("alice", 2, days=31)
    correct(c, "hold_room", {"login": "carol"}, "identity_fraud", days=1)
    correct(c, "note", {"action": "lock", "target": "issue#3", "rule": "docs/governance/CUSTODIAN.md#10"})
    c.add("depart", "alice", {}, days=1)
    c.now += 40 * DAY
    return c


def strings(doc) -> list[str]:
    """Every key and every string value of a JSON document."""
    out = []
    if isinstance(doc, dict):
        for k, v in doc.items():
            out.append(k)
            out += strings(v)
    elif isinstance(doc, list):
        for v in doc:
            out += strings(v)
    elif isinstance(doc, str):
        out.append(doc)
    return out


def keys(doc) -> list[str]:
    if isinstance(doc, dict):
        return [k for k, v in doc.items()] + [x for v in doc.values() for x in keys(v)]
    if isinstance(doc, list):
        return [x for v in doc for x in keys(v)]
    return []


def never_measured(test, doc, st) -> None:
    """No login, no GitHub id, no key that names a ranking, a profile, an examiner's rate, room activity, an
    hour or a weekday, an address or a target, and no list of names anywhere in `doc`."""
    logins = {m.lower() for m in st.members} | {c.lower() for c in st.custodians} | {"alice", "bob", "cid"}
    for s in strings(doc):
        test.assertNotIn(s.lower(), logins, f"the metrics name {s!r}")
    text = json.dumps(doc)
    for m in st.members.values():
        test.assertIsNone(re.search(rf"\b{m.github_id}\b", text), f"the metrics hold the GitHub id of {m.login}")
    for k in keys(doc):
        for word in re.split(r"[_\W]+", k.lower()):
            test.assertNotIn(word, NEVER_MEASURED, f"key {k!r}")

    def no_names(d, path="m"):
        if isinstance(d, list):
            test.assertFalse(any(isinstance(x, str) for x in d), f"{path} is a list of names")
            for i, x in enumerate(d):
                no_names(x, f"{path}[{i}]")
        elif isinstance(d, dict):
            for k, v in d.items():
                no_names(v, f"{path}.{k}")
    no_names(doc)


class Metrics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = busy()
        cls.st = cls.c.state()
        cls.m = metrics(cls.st, cls.c.entries, cls.c.now)

    def test_the_numbers(self):
        m = self.m
        self.assertEqual((m["schema"], m["founded"], m["head"]), ("om.metrics/1", True, self.st.head))
        self.assertEqual(m["chain"]["height"], len(self.c.entries))
        self.assertEqual(sum(sum(v.values()) for v in m["chain"]["entries_per_month"].values()), len(self.c.entries))
        self.assertEqual(m["members"]["by_status"], {"active": 3, "suspended": 0, "expelled": 0, "departed": 1,
                                                     "voided": 0})
        self.assertEqual(m["members"]["by_degree"], {"3": 3})
        self.assertEqual(sum(m["members"]["admissions_per_month"].values()), 4)     # three founders and alice
        self.assertEqual(sum(m["members"]["departures_per_month"].values()), 1)
        self.assertEqual(m["admission"], {"invited": 3, "petitioned": 2, "admitted": 1, "refused": 1, "undone": 0,
                                          "lapsed_invitations": 1, "lapsed_petitions": 0})
        self.assertEqual(m["ballots"]["by_kind"]["admission"]["passed"], 1)
        self.assertEqual(m["ballots"]["by_kind"]["admission"]["failed"], 1)
        self.assertEqual(m["ballots"]["turnout_by_kind"]["admission"], {"closed": 2, "mean": 1.0})
        self.assertEqual(m["exams"]["passed"], 1)
        self.assertEqual(m["exams"]["days_to_verdict"]["count"], 1)
        self.assertEqual(m["custodians"]["by_act"], {"hold_room": 1})
        self.assertEqual(m["custodians"]["notes"], 1)
        self.assertEqual(m["custodians"]["keys"], 1)
        self.assertEqual(m["custodians"]["keys_by_status"], {"live": 1})
        self.assertEqual(m["custodians"]["corrections_by_status"], {"lapsed": 1})
        self.assertEqual(m["custodians"]["next_alive_due"], ledger.iso(self.st.custodians["warden"].alive + 180 * DAY))
        self.assertEqual(m["rooms"]["with_access"], 3)                          # the hold lapsed: 14 days
        self.assertEqual(m["rooms"]["readers_per_room"]["degree-03"], 3)
        self.assertEqual(m["sponsorship"]["sponsors"], 3)

    def test_the_same_inputs_give_the_same_document(self):
        again = metrics(ledger.replay(self.c.entries, verifier=by_key), list(self.c.entries), self.c.now)
        self.assertEqual(json.dumps(again, sort_keys=True), json.dumps(self.m, sort_keys=True))

    def test_a_state_of_another_history_is_refused(self):
        with self.assertRaises(ValueError):
            metrics(self.st, self.c.entries[:-1], self.c.now)

    def test_nothing_on_the_never_measured_list(self):
        never_measured(self, self.m, self.st)

    def test_the_guard_would_catch_a_ranking_a_histogram_or_an_id(self):
        for bad in (dict(self.m, members=dict(self.m["members"], top=["hiram", "ada"])),
                    dict(self.m, activity_by_hour={"13": 4}),
                    dict(self.m, chain=dict(self.m["chain"], last_signer="carol")),
                    dict(self.m, sponsor={"n": self.st.members["ada"].github_id})):
            with self.assertRaises(AssertionError):
                never_measured(self, bad, self.st)

    def test_an_empty_ledger(self):
        m = metrics(None, [], self.c.now)
        self.assertEqual((m["schema"], m["founded"], m["head"]), ("om.metrics/1", False, None))


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = busy()
        cls.st = cls.c.state()

    def build(self, actual=None, runs=None):
        out = tmpdir(self) / "site"
        docs = observatory.build(self.st, self.c.entries, self.c.now, out, actual, runs)
        return out, docs

    def test_four_files_and_a_self_contained_page(self):
        out, docs = self.build()
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["index.html", "metrics.json", "rooms.json",
                                                                 "timeline.json"])
        page = (out / "index.html").read_text(encoding="utf-8")
        self.assertIn("<svg", page)
        self.assertIn('class="logo"', page)
        self.assertIn("prefers-color-scheme:dark", page)
        for bad in ("<script", "<link", "@import", "url(", "<iframe", "<img", "srcset", "@font-face"):
            self.assertNotIn(bad, page.lower())
        for url in re.findall(r"""(?:https?:)?//[^\s"'<>)]+""", page):
            self.assertTrue(url.startswith(REPO_URL), f"an external URL in the page: {url}")
        for m in re.findall(r'(?:href|src)="([^"]+)"', page):
            self.assertTrue(m.startswith(REPO_URL) or m in ("metrics.json", "timeline.json", "rooms.json"), m)
        self.assertIn("[a link to example.org: see timeline.json]", page)     # the work of an exam, defanged
        self.assertEqual(json.loads((out / "metrics.json").read_text())["schema"], "om.metrics/1")
        self.assertEqual(json.loads((out / "rooms.json").read_text()), docs["rooms"])

    def test_untrusted_text_is_escaped(self):
        c = lodge(name="Lodge <script>alert(1)</script>")
        out = tmpdir(self) / "site"
        observatory.build(c.state(), c.entries, c.now, out)
        page = (out / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_timeline_has_one_line_per_entry(self):
        tl = observatory.timeline(self.st, self.c.entries)
        self.assertEqual(tl["schema"], "om.timeline/1")
        self.assertEqual([e["seq"] for e in tl["entries"]], list(range(len(self.c.entries))))
        self.assertTrue(all("\n" not in e["line"] and e["line"] for e in tl["entries"]))
        self.assertTrue(tl["entries"][0]["line"].startswith("FOUND the fraternity"))
        self.assertEqual(tl["entries"][-1]["line"].split(".")[0], "LEAVE the fraternity")

    def test_actual_access_against_the_roll(self):
        actual = {"schema": "om.rooms-actual/1", "time": "2027-03-01T00:00:00Z",
                  "teams": {"degree-03": ["Hiram", "ada", "intruder"], "degree-01": [], "admins": ["x"]},
                  "owners": ["openmasonry"], "apps": ["openmasonry-rooms"]}
        _, docs = self.build(actual)
        act = docs["rooms"]["actual"]
        r1 = act["rooms"][0]
        self.assertEqual((r1["missing"], r1["extra"]), (["carol"], ["intruder"]))
        self.assertEqual(act["rooms"][3], {"room": "degree-04", "missing": [], "extra": []})
        self.assertEqual(act["unknown_teams"], ["admins"])
        self.assertEqual(act["differences"], 3 * 2 + 1)                # rooms 1..3 each, and the unknown team
        with self.assertRaises(ValueError):
            observatory.compare({}, {"teams": {}})
        with self.assertRaises(ValueError):
            observatory.compare({}, actual | {"apps": [{"slug": "x"}]})

    def test_owners_apps_and_the_run_log_beside_the_roll(self):
        actual = {"schema": "om.rooms-actual/1", "time": "2027-03-01T00:00:00Z", "teams": {"degree-03": ["hiram"]},
                  "owners": ["openmasonry"], "apps": ["openmasonry-rooms", "zeta-ci"]}
        runs = [{"time": "2027-03-01T00:17:00Z", "apply": True, "force_mass": False, "seq": 9, "head": "ab" * 32,
                 "result": "applied", "additions": 1, "removals": 0, "deferred": 0, "actions": {"invite": {"done": 1}}},
                {"time": "2027-03-01T01:17:00Z", "apply": False, "result": "refused", "actions": {},
                 "login": "ada", "reason": "about ada"}]                   # what a run line never carries is dropped
        out, docs = self.build(actual, runs)
        page = (out / "index.html").read_text(encoding="utf-8")
        roll = page.index("The roll of every room")
        beside = page.index("openmasonry-rooms, zeta-ci")
        self.assertLess(abs(beside - roll), 600)                         # owners and apps sit beside the roll
        self.assertIn("openmasonry", page[beside - 300:beside])
        self.assertIn("The log of the room sync", page)
        self.assertIn("invite done 1", page)
        self.assertNotIn("about ada", page)
        self.assertEqual(docs["rooms"]["runs"][1], {"time": "2027-03-01T01:17:00Z", "apply": False,
                                                    "result": "refused", "actions": {}})
        self.assertEqual(json.loads((out / "rooms.json").read_text())["runs"], docs["rooms"]["runs"])
        self.assertEqual(docs["rooms"]["runs"][0]["deferred"], 0)
        from tests.test_sync import sync                                  # every key a run line may carry is kept
        self.assertEqual(set(observatory.RUN_KEYS), set(sync.PUBLIC_RUN) | {"actions"})
        _, plain = self.build()
        self.assertNotIn("runs", plain["rooms"])

    def test_the_commands(self):
        led = write_ledger(tmpdir(self) / "entries", self.c.entries)
        fake = lambda entries: ledger.replay(entries, verifier=by_key)
        when = ledger.iso(self.c.now)

        def om(*args):
            out = io.StringIO()
            with mock.patch.object(observatory, "replay", fake), contextlib.redirect_stdout(out):
                code = cli.main([*args, "--ledger", str(led), "--time", when])
            return code, out.getvalue()
        code, text = om("metrics", "--json")
        self.assertEqual((code, json.loads(text)), (0, metrics(self.st, self.c.entries, self.c.now)))
        code, text = om("metrics")
        self.assertEqual(code, 0)
        self.assertIn("members of record 3", text)
        code, text = om("timeline")
        self.assertEqual((code, len(text.splitlines())), (0, len(self.c.entries)))
        code, text = om("timeline", "--json")
        self.assertEqual(len(json.loads(text)["entries"]), len(self.c.entries))
        site = tmpdir(self) / "site"
        code, text = om("observatory", "--out", str(site))
        self.assertEqual(code, 0, text)
        self.assertTrue((site / "index.html").is_file())
        bad = tmpdir(self) / "bad.json"
        bad.write_text("{}")
        code, text = om("observatory", "--out", str(tmpdir(self) / "x"), "--rooms-actual", str(bad))
        self.assertEqual(code, 1)
        self.assertIn("--rooms-actual", text)
        sync = tmpdir(self) / "rooms"                                  # actual.json and, beside it, runs.jsonl
        sync.mkdir()
        (sync / "actual.json").write_text(json.dumps({"schema": "om.rooms-actual/1", "time": when, "teams": {},
                                                      "owners": ["openmasonry"], "apps": ["openmasonry-rooms"]}))
        (sync / "runs.jsonl").write_text('{"time": "%s", "result": "dry-run", "actions": {}}\n\n' % when)
        site = tmpdir(self) / "with-actual"
        code, text = om("observatory", "--out", str(site), "--rooms-actual", str(sync / "actual.json"))
        self.assertEqual(code, 0, text)
        self.assertEqual(json.loads((site / "rooms.json").read_text())["runs"],
                         [{"time": when, "result": "dry-run", "actions": {}}])
        (sync / "runs.jsonl").write_text("not json\n")
        code, text = om("observatory", "--out", str(tmpdir(self) / "y"), "--rooms-actual", str(sync / "actual.json"))
        self.assertEqual(code, 1)
        self.assertIn("runs.jsonl", text)

    def test_an_empty_ledger_builds_a_page(self):
        out = tmpdir(self) / "site"
        observatory.build(None, [], self.c.now, out)
        self.assertIn("has not been founded", (out / "index.html").read_text())


if __name__ == "__main__":
    unittest.main()
