"""Project an LCMA annotation (a JSON-LD string) into the visual channels a timeline span
can carry, plus a level-of-detail (LOD) ladder keyed to the span's pixel width.

Python port of the web reference spec ``annotation-ui/src/model/spanView.ts``. Kept Qt-free
and dependency-free so it is unit testable on its own and the element code stays thin.
Headline abbreviations come from the ontology vocab (``FUNCTION_ABBR`` / ``MAIN_TYPE_ABBR``,
generated from ``ontology/lcma.ttl``); we vendor ``vocab.json`` next to this module so the
timeline shows exactly what the reference editor does — see ``_load_abbr``. The painted fill
matches the editor's rendered ``.span-fill`` (family hue composited over the white track) —
see ``span_fill_hex``. One known gap: fusion / function-operator overlays are not yet
serialised into JSON-LD, so only the cases that reach the wire are read (transformation via
``lcma:FunctionTransformation``).

Reads the compact JSON-LD the builder emits via ``toJsonLd``: the top-level ``name`` /
``forms`` / ``hasAttribute`` keys. The ``@context`` wrapper is present but ignored — the
document is already in compact form, so the keys we read are stable.
"""

from __future__ import annotations

import colorsys
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

# --- colour by function family -------------------------------------------------
# A deliberately low-information channel: a stable hue per function family that survives to
# the narrowest zoom. Matched on the un-abbreviated headline so word stems group
# ("theme"/"verse"/"main"). Mirrors spanColor() in spanView.ts.

_GREY_HSL = (225, 9, 58)

_FAMILY_HUES: list[tuple[re.Pattern, int]] = [
    (re.compile(r"theme|verse|main|primary|basic"), 145),  # green — thematic
    (re.compile(r"chorus|subordinate|secondary"), 212),  # blue — subordinate
    (re.compile(r"transition|trnst|bridge|link"), 33),  # amber — connective
    (re.compile(r"caden|closing|outro|coda"), 2),  # red — closing
    (re.compile(r"intro|introduction|antecedent|presentation"), 178),  # teal — opening
    (
        re.compile(r"develop|core|solo|interlude|continuation"),
        276,
    ),  # purple — developmental
]


def family_hue(headline_full: str) -> int | None:
    """The family hue (degrees) for a headline, or None for the grey fallback."""
    n = headline_full.lower()
    for pattern, hue in _FAMILY_HUES:
        if pattern.search(n):
            return hue
    return None


def _hsl_rgb(h: int, s: int, lightness: int) -> tuple[int, int, int]:
    r, g, b = colorsys.hls_to_rgb(h / 360, lightness / 100, s / 100)
    return round(r * 255), round(g * 255), round(b * 255)


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


# The reference editor never paints the raw family hue: its ``.span-fill`` lays the hue over the
# white track at a low opacity (styles.css), so what the analyst actually SEES is a pale tint.
# We composite the same blend here and paint it opaquely, so the timeline rectangle matches the
# web exactly instead of showing a far more saturated block.
_TRACK_BG = (255, 255, 255)  # web --panel
_FILL_ALPHA = 0.22  # .span-fill opacity
_STANDALONE_ALPHA = 0.16  # .span.is-standalone .span-fill opacity


def _blend_over_track(rgb: tuple[int, int, int], alpha: float) -> str:
    return _hex(
        tuple(
            round(alpha * c + (1 - alpha) * bg)
            for c, bg in zip(rgb, _TRACK_BG, strict=True)
        )
    )


def span_color_hex(headline_full: str) -> str:
    """The raw family hue as ``#rrggbb`` (``hsl(hue 52% 52%)`` or grey) — the colour IDENTITY,
    before the track composite. Kept for reference/legends, not the painted fill."""
    hue = family_hue(headline_full)
    return _hex(_hsl_rgb(*_GREY_HSL) if hue is None else _hsl_rgb(hue, 52, 52))


def span_fill_hex(headline_full: str, standalone: bool = False) -> str:
    """The opaque fill the timeline paints. Matches the web's rendered ``.span-fill`` (the
    family/grey hue composited over the white track at the CSS opacity), so the rectangle and
    the reference editor agree. QColor parses the ``#rrggbb`` result; it does NOT parse ``hsl()``.
    """
    hue = None if standalone else family_hue(headline_full)
    rgb = _hsl_rgb(*_GREY_HSL) if hue is None else _hsl_rgb(hue, 52, 52)
    return _blend_over_track(rgb, _STANDALONE_ALPHA if standalone else _FILL_ALPHA)


# --- display formatting (port of format.ts prettify) ---------------------------


def prettify(name: str) -> str:
    """``basic_idea`` -> ``Basic idea``; ``hybrid1`` -> ``Hybrid 1``. Display only."""
    spaced = re.sub(r"([A-Za-z])(\d)", r"\1 \2", name.replace("_", " "))
    return spaced[:1].upper() + spaced[1:] if spaced else spaced


# --- abbreviations (from the vendored ontology vocab) --------------------------
# The reference editor abbreviates headlines with maps generated from ontology/lcma.ttl
# (annotation-ui src/generated/vocab.json). We vendor that same file next to this module so the
# timeline shows the SAME abbreviations the web does — sourced from the ontology, not guessed.
# It is a build artifact, kept in sync alongside the vendored embed.html; if it is ever missing
# or malformed we degrade gracefully to the prettified full term.

_VOCAB_PATH = Path(__file__).parent / "vocab.json"


def _load_abbr() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Build {name: abbr} maps for functions, main types and placeholders. Returns empty maps on
    any failure (missing / malformed file), so abbreviation falls back to the prettified term.
    """
    try:
        vocab = json.loads(_VOCAB_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}, {}

    def amap(entries) -> dict[str, str]:
        return {e["name"]: e["abbr"] for e in entries if "name" in e and "abbr" in e}

    fns = vocab.get("functions", {})
    # specific first, then generic_units — generic wins on the lone name collision, matching the
    # web's FUNCTION_ABBR construction order.
    function_abbr = {
        **amap(fns.get("specific", [])),
        **amap(fns.get("generic_units", [])),
    }
    type_abbr = amap(vocab.get("types", {}).get("main", []))
    placeholder_abbr = amap(vocab.get("placeholders", []))
    return function_abbr, type_abbr, placeholder_abbr


FUNCTION_ABBR, MAIN_TYPE_ABBR, PLACEHOLDER_ABBR = _load_abbr()


def _abbr(mapping: dict[str, str], name: str) -> str:
    """The vocab abbreviation for a controlled name, or its prettified full form as a fallback."""
    return mapping.get(name) or prettify(name)


# --- model ---------------------------------------------------------------------


@dataclass
class SpanFlags:
    operator: str | None = None  # "transformation" | "fusion" | None
    notional: bool = False
    material: bool = False
    attributes: int = 0  # count of literal descriptive keys
    references: int = 0  # count of unit-reference targets
    uncertain: bool = False
    standalone: bool = False  # attribute-only label (no forms)


@dataclass
class SpanRef:
    dimension: str  # the attribute key naming the relationship
    target: str  # referenced unit name
    qualifier: str | None = None


@dataclass
class SpanModel:
    name: str = ""
    primary: str = "—"  # headline: vocab abbreviation (function / placeholder)
    primary_full: str = "—"  # un-abbreviated, for tooltip / detail
    secondary: str = ""  # formal type: vocab abbreviation
    secondary_full: str = ""
    color: str = (
        ""  # #rrggbb opaque fill (family hue composited over the track, matches web)
    )
    flags: SpanFlags = field(default_factory=SpanFlags)
    refs: list[SpanRef] = field(default_factory=list)
    attrs: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Badge:
    glyph: str
    title: str
    kind: str  # "op" | "mat" | "attr" | "ref" | "unc"


# --- JSON-LD reading (mirrors the reverse helpers in jsonld.ts) ----------------


def _local(curie: str) -> str:
    """Strip a CURIE prefix: ``fn:basic_idea`` -> ``basic_idea``."""
    return curie[curie.find(":") + 1 :] if isinstance(curie, str) else ""


def _key_term(k) -> str:
    return _local(k.get("@id", "")) if isinstance(k, dict) else (k or "")


def _qualifier_term(q):
    return _local(q.get("@id", "")) if isinstance(q, dict) else q


def _value_term(v) -> str:
    # A controlled value is an {@id} node ref; MVP shows its local name (the web maps the
    # CURIE to a vocab label). A soft/free value is a plain literal.
    if isinstance(v, dict):
        return _local(v.get("@id", ""))
    return v if v is not None else ""


def _unit_name(iri: str) -> str:
    return unquote(_local(iri))  # inverse of unitIri (encodeURIComponent)


def _fn_headline(fn: dict, abbreviate: bool) -> str:
    """A function node rendered to one line: a transformation as ``a→b``, else the function
    category (abbreviated via the vocab, or prettified in full), quoted when notional.
    """
    if fn.get("@type") == "lcma:FunctionTransformation":
        return (
            f"{_fn_headline(fn.get('source') or {}, abbreviate)}→"
            f"{_fn_headline(fn.get('target') or {}, abbreviate)}"
        )
    name = _local(fn.get("hasCategory", ""))
    base = (_abbr(FUNCTION_ABBR, name) if abbreviate else prettify(name)) or "—"
    return f"“{base}”" if fn.get("notional") else base


def _fn_operator(fn: dict) -> str | None:
    if fn.get("@type") == "lcma:FunctionTransformation" or "source" in fn:
        return "transformation"
    return None  # fusion is not yet serialised into JSON-LD


def parse_span_model(jsonld: str) -> SpanModel | None:
    """Project the builder's JSON-LD into a SpanModel. Returns None for empty / unparseable
    input, so the caller can fall back to a plain hierarchy render (unannotated unit).
    """
    if not jsonld or not jsonld.strip():
        return None
    try:
        node = json.loads(jsonld)
    except (ValueError, TypeError):
        return None
    if not isinstance(node, dict):
        return None

    refs: list[SpanRef] = []
    attrs: list[tuple[str, str]] = []
    for a in node.get("hasAttribute") or []:
        if not isinstance(a, dict):
            continue
        key = _key_term(a.get("key"))
        if "valueRef" in a:
            for r in a.get("valueRef") or []:
                q = r.get("qualifier")
                refs.append(
                    SpanRef(
                        key,
                        _unit_name(r.get("refTarget", "")),
                        _qualifier_term(q) if q is not None else None,
                    )
                )
        else:
            attrs.append((key, _value_term(a.get("value"))))

    forms = node.get("forms") or []
    standalone = len(forms) == 0
    form = forms[0] if forms else None
    name = node.get("name") or ""

    primary = primary_full = "—"  # em dash
    secondary = secondary_full = ""
    operator = None
    notional = material = uncertain = False

    if isinstance(form, dict):
        if form.get("@type") == "lcma:Placeholder":
            ph_name = _local(form.get("hasCategory", ""))
            primary = _abbr(PLACEHOLDER_ABBR, ph_name) or "—"
            primary_full = prettify(ph_name) or "—"
            material = "material" in form
        else:
            fn = form.get("function") or {}
            primary = _fn_headline(fn, True)
            primary_full = _fn_headline(fn, False)
            operator = _fn_operator(fn)
            notional = bool(fn.get("notional"))
            material = "material" in form
            uncertain = form.get("certainty") == "uncertain"
            ftype = form.get("formalType")
            if isinstance(ftype, dict):
                main = _local(ftype.get("hasCategory", ""))
                secondary = _abbr(MAIN_TYPE_ABBR, main)
                secondary_full = prettify(main)
    elif standalone and name:
        primary = primary_full = prettify(name)
    elif standalone:
        primary = primary_full = "Description"

    flags = SpanFlags(
        operator=operator,
        notional=notional,
        material=material,
        attributes=len(attrs),
        references=len(refs),
        uncertain=uncertain,
        standalone=standalone,
    )
    color = span_fill_hex(primary_full, standalone)
    return SpanModel(
        name=name,
        primary=primary,
        primary_full=primary_full,
        secondary=secondary,
        secondary_full=secondary_full,
        color=color,
        flags=flags,
        refs=refs,
        attrs=attrs,
    )


# --- level of detail -----------------------------------------------------------

Lod = str  # "full" | "med" | "short" | "min"


def lod_for(px_width: float) -> Lod:
    """The detail tier a span at this pixel width can legibly show. As a span narrows,
    channels are shed in priority order rather than crammed and clipped."""
    if px_width >= 200:
        return "full"
    if px_width >= 104:
        return "med"
    if px_width >= 48:
        return "short"
    return "min"


def badges_for(m: SpanModel) -> list[Badge]:
    """The single-glyph badges a span carries when inline text has no room. Notional (a
    border style) and fusion (read from inline ``/``) are intentionally absent."""
    b: list[Badge] = []
    if m.flags.operator == "transformation":
        b.append(Badge("→", "transformation", "op"))  # →
    if m.flags.material:
        b.append(Badge("▦", "material reference", "mat"))  # ▦
    if m.flags.attributes:
        plural = "s" if m.flags.attributes > 1 else ""
        b.append(Badge("✱", f"{m.flags.attributes} attribute{plural}", "attr"))  # ✱
    if m.flags.references:
        targets = ", ".join(
            (
                f"{r.dimension}: {r.target} ({prettify(r.qualifier)})"
                if r.qualifier
                else f"{r.dimension}: {r.target}"
            )
            for r in m.refs
        )
        b.append(Badge("↗", f"references {targets}", "ref"))  # ↗
    if m.flags.uncertain:
        b.append(Badge("?", "uncertain", "unc"))
    return b


def display_label(m: SpanModel, lod: Lod) -> str:
    """The inline text a span shows at a given LOD tier. Badge glyphs are appended on one
    line (the timeline label is a single text item in this MVP); ``min`` shows nothing — the
    colour fill carries the family."""
    if lod == "min":
        return ""
    badges = badges_for(m)
    if lod == "short":
        return m.primary + (" •" if badges else "")  # • dot signals "more here"
    # full / med
    head = m.primary + (f" | {m.secondary}" if m.secondary else "")
    text = f"{m.name} · {head}" if m.name else head  # ·
    if badges:
        text += "  " + "".join(b.glyph for b in badges)
    return text


def span_tooltip(m: SpanModel) -> str:
    """A full plain-text breakdown of every channel, one per line, for the span's hover
    tooltip — so what the badges only hint at stays legible at any zoom."""
    head = f"{m.name} — {m.primary_full}" if m.name else m.primary_full
    lines = [f"{head}  |  {m.secondary_full}" if m.secondary_full else head]
    if m.flags.operator:
        lines.append(f"• {m.flags.operator}")
    if m.flags.notional:
        lines.append("• notional (“…”)")
    if m.flags.material:
        lines.append("• material reference")
    for key, value in m.attrs:
        lines.append(f"• {key}: {value}")
    for r in m.refs:
        tail = f" ({prettify(r.qualifier)})" if r.qualifier else ""
        lines.append(f"• {r.dimension} → {r.target}{tail}")
    if m.flags.uncertain:
        lines.append("• uncertain")
    if m.flags.standalone:
        lines.append("• standalone description")
    return "\n".join(lines)
