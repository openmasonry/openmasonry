"""Coats of arms, generated: never drawn by hand, never sold.

* Degree arms come from the blazon fields of canon/degrees.toml.
* Personal arms are derived deterministically from the member's public key,
  so a member's shield is as unforgeable as the key itself and two members can
  never share one (up to SHA-256 collisions).
"""
from __future__ import annotations

import hashlib
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


def _charge(n_or_label: str, ink: str) -> str:
    return (f'<circle cx="100" cy="110" r="34" fill="{ink}" stroke="#00000040" stroke-width="2"/>'
            f'<text x="100" y="122" font-family="Georgia,serif" font-size="32" text-anchor="middle" '
            f'fill="{"#1C1B1F" if ink in (TINCTURES["or"], TINCTURES["argent"]) else "#FFFFFF"}">'
            f'{escape(n_or_label)}</text>')


def shield(field: str, ordinary: str, ordinary_ink: str, charge_label: str, charge_ink: str, title: str) -> str:
    """Rule of tincture: a color is always laid on a metal and vice versa."""
    f, o, c = TINCTURES[field], TINCTURES[ordinary_ink], TINCTURES[charge_ink]
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 222" role="img" aria-label="{escape(title)}">'
        f'<title>{escape(title)}</title><defs><clipPath id="s"><path d="{SHIELD}"/></clipPath></defs>'
        f'<g clip-path="url(#s)"><rect width="200" height="222" fill="{f}"/>{_ordinary(ordinary, o)}</g>'
        f'{_charge(charge_label, c)}'
        f'<path d="{SHIELD}" fill="none" stroke="#1C1B1F" stroke-width="4"/></svg>'
    )


def _contrast(t: str) -> str:
    return "sable" if t in METALS else "or"


def degree_arms(d) -> str:
    ink = _contrast(d.tincture)
    return shield(d.tincture, d.ordinary, ink, str(d.n), ink, f"Arms of the {d.n}°: {d.title}")


def personal_arms(login: str, public_key: str, degree: int) -> str:
    h = hashlib.sha256(public_key.strip().encode()).digest()
    metal_field = h[0] % 2 == 0
    field = METALS[h[1] % 2] if metal_field else COLORS[h[1] % len(COLORS)]
    ink = COLORS[h[2] % len(COLORS)] if metal_field else METALS[h[2] % 2]
    ordinary = ORDINARIES[1 + h[3] % (len(ORDINARIES) - 1)]
    label = f"{degree}"
    return shield(field, ordinary, ink, label, ink, f"Arms of {login}, {degree}°")
