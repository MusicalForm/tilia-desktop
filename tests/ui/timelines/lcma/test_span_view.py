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


# --- prettify / LOD ------------------------------------------------------------


class TestPrettifyAndLod:
    def test_prettify(self):
        assert sv.prettify("basic_idea") == "Basic idea"
        assert sv.prettify("hybrid1") == "Hybrid 1"
        assert sv.prettify("") == ""

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
        assert m.primary == "Basic idea"
        assert m.secondary == "Period"
        assert m.color == sv.span_color_hex("Basic idea")  # green family
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
        assert m.primary == "Basic idea→Contrasting idea"
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
        assert m.primary == "“Basic idea”"
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
        assert m.primary == "Fortspinnung"
        assert m.flags.standalone is False

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
        assert m.color == sv.span_color_hex("anything unmatched")  # forced grey
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
        full = sv.display_label(m, "full")
        assert "Theme A" in full and "Basic idea" in full and "Period" in full
        # short: headline only + a dot (it carries badges)
        short = sv.display_label(m, "short")
        assert short == "Basic idea •"
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
