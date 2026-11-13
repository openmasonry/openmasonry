"""Who may push an entry: the judge's online identity check for a pull request.

Offline replay proves an entry was signed by the key the ledger knows. It cannot prove that the key
of a *petition*, or the new key of a *rekey* or of a key recovery, belongs to the GitHub login it claims, that the person
who opened the pull request is the actor, nor that a login still names the GitHub account a Master
Builder invited. This module checks all of these for the new entries of a PR. The only network calls
are `fetch_github_keys` and `fetch_github_user`, kept tiny so tests can replace them.

A person is a GitHub account, and an account is its numeric id: a login can be renamed, and a login that
was given up can be taken by someone else. The author of a pull request is therefore compared with the
`github_id` the ledger holds for the member, never with the login.

Four kinds of entry are not bound to the author of their pull request. The acts of a witness and the
entries of a custodian (signed by a custodian key or by its revoke key) are signed by a key that belongs
to no GitHub account. A `depart` and a `rekey_object` are signed by the key the ledger holds for the
member and restrict nobody but that member: a member whose GitHub account is in other hands must still be
able to leave, and to stop a recovery of their key. Anyone may carry those; replay alone decides whether
they stand.
"""
from __future__ import annotations

import json
import os
import urllib.request

from . import canon
from .ledger import CUSTODIAN_SIGNED, WITNESS_TYPES, Invalid, State, apply, same_login, valid_login

KEYS_URL = "https://github.com/{login}.keys"
USER_URL = "https://api.github.com/users/{login}"


def fetch_github_keys(login: str, timeout: float = 10) -> list[str]:
    """The public keys GitHub lists for `login` (raises OSError on any network failure)."""
    with urllib.request.urlopen(KEYS_URL.format(login=login), timeout=timeout) as r:   # login is LOGIN_RE-valid
        if r.status != 200:
            raise OSError(f"HTTP {r.status}")
        return r.read(256 * 1024).decode("utf-8", "replace").splitlines()


def fetch_github_user(login: str, timeout: float = 10) -> dict:
    """`{"id": …, "login": …}` as GitHub answers for `login` today (raises OSError on any network failure,
    ValueError when the answer is not JSON). A token in $GITHUB_TOKEN only raises the rate limit."""
    req = urllib.request.Request(USER_URL.format(login=login), headers={"Accept": "application/vnd.github+json"})
    if os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", "Bearer " + os.environ["GITHUB_TOKEN"])
    with urllib.request.urlopen(req, timeout=timeout) as r:                             # login is LOGIN_RE-valid
        if r.status != 200:
            raise OSError(f"HTTP {r.status}")
        data = json.loads(r.read(256 * 1024).decode("utf-8", "replace"))
    return {"id": data.get("id"), "login": data.get("login")} if type(data) is dict else {}


def _github_id(seq: int, login: str, fetch_user, problems: list[str]) -> int | None:
    """The numeric id GitHub gives `login` today. When it cannot be told, a problem is recorded (fail closed)
    and None is returned."""
    url = USER_URL.format(login=login)
    try:
        user = fetch_user(login)
        if type(user) is not dict or type(user.get("id")) is not int or type(user.get("login")) is not str:
            raise ValueError("the answer has no numeric id or no login")
        if not same_login(user["login"], login):
            raise ValueError(f"answered for another login, {user['login']}")
    except (OSError, ValueError) as err:
        problems.append(f"entry {seq}: cannot fetch {url} ({err}); refusing (fail closed)")
        return None
    return user["id"]


def _key_listed(seq: int, login: str, key, what: str, fetch, problems: list[str]) -> None:
    """`key` must be one of the keys GitHub lists for `login` today; a problem is recorded when it is not, and
    when the list cannot be fetched (fail closed)."""
    url = KEYS_URL.format(login=login)
    try:
        listed = {" ".join(line.split()[:2]) for line in fetch(login) if line.strip()}
    except (OSError, ValueError) as err:
        problems.append(f"entry {seq}: cannot fetch {url} ({err}); refusing (fail closed)")
    else:
        if key not in listed:
            problems.append(f"entry {seq}: the {what} is not listed at {url}")


CARRIED = frozenset({"depart", "rekey_object"})     # member entries any pull request may carry


def pr_problems(entries: list[dict], since: int, author: str, fetch=None, fetch_user=None,
                author_id: int | None = None, founder_id: int | None = None) -> list[str]:
    """Problems with the new entries (seq >= since) of a PR opened by `author`. Empty = lawful.

    * the pull request of an entry a member signs must come from that member's GitHub account: the numeric
      id of the PR author (`author_id`, as the pull request event gives it; looked up once when absent) must
      equal the `github_id` the ledger holds for the actor. Excepted: entries a registered witness signs
      with its witness key, entries a custodian signs with its custodian key or its revoke key, and the two
      types of `CARRIED` (`depart`, `rekey_object`). An actor the ledger does not know is compared by login;
    * a petition's pull request must come from the GitHub account its invitation names;
    * a petition's key, and the new key of a rekey or of a key recovery (`rekey_recover`, and again at
      `rekey_recover_apply`), must be listed at https://github.com/<login>.keys, with `login` the login the
      account has today (the PR author's, once its id is the right one);
    * the login of an `invite` (and of each founder of a genesis) must be, today, the GitHub account with
      the numeric id the entry states (https://api.github.com/users/<login>);
    * the genesis comes from the founder's account: `founder_id` (default: `canon.FOUNDER_GITHUB_ID`, the
      `founder_github_id` of the pinned `network.toml`) must be set, and both the PR author's id and the
      `github_id` of the first founder must equal it.
    A network failure fails closed. Signatures are assumed already verified by a full replay.
    """
    fetch = fetch or fetch_github_keys
    fetch_user = fetch_user or fetch_github_user
    founder_id = canon.FOUNDER_GITHUB_ID if founder_id is None else founder_id
    st = State()
    problems: list[str] = []
    looked_up: list[int | None] = []

    def pr_account(seq: int) -> int | None:
        """The numeric id of the PR author: given, or asked of GitHub once (None when it cannot be told)."""
        if author_id is not None:
            return author_id
        if not looked_up:
            looked_up.append(_github_id(seq, author, fetch_user, problems))
        return looked_up[0]

    for e in entries:
        if e["seq"] >= since:
            seq, actor, typ, body = e["seq"], e["actor"], e["type"], e["body"]
            by_witness = typ in WITNESS_TYPES and actor in st.witnesses
            by_custodian = typ in CUSTODIAN_SIGNED and actor in st.custodians
            member = st.members.get(actor)
            listed_at = actor                    # whose key list a new key must be on: the account behind the actor
            if by_witness or by_custodian or typ in CARRIED:
                pass                                                         # anyone may carry these
            elif typ == "genesis":
                first = body.get("founders", [None])[0] if type(body.get("founders")) is list and body["founders"] else None
                first_id = first.get("github_id") if type(first) is dict else None
                found = pr_account(seq)
                if founder_id < 1:
                    problems.append(f"entry {seq}: founder_github_id is not set in src/openmasonry/network.toml (the "
                                    "genesis is accepted only from the founder's GitHub account: set it to the numeric "
                                    "id of the first founder before the genesis)")
                elif first_id != founder_id:
                    problems.append(f"entry {seq}: the first founder states the GitHub id {first_id}, but "
                                    f"src/openmasonry/network.toml names the founder with id {founder_id}")
                elif found is not None and found != founder_id:
                    problems.append(f"entry {seq}: the genesis comes from the founder's GitHub account (id {founder_id}), "
                                    f"but the pull request is by the account with id {found}")
            elif typ == "petition":
                invitation = st.invitations.get(actor)
                if invitation is not None:                                   # without one, replay refuses the petition
                    found = pr_account(seq)
                    if found is not None and found != invitation["github_id"]:
                        problems.append(f"entry {seq}: the invitation is for the GitHub account with id "
                                        f"{invitation['github_id']}, but the pull request is by the account with id {found}")
                    elif found is not None:
                        listed_at = author       # the invited account, under the login it has today
            elif member is not None:
                found = pr_account(seq)
                if found is not None and found != member.github_id:
                    problems.append(f"entry {seq} ({typ}): {actor} is the GitHub account with id {member.github_id}, but "
                                    f"the pull request is by the account with id {found}")
                elif found is not None:
                    listed_at = author           # the member's account, under the login it has today
            elif not same_login(actor, author):                              # nobody the ledger knows: replay refuses it
                problems.append(f"entry {seq} ({typ}) has actor {actor}, but the pull request is by {author}")
            accounts = [body] if typ == "invite" else body.get("founders", []) if typ == "genesis" else []
            for acc in accounts:
                if type(acc) is dict and valid_login(acc.get("login")):      # anything else is refused by replay
                    found = _github_id(seq, acc["login"], fetch_user, problems)
                    if found is not None and found != acc.get("github_id"):
                        problems.append(f"entry {seq}: the GitHub account {acc['login']} has id {found}, "
                                        f"not {acc.get('github_id')}")
            recovery = st.recoveries.get(actor) if typ == "rekey_recover_apply" else None
            if typ in ("rekey", "rekey_recover") or recovery is not None:
                # The new key: of the entry itself, or the one the pending recovery named (checked again today).
                _key_listed(seq, listed_at, recovery.key if recovery is not None else body.get("key", ""), "new key",
                            fetch, problems)
            if typ == "petition":
                _key_listed(seq, listed_at, body.get("key", ""), "petition key", fetch, problems)
        try:
            apply(st, e, verifier=lambda *_: True, trusted=True)
        except Invalid as err:
            problems.append(str(err))
            break
    return problems
