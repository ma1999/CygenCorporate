"""documents plugin — downloadable files (PDF/STEP/DWG/...) owned by a product
or a company certification (spec 6.4.6).

A *document* = i18n title + type + revision + one file per language.
Files are validated (extension allow-list, size cap, content signature),
stored OUTSIDE ``uploads/`` under ``storage/documents/<yyyy>/<uuid>.<ext>``
(random name; the original file name lives only in the DB) and are served
only through ``GET /api/public/documents/<id>/download``.

Owners register themselves with :func:`register_owner` (products,
company certifications), so this plugin has no knowledge of either table.
"""
from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path

from flask import Blueprint, abort, current_app, request, send_file

from app.core import content as C
from app.core.base_plugin import BasePlugin
from app.core.admin_api import api_route, invalid, page_route, reply
from app.core.entity import get_langs
from app.core.public import ApiError, not_found, public_blueprint

ROOT_DIR = C.ROOT_DIR
DOC_TYPES = [
    ("datasheet", "دیتاشیت"), ("manual", "راهنما/دفترچه"), ("certificate", "گواهینامه"),
    ("cad", "نقشه/CAD"), ("brochure", "بروشور"), ("other", "سایر"),
]
DEFAULT_ALLOWED = "pdf,zip,step,stp,igs,iges,dwg,dxf,doc,docx,xls,xlsx,ppt,pptx,csv,txt,png,jpg,jpeg,webp"
FORBIDDEN = {
    "html", "htm", "xhtml", "js", "mjs", "cjs", "php", "phtml", "py", "pyc", "rb", "pl", "sh", "bash",
    "bat", "cmd", "com", "exe", "dll", "msi", "scr", "vbs", "ps1", "jar", "svg", "swf", "asp", "aspx", "jsp", "cgi",
}
EXTRA_MIME = {
    "step": "model/step", "stp": "model/step", "igs": "model/iges", "iges": "model/iges",
    "dwg": "image/vnd.dwg", "dxf": "image/vnd.dxf", "csv": "text/csv", "txt": "text/plain",
    "zip": "application/zip", "webp": "image/webp",
}
IMAGE_EXT = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "webp": "WEBP"}
ZIP_LIKE = {"zip", "docx", "xlsx", "pptx"}
INLINE_OK = {"pdf", "png", "jpg", "jpeg", "webp"}

OWNERS: dict = {}


def register_owner(app, owner_type: str, *, label: str, title, visible, tags, back, touch=None):
    """``title(db, id) -> str|None`` · ``visible(db, ids) -> set(ids)`` (publicly
    visible owners) · ``tags(db, id) -> [revalidate tags]`` · ``back(id) -> admin
    url`` · ``touch(db, id)`` bumps the owner's updated_at."""
    OWNERS[owner_type] = {"label": label, "title": title, "visible": visible, "tags": tags, "back": back, "touch": touch}


def allowed_exts() -> set:
    raw = os.getenv("DOCUMENT_ALLOWED_EXTENSIONS") or DEFAULT_ALLOWED
    return {e.strip().lower().lstrip(".") for e in raw.split(",") if e.strip()} - FORBIDDEN


def max_bytes() -> int:
    try:
        mb = float(os.getenv("DOCUMENT_MAX_SIZE_MB", "50") or 50)
    except ValueError:
        mb = 50
    return int(max(mb, 0.001) * 1024 * 1024)


def storage_root() -> Path:
    raw = os.getenv("DOCUMENT_STORAGE_DIR") or "storage/documents"
    p = Path(raw)
    return p if p.is_absolute() else ROOT_DIR / p


def _dir_size(p: Path) -> int:
    total = 0
    for dirpath, _d, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def quota_bytes() -> int:
    """``ASSETS_DIR_Max_Size`` (GB) caps uploads/ + documents storage together."""
    try:
        gb = float(os.getenv("ASSETS_DIR_Max_Size", "0") or 0)
    except ValueError:
        gb = 0
    return int(gb * 1024 ** 3)


def safe_filename(name: str) -> str:
    name = os.path.basename((name or "").replace("\\", "/"))
    name = re.sub(r"[\x00-\x1f\x7f/\\:*?\"<>|]", "_", name).strip(" .")
    return name[:200] or "file"


class UploadError(Exception):
    pass


def validate_and_store(fs) -> dict:
    """Validate an uploaded ``FileStorage`` and write it to the storage dir.

    Raises :class:`UploadError` (Persian message) and leaves nothing behind
    on failure."""
    original = safe_filename(fs.filename or "")
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if not ext:
        raise UploadError("فایل باید پسوند داشته باشد")
    if ext in FORBIDDEN:
        raise UploadError(f"پسوند «{ext}» مجاز نیست (فایل اجرایی/اسکریپت)")
    # every suffix of a multi-dot name must be non-executable (a.php.pdf)
    for part in original.lower().split(".")[1:]:
        if part in FORBIDDEN:
            raise UploadError(f"نام فایل شامل پسوند ممنوع «{part}» است")
    if ext not in allowed_exts():
        raise UploadError(f"پسوند «{ext}» مجاز نیست. مجاز: {', '.join(sorted(allowed_exts()))}")

    limit = max_bytes()
    year = datetime.utcnow().strftime("%Y")
    dest_dir = storage_root() / year
    dest_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}.{ext}"
    path = dest_dir / stored
    h = hashlib.sha256()
    size = 0
    head = b""
    stream = fs.stream
    try:
        with open(path, "wb") as out:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                if not head:
                    head = chunk[:16]
                size += len(chunk)
                if size > limit:
                    raise UploadError(f"حجم فایل بیش از {limit // (1024 * 1024)} مگابایت است")
                h.update(chunk)
                out.write(chunk)
        if size == 0:
            raise UploadError("فایل خالی است")
        quota = quota_bytes()
        if quota:
            used = _dir_size(C.UPLOAD_ROOT) + _dir_size(storage_root())
            if used > quota:
                raise UploadError("سهمیه‌ی فضای ذخیره‌سازی پر شده است")
        if ext == "pdf" and not head.startswith(b"%PDF-"):
            raise UploadError("محتوای فایل PDF معتبر نیست (امضای %PDF- یافت نشد)")
        if ext in ZIP_LIKE and not (head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06")):
            raise UploadError(f"محتوای فایل {ext.upper()} معتبر نیست (امضای ZIP یافت نشد)")
        if ext in IMAGE_EXT:
            try:
                from PIL import Image

                with Image.open(path) as im:
                    fmt = im.format
                    im.verify()
                if fmt != IMAGE_EXT[ext]:
                    raise UploadError(f"محتوای تصویر با پسوند «{ext}» هم‌خوانی ندارد")
            except UploadError:
                raise
            except Exception:
                raise UploadError("فایل تصویری معتبر نیست")
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    mime = EXTRA_MIME.get(ext) or mimetypes.guess_type(original)[0] or "application/octet-stream"
    return {
        "stored_path": f"{year}/{stored}", "original_filename": original, "mime": mime,
        "size_bytes": size, "sha256": h.hexdigest(), "ext": ext,
    }


def remove_stored(rel: str):
    try:
        p = (storage_root() / rel).resolve()
        p.relative_to(storage_root().resolve())
        p.unlink()
    except (OSError, ValueError):
        pass


class Plugin(BasePlugin):
    name = "documents"
    auto_enable = True
    output_type = "json"
    # no dashboard tile: documents are managed from their owner's page
    admin_entry = {"title": "اسناد", "icon": "📄", "url": None, "order": 90}

    def declare_schema(self, schema):
        schema.register_table("documents", {
            "id": "INT AUTO_INCREMENT PRIMARY KEY",
            "owner_type": "VARCHAR(20) NOT NULL",
            "owner_id": "INT NOT NULL",
            "doc_type": "VARCHAR(20) NOT NULL DEFAULT 'other'",
            "title_i18n": "LONGTEXT NULL",
            "revision": "VARCHAR(32) NULL",
            "sort_order": "INT NOT NULL DEFAULT 0",
            "is_public": "TINYINT(1) NOT NULL DEFAULT 1",
            "created_at": "DATETIME NULL",
            "updated_at": "DATETIME NULL",
        })
        schema.register_table("document_files", {
            "id": "INT AUTO_INCREMENT PRIMARY KEY",
            "document_id": "INT NOT NULL",
            "lang_code": "VARCHAR(8) NOT NULL",
            "stored_path": "VARCHAR(500) NOT NULL",
            "original_filename": "VARCHAR(255) NOT NULL",
            "mime": "VARCHAR(100) NULL",
            "size_bytes": "BIGINT NOT NULL DEFAULT 0",
            "sha256": "CHAR(64) NULL",
            "format_label": "VARCHAR(40) NULL",
            "download_count": "INT NOT NULL DEFAULT 0",
            "created_at": "DATETIME NULL",
        })

    def maybe_run_migration(self):
        from app.core import migrate

        def go(cur):
            migrate.ensure_index(cur, "documents", "idx_doc_owner", "owner_type, owner_id")
            migrate.ensure_index(cur, "document_files", "uniq_doc_lang", "document_id, lang_code", unique=True)

        migrate.run(self.db, go)

    # ------------------------------------------------------------------ admin
    def register(self):
        db = self.db
        bp = Blueprint("plugin_documents", __name__)

        def owner_or_404(owner_type):
            o = OWNERS.get(owner_type)
            if not o:
                abort(404)
            return o

        async def load_docs(owner_type, owner_id):
            docs = await db.fetch(
                "SELECT * FROM documents WHERE owner_type=%s AND owner_id=%s ORDER BY sort_order, id", (owner_type, owner_id)
            )
            ids = [d["id"] for d in docs]
            files = {}
            if ids:
                ph = ",".join(["%s"] * len(ids))
                for f in await db.fetch(f"SELECT * FROM document_files WHERE document_id IN ({ph}) ORDER BY id", tuple(ids)):
                    files.setdefault(f["document_id"], {})[f["lang_code"]] = f
            for d in docs:
                d["title"] = C.parse_i18n(d["title_i18n"])
                d["files"] = files.get(d["id"], {})
            return docs

        page_route(bp, "/admin/documents/<owner_type>/<int:owner_id>", "admin_page", "documents", "اسناد", "pages-documents")

        def public_doc(d):
            return {
                "id": d["id"], "doc_type": d["doc_type"], "title": d["title"], "revision": d["revision"],
                "sort_order": d["sort_order"], "is_public": bool(d["is_public"]),
                "files": {code: {"filename": f["original_filename"], "size": f["size_bytes"], "size_label": C.fmt_size(f["size_bytes"]),
                                 "format": f["format_label"], "downloads": f["download_count"]}
                          for code, f in d["files"].items()},
            }

        @api_route(bp, "/api/admin/documents/<owner_type>/<int:owner_id>", "api_page")
        async def api_page(owner_type, owner_id):
            o = OWNERS.get(owner_type)
            if not o:
                raise ApiError(404, "not_found", "نوع مالک ناشناخته است")
            title = await o["title"](db, owner_id)
            if title is None:
                raise ApiError(404, "not_found", "مورد یافت نشد")
            return reply({
                "owner_type": owner_type, "owner_id": owner_id, "owner_title": title, "owner_label": o["label"],
                "back": o["back"](owner_id), "docs": [public_doc(d) for d in await load_docs(owner_type, owner_id)],
                "languages": await get_langs(db), "doc_types": [{"value": t, "label": l} for t, l in DOC_TYPES],
                "max_mb": max_bytes() // (1024 * 1024), "allowed": sorted(allowed_exts()),
            })

        async def read_meta(langs):
            title = {}
            for l in langs:
                v = C.strip_tags((request.form.get(f"title__{l}") or "").strip())
                if v:
                    title[l] = v[:191]
            dtype = request.form.get("type") or "other"
            if dtype not in [t for t, _ in DOC_TYPES]:
                raise UploadError("نوع سند نامعتبر است")
            if not title.get("fa"):
                raise UploadError("عنوان فارسی سند الزامی است")
            rev = C.strip_tags((request.form.get("revision") or "").strip())
            if len(rev) > 32:
                raise UploadError("ویرایش (revision) حداکثر ۳۲ نویسه است")
            try:
                sort = int(request.form.get("sort_order") or 0)
            except ValueError:
                raise UploadError("ترتیب باید عدد باشد")
            pub = (request.form.get("is_public") or "1") in ("1", "true", "on")
            return title, dtype, rev, sort, pub

        def collect_uploads(codes):
            ups = {}
            for l in codes:
                fs = request.files.get(f"file__{l}")
                if fs and fs.filename:
                    ups[l] = fs
            return ups

        async def after_change(owner_type, owner_id):
            o = OWNERS[owner_type]
            if o.get("touch"):
                await o["touch"](db, owner_id)
            self.app.revalidate.notify(*(await o["tags"](db, owner_id)))

        @api_route(bp, "/api/admin/documents/<owner_type>/<int:owner_id>", "api_create", ["POST"])
        async def api_create(owner_type, owner_id):
            o = OWNERS.get(owner_type)
            if not o or await o["title"](db, owner_id) is None:
                raise ApiError(404, "not_found", "مورد یافت نشد")
            langs = [l["code"] for l in await get_langs(db)]
            request.max_content_length = max_bytes() * max(1, len(langs)) + 2 * 1024 * 1024
            stored = []
            try:
                title, dtype, rev, sort, pub = await read_meta(langs)
                ups = collect_uploads(langs)
                if not ups:
                    raise UploadError("حداقل یک فایل (برای یکی از زبان‌ها) لازم است")
                for code, fs in ups.items():
                    stored.append((code, validate_and_store(fs)))
            except UploadError as e:
                for _c, info in stored:
                    remove_stored(info["stored_path"])
                raise invalid({"_": str(e)}, str(e))

            def go(tx):
                did = tx.run(
                    "INSERT INTO documents (owner_type, owner_id, doc_type, title_i18n, revision, sort_order, is_public, created_at, updated_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
                    (owner_type, owner_id, dtype, C.dump_i18n(title), rev or None, sort, 1 if pub else 0),
                )
                for code, info in stored:
                    self._insert_file(tx, did, code, info)

            try:
                await db.transaction(go)
            except Exception:
                for _c, info in stored:
                    remove_stored(info["stored_path"])
                raise
            await after_change(owner_type, owner_id)
            return reply({"docs": [public_doc(d) for d in await load_docs(owner_type, owner_id)]}, 201)

        @api_route(bp, "/api/admin/documents/<int:doc_id>/save", "api_save", ["POST"])
        async def api_save(doc_id):
            doc = await db.fetch("SELECT * FROM documents WHERE id=%s", (doc_id,), one=True)
            if not doc:
                raise ApiError(404, "not_found", "سند یافت نشد")
            owner_type, owner_id = doc["owner_type"], doc["owner_id"]
            langs = [l["code"] for l in await get_langs(db)]
            request.max_content_length = max_bytes() * max(1, len(langs)) + 2 * 1024 * 1024
            existing = {f["lang_code"]: f for f in await db.fetch("SELECT * FROM document_files WHERE document_id=%s", (doc_id,))}
            stored = []
            try:
                title, dtype, rev, sort, pub = await read_meta(langs)
                ups = collect_uploads(langs)
                removes = [l for l in langs if request.form.get(f"remove__{l}") and l in existing and l not in ups]
                remaining = (set(existing) - set(removes)) | set(ups)
                if not remaining:
                    raise UploadError("هر سند باید حداقل یک فایل داشته باشد")
                for code, fs in ups.items():
                    stored.append((code, validate_and_store(fs)))
            except UploadError as e:
                for _c, info in stored:
                    remove_stored(info["stored_path"])
                raise invalid({"_": str(e)}, str(e))
            old_paths = [existing[c]["stored_path"] for c in removes] + [existing[c]["stored_path"] for c, _ in stored if c in existing]

            def go(tx):
                tx.run(
                    "UPDATE documents SET doc_type=%s, title_i18n=%s, revision=%s, sort_order=%s, is_public=%s, updated_at=UTC_TIMESTAMP() WHERE id=%s",
                    (dtype, C.dump_i18n(title), rev or None, sort, 1 if pub else 0, doc_id),
                )
                for c in removes:
                    tx.run("DELETE FROM document_files WHERE document_id=%s AND lang_code=%s", (doc_id, c))
                for code, info in stored:
                    tx.run("DELETE FROM document_files WHERE document_id=%s AND lang_code=%s", (doc_id, code))
                    self._insert_file(tx, doc_id, code, info)

            try:
                await db.transaction(go)
            except Exception:
                for _c, info in stored:
                    remove_stored(info["stored_path"])
                raise
            for rel in old_paths:
                remove_stored(rel)
            await after_change(owner_type, owner_id)
            return reply({"docs": [public_doc(d) for d in await load_docs(owner_type, owner_id)]})

        @api_route(bp, "/api/admin/documents/<int:doc_id>", "api_delete", ["DELETE"])
        async def api_delete(doc_id):
            doc = await db.fetch("SELECT * FROM documents WHERE id=%s", (doc_id,), one=True)
            if not doc:
                raise ApiError(404, "not_found", "سند یافت نشد")
            files = await db.fetch("SELECT stored_path FROM document_files WHERE document_id=%s", (doc_id,))

            def go(tx):
                tx.run("DELETE FROM document_files WHERE document_id=%s", (doc_id,))
                tx.run("DELETE FROM documents WHERE id=%s", (doc_id,))

            await db.transaction(go)
            for f in files:
                remove_stored(f["stored_path"])
            await after_change(doc["owner_type"], doc["owner_id"])
            return reply({"deleted": doc_id})

        self.app.register_blueprint(bp)

        # ---------------- public download ----------------
        pub = public_blueprint("public_documents")

        @pub.route("/documents/<int:doc_id>/download", methods=["GET", "HEAD"])
        async def download(doc_id):
            doc = await db.fetch("SELECT * FROM documents WHERE id=%s AND is_public=1", (doc_id,), one=True)
            if not doc:
                raise not_found("Document not found")
            o = OWNERS.get(doc["owner_type"])
            if not o or doc["owner_id"] not in await o["visible"](db, [doc["owner_id"]]):
                raise not_found("Document not found")
            files = await db.fetch("SELECT * FROM document_files WHERE document_id=%s ORDER BY id", (doc_id,))
            if not files:
                raise not_found("Document has no file")
            lang = (request.args.get("lang") or "").strip().lower()
            by_lang = {f["lang_code"]: f for f in files}
            f = by_lang.get(lang) or by_lang.get("fa") or files[0]
            path = (storage_root() / f["stored_path"]).resolve()
            try:
                path.relative_to(storage_root().resolve())
            except ValueError:
                raise not_found("File not found")
            if not path.is_file():
                raise not_found("File not found")
            ext = f["stored_path"].rsplit(".", 1)[-1].lower()
            inline = (request.args.get("inline") or "").strip() in ("1", "true") and ext in INLINE_OK
            if request.method == "GET" and not request.headers.get("Range"):
                threading.Thread(target=self._bump, args=(f["id"],), daemon=True).start()
            resp = send_file(
                path, mimetype=f["mime"] or "application/octet-stream", as_attachment=not inline,
                download_name=f["original_filename"], conditional=True, max_age=3600,
            )
            resp.headers["X-Content-Type-Options"] = "nosniff"
            resp.headers["Cache-Control"] = "public, max-age=3600"
            return resp

        self.app.register_blueprint(pub)

    @staticmethod
    def _insert_file(tx, did, code, info):
        tx.run(
            "INSERT INTO document_files (document_id, lang_code, stored_path, original_filename, mime, size_bytes, sha256, format_label, created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP())",
            (did, code, info["stored_path"], info["original_filename"], info["mime"], info["size_bytes"], info["sha256"],
             info["ext"].upper()),
        )

    def _bump(self, file_id):
        try:
            conn = self.db._conn()
            try:
                cur = conn.cursor()
                cur.execute("UPDATE document_files SET download_count=download_count+1 WHERE id=%s", (file_id,))
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass

    # ---------------------------------------------------------------- public API helpers
    async def public_documents(self, ctx, owner_type: str, owner_ids: list) -> dict:
        """``{owner_id: [ProductDocument, ...]}`` for public documents only."""
        out = {i: [] for i in owner_ids}
        if not owner_ids:
            return out
        ph = ",".join(["%s"] * len(owner_ids))
        docs = await ctx.db.fetch(
            f"SELECT * FROM documents WHERE owner_type=%s AND is_public=1 AND owner_id IN ({ph}) ORDER BY sort_order, id",
            (owner_type, *owner_ids),
        )
        if not docs:
            return out
        dph = ",".join(["%s"] * len(docs))
        files = await ctx.db.fetch(
            f"SELECT * FROM document_files WHERE document_id IN ({dph}) ORDER BY id", tuple(d["id"] for d in docs)
        )
        by_doc = {}
        for f in files:
            by_doc.setdefault(f["document_id"], []).append(f)
        for d in docs:
            fmap = {}
            for f in by_doc.get(d["id"], []):
                ext = f["stored_path"].rsplit(".", 1)[-1].lower()
                url = f"{ctx.base}/api/public/documents/{d['id']}/download?lang={f['lang_code']}"
                fmap[f["lang_code"]] = {
                    "download_url": url,
                    "view_url": url + "&inline=1" if ext in INLINE_OK else None,
                    "format": f["format_label"] or ext.upper(),
                    "mime": f["mime"] or "application/octet-stream",
                    "size_bytes": int(f["size_bytes"] or 0),
                    "size_label": C.fmt_size(f["size_bytes"]),
                }
            if not fmap:
                continue
            out[d["owner_id"]].append({
                "id": d["id"], "type": d["doc_type"], "title": ctx.text(d["title_i18n"]),
                "revision": d["revision"] or None, "updated_at": ctx.iso(d["updated_at"]), "files": fmap,
            })
        return out
