"""Pure (Qt-free) tests for the LCMA span-view projection — the Python port of
annotation-ui ``src/model/spanView.ts``. No fixtures, no webview: just JSON-LD in, model out.
"""

import json

from tilia.ui.timelines.lcma import span_view as sv

# --- colour by family ----------------------------------------------------------


class TestFamilyColour:
    def test_each_family_stem_maps_to_its_hue(self):
        assert sv.family_hue("Main theme") == 145  # thematic green
        assert sv.family_hue("Chorus") == 212  # subordinate blue
        assert sv.family_hue("Transition") == 33  # connective amber
        assert sv.family_hue("Closing") == 2  # closing red
        assert sv.family_hue("Introduction") == 178  # opening teal
        assert sv.family_hue("Development") == 276  # developmental purple

    def test_unmatched_headline_is_grey(self):
        assert sv.family_hue("Wibble") is None

    def test_match_is_case_insensitive_and_on_stems(self):
        assert sv.family_hue("VERSE") == 145
        assert sv.family_hue("recapitulation has a theme") == 145

    def test_span_color_hex_is_qcolor_parseable_hex(self):
        # family -> saturated hex; unmatched -> the grey fallback hex
        assert sv.span_color_hex("Main theme").startswith("#")
        assert len(sv.span_color_hex("Main theme")) == 7
        assert sv.span_color_hex("Wibble") == sv.span_color_hex("also unmatched")

    def test_span_fill_is_the_web_composite_not_the_raw_hue(self):
        # The painted fill is the hue laid over the white track at .span-fill opacity, so it is
        # much paler than the raw family hue — this is what makes it match the reference editor.
        raw = sv.span_color_hex("Main theme")
        fill = sv.span_fill_hex("Main theme")
        assert fill != raw
        assert len(fill) == 7 and fill.startswith("#")
        # composited over white -> every channel is lighter than the raw hue
        assert all(
            int(fill[i : i + 2], 16) >= int(raw[i : i + 2], 16) for i in (1, 3, 5)
        )
        # standalone uses a still-lower opacity, so it is paler again than the base grey fill
        assert sv.span_fill_hex("x", standalone=True) != sv.span_fill_hex("x")


# --- prettify / LOD ------------------------------------------------------------


class TestPrettifyAndLod:
    def test_prettify(self):
        assert sv.prettify("basic_idea") == "Basic idea"
        assert sv.prettify("hybrid1") == "Hybrid 1"
        assert sv.prettify("") == ""

    def test_abbr_maps_loaded_from_vendored_vocab(self):
        # the vendored vocab.json must actually load, so headlines match the reference editor
        assert sv.FUNCTION_ABBR.get("basic_idea") == "bi"
        assert sv.FUNCTION_ABBR.get("transition") == "tr"
        assert sv.MAIN_TYPE_ABBR.get("period") == "pd"

    def test_abbr_falls_back_to_prettify_for_unknown_name(self):
        assert sv._abbr(sv.FUNCTION_ABBR, "not_a_real_term") == "Not a real term"

    def test_lod_thresholds(self):
        # Tuned for the multi-line wrapping label in tall bands — far lower than a single-line
        # label needs, so a ~70px unit shows full names (wrapped) instead of folding to an abbr.
        assert sv.lod_for(140) == "full"
        assert sv.lod_for(139) == "med"
        assert sv.lod_for(64) == "med"
        assert sv.lod_for(63) == "short"
        assert sv.lod_for(32) == "short"
        assert sv.lod_for(31) == "min"
        assert sv.lod_for(0) == "min"

    def test_lod_units_shed_earlier_for_multi_operand_headlines(self):
        # A K-operand fusion/transformation headline is ~K× as wide, so the tier is picked against
        # width/units: it sheds to a coarser tier earlier than a plain function of the same px width.
        assert sv.lod_for(140, 1) == "full"  # plain function: ladder unchanged
        assert sv.lod_for(140, 2) == "med"  # 140/2 = 70  -> med
        assert sv.lod_for(140, 3) == "short"  # 140/3 ≈ 46 -> short
        assert sv.lod_for(280, 2) == "full"  # 280/2 = 140 -> full
        assert sv.lod_for(96, 3) == "short"  # 96/3 = 32   -> short
        assert sv.lod_for(95, 3) == "min"  # 95/3 ≈ 31   -> min
        assert sv.lod_for(64) == "med"  # units defaults to 1 (bare call unchanged)


# --- parsing -------------------------------------------------------------------


def _named_jsonld():
    return json.dumps(
        {
            "@context": {"ignored": "wrapper"},
            "@type": ["lcma:AnnotationLabel", "lcma:AnnotatedUnit"],
            "@id": "anno:Theme%20A",
            "name": "Theme A",
            "forms": [
                {
                    "@type": "lcma:Form",
                    "function": {
                        "@type": "lcma:Function",
                        "hasCategory": "fn:basic_idea",
                    },
                    "formalType": {
                        "@type": "lcma:FormalType",
                        "hasCategory": "type:period",
                    },
                    "material": {"@type": "lcma:MaterialReferences", "refs": []},
                    "certainty": "uncertain",
                }
            ],
            "hasAttribute": [
                {
                    "@type": "lcma:AttributeAssignment",
                    "key": {"@id": "lcma:texture"},
                    "value": "homophonic",
                },
                {
                    "@type": "lcma:AttributeAssignment",
                    "key": {"@id": "lcma:harmony"},
                    "valueRef": [
                        {
                            "@type": "lcma:AttrRef",
                            "refTarget": "anno:Verse",
                            "qualifier": {"@id": "lcma:louder_than"},
                        }
                    ],
                },
            ],
        }
    )


class TestParse:
    def test_empty_is_placeholder_garbage_is_none(self):
        # An empty annotation projects the empty-form PLACEHOLDER ("—" headline) so an un-annotated
        # LCMA unit still renders as an LCMA form (todo #2). Only unparseable / non-object input
        # returns None (the raw-label fallback).
        for empty in ("", "   "):
            m = sv.parse_span_model(empty)
            assert m is not None, empty
            assert m.primary == "—"
        assert sv.parse_span_model("not json") is None
        assert sv.parse_span_model("[1,2,3]") is None  # not an object

    def test_empty_matches_empty_span_model(self):
        assert sv.parse_span_model("") == sv.empty_span_model()

    def test_named_form(self):
        m = sv.parse_span_model(_named_jsonld())
        assert m.name == "Theme A"
        assert m.primary == sv.FUNCTION_ABBR["basic_idea"]  # abbreviated headline
        assert m.primary_full == "Basic idea"  # un-abbreviated, for tooltip/detail
        assert m.secondary == sv.MAIN_TYPE_ABBR["period"]
        assert m.secondary_full == "Period"
        assert m.color == sv.span_fill_hex(
            "Basic idea"
        )  # green family, track-composited
        assert m.flags.material is True
        assert m.flags.uncertain is True
        assert m.flags.operator is None
        assert m.flags.standalone is False
        assert m.attrs == [("texture", "homophonic")]
        assert m.refs == [sv.SpanRef("harmony", "Verse", "louder_than")]
        assert m.flags.attributes == 1
        assert m.flags.references == 1

    def test_formal_subtype_is_parsed(self):
        # typeNode emits the subtype as the CURIE "type:<name>" under `sub`
        data = json.dumps(
            {
                "forms": [
                    {
                        "@type": "lcma:Form",
                        "function": {"hasCategory": "fn:basic_idea"},
                        "formalType": {
                            "@type": "lcma:FormalType",
                            "hasCategory": "type:period",
                            "sub": "type:parallel",
                        },
                    }
                ]
            }
        )
        m = sv.parse_span_model(data)
        assert m.secondary_full == "Period"
        assert m.secondary_sub == "Parallel"

    def test_no_subtype_leaves_secondary_sub_empty(self):
        m = sv.parse_span_model(_named_jsonld())
        assert m.secondary_sub == ""

    def test_transformation_headline_and_operator(self):
        data = json.dumps(
            {
                "forms": [
                    {
                        "@type": "lcma:Form",
                        "function": {
                            "@type": "lcma:FunctionTransformation",
                            "source": {"hasCategory": "fn:basic_idea"},
                            "target": {"hasCategory": "fn:contrasting_idea"},
                        },
                    }
                ]
            }
        )
        m = sv.parse_span_model(data)
        bi, ci = sv.FUNCTION_ABBR["basic_idea"], sv.FUNCTION_ABBR["contrasting_idea"]
        assert m.primary == f"{bi}→{ci}"
        assert m.primary_full == "Basic idea→Contrasting idea"
        assert m.flags.operator == "transformation"

    def test_notional_function_is_quoted(self):
        data = json.dumps(
            {
                "forms": [
                    {
                        "@type": "lcma:Form",
                        "function": {"hasCategory": "fn:basic_idea", "notional": True},
                    }
                ]
            }
        )
        m = sv.parse_span_model(data)
        assert m.primary == f"“{sv.FUNCTION_ABBR['basic_idea']}”"  # abbr, quoted
        assert m.primary_full == "“Basic idea”"
        assert m.flags.notional is True

    def test_cardinality_renders_as_ordinal_prefix(self):
        # a function leaf's cardinality (repeat count) shows as an ordinal prefix on both tiers
        data = json.dumps(
            {
                "forms": [
                    {
                        "@type": "lcma:Form",
                        "function": {"hasCategory": "fn:intro", "cardinality": 3},
                    }
                ]
            }
        )
        m = sv.parse_span_model(data)
        assert m.primary == f"3rd {sv.FUNCTION_ABBR['intro']}"
        assert m.primary_full == "3rd Intro"

    def test_cardinality_ordinal_suffixes(self):
        assert sv._ordinal(1) == "1st"
        assert sv._ordinal(2) == "2nd"
        assert sv._ordinal(3) == "3rd"
        assert sv._ordinal(4) == "4th"
        assert sv._ordinal(9) == "9th"

    def test_cardinality_prefix_is_inside_notional_quotes(self):
        # mirrors SingleFnText: `“${card}${name}”`, not `${card}“${name}”`
        data = json.dumps(
            {
                "forms": [
                    {
                        "@type": "lcma:Form",
                        "function": {
                            "hasCategory": "fn:intro",
                            "cardinality": 2,
                            "notional": True,
                        },
                    }
                ]
            }
        )
        m = sv.parse_span_model(data)
        assert m.primary_full == "“2nd Intro”"

    def test_cardinality_on_transformation_side(self):
        # each leaf of a transformation carries its own cardinality
        data = json.dumps(
            {
                "forms": [
                    {
                        "@type": "lcma:Form",
                        "function": {
                            "@type": "lcma:FunctionTransformation",
                            "source": {"hasCategory": "fn:intro", "cardinality": 2},
                            "target": {"hasCategory": "fn:transition"},
                        },
                    }
                ]
            }
        )
        m = sv.parse_span_model(data)
        assert m.primary_full == "2nd Intro→Transition"

    def test_placeholder(self):
        data = json.dumps(
            {
                "name": "Q",
                "forms": [
                    {"@type": "lcma:Placeholder", "hasCategory": "ph:fortspinnung"}
                ],
            }
        )
        m = sv.parse_span_model(data)
        # not a controlled placeholder in the vocab -> prettified fallback (both tiers)
        assert m.primary == "Fortspinnung"
        assert m.primary_full == "Fortspinnung"
        assert m.flags.standalone is False

    def test_placeholder_uses_vocab_abbr_when_present(self):
        data = json.dumps(
            {"forms": [{"@type": "lcma:Placeholder", "hasCategory": "ph:repeat"}]}
        )
        m = sv.parse_span_model(data)
        assert m.primary == sv.PLACEHOLDER_ABBR["repeat"]  # "%"
        assert m.primary_full == "Repeat"

    def test_bare_material_reference_shows_repeat_glyph_and_ref(self):
        # A "ref!" unit: a function form with no category at all, only a material
        # reference — must not fall back to the empty-headline em dash (todo #19).
        data = json.dumps(
            {
                "forms": [
                    {
                        "@type": "lcma:Form",
                        "function": {"@type": "lcma:Function"},
                        "material": {
                            "@type": "lcma:MaterialReferences",
                            "refs": [{"ref": "Verse"}],
                        },
                    }
                ],
            }
        )
        m = sv.parse_span_model(data)
        assert m.primary == f'{sv.PLACEHOLDER_ABBR["repeat"]} [Verse]'
        assert m.primary_full == m.primary

    def test_fusion_with_material_keeps_its_headline(self):
        # todo #4: a fusion / transformation form carrying a material reference must render its
        # function headline (bi/ci), NOT collapse to the bare-reference "% [ref]" glyph. The
        # operator tree has no top-level hasCategory, so the empty-headline fallback used to
        # clobber it; the material still rides in its own channel (flags.material / material_text).
        data = json.dumps(
            {
                "forms": [
                    {
                        "@type": "lcma:Form",
                        "function": {
                            "@type": "lcma:FunctionOperation",
                            "operator": "fnop:fusion",
                            "operands": [
                                {
                                    "@type": "lcma:Function",
                                    "hasCategory": "fn:basic_idea",
                                },
                                {
                                    "@type": "lcma:Function",
                                    "hasCategory": "fn:contrasting_idea",
                                },
                            ],
                        },
                        "material": {
                            "@type": "lcma:MaterialReferences",
                            "refs": [{"ref": "Verse"}],
                        },
                    }
                ]
            }
        )
        m = sv.parse_span_model(data)
        bi, ci = sv.FUNCTION_ABBR["basic_idea"], sv.FUNCTION_ABBR["contrasting_idea"]
        assert m.primary == f"{bi}/{ci}"
        assert m.primary_full == "Basic idea/Contrasting idea"
        assert m.flags.operator == "fusion"
        assert m.flags.material is True
        assert m.material_text == "Verse"

    def test_transformation_with_material_keeps_its_headline(self):
        # todo #4, transformation side: same guard, directed-arrow glyph.
        data = json.dumps(
            {
                "forms": [
                    {
                        "@type": "lcma:Form",
                        "function": {
                            "@type": "lcma:FunctionTransformation",
                            "source": {"hasCategory": "fn:basic_idea"},
                            "target": {"hasCategory": "fn:contrasting_idea"},
                        },
                        "material": {
                            "@type": "lcma:MaterialReferences",
                            "refs": [{"ref": "Verse"}],
                        },
                    }
                ]
            }
        )
        m = sv.parse_span_model(data)
        bi, ci = sv.FUNCTION_ABBR["basic_idea"], sv.FUNCTION_ABBR["contrasting_idea"]
        assert m.primary == f"{bi}→{ci}"
        assert m.flags.operator == "transformation"
        assert m.flags.material is True

    def test_standalone_is_grey_and_flagged(self):
        data = json.dumps(
            {
                "forms": [],
                "hasAttribute": [
                    {
                        "@type": "lcma:AttributeAssignment",
                        "key": "mykey",
                        "value": "v",
                    }
                ],
            }
        )
        m = sv.parse_span_model(data)
        assert m.primary == "—"  # unnamed standalone unit: no "Description" label
        assert m.flags.standalone is True
        assert m.color == sv.span_fill_hex("x", standalone=True)  # forced grey, paler
        assert m.attrs == [("mykey", "v")]

    def test_soft_attribute_key_stays_literal(self):
        # a free/soft key is a plain string, not an {@id} node ref
        data = json.dumps(
            {
                "forms": [{"@type": "lcma:Form", "function": {"hasCategory": "fn:x"}}],
                "hasAttribute": [
                    {
                        "@type": "lcma:AttributeAssignment",
                        "key": "mood",
                        "value": "dark",
                    }
                ],
            }
        )
        m = sv.parse_span_model(data)
        assert m.attrs == [("mood", "dark")]

    def test_multi_valued_key_joins_its_values(self):
        # a multi-valued key (instrumentation) is a SET — each element is joined with ", "
        data = json.dumps(
            {
                "forms": [{"@type": "lcma:Form", "function": {"hasCategory": "fn:x"}}],
                "hasAttribute": [
                    {
                        "@type": "lcma:AttributeAssignment",
                        "key": {"@id": "lcma:instrumentation"},
                        "value": [{"@id": "lcma:violin"}, {"@id": "lcma:guitar"}],
                    }
                ],
            }
        )
        m = sv.parse_span_model(data)
        assert m.attrs == [("instrumentation", "violin, guitar")]

    def test_delta_valued_element_shows_add_remove_sign(self):
        # a deltaValued element (instrumentation +guitar / -organ) reifies as an lcma:ValueChange
        # node; it must render with its +/− sign, not fall through to an empty string
        data = json.dumps(
            {
                "forms": [{"@type": "lcma:Form", "function": {"hasCategory": "fn:x"}}],
                "hasAttribute": [
                    {
                        "@type": "lcma:AttributeAssignment",
                        "key": {"@id": "lcma:instrumentation"},
                        "value": [
                            {"@id": "lcma:violin"},
                            {
                                "@type": "lcma:ValueChange",
                                "change": "lcma:added",
                                "value": {"@id": "lcma:guitar"},
                            },
                            {
                                "@type": "lcma:ValueChange",
                                "change": "lcma:removed",
                                "value": {"@id": "lcma:organ"},
                            },
                        ],
                    }
                ],
            }
        )
        m = sv.parse_span_model(data)
        assert m.attrs == [("instrumentation", "violin, +guitar, −organ")]

    def test_delta_valued_proposed_value_keeps_its_verbatim_term(self):
        # a delta on a value NOT in the controlled enum (a proposed value) unwraps the flagged
        # literal, still prefixed with the sign
        data = json.dumps(
            {
                "forms": [{"@type": "lcma:Form", "function": {"hasCategory": "fn:x"}}],
                "hasAttribute": [
                    {
                        "@type": "lcma:AttributeAssignment",
                        "key": {"@id": "lcma:instrumentation"},
                        "value": [
                            {
                                "@type": "lcma:ValueChange",
                                "change": "lcma:added",
                                "value": {
                                    "provisional": True,
                                    "provisionalTerm": "kazoo",
                                },
                            }
                        ],
                    }
                ],
            }
        )
        m = sv.parse_span_model(data)
        assert m.attrs == [("instrumentation", "+kazoo")]


# --- badges / display text / tooltip ------------------------------------------


class TestChannels:
    def test_badges_order_and_glyphs(self):
        m = sv.parse_span_model(_named_jsonld())
        glyphs = [b.glyph for b in sv.badges_for(m)]
        assert glyphs == ["▦", "✱", "↗", "?"]  # mat, attr, ref, unc (no transformation)

    def test_transformation_badge_arrow(self):
        data = json.dumps(
            {
                "forms": [
                    {
                        "@type": "lcma:Form",
                        "function": {
                            "@type": "lcma:FunctionTransformation",
                            "source": {"hasCategory": "fn:basic_idea"},
                            "target": {"hasCategory": "fn:contrasting_idea"},
                        },
                    }
                ]
            }
        )
        assert [b.glyph for b in sv.badges_for(sv.parse_span_model(data))] == ["→"]

    def test_display_label_sheds_by_tier(self):
        m = sv.parse_span_model(_named_jsonld())
        bi, pd = sv.FUNCTION_ABBR["basic_idea"], sv.MAIN_TYPE_ABBR["period"]
        full = sv.display_label(m, "full")
        assert "Theme A" in full and bi in full and pd in full
        # short: abbreviated headline only + a dot (it carries badges)
        short = sv.display_label(m, "short")
        assert short == f"{bi} •"
        # min: nothing — the colour fill carries the family
        assert sv.display_label(m, "min") == ""

    def test_tooltip_lists_every_channel(self):
        tip = sv.span_tooltip(sv.parse_span_model(_named_jsonld()))
        assert "Theme A — Basic idea" in tip
        assert "Period" in tip
        assert "• material reference" in tip
        assert "• texture: homophonic" in tip
        assert "• harmony → Verse (Louder than)" in tip
        assert "• uncertain" in tip


# --- robustness: hand-edited / non-builder JSON-LD must never crash the renderer ----
# annotation_data is a free string field on the component, so a .tla can carry anything (a
# hand edit, a future schema, a truncated write). parse_span_model must return None or a safe
# model — never raise — and every downstream consumer must survive whatever it returns.


class TestRobustness:
    MALFORMED = [
        '{"forms": ["x"]}',  # form is not an object
        '{"forms": [null]}',  # form is null
        '{"forms": [{"@type": "lcma:Form", "function": {}}]}',  # no hasCategory
        '{"forms": [{"@type": "lcma:Form", "function": {"hasCategory": "fn:x"}}],'
        ' "hasAttribute": {"k": "v"}}',  # hasAttribute is a dict, not a list
        '{"forms": [{"@type":"lcma:Form","function":{"hasCategory":"fn:x"}}],'
        ' "hasAttribute":[{"key":"k","valueRef":[{}]}]}',  # ref with no refTarget
        '{"forms": [{"@type":"lcma:Form","function":{"hasCategory":"fn:x"},'
        ' "formalType":"oops"}]}',  # formalType not an object
    ]

    # Empty / whitespace are NOT here: they project the empty-form placeholder, not None
    # (see TestParse.test_empty_is_placeholder_garbage_is_none). These are true non-objects.
    NON_MODELS = ["not json", "[1,2,3]", "42", "null", '"hi"']

    def test_non_objects_return_none(self):
        for data in self.NON_MODELS:
            assert sv.parse_span_model(data) is None, data

    def test_malformed_objects_parse_without_crashing(self):
        for data in self.MALFORMED:
            m = sv.parse_span_model(data)
            assert m is not None, data  # a JSON object always yields a (safe) model
            # every consumer must survive the model
            for lod in ("full", "med", "short", "min"):
                assert isinstance(sv.display_label(m, lod), str)
            assert isinstance(sv.span_tooltip(m), str)
            assert all(b.glyph for b in sv.badges_for(m))
            assert m.color.startswith("#") and len(m.color) == 7

    def test_deeply_nested_transformation(self):
        data = json.dumps(
            {
                "forms": [
                    {
                        "@type": "lcma:Form",
                        "function": {
                            "@type": "lcma:FunctionTransformation",
                            "source": {
                                "@type": "lcma:FunctionTransformation",
                                "source": {"hasCategory": "fn:basic_idea"},
                                "target": {"hasCategory": "fn:cadence"},
                            },
                            "target": {"hasCategory": "fn:transition"},
                        },
                    }
                ]
            }
        )
        m = sv.parse_span_model(data)
        assert "→" in m.primary and m.primary.count("→") == 2
        assert m.flags.operator == "transformation"

    def test_unicode_reference_target_round_trips(self):
        # refTarget is percent-encoded by the builder (unitIri); _unit_name must decode it
        data = json.dumps(
            {
                "forms": [{"@type": "lcma:Form", "function": {"hasCategory": "fn:x"}}],
                "hasAttribute": [
                    {
                        "key": {"@id": "lcma:harmony"},
                        "valueRef": [{"refTarget": "anno:Th%C3%A8me%20A"}],
                    }
                ],
            }
        )
        m = sv.parse_span_model(data)
        assert m.refs[0].target == "Thème A"


# --- new-model channels: cadences, proposed (provisional) terms, multi-valued attrs ----------
# The structured editor emits these now; the span view must read what reaches the wire so the
# timeline stays in step with the builder (mirrors the same features in spanView.ts).


class TestNewModelChannels:
    def test_cadence_abbr_loaded_from_its_own_vocab_group(self):
        # cadences moved to vocab.functions.cadences; their abbreviations must still load
        assert sv.FUNCTION_ABBR.get("pac") == "PAC"
        assert sv.FUNCTION_ABBR.get("hc") == "HC"

    def test_provisional_function_headline_flag_and_badge(self):
        data = json.dumps(
            {
                "forms": [
                    {
                        "@type": "lcma:Form",
                        "function": {
                            "@type": "lcma:Function",
                            "provisional": True,
                            "provisionalTerm": "my_new_function",
                        },
                    }
                ]
            }
        )
        m = sv.parse_span_model(data)
        assert m.flags.provisional is True
        # proposed term shown verbatim (prettified), not "—"
        assert m.primary_full == "My new function"
        assert "⚠" in [b.glyph for b in sv.badges_for(m)]
        assert "• proposed term (not in the controlled vocabulary)" in sv.span_tooltip(
            m
        )

    def test_provisional_leaf_inside_transformation_is_flagged(self):
        data = json.dumps(
            {
                "forms": [
                    {
                        "@type": "lcma:Form",
                        "function": {
                            "@type": "lcma:FunctionTransformation",
                            "source": {"provisional": True, "provisionalTerm": "weird"},
                            "target": {"hasCategory": "fn:transition"},
                        },
                    }
                ]
            }
        )
        m = sv.parse_span_model(data)
        assert m.flags.provisional is True
        assert m.flags.operator == "transformation"

    def test_provisional_formal_type_is_flagged_and_shown(self):
        data = json.dumps(
            {
                "forms": [
                    {
                        "@type": "lcma:Form",
                        "function": {"hasCategory": "fn:basic_idea"},
                        "formalType": {
                            "@type": "lcma:FormalType",
                            "provisional": True,
                            "provisionalTerm": "my_type",
                        },
                    }
                ]
            }
        )
        m = sv.parse_span_model(data)
        assert m.flags.provisional is True
        assert m.secondary_full == "My type"

    def test_multi_valued_attribute_is_joined(self):
        data = json.dumps(
            {
                "forms": [{"@type": "lcma:Form", "function": {"hasCategory": "fn:x"}}],
                "hasAttribute": [
                    {
                        "@type": "lcma:AttributeAssignment",
                        "key": {"@id": "lcma:instrumentation"},
                        "value": ["bassoon", "cello"],
                    }
                ],
            }
        )
        m = sv.parse_span_model(data)
        assert m.attrs == [("instrumentation", "bassoon, cello")]
        assert m.flags.attributes == 1

    def test_provisional_attribute_value(self):
        # a proposed value on a controlled key is a flagged literal carrying its verbatim term
        data = json.dumps(
            {
                "forms": [{"@type": "lcma:Form", "function": {"hasCategory": "fn:x"}}],
                "hasAttribute": [
                    {
                        "@type": "lcma:AttributeAssignment",
                        "key": {"@id": "lcma:harmonicProgression"},
                        "value": {
                            "provisional": True,
                            "provisionalTerm": "my-progression",
                        },
                    }
                ],
            }
        )
        m = sv.parse_span_model(data)
        assert m.attrs == [("harmonicProgression", "my-progression")]


# --- function-operator tree: fusion (/) and transformation (→) -----------------
# The builder serialises functions as a {operator, operands} tree — fusion and transformation, both
# n-ary — with a notional modifier wrapper (jsonld.ts fnExprNode; docs/function-operators.md). The
# span view must read both operators so the timeline shows what the reference editor's LabelChips do.


def _fn_form(function: dict) -> str:
    return json.dumps({"forms": [{"@type": "lcma:Form", "function": function}]})


def _op(operator: str, *operands: dict) -> dict:
    return {
        "@type": "lcma:FunctionOperation",
        "operator": f"fnop:{operator}",
        "operands": list(operands),
    }


def _leaf(name: str) -> dict:
    return {"@type": "lcma:Function", "hasCategory": f"fn:{name}"}


def _notional(operand: dict) -> dict:
    return {
        "@type": "lcma:FunctionModifier",
        "modifier": "fnop:notional",
        "operand": operand,
    }


class TestFunctionOperatorTree:
    def test_fusion_headline_operator_and_badge(self):
        m = sv.parse_span_model(
            _fn_form(_op("fusion", _leaf("basic_idea"), _leaf("contrasting_idea")))
        )
        bi, ci = sv.FUNCTION_ABBR["basic_idea"], sv.FUNCTION_ABBR["contrasting_idea"]
        assert m.primary == f"{bi}/{ci}"  # abbreviated, joined by /
        assert m.primary_full == "Basic idea/Contrasting idea"
        assert m.flags.operator == "fusion"
        assert [b.glyph for b in sv.badges_for(m)] == ["/"]

    def test_transformation_operation_is_n_ary(self):
        # the operator tree the bar authors now (a > b > c), distinct from the legacy binary
        # lcma:FunctionTransformation node
        m = sv.parse_span_model(
            _fn_form(
                _op(
                    "transformation",
                    _leaf("basic_idea"),
                    _leaf("cadence"),
                    _leaf("transition"),
                )
            )
        )
        assert m.primary_full == "Basic idea→Cadence→Transition"
        assert m.primary_full.count("→") == 2
        assert m.flags.operator == "transformation"
        assert [b.glyph for b in sv.badges_for(m)] == ["→"]

    def test_notional_modifier_quotes_whole_operation(self):
        # "a > b" — the transformation itself is notional (a modifier wrapping the operation), which
        # the old leaf-level bool could not express
        m = sv.parse_span_model(
            _fn_form(
                _notional(
                    _op("transformation", _leaf("antecedent"), _leaf("consequent"))
                )
            )
        )
        assert m.primary_full == "“Antecedent→Consequent”"
        assert m.flags.notional is True
        assert m.flags.operator == "transformation"  # unwrapped from the modifier

    def test_nested_operation_is_parenthesised(self):
        # "ant" > (bi / ci): a notional endpoint transformed into a fusion — the docs' nesting example
        m = sv.parse_span_model(
            _fn_form(
                _op(
                    "transformation",
                    _notional(_leaf("antecedent")),
                    _op("fusion", _leaf("basic_idea"), _leaf("contrasting_idea")),
                )
            )
        )
        assert m.primary_full == "“Antecedent”→(Basic idea/Contrasting idea)"
        assert (
            m.flags.operator == "transformation"
        )  # outermost operator drives the badge

    def test_provisional_leaf_inside_fusion_is_flagged(self):
        m = sv.parse_span_model(
            _fn_form(
                _op(
                    "fusion",
                    {"provisional": True, "provisionalTerm": "weird"},
                    _leaf("transition"),
                )
            )
        )
        assert m.primary_full == "Weird/Transition"
        assert m.flags.provisional is True
        assert "⚠" in [b.glyph for b in sv.badges_for(m)]

    def test_leaf_crossing_rightward_is_an_inline_fusion(self):
        # the old under-specified fusion: a bare leaf flagged crossing_rightward, rendered with a
        # trailing / (mirrors SingleFnText's fn-op-pill)
        m = sv.parse_span_model(
            _fn_form(
                {
                    "@type": "lcma:Function",
                    "hasCategory": "fn:basic_idea",
                    "crossing_rightward": True,
                }
            )
        )
        assert m.primary_full == "Basic idea/"
        assert m.flags.operator == "fusion"
        assert [b.glyph for b in sv.badges_for(m)] == ["/"]

    def test_fusion_named_in_tooltip(self):
        m = sv.parse_span_model(
            _fn_form(_op("fusion", _leaf("basic_idea"), _leaf("contrasting_idea")))
        )
        assert "• fusion" in sv.span_tooltip(m)

    def test_operator_tree_with_no_or_bad_operands_never_crashes(self):
        # hand-edited / malformed JSON-LD must degrade, not raise (see TestRobustness)
        assert sv.parse_span_model(_fn_form(_op("transformation"))).primary_full == "—"
        m = sv.parse_span_model(
            _fn_form(
                {
                    "@type": "lcma:FunctionOperation",
                    "operator": "fnop:fusion",
                    "operands": ["junk", _leaf("transition")],
                }
            )
        )
        assert m.primary_full == "—/Transition"
        assert m.flags.operator == "fusion"

    def test_headline_units_counts_leaf_functions(self):
        # headline_units drives the LOD width demand: 1 for a plain function, the summed leaves for
        # an operator tree (through nesting and the notional modifier), 2 for a legacy transformation
        def units(fn: dict) -> int:
            return sv.parse_span_model(_fn_form(fn)).headline_units

        assert units(_leaf("basic_idea")) == 1
        assert units(_op("fusion", _leaf("basic_idea"), _leaf("contrasting_idea"))) == 2
        assert (
            units(
                _op(
                    "transformation",
                    _leaf("basic_idea"),
                    _leaf("cadence"),
                    _leaf("transition"),
                )
            )
            == 3
        )
        # nested: transformation( notional(ant), fusion(bi, ci) ) -> 1 + 2 = 3
        assert (
            units(
                _op(
                    "transformation",
                    _notional(_leaf("antecedent")),
                    _op("fusion", _leaf("basic_idea"), _leaf("contrasting_idea")),
                )
            )
            == 3
        )
        assert units(_notional(_leaf("antecedent"))) == 1  # modifier wrapping one leaf
        # legacy binary transformation node
        legacy = {
            "@type": "lcma:FunctionTransformation",
            "source": {"hasCategory": "fn:basic_idea"},
            "target": {"hasCategory": "fn:transition"},
        }
        assert units(legacy) == 2

    def test_headline_units_is_one_for_plain_and_placeholder(self):
        # a plain function and a placeholder both stay on the tuned single-unit LOD ladder
        assert sv.parse_span_model(_fn_form(_leaf("basic_idea"))).headline_units == 1
        ph = json.dumps(
            {"forms": [{"@type": "lcma:Placeholder", "hasCategory": "ph:repeat"}]}
        )
        assert sv.parse_span_model(ph).headline_units == 1


# --- material references parsed to a string (material_text) --------------------
# The timeline shows the specific references as text (not a generic ▦ badge). material_text
# mirrors revMaterial + the Refs/MaterialChip components: refs joined ", ", each name + its
# operator symbols, {…} when unordered, transformational as "source ▸ target".


def _material_jsonld(material: dict) -> str:
    return json.dumps(
        {
            "forms": [
                {
                    "@type": "lcma:Form",
                    "function": {"hasCategory": "fn:x"},
                    "material": material,
                }
            ]
        }
    )


class TestMaterialText:
    def test_operator_maps_loaded_from_vocab(self):
        # a string-writable operator renders as its symbol; the maps must actually load
        assert sv.OPERATOR_SYMBOL.get("adaptation") == "°"
        assert sv.OPERATOR_WRITABLE.get("adaptation") is True

    def test_references_joined_with_operator_symbols(self):
        m = sv.parse_span_model(
            _material_jsonld(
                {
                    "@type": "lcma:MaterialReferences",
                    "refs": [
                        {
                            "@type": "lcma:Reference",
                            "ref": "r1",
                            "operators": ["op:adaptation"],
                        },
                        {"@type": "lcma:Reference", "ref": "r2", "operators": []},
                    ],
                }
            )
        )
        assert m.flags.material is True
        assert m.material_text == "r1°, r2"

    def test_unordered_set_is_braced(self):
        m = sv.parse_span_model(
            _material_jsonld(
                {
                    "@type": "lcma:MaterialReferences",
                    "unordered": True,
                    "refs": [
                        {"ref": "r1", "operators": []},
                        {"ref": "r2", "operators": []},
                    ],
                }
            )
        )
        assert m.material_text == "{r1, r2}"

    def test_sentinel_reference_shows_prev(self):
        m = sv.parse_span_model(
            _material_jsonld(
                {
                    "@type": "lcma:MaterialReferences",
                    "refs": [{"ref": sv.SENTINEL, "operators": []}],
                }
            )
        )
        assert m.material_text == "prev"

    def test_non_writable_operator_is_prettified(self):
        # augmentation is not string-writable -> its prettified word, not the raw symbol
        m = sv.parse_span_model(
            _material_jsonld(
                {
                    "@type": "lcma:MaterialReferences",
                    "refs": [{"ref": "r1", "operators": ["op:augmentation"]}],
                }
            )
        )
        assert m.material_text == "r1Augmentation"

    def test_transformational_material_is_source_to_target(self):
        m = sv.parse_span_model(
            _material_jsonld(
                {
                    "@type": "lcma:TransformationalMaterial",
                    "source": {"refs": [{"ref": "r1", "operators": []}]},
                    "target": {"refs": [{"ref": "r2", "operators": []}]},
                }
            )
        )
        assert m.material_text == "r1 ▸ r2"

    def test_transformational_null_side_is_dash(self):
        m = sv.parse_span_model(
            _material_jsonld(
                {
                    "@type": "lcma:TransformationalMaterial",
                    "source": None,
                    "target": {"refs": [{"ref": "r2", "operators": []}]},
                }
            )
        )
        assert m.material_text == "— ▸ r2"

    def test_no_material_is_empty_string(self):
        m = sv.parse_span_model(
            json.dumps(
                {"forms": [{"@type": "lcma:Form", "function": {"hasCategory": "fn:x"}}]}
            )
        )
        assert m.material_text == ""


# --- rich HTML projection (span_html) ------------------------------------------
# The painted timeline label. Full names at full width (the "Core | caaba" fix), material and
# attributes as readable strings, weight/size/muted distinction, channels shed by LOD, and every
# user value HTML-escaped.


class TestSpanHtml:
    def test_full_shows_full_names_not_abbreviations(self):
        m = sv.parse_span_model(_named_jsonld())
        out = sv.span_html(m, "full")
        assert "Theme A" in out  # name line
        assert "Basic idea" in out  # FULL function name, not "bi"
        assert "Period" in out  # FULL type name, not "pd"

    def test_full_includes_material_and_attributes_as_strings(self):
        m = sv.parse_span_model(
            json.dumps(
                {
                    "name": "U",
                    "forms": [
                        {
                            "@type": "lcma:Form",
                            "function": {"hasCategory": "fn:chorus"},
                            "material": {
                                "@type": "lcma:MaterialReferences",
                                "refs": [{"ref": "r1", "operators": []}],
                            },
                        }
                    ],
                    "hasAttribute": [
                        {
                            "key": {"@id": "lcma:texture"},
                            "value": "homophonic",
                        }
                    ],
                }
            )
        )
        out = sv.span_html(m, "full")
        assert "r1" in out  # material reference string
        assert "texture: homophonic" in out  # attribute string

    def test_provisional_shows_proposed_glyph(self):
        m = sv.parse_span_model(
            json.dumps(
                {
                    "forms": [
                        {
                            "@type": "lcma:Form",
                            "function": {
                                "@type": "lcma:Function",
                                "provisional": True,
                                "provisionalTerm": "my_fn",
                            },
                        }
                    ]
                }
            )
        )
        assert "⚠" in sv.span_html(m, "full")

    def test_values_are_html_escaped(self):
        m = sv.parse_span_model(
            json.dumps(
                {
                    "name": "A & B <x>",
                    "forms": [
                        {"@type": "lcma:Form", "function": {"hasCategory": "fn:x"}}
                    ],
                }
            )
        )
        out = sv.span_html(m, "full")
        assert "A &amp; B &lt;x&gt;" in out
        assert "A & B <x>" not in out

    def test_min_is_empty_and_short_is_abbreviated_single_line(self):
        m = sv.parse_span_model(_named_jsonld())
        assert sv.span_html(m, "min") == ""
        short = sv.span_html(m, "short")
        assert sv.FUNCTION_ABBR["basic_idea"] in short  # abbreviated headline
        assert "Basic idea" not in short  # not the full name at short
        assert "•" in short  # carries more channels (material/attrs/refs)

    def test_subtype_rendered_with_typographic_accent(self):
        m = sv.parse_span_model(
            json.dumps(
                {
                    "forms": [
                        {
                            "@type": "lcma:Form",
                            "function": {"hasCategory": "fn:basic_idea"},
                            "formalType": {
                                "@type": "lcma:FormalType",
                                "hasCategory": "type:period",
                                "sub": "type:parallel",
                            },
                        }
                    ]
                }
            )
        )
        out = sv.span_html(m, "full")
        assert "Period" in out
        assert "Parallel" in out  # the subtype is shown
        assert "font-style:italic" in out  # ...with a typographic distinction
        # short drops the subtype for room (abbreviated headline only)
        assert "Parallel" not in sv.span_html(m, "short")

    def test_type_restating_the_function_collapses_to_its_subtype(self):
        # function "intro" + a proposed type "intro" subtyped "accumulative" -> "Intro · accumulative"
        # (the redundant main type is dropped), NOT "Intro | Intro · accumulative".
        m = sv.parse_span_model(
            json.dumps(
                {
                    "forms": [
                        {
                            "@type": "lcma:Form",
                            "function": {"hasCategory": "fn:intro"},
                            "formalType": {
                                "@type": "lcma:FormalType",
                                "provisional": True,
                                "provisionalTerm": "intro",
                                "sub": "type:accumulative",
                            },
                        }
                    ]
                }
            )
        )
        assert m.secondary_full == "Intro" and m.secondary_sub == "Accumulative"
        out = sv.span_html(m, "full")
        assert "Accumulative" in out
        assert (
            "| Intro" not in out
        )  # the restated main type is not shown as a peer channel
        # tooltip likewise shows the subtype, not the doubled main
        tip = sv.span_tooltip(m)
        assert "Accumulative" in tip and "Intro | Intro" not in tip

    def test_med_collapses_extra_channels_to_one_line(self):
        m = sv.parse_span_model(_named_jsonld())
        med = sv.span_html(m, "med")
        assert "Theme A" in med and "Basic idea" in med
        # material/attrs/refs are present but condensed (the ref string survives)
        assert "Verse" in med
