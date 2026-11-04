"""Pure-logic tests of the page builder (no database, no network).

    python -m unittest tests.test_page_builder -v
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.plugins.page_builder import layout as L  # noqa: E402

MANIFEST_RAW = {
    "theme": "demo-theme",
    "name": {"fa": "نمونه", "en": "Demo"},
    "section_fields": [{"name": "bg", "type": "color"}, {"name": "padding", "type": "select", "options": ["sm", "lg"], "default": "sm"}],
    "column_fields": [],
    "pages": [{"key": "home", "path": "/", "label": {"fa": "خانه"}}, {"key": "bad key!", "label": "x"}],
    "widgets": [
        {"type": "heading", "label": "Heading", "fields": [
            {"name": "text", "type": "text", "i18n": True, "max": 20},
            {"name": "html", "type": "richtext", "i18n": True},
            {"name": "size", "type": "select", "options": ["sm", "lg"], "default": "sm"},
            {"name": "count", "type": "number", "min": 1, "max": 5, "default": 3},
            {"name": "on", "type": "switch"},
            {"name": "cta", "type": "link", "label_field": True},
            {"name": "photo", "type": "image"},
            {"name": "items", "type": "repeater", "max_rows": 2, "fields": [{"name": "t", "type": "text"}]},
            {"name": "cat", "type": "entity", "entity": "category"},
            {"name": "picks", "type": "entity", "entity": "product", "multiple": True},
        ]},
        {"type": "heading", "label": "duplicate type is dropped", "fields": []},
        {"type": "Bad-Type", "label": "invalid type is dropped", "fields": []},
    ],
}


def manifest():
    m, errors = L.normalize_manifest(json.loads(json.dumps(MANIFEST_RAW)))
    assert m is not None, errors
    return m


def one_widget(settings, type_="heading"):
    return {"sections": [{"columns": [{"widgets": [{"type": type_, "settings": settings}]}]}]}


class ManifestTests(unittest.TestCase):
    def test_invalid_entries_are_dropped_and_reported(self):
        m, errors = L.normalize_manifest(json.loads(json.dumps(MANIFEST_RAW)))
        self.assertEqual([w["type"] for w in m["widgets"]], ["heading"])
        self.assertEqual([p["key"] for p in m["pages"]], ["home"])
        self.assertIn("widgets[1]", errors)
        self.assertIn("widgets[2]", errors)
        self.assertIn("pages[1]", errors)

    def test_theme_id_is_validated(self):
        for bad in ("", "A B", "../x", None, 5):
            m, errors = L.normalize_manifest({"theme": bad, "widgets": []})
            self.assertIsNone(m)
            self.assertIn("theme", errors)
        self.assertIsNone(L.normalize_manifest("nope")[0])

    def test_repeater_nesting_is_limited(self):
        deep = {"name": "a", "type": "repeater", "fields": [{"name": "b", "type": "repeater", "fields": [
            {"name": "c", "type": "repeater", "fields": []}]}]}
        _m, errors = L.normalize_manifest({"theme": "demo-theme", "widgets": [{"type": "wid", "fields": [deep]}]})
        self.assertTrue(any("nest" in v for v in errors.values()))


class SanitizerTests(unittest.TestCase):
    def test_scripts_handlers_and_bad_links_are_removed(self):
        out = L.sanitize_html(
            '<p onclick="x()">a<script>alert(1)</script><style>p{}</style><a href="javascript:alert(1)">l</a>'
            '<a href="/ok" target="_blank" onmouseover="y()">k</a><img src=x onerror=z()><iframe src="//e"></iframe></p>')
        self.assertEqual(out, '<p>a<a>l</a><a href="/ok" target="_blank" rel="noopener noreferrer">k</a></p>')

    def test_text_is_escaped_and_tags_balanced(self):
        self.assertEqual(L.sanitize_html("1 < 2 & <b>bold"), "1 &lt; 2 &amp; <b>bold</b>")

    def test_safe_href(self):
        for ok in ("/a", "#x", "https://e.com/x", "mailto:a@b.c", "tel:+98"):
            self.assertEqual(L.safe_href(ok), ok)
        for bad in ("javascript:alert(1)", "//evil.com", "data:text/html,x", " ", None, 5, "ftp://x"):
            self.assertEqual(L.safe_href(bad), "")


class LayoutTests(unittest.TestCase):
    def test_known_widget_keeps_only_declared_keys_coerced(self):
        lay, errors, unknown = L.validate_layout(one_widget({
            "text": {"fa": "<b>سلام</b>" + "x" * 50, "en": "Hi", "de": "no"}, "size": "xx", "count": 99, "on": 1,
            "cta": {"href": "javascript:x", "new_tab": 1, "label": {"fa": "برو"}}, "photo": "../etc/passwd",
            "items": [{"t": "<i>1</i>"}, {"t": "2"}, {"t": "3"}], "cat": "tools", "evil": "dropped"}), manifest(), ["fa", "en"])
        s = lay["sections"][0]["columns"][0]["widgets"][0]["settings"]
        self.assertEqual(s["text"]["en"], "Hi")
        self.assertNotIn("de", s["text"])                 # language not active
        self.assertEqual(len(s["text"]["fa"]), 20)        # field max
        self.assertNotIn("<b>", s["text"]["fa"])
        self.assertEqual((s["size"], s["count"], s["on"]), ("sm", 5, True))
        self.assertEqual(s["cta"], {"href": "", "new_tab": True, "label": {"fa": "برو"}})
        self.assertEqual(s["photo"], "")
        self.assertEqual(s["items"], [{"t": "1"}, {"t": "2"}])   # max_rows, tags stripped
        self.assertEqual(s["cat"], "tools")
        self.assertNotIn("evil", s)
        self.assertEqual((errors, unknown), ({}, []))

    def test_hand_picked_entities_keep_order_and_drop_junk(self):
        lay, _errors, _unknown = L.validate_layout(one_widget({"picks": ["b-2", "a-1", "<x>", 7, "a b", "c"]}), manifest(), ["fa"])
        self.assertEqual(lay["sections"][0]["columns"][0]["widgets"][0]["settings"]["picks"], ["b-2", "a-1", "c"])
        lay, _e, _u = L.validate_layout(one_widget({"picks": "not-a-list"}), manifest(), ["fa"])
        self.assertEqual(lay["sections"][0]["columns"][0]["widgets"][0]["settings"]["picks"], [])

    def test_unknown_widget_is_kept_not_destroyed(self):
        lay, _e, unknown = L.validate_layout(one_widget({"a": [1, {"b": "<x>"}]}, "from_future"), manifest(), ["fa"])
        w = lay["sections"][0]["columns"][0]["widgets"][0]
        self.assertEqual((w["type"], w["settings"]), ("from_future", {"a": [1, {"b": "<x>"}]}))
        self.assertEqual(unknown, ["from_future"])

    def test_structure_is_normalised(self):
        raw = {"sections": [{"id": "dup", "settings": {"bg": "red;drop", "padding": "lg"}, "columns": [
            {"id": "dup", "span": 99, "widgets": []}, {"span": 0}, {"span": True}, "junk"]}, "junk"]}
        lay, _e, _u = L.validate_layout(raw, manifest(), ["fa"])
        sec = lay["sections"][0]
        self.assertEqual(sec["settings"], {"bg": "", "padding": "lg"})
        self.assertEqual([c["span"] for c in sec["columns"]], [12, 12, 12])
        ids = [sec["id"]] + [c["id"] for c in sec["columns"]]
        self.assertEqual(len(set(ids)), len(ids))           # duplicate ids are regenerated
        self.assertEqual(lay["v"], 1)

    def test_limits(self):
        with self.assertRaises(L.LayoutError):
            L.validate_layout([], manifest(), ["fa"])
        with self.assertRaises(L.LayoutError):
            L.validate_layout({"sections": "x"}, manifest(), ["fa"])
        with self.assertRaises(L.LayoutError):
            L.validate_layout({"sections": [{"columns": []}] * (L.MAX_SECTIONS + 1)}, manifest(), ["fa"])
        with self.assertRaises(L.LayoutError):
            L.validate_layout({"sections": [{"columns": [{"widgets": [{"type": "heading"}] * (L.MAX_WIDGETS + 1)}]}]}, manifest(), ["fa"])
        with self.assertRaises(L.LayoutError):
            L.validate_layout({"sections": [{"columns": [{}] * (L.MAX_COLUMNS + 1)}]}, manifest(), ["fa"])
        with self.assertRaises(L.LayoutError):
            L.validate_layout({"sections": [], "pad": "x" * (L.MAX_LAYOUT_BYTES + 1)}, manifest(), ["fa"])

    def test_validation_is_idempotent(self):
        once, _e, _u = L.validate_layout(one_widget({"text": {"fa": "a"}, "count": 2}), manifest(), ["fa"])
        twice, _e, _u = L.validate_layout(once, manifest(), ["fa"])
        self.assertEqual(once, twice)                        # ids are kept, so publish/draft comparison stays stable


class SlugTests(unittest.TestCase):
    def test_valid_slugs(self):
        self.assertEqual(L.check_slug(" /Landing/Spring-Sale/ "), "landing/spring-sale")

    def test_invalid_and_reserved_slugs(self):
        for bad in ("", None, "a b", "a//b", "-a", "a/b/c/d", "فارسی", "x" * 200, "../etc"):
            with self.assertRaises(L.LayoutError, msg=repr(bad)):
                L.check_slug(bad)
        for reserved in ("products", "admin/x", "api", "home", "news/2024"):
            with self.assertRaises(L.LayoutError, msg=reserved):
                L.check_slug(reserved)



class CommonAndNestingTests(unittest.TestCase):
    def test_common_settings_are_coerced_and_empty_values_dropped(self):
        raw = {"sections": [{"common": {"anim_type": "slide-left", "anim_duration": 99, "parallax": 12, "css_id": "a b<c>", "css_class": "x y;z",
                                        "hide_mobile": True, "hide_tablet": False, "evil": 1, "grad_from": "red;x"},
                             "columns": [{"span_tablet": 6, "span_mobile": 99, "common": {"hover_effect": "lift", "box_radius": "huge"},
                                          "widgets": [{"type": "heading", "common": {"margin_top": -5, "text_align": "center", "loop_effect": "float"}}]}]}]}
        lay, _e, _u = L.validate_layout(raw, manifest(), ["fa"])
        sec = lay["sections"][0]
        self.assertEqual(sec["common"], {"anim_type": "slide-left", "anim_duration": 5, "parallax": 12, "css_id": "ab", "css_class": "x yz", "hide_mobile": True})
        col = sec["columns"][0]
        self.assertEqual((col["span_tablet"], "span_mobile" in col), (6, False))
        self.assertEqual(col["common"], {"hover_effect": "lift"})
        self.assertEqual(col["widgets"][0]["common"], {"margin_top": 0, "text_align": "center", "loop_effect": "float"})

    def test_inner_rows_nest_one_level(self):
        inner = {"type": "inner_row", "columns": [{"span": 6, "widgets": [{"type": "heading", "settings": {"count": 2}}]}, {"span": 6}]}
        lay, _e, unknown = L.validate_layout({"sections": [{"columns": [{"widgets": [inner]}]}]}, manifest(), ["fa"])
        w = lay["sections"][0]["columns"][0]["widgets"][0]
        self.assertEqual((w["type"], len(w["columns"]), w["columns"][0]["widgets"][0]["settings"]["count"]), ("inner_row", 2, 2))
        self.assertEqual(unknown, [])
        too_deep = {"type": "inner_row", "columns": [{"widgets": [{"type": "inner_row", "columns": []}]}]}
        with self.assertRaises(L.LayoutError):
            L.validate_layout({"sections": [{"columns": [{"widgets": [too_deep]}]}]}, manifest(), ["fa"])
        with self.assertRaises(L.LayoutError):
            L.validate_layout({"sections": [{"columns": [{"widgets": [{"type": "inner_row", "columns": [{}] * 7}]}]}]}, manifest(), ["fa"])

    def test_inner_widgets_count_towards_the_widget_cap(self):
        many = {"type": "inner_row", "columns": [{"widgets": [{"type": "heading"}] * L.MAX_WIDGETS}]}
        with self.assertRaises(L.LayoutError):
            L.validate_layout({"sections": [{"columns": [{"widgets": [many, {"type": "heading"}]}]}]}, manifest(), ["fa"])

    def test_header_and_footer_slugs_are_reserved(self):
        for s in ("header", "footer"):
            with self.assertRaises(L.LayoutError):
                L.check_slug(s)


class FactoryLayoutTests(unittest.TestCase):
    def test_factory_layout_in_manifest_keeps_its_widgets(self):
        """Regression: the JSON depth cap once nulled every widget of a manifest page layout (an empty home page was seeded)."""
        raw = json.loads(json.dumps(MANIFEST_RAW))
        raw["pages"][0]["layout"] = {"sections": [{"columns": [{"widgets": [
            {"type": "heading", "settings": {"items": [{"t": "x"}], "text": {"fa": "سلام", "en": "Hi"}}}]}]}]}
        m, _errors = L.normalize_manifest(raw)
        lay, _e, unknown = L.validate_layout(m["pages"][0]["layout"], m, ["fa", "en"])
        w = lay["sections"][0]["columns"][0]["widgets"][0]
        self.assertEqual((w["type"], w["settings"]["text"], w["settings"]["items"]), ("heading", {"fa": "سلام", "en": "Hi"}, [{"t": "x"}]))
        self.assertEqual(unknown, [])


if __name__ == "__main__":
    unittest.main()
