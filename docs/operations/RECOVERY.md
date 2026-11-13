# Recovery runbooks

What to do when something breaks: a key, a token, the host, the protocol itself. Each runbook is a list of numbered steps. Nothing here adds a rule: every step uses an entry or a setting that the [Constitution](../../CONSTITUTION.md), the [Custodian's charter](../governance/CUSTODIAN.md) and the [specification](../whitepaper/SPEC.md) already define. Where a runbook and those texts disagree, they govern.

Three facts hold in every case below.

- **Nothing in the ledger is ever rewritten or erased.** A repair is a new signed entry (Landmark VI).
- **The ledger is not on GitHub; a copy of it is.** Every clone that verifies from genesis is as good as the original (Constitution Art. I.4).
- **Leaving is always possible.** No freeze, halt or suspension stops a `depart` (Landmark VII).

Commands are written as `om …`; in a clone that is `bin/om …`. Every act is drafted first and signed only when the person approves it.

| If this happened | Go to |
|---|---|
| My key may have been copied, or I want a new one | [1.1](#11-you-still-hold-the-key) |
| My key is lost, or someone else has it | [1.2](#12-the-key-is-lost-or-in-other-hands) |
| The custodian key is stolen or lost | [2](#2-the-custodian-key-is-stolen-or-lost) |
| A witness's token or key is compromised | [3](#3-a-witness-token-or-key-is-compromised) |
| The GitHub account or organization is gone | [4](#4-the-github-account-or-organization-is-lost) |
| A flaw in the protocol was found | [5](#5-a-flaw-in-the-protocol-is-found) |
| The protocol core must be upgraded | [6](#6-upgrading-the-pinned-core) |
| The ledger cannot continue under its own rules | [7](#7-the-last-resort-a-recovery-genesis) |
| My client prints ROLLBACK, BEHIND, DIFFERENT GENESIS or FUTURE HEAD | [8](#8-what-your-client-shows-and-what-to-do) |
| No Master Builder is left, or none answers | [9](#9-no-master-builder-is-left) |
| The judge cannot run, or nobody can make it run | [10](#10-manual-judging) |
| The room sync's GitHub App key may be exposed | [11](#11-the-room-sync-app-key-is-compromised) |

---

## 1. A member's key is lost or stolen

### 1.1 You still hold the key

Replace it yourself. No one else is needed, and it works also while you are suspended, while your key is frozen and while the ledger is halted.

1. Make a new key (`ssh-keygen -t ed25519`, or `-t ed25519-sk` for a hardware token). It must be a key this ledger has never seen.
2. Add the new public key to your GitHub account. The judge checks that it is listed at `github.com/<login>.keys`.
3. Draft the replacement: `om rekey --new-key PATH`. Your current key signs the entry and the new key signs a proof.
4. Approve the draft. The pull request must come from your own GitHub account.
5. When it is merged, remove the old key from GitHub. From the next entry on the old key signs nothing, and it can never be registered again.

You may do this once in 30 days. Votes you committed before the change are revealed with the new key.

### 1.2 The key is lost, or in other hands

You cannot sign, so your peers answer for you. There are two paths. **With a freeze**, when a Custodian answers: the steps below. **Without a freeze**, when no custodian key is live or the Custodian does not answer: a recovery never needs a Custodian (SPEC section 6.26), and the differences are listed after the steps.

1. **Ask for a freeze.** Tell the Custodian, in a public issue or, if the matter is sensitive, through the channel of [SECURITY.md](../../SECURITY.md). The Custodian signs a `freeze_key` correction on the ground `key_compromised`, with a public reason (`om correct`). For 30 days the old key signs nothing except a departure, a key replacement, the stop of a recovery of its own key, its votes (commit and reveal) in every ballot, and the entries of an amendment ballot or of the ballot that removes a Custodian.
2. **Make a new key** and add it to your GitHub account, as in 1.1.
3. **Ask for the recovery** while the freeze is in force: `om recover --new-key PATH`. The new key signs the request, and the pull request must come from your own GitHub account, the one the ledger records for you.
4. **Two Master Builders co-sign**, or as many other Master Builders as answered within the last year (below). Each must be satisfied, by a means they already trusted before the loss, that the person asking is you. A Master Builder never co-signs on the word of a new account or a new channel.
5. **Wait 21 days.** This is the notice. During it, whoever holds the old key can stop the recovery with one signed entry (`om recover-object`). If you find your old key, stop the recovery yourself and use 1.1 (a later request needs another new key: the key of a request is registered for good).
6. **Complete it** (`om recover-apply`) between day 21 and day 60, once it has its co-signatures (`om me` shows it `ready` only then), with the new key, which must still be listed on your GitHub account. From the next entry on the new key is yours and nothing is frozen.
7. Remove the old key from GitHub. You cannot replace the new key again for 30 days.

**Without a freeze** (an open recovery), step 1 is skipped and the rest changes so:

- **Three Master Builders co-sign**, or as many other Master Builders as answered within the last year (none, where you are the only one). While such a Master Builder who is not one of your sponsors exists, the co-signers are not all your sponsors.
- **The notice is 30 days**, and it starts at the co-signature that completes the number. From that moment the old key is frozen until the recovery ends.
- **Any other Master Builder who did not co-sign may oppose it** (`om recover-oppose`); at one fifth of the active Master Builders other than you, rounded up and never fewer than one, it is void.
- **Fewer Master Builders than the number it asks for** (three, or two after a freeze): the number is lowered to the Masters who exist, and the notice is **45 days** instead, on either path.
- After the old key stopped one recovery, the next one (90 days later) cannot be stopped by it and needs three co-signers, or as many other Master Builders as answered within the last year, with the 45-day notice when that is fewer.

On either path:

- **Only the Master Builders who answered are waited for.** A recovery counts, among the co-signers it may need, only the other Master Builders who revealed a vote or reported in an examination within the last 365 days, or who reached the 3rd degree within them. A Master who signs a work a year and answers nothing keeps every other power, opposition included, but is not waited for: otherwise one such Master held every request open until it expired, forever. Where every other Master answered nothing for a year, the recovery rests on what protects the only Master: your GitHub account (the request and the completion come from it, with a new key it lists), the 45 days of notice, the old key's objection and the opposition of any Master Builder (SPEC section 12, points 62 and 76). The old key stops only one request: a thief who holds your GitHub account asks again 90 days later, and that final request, which the old key cannot stop, applies after 45 days unless a Master Builder opposes it (section 9).
- **A request open 30 days with fewer co-signatures than it needs** (those given by then, counted as one at least while another Master Builder exists; and, without a freeze, only while its notice had not begun by then) then needs only those already given, and never fewer than one while another Master Builder who answered exists, so that one absent Master never blocks it. Its notice is then 45 days: after a freeze it runs from that thirtieth day and the old key stays frozen meanwhile; without a freeze it runs from that moment where the co-signatures already given are enough, and otherwise from the co-signature that makes them enough.
- **A departure is reversed by a recovery** asked before it or within 30 days after it, once that recovery is completed: a stolen key that signed `depart` does not end the membership. It is also reversed by a recovery that follows such a recovery, whatever ended it, when it is asked within 150 days of that recovery's request or of the old key's stop of it, and one such follow-up may follow another; a Council seat the departure ended comes back only into a vacancy. Otherwise the departure stands, and the way back is a new invitation after 90 days.

What can go wrong:

| What happened | What it means | What to do |
|---|---|---|
| The old key stopped the recovery | Someone holds it. The recovery is canceled, and no new request is accepted for 90 days. | Ask again after the 90 days, with another new key: that final recovery cannot be stopped by the old key. Meanwhile the matter is also for the members (a sanction ballot can suspend the membership), and the Custodian may freeze the key again once 90 days have passed since the first freeze began. |
| The Master Builders doubt the request | They object to the freeze. At one fifth of the eligible Masters the freeze is void and the recovery ends with it. | Convince them, in public, and ask again after 90 days, with another new key. |
| 60 days passed | The recovery lapsed. | Ask again after 90 days from the first request, with another new key. |
| The thief replaced your key first | The freeze is on your login, not on a key, so it still holds. A completed recovery replaces whatever key the ledger holds then. | Take your GitHub account back first: a recovery must come from it. |
| No Custodian exists, or none answers | No key can be frozen. | Use the path without a freeze. Keep a second copy of your key, or a hardware token and its backup, all the same: a recovery takes 30 to 45 days. |

A membership is also bound to one GitHub account, by its numeric id. Keep that account's own recovery codes safe: no entry replaces an account.

---

## 2. The custodian key is stolen or lost

The Custodian holds three keys: a member key, a custodian key and a revoke key ([charter](../governance/CUSTODIAN.md), section 2). A custodian key never changes; it can only end. While few Masters exist, a founder may then take up the office again with new keys (2.6).

### 2.1 The custodian key is stolen

1. **Revoke it at once.** Sign one `custodian_revoke` entry with the revoke key: draft it with `om revoke-custodian NAME --revoke-key PATH`. Any GitHub account may open the pull request that carries it.
2. From the next entry on the custodian key signs nothing. Every freeze, stay, halt and hold it had in force ends at that moment, and no noticed act it posted is ever applied.
3. Say so in public, in an issue labeled `capture-alarm`, with the number of the entry.
4. If this was the only Custodian, **no correction exists from now on**, unless a founder takes up the office again (2.6). Key recoveries go on without a freeze (1.2). Section 9 of the charter says how the administration is handed over.

### 2.2 The custodian key is stolen and the revoke key cannot be used

1. Any Master Builder other than the Custodian's member opens the removal ballot: `om open custodian NAME`. It takes seven days to commit and three to reveal, and passes by a simple majority of the votes cast.
2. Nothing the thief signs can stop that ballot: it runs through a halt, a frozen member may vote in it, and no correction can stay, void or undo it.
3. Meanwhile the Master Builders object to each abusive correction (`om object`). One fifth of the eligible Masters, never fewer than one, voids it for good. Objections are accepted during a halt.
4. A thief with the custodian key is still bound by every limit: five corrections in 30 days, one halt in 90 days, 14 days of notice before any ballot is voided or undone, and no power to admit, advance or sanction anyone.
5. If the Custodian's member is the only Master Builder, there is no one to vote. The thief's acts are then answered by publicity, by the limits above and, at the worst, by section 7.

### 2.3 The custodian key is lost, not stolen

1. If the revoke key is at hand, revoke the custodian key as in 2.1. That makes the end certain and immediate.
2. Otherwise do nothing: a custodian key that signs no sign of life for 180 days lapses for good. Say in public that it is lost.
3. Acts already in force run to their own end, 30 days at most, or until the key lapses, whichever comes first.

### 2.4 Only the revoke key is lost or stolen

- Lost: the custodian key still works and still ends by silence, by the Sunset or by removal. Say in public that the revoke key is lost.
- Stolen: all a thief can do with it is end the office. Treat it as 2.1 done by someone else.

### 2.5 The Custodian disappears

1. After 180 days without a sign of life the custodian key lapses by itself. No entry is needed.
2. The ledger goes on: ledger pull requests are admitted by the judge without any administrator, and key recoveries need no Custodian (1.2).
3. What stops is what only an administrator can do on GitHub: code-owner review, settings, the renewal of the witness token. If that blocks the fraternity, follow section 4.

### 2.6 A founder takes up the office again

Whenever no custodian key is live (lapsed, revoked, removed or never named), the Sunset has not come and fewer than three active Master Builders who are not founders exist, a founder may take up the office again, as often as needed (Constitution Art. XVI.10, SPEC section 6.31). Never a founder against whose custodian key a removal ballot passed.

1. **Make two new keys**, a custodian key and a revoke key, each one this ledger has never seen, and choose a custodian name nobody holds.
2. **Claim the office** with a `custodian_claim` entry signed by your member key (`om claim-custodian`), from your own GitHub account (the judge compares its numeric id with the one the ledger holds for you). Both new keys prove themselves in it, as at genesis.
3. **Wait 30 days.** This is the notice. Any active Master Builder who is not a founder may stop the claim with one `custodian_claim_object` entry (`om object-claim SEQ`), until it is applied: one is enough. After an objection, no founder claims again for 30 days. A stolen member key therefore never mints the office against the Masters who are there.
4. **Apply it** with `custodian_claim_apply` (`om apply-claim SEQ`), between day 30 and day 60. Every condition is checked again that day. The new key is the only live custodian key, so a noticed act needs that one key; it lapses by silence, at the Sunset, by its revoke key, by a removal ballot, and seven years after this day.

With three or more active Master Builders who are not founders, or after the Sunset, no claim is accepted: the office is filled only by amendment (Art. XVI.10 and XVI.14).

---

## 3. A witness token or key is compromised

A witness holds two different things: a **GitHub token**, with which its node opens pull requests, and a **witness key**, with which it signs entries.

### 3.1 The token

1. Revoke the token on GitHub at once and issue a new one with the permissions of [LAUNCH.md](LAUNCH.md).
2. Look at every pull request the token opened since the leak, and at every change on `main`. A token cannot forge a signature: the worst it can do is open pull requests the judge refuses, or noise.
3. The Custodian records the emergency as a `note`.

### 3.2 The key

1. **Freeze it.** The Custodian signs a `freeze_witness` correction (`om correct`). For 30 days that key signs nothing. If it is the last witness that is not frozen, the freeze needs the ground `attack_in_progress`.
2. **Remove it.** A Master Builder opens a witness ballot to remove the key (`om open witness NAME --measure remove`). It is decided by the amendment rule.
3. **Replace it.** The operator signs the proof of possession of the new key (`om proof witness NAME --key PATH --out FILE`), and a second witness ballot adds it (`om open witness NAME --measure add --witness-key KEY --witness-proof FILE`).
4. **Check what the stolen key signed.** A witness key can close a ballot whose windows ended, perform a lot, and sign a checkpoint. Each is checked by replay: a close computes the result from the votes, a lot is compared with the public beacon, a checkpoint must state the true state digest. A stolen witness key cannot change an outcome; it can only sign what any member could have signed.
5. While every witness is frozen, members close ballots and perform lots themselves (`om close`, `om draw`).
6. If the addition of a witness was itself obtained by fraud, no correction undoes it (the Custodians are recused from the ballots the Sunset counts): the Master Builders remove the witness by ballot, as in step 2.

Without a Custodian, steps 2 to 5 still work; only the freeze is missing.

---

## 4. The GitHub account or organization is lost

The account may be locked, suspended, taken over or simply unreachable. The sole owner of an organization is a single point of failure; mirrors and this runbook are the answer to it.

**What is not lost:** the ledger, the law and the teaching, which are in every clone and every mirror. **What is lost:** issues, discussions and the content of the rooms. That is why nothing of lasting value may exist only in a room.

**Where the canonical ledger lives** is what the ratified `src/openmasonry/network.toml` says. That file is part of the protocol core, so it changes only by amendment. It is not what a host says, and not what whoever controls a GitHub account says.

1. **Verify what you hold.** Every member runs `om verify` in their own clone. The client remembers the last head of the canonical ledger it verified.
2. **Find the longest ledger that verifies.** Witness operators and members publish, wherever they can reach each other, the head they hold: its number, its hash and its state digest (`om verify --json`). Two clones that hold the same head hold the same history.
3. **Stand up a new home.** A witness operator, or any Master Builder, publishes a full clone as a new repository and applies every setting of [LAUNCH.md](LAUNCH.md), so that the judge runs there as it did before.
4. **Work there by your own decision.** Until the move is ratified, the canonical location is still the old one. A member who chooses to work at the new home sets `OM_CANONICAL=owner/repository` for their own tools. The client still holds the new home against its memory: it goes on only if that ledger has the same genesis and still contains the head the member verified. If it does not, see section 8.
5. **Ratify the move.** A Master Builder opens an amendment of `@protocol` whose tree differs only in `network.toml` (section 6). It needs two thirds of the votes cast and a turnout of one third of the active Master Builders, like every amendment. When it has passed and the change is merged, everyone removes `OM_CANONICAL`.
6. **Rebuild around it.** Witness operators point their nodes at the new home. The rooms are created again and their access is set again from the ledger. Mirrors are pointed at the new home.
7. **If the old home comes back,** or two homes compete, both hold the same genesis and one of them holds entries the other lacks. Each member's client says which one contains what that member verified. A continuation with the same genesis and intact Landmarks is not an offense (Landmark VII); where the members sign their entries is where the fraternity is.

If the account was taken over, treat `main` at the old home as hostile from the moment of the takeover: the judge still refuses invalid entries, but the settings that make the judge binding are now in other hands.

---

## 5. A flaw in the protocol is found

A flaw not yet repaired is one of the few secrets Landmark II permits. It is kept only until the repair is in force.

1. **Report it in private**, as [SECURITY.md](../../SECURITY.md) says: a private security advisory, with a ledger that the verifier wrongly accepts or wrongly refuses.
2. **Stop the harm, if there is harm.** While a Custodian exists:
   - an open ballot that the flaw distorts is stayed (`stay`, 14 days) and, after 14 days of notice, voided (`void_ballot`); both are posted only before its reveal window opens, and neither reaches an amendment, the removal of a Custodian, a ballot that adds a witness or an advancement to the 3rd degree;
   - if the flaw is being used against the whole ledger, the ledger is halted (`halt`, 14 days, ground `attack_in_progress`). A halt stops every ballot except an amendment and the one that removes a Custodian: the amendment that repairs the flaw runs through it, on wall time, and so do key replacements and recoveries.
3. **Prepare the repair** in the private advisory: the corrected code, a test, and a conformance vector that fails before and passes after.
4. **Amend.** The repair changes the protocol core, so it needs an amendment of `@protocol` (section 6). The ballot is public and states the digest of the repaired tree. Only an amendment ballot may set its windows, and the shortest is two days to commit (at least seven while any Master Builder is dormant) and one to reveal: `om open amendment @protocol --sha256 DIGEST --commit-days 2 --reveal-days 1`. The reveal window opens 6 hours and 15 minutes after the commit window closes, and the ballot may be closed as soon as every elector has revealed (`om close`, by any active member or a witness). An amendment that alters the decision function, the electorates, the sponsorship rules or Article VII itself needs two passed ballots at least 90 days apart (Constitution Art. VII.3): the first is a first reading on `first-reading/protocol.patch` (section 6).
5. **Activate.** When the ballot has passed, the pull request with exactly that tree is merged. Witness operators rebuild their nodes from it: a node whose own core differs from the pin signs nothing.
6. **Repair what the flaw let through.** Within 90 days of its close, an admission, or an advancement to a degree other than the 3rd, that passed through the flaw is undone by a correction on the ground `protocol_defect`, with 14 days of notice. Anything else (an amendment, a sanction, the addition of a witness, an advancement to the 3rd degree, an older ballot) is repaired by a new ballot of the members. Nothing is erased.
7. **Publish** the advisory, the reason of every correction and the credit to the reporter.

Without a Custodian, steps 2 and 6 fall to the members alone: they repair by amendment and by new ballots.

---

## 6. Upgrading the pinned core

The protocol core is the list of files in `src/openmasonry/protocol.manifest`, pinned by one digest as `@protocol`. The judge always runs the code of the base branch and reads the pull request as data. The order is therefore **amendment first, then the pull request that applies it**.

1. **Prepare the new tree** on a branch: the changed files and, if a file is added to the core or removed from it, the changed manifest. A rule that changes applies from a fixed future time or entry number written in the code the ballot pins, later than the last moment at which the ballot can close plus the 30 days in which the previous text stays lawful, and never to the entries already merged. It never branches on the protocol epoch alone (`S.epoch`, the number of amendments of `@protocol` that passed): the epoch moves when the ballot closes, before the new code is merged, and an entry accepted by the old code in between would be refused by the new one on replay (SPEC section 12.7).
2. **Compute its digest:** `om digest --root DIR`, and **replay `main` with it:** the `candidate` check of the pull request (`tyler.yml`, run by GitHub, away from anyone's keys) must pass: the new core reaches the same head and the same state digest (or, where it changes the state document, the same head and a stated new version). Electors check it before they vote. **`om verify --candidate-root DIR` executes the code of DIR** on the machine that runs it, as that user, with every key and file in reach (`~/.ssh`, the ssh-agent, `~/.config/openmasonry`): the code of a pull request is untrusted until it is ratified. So `om verify` refuses to run it unless the person types `RUN` at its prompt or passes `--i-trust-this-code`. An elector who wants the check on their own machine runs it only in a disposable container or VM that holds no keys (a fresh clone of the repository, the candidate tree and nothing else), never where their member key lives, and must print `VALID` there.
3. **Amend.** Open the amendment ballot: `om open amendment @protocol --sha256 DIGEST`. Publish the branch, so that every elector can compute the same digest before voting.
4. **Wait for the ballot to pass.** Until it is closed as passed, the pull request is unlawful and the judge refuses it.
5. **Open the pull request with exactly that tree.** The old code judges it: it reads the new manifest from the pull request, computes the ratified digest, and lets it through.
6. **Merge.** From then on the new code judges `main` and computes the same digest. Between the close of the ballot and the merge, the previous text stays lawful for 30 days of ledger time.
7. **Rebuild the witness nodes** from the merged tree.

**Two readings.** An amendment that alters the decision function, the electorates, the sponsorship rules or Constitution Art. VII needs two passed ballots at least 90 days apart (Art. VII.3). The first ballot pins `first-reading/` followed by the governed path (for the core, `first-reading/protocol.patch`, the patch that makes the change), never the governed path itself, since the verifier pins whatever path a passed amendment names; the second, at least 90 days later, pins the governed path to exactly the text the first reading ratified.

The same order holds for the Constitution, the two charters and the degree canon. For the degree canon, the new table is archived as `canon/history/<sha256>.toml` no later than the ballot is opened: the ledger refuses to open an amendment of `canon/degrees.toml` whose table is not archived. The ledger pull request that opens the ballot may add that one file itself; the judge holds it to its name (the sha256 of its bytes) and to the ballot.

### 6.1 The one case that cannot pass the judge

A change in **how the `@protocol` digest itself is computed** (another hash or framing, another path or form of the manifest, another set of required paths, or a judge that reads the list from somewhere else) cannot be applied by the steps above. The old code gives the new tree one digest and the new code gives it another; a pin has one value, so no single amendment satisfies the judge before the merge and the audit after it.

It is done in two ordinary upgrades, and never by hand:

1. **First upgrade: a core that accepts both.** Prepare a tree whose code computes the digest both ways and accepts a tree when either value equals the pin. Its own digest is computed the old way. Amend, apply and merge it by steps 1 to 7. Nothing changes for anyone yet.
2. **Second upgrade: pin the new computation.** Prepare the tree that is to stand, and compute its digest the **new** way. Amend with that value. The judge, which now runs the code of the first upgrade, finds that the new computation equals the pin, and lets the pull request through.
3. **Optional third upgrade:** remove the old computation, as an ordinary upgrade under the new one.

Each step is an amendment, so the members vote on the change of the computation twice. The ruleset's emergency bypass could force such a change through in one step; that is exactly what the judge exists to prevent, and it is not a lawful way to change the protocol. If a bypass was ever used on the core, it is recorded as a `note`, and every clone and witness will report the tree as unratified until an amendment pins it.

### 6.2 A change of the state document

The state digest that checkpoints state is computed from the state document, whose version is `STATE_VERSION` (SPEC section 4.11), and every checkpoint names the version it was computed under (`state_version`). A core that changes the document gives it a new version. The candidate check then holds the new core to the same head only, and says so in a warning; the new core judges each existing checkpoint by the document of the version it names, or takes it on trust. Such a change is an ordinary upgrade (steps 1 to 7).

---

## 7. The last resort: a recovery genesis

A recovery genesis is a **new entry 0**: a new ledger that takes up the state of the old one. It is for the case in which the ledger cannot continue under its own rules at all: no lawful entry can be added, or the rules of replay themselves are broken in a way no amendment can reach.

It is the last resort because it breaks the chain of hashes. Every client will report `DIFFERENT GENESIS`, and every person must decide for themselves whether to follow it.

A recovery genesis is the same fraternity **only if all four hold**. Anything else is a different fraternity, which anyone is free to found under another name (Landmark VII).

1. **It pins the same Landmarks, byte for byte.** The pin of `canon/eternal.toml` and the digest of the Declaration are the values of the first genesis.
2. **It carries the state unchanged.** The state digest it starts from is the state digest of the old head: every member, degree, standing, ballot and pin as they stood. Nobody is added, removed, promoted or pardoned by it.
3. **It names the old head:** the number and the hash of the last entry of the old ledger, so that anyone can replay the old ledger to that entry and compare the digest.
4. **It is made in public,** with the reason, and the old ledger stays published beside it.

How it is done:

1. Agree, in public, on the old head: the last entry that verifies, and its state digest (`om verify --json`). Witness checkpoints state that digest too.
2. Publish the code that reads a ledger starting from that state. The protocol as it stands defines no such entry: an ordinary genesis names founders and cannot carry a state. A recovery genesis therefore comes with a version of the protocol core that adds exactly this and nothing else, published so that anyone can read the difference.
3. Publish the new entry 0 with the four properties above.
4. Each member checks the four properties for themselves, and then accepts the new genesis on their own machine: `om verify --accept-genesis HASH`. This is the person's decision. An agent never passes that flag by itself.
5. The members ratify the new home as in section 4, and go on.

Two things a recovery genesis is not. It is not a way to undo a decision: the state is carried unchanged. And it is not needed to move house: a continuation with the same genesis and intact Landmarks, on any host, is the same ledger, and it is not an offense.

---

## 8. What your client shows, and what to do

Before it drafts, approves or signs anything, your client holds the canonical ledger against its own memory of the last head it verified. Four messages mean it has stopped, and nothing is signed while one of them stands (`om verify` still exits 0 on `BEHIND`, which is no fault of the ledger).

| Message | What it means | What to do |
|---|---|---|
| `BEHIND` | The canonical ledger you fetched is shorter than what you verified before, and nothing shows it was rewritten. Most often you fetched from a mirror that lags. | Fetch again from the canonical repository, later if need be. If the canonical repository itself stays short, treat it as `ROLLBACK`. |
| `ROLLBACK` | The canonical ledger no longer contains an entry you verified. History was rewound or rewritten. | Sign nothing. Keep your clone as it is: it is evidence. Compare heads with a witness or a mirror, and raise a capture alarm (`om alarm TITLE BODY`; the Custodian labels the issue `capture-alarm`). The repair is to restore `main` from a clone that holds the true history, or to continue elsewhere (section 4). |
| `DIFFERENT GENESIS` | The canonical ledger starts from another genesis than the one you verified. It is another fraternity, or a recovery genesis (section 7). | Check where your remote points. Accept another genesis only on purpose, after checking it yourself: `om verify --accept-genesis HASH`. |
| `FUTURE HEAD` | The last entry is dated more than ten minutes ahead of your clock. Every notice period is counted from entry times, so a post-dated entry bends them. | Check your own clock first. If it is right, a gate was passed around: raise a capture alarm (`om alarm TITLE BODY`). Nothing is signed on that ledger until the clock has caught up. |

`om verify --accept-genesis HASH` also accepts a fork of the same genesis after a `ROLLBACK`. It is always the person's own decision, made once and on one machine. No officer, no Custodian and no agent can make it for you.

Two more messages come from the verifier itself. `INVALID` means the ledger does not replay: an entry breaks a rule. `UNRATIFIED` means a governed file, a workflow or the reason of a correction in the tree is not what the ledger pins. In both cases the copy you hold is not lawful as it stands; fetch from the canonical repository and, if it persists there, raise a capture alarm.

---

## 9. No Master Builder is left

The fraternity can lose its last Master Builder: the founder departs, goes silent or loses every key, before anyone else reached the 3rd degree. The game does not stop (SPEC section 6.34).

1. **Claim the succession.** Any active member below the 3rd degree signs a `succession_claim` (`om claim-succession`) while no active Master Builder is present. A Master who has signed nothing for 365 days is dormant and does not count; nor does a silent one, called to at least two examinations or ballots that ended in the last 180 days, at least 7 days apart, without a revealed vote or a report in any of them. Only a ballot that gave at least 7 days to commit is a call, and a vote committed but never revealed is no answer. The call of an examination that timed out is recorded when the candidate opens the next examination for that degree, so a lodge with one Master who never reports may need a third examination before the claim is accepted. **After a timeout the next lot seats everyone any rung holds** (without the examiners already found silent), so every Master who never answers is called: open the next examination at once after each timeout, and within about three examinations (180 days) all of them are silent, however many they are, founders among them: for a founder candidate too (a founder who departed and was admitted again under the same GitHub account is a founder below the 3rd degree), the lot after a timeout seats the founding cohort (SPEC section 12, point 75).
2. **Wait 90 days.** Any entry of a Master Builder who, after it, is active and neither dormant nor silent cancels the claim: a Master who wakes up is there, and nobody stands in for them. One revealed vote or one report ends a silence; a `work` does not.
   - **A silent Master who returns.** Reveal one vote, in any ballot you are an elector of, or report in an examination you were drawn for. If no ballot is open, open an amendment ballot with at least 7 days to commit, commit a vote and reveal it when the reveal window opens (vote no if the text is there only to be answered: a ballot that fails changes nothing): from that reveal you are present again for 180 days, and your next entries cancel a pending claim. `om me` tells you when you count as silent.
3. **The successors.** From day 90, the active members of the highest degree present, neither dormant nor silent, stand in for Master Builders in four things only: they are the last rung of the lot of examiners, they elect an advancement where no Master Builder is present to elect it, and they may invite and sponsor. They open no amendment, witness, sanction or custodian ballot, vote in none, object to nothing, and never count for the Sunset, the Founding Phase or the sponsors an admission needs. While the succession is in force every member's calls are recorded: a successor who is called to two examinations or ballots and answers none is silent and left out, and the next degree down stands in for them. An admission does not wait for a silent member either: where every member of the 2nd degree or higher is dormant or silent, the members of the 1st degree elect it, and every member keeps the vote. So a lone successor behind a silent Master invites and admits a newcomer, who can then examine them.
4. **Climb back.** A successor examines and elects the next member of their degree, and the two of them can then examine and elect each other to the 3rd degree. A dormant Master keeps the vote in every electorate throughout.
5. The succession ends for good once three active Master Builders who are neither dormant nor silent exist.

Some cases are stuck by nature, and the documents name the way out:

- **No member holds a key**: nobody can sign anything, and the only way on is a recovery genesis (section 7).
- **A member holds a key but no GitHub account**: every entry a member signs must come from that member's account (a `depart` and a `rekey_object` excepted, which anyone may carry); recover the account first, or move house (section 4). With a single member, that GitHub account is the root of trust.
- **A deadlock among very few members**: where one no defeats every proposal, the way on is a fork (Landmark VII).
- **The host or the judge is dead and nobody administers the repository**: move house (section 4), or judge by hand (section 10).
- **A head dated far in the future was merged past the gate**: every later honest entry is refused until the clock catches up; restore `main` from a clone that holds the true history (section 8).
- **No Master Builder is left and the drand beacon is retired**: no lot can be drawn, so no examination opens and no member reaches the 3rd degree. The way on is an amendment that names another source of public randomness, which needs Master Builders to vote, so in practice a recovery genesis (section 7), or a fork.
- **A merged core refuses its own history**: merge the previous core back while its pin is still lawful (30 days after the close), or, past that, a recovery genesis (section 7).
- **The same login invited again and again by one Master, with a wrong account id**: replay alone lets a new invitation of a login replace the lapsed one, so one Master can keep a login from every other inviter for 30 days at a time. The identity gate refuses an invitation whose login is not the GitHub account with the id it states; under manual judging (section 10) never skip that step (SPEC section 12, point 70).
- **One login that holds the single freeze slot**: with fewer than 20 active members one key is frozen at a time, and a recovery under way counts. A login that a custodian key freezes again every 90 days, and that asks for a recovery after each freeze which nobody co-signs, keeps the slot full for as long as the two act together, and so holds back every freeze of another login. It never holds back a recovery: a co-signature, or a request that needs none, starts the notice of a recovery whatever else is frozen, so a stolen key is stopped by its own recovery (section 1), not by a freeze. The way out of the held slot: a Master who is not the custodian's member objects to the freeze, the custodian's revoke key, or the removal ballot (SPEC section 12, point 71).
- **A departure kept reversible by a chain of follow-ups**: a recovery asked within 30 days of a departure, and every request after it within 150 days of the one before, keep the departure reversible, with no end. Only whoever controls the member's GitHub account can add a link (the identity gate takes a request only from that account, with a new key it lists), at the cost of one request every 90 to 150 days; a thief with the old key alone cannot. A link that expires, is opposed or is stopped ends that link and not the chain. The link that completes needs its co-signers (after 30 days, those given by then, at least one where another Master exists) and 45 days of notice nobody opposes, and it restores the member at their degree, with no admission ballot (SPEC section 12, point 58). A departure with no recovery in play is final after 30 days.
- **A Master made silent by examinations decided at once**: the report that decides an exam ends every examiner's call, and at the 2nd degree one `fail` decides. A Master drawn twice beside the same other Master, the draws at least 7 days apart, can be made silent within about 7 days by that Master's two reports given right after each draw. It needs two lots that seat both, and works only on a Master who answered nothing in the last 180 days. The victim answers by a late report in either exam (accepted until that exam lapses or expires, 60 days from its opening) or by any revealed vote, and keeps every vote meanwhile (SPEC section 12, point 73).
- **Every other Master Builder answers nothing, and a key is lost**: the recovery does not wait for them (section 1.2); it rests on the member's GitHub account, the 45 days of notice, the old key's objection and the opposition of any Master Builder. Whoever controls that GitHub account, with a new key it lists, takes the membership in 45 days if nobody watches the ledger, and in about 135 days even when the member watches: the old key stops one request, and the next one, asked 90 days after the stop, cannot be stopped by it and applies after 45 days of notice unless a Master Builder opposes it. Ask the Masters to oppose it, and take the GitHub account back; one other Master who answered within the year closes that path, because the final request then needs that Master's co-signature (SPEC section 12, points 62 and 76).
- **One Master who answers among peers who do not**: outside the Founding Phase, an admission needs two sponsors only while seven or more Master Builders are present (neither dormant nor silent); with fewer, one sponsor suffices once the petition has been live 30 days. Two ballots of at least 7 days to commit, at least 7 days apart, call every Master and make those who answer nothing silent; every Master still votes on the admission (SPEC section 12, point 77).
- **A founder's claim of the Custodian office objected to**: after an objection, no founder claims again for 30 days, so a claim cannot hold a name out of invitations claim after claim.

---

## 10. Manual judging

The judge is a convenience; `verify` is the law. A merge into `main` is lawful when, and only when, the resulting `main` passes the pinned verifier: `python3 -P -m openmasonry.verify --tree` run with the core of `main` itself (and, for a pull request of entries, the checks the judge runs: `--since`, `--pr-author`, `--clock-since`, `--online`). When the judge cannot run (GitHub Actions is down or disabled, the runner image lost its Python, a third-party outage, nobody left who can repair a setting), an administrator may merge by hand:

1. **Fetch the pull request** into a clean clone of `main`, as data: do not run anything of it.
2. **Run what the judge runs** (`.github/workflows/judge.yml`), both steps: the shell checks of the step "Gates" (append-only entries and archive, ledger-only, no implicit code, no shadows, no links, no new workflow), then the pinned verifier of `main`, as in the step "Replay, identity, governed files, fresh timestamps, public beacons": `python3 -P -m openmasonry.verify --ledger PR/ledger/entries --tree --root PR --base-root MAIN --online --clock-since N --pr-author LOGIN --since N --pr-author-id ID --anchors-changed FILE`, where `N` is the number of entries of `main`. Keep the full output.
3. **Merge only if it prints `VALID`.** A merge that the verifier refuses is not lawful, whoever makes it, and every clone and witness will report it.
4. **Record each use** as a `note` (act `other`, target the pull request, rule `docs/operations/RECOVERY.md#10-manual-judging`), with the verifier's output in its public reason. Where no Custodian exists, say it in a public issue instead.
5. The audit of the Tyler, and every member's own `om verify`, judge the result again: a hand merge is checked like any other.

The same holds for every workflow the judge uses: none of them adds a rule. If a workflow refuses what the verifier accepts, the verifier is right, and the workflow is repaired by amendment of `@protocol`.

---

## 11. The room sync App key is compromised

The room sync acts through a GitHub App whose only permissions are the members of the organization `openmasonry-org` and the read-only listing of the applications installed on it, which the published access file (`actual.json`) names ([ops/rooms/README.md](../../ops/rooms/README.md)).

1. **Revoke and rotate the key** in the App's settings (`openmasonry-org` → Settings → Developer settings → GitHub Apps → the App → Private keys): delete the exposed key, generate a new one, and replace the secret `ROOMS_APP_PRIVATE_KEY` of the private `ops` repository.
2. **Check what it changed.** The guards of the sync bound the program, not the key: whoever holds the key can change the membership of the organization directly. Compare the room teams with the derived roll (`bin/om rooms`, and the Console's alarms), and let the next run of the sync set them back from the ledger.
3. **Record the emergency** as a `note`; where no custodian key is live, report it in a public issue instead.
