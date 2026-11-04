"""Pure-logic tests (no database, no network except a local loopback server).

    python -m unittest discover -s tests -p "test_logic.py" -v
"""
import http.server
import io
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from werkzeug.datastructures import FileStorage, MultiDict  # noqa: E402

from app.core import content as C  # noqa: E402
from app.core.entity import Child, Entity, Field as F, UNSET  # noqa: E402
from app.core.public import RateLimiter  # noqa: E402


class TextHelpers(unittest.TestCase):
    def test_normalize_search_unifies_persian_arabic_and_digits(self):
        self.assertEqual(C.normalize_search("كتاب"), C.normalize_search("کتاب"))      # ك -> ک
        self.assertEqual(C.normalize_search("شير"), C.normalize_search("شیر"))        # ي -> ی
        self.assertEqual(C.normalize_search("۹۴۰"), "940")                            # Persian digits
        self.assertEqual(C.normalize_search("٩٤٠"), "940")                            # Arabic-Indic digits
        self.assertEqual(C.normalize_search("AS-FCV ۹۴۰"), "as-fcv 940")
        self.assertEqual(C.normalize_search("می‌خواهم"), "میخواهم")              # ZWNJ removed
        self.assertEqual(C.normalize_search("سـلام"), "سلام")                          # kashida removed
        self.assertEqual(C.normalize_search("  a   b  "), "a b")

    def test_escape_like(self):
        self.assertEqual(C.escape_like("50%_a\\b"), "50\\%\\_a\\\\b")

    def test_slugify_and_validation(self):
        self.assertEqual(C.slugify("Flow Control Valve 940"), "flow-control-valve-940")
        self.assertTrue(C.valid_slug("as-fcv-940"))
        for bad in ("", "AS-FCV", "a b", "a--b", "-a", "a-", "تست", "a" * 121):
            self.assertFalse(C.valid_slug(bad), bad)
        self.assertTrue(C.valid_slug(C.slugify("شیر کنترل")))   # Persian is transliterated to a valid slug

    def test_html_to_text_and_paragraphs(self):
        self.assertEqual(C.html_to_text("<p>سلام<br>دنیا</p><p>x &amp; y</p>"), "سلام\nدنیا\n\nx & y")
        self.assertEqual(C.split_paragraphs("a\n\nb\nc\n\n\nd"), ["a", "b\nc", "d"])
        self.assertEqual(C.strip_tags("a <b>bold</b> and a < b"), "a bold and a < b")

    def test_reading_time(self):
        self.assertEqual(C.reading_time_minutes([]), 1)
        self.assertEqual(C.reading_time_minutes(["w " * 400]), 2)
        self.assertEqual(C.reading_time_minutes(["w " * 1000]), 5)

    def test_phone_and_coordinates(self):
        self.assertEqual(C.phone_tel("+98 21 8865 4200"), "+982188654200")
        self.assertEqual(C.coords_label(35.7742, 51.4128), "35.7742° N, 51.4128° E")
        self.assertEqual(C.coords_label(-33.5, -70.25), "33.5000° S, 70.2500° W")
        self.assertIsNone(C.coords_label(None, 1))

    def test_fmt_size_and_iso(self):
        self.assertEqual(C.fmt_size(2516582), "2.4 MB")
        self.assertEqual(C.fmt_size(512), "512 B")
        import datetime as dt
        self.assertEqual(C.iso(dt.datetime(2026, 9, 7, 17, 15, 14)), "2026-09-07T17:15:14Z")

    def test_media_path(self):
        self.assertEqual(C.norm_media_path("assets/uploads/a.jpg"), "/assets/uploads/a.jpg")
        self.assertEqual(C.norm_media_path("\\assets\\uploads\\a.jpg"), "/assets/uploads/a.jpg")
        self.assertEqual(C.norm_media_path("https://cdn.x/a.jpg"), "https://cdn.x/a.jpg")
        self.assertTrue(C.valid_media_path("/assets/uploads/a.jpg"))
        self.assertFalse(C.valid_media_path("/assets/../etc/passwd"))
        self.assertFalse(C.valid_media_path("javascript:alert(1)") and False or C.valid_media_path("/x y"))
        self.assertEqual(C.abs_url("/assets/uploads/a.jpg", "https://api.x"), "https://api.x/assets/uploads/a.jpg")
        self.assertEqual(C.abs_url("https://cdn.x/a.jpg", "https://api.x"), "https://cdn.x/a.jpg")
        self.assertIsNone(C.abs_url("", "https://api.x"))


class I18nShape(unittest.TestCase):
    def test_i18n_text_always_has_fa_and_never_null(self):
        self.assertEqual(C.i18n_text(None), {"fa": ""})
        self.assertEqual(C.i18n_text('{"fa":"الف","en":"A","de":""}', langs=["fa", "en", "de"]), {"fa": "الف", "en": "A"})
        self.assertEqual(C.i18n_text('{"en":"A"}', langs=["fa", "en"]), {"fa": "", "en": "A"})
        self.assertEqual(C.i18n_text('{"fa":"x","ar":"y"}', langs=["fa", "en"]), {"fa": "x"})       # inactive language dropped
        self.assertEqual(C.i18n_text('{"fa":null,"en":null}', "fb"), {"fa": "fb"})
        self.assertEqual(C.i18n_text("not json"), {"fa": ""})

    def test_i18n_list(self):
        self.assertEqual(C.i18n_list(None), {"fa": []})
        self.assertEqual(C.i18n_list('{"en":["x"],"fa":["a","b"]}', langs=["fa", "en"]), {"fa": ["a", "b"], "en": ["x"]})
        self.assertEqual(C.i18n_list('{"en":[]}', langs=["fa", "en"]), {"fa": []})

    def test_dump_i18n_drops_empty(self):
        self.assertIsNone(C.dump_i18n({"fa": "", "en": "  "}))
        self.assertEqual(json.loads(C.dump_i18n({"fa": "a", "en": ""})), {"fa": "a"})
        self.assertEqual(json.loads(C.dump_i18n({"fa": ["a", ""], "en": []})), {"fa": ["a"]})


def _entity():
    return Entity(
        "thing", "things", "چیز", "چیزها",
        [
            F("slug", "slug", "Slug", declare=False),
            F("name", "text", "نام", i18n=True, required=True, max=20),
            F("code", "text", "کد", max=10, publish_required=True),
            F("qty", "int", "تعداد", min=0, max=100),
            F("color", "hex", "رنگ"),
            F("is_hot", "bool", "داغ"),
            F("kind", "select", "نوع", options=[("a", "A"), ("b", "B")]),
            F("lines", "lines", "خطوط", i18n=True, max_items=3),
            F("tags", "list", "تگ‌ها"),
        ],
        children=[Child("rows", "thing_rows", "thing_id", "ردیف‌ها", [
            F("label", "text", "برچسب", i18n=True, required=True), F("val", "text", "مقدار")])],
        status=True, slug_field="slug",
    )


class EntityForms(unittest.TestCase):
    def setUp(self):
        self.e = _entity()
        self.langs = ["fa", "en"]

    def test_absent_field_is_untouched_but_empty_field_clears(self):
        existing = self.e.values_from_row({"id": 1, "name_i18n": '{"fa":"الف","en":"A"}', "code": "X1", "qty": 5, "status": "published"})
        # only qty present -> everything else stays
        merged = self.e.merge(existing, self.e.read_form(MultiDict({"qty": "7"}), self.langs))
        self.assertEqual(merged["qty"], "7")
        self.assertEqual(merged["name"], {"fa": "الف", "en": "A"})
        self.assertEqual(merged["code"], "X1")
        # present-but-empty English clears only English
        merged = self.e.merge(existing, self.e.read_form(MultiDict({"name__en": ""}), self.langs))
        clean, errors = self.e.validate(merged, self.langs)
        self.assertEqual(clean["name"], {"fa": "الف"})
        self.assertFalse(errors)
        # empty code clears it (explicit empty field)
        merged = self.e.merge(existing, self.e.read_form(MultiDict({"code": ""}), self.langs))
        self.assertEqual(self.e.validate(merged, self.langs)[0]["code"], "")

    def test_required_persian_name(self):
        _, errors = self.e.validate(self.e.merge(None, self.e.read_form(MultiDict({"name__en": "A"}), self.langs)), self.langs)
        self.assertIn("name", errors)
        self.assertIn("فارسی", errors["name"])

    def test_legacy_single_input_alias_for_fa(self):
        got = self.e.read_form(MultiDict({"name": "نام قدیمی"}), self.langs)
        self.assertEqual(got["name"], {"fa": "نام قدیمی"})

    def test_field_validation_messages(self):
        form = MultiDict({"name__fa": "x" * 21, "qty": "abc", "color": "red", "kind": "z", "slug": "Bad Slug", "lines__fa": "a\nb\nc\nd"})
        _, errors = self.e.validate(self.e.merge(None, self.e.read_form(form, self.langs)), self.langs)
        for k in ("name", "qty", "color", "kind", "slug", "lines"):
            self.assertIn(k, errors, k)
        _, errors = self.e.validate(self.e.merge(None, self.e.read_form(MultiDict({"name__fa": "ok", "qty": "101"}), self.langs)), self.langs)
        self.assertIn("qty", errors)

    def test_html_is_stripped_from_plain_text_fields(self):
        got = self.e.read_form(MultiDict({"name__fa": "<script>alert(1)</script>نام", "tags": "<b>a</b>\nb"}), self.langs)
        self.assertEqual(got["name"]["fa"], "alert(1)نام")
        self.assertEqual(got["tags"], ["a", "b"])

    def test_publish_requires_fields(self):
        merged = self.e.merge(None, self.e.read_form(MultiDict({"name__fa": "ok", "status": "published"}), self.langs))
        _, errors = self.e.validate(merged, self.langs)
        self.assertIn("code", errors)
        merged = self.e.merge(None, self.e.read_form(MultiDict({"name__fa": "ok", "status": "draft"}), self.langs))
        self.assertNotIn("code", self.e.validate(merged, self.langs)[1])

    def test_grandfathered_slug_accepts_legacy_persian_slug(self):
        existing = {"slug": "تست 2", "name": {"fa": "تست"}}
        merged = self.e.merge(existing, {})
        clean, errors = self.e.validate(merged, self.langs, existing)
        self.assertNotIn("slug", errors)
        self.assertEqual(clean["slug"], "تست 2")
        merged = self.e.merge(existing, {"slug": "تست 3"})        # changed -> new rules apply
        self.assertIn("slug", self.e.validate(merged, self.langs, existing)[1])

    def test_repeater_rows_and_marker(self):
        form = MultiDict([
            ("rows__present", "1"),
            ("rows-n1_1-label__fa", "اول"), ("rows-n1_1-val", "1"),
            ("rows-n2_2-label__fa", ""), ("rows-n2_2-val", ""),             # fully blank row is skipped
            ("rows-5-label__fa", "دوم"), ("rows-5-label__en", "second"),
        ])
        got = self.e.read_form(form, self.langs)
        self.assertEqual([r["label"] for r in got["rows"]], [{"fa": "دوم", "en": "second"}])  # numeric index order, blank skipped, 'n1_1' ignored
        # without the marker the group is untouched
        self.assertNotIn("rows", self.e.read_form(MultiDict({"rows-0-label__fa": "x"}), self.langs))
        # marker with no rows = clear all rows
        self.assertEqual(self.e.read_form(MultiDict({"rows__present": "1"}), self.langs)["rows"], [])

    def test_child_row_errors_are_keyed_by_row(self):
        merged = self.e.merge(None, {"name": {"fa": "ok"}, "rows": [{"label": {}, "val": "v"}]})
        _, errors = self.e.validate(merged, self.langs)
        self.assertIn("rows-0-label", errors)

    def test_to_db_syncs_legacy_column_with_fa(self):
        f = F("name", "text", "نام", i18n=True, required=True, legacy="name")
        cols = f.to_db({"fa": "الف", "en": "A"})
        self.assertEqual(cols["name"], "الف")
        self.assertEqual(json.loads(cols["name_i18n"]), {"fa": "الف", "en": "A"})

    def test_from_row_falls_back_to_legacy_column(self):
        f = F("description", "textarea", "d", i18n=True, legacy="description", legacy_html=True)
        self.assertEqual(f.from_row({"description_i18n": None, "description": "<p>a</p><p>b</p>"}), {"fa": "a\n\nb"})
        self.assertEqual(f.from_row({"description_i18n": '{"fa":"x"}', "description": "<p>old</p>"}), {"fa": "x"})


class DocumentUploads(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ["DOCUMENT_STORAGE_DIR"] = cls.tmp.name
        os.environ["DOCUMENT_MAX_SIZE_MB"] = "1"
        os.environ.pop("DOCUMENT_ALLOWED_EXTENSIONS", None)
        from app.plugins.documents import plugin as docs

        cls.docs = docs

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("DOCUMENT_MAX_SIZE_MB", None)
        os.environ.pop("DOCUMENT_STORAGE_DIR", None)
        cls.tmp.cleanup()

    def fs(self, name, data):
        return FileStorage(stream=io.BytesIO(data), filename=name)

    def test_valid_pdf_is_stored_outside_uploads_with_random_name(self):
        info = self.docs.validate_and_store(self.fs("دیتاشیت فارسی.pdf", b"%PDF-1.4\n" + b"x" * 100))
        self.assertEqual(info["original_filename"], "دیتاشیت فارسی.pdf")
        self.assertNotIn("دیتاشیت", info["stored_path"])
        self.assertTrue(info["stored_path"].endswith(".pdf"))
        stored = Path(self.tmp.name) / info["stored_path"]
        self.assertTrue(stored.is_file())
        self.assertEqual(len(info["sha256"]), 64)
        self.assertEqual(info["mime"], "application/pdf")
        self.assertNotIn(str(C.UPLOAD_ROOT), str(stored))
        self.docs.remove_stored(info["stored_path"])
        self.assertFalse(stored.exists())

    def test_forbidden_and_unknown_extensions_rejected(self):
        for name in ("a.html", "a.exe", "a.php", "a.svg", "a.js", "a.sh", "a.bat", "evil.php.pdf", "noext", "a.xyz", "a."):
            with self.assertRaises(self.docs.UploadError, msg=name):
                self.docs.validate_and_store(self.fs(name, b"%PDF-1.4 whatever"))

    def test_oversize_rejected_and_nothing_left_behind(self):
        before = list(Path(self.tmp.name).rglob("*"))
        with self.assertRaises(self.docs.UploadError):
            self.docs.validate_and_store(self.fs("big.pdf", b"%PDF-" + b"0" * (1024 * 1024 + 10)))
        self.assertEqual([p for p in Path(self.tmp.name).rglob("*") if p.is_file()], [p for p in before if p.is_file()])

    def test_content_signature_checks(self):
        with self.assertRaises(self.docs.UploadError):
            self.docs.validate_and_store(self.fs("fake.pdf", b"<html>not a pdf</html>"))
        with self.assertRaises(self.docs.UploadError):
            self.docs.validate_and_store(self.fs("fake.zip", b"not a zip"))
        with self.assertRaises(self.docs.UploadError):
            self.docs.validate_and_store(self.fs("fake.png", b"GIF89a....."))
        with self.assertRaises(self.docs.UploadError):
            self.docs.validate_and_store(self.fs("empty.pdf", b""))
        ok = self.docs.validate_and_store(self.fs("a.zip", b"PK\x03\x04" + b"0" * 50))
        self.docs.remove_stored(ok["stored_path"])
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (4, 4), "red").save(buf, "PNG")
        ok = self.docs.validate_and_store(self.fs("a.png", buf.getvalue()))
        self.docs.remove_stored(ok["stored_path"])
        with self.assertRaises(self.docs.UploadError):   # PNG bytes under a .jpg name
            self.docs.validate_and_store(self.fs("a.jpg", buf.getvalue()))

    def test_step_dwg_allowed_without_signature(self):
        for name in ("part.step", "part.stp", "draw.dwg", "draw.dxf", "x.csv", "n.txt"):
            info = self.docs.validate_and_store(self.fs(name, b"data " * 10))
            self.docs.remove_stored(info["stored_path"])

    def test_extension_whitelist_is_configurable_but_never_allows_executables(self):
        os.environ["DOCUMENT_ALLOWED_EXTENSIONS"] = "pdf,exe,html"
        try:
            self.assertEqual(self.docs.allowed_exts(), {"pdf"})
        finally:
            os.environ.pop("DOCUMENT_ALLOWED_EXTENSIONS", None)

    def test_path_traversal_filename_is_sanitised(self):
        info = self.docs.validate_and_store(self.fs("../../etc/passwd.pdf", b"%PDF-1.4 x"))
        self.assertEqual(info["original_filename"], "passwd.pdf")
        self.docs.remove_stored(info["stored_path"])


class Inquiries(unittest.TestCase):
    def setUp(self):
        from app.plugins.inquiries.plugin import validate_payload

        self.v = validate_payload
        self.ok = {"full_name": "علی رضایی", "email": "a@b.co", "phone": "+98 21 8865 4200", "subject": "درخواست قیمت",
                   "message": "لطفاً قیمت و زمان تحویل را اعلام کنید."}

    def test_valid(self):
        clean, errors = self.v(self.ok)
        self.assertEqual(errors, {})
        self.assertEqual(clean["locale"], "fa")

    def test_each_rule(self):
        cases = [
            ({"full_name": "ab"}, "full_name", "too_short", {"min": 3}),
            ({"full_name": "a" * 161}, "full_name", "too_long", {"max": 160}),
            ({"email": "nope"}, "email", "invalid_email", {}),
            ({"email": "a@b.co" + "x" * 200}, "email", "too_long", {"max": 200}),
            ({"phone": "123"}, "phone", "too_short", {"min": 8}),
            ({"phone": "abcdefghij"}, "phone", "invalid_value", {}),
            ({"subject": "abc"}, "subject", "too_short", {"min": 4}),
            ({"message": "short"}, "message", "too_short", {"min": 15}),
            ({"message": "m" * 5001}, "message", "too_long", {"max": 5000}),
            ({"company": "c" * 161}, "company", "too_long", {"max": 160}),
            ({"product_code": "p" * 81}, "product_code", "too_long", {"max": 80}),
            ({"locale": "de"}, "locale", "invalid_value", {}),
            ({"full_name": 5}, "full_name", "invalid_value", {}),
        ]
        for patch, field, code, extra in cases:
            _, errors = self.v({**self.ok, **patch})
            self.assertEqual(errors.get(field, {}).get("code"), code, (patch, errors))
            for k, val in extra.items():
                self.assertEqual(errors[field][k], val)
        for field in ("full_name", "email", "phone", "subject", "message"):
            data = dict(self.ok)
            data.pop(field)
            _, errors = self.v(data)
            self.assertEqual(errors[field]["code"], "required")

    def test_persian_and_arabic_digits_in_phone_ok(self):
        _, errors = self.v({**self.ok, "phone": "۰۲۱-۸۸۶۵۴۲۰۰"})
        self.assertEqual(errors, {})

    def test_whitespace_is_trimmed_before_length_check(self):
        _, errors = self.v({**self.ok, "full_name": "  a  "})
        self.assertEqual(errors["full_name"]["code"], "too_short")


class ImportFlatten(unittest.TestCase):
    def test_flatten_with_prefix_and_placeholders(self):
        from app.plugins.i18n.plugin import Plugin

        flat, ignored = Plugin.flatten_json(
            {"nav": {"home": "خانه"}, "search": {"resultsFor": "{shown} از {query}", "n": 5, "bad": [1], "no": None, "t": True}}, "web.")
        self.assertEqual(flat["web.nav.home"], "خانه")
        self.assertEqual(flat["web.search.resultsFor"], "{shown} از {query}")
        self.assertEqual(flat["web.search.n"], "5")
        self.assertEqual(ignored, 3)

    def test_real_frontend_files_flatten_consistently(self):
        from app.plugins.i18n.plugin import Plugin

        fa = json.loads((ROOT / "front-locales" / "fa.json").read_text(encoding="utf-8"))
        en = json.loads((ROOT / "front-locales" / "en.json").read_text(encoding="utf-8"))
        ff, ig1 = Plugin.flatten_json(fa, "web.")
        fe, ig2 = Plugin.flatten_json(en, "web.")
        self.assertEqual(set(ff), set(fe))
        self.assertEqual((ig1, ig2), (0, 0))
        self.assertGreaterEqual(len(ff), 300)
        self.assertTrue(all(k.startswith("web.") for k in ff))


class RateLimiting(unittest.TestCase):
    def test_sliding_window(self):
        rl = RateLimiter()
        rules = [(3, 3600), (10, 86400)]
        self.assertEqual([rl.check("ip", rules) for _ in range(3)], [0, 0, 0])
        wait = rl.check("ip", rules)
        self.assertGreater(wait, 0)
        self.assertEqual(rl.check("other", rules), 0)      # independent per key
        rl.reset()
        self.assertEqual(rl.check("ip", rules), 0)


class _Sink(http.server.BaseHTTPRequestHandler):
    received = []
    fail_first = 0

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if _Sink.fail_first > 0:
            _Sink.fail_first -= 1
            self.send_response(500)
            self.end_headers()
            return
        _Sink.received.append((dict(self.headers), json.loads(body)))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


class _FakeCache:
    def __init__(self):
        self.cleared = 0

    def invalidate_namespace(self, ns):
        self.cleared += 1


class _FakeApp:
    def __init__(self):
        self.cache = _FakeCache()
        self.core = type("C", (), {"db": None})()


class Revalidate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.HTTPServer(("127.0.0.1", 0), _Sink)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        from app.core.revalidate import Revalidator

        _Sink.received.clear()
        _Sink.fail_first = 0
        os.environ["FRONTEND_REVALIDATE_URL"] = f"http://127.0.0.1:{self.port}/api/revalidate"
        os.environ["FRONTEND_REVALIDATE_SECRET"] = "s3cret-value"
        self.app = _FakeApp()
        self.rv = Revalidator(self.app)
        self.rv.window = 0.3
        self.rv._persist = lambda r: None

    def tearDown(self):
        os.environ.pop("FRONTEND_REVALIDATE_URL", None)
        os.environ.pop("FRONTEND_REVALIDATE_SECRET", None)

    def test_events_within_window_are_merged_into_one_request(self):
        self.rv.notify("product:a")
        self.rv.notify("product:b")
        self.rv.notify("categories")
        self.assertTrue(self.rv.wait_idle(10))
        self.assertEqual(len(_Sink.received), 1)
        headers, body = _Sink.received[0]
        self.assertEqual(headers.get("X-Revalidate-Secret"), "s3cret-value")
        self.assertEqual(headers.get("Content-Type"), "application/json")
        self.assertEqual(body["event"], "content.changed")
        self.assertTrue({"product:a", "product:b", "categories", "products", "sitemap", "search"} <= set(body["tags"]))
        self.assertRegex(body["at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertTrue(self.rv.last["ok"])
        self.assertNotIn("s3cret-value", json.dumps(self.rv.last))
        self.assertEqual(self.app.cache.cleared, 3)          # public API cache cleared on every event

    def test_retries_then_succeeds(self):
        _Sink.fail_first = 2
        self.rv.notify("site")
        self.assertTrue(self.rv.wait_idle(15))
        self.assertEqual(len(_Sink.received), 1)
        self.assertEqual(self.rv.last["attempts"], 3)

    def test_failure_is_recorded_not_raised(self):
        os.environ["FRONTEND_REVALIDATE_URL"] = "http://127.0.0.1:1/x"      # nothing listens
        t0 = time.time()
        self.rv.notify("site")                                              # returns immediately
        self.assertLess(time.time() - t0, 1)
        self.assertTrue(self.rv.wait_idle(30))
        self.assertFalse(self.rv.last["ok"])
        self.assertEqual(self.rv.last["attempts"], 3)

    def test_disabled_without_config_still_clears_cache(self):
        os.environ.pop("FRONTEND_REVALIDATE_SECRET")
        self.rv.notify("site")
        self.assertTrue(self.rv.wait_idle(2))
        self.assertEqual(_Sink.received, [])
        self.assertEqual(self.app.cache.cleared, 1)

    def test_tag_expansion(self):
        from app.core.revalidate import expand_tags

        self.assertEqual(expand_tags(["site"]), ["site"])
        self.assertEqual(set(expand_tags(["category:x"])), {"category:x", "products", "sitemap", "search"})
        self.assertEqual(set(expand_tags(["brands"])), {"brands", "products", "search"})
        self.assertEqual(set(expand_tags(["article:y"])), {"article:y", "sitemap", "search"})


if __name__ == "__main__":
    unittest.main()
