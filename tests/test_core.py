"""The pinned core: the manifest behind `@protocol`, the verifier's entry point, the pins of genesis
and the witness's own safeguards.

`@protocol` is the digest of an explicit list of files, the manifest `src/openmasonry/protocol.manifest`,
which is data read from the tree being checked. These tests hold that list to what it promises: the listed
Python modules import nothing but each other and the standard library, the judge runs only that code, a
change to any listed file (the list included) is unlawful until the ledger pins it, and a ratified change
of the list is accepted by the code that was there before it.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from openmasonry import canon, govern, ledger
from openmasonry.ledger import Invalid, load, replay
from tests.test_protocol import witness_subject, DECL, FOUNDERS, Chain, copy_governed, genesis_body, entry_file, entry_path
from tests.test_strict import Fast, by_key, write_ledger
from tests.test_strict import founded as fast_founded

REPO = Path(__file__).resolve().parents[1]
PACKAGE = "openmasonry"

MANIFEST_FILE = "src/openmasonry/protocol.manifest"
# What the manifest of this repository lists today, written out here independently of the file.
MANIFEST = (
    ".github/workflows/judge.yml",
    ".github/workflows/pages.yml",
    ".github/workflows/tyler.yml",
    "src/openmasonry/__init__.py",
    "src/openmasonry/beacon.py",
    "src/openmasonry/canon.py",
    "src/openmasonry/crypto.py",
    "src/openmasonry/govern.py",
    "src/openmasonry/identity.py",
    "src/openmasonry/ledger.py",
    "src/openmasonry/lot.py",
    "src/openmasonry/network.toml",
    "src/openmasonry/protocol.manifest",
    "src/openmasonry/rooms.py",
    "src/openmasonry/verify.py",
)
# The list as the file itself gives it: what the closure and the witness are held to.
LISTED = tuple((REPO / MANIFEST_FILE).read_text(encoding="ascii").splitlines())
WORKFLOWS = sorted(rel for rel in LISTED if rel.startswith(".github/workflows/"))
GENESIS_PINS = {"canon/degrees.toml", "canon/eternal.toml", "CONSTITUTION.md", "@protocol",
                "docs/governance/CUSTODIAN.md", "docs/governance/ROOMS.md"}


def tmpdir(test) -> Path:
    t = tempfile.TemporaryDirectory()
    test.addCleanup(t.cleanup)
    return Path(t.name)


def manifest_bytes(files) -> bytes:
    return "".join(f"{rel}\n" for rel in files).encode("ascii")


def write_manifest(root: Path, files) -> None:
    (root / MANIFEST_FILE).parent.mkdir(parents=True, exist_ok=True)
    (root / MANIFEST_FILE).write_bytes(manifest_bytes(files))


def listed_in(root: Path) -> tuple[str, ...]:
    return tuple((root / MANIFEST_FILE).read_text(encoding="ascii").splitlines())


def small_tree(root: Path, files=MANIFEST) -> Path:
    """A tree holding every file of `files` with short, distinct contents, and the manifest that lists them."""
    for i, rel in enumerate(files):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(f"file {i}\n".encode())
    write_manifest(root, files)
    return root


def framed(root: Path, files=None) -> str:
    """The digest, written out independently of the code under test: over `files`, else over what the
    tree's own manifest lists."""
    h = hashlib.sha256()
    for rel in listed_in(root) if files is None else files:
        path, data = rel.encode("ascii"), (root / rel).read_bytes()
        h.update(len(path).to_bytes(8, "big") + path + len(data).to_bytes(8, "big") + data)
    return h.hexdigest()


def module_name(rel: str) -> str:
    parts = Path(rel).relative_to("src").with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


PINNED_MODULES = {module_name(rel) for rel in LISTED if rel.endswith(".py")}


def imports_of(path: Path, package: str | None = PACKAGE) -> set[str]:
    """Every module a Python file can import, wherever the statement is: `import`, `from … import`
    (relative ones resolved inside `package`), `__import__("…")` and `import_module("…")`. An import
    whose target is not a literal is reported as `<dynamic>`."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if node.level != 1 or package is None:
                    found.add("<relative import outside the package>")
                    continue
                base = package
            else:
                base = None
            module = ".".join(x for x in (base, node.module) if x)
            found.add(module)
            if module == PACKAGE:                    # `from openmasonry import actions` imports a submodule
                found |= {f"{PACKAGE}.{alias.name}" for alias in node.names}
        elif isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None)
            if name in ("__import__", "import_module"):
                arg = node.args[0] if node.args else None
                found.add(arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else "<dynamic>")
    return found


def outside_the_core(modules: set[str]) -> set[str]:
    return {m for m in modules if m not in PINNED_MODULES and m.split(".")[0] not in sys.stdlib_module_names}


# ------------------------------------------------------------------ 1: the manifest and its digest ----

class Manifest(unittest.TestCase):
    def test_the_manifest_is_a_file_of_the_tree_with_the_exact_sorted_list(self):
        self.assertFalse(hasattr(govern, "PROTOCOL_FILES"))           # the list is data, not code
        self.assertEqual(govern.MANIFEST, MANIFEST_FILE)
        self.assertEqual((REPO / MANIFEST_FILE).read_bytes(), manifest_bytes(MANIFEST))
        self.assertEqual(govern.read_manifest(REPO), MANIFEST)
        self.assertEqual(govern.read_manifest(), MANIFEST)            # the default root is this repository
        self.assertEqual(LISTED, MANIFEST)
        self.assertEqual(sorted(MANIFEST), list(MANIFEST))
        self.assertIn(MANIFEST_FILE, MANIFEST)                         # the list is itself on the list
        self.assertIn("src/openmasonry/govern.py", MANIFEST)
        for rel in MANIFEST:
            path = REPO / rel
            self.assertTrue(path.is_file() and not path.is_symlink(), rel)

    def test_the_digest_frames_path_length_and_bytes_in_manifest_order(self):
        root = small_tree(tmpdir(self))
        self.assertEqual(govern.protocol_digest(root), framed(root, MANIFEST))
        self.assertNotEqual(govern.protocol_digest(root), framed(root, tuple(reversed(MANIFEST))))
        self.assertEqual(govern.protocol_digest(), framed(REPO, MANIFEST))    # the default root is this repository

    def test_the_manifest_is_read_from_the_tree_being_checked(self):
        """Another tree, another list: the code that computes the digest carries no list of its own."""
        other = (".github/workflows/deploy.yml", "docs/NOTE.md", "src/openmasonry/govern.py", MANIFEST_FILE,
                 "src/openmasonry/rules.py")
        root = small_tree(tmpdir(self), other)
        self.assertEqual(govern.read_manifest(root), other)
        self.assertEqual(govern.protocol_digest(root), framed(root, other))
        self.assertEqual(govern.stray_workflows(root), [])
        self.assertEqual(govern.read_manifest(REPO), MANIFEST)         # …and this repository's is untouched
        with mock.patch.object(govern.canon, "ROOT", root):            # also when the root is the default one
            self.assertEqual(govern.read_manifest(), other)
            self.assertEqual(govern.protocol_digest(), framed(root, other))

    def test_every_listed_file_counts_and_nothing_else_does(self):
        root = small_tree(tmpdir(self))
        before = govern.protocol_digest(root)
        for rel in ("src/openmasonry/actions.py", "src/openmasonry/__main__.py", "src/openmasonry/guide.py",
                    "bin/om", "node/witness.py", "scripts/genesis.sh", ".github/CODEOWNERS",
                    "src/openmasonry/__pycache__/ledger.cpython-312.pyc", "notes.py"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("anything\n")
        self.assertEqual(govern.protocol_digest(root), before)
        for rel in MANIFEST:
            if rel == MANIFEST_FILE:
                continue                                              # its own test, below
            original = (root / rel).read_bytes()
            (root / rel).write_bytes(original + b"#")
            self.assertNotEqual(govern.protocol_digest(root), before, rel)
            (root / rel).write_bytes(original)
        self.assertEqual(govern.protocol_digest(root), before)

    def test_the_list_itself_is_hashed(self):
        """A file added to the list, or dropped from it, changes the digest although no other byte moved."""
        root = small_tree(tmpdir(self))
        before = govern.protocol_digest(root)
        (root / "src/openmasonry/extra.py").write_text("x = 1\n")
        self.assertEqual(govern.protocol_digest(root), before)        # not listed: not read
        write_manifest(root, sorted((*MANIFEST, "src/openmasonry/extra.py")))
        added = govern.protocol_digest(root)
        self.assertNotEqual(added, before)
        self.assertEqual(added, framed(root))
        for rel in MANIFEST:
            if rel in govern.MANIFEST_REQUIRED:
                continue
            write_manifest(root, [x for x in MANIFEST if x != rel])
            dropped = govern.protocol_digest(root)                     # the file is still there, and no longer counts
            self.assertNotIn(dropped, (before, added), rel)
            (root / rel).write_bytes(b"changed at will\n")
            self.assertEqual(govern.protocol_digest(root), dropped, rel)
            small_tree(root)
        self.assertEqual(govern.protocol_digest(root), before)

    def test_a_malformed_manifest_is_an_error(self):
        good = manifest_bytes(MANIFEST)
        first, rest = MANIFEST[0], manifest_bytes(MANIFEST[1:])
        swapped = manifest_bytes((MANIFEST[1], MANIFEST[0], *MANIFEST[2:]))
        cases = [
            (b"", "must end with a line feed"),
            (good[:-1], "must end with a line feed"),
            (good.replace(b"\n", b"\r\n"), "line 1 is not a safe relative path"),
            (good + b"\n", f"line {len(MANIFEST) + 1} is not a safe relative path"),
            (b"\n" + good, "line 1 is not a safe relative path"),
            (good.replace(b"\n", b"\n\n", 1), "line 2 is not a safe relative path"),
            (b"# the pinned core\n" + good, "line 1 is not a safe relative path"),
            (f"{first} # the judge\n".encode() + rest, "line 1 is not a safe relative path"),
            (f" {first}\n".encode() + rest, "line 1 is not a safe relative path"),
            (f"{first}\t\n".encode() + rest, "line 1 is not a safe relative path"),
            (f"/{first}\n".encode() + rest, "line 1 is not a safe relative path"),
            (f"./{first}\n".encode() + rest, "line 1 is not a safe relative path"),
            (b"../outside.py\n" + good, "line 1 is not a safe relative path"),
            (good + b"src/openmasonry/x/../ledger.py\n", f"line {len(MANIFEST) + 1} is not a safe relative path"),
            (good + b"src/openmasonry//zz.py\n", f"line {len(MANIFEST) + 1} is not a safe relative path"),
            (good + b"src/openmasonry/zz/\n", f"line {len(MANIFEST) + 1} is not a safe relative path"),
            (good + b"src\\openmasonry\\zz.py\n", f"line {len(MANIFEST) + 1} is not a safe relative path"),
            (good + b"src/openmasonry/zz.py:Zone\n", f"line {len(MANIFEST) + 1} is not a safe relative path"),
            (good + "src/openmasonry/λ.py\n".encode(), "holds a byte outside ASCII"),
            (swapped, "line 2 is not after line 1"),
            (f"{first}\n".encode() + good, "line 2 is not after line 1"),            # the same path twice
            (good + b"a.py\n", f"line {len(MANIFEST) + 1} is not after line {len(MANIFEST)}"),
            (manifest_bytes(sorted((*MANIFEST, "src/openmasonry/Ledger.py"))), "lines 4 and 11 differ only by case"),
            (manifest_bytes(x for x in MANIFEST if x != MANIFEST_FILE), f"does not list {MANIFEST_FILE}"),
            (manifest_bytes(x for x in MANIFEST if x != "src/openmasonry/govern.py"),
             "does not list src/openmasonry/govern.py"),
            (good + b"z" * (64 * 1024) + b"\n", "larger than 65536 bytes"),
        ]
        st = fast_founded().state()
        for data, pattern in cases:
            with self.subTest(pattern, data=data[:40]):
                with self.assertRaisesRegex(govern.UnsafeTree, f"^{MANIFEST_FILE}: .*{pattern}"):
                    govern.parse_manifest(data)
                root = copy_governed(tmpdir(self) / "tree")
                (root / MANIFEST_FILE).write_bytes(data)
                with self.assertRaisesRegex(govern.UnsafeTree, pattern):
                    govern.protocol_digest(root)
                problems = govern.check_tree(st, root)                 # the tree is unlawful, and says why
                self.assertIn(f"@protocol: {MANIFEST_FILE}: ", problems[0])
                self.assertRegex(problems[0], pattern)
                # …and with no readable list, no workflow is a listed one
                self.assertEqual(govern.stray_workflows(root), WORKFLOWS)
        self.assertEqual(govern.parse_manifest(good), MANIFEST)
        self.assertEqual(govern.parse_manifest(manifest_bytes(sorted(govern.MANIFEST_REQUIRED))),
                         tuple(sorted(govern.MANIFEST_REQUIRED)))

    def test_a_missing_or_linked_manifest_is_an_error(self):
        root = small_tree(tmpdir(self))
        (root / MANIFEST_FILE).unlink()
        with self.assertRaisesRegex(govern.UnsafeTree, f"{MANIFEST_FILE} is missing"):
            govern.protocol_digest(root)
        elsewhere = root / "elsewhere.manifest"
        elsewhere.write_bytes(manifest_bytes(MANIFEST))
        (root / MANIFEST_FILE).symlink_to(elsewhere)
        with self.assertRaisesRegex(govern.UnsafeTree, "symlink"):
            govern.protocol_digest(root)
        with self.assertRaisesRegex(govern.UnsafeTree, "symlink"):
            govern.read_manifest(root)

    def test_bytes_cannot_move_between_files_unnoticed(self):
        root = small_tree(tmpdir(self))
        a, b = root / MANIFEST[1], root / MANIFEST[2]
        a.write_bytes(b"one\ntwo\n")
        b.write_bytes(b"three\n")
        before = govern.protocol_digest(root)
        a.write_bytes(b"one\n")
        b.write_bytes(b"two\nthree\n")
        self.assertNotEqual(govern.protocol_digest(root), before)

    def test_a_missing_file_is_an_error(self):
        for rel in MANIFEST:
            root = small_tree(tmpdir(self))
            (root / rel).unlink()
            with self.assertRaisesRegex(govern.UnsafeTree, f"{rel} is missing"):
                govern.protocol_digest(root)

    def test_a_symlink_or_a_directory_is_an_error(self):
        root = small_tree(tmpdir(self))
        target = root / "elsewhere.py"
        target.write_text("x = 1\n")
        victim = root / "src/openmasonry/lot.py"
        victim.unlink()
        victim.symlink_to(target)
        with self.assertRaisesRegex(govern.UnsafeTree, "symlink"):
            govern.protocol_digest(root)
        victim.unlink()
        victim.mkdir()
        with self.assertRaisesRegex(govern.UnsafeTree, "not a regular file"):
            govern.protocol_digest(root)

    def test_a_symlinked_directory_on_the_way_is_an_error(self):
        root = small_tree(tmpdir(self))
        real = root / "real"
        shutil.move(root / "src" / "openmasonry", real)
        (root / "src" / "openmasonry").symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(govern.UnsafeTree, "symlink"):
            govern.protocol_digest(root)

    def test_one_definition_with_no_git_and_no_directory_walk(self):
        for gone in ("protocol_files", "_git_tracked", "_ignore_patterns", "PROTOCOL_DIRS", "DEFAULT_IGNORES",
                     "PROTOCOL_FILES"):
            self.assertFalse(hasattr(govern, gone), gone)
        root = small_tree(tmpdir(self))
        before = govern.protocol_digest(root)
        (root / ".git").mkdir()                              # a checkout and an unpacked archive digest alike
        (root / ".gitignore").write_text("src/\n")
        with mock.patch("subprocess.run", side_effect=AssertionError("the digest must not run a program")), \
                mock.patch("pathlib.Path.rglob", side_effect=AssertionError("the digest must not walk a directory")), \
                mock.patch("pathlib.Path.iterdir", side_effect=AssertionError("the digest must not list a directory")):
            self.assertEqual(govern.protocol_digest(root), before)

    def test_the_digest_command_prints_it(self):
        from openmasonry.__main__ import main
        with mock.patch("builtins.print") as out:
            self.assertEqual(main(["digest"]), 0)
        out.assert_called_once_with(govern.protocol_digest())


# ------------------------------------------------------------------ 2: the import closure ----

class ImportClosure(unittest.TestCase):
    def test_pinned_modules_import_only_pinned_modules_and_the_standard_library(self):
        modules = [rel for rel in govern.read_manifest(REPO) if rel.endswith(".py")]
        self.assertEqual(len(modules), 10)
        for rel in modules:
            self.assertEqual(outside_the_core(imports_of(REPO / rel)), set(), rel)

    def test_the_check_would_catch_convenience_code(self):
        main = outside_the_core(imports_of(REPO / "src/openmasonry/__main__.py"))
        self.assertIn("openmasonry.actions", main)
        self.assertIn("openmasonry.heraldry", main)
        probe = tmpdir(self) / "probe.py"
        probe.write_text("def f():\n    from . import guide\n    from .actions import propose\n"
                         "    import openmasonry.__main__\n    from openmasonry import heraldry\n"
                         "    __import__('yaml')\n    import importlib\n    importlib.import_module(name)\n")
        self.assertEqual(outside_the_core(imports_of(probe)),
                         {"openmasonry.guide", "openmasonry.actions", "openmasonry.__main__", "openmasonry.heraldry",
                          "yaml", "<dynamic>"})

    def test_the_witness_signs_with_pinned_code_only(self):
        used = {m for m in imports_of(REPO / "node/witness.py", package=None) if m.split(".")[0] == PACKAGE}
        self.assertTrue(used)
        self.assertEqual(used - PINNED_MODULES, set())

    def test_running_the_verifier_loads_nothing_outside_the_core(self):
        led = tmpdir(self) / "led"
        led.mkdir()
        probe = ("import json, runpy, sys\n"
                 f"sys.argv = ['verify', '--ledger', {str(led)!r}, '--json']\n"
                 "try:\n    runpy.run_module('openmasonry.verify', run_name='__main__')\n"
                 "except SystemExit as stop:\n    code = stop.code\n"
                 "print(json.dumps({'code': code, 'loaded': sorted(m for m in sys.modules if m.split('.')[0] == 'openmasonry')}))\n")
        r = subprocess.run([sys.executable, "-P", "-c", probe], capture_output=True, text=True,
                           env={**os.environ, "PYTHONPATH": str(REPO / "src")})
        self.assertEqual(r.returncode, 0, r.stderr)
        report, tail = r.stdout.rsplit("\n{", 1)
        tail = json.loads("{" + tail)
        self.assertEqual(tail["code"], 0)
        self.assertEqual(json.loads(report)["schema"], "om.verify/1")
        self.assertEqual(set(tail["loaded"]) - PINNED_MODULES, set())
        self.assertIn("openmasonry.govern", PINNED_MODULES)


# ------------------------------------------------------------------ 3: the pinned entry point ----

class EntryPoint(unittest.TestCase):
    def run_verify(self, *args):
        return subprocess.run([sys.executable, "-P", "-m", "openmasonry.verify", *args], capture_output=True, text=True,
                              env={**os.environ, "PYTHONPATH": str(REPO / "src")})

    def args(self, led: Path, **flags) -> argparse.Namespace:
        a = argparse.Namespace(ledger=led, tree=False, online=False, clock_since=None, root=None, pr_author=None,
                               since=None, json=True)
        for k, v in flags.items():
            setattr(a, k, v)
        return a

    def test_it_runs_as_a_module_with_the_exit_codes_and_the_json_contract(self):
        tmp = tmpdir(self)
        c = Chain(tmp)
        c.add("genesis", "hiram", genesis_body(c, ["hiram"]))
        led = write_ledger(tmp / "led", c.entries)
        r = self.run_verify("--ledger", str(led), "--tree", "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rep = json.loads(r.stdout)
        self.assertEqual(sorted(rep), ["entries", "head", "message", "problems", "schema", "state_sha256", "state_version", "valid", "warnings"])
        self.assertEqual(rep["state_sha256"], replay(c.entries).digest())
        self.assertEqual((rep["schema"], rep["valid"], rep["entries"], rep["problems"]), ("om.verify/1", True, 1, []))
        self.assertEqual(rep["head"], ledger.entry_hash(c.entries[0]))
        self.assertTrue(rep["message"].startswith("VALID — "))
        e = json.loads(entry_path(led, 0).read_text())
        e["body"]["name"] = "Another Lodge"
        entry_file(led, 0).write_text(json.dumps(e))
        r = self.run_verify("--ledger", str(led))
        self.assertEqual(r.returncode, 1)
        self.assertTrue(r.stdout.startswith("INVALID — entry 0: bad signature"), r.stdout)

    def test_it_takes_the_same_flags_as_before(self):
        from openmasonry import verify
        a = verify.parser().parse_args(["--ledger", "x", "--tree", "--root", "pr", "--online", "--clock-since", "3",
                                        "--pr-author", "ada", "--since", "3", "--json"])
        self.assertEqual((a.ledger, a.tree, a.root, a.online, a.clock_since, a.pr_author, a.since, a.json),
                         (Path("x"), True, Path("pr"), True, 3, "ada", 3, True))
        d = verify.parser().parse_args([])
        self.assertEqual((d.ledger, d.tree, d.root, d.online, d.clock_since, d.pr_author, d.since, d.json),
                         (canon.ROOT / "ledger" / "entries", False, None, False, None, None, None, False))
        self.assertEqual(self.run_verify("--no-such-flag").returncode, 2)

    def test_om_verify_delegates_to_it(self):
        from openmasonry import __main__ as cli
        from openmasonry import verify
        self.assertFalse(hasattr(cli, "verify_report"))
        seen = []

        def fake(a):
            seen.append(a)
            return {"schema": "om.verify/1", "valid": False, "entries": 0, "head": None, "message": "INVALID — x",
                    "problems": ["x", "y"]}
        with mock.patch.object(verify, "verify_report", fake), mock.patch("builtins.print") as out:
            code = cli.main(["verify", "--ledger", "somewhere", "--tree", "--clock-since", "2"])
        self.assertEqual(code, 1)
        self.assertEqual((seen[0].ledger, seen[0].tree, seen[0].clock_since), (Path("somewhere"), True, 2))
        self.assertEqual([c.args[0] for c in out.call_args_list], ["INVALID — x", "  also: y"])

    def test_the_gates_still_answer_in_order(self):
        from openmasonry import verify
        c = fast_founded()
        c.add("work", "ada", {"ref": "https://example.org/a"})
        led = write_ledger(tmpdir(self) / "led", c.entries)
        with mock.patch.object(verify, "replay", lambda entries, **kw: replay(entries, verifier=by_key, **kw)):
            self.assertTrue(verify.verify_report(self.args(led))["valid"])
            self.assertTrue(verify.verify_report(self.args(led, tree=True))["valid"])
            r = verify.verify_report(self.args(led, clock_since=0, tree=True))
            self.assertTrue(r["message"].startswith("STALE OR FUTURE TIME — "), r["message"])
            r = verify.verify_report(self.args(led, pr_author="hiram", since=1))
            self.assertTrue(r["message"].startswith("WRONG AUTHOR OR KEY — "), r["message"])
            r = verify.verify_report(self.args(led, pr_author="hiram"))
            self.assertEqual(r["problems"], ["usage"])
        empty = tmpdir(self)
        self.assertEqual(verify.verify_report(self.args(empty))["message"], "ledger is empty (no genesis yet)")


# ------------------------------------------------------------------ 3b: the workflows ----

def python_calls(workflow: str) -> list[str]:
    text = (REPO / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines()
            if ("python " in line or "python3 " in line) and not line.lstrip().startswith("#")
            and "python-version" not in line and "python3 --version" not in line]


class Workflows(unittest.TestCase):
    def test_the_judge_runs_nothing_but_the_pinned_entry_point(self):
        calls = python_calls("judge.yml")
        self.assertTrue(calls)
        for line in calls:
            self.assertIn("python3 -P -m openmasonry.verify ", line + " ")
        text = (REPO / ".github/workflows/judge.yml").read_text(encoding="utf-8")
        self.assertIn("python3 -P -m openmasonry.verify --ledger pr/ledger/entries --tree --root pr --base-root base --online \\\n"
                      '            --clock-since "$BASE_LEN" --pr-author "$PR_AUTHOR" --since "$BASE_LEN" '
                      '--pr-author-id "$PR_AUTHOR_ID" \\\n'
                      '            --anchors-changed "$RUNNER_TEMP/anchors-changed"\n', text)
        self.assertIn("PR_AUTHOR_ID: ${{ github.event.pull_request.user.id }}", text)
        self.assertIn("PYTHONPATH: base/src", text)
        self.assertNotIn("pip install", text)

    def test_the_judge_only_judges_pull_requests_into_main(self):
        text = (REPO / ".github/workflows/judge.yml").read_text(encoding="utf-8")
        head = text.split("permissions:", 1)[0]
        self.assertIn("  pull_request_target:\n    branches: [main]\n    types: [opened, synchronize, reopened, ready_for_review]\n",
                      head)
        self.assertNotIn("  pull_request:", text)

    def test_the_judge_keeps_every_gate(self):
        text = (REPO / ".github/workflows/judge.yml").read_text(encoding="utf-8")
        for gate in ("Ledger entries may only be added, never modified, renamed or deleted:",
                     "Only entry files, each in the shard of its seq (ledger/entries/NNNN/NNNNNN.json), may be added to ledger/entries/:",
                     "Files under canon/history/ may only be added, never modified, renamed or deleted:",
                     "Files that Python could execute implicitly are not allowed:",
                     r"(^|/)(__pycache__/|sitecustomize\.py$|usercustomize\.py$)|\.(pyc|pyo|pth|so|dylib)$|^[^/]+\.py$",
                     "Symlinks and submodules are not allowed in OpenMasonry pull requests:",
                     "A pull request that adds ledger entries must change nothing else",
                     "--match-head-commit", "with plain git and no credentials", "permissions: {}"):
            self.assertIn(gate, text)

    def test_nothing_may_shadow_the_verifier_or_the_standard_library(self):
        import re
        text = (REPO / ".github/workflows/judge.yml").read_text(encoding="utf-8")
        m = re.search(r'--diff-filter=AMT "\$range" -- src \\\n\s+\| grep -Ev \'([^\']+)\' \|\| true\)', text)
        self.assertIsNotNone(m, "the gate on src/ is gone")
        allowed = re.compile(m.group(1))
        for path in ("src/openmasonry/ledger.py", "src/openmasonry/actions.py", "src/openmasonry/network.toml"):
            self.assertIsNotNone(allowed.search(path), path)
        for path in ("src/json.py", "src/json/__init__.py", "src/hashlib.py", "src/sitecustomize.py",
                     "src/openmasonry/ledger/__init__.py", "src/openmasonry/verify/__main__.py",
                     "src/openmasonry/vendor/x.py", "src/tomllib/_parser.py"):
            self.assertIsNone(allowed.search(path), path)
        self.assertEqual(sorted(p.name for p in (REPO / "src").iterdir() if not p.name.startswith(".")
                                and not p.name.endswith(".egg-info")), ["openmasonry"])
        self.assertEqual([p.name for p in (REPO / "src" / "openmasonry").iterdir()
                          if p.is_dir() and p.name != "__pycache__"], [])

    def test_the_audit_of_main_uses_the_pinned_entry_point(self):
        calls = python_calls("tyler.yml")
        self.assertIn("run: python3 -P -m openmasonry.verify --tree", calls)
        self.assertIn("run: python3 -P -m openmasonry.verify --tree --online", calls)
        self.assertFalse([line for line in calls if "-m openmasonry verify" in line])


# ------------------------------------------------------------------ 3c: the judge protects itself ----

class JudgeProtectsItself(unittest.TestCase):
    """What `verify --tree --root pr` decides for a pull request that changes code."""

    def judge(self, c: Fast, root: Path) -> dict:
        from openmasonry import verify
        led = write_ledger(tmpdir(self) / "led", c.entries)
        a = argparse.Namespace(ledger=led, tree=True, online=False, clock_since=None, root=root, pr_author=None,
                               since=None, json=True)
        with mock.patch.object(verify, "replay", lambda entries, **kw: replay(entries, verifier=by_key, **kw)):
            return verify.verify_report(a)

    def test_a_change_to_any_pinned_file_is_unlawful_until_the_ledger_pins_it(self):
        root = copy_governed(tmpdir(self) / "pr")
        c = fast_founded()
        self.assertTrue(self.judge(c, root)["valid"])
        for rel in MANIFEST:
            original = (root / rel).read_bytes()
            (root / rel).write_bytes(original + b"\n# a quiet change\n")
            r = self.judge(c, root)
            self.assertFalse(r["valid"], rel)
            self.assertTrue(r["message"].startswith("UNRATIFIED — @protocol: "), r["message"])
            (root / rel).write_bytes(original)
        (root / "src/openmasonry/verify.py").unlink()
        r = self.judge(c, root)
        self.assertIn("@protocol: src/openmasonry/verify.py is missing", r["message"])

    def test_the_same_change_is_lawful_once_a_passed_amendment_pins_the_new_digest(self):
        root = copy_governed(tmpdir(self) / "pr")
        with open(root / "src/openmasonry/ledger.py", "a", encoding="utf-8") as f:
            f.write("\n# a ratified change\n")
        new = govern.protocol_digest(root)
        c = fast_founded()
        self.assertFalse(self.judge(c, root)["valid"])
        c.add("ballot_open", "hiram", {"id": "core-2", "kind": "amendment",
                                       "subject": {"path": "@protocol", "new_sha256": new}})
        self.assertFalse(self.judge(c, root)["valid"])                # an open ballot pins nothing
        c.vote("core-2", {f: "yes" for f in FOUNDERS})
        self.assertEqual(c.state().pins["@protocol"], new)
        self.assertTrue(self.judge(c, root)["valid"])
        self.assertTrue(self.judge(c, copy_governed(tmpdir(self) / "old"))["valid"])   # the prior-pin window
        with open(root / "src/openmasonry/ledger.py", "a", encoding="utf-8") as f:
            f.write("# one more line nobody voted on\n")
        self.assertFalse(self.judge(c, root)["valid"])

    def amend(self, c: Fast, bid: str, digest: str) -> None:
        c.add("ballot_open", "hiram", {"id": bid, "kind": "amendment",
                                       "subject": {"path": "@protocol", "new_sha256": digest}})
        c.vote(bid, {f: "yes" for f in FOUNDERS})

    def upgraded(self, name: str = "pr") -> tuple[Path, tuple[str, ...]]:
        """A pull request's tree whose core grew: a new module and a new workflow, both listed in its manifest,
        and a verifier of its own that is no longer this one."""
        root = copy_governed(tmpdir(self) / name)
        (root / "src/openmasonry/freeze.py").write_text("FROZEN = True\n")
        (root / ".github/workflows/release.yml").write_text("name: Release\non: workflow_dispatch\njobs: {}\n")
        with open(root / "src/openmasonry/govern.py", "a", encoding="utf-8") as f:
            f.write("\n# the verifier of the next version\n")
        files = tuple(sorted((*MANIFEST, "src/openmasonry/freeze.py", ".github/workflows/release.yml")))
        write_manifest(root, files)
        return root, files

    def test_a_tree_whose_manifest_changed_is_unlawful_until_an_amendment_ratifies_its_digest(self):
        c = fast_founded()
        pinned = c.state().pins["@protocol"]
        # a file added to the list
        root = copy_governed(tmpdir(self) / "added")
        (root / "src/openmasonry/freeze.py").write_text("FROZEN = True\n")
        self.assertTrue(self.judge(c, root)["valid"])                 # not listed: none of the judge's business
        write_manifest(root, sorted((*MANIFEST, "src/openmasonry/freeze.py")))
        r = self.judge(c, root)
        self.assertFalse(r["valid"])
        self.assertRegex(r["message"], "^UNRATIFIED — @protocol: tree sha256 [0-9a-f]{12}… ≠ ratified "
                         + pinned[:12] + "… — needs a passed amendment$")
        # a file removed from the list
        root = copy_governed(tmpdir(self) / "removed")
        write_manifest(root, [x for x in MANIFEST if x != "src/openmasonry/lot.py"])
        r = self.judge(c, root)
        self.assertFalse(r["valid"])
        self.assertTrue(r["message"].startswith("UNRATIFIED — @protocol: tree sha256 "), r["message"])
        self.assertEqual(len(r["problems"]), 1)
        # a listed file that the tree does not hold
        root = copy_governed(tmpdir(self) / "absent")
        write_manifest(root, sorted((*MANIFEST, "src/openmasonry/freeze.py")))
        self.assertEqual(self.judge(c, root)["message"], "UNRATIFIED — @protocol: src/openmasonry/freeze.py is missing")

    def test_dropping_a_file_from_the_manifest_without_ratification_is_detected(self):
        """Nobody takes a file out of the core quietly, to change it afterward by review alone."""
        c = fast_founded()
        for rel in MANIFEST:
            if rel in govern.MANIFEST_REQUIRED:
                continue
            root = copy_governed(tmpdir(self) / "pr")
            write_manifest(root, [x for x in MANIFEST if x != rel])
            r = self.judge(c, root)
            self.assertFalse(r["valid"], rel)
            self.assertTrue(r["problems"][0].startswith("@protocol: tree sha256 "), (rel, r["problems"]))
            if rel in WORKFLOWS:                                      # an unlisted workflow is a stray as well
                self.assertEqual(r["problems"][1:], [f"{rel}: a workflow outside the pinned core ({MANIFEST_FILE}) — "
                                                     "needs a passed amendment of @protocol"])
        for rel in govern.MANIFEST_REQUIRED:                          # these two cannot be dropped at all
            root = copy_governed(tmpdir(self) / "pr")
            write_manifest(root, [x for x in MANIFEST if x != rel])
            self.assertEqual(self.judge(c, root)["problems"][0], f"@protocol: {MANIFEST_FILE}: does not list {rel}")

    def test_the_verifier_of_before_accepts_a_ratified_tree_with_a_new_manifest_and_a_new_workflow(self):
        """The upgrade path. The judge runs the base branch's code (this code, which knows nothing of the new
        files) on the pull request's tree. It reads that tree's manifest, so the digest it computes is the one
        the amendment ratified, and the new workflow is a listed one."""
        root, files = self.upgraded()
        new = framed(root, files)                                     # computed here, not by the code under test
        self.assertNotIn("src/openmasonry/freeze.py", govern.read_manifest(REPO))
        self.assertEqual(sorted(os.listdir(REPO / ".github" / "workflows")), ["judge.yml", "pages.yml", "tyler.yml"])
        c = fast_founded()
        r = self.judge(c, root)                                       # before the amendment: one violation, the digest
        self.assertEqual(len(r["problems"]), 1)
        self.assertTrue(r["problems"][0].startswith("@protocol: tree sha256 " + new[:12]), r["problems"])
        c.add("ballot_open", "hiram", {"id": "core-2", "kind": "amendment",
                                       "subject": {"path": "@protocol", "new_sha256": new}})
        self.assertFalse(self.judge(c, root)["valid"])                # an open ballot pins nothing
        c.vote("core-2", {f: "yes" for f in FOUNDERS})
        self.assertEqual(c.state().pins["@protocol"], new)
        self.assertEqual(self.judge(c, root)["problems"], [])        # the same code now lets the new tree in
        self.assertTrue(self.judge(c, root)["valid"])
        self.assertEqual(govern.stray_workflows(root), [])
        self.assertTrue(self.judge(c, copy_governed(tmpdir(self) / "old"))["valid"])    # the prior-pin window
        # What was ratified is that tree and no other.
        (root / ".github/workflows/second.yml").write_text("name: Second\non: push\njobs: {}\n")
        self.assertEqual(self.judge(c, root)["problems"],
                         [f".github/workflows/second.yml: a workflow outside the pinned core ({MANIFEST_FILE}) — needs "
                          "a passed amendment of @protocol"])
        (root / ".github/workflows/second.yml").unlink()
        (root / ".github/workflows/release.yml").write_text("name: Release\non: push\njobs: {judge: {}}\n")
        self.assertTrue(self.judge(c, root)["message"].startswith("UNRATIFIED — @protocol: tree sha256 "))
        (root / ".github/workflows/release.yml").unlink()
        self.assertEqual(self.judge(c, root)["message"],
                         "UNRATIFIED — @protocol: .github/workflows/release.yml is missing")

    def test_a_second_upgrade_follows_the_first(self):
        root, files = self.upgraded()
        c = fast_founded()
        self.amend(c, "core-2", framed(root, files))
        self.assertTrue(self.judge(c, root)["valid"])
        (root / ".github/workflows/release.yml").unlink()             # the next version drops the workflow again
        write_manifest(root, [x for x in files if x != ".github/workflows/release.yml"])
        self.assertFalse(self.judge(c, root)["valid"])
        c.now += timedelta(days=40)
        self.amend(c, "core-3", framed(root))
        self.assertTrue(self.judge(c, root)["valid"])
        self.assertFalse(self.judge(c, copy_governed(tmpdir(self) / "first"))["valid"])   # two versions back

    def test_the_command_line_of_before_judges_the_new_tree_the_same_way(self):
        """`python -P -m openmasonry.verify --tree --root pr` from this repository's src/, as the judge runs it."""
        tmp = tmpdir(self)
        root, files = self.upgraded()
        c = Chain(tmp)
        c.add("genesis", "hiram", genesis_body(c, ["hiram"]))
        led = write_ledger(tmp / "led", c.entries)
        run = lambda: subprocess.run([sys.executable, "-P", "-m", "openmasonry.verify", "--ledger", str(led), "--tree",
                                      "--root", str(root)], capture_output=True, text=True,
                                     env={**os.environ, "PYTHONPATH": str(REPO / "src"), "OM_NO_CACHE": "1"})
        r = run()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("UNRATIFIED — @protocol: tree sha256 " + framed(root, files)[:12]), r.stdout)
        c.add("ballot_open", "hiram", {"id": "core-2", "kind": "amendment",
                                       "subject": {"path": "@protocol", "new_sha256": framed(root, files)}})
        c.vote("core-2", {"hiram": "yes"})
        write_ledger(led, c.entries)
        r = run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("VALID — "), r.stdout)

    def test_code_outside_the_manifest_is_not_the_judges_business(self):
        root = copy_governed(tmpdir(self) / "pr")
        for rel in ("src/openmasonry/__main__.py", "src/openmasonry/actions.py", "src/openmasonry/guide.py",
                    "src/openmasonry/heraldry.py", "bin/om", "node/witness.py", "scripts/genesis.sh",
                    ".github/CODEOWNERS", ".github/ISSUE_TEMPLATE/application.yml", ".github/dependabot.yml"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("changed by a reviewed pull request\n")
        self.assertTrue(self.judge(fast_founded(), root)["valid"])


# ------------------------------------------------------------------ 3d: a closed set of workflows ----

class ClosedWorkflows(unittest.TestCase):
    """No workflow may exist beside the pinned ones: a new file could carry a job named `judge`."""

    judge = JudgeProtectsItself.judge

    FAKE = "name: Fake\non: pull_request_target\njobs:\n  judge:\n    runs-on: ubuntu-latest\n    steps: [{run: 'true'}]\n"

    def test_the_three_workflows_of_the_repository_are_pinned_and_there_is_no_other(self):
        self.assertEqual(WORKFLOWS, [".github/workflows/judge.yml", ".github/workflows/pages.yml",
                                     ".github/workflows/tyler.yml"])
        self.assertEqual(WORKFLOWS, [rel for rel in MANIFEST if rel.startswith(".github/workflows/")])
        self.assertEqual(sorted(f".github/workflows/{n}" for n in os.listdir(REPO / ".github" / "workflows")), WORKFLOWS)
        self.assertEqual(govern.stray_workflows(REPO), [])
        self.assertEqual(govern.check_tree(fast_founded().state()), [])

    def test_no_job_but_the_judges_is_named_judge_and_the_witness_image_holds_what_the_manifest_lists(self):
        import re
        tyler = (REPO / ".github/workflows/tyler.yml").read_text(encoding="utf-8")
        head, jobs = tyler.split("\njobs:\n", 1)
        self.assertEqual(re.findall(r"(?m)^  ([A-Za-z0-9_-]+):$", jobs), ["audit", "alarm", "tests", "candidate", "engine",
                                                                               "applications"])
        self.assertNotIn("judge", re.findall(r"(?m)^    name: (\S+)", jobs))
        triggers = head.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertEqual(re.findall(r"(?m)^  ([a-z_]+):", triggers), ["pull_request", "push", "schedule", "workflow_dispatch"])
        dockerfile = (REPO / "node" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("done < src/openmasonry/protocol.manifest\n", dockerfile)      # the image copies the listed files
        self.assertIn("COPY --from=core --chown=tyler:tyler /core /home/tyler/verifier\n", dockerfile)
        for rel in LISTED:                                             # …and names none of them itself
            self.assertNotIn(f"COPY --chown=tyler:tyler {rel}", dockerfile)
        self.assertNotIn("COPY --chown=tyler:tyler src/openmasonry ", dockerfile)

    def test_the_witness_image_copies_exactly_what_the_manifest_lists(self):
        """The copy step of node/Dockerfile, run here by sh on a scratch tree."""
        import re
        dockerfile = (REPO / "node" / "Dockerfile").read_text(encoding="utf-8")
        m = re.search(r"RUN (set -eu; mkdir /core; cd /repo; .*?done < src/openmasonry/protocol\.manifest)\n", dockerfile,
                      re.DOTALL)
        self.assertIsNotNone(m, "the copy step is gone")
        script = m.group(1).replace("\\\n", " ")
        repo = copy_governed(tmpdir(self) / "repo")
        (repo / "src/openmasonry/actions.py").write_text("not pinned\n")
        (repo / ".github/workflows/other.yml").write_text("not listed\n")
        out = tmpdir(self) / "core"
        r = subprocess.run(["sh", "-c", script.replace("/core", str(out)).replace("/repo", str(repo))],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        copied = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
        self.assertEqual(copied, sorted(MANIFEST))
        self.assertEqual(govern.protocol_digest(out), govern.protocol_digest(REPO))
        (repo / "src/openmasonry/lot.py").unlink()                    # a listed file that is missing stops the build
        shutil.rmtree(out)
        r = subprocess.run(["sh", "-c", script.replace("/core", str(out)).replace("/repo", str(repo))],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)

    def test_a_new_workflow_makes_the_tree_unlawful_though_the_digest_still_matches(self):
        root = copy_governed(tmpdir(self) / "pr")
        c = fast_founded()
        pinned = c.state().pins["@protocol"]
        for name in ("fake.yml", "judge.yaml", "judge2.yml", ".hidden.yml", "notes.txt"):
            stray = root / ".github" / "workflows" / name
            stray.write_text(self.FAKE)
            self.assertEqual(govern.protocol_digest(root), pinned)       # the digest alone would not notice
            r = self.judge(c, root)
            self.assertFalse(r["valid"], name)
            self.assertEqual(r["message"], f"UNRATIFIED — .github/workflows/{name}: a workflow outside the pinned core "
                             f"({MANIFEST_FILE}) — needs a passed amendment of @protocol")
            stray.unlink()
        self.assertTrue(self.judge(c, root)["valid"])

    def test_a_directory_or_a_symlink_there_is_refused_too(self):
        root = copy_governed(tmpdir(self) / "pr")
        c = fast_founded()
        inner = root / ".github" / "workflows" / "more"
        inner.mkdir()
        (inner / "fake.yml").write_text(self.FAKE)
        self.assertIn(".github/workflows/more: a workflow outside the pinned core", self.judge(c, root)["message"])
        shutil.rmtree(inner)
        (root / ".github" / "workflows" / "link.yml").symlink_to(root / ".github" / "workflows" / "judge.yml")
        self.assertIn(".github/workflows/link.yml: a workflow outside the pinned core", self.judge(c, root)["message"])

    def test_every_stray_is_reported_in_order_after_the_pins(self):
        root = copy_governed(tmpdir(self) / "pr")
        for name in ("b.yml", "a.yml"):
            (root / ".github" / "workflows" / name).write_text(self.FAKE)
        st = fast_founded().state()
        self.assertEqual([p.split(":")[0] for p in govern.check_tree(st, root)],
                         [".github/workflows/a.yml", ".github/workflows/b.yml"])
        (root / "CONSTITUTION.md").write_text("another text\n")
        self.assertEqual([p.split(":")[0] for p in govern.check_tree(st, root)],
                         ["CONSTITUTION.md", ".github/workflows/a.yml", ".github/workflows/b.yml"])

    def test_a_tree_without_the_directory_is_judged_by_its_pins_alone(self):
        root = copy_governed(tmpdir(self) / "pr")
        shutil.rmtree(root / ".github")
        self.assertEqual(govern.stray_workflows(root), [])
        problems = govern.check_tree(fast_founded().state(), root)
        self.assertEqual(len(problems), 1)
        self.assertIn("@protocol: .github/workflows/judge.yml is missing", problems[0])

    def test_the_judges_own_gate_states_the_same_rule(self):
        """The gate of judge.yml allows exactly the workflow files the pull request's own manifest lists. Its
        two greps are read out of the workflow and applied here as grep would apply them."""
        import re
        text = (REPO / ".github/workflows/judge.yml").read_text(encoding="utf-8")
        self.assertIn("Only the workflows of the pinned core may exist under .github/workflows/", text)
        self.assertNotIn("(judge|tyler)", text)                       # no list of its own any more
        listed = re.search(r"listed=\$\(git show \"\$HEAD_SHA:src/openmasonry/protocol\.manifest\" 2>/dev/null \\\n"
                           r"\s+\| grep -xE '([^']+)' \|\| true\)", text)
        self.assertIsNotNone(listed, "the gate no longer reads the pull request's manifest")
        m = re.search(r"stray=\$\(git ls-tree -r --name-only \"\$HEAD_SHA\" \| grep -iE '([^']+)' \\\n"
                      r"\s+\| grep -vxFf <\(printf '%s\\n' \"\$listed\"\) \|\| true\)", text)
        self.assertIsNotNone(m, "the gate on .github/workflows/ is gone")
        is_workflow = re.compile(listed.group(1))
        under = re.compile(m.group(1), re.IGNORECASE)

        def strays(tree: list[str], manifest: bytes | None) -> list[str]:
            lines = [] if manifest is None else manifest.decode("ascii", "replace").split("\n")
            allowed = {x for x in lines if is_workflow.fullmatch(x)} or {""}      # printf of nothing: one empty line
            return [path for path in tree if under.search(path) and path not in allowed]

        ours = manifest_bytes(MANIFEST)
        tree = [*MANIFEST, ".github/CODEOWNERS", ".github/ISSUE_TEMPLATE/application.yml", "docs/.github/workflows/x.yml",
                ".github/workflows-notes.md", "README.md"]
        self.assertEqual(strays(tree, ours), [])
        for path in (".github/workflows/fake.yml", ".github/workflows/judge.yaml", ".github/workflows/judge.yml.bak",
                     ".github/workflows/more/judge.yml", ".github/Workflows/judge.yml", ".GITHUB/WORKFLOWS/x.yml",
                     ".github/workflows", '".github/workflows/caf\\303\\251.yml"'):
            self.assertEqual(strays([*tree, path], ours), [path])
        # A workflow the pull request's manifest lists is allowed (whether that tree is ratified is the digest's
        # business); one it does not list never is, and without a manifest nothing is listed.
        grown = manifest_bytes(sorted((*MANIFEST, ".github/workflows/release.yml")))
        self.assertEqual(strays([*tree, ".github/workflows/release.yml"], grown), [])
        self.assertEqual(strays([*tree, ".github/workflows/release.yml", ".github/workflows/x.yml"], grown),
                         [".github/workflows/x.yml"])
        self.assertEqual(strays(tree, None), WORKFLOWS)
        self.assertEqual(strays(tree, b""), WORKFLOWS)
        self.assertEqual(strays(tree, manifest_bytes(x for x in MANIFEST if x not in WORKFLOWS)), WORKFLOWS)
        # A line of the manifest counts only as a file directly in the directory, exactly as spelled.
        odd = manifest_bytes([".github/Workflows/a.yml", ".github/workflows/sub/b.yml", ".github/workflows/judge.yml "])
        self.assertEqual(strays([".github/Workflows/a.yml", ".github/workflows/sub/b.yml", ".github/workflows/judge.yml"],
                                odd),
                         [".github/Workflows/a.yml", ".github/workflows/sub/b.yml", ".github/workflows/judge.yml"])
        # The same verdicts as the verifier's on a tree on disk.
        root, files = JudgeProtectsItself.upgraded(self)
        on_disk = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
        self.assertEqual(strays(on_disk, (root / MANIFEST_FILE).read_bytes()), govern.stray_workflows(root))
        (root / ".github/workflows/x.yml").write_text(self.FAKE)
        on_disk.append(".github/workflows/x.yml")
        self.assertEqual(strays(on_disk, (root / MANIFEST_FILE).read_bytes()), govern.stray_workflows(root))
        self.assertEqual(govern.stray_workflows(root), [".github/workflows/x.yml"])


# ------------------------------------------------------------------ 4: what genesis pins ----

class GenesisPins(unittest.TestCase):
    def test_genesis_pins_exactly_six_paths(self):
        self.assertEqual(set(ledger.GENESIS_PINS), GENESIS_PINS)
        c = Fast()
        body = genesis_body(c)
        self.assertEqual(sorted(body), ["custodian_threshold", "custodians", "declaration_sha256", "founders", "name", "pins",
                                        "witnesses"])
        self.assertEqual(set(body["pins"]), GENESIS_PINS)
        c.add("genesis", "hiram", body)
        st = c.state()
        self.assertEqual(st.pins, body["pins"])
        self.assertEqual(st.pins["@protocol"], govern.protocol_digest())
        for rel in GENESIS_PINS - {"@protocol"}:
            self.assertEqual(st.pins[rel], hashlib.sha256((REPO / rel).read_bytes()).hexdigest(), rel)
        self.assertEqual(st.declaration_sha256, DECL)
        self.assertEqual((st.prior_pins, st.history["amendments"], st.degree_tables), ({}, (0, "0" * 64), []))

    def test_the_key_set_is_exact(self):
        good = genesis_body(Fast())["pins"]
        cases = [({k: v for k, v in good.items() if k != rel}, f"genesis entry: pins: missing field '{rel}'")
                 for rel in sorted(GENESIS_PINS)]
        cases += [(good | {"README.md": "ab" * 32}, "genesis entry: pins: unknown field 'README.md'"),
                  (good | {"canon/Degrees.toml": "ab" * 32}, "unknown field 'canon/Degrees.toml'"),
                  ({}, "genesis entry: pins: missing field"),
                  (sorted(good.values()), "field 'pins' must be an object"),
                  (good | {"@protocol": 7}, "field '@protocol' must be a string")]
        cases += [(good | {rel: bad}, "genesis must pin")
                  for rel in sorted(GENESIS_PINS) for bad in ("", "AB" * 32, "ab" * 31, "ab" * 32 + "\n", "g" * 64)]
        for pins, pattern in cases:
            c = Fast()
            c.add("genesis", "hiram", genesis_body(c) | {"pins": pins})
            c.refused(self, pattern)

    def test_the_four_separate_fields_are_gone(self):
        for old in ("degrees_sha256", "eternal_sha256", "constitution_sha256", "protocol_sha256"):
            c = Fast()
            c.add("genesis", "hiram", genesis_body(c) | {old: "ab" * 32})
            c.refused(self, f"malformed genesis entry: unknown field '{old}'")
        c = Fast()
        body = genesis_body(c)
        del body["pins"]
        c.add("genesis", "hiram", body)
        c.refused(self, "malformed genesis entry: missing field 'pins'")
        c = Fast()
        body = genesis_body(c)
        del body["declaration_sha256"]
        c.add("genesis", "hiram", body)
        c.refused(self, "missing field 'declaration_sha256'")

    def test_an_amendment_moves_a_genesis_pin_like_any_other(self):
        c = fast_founded()
        old = c.state().pins["docs/governance/ROOMS.md"]
        c.add("ballot_open", "hiram", {"id": "rooms-2", "kind": "amendment",
                                       "subject": {"path": "docs/governance/ROOMS.md", "new_sha256": "cd" * 32}})
        c.vote("rooms-2", {f: "yes" for f in FOUNDERS})
        st = c.state()
        self.assertEqual(st.pins["docs/governance/ROOMS.md"], "cd" * 32)
        self.assertEqual(st.prior_pins, {"docs/governance/ROOMS.md": old})
        self.assertEqual(set(st.pins), GENESIS_PINS)
        c.add("ballot_open", "hiram", {"id": "x", "kind": "amendment",
                                       "subject": {"path": "docs/governance/custodian.md", "new_sha256": "cd" * 32}})
        c.refused(self, "collides with the pinned path 'docs/governance/CUSTODIAN.md'")

    def test_the_tree_must_match_all_six(self):
        st = fast_founded().state()
        self.assertEqual(govern.check_tree(st), [])
        for rel in sorted(GENESIS_PINS - {"@protocol"}):
            root = copy_governed(tmpdir(self) / "tree")
            self.assertEqual(govern.check_tree(st, root), [])
            with open(root / rel, "a", encoding="utf-8") as f:
                f.write("\n")
            problems = govern.check_tree(st, root)
            self.assertTrue(any(p.startswith(f"{rel}: tree sha256 ") for p in problems), (rel, problems))
            (root / rel).unlink()
            self.assertTrue(any(p.startswith(f"{rel}: tree sha256 (missing)") for p in govern.check_tree(st, root)), rel)

    def test_genesis_pins_of_a_tree(self):
        root = copy_governed(tmpdir(self) / "tree")
        self.assertEqual(govern.genesis_pins(root), govern.genesis_pins())
        (root / "docs/governance/CUSTODIAN.md").write_text("another charter\n")
        pins = govern.genesis_pins(root)
        self.assertEqual(pins["docs/governance/CUSTODIAN.md"], hashlib.sha256(b"another charter\n").hexdigest())
        self.assertEqual({k for k, v in pins.items() if v != govern.genesis_pins()[k]}, {"docs/governance/CUSTODIAN.md"})


class GenesisCommand(unittest.TestCase):
    def test_om_genesis_drafts_the_six_pins_and_the_dialog_names_them(self):
        from openmasonry import actions
        tmp = tmpdir(self)
        c = Chain(tmp)
        c.key("hiram")
        home = tmp / "home"
        home.mkdir()
        r = subprocess.run([sys.executable, "-m", "openmasonry", "genesis", "--ledger", str(tmp / "led"), "--json",
                            "--github-id", "7", "--time", "2027-01-01T00:00:00Z"], capture_output=True, text=True,
                           env={**os.environ, "PYTHONPATH": str(REPO / "src"), "OM_LOGIN": "hiram", "OM_HOME": str(home),
                                "OM_KEY": str(c.keys["hiram"][0]), "OM_CACHE": str(tmp / "cache")})
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        entry = json.loads(r.stdout)["entry"]
        self.assertEqual(entry["body"]["pins"], govern.genesis_pins())
        self.assertEqual(sorted(entry["body"]), ["custodian_threshold", "custodians", "declaration_sha256", "founders", "name",
                                                 "pins", "witnesses"])
        self.assertEqual((entry["body"]["custodians"], entry["body"]["custodian_threshold"]), ([], 0))
        self.assertEqual(entry["body"]["declaration_sha256"], DECL)
        text = actions.describe(None, entry)
        for rel in GENESIS_PINS:
            self.assertIn(rel, text)


# ------------------------------------------------------------------ 5: the witness ----

class Done:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class Witness(unittest.TestCase):
    """The witness node with `gh` and `git` replaced: what it closes, what it signs and what it refuses."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._tmp.cleanup)
        c = Chain(Path(cls._tmp.name))
        c.now = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=30)
        c.add("genesis", "hiram", genesis_body(c, ["hiram", "ada"], ["tyler"]))
        c.add("ballot_open", "ada", {"id": "w", "kind": "witness",
                                     "subject": witness_subject(c, "node2")})
        cls.chain = c

    def node(self, mode="pr", prs=None, diff="", list_ok=True, close_ok=True):
        """A witness module over a scratch clone. `prs` is what `gh pr list` answers; `diff` is what
        `git diff --name-status origin/main origin/<branch>` answers (an Exception makes it fail)."""
        repo = copy_governed(tmpdir(self) / "repo")
        write_ledger(repo / "ledger" / "entries", self.chain.entries)
        env = mock.patch.dict(os.environ, {"OM_WITNESS_REPO": str(repo), "OM_WITNESS_NAME": "tyler",
                                           "OM_WITNESS_KEY": str(self.chain.keys["tyler"][0]), "OM_WITNESS_PUSH": mode})
        env.start()
        self.addCleanup(env.stop)
        path = mock.patch.object(sys, "path", [str(REPO / "node"), *sys.path])
        path.start()
        self.addCleanup(path.stop)
        w = importlib.reload(importlib.import_module("witness"))
        self.gh, self.git, self.logs, self.alarms = [], [], [], []

        def gh(*args):
            self.gh.append(args)
            if args[:2] == ("pr", "list"):
                return Done(0, json.dumps(prs or [])) if list_ok else Done(1, "", "HTTP 502")
            if args[:2] == ("pr", "close"):
                return Done(0 if close_ok else 1, "", "" if close_ok else "HTTP 403")
            return Done(0, "https://github.com/openmasonry/openmasonry/pull/9\n")

        def git(*args, check=True):
            self.git.append(args)
            if args[0] == "diff":
                if isinstance(diff, Exception):
                    raise diff
                return diff
            return ""
        real_which = shutil.which
        which = mock.patch.object(shutil, "which", lambda name, *a, **k: "/usr/bin/gh" if name == "gh" else
                                  None if name == "ots" else real_which(name, *a, **k))
        which.start()
        self.addCleanup(which.stop)
        w.gh, w.git, w.sync = gh, git, lambda: True
        w.log = self.logs.append
        w.alarm = self.alarms.append
        return w

    def written(self, w) -> list[str]:
        return [e["type"] for e in load(w.LEDGER)][len(self.chain.entries):]

    def did(self, *prefix) -> bool:
        return any(call[:len(prefix)] == prefix for call in self.gh)

    OWN = {"number": 7, "headRefName": "witness/tyler/000002-1767225600", "isCrossRepository": False,
           "mergeable": "MERGEABLE"}

    # -- (a) a pull request of ours that lost its place --

    def test_a_conflicted_pull_request_is_closed_and_the_work_redone(self):
        w = self.node(prs=[self.OWN | {"mergeable": "CONFLICTING"}])
        w.cycle()
        self.assertTrue(self.did("pr", "close", "7"))
        self.assertEqual(self.written(w), ["ballot_close", "witness"])
        replay(load(w.LEDGER))
        order = [call[:2] for call in self.gh if call[0] == "pr"]
        self.assertLess(order.index(("pr", "close")), order.index(("pr", "create")))
        self.assertIn(("push", "-q", "origin", "--delete", self.OWN["headRefName"]), self.git)

    def test_a_pull_request_whose_entries_no_longer_extend_main_is_closed(self):
        for diff in ("M\tledger/entries/0000/000002.json\nA\tledger/entries/0000/000003.json\n",   # another entry took seq 2
                     "D\tledger/entries/0000/000002.json\nA\tledger/entries/0000/000003.json\n",   # main has entries we lack
                     ""):                                                                # nothing left to add
            w = self.node(prs=[self.OWN | {"mergeable": "UNKNOWN"}], diff=diff)
            w.cycle()
            self.assertTrue(self.did("pr", "close", "7"), repr(diff))
            self.assertEqual(self.written(w), ["ballot_close", "witness"], repr(diff))
            self.assertIn(("diff", "--no-renames", "--name-status", "refs/remotes/origin/main",
                           f"refs/remotes/origin/{self.OWN['headRefName']}", "--", "ledger/entries"), self.git)

    def test_a_live_pull_request_still_means_verify_only(self):
        w = self.node(prs=[self.OWN], diff="A\tledger/entries/0000/000002.json\nA\tledger/entries/0000/000003.json\n")
        w.cycle()
        self.assertFalse(self.did("pr", "close"))
        self.assertEqual(self.written(w), [])
        self.assertTrue(any("not merged yet" in line for line in self.logs), self.logs)

    def test_when_it_cannot_tell_it_leaves_the_pull_request_alone(self):
        w = self.node(prs=[self.OWN | {"mergeable": "UNKNOWN"}], diff=RuntimeError("git diff: unknown revision"))
        w.cycle()
        self.assertFalse(self.did("pr", "close"))
        self.assertEqual(self.written(w), [])

    def test_it_never_writes_beside_a_pull_request_it_could_not_close(self):
        w = self.node(prs=[self.OWN | {"mergeable": "CONFLICTING"}], close_ok=False)
        w.cycle()
        self.assertTrue(self.did("pr", "close", "7"))
        self.assertEqual(self.written(w), [])
        self.assertFalse(self.did("pr", "create"))

    def test_it_never_writes_when_it_cannot_list_its_pull_requests(self):
        w = self.node(list_ok=False)
        w.cycle()
        self.assertEqual(self.written(w), [])
        self.assertFalse(self.did("pr", "close"))

    def test_one_stale_and_one_live_pull_request(self):
        live = self.OWN | {"number": 8, "headRefName": "witness/tyler/000003-1767229200"}
        w = self.node(prs=[self.OWN | {"mergeable": "CONFLICTING"}, live], diff="A\tledger/entries/0000/000002.json\n")
        w.cycle()
        self.assertTrue(self.did("pr", "close", "7"))
        self.assertFalse(self.did("pr", "close", "8"))
        self.assertEqual(self.written(w), [])

    def test_other_peoples_pull_requests_are_never_closed_and_never_pause_it(self):
        others = [self.OWN | {"isCrossRepository": True, "mergeable": "CONFLICTING"},              # a fork's branch
                  self.OWN | {"number": 3, "headRefName": "witness/tyler2/000002-1", "mergeable": "CONFLICTING"},
                  self.OWN | {"number": 4, "headRefName": "feature/witness/tyler/x", "mergeable": "CONFLICTING"}]
        w = self.node(prs=others)
        w.cycle()
        self.assertFalse(self.did("pr", "close"))
        self.assertEqual(self.written(w), ["ballot_close", "witness"])

    def test_it_closes_nothing_on_a_copy_it_could_not_sync(self):
        w = self.node(prs=[self.OWN | {"mergeable": "CONFLICTING"}])
        w.sync = lambda: False
        w.cycle()
        self.assertFalse(self.did("pr", "close"))
        self.assertEqual(self.written(w), [])

    # -- (b) its own code must be the ratified code --

    def test_it_signs_when_its_code_is_the_pinned_code(self):
        w = self.node(mode="none")
        self.assertEqual(w.protocol_digest(), replay(load(w.LEDGER)).pins["@protocol"])
        w.cycle()
        self.assertEqual(self.written(w), ["ballot_close", "witness"])
        self.assertEqual(self.alarms, [])

    def test_its_own_code_is_what_the_manifest_of_its_own_copy_lists(self):
        """The self-check reads the manifest beside the code the witness imported, not a list in that code."""
        image = copy_governed(tmpdir(self) / "image")                 # the verifier as baked into an image
        w = self.node(mode="none")
        with mock.patch.object(govern.canon, "ROOT", image):
            self.assertEqual(w.protocol_digest(), framed(image, MANIFEST))
            w.cycle()
        self.assertEqual(self.written(w), ["ballot_close", "witness"])
        for manifest, why in ((manifest_bytes(x for x in MANIFEST if x != "src/openmasonry/lot.py"), "@protocol"),
                              (manifest_bytes(sorted((*MANIFEST, "src/openmasonry/absent.py"))), "absent.py is missing"),
                              (b"# the pinned core\n" + manifest_bytes(MANIFEST), "not a safe relative path")):
            (image / MANIFEST_FILE).write_bytes(manifest)
            w = self.node(mode="none")
            with mock.patch.object(govern.canon, "ROOT", image):
                w.cycle()
            self.assertEqual(self.written(w), [], why)
            self.assertTrue(any("refusing to sign" in line and why in line for line in self.logs), (why, self.logs))
            self.assertEqual(self.alarms, [])

    def test_it_refuses_to_sign_when_its_code_is_not_the_pinned_code(self):
        w = self.node(mode="none")
        w.protocol_digest = lambda: "00" * 32
        w.cycle()
        self.assertEqual(self.written(w), [])
        self.assertEqual(self.alarms, [])
        self.assertTrue(any("refusing to sign" in line and "@protocol" in line for line in self.logs), self.logs)

    def test_it_refuses_to_sign_when_it_cannot_read_its_own_code(self):
        w = self.node(mode="none")
        w.protocol_digest = mock.Mock(side_effect=govern.UnsafeTree("src/openmasonry/verify.py is missing"))
        w.cycle()
        self.assertEqual(self.written(w), [])
        self.assertTrue(any("refusing to sign" in line for line in self.logs), self.logs)

    def test_with_the_wrong_code_it_still_verifies_and_still_raises_the_alarm(self):
        w = self.node(mode="none")
        w.protocol_digest = lambda: "00" * 32
        with open(w.REPO / "CONSTITUTION.md", "a", encoding="utf-8") as f:
            f.write("\nAn article nobody voted on.\n")
        w.cycle()
        self.assertEqual(self.written(w), [])
        self.assertEqual(len(self.alarms), 1)
        self.assertIn("CONSTITUTION.md", str(self.alarms[0]))
        w = self.node(mode="none")
        w.protocol_digest = lambda: "00" * 32
        e = json.loads(entry_path(w.LEDGER, 1).read_text())
        e["body"]["id"] = "another"
        entry_file(w.LEDGER, 1).write_text(json.dumps(e))
        w.cycle()
        self.assertEqual(len(self.alarms), 1)
        self.assertIsInstance(self.alarms[0], Invalid)


if __name__ == "__main__":
    unittest.main()
