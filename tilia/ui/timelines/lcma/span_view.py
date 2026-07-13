"""Project an LCMA annotation (a JSON-LD string) into the visual channels a timeline span
can carry, plus a level-of-detail (LOD) ladder keyed to the span's pixel width.

Python port of the web reference spec ``annotation-ui/src/model/spanView.ts``. Kept Qt-free
and dependency-free so it is unit testable on its own and the element code stays thin.
Headline abbreviations come from the ontology vocab (``FUNCTION_ABBR`` / ``MAIN_TYPE_ABBR``,
generated from ``ontology/lcma.ttl``); we vendor ``vocab.json`` next to this module so the
timeline shows exactly what the reference editor does — see ``_load_abbr``. The painted fill
matches the editor's rendered ``.span-fill`` (family hue composited over the white track) —
see ``span_fill_hex``. Function operators reach the wire as a ``lcma:FunctionOperation`` tree —
fusion (``/``) and transformation (``→``), both n-ary — with a ``lcma:FunctionModifier`` for a
notional wrapper; these are read alongside the legacy ``lcma:FunctionTransformation``, so both
fusions and transformations show on the span. See ``_fn_headline`` / ``_fn_operator``.

Reads the compact JSON-LD the builder emits via ``toJsonLd``: the top-level ``name`` /
``forms`` / ``hasAttribute`` keys. The ``@context`` wrapper is present but ignored — the
document is already in compact form, so the keys we read are stable.
"""

from __future__ import annotations

import colorsys
import html
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


def _read_vocab() -> dict:
    """The vendored ontology vocab as a dict, or ``{}`` on any failure (missing / malformed
    file), so every derived map degrades gracefully to its empty form."""
    try:
        return json.loads(_VOCAB_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _load_abbr(vocab: dict) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Build {name: abbr} maps for functions, main types and placeholders. Empty maps when the
    vocab is missing, so abbreviation falls back to the prettified term."""

    def amap(entries) -> dict[str, str]:
        return {e["name"]: e["abbr"] for e in entries if "name" in e and "abbr" in e}

    fns = vocab.get("functions", {})
    # specific, then generic_units, then cadences — last wins on a name collision, matching the
    # web's FUNCTION_ABBR construction order (vocab.ts). Cadences are a first-class function group
    # now (vocab.json functions.cadences); include them so a cadence headline still abbreviates.
    function_abbr = {
        **amap(fns.get("specific", [])),
        **amap(fns.get("generic_units", [])),
        **amap(fns.get("cadences", [])),
    }
    type_abbr = amap(vocab.get("types", {}).get("main", []))
    placeholder_abbr = amap(vocab.get("placeholders", []))
    return function_abbr, type_abbr, placeholder_abbr


def _load_operators(vocab: dict) -> tuple[dict[str, str], dict[str, bool]]:
    """{name: symbol} and {name: string_writable} for material operators, mirroring
    OPERATOR_SYMBOL / OPERATOR_WRITABLE in vocab.ts. A writable operator renders as its symbol
    (e.g. ``°``); the rest render as their prettified word. Empty when the vocab is missing."""
    ops = vocab.get("operators", []) or []
    symbol = {o["name"]: o["symbol"] for o in ops if "name" in o and "symbol" in o}
    writable = {o["name"]: bool(o.get("string_writable")) for o in ops if "name" in o}
    return symbol, writable


_VOCAB = _read_vocab()
FUNCTION_ABBR, MAIN_TYPE_ABBR, PLACEHOLDER_ABBR = _load_abbr(_VOCAB)
OPERATOR_SYMBOL, OPERATOR_WRITABLE = _load_operators(_VOCAB)
# The unit-reference sentinel ("previous") — rendered as "prev" in a material reference list,
# matching the web's Refs component. Falls back to the web's literal default.
SENTINEL = _VOCAB.get("reference_sentinel", "previous")


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
    provisional: bool = (
        False  # a PROPOSED term (commit-as-is), not in the controlled vocabulary
    )
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
    secondary_sub: str = ""  # formal SUBtype, prettified ("" when none)
    material_text: str = (
        ""  # material references on one line (refs + operators), "" when none
    )
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
    kind: str  # "op" | "mat" | "attr" | "ref" | "unc" | "prov"


# --- JSON-LD reading (mirrors the reverse helpers in jsonld.ts) ----------------


def _local(curie: str) -> str:
    """Strip a CURIE prefix: ``fn:basic_idea`` -> ``basic_idea``."""
    return curie[curie.find(":") + 1 :] if isinstance(curie, str) else ""


def _key_term(k) -> str:
    return _local(k.get("@id", "")) if isinstance(k, dict) else (k or "")


def _qualifier_term(q):
    return _local(q.get("@id", "")) if isinstance(q, dict) else q


def _value_term(v) -> str:
    # A controlled value is an {@id} node ref (shown as its local name; the web maps the CURIE to a
    # vocab label). A PROPOSED value is a flagged literal carrying its verbatim term. A soft/free
    # value is a plain literal. A DELTA element (a deltaValued key like instrumentation +guitar) is an
    # lcma:ValueChange node wrapping one of those — unwrap it and re-emit the +/− sign, mirroring the
    # web's LabelChips add/remove marker (without which the value would render empty).
    if isinstance(v, dict):
        if v.get("@type") == "lcma:ValueChange":
            sign = "+" if _local(v.get("change", "")) == "added" else "−"
            return sign + _value_term(v.get("value"))
        if v.get("provisional") is True:
            return v.get("provisionalTerm", "")
        return _local(v.get("@id", ""))
    return v if v is not None else ""


def _unit_name(iri: str) -> str:
    return unquote(_local(iri))  # inverse of unitIri (encodeURIComponent)


def _ordinal(n: int) -> str:
    """``1`` -> ``1st``, ``2`` -> ``2nd`` … ``4`` -> ``4th``. Mirrors ordinal() in
    annotation-ui format.ts — the cardinality (repeat-count) prefix on a function leaf."""
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n, "th")
    return f"{n}{suffix}"


# Function-operator glyphs, keyed on the operator's local name (the ``fnop:`` CURIE stripped) and
# mirroring OverlayExpr in the web's LabelChips: a transformation joins its operands with a directed
# arrow, a fusion with a slash. An unknown operator falls back to its bare name.
_FN_OP_GLYPH = {"transformation": "→", "fusion": "/"}


def _fn_headline(fn: dict, abbreviate: bool) -> str:
    """A function node rendered to one line, mirroring OverlayExpr / SingleFnText in LabelChips.

    The builder now authors a function-operator TREE: a ``lcma:FunctionOperation`` joins its
    operands with the operator glyph (transformation ``→``, fusion ``/``; a nested operation is
    parenthesised so the flat headline stays unambiguous), and a ``lcma:FunctionModifier`` wraps its
    operand in ``“…”`` (notional). The legacy ``lcma:FunctionTransformation`` (``source→target``,
    loaded from old data) and a bare leaf still render. On a leaf, its cardinality ordinal prefixes
    the name (``3rd intro``), ``notional`` quotes it, and ``crossing_rightward`` — the old
    under-specified fusion flag — appends a trailing ``/``. A PROVISIONAL (proposed) leaf carries
    its verbatim term under ``provisionalTerm``, not a CURIE.
    """
    if not isinstance(fn, dict):
        return "—"
    fn_type = fn.get("@type")
    if fn_type == "lcma:FunctionOperation":
        op = _local(fn.get("operator", ""))
        glyph = _FN_OP_GLYPH.get(op, op)
        return (
            glyph.join(_fn_operand(o, abbreviate) for o in (fn.get("operands") or []))
            or "—"
        )
    if fn_type == "lcma:FunctionModifier":
        return f"“{_fn_headline(fn.get('operand') or {}, abbreviate)}”"
    if fn_type == "lcma:FunctionTransformation":
        return (
            f"{_fn_headline(fn.get('source') or {}, abbreviate)}→"
            f"{_fn_headline(fn.get('target') or {}, abbreviate)}"
        )
    name = (
        fn.get("provisionalTerm", "")
        if fn.get("provisional") is True
        else _local(fn.get("hasCategory", ""))
    )
    base = (_abbr(FUNCTION_ABBR, name) if abbreviate else prettify(name)) or "—"
    # Cardinality (the repeat count) renders as an ordinal prefix, inside the notional quotes —
    # mirrors SingleFnText in LabelChips.tsx (`${card}${name}`).
    card = fn.get("cardinality")
    if card is not None:
        base = f"{_ordinal(card)} {base}"
    if fn.get("notional"):
        base = f"“{base}”"
    if fn.get("crossing_rightward"):
        base = f"{base}/"
    return base


def _fn_operand(fn: dict, abbreviate: bool) -> str:
    """An operand inside a ``lcma:FunctionOperation``: a nested operation is parenthesised so a flat
    headline stays unambiguous (mirrors OverlayOperand); anything else renders inline."""
    if isinstance(fn, dict) and fn.get("@type") == "lcma:FunctionOperation":
        return f"({_fn_headline(fn, abbreviate)})"
    return _fn_headline(fn, abbreviate)


def _fn_operator(fn: dict) -> str | None:
    """The span's structural operator for the badge channel — ``"transformation"`` or ``"fusion"``,
    the OUTERMOST operator of the function tree — or ``None`` for a plain leaf. Reads the
    ``lcma:FunctionOperation`` operator, unwraps a notional ``lcma:FunctionModifier`` to the
    operation it wraps, the legacy ``lcma:FunctionTransformation``, and a leaf's
    ``crossing_rightward`` (the old under-specified fusion)."""
    if not isinstance(fn, dict):
        return None
    fn_type = fn.get("@type")
    if fn_type == "lcma:FunctionOperation":
        op = _local(fn.get("operator", ""))
        return op if op in _FN_OP_GLYPH else None
    if fn_type == "lcma:FunctionModifier":
        return _fn_operator(fn.get("operand") or {})
    if fn_type == "lcma:FunctionTransformation" or "source" in fn:
        return "transformation"
    if fn.get("crossing_rightward"):
        return "fusion"
    return None


def _fn_provisional(fn) -> bool:
    """True when a PROVISIONAL (proposed, not-in-vocab) leaf sits anywhere in the function tree — a
    bare provisional leaf, or one inside a ``lcma:FunctionOperation``'s operands (fusion /
    transformation), a notional ``lcma:FunctionModifier``'s operand, or a legacy transformation's
    source/target. Mirrors fnProvisional in the web, extended to the operator tree the builder now
    serialises."""
    if not isinstance(fn, dict):
        return False
    if fn.get("provisional") is True:
        return True
    if fn.get("@type") == "lcma:FunctionOperation":
        return any(_fn_provisional(o) for o in (fn.get("operands") or []))
    if fn.get("@type") == "lcma:FunctionModifier":
        return _fn_provisional(fn.get("operand"))
    return _fn_provisional(fn.get("source")) or _fn_provisional(fn.get("target"))


def _type_provisional(t) -> bool:
    """True when a formal-type node carries the PROVISIONAL (proposed) flag."""
    return isinstance(t, dict) and t.get("provisional") is True


def _op_text(op_name: str) -> str:
    """A material operator as its writable symbol or prettified name — the op-pill in LabelChips
    Refs: writable operators show their symbol, the rest their prettified word."""
    if OPERATOR_WRITABLE.get(op_name):
        return OPERATOR_SYMBOL.get(op_name, op_name)
    return prettify(op_name)


def _refs_text(node: dict) -> str:
    """A ``lcma:MaterialReferences`` node as one line: each reference's name (the SENTINEL shown
    as ``prev``) followed by its operator symbols, references joined by ``, ``, wrapped in
    ``{…}`` when the set is unordered. Mirrors revRefs + the Refs component in the web."""
    parts = []
    for r in node.get("refs") or []:
        if not isinstance(r, dict):
            continue
        ref = r.get("ref", "")
        name = "prev" if ref == SENTINEL else ref
        ops = "".join(_op_text(_local(o)) for o in (r.get("operators") or []))
        parts.append(f"{name}{ops}")
    body = ", ".join(parts)
    return f"{{{body}}}" if node.get("unordered") else body


def _material_text(material) -> str:
    """A material node rendered to one line, or ``""`` when absent. References render as the ref
    list; a transformational material renders as ``source ▸ target`` (each side the ref list, or
    ``—`` when that side is empty). Mirrors revMaterial + MaterialChip in the web."""
    if not isinstance(material, dict):
        return ""
    if material.get("@type") == "lcma:TransformationalMaterial":
        src, tgt = material.get("source"), material.get("target")
        src_s = _refs_text(src) if isinstance(src, dict) else "—"
        tgt_s = _refs_text(tgt) if isinstance(tgt, dict) else "—"
        return f"{src_s} ▸ {tgt_s}"
    return _refs_text(material)


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
            value = a.get("value")
            if isinstance(value, list):
                # A multi-valued key (instrumentation) is a SET of values — join the per-element
                # terms, mirroring the web's value.values.join(", ").
                attrs.append((key, ", ".join(_value_term(v) for v in value)))
            else:
                attrs.append((key, _value_term(value)))

    forms = node.get("forms") or []
    standalone = len(forms) == 0
    form = forms[0] if forms else None
    name = node.get("name") or ""

    primary = primary_full = "—"  # em dash
    secondary = secondary_full = secondary_sub = ""
    material_text = ""
    operator = None
    notional = material = uncertain = provisional = False

    if isinstance(form, dict):
        if form.get("@type") == "lcma:Placeholder":
            ph_name = _local(form.get("hasCategory", ""))
            primary = _abbr(PLACEHOLDER_ABBR, ph_name) or "—"
            primary_full = prettify(ph_name) or "—"
            material = "material" in form
            material_text = _material_text(form.get("material"))
        else:
            fn = form.get("function") or {}
            primary = _fn_headline(fn, True)
            primary_full = _fn_headline(fn, False)
            operator = _fn_operator(fn)
            # A leaf carries `notional` as a bool; the operator tree carries it as a whole-subtree
            # `lcma:FunctionModifier` wrapper (e.g. a notional transformation). Either sets the flag
            # so the notional border + tooltip fire; the headline quotes it independently.
            notional = bool(fn.get("notional")) or (
                fn.get("@type") == "lcma:FunctionModifier"
                and _local(fn.get("modifier", "")) == "notional"
            )
            material = "material" in form
            material_text = _material_text(form.get("material"))
            uncertain = form.get("certainty") == "uncertain"
            ftype = form.get("formalType")
            # A proposed (commit-as-is) function leaf or formal type — flag it so the timeline
            # marks it ⚠, the same channel the reference editor's LEGEND shows.
            provisional = _fn_provisional(fn) or _type_provisional(ftype)
            if isinstance(ftype, dict):
                main = (
                    ftype.get("provisionalTerm", "")
                    if ftype.get("provisional") is True
                    else _local(ftype.get("hasCategory", ""))
                )
                secondary = _abbr(MAIN_TYPE_ABBR, main)
                secondary_full = prettify(main)
                # A formal SUBtype (typeNode emits sub as the CURIE "type:<name>"); shown with a
                # typographic accent after the main type, mirroring the web's "· sub" chip-sub.
                sub = ftype.get("sub")
                if sub:
                    secondary_sub = prettify(
                        _local(sub)
                        if isinstance(sub, str)
                        else _local(sub.get("@id", ""))
                    )
    elif standalone and name:
        primary = primary_full = prettify(name)
    # An unnamed standalone unit keeps the default "—" headline (no "Description" label).

    flags = SpanFlags(
        operator=operator,
        notional=notional,
        material=material,
        attributes=len(attrs),
        references=len(refs),
        uncertain=uncertain,
        provisional=provisional,
        standalone=standalone,
    )
    color = span_fill_hex(primary_full, standalone)
    return SpanModel(
        name=name,
        primary=primary,
        primary_full=primary_full,
        secondary=secondary,
        secondary_full=secondary_full,
        secondary_sub=secondary_sub,
        material_text=material_text,
        color=color,
        flags=flags,
        refs=refs,
        attrs=attrs,
    )


# --- level of detail -----------------------------------------------------------

Lod = str  # "full" | "med" | "short" | "min"


def lod_for(px_width: float) -> Lod:
    """The detail tier a span at this pixel width can legibly show. As a span narrows, channels
    are shed in priority order rather than crammed and clipped.

    These thresholds are tuned for the multi-line, wrapping HTML label (span_html) in tall LCMA
    bands — NOT a single clipped line — so they are far lower than a one-line label would need:
    a ~70px unit wraps its full names over a few lines comfortably, where a single line would
    have to abbreviate. Shedding still happens, just much later."""
    if px_width >= 140:
        return "full"
    if px_width >= 64:
        return "med"
    if px_width >= 32:
        return "short"
    return "min"


def badges_for(m: SpanModel) -> list[Badge]:
    """The single-glyph badges a span carries when inline text has no room. Notional (a border
    style) is intentionally absent; the function operator shows its glyph — ``→`` transformation,
    ``/`` fusion."""
    b: list[Badge] = []
    if m.flags.operator == "transformation":
        b.append(Badge("→", "transformation", "op"))  # →
    elif m.flags.operator == "fusion":
        b.append(Badge("/", "fusion", "op"))  # /
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
    if m.flags.provisional:
        b.append(Badge("⚠", "proposed term — not in the controlled vocabulary", "prov"))
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
    type_parts = []
    # Drop a type-main that just restates the function (see _headline_html), keep its subtype.
    if m.secondary_full and not (
        m.secondary_sub and m.secondary_full.lower() == m.primary_full.lower()
    ):
        type_parts.append(m.secondary_full)
    if m.secondary_sub:
        type_parts.append(m.secondary_sub)
    type_text = " · ".join(type_parts)
    lines = [f"{head}  |  {type_text}" if type_text else head]
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
    if m.flags.provisional:
        lines.append("• proposed term (not in the controlled vocabulary)")
    if m.flags.uncertain:
        lines.append("• uncertain")
    if m.flags.standalone:
        lines.append("• standalone description")
    return "\n".join(lines)


# --- rich HTML projection (the timeline's multi-line LCMA label) ---------------
# span_html renders a SpanModel as the multi-line, weight/size/muted breakdown the LCMA element
# paints with QGraphicsTextItem.setHtml — the timeline counterpart of the builder's LabelChips.
# It is additive: display_label (plain, single line) still backs the tooltip and any plain
# consumer. Qt's rich-text engine supports inline-styled block/inline tags; every user value is
# HTML-escaped because names, attribute values and proposed terms are free text.

_HTML_TEXT = "#1a1a1a"  # near-black headline over the pale family fill
_HTML_MUTED = "#5b6170"  # secondary channels (name, type, material, attributes)
_HTML_PROV = "#b8860b"  # amber — a proposed (⚠) term, the editor's provisional accent


def _esc(value: str) -> str:
    return html.escape(value or "", quote=False)


def _headline_html(m: SpanModel, abbreviate: bool) -> str:
    """The ``function | type`` headline as HTML: function bold (dark), type muted, with a ⚠
    (proposed) and ``?`` (uncertain) mark. ``abbreviate`` chooses the vocab abbreviation over the
    full prettified name (full names at full/med, abbreviations at short)."""
    fn = m.primary if abbreviate else m.primary_full
    ty = m.secondary if abbreviate else m.secondary_full
    # A formal type that merely restates the function (same word) carries no information beyond a
    # subtype it may refine — drop it so "intro" + type "intro·accumulative" reads "Intro ·
    # accumulative", not "Intro | Intro · accumulative".
    if ty and m.secondary_sub and ty.lower() == fn.lower():
        ty = ""
    parts = [f'<span style="font-weight:bold;color:{_HTML_TEXT}">{_esc(fn)}</span>']
    if ty:
        parts.append(f'<span style="color:{_HTML_MUTED}"> | {_esc(ty)}</span>')
    # The subtype gets its own typographic accent (italic) so it reads as a refinement of the
    # type, not a third peer channel. Full names only — short drops it for room.
    if not abbreviate and m.secondary_sub:
        parts.append(
            f'<span style="color:{_HTML_MUTED};font-style:italic"> · {_esc(m.secondary_sub)}</span>'
        )
    if m.flags.provisional:
        parts.append(f'<span style="color:{_HTML_PROV}"> ⚠</span>')
    if m.flags.uncertain:
        parts.append(f'<span style="color:{_HTML_MUTED}"> ?</span>')
    return "".join(parts)


def _attrs_refs_text(m: SpanModel) -> str:
    """Descriptive attributes and cross-unit references as one plain string — ``key: value`` and
    ``dimension → target (qualifier)`` items joined by ``·``. (Escaped by the caller.)"""
    bits = [f"{k}: {v}" for k, v in m.attrs]
    for r in m.refs:
        tail = f" ({prettify(r.qualifier)})" if r.qualifier else ""
        bits.append(f"{r.dimension} → {r.target}{tail}")
    return " · ".join(bits)


def span_html(m: SpanModel, lod: Lod) -> str:
    """The multi-line rich-text label for an LCMA span at a LOD tier, mirroring the builder's
    LabelChips with weight/size/muted distinction. ``full`` shows every channel on its own line
    (full names — the fix for a wide unit only showing its abbreviation); ``med`` keeps name +
    headline + one condensed material/attributes line; ``short`` is a single abbreviated
    ``fn | type`` (+ ``•`` when more channels exist); ``min`` is empty — the colour fill carries
    the family. Returns an HTML fragment for ``QGraphicsTextItem.setHtml``."""
    if lod == "min":
        return ""
    if lod == "short":
        more = bool(m.material_text or m.attrs or m.refs)
        dot = f'<span style="color:{_HTML_MUTED}"> •</span>' if more else ""
        return f'<div style="font-size:8pt">{_headline_html(m, True)}{dot}</div>'

    # full / med — full names, multi-line
    lines = []
    if m.name:
        lines.append(
            f'<div style="font-size:7pt;font-weight:bold;color:{_HTML_MUTED}">'
            f"{_esc(m.name)}</div>"
        )
    lines.append(f'<div style="font-size:9pt">{_headline_html(m, False)}</div>')

    extra = []
    if m.material_text:
        extra.append(_esc(m.material_text))
    attrs_refs = _attrs_refs_text(m)
    if attrs_refs:
        extra.append(_esc(attrs_refs))

    if lod == "full":
        for line in extra:
            lines.append(f'<div style="font-size:7pt;color:{_HTML_MUTED}">{line}</div>')
    elif extra:  # med — collapse material + attributes/refs onto one line
        lines.append(
            f'<div style="font-size:7pt;color:{_HTML_MUTED}">{" · ".join(extra)}</div>'
        )
    return "".join(lines)
