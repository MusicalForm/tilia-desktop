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
        assert sv.lod_for(200) == "full"
        assert sv.lod_for(199) == "med"
        assert sv.lod_for(104) == "med"
        assert sv.lod_for(103) == "short"
        assert sv.lod_for(48) == "short"
        assert sv.lod_for(47) == "min"
        assert sv.lod_for(0) == "min"


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
    def test_empty_and_garbage_are_none(self):
        assert sv.parse_span_model("") is None
        assert sv.parse_span_model("   ") is None
        assert sv.parse_span_model("not json") is None
        assert sv.parse_span_model("[1,2,3]") is None  # not an object

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
        assert m.primary == "Description"
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
