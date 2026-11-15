"""Coats of arms, generated: never drawn by hand, never sold.

* Degree arms come from the blazon fields of canon/degrees.toml: the field, the
  ordinary and the charge. Every degree has its own charge, so no two degrees
  share a shield even where they share a field and an ordinary.
* Personal arms are derived deterministically from the member's public key,
  so a member's shield is as unforgeable as the key itself and two members can
  never share one (up to SHA-256 collisions).
"""
from __future__ import annotations

import hashlib
import math
from html import escape

TINCTURES = {  # heraldic tinctures -> hex
    "or": "#D4A93A", "argent": "#ECEFF1", "gules": "#B3261E", "azure": "#1E4E9C",
    "vert": "#2E7D32", "purpure": "#6A1B9A", "sable": "#1C1B1F",
}
METALS = ("or", "argent")
COLORS = ("gules", "azure", "vert", "purpure", "sable")
ORDINARIES = ("plain", "chevron", "pale", "fess", "bend", "saltire", "cross", "chief", "per-pale", "per-saltire")
SHIELD = "M10 8 H190 V110 C190 170 140 200 100 214 C60 200 10 170 10 110 Z"


def _ordinary(kind: str, ink: str) -> str:
    s = f'fill="{ink}"'
    return {
        "plain": "",
        "chevron": f'<path {s} d="M10 150 L100 70 L190 150 L190 120 L100 40 L10 120 Z"/>',
        "pale": f'<rect {s} x="75" y="8" width="50" height="210"/>',
        "fess": f'<rect {s} x="10" y="85" width="180" height="45"/>',
        "bend": f'<path {s} d="M10 8 L50 8 L190 170 L190 214 L170 214 L10 48 Z"/>',
        "saltire": f'<path {s} d="M10 8 L40 8 L100 80 L160 8 L190 8 L190 30 L120 110 L190 190 L170 214 L100 135 L30 214 L10 190 L80 110 L10 30 Z"/>',
        "cross": f'<path {s} d="M80 8 H120 V90 H190 V130 H120 V214 H80 V130 H10 V90 H80 Z"/>',
        "chief": f'<rect {s} x="10" y="8" width="180" height="55"/>',
        "per-pale": f'<rect {s} x="100" y="8" width="90" height="210"/>',
        "per-saltire": f'<path {s} d="M10 8 L100 110 L10 214 Z M190 8 L100 110 L190 214 Z"/>',
    }[kind]


def _star(cx: float, cy: float, outer: float, inner: float, points: int = 5) -> str:
    pts = []
    for i in range(2 * points):
        a = -math.pi / 2 + i * math.pi / points
        r = outer if i % 2 == 0 else inner
        pts.append(f"{cx + r * math.cos(a):.1f} {cy + r * math.sin(a):.1f}")
    return "M" + " L".join(pts) + " Z"


def _rays(cx: float, cy: float, r1: float, r2: float, count: int) -> str:
    out = []
    for i in range(count):
        a = i * 2 * math.pi / count
        out.append(f"M{cx + r1 * math.cos(a):.1f} {cy + r1 * math.sin(a):.1f} "
                   f"L{cx + r2 * math.cos(a):.1f} {cy + r2 * math.sin(a):.1f}")
    return " ".join(out)


def _rose() -> str:
    petals = "".join(
        f'<circle cx="{24 + 9 * math.cos(-math.pi / 2 + i * 2 * math.pi / 5):.1f}" '
        f'cy="{24 + 9 * math.sin(-math.pi / 2 + i * 2 * math.pi / 5):.1f}" r="7"/>' for i in range(5))
    return petals + '<circle cx="24" cy="24" r="4" class="f"/>'


# The charges of canon/degrees.toml, drawn as strokes in a 48 x 48 box; class "f" marks a filled shape.
CHARGES = {
    "rough-ashlar": '<path d="M8 16 L21 8 L37 11 L42 27 L33 40 L13 39 L6 27 Z M21 8 L24 22 L42 27 M24 22 L13 39"/>',
    "level": '<path d="M7 40 L24 9 L41 40 Z M14 28 H34 M24 9 V32"/><circle cx="24" cy="34" r="2.5" class="f"/>',
    "compass": '<path d="M24 10 L11 42 M24 10 L37 42 M15 32 Q24 37 33 32"/><circle cx="24" cy="8" r="3.5"/>',
    "key": '<circle cx="13" cy="24" r="7"/><path d="M20 24 H43 M37 24 V32 M43 24 V32"/>',
    "column": '<path d="M12 9 H36 M15 14 H33 M18 14 V37 M24 14 V37 M30 14 V37 M15 37 H33 M12 42 H36"/>',
    "quill": '<path d="M39 7 C24 10 15 24 12 40 M39 7 C36 21 27 30 15 33 M12 40 L8 45 M30 15 L20 27"/>',
    "balance": '<path d="M24 7 V40 M15 40 H33 M9 14 H39 M9 14 L4 27 H14 Z M39 14 L34 27 H44 Z"/>',
    "plumb": '<path d="M13 6 H35 M24 6 V29 M24 29 L30 37 L24 45 L18 37 Z"/>',
    "lamp": '<path d="M6 30 H38 C37 38 9 38 6 30 Z M38 30 L44 25 M18 39 V43 H30 V39 M12 25 C9 19 14 15 13 10 C19 16 19 21 16 25"/>',
    "star": f'<path d="{_star(24, 26, 19, 7.5)}"/>',
    "sheaf": '<path d="M24 44 V13 M24 31 L13 12 M24 31 L35 12 M17 32 H31"/><ellipse cx="24" cy="9" rx="3" ry="5"/>'
             '<ellipse cx="12" cy="9" rx="3" ry="5" transform="rotate(-30 12 9)"/>'
             '<ellipse cx="36" cy="9" rx="3" ry="5" transform="rotate(30 36 9)"/>',
    "square": '<path d="M9 7 V41 H41 V34 H16 V7 Z"/>',
    "arch": '<path d="M7 42 V24 A17 17 0 0 1 41 24 V42 M15 42 V25 A9 9 0 0 1 33 25 V42 M21 7 L22 16 H26 L27 7"/>',
    "ring": '<circle cx="24" cy="29" r="13"/><path d="M19 15 L24 7 L29 15 Z"/>',
    "sword": '<path d="M21 31 V8 L24 3 L27 8 V31 Z M14 31 H34 M24 31 V41"/><circle cx="24" cy="44" r="2.5" class="f"/>',
    "tower": '<path d="M12 42 V14 H17 V9 H21 V14 H27 V9 H31 V14 H36 V42 Z M20 42 V34 A4 4 0 0 1 28 34 V42 M22 22 H26"/>',
    "sun-moon": f'<circle cx="15" cy="24" r="7"/><path d="{_rays(15, 24, 10, 13, 8)}"/>'
                '<path d="M36 12 A12 12 0 1 0 36 36 A9.5 9.5 0 1 1 36 12 Z"/>',
    "rose": _rose(),
    "bridge": '<path d="M3 21 H45 M7 21 V41 M41 21 V41 M7 41 Q24 23 41 41 M16 21 V31 M24 21 V28 M32 21 V31"/>',
    "book": '<path d="M24 13 C18 9 10 9 5 11 V38 C10 36 18 36 24 40 C30 36 38 36 43 38 V11 C38 9 30 9 24 13 Z M24 13 V40"/>',
    "ark": '<path d="M3 30 H45 L38 41 H10 Z M13 30 V20 H35 V30 M20 20 L24 13 L28 20"/>',
    "axe": '<path d="M13 44 L33 11 M27 12 L33 5 C41 9 44 17 42 24 L33 19 Z"/>',
    "flame": '<path d="M24 43 C13 43 9 34 14 25 C16 30 18 30 20 28 C18 19 22 12 29 5 C28 16 39 20 37 32 C36 39 31 43 24 43 Z"/>',
    "triangle": '<path d="M24 7 L43 40 H5 Z"/>',
    "serpent": '<path d="M33 9 C19 6 13 17 22 23 C31 29 31 39 13 41 M13 41 L9 38"/><circle cx="36" cy="9" r="3" class="f"/>',
    "heart": '<path d="M24 41 C10 31 5 23 9 15 C13 9 21 10 24 17 C27 10 35 9 39 15 C43 23 38 31 24 41 Z"/>',
    "cross-potent": '<path d="M24 7 V41 M7 24 H41 M17 7 H31 M17 41 H31 M7 17 V31 M41 17 V31"/>',
    "sun": f'<circle cx="24" cy="24" r="9"/><path d="{_rays(24, 24, 13, 20, 12)}"/>',
    "saltire-cross": '<path d="M11 11 L37 37 M37 11 L11 37 M6 15 L15 6 M33 6 L42 15 M42 33 L33 42 M15 42 L6 33"/>',
    "eagle": '<path d="M24 19 C16 10 8 11 3 15 C9 17 13 22 15 29 L24 27 L33 29 C35 22 39 17 45 15 C40 11 32 10 24 19 Z '
             'M24 27 V37 M19 42 L24 36 L29 42"/><circle cx="24" cy="12" r="3.5"/>',
    "eye": '<path d="M3 24 C12 12 36 12 45 24 C36 36 12 36 3 24 Z"/><circle cx="24" cy="24" r="7"/>'
           '<circle cx="24" cy="24" r="2.5" class="f"/>',
    "double-eagle": '<path d="M24 21 C16 12 8 13 3 17 C9 19 13 24 15 31 L24 29 L33 31 C35 24 39 19 45 17 C40 13 32 12 24 21 Z '
                    'M24 29 V38 M19 43 L24 37 L29 43 M24 21 L18 12 M24 21 L30 12"/>'
                    '<circle cx="17" cy="9" r="3"/><circle cx="31" cy="9" r="3"/>',
    "delta": '<path d="M24 5 L44 40 H4 Z M15 30 C20 23 28 23 33 30 C28 36 20 36 15 30 Z"/>'
             '<circle cx="24" cy="30" r="2.5" class="f"/>',
}


def _on(ink: str) -> str:
    """What reads on a roundel of `ink`: sable on a metal, white on a color."""
    return "#1C1B1F" if ink in (TINCTURES["or"], TINCTURES["argent"]) else "#FFFFFF"


def _numeral(label: str, ink: str) -> str:
    return (f'<circle cx="100" cy="110" r="34" fill="{ink}" stroke="#00000040" stroke-width="2"/>'
            f'<text x="100" y="122" font-family="Georgia,serif" font-size="32" text-anchor="middle" '
            f'fill="{_on(ink)}">{escape(label)}</text>')


def _emblem(charge: str, ink: str) -> str:
    fg = _on(ink)
    return (f'<circle cx="100" cy="110" r="45" fill="{ink}" stroke="#00000055" stroke-width="2.5"/>'
            f'<g transform="translate(68.8 78.8) scale(1.3)" fill="none" stroke="{fg}" stroke-width="2.7" '
            f'stroke-linecap="round" stroke-linejoin="round"><style>.f{{fill:{fg};stroke:none}}</style>'
            f'{CHARGES[charge]}</g>')


def shield(field: str, ordinary: str, ordinary_ink: str, charge_svg: str, title: str) -> str:
    """Rule of tincture: a color is always laid on a metal and vice versa. A light rim keeps a dark shield
    visible on a dark page."""
    f, o = TINCTURES[field], TINCTURES[ordinary_ink]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 222" role="img" aria-label="{escape(title)}">'
        f'<title>{escape(title)}</title><defs><clipPath id="s"><path d="{SHIELD}"/></clipPath></defs>'
        f'<path d="{SHIELD}" fill="none" stroke="#E6EDF3" stroke-width="10" stroke-opacity=".9"/>'
        f'<g clip-path="url(#s)"><rect width="200" height="222" fill="{f}"/>{_ordinary(ordinary, o)}</g>'
        f'{charge_svg}'
        f'<path d="{SHIELD}" fill="none" stroke="#1C1B1F" stroke-width="4"/></svg>'
    )


def _contrast(t: str) -> str:
    return "sable" if t in METALS else "or"


def degree_arms(d) -> str:
    ink = _contrast(d.tincture)
    return shield(d.tincture, d.ordinary, ink, _emblem(d.charge, TINCTURES[ink]), f"Arms of the {d.n}°: {d.title}")


def personal_arms(login: str, public_key: str, degree: int) -> str:
    h = hashlib.sha256(public_key.strip().encode()).digest()
    metal_field = h[0] % 2 == 0
    field = METALS[h[1] % 2] if metal_field else COLORS[h[1] % len(COLORS)]
    ink = COLORS[h[2] % len(COLORS)] if metal_field else METALS[h[2] % 2]
    ordinary = ORDINARIES[1 + h[3] % (len(ORDINARIES) - 1)]
    return shield(field, ordinary, ink, _numeral(f"{degree}", TINCTURES[ink]), f"Arms of {login}, {degree}°")
