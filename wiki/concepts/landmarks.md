---
title: "Landmarks"
type: concept
tags: [law, landmarks, freemasonry, tradition]
sources:
  - raw/sources/sym-landmarks-anderson-mackey-pound.md
  - raw/sources/sym-regularity-ugle-1929.md
  - canon/eternal.toml
---

# Landmarks

The "ancient landmarks" of Freemasonry: principles that, by definition, no Masonic authority can change. The term comes from General Regulation XXXIX of the 1723 *Constitutions*, which orders that "the old Land-Marks" be preserved **without saying what they are**. The biblical echo is Proverbs 22:28: "Remove not the ancient landmark, which thy fathers have set."

**The lists**
- **[[albert-mackey]] (1858)** was the first to enumerate them: **25 landmarks**, with immemorial and universal custom as the criterion. The list includes the modes of recognition, the three degrees, the legend of the third degree, the powers of the Grand Master, the "tyled" lodge, the candidate's qualifications (a man, freeborn, without physical defect), belief in God and in a future life, the Book of the Law, equality, secrecy and, as the 25th, immutability itself.
- **Roscoe Pound (1911)** reduced them to 7.
- **American Grand Lodges** adopt lists of 3 to 54 items. Only a minority formally adopted Mackey's.
- In the 1950s, a North American recognition commission summed everything up in three standards: monotheism, the Volume of the Sacred Law, and no religion or politics in lodge.

**Readings**
- **Conservative:** the landmarks are the identity of the Order. Removing them means ceasing to be Freemasonry (see [[regularity-and-recognition]]).
- **Critical:** since there has never been a universal list, "landmark" often works as a rhetorical trump card to declare a local preference unchangeable.
- **Historical:** several of Mackey's "immemorial" items (such as the legend of the third degree) date from the 18th century.

## In OpenMasonry
OpenMasonry keeps the **form** (a core no vote can change) and replaces the **content**: the seven [[eternal-landmarks-of-openmasonry|Eternal Landmarks]] (Open Door, Light not Secrecy, Nothing for Sale, One Member One Vote, No Permanent Power, Verifiable Law, Exit and Fork). Immutability does not depend on an oath. It depends on cryptography:
- the genesis pins the SHA-256 of `canon/eternal.toml` (`ledger._genesis`);
- the opening of an amendment ballot compares the path without regard to case and rejects any amendment whose target begins with `canon/eternal.toml` (`ledger._open_amendment`);
- `verify --tree` reports the file as unratified if its bytes differ from the pin (`govern.check_tree`).

Changing the landmarks requires a public **fork**, with a new genesis and a new name. Note that Mackey's items 18–20 and 23 (exclusions and secrecy) are exactly what Landmarks I and II deny.
