"""The Observatory: the public view of the fraternity, computed only from the ledger (outside the pinned core).

`om rooms`, `om metrics`, `om timeline` print its parts; `om observatory --out DIR` writes the page:

  index.html     one self-contained page (no external script, style or font; inline SVG charts; light and
                 dark by the reader's system setting; links only to the canonical repository)
  metrics.json   om.metrics/1   (src/openmasonry/metrics.py)
  timeline.json  om.timeline/1  every entry as one described line
  rooms.json     om.rooms/1     the roll each room's access derives from the ledger, and, given the access
                                GitHub actually grants (--rooms-actual FILE, om.rooms-actual/1), every difference,
                                the owners and Apps beside it, and the log of the room sync's runs (the
                                runs.jsonl beside that file, when there is one)

Reading the ledger is the only input; nothing here signs, writes to the ledger or calls the network.
"""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import canon, rooms
from .ledger import Invalid, fold, iso, load, replay, ts
from .metrics import metrics

ROOMS_SCHEMA = "om.rooms/1"
ACTUAL_SCHEMA = "om.rooms-actual/1"
TIMELINE_SCHEMA = "om.timeline/1"
RUN_KEYS = ("time", "apply", "force_mass", "seq", "head", "result", "additions", "removals", "deferred",
            "note_required", "actions")                                       # all a run line of the room sync may carry
RUNS_SHOWN = 24
LOGO = canon.ROOT / "docs" / "assets" / "logo.svg"


def repo_url() -> str:
    return f"https://github.com/{canon.CANONICAL_REPO}"


# ------------------------------------------------------------------------------------------ the data ----

def rooms_report(st, now: datetime, entries_count: int, actual: dict | None = None,
                 runs: list[dict] | None = None) -> dict:
    """om.rooms/1: the derived roll of every room (public information: Constitution Art. XV.3) and counts.
    With `actual` (om.rooms-actual/1: the members of each room team, the owners and the applications), also
    the access GitHub grants and every difference from the roll; with `runs`, the room sync's log of runs."""
    access = rooms.room_access(st, now) if st is not None else {}
    roll = rooms.readers(access)
    gone = {"departed", "expelled", "voided"}
    of_record = [m for m in st.members.values() if m.standing(now) not in gone] if st is not None else []
    doc = {"schema": ROOMS_SCHEMA, "name": st.name if st else "", "head": st.head if st else None,
           "entries": entries_count, "time": iso(now),
           "rooms": [{"room": rooms.team(k), "degree": k, "readers": roll[k], "count": len(roll[k])}
                     for k in range(1, rooms.ROOMS + 1)],
           "counts": {"with_access": len(access), "without_access": len(of_record) - len(access),
                      "rooms_open": sum(1 for k in roll if roll[k])}}
    if actual is not None:
        doc["actual"] = compare(roll, actual)
    if runs is not None:
        doc["runs"] = [{k: r[k] for k in RUN_KEYS if k in r} for r in runs]
    return doc


def read_runs(text: str) -> list[dict]:
    """The lines of the room sync's runs.jsonl, oldest first; anything but an object per line is refused."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if line.strip():
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"line {n} is not an object")
            out.append(row)
    return out


def compare(roll: dict[int, list[str]], actual: dict) -> dict:
    """Per room: who GitHub lets read it (the members of teams k..33, every owner and every application)
    against the roll. Owners and applications read every room by their role; they are listed, not counted
    as differences. Logins compare without case, as GitHub's do."""
    if not isinstance(actual, dict) or actual.get("schema") != ACTUAL_SCHEMA:
        raise ValueError(f"the actual access must be a {ACTUAL_SCHEMA} document")
    teams = actual.get("teams", {})
    names = lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v)
    if not (isinstance(teams, dict) and all(names(v) for v in teams.values())
            and names(actual.get("owners", [])) and names(actual.get("apps", []))):
        raise ValueError("teams, owners and apps must be lists of logins")
    owners, apps = sorted(actual.get("owners", [])), sorted(actual.get("apps", []))
    unknown = sorted(t for t in teams if rooms.team_degree(t) is None)
    out = []
    for k in range(1, rooms.ROOMS + 1):
        granted = {fold(x): x for j in range(k, rooms.ROOMS + 1) for x in teams.get(rooms.team(j), [])}
        derived = {fold(x): x for x in roll[k]}
        out.append({"room": rooms.team(k), "missing": sorted(derived[x] for x in derived.keys() - granted.keys()),
                    "extra": sorted(granted[x] for x in granted.keys() - derived.keys())})
    return {"time": actual.get("time"), "owners": owners, "apps": apps, "unknown_teams": unknown,
            "rooms": out, "differences": sum(len(r["missing"]) + len(r["extra"]) for r in out) + len(unknown)}


def timeline(st, entries: list[dict]) -> dict:
    """om.timeline/1: every entry, oldest first, as one line built by `describe` from the entry itself."""
    from .actions import describe
    rows = []
    for e in entries:
        text = describe(st, e).split("\n\n", 1)[0]
        rows.append({"seq": e["seq"], "time": e["time"], "type": e["type"], "actor": e["actor"],
                     "line": " ".join(part.strip() for part in text.split("\n") if part.strip())})
    return {"schema": TIMELINE_SCHEMA, "name": st.name if st else "", "head": st.head if st else None,
            "entries": rows}


# ------------------------------------------------------------------------------------------ the page ----

def _e(x) -> str:
    return html.escape(str(x), quote=True)


def bars(title: str, rows: list[tuple[str, int]], width: int = 420) -> str:
    """A horizontal bar chart as inline SVG, colored by the page's CSS variables (both themes)."""
    if not rows:
        return f'<p class="muted">{_e(title)}: nothing yet.</p>'
    top = max(v for _, v in rows) or 1
    label_w, bar_h, gap = 120, 20, 6
    h = len(rows) * (bar_h + gap) + gap
    out = [f'<svg viewBox="0 0 {width} {h}" width="100%" role="img" aria-label="{_e(title)}">']
    for i, (label, v) in enumerate(rows):
        y = gap + i * (bar_h + gap)
        w = 0 if v == 0 else max(2, round((width - label_w - 44) * v / top))
        out.append(f'<text x="{label_w - 8}" y="{y + 13}" text-anchor="end" class="lbl">{_e(label)}</text>'
                   f'<rect x="{label_w}" y="{y}" width="{w}" height="{bar_h}" rx="3" class="bar"/>'
                   f'<text x="{label_w + w + 6}" y="{y + 13}" class="val">{_e(v)}</text>')
    out.append("</svg>")
    return f"<figure><figcaption>{_e(title)}</figcaption>{''.join(out)}</figure>"


_URL = re.compile(r"(?:https?:)?//([A-Za-z0-9.-]*)[^\s\"'<>)]*")


def defang(text: str) -> str:
    """Untrusted text from an entry, with every URL that does not lead to the repository replaced by a mention
    of its host: the page links nowhere else (the full lines are in timeline.json)."""
    return _URL.sub(lambda m: m.group(0) if m.group(0).startswith(repo_url())
                    else f"[a link to {m.group(1) or 'elsewhere'}: see timeline.json]", text)


def _table(head: list[str], rows: list[list]) -> str:
    th = "".join(f"<th>{_e(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="scroll"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def _logo() -> str:
    """The logo, inlined; the namespace attribute is dropped (inline SVG in HTML needs none), so the page
    names no URL but the repository's."""
    try:
        svg = LOGO.read_text(encoding="utf-8")
    except OSError:
        return ""
    return svg.replace(' xmlns="http://www.w3.org/2000/svg"', "").replace("<svg ", '<svg class="logo" ', 1).strip()


CSS = """
:root{--bg:#ffffff;--fg:#16213A;--muted:#5b6475;--line:#d8dee8;--accent:#2FB8A5;--card:#f5f7fa}
@media (prefers-color-scheme:dark){:root{--bg:#0f1522;--fg:#E6EDF3;--muted:#9aa4b2;--line:#2a3447;--accent:#2FB8A5;--card:#161e2e}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:960px;margin:0 auto;padding:16px}
header{display:flex;align-items:center;gap:12px;margin:8px 0 16px;overflow-wrap:anywhere}
.logo{width:44px;height:44px;flex:none}
h1{font-size:1.5rem;margin:0}h2{font-size:1.15rem;margin:28px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
.muted{color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px}
.card b{display:block;font-size:1.4rem}
figure{margin:12px 0}figcaption{color:var(--muted);font-size:.9rem;margin-bottom:4px}
svg{max-width:640px}svg .bar{fill:var(--accent)}svg .lbl,svg .val{fill:var(--fg);font-size:13px}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:.9rem}
th,td{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
details{margin:6px 0}summary{cursor:pointer}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.85rem;overflow-wrap:anywhere}
a{color:var(--accent)}
"""


def render(m: dict, tl: dict, rm: dict) -> str:
    """The page, from the three documents it is published with (and nothing else)."""
    title = "OpenMasonry Observatory"
    repo = repo_url()
    parts = [f'<header>{_logo()}<div><h1>{_e(title)}</h1><div class="muted">Computed only from the public ledger of '
             f'<a href="{_e(repo)}">{_e(canon.CANONICAL_REPO)}</a> at {_e(m["time"])}. Every number can be '
             f'reproduced with <code>bin/om metrics</code>.</div></div></header>']
    if not m.get("founded"):
        parts.append('<p>The ledger is empty: the fraternity has not been founded yet.</p>')
    else:
        ch, mem, bal, adm, ex = m["chain"], m["members"], m["ballots"], m["admission"], m["exams"]
        wit, cus = m["witnesses"], m["custodians"]
        card = lambda k, v: f'<div class="card"><span class="muted">{_e(k)}</span><b>{_e(v)}</b></div>'
        parts.append('<section class="cards">' + "".join([
            card("entries", ch["height"]), card("members of record", mem["of_record"]), card("active", mem["active"]),
            card("Master Builders", mem["masters"]), card("open ballots", bal["open"]), card("witnesses", wit["count"]),
            card("founding phase", "yes" if mem["founding_phase"] else "no"),
            card("halted", "yes" if cus["halted"] else "no")]) + "</section>")
        parts.append(f'<p class="muted">Head <code>{_e(ch["head"])}</code>, entry #{_e(ch["last_entry"]["seq"])} '
                     f'({_e(ch["last_entry"]["type"])}) at {_e(ch["last_entry"]["time"])}.</p>')
        parts.append("<h2>Members</h2>")
        parts.append(bars("Members by degree", [(f"{d}°", n) for d, n in mem["by_degree"].items()]))
        parts.append(bars("Members by standing", list(mem["by_status"].items())))
        parts.append(f'<p>Dormant (no entry in the last year; they keep their vote and their rooms): {_e(mem["dormant"])}.</p>')
        months = sorted(set(mem["admissions_per_month"]) | set(mem["departures_per_month"]))
        parts.append(_table(["month", "admissions", "departures"],
                            [[mo, mem["admissions_per_month"].get(mo, 0), mem["departures_per_month"].get(mo, 0)]
                             for mo in months]))
        parts.append("<h2>The chain</h2>")
        parts.append(bars("Entries per month", [(mo, sum(c.values())) for mo, c in ch["entries_per_month"].items()]))
        parts.append("<h2>Ballots</h2>")
        kinds = [k for k, r in bal["by_kind"].items() if any(r.values())]
        parts.append(_table(["kind", "open", "passed", "failed", "lapsed", "voided", "undone", "mean turnout",
                             "median days to close"],
                            [[k, *bal["by_kind"][k].values(), bal["turnout_by_kind"].get(k, {}).get("mean", "—"),
                              bal["days_to_close_by_kind"].get(k, {}).get("median", "—")] for k in kinds])
                     if kinds else '<p class="muted">No ballot yet.</p>')
        parts.append("<h2>Admission</h2>")
        parts.append(bars("The admission funnel", [("invited", adm["invited"]), ("petitioned", adm["petitioned"]),
                                                   ("admitted", adm["admitted"]), ("refused", adm["refused"]),
                                                   ("undone", adm["undone"]),
                                                   ("invitation lapsed", adm["lapsed_invitations"]),
                                                   ("petition lapsed", adm["lapsed_petitions"])]))
        sp = m["sponsorship"]
        parts.append(f'<p>Sponsorship: {_e(sp["used"])} of {_e(sp["budget"])} places used by {_e(sp["sponsors"])} '
                     f'Master Builders (in aggregate; no one\'s budget is shown).</p>')
        parts.append("<h2>Examinations</h2>")
        parts.append(bars("Examinations", [(k.replace("_", " "), ex[k]) for k in ("open", "passed", "failed",
                                                                                   "timed_out", "lapsed")]))
        if ex["days_to_verdict"]["count"]:
            parts.append(f'<p>Median days from opening to verdict: {_e(ex["days_to_verdict"]["median"])}.</p>')
        parts.append("<h2>Witnesses</h2>")
        last = wit["last_checkpoint"]
        parts.append(f'<p>{_e(wit["count"])} witness(es), {_e(wit["frozen"])} frozen; {_e(wit["checkpoints"])} '
                     f'checkpoint(s), {_e(wit["anchors"])} with a timestamp anchor; last checkpoint: '
                     + (f'#{_e(last["seq"])} at {_e(last["time"])}' if last else "none yet") + ".</p>")
        parts.append("<h2>Custodians and corrections</h2>")
        parts.append(f'<p>{_e(cus["keys"])} custodian key(s): '
                     + (", ".join(f"{_e(n)} {_e(s)}" for s, n in cus["keys_by_status"].items()) or "none")
                     + f'. A noticed correction needs {_e(cus["threshold"])} key(s).'
                     + (f' Next sign of life due before {_e(cus["next_alive_due"])}.' if cus["next_alive_due"] else "")
                     + (f' The Sunset was reached at {_e(cus["sunset"])}.' if cus["sunset"] else "") + "</p>")
        parts.append(_table(["corrections", "pending", "objected", "void by objection", "halts", "stays", "notes"],
                            [[cus["corrections"], cus["pending"], cus["objected"], cus["void_by_objection"],
                              cus["halts"], cus["stays"], cus["notes"]]]))
        if cus["by_act"]:
            parts.append(bars("Corrections by act", list(cus["by_act"].items())))
            parts.append(bars("Corrections by ground", list(cus["by_ground"].items())))
    parts.append("<h2>Rooms</h2>")
    parts.append('<p>Each degree has a room, read by the members of that degree and of every higher degree who are '
                 f'not suspended, expelled or departed, nor held out by a correction (<a href="{_e(repo)}/blob/main/'
                 'docs/governance/ROOMS.md">the rules of the rooms</a>). Below is the roll the ledger derives. '
                 'Room activity is never measured.</p>')
    parts.append(bars("Readers per room", [(r["room"], r["count"]) for r in rm["rooms"] if r["count"]]))
    act = rm.get("actual")
    if act:
        parts.append(f'<p>Besides the roll, by their role, every room is read by the owners of the organization: '
                     f'{_e(", ".join(act["owners"]) or "none")}; and by every installed application: '
                     f'{_e(", ".join(act["apps"]) or "none")}.</p>')
    rows = []
    for r in rm["rooms"]:
        diff = next((d for d in act["rooms"] if d["room"] == r["room"]), None) if act else None
        rows.append([r["room"], r["count"], ", ".join(r["readers"]) or "—"]
                    + ([", ".join(diff["missing"]) or "—", ", ".join(diff["extra"]) or "—"] if act else []))
    parts.append("<details><summary>The roll of every room</summary>"
                 + _table(["room", "readers", "who"] + (["missing on GitHub", "extra on GitHub"] if act else []), rows)
                 + "</details>")
    if act:
        parts.append(f'<p>Access as GitHub granted it at {_e(act["time"])}: {_e(act["differences"])} difference(s). '
                     'An account the ledger does not name is shown only as "not on the ledger".</p>')
    else:
        parts.append('<p class="muted">The access GitHub actually grants is not part of this build.</p>')
    if "runs" in rm:
        recent = rm["runs"][-RUNS_SHOWN:][::-1]
        did = lambda a: ", ".join(f"{op} {res} {n}" for op, c in sorted(a.items()) if isinstance(c, dict)
                                  for res, n in sorted(c.items())) if isinstance(a, dict) else ""
        parts.append(f'<h3>The log of the room sync</h3><p class="muted">The newest {len(recent)} of '
                     f'{len(rm["runs"])} runs, all of them in <a href="rooms.json">rooms.json</a>. It names no '
                     'person: what each run did, in counts.</p>')
        parts.append(_table(["time", "mode", "ledger entry", "result", "actions"],
                            [[r.get("time", ""), "apply" if r.get("apply") else "dry run", r.get("seq", "—"),
                              r.get("result", ""), did(r.get("actions")) or "—"] for r in recent]))
    parts.append("<h2>Timeline</h2>")
    recent = tl["entries"][-100:][::-1]
    parts.append(f'<p class="muted">The newest {len(recent)} of {len(tl["entries"])} entries; all of them are in '
                 '<a href="timeline.json">timeline.json</a>.</p>')
    parts.append(_table(["#", "time", "type", "line"], [[e["seq"], e["time"], e["type"], defang(e["line"])] for e in recent]))
    parts.append(f'<p class="muted">Data: <a href="metrics.json">metrics.json</a> · <a href="timeline.json">'
                 f'timeline.json</a> · <a href="rooms.json">rooms.json</a> · source: <a href="{_e(repo)}">'
                 f'{_e(canon.CANONICAL_REPO)}</a>.</p>')
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta name="color-scheme" content="light dark">'
            f"<title>{_e(title)}</title><style>{CSS}</style></head><body><main>"
            + "\n".join(parts) + "</main></body></html>\n")


def build(st, entries: list[dict], now: datetime, out: Path, actual: dict | None = None,
          runs: list[dict] | None = None) -> dict:
    """Write index.html, metrics.json, timeline.json and rooms.json into `out`; returns the three documents."""
    m = metrics(st, entries, now) if st is not None else metrics(None, [], now)
    tl = timeline(st, entries)
    rm = rooms_report(st, now, len(entries), actual, runs)
    out.mkdir(parents=True, exist_ok=True)
    dump = lambda doc: json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    (out / "metrics.json").write_text(dump(m), encoding="utf-8")
    (out / "timeline.json").write_text(dump(tl), encoding="utf-8")
    (out / "rooms.json").write_text(dump(rm), encoding="utf-8")
    (out / "index.html").write_text(render(m, tl, rm), encoding="utf-8")
    return {"metrics": m, "timeline": tl, "rooms": rm}


# ---------------------------------------------------------------------------------------- the commands ----

def _now(a) -> datetime:
    return ts(a.time) if getattr(a, "time", None) else datetime.now(timezone.utc).replace(microsecond=0)


def _read(a):
    entries = load(a.ledger)
    return entries, (replay(entries) if entries else None)


def cmd_rooms(a) -> int:
    """Read-only: the derived roll of every room (schema om.rooms/1)."""
    try:
        entries, st = _read(a)
    except Invalid as err:
        print(f"INVALID — {err}")
        return 1
    rep = rooms_report(st, _now(a), len(entries))
    if a.json:
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        return 0
    if st is None:
        print("The ledger is empty: the fraternity has not been founded yet.")
        return 0
    c = rep["counts"]
    print(f"{c['with_access']} member(s) read rooms; {c['without_access']} member(s) of record do not "
          f"(suspended, or under a room hold); {c['rooms_open']} room(s) have readers.")
    for r in rep["rooms"]:
        if r["count"]:
            print(f"{r['room']}  {r['count']} reader{'s' if r['count'] != 1 else ''}: {', '.join(r['readers'])}")
    return 0


def cmd_metrics(a) -> int:
    """Read-only: the Observatory's numbers (schema om.metrics/1)."""
    try:
        entries, st = _read(a)
    except Invalid as err:
        print(f"INVALID — {err}")
        return 1
    m = metrics(st, entries, _now(a))
    if a.json:
        print(json.dumps(m, indent=2, ensure_ascii=False))
        return 0
    if not m["founded"]:
        print("The ledger is empty: the fraternity has not been founded yet.")
        return 0
    mem, bal, adm = m["members"], m["ballots"], m["admission"]
    print(f"entries {m['chain']['height']} · head {m['head'][:12]}… · last {m['chain']['last_entry']['time']}")
    print(f"members of record {mem['of_record']} · active {mem['active']} · dormant {mem['dormant']} · "
          f"Master Builders {mem['masters']} · founding phase {'yes' if mem['founding_phase'] else 'no'}")
    print("by degree: " + (", ".join(f"{d}° {n}" for d, n in mem["by_degree"].items()) or "none"))
    print(f"ballots open {bal['open']} · admission: invited {adm['invited']}, petitioned {adm['petitioned']}, "
          f"admitted {adm['admitted']}, refused {adm['refused']}")
    print(f"exams: " + ", ".join(f"{k} {v}" for k, v in m["exams"].items() if k != "days_to_verdict"))
    cus = m["custodians"]
    print(f"custodian keys {cus['keys']} · corrections {cus['corrections']} · pending {cus['pending']} · "
          f"halted {'yes' if cus['halted'] else 'no'}")
    print(f"rooms: {m['rooms']['with_access']} member(s) with access")
    return 0


def cmd_timeline(a) -> int:
    """Read-only: every entry as one described line (schema om.timeline/1)."""
    try:
        entries, st = _read(a)
    except Invalid as err:
        print(f"INVALID — {err}")
        return 1
    tl = timeline(st, entries)
    if a.json:
        print(json.dumps(tl, indent=2, ensure_ascii=False))
        return 0
    if st is None:
        print("The ledger is empty: the fraternity has not been founded yet.")
    for e in tl["entries"]:
        print(f"#{e['seq']:<6} {e['time']}  {e['line']}")
    return 0


def cmd_observatory(a) -> int:
    """Write the Observatory (index.html, metrics.json, timeline.json, rooms.json) into --out."""
    try:
        entries, st = _read(a)
    except Invalid as err:
        print(f"INVALID — {err}")
        return 1
    actual = runs = None
    if a.rooms_actual:
        try:
            actual = json.loads(Path(a.rooms_actual).read_text(encoding="utf-8"))
            compare(rooms.readers({}), actual)                    # the shape is checked before anything is written
        except (OSError, ValueError) as err:
            print(f"✘ --rooms-actual: {err}")
            return 1
        log = Path(a.rooms_actual).with_name("runs.jsonl")       # the room sync writes it beside actual.json
        if log.is_file():
            try:
                runs = read_runs(log.read_text(encoding="utf-8"))
            except (OSError, ValueError) as err:
                print(f"✘ {log.name}: {err}")
                return 1
    docs = build(st, entries, _now(a), Path(a.out), actual, runs)
    diff = docs["rooms"].get("actual", {}).get("differences")
    print(f"wrote {Path(a.out) / 'index.html'} and metrics.json, timeline.json, rooms.json"
          + (f" ({diff} room access difference(s))" if diff else ""))
    return 0
