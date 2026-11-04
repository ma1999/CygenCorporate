"""Images plugin — file-manager style media library.

- Root upload dir: <project>/uploads  (served at /assets/uploads/...)
- Folder create, upload into folder, rename, delete (files & folders)
- .txt files editable inline
- Image info: dimensions, size, preview
- Multi-select bulk delete + search by name, extension, date range, size range
"""
import os
import shutil
import time
import base64

from flask import Blueprint, request, send_from_directory

from app.core.base_plugin import BasePlugin
from app.core.admin_api import api_route, body, invalid, page_route, reply
from app.core.public import ApiError
from dotenv import load_dotenv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))   # project root (plugin file is 4 levels deep)
UPLOAD_ROOT = os.path.join(ROOT_DIR, "uploads")
PUBLIC_PREFIX = "assets/uploads"   # web path prefix
load_dotenv(os.path.join(ROOT_DIR, ".env"))
# ASSETS_DIR_Max_Size in GB (e.g. 10 = 10GB, 0.5 = 500MB). 0/empty = unlimited
MAX_SIZE_GB = float(os.getenv("ASSETS_DIR_Max_Size", "0") or 0)
MAX_SIZE_BYTES = int(MAX_SIZE_GB * 1024 * 1024 * 1024)


def _safe_rel(rel: str) -> str:
    """Normalize a relative path and prevent traversal outside uploads/."""
    rel = (rel or "").replace("\\", "/").strip("/")
    if ".." in rel.split("/"):
        raise ValueError("invalid path")
    return rel


def _abs_path(rel: str) -> str:
    rel = _safe_rel(rel)
    p = os.path.abspath(os.path.join(UPLOAD_ROOT, rel))
    if not p.startswith(os.path.abspath(UPLOAD_ROOT)):
        raise ValueError("path escapes uploads root")
    return p


def _fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} TB"


class Plugin(BasePlugin):
    name = "images"
    # enabled by default on a fresh database (the headless frontend needs it);
    # an existing "plugins" row (enabled or not) is never touched
    auto_enable = True

    admin_entry = {
        "title": "تصاویر",
        "icon": "🖼️",
        "url": "/admin/images",
        "order": 12,
    }
    output_type = "html"

    # ---------------- cache ----------------
    CACHE_NS = "images"

    @property
    def _cache(self):
        return self.app.cache

    def _invalidate_cache(self, folder: str = None):
        """بعد از هر تغییر فایل/پوشه، کش لیست‌ها پاک می‌شود.
        اگر folder مشخص شود فقط همان شاخه و والدش پاک می‌شود، وگرنه کل کش پلاگین."""
        if folder is None:
            self._cache.invalidate_namespace(self.CACHE_NS)
            return
        keys = [f"{self.CACHE_NS}:list:{folder}"]
        parent = "/".join(folder.split("/")[:-1])
        if parent:
            keys.append(f"{self.CACHE_NS}:list:{parent}")
        self._cache.invalidate(*keys)

    # ---------------- schema ----------------
    def declare_schema(self, schema):
        """DB mirror of the uploads folder — every file operation is synced here.
        For images: dimensions (width/height) are stored; for other files:
        name, size and path are enough."""
        schema.register_table("images", {
            "id": "INT AUTO_INCREMENT PRIMARY KEY",
            "rel_path": "VARCHAR(500) NOT NULL UNIQUE",   # مسیر نسبی داخل uploads
            "file_name": "VARCHAR(255) NOT NULL",
            "folder": "VARCHAR(500) DEFAULT ''",
            "format": "VARCHAR(16)",                      # پسوند/فرمت
            "size_bytes": "INT DEFAULT 0",
            "width": "INT DEFAULT NULL",                  # فقط برای عکس
            "height": "INT DEFAULT NULL",                 # فقط برای عکس
            "is_image": "TINYINT(1) DEFAULT 0",
            "alt": "VARCHAR(255) DEFAULT ''",
            "url": "VARCHAR(600)",                        # assets/uploads/...
            "status": "VARCHAR(20) DEFAULT 'active'",
            "created_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
            "updated_at": "TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
        })

    def __init__(self, app, db):
        super().__init__(app, db)
        os.makedirs(UPLOAD_ROOT, exist_ok=True)

    # ---------------- storage quota ----------------
    @staticmethod
    def _used_bytes() -> int:
        total = 0
        for dirpath, _, files in os.walk(UPLOAD_ROOT):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
        return total

    # ---------------- routes ----------------

        
        

    @staticmethod
    def _build_tree():
        """Nested folder tree for the sidebar."""
        nodes = {}

        def ensure(path):
            if path in nodes:
                return nodes[path]
            node = {"name": path.split("/")[-1], "rel": path, "children": []}
            nodes[path] = node
            parent = "/".join(path.split("/")[:-1])
            if parent:
                ensure(parent)["children"].append(node)
            return node

        for dirpath, dirnames, _ in os.walk(UPLOAD_ROOT):
            rel = os.path.relpath(dirpath, UPLOAD_ROOT).replace("\\", "/")
            base = "" if rel == "." else rel
            for d in sorted(dirnames):
                full = f"{base}/{d}" if base else d
                ensure(full)
        # keep only top-level nodes (children already nested)
        return [n for n in nodes.values() if "/" not in n["rel"]]

    def _scan_folder(self, folder, cur_abs, recursive):
        """Folders + files of ``folder`` (cached; filters are applied by the caller)."""
        list_key = f"{self.CACHE_NS}:list:{folder}:{int(recursive)}"
        cached = self._cache.get(list_key, namespace=self.CACHE_NS)
        if cached is not None:
            return cached
        fls, fds = [], []
        s_dirs = [cur_abs]
        if recursive:
            for dirpath, dirnames, _filenames in os.walk(cur_abs):
                s_dirs.extend(os.path.join(dirpath, d) for d in dirnames)
        else:
            for name in sorted(os.listdir(cur_abs)):
                full = os.path.join(cur_abs, name)
                if os.path.isdir(full):
                    fds.append({
                        "name": name,
                        "rel": _safe_rel(os.path.join(folder, name)) if folder else name,
                        "count": sum(len(fs) for _, _, fs in os.walk(full)),
                    })
        seen = set()
        for d in s_dirs:
            try:
                names = os.listdir(d)
            except OSError:
                continue
            for name in sorted(names):
                full = os.path.join(d, name)
                if not os.path.isfile(full):
                    continue
                st = os.stat(full)
                fext = os.path.splitext(name)[1].lstrip(".").lower()
                key = os.path.abspath(full)
                if key in seen:
                    continue
                seen.add(key)
                rel = os.path.relpath(full, UPLOAD_ROOT).replace("\\", "/")
                item = {
                    "name": name, "rel": rel, "url": f"/{PUBLIC_PREFIX}/{rel}", "ext": fext, "size": st.st_size,
                    "size_h": _fmt_size(st.st_size),
                    "mtime_h": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
                    "is_image": fext in ("png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"),
                    "is_text": fext in ("txt", "md", "css", "js", "json", "html"),
                    "width": None, "height": None,
                }
                if item["is_image"]:
                    item["width"], item["height"] = self._image_size(full)
                fls.append(item)
        self._cache.set(list_key, (fds, fls), namespace=self.CACHE_NS)
        return fds, fls

    def _routes(self, bp):
        page_route(bp, "/admin/images", "admin_browse", "images", "تصاویر و فایل‌ها", "pages-images")

        @api_route(bp, "/api/admin/images", "api_list")
        async def api_list():
            q = request.args.get("q", "").strip()
            folder = request.args.get("folder", "")
            ext = request.args.get("ext", "").strip().lstrip(".").lower()
            date_from = request.args.get("date_from", "").strip()
            date_to = request.args.get("date_to", "").strip()
            size_min = request.args.get("size_min", "").strip()   # MB
            size_max = request.args.get("size_max", "").strip()   # MB
            recursive = request.args.get("recursive") == "1"
            try:
                cur_abs = _abs_path(folder) if folder else UPLOAD_ROOT
                min_b = float(size_min) * 1024 * 1024 if size_min else None
                max_b = float(size_max) * 1024 * 1024 if size_max else None
                ts_from = time.mktime(time.strptime(date_from, "%Y-%m-%d")) if date_from else None
                ts_to = time.mktime(time.strptime(date_to, "%Y-%m-%d")) + 86399 if date_to else None
            except ValueError:
                raise ApiError(400, "bad_request", "مسیر یا فیلتر نامعتبر است")
            if not os.path.isdir(cur_abs):
                raise ApiError(404, "not_found", "پوشه یافت نشد")
            folders, files = self._scan_folder(folder, cur_abs, recursive)

            filtered = []
            for item in files:
                if q and q.lower() not in item["name"].lower():
                    continue
                if ext and item["ext"] != ext:
                    continue
                if min_b is not None and item["size"] < min_b:
                    continue
                if max_b is not None and item["size"] > max_b:
                    continue
                if ts_from is not None or ts_to is not None:
                    try:
                        mtime = time.mktime(time.strptime(item["mtime_h"], "%Y-%m-%d %H:%M"))
                    except ValueError:
                        mtime = 0
                    if ts_from is not None and mtime < ts_from:
                        continue
                    if ts_to is not None and mtime > ts_to:
                        continue
                filtered.append(item)
            return reply({
                "folder": folder, "parent": "/".join(folder.split("/")[:-1]) if folder else "",
                "folders": folders, "files": filtered, "all_folders": await self.list_folders(),
                "tree": self._build_tree(), "used_bytes": self._used_bytes(), "max_bytes": MAX_SIZE_BYTES,
                "used_h": _fmt_size(self._used_bytes()), "max_h": _fmt_size(MAX_SIZE_BYTES) if MAX_SIZE_BYTES else None,
            })

        @api_route(bp, "/api/admin/images/folder", "api_folder_create", ["POST"])
        async def api_folder_create():
            data = body()
            name, folder = str(data.get("name", "")).strip(), str(data.get("folder", ""))
            if not name:
                raise invalid({"name": "نام پوشه را وارد کنید"})
            try:
                os.makedirs(_abs_path(os.path.join(folder, name)), exist_ok=True)
            except ValueError:
                raise invalid({"name": "نام پوشه نامعتبر است"})
            self._invalidate_cache()
            return reply({"created": _safe_rel(os.path.join(folder, name))}, 201)

        @api_route(bp, "/api/admin/images/upload", "api_upload", ["POST"])
        async def api_upload():
            folder = request.form.get("folder", "")
            try:
                dest_dir = _abs_path(folder) if folder else UPLOAD_ROOT
            except ValueError:
                raise invalid({"folder": "مسیر نامعتبر است"})
            os.makedirs(dest_dir, exist_ok=True)
            results = []
            incoming = 0
            pending = []
            for f in request.files.getlist("files"):
                if not f or not f.filename:
                    continue
                f.seek(0, os.SEEK_END)
                sz = f.tell()
                f.seek(0)
                pending.append((f, sz))
                incoming += sz
            used = self._used_bytes()
            if MAX_SIZE_BYTES and used + incoming > MAX_SIZE_BYTES:
                free = max(0, MAX_SIZE_BYTES - used)
                raise ApiError(413, "quota_exceeded",
                               f"فضای کافی وجود ندارد — حجم درخواستی {_fmt_size(incoming)} "
                               f"اما فقط {_fmt_size(free)} از سهمیه {_fmt_size(MAX_SIZE_BYTES)} باقی مانده")
            for f, _sz in pending:
                fname = os.path.basename(f.filename)
                # avoid overwriting: name-1.ext, name-2.ext, ...
                base, ext = os.path.splitext(fname)
                i = 1
                while os.path.exists(os.path.join(dest_dir, fname)):
                    fname = f"{base}-{i}{ext}"
                    i += 1
                path = os.path.join(dest_dir, fname)
                f.save(path)
                st = os.stat(path)
                fext = os.path.splitext(fname)[1].lstrip(".").lower()
                w = h = None
                if fext in ("png", "jpg", "jpeg", "gif", "webp", "bmp", "svg"):
                    w, h = self._image_size(path)
                rel = os.path.relpath(path, UPLOAD_ROOT).replace("\\", "/")
                await self._db_upsert(path)
                results.append({
                    "name": fname, "rel": rel, "url": f"/{PUBLIC_PREFIX}/{rel}", "size_h": _fmt_size(st.st_size),
                    "mtime_h": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)), "ext": fext,
                    "width": w, "height": h, "is_image": w is not None or fext in ("jpg", "jpeg", "svg"),
                })
            if results:
                self._invalidate_cache(folder or "")
            return reply({"uploaded": results}, 201)

        @api_route(bp, "/api/admin/images/folder/rename", "api_folder_rename", ["POST"])
        async def api_folder_rename():
            """Rename a folder on disk and update every DB record under it."""
            data = body()
            new_name = os.path.basename(str(data.get("new_name", "")).strip())
            try:
                rel = _safe_rel(str(data.get("rel", "")))
                src = _abs_path(rel)
                dst = os.path.join(os.path.dirname(src), new_name)
                if not os.path.isdir(src):
                    raise ApiError(404, "not_found", "پوشه یافت نشد")
                if not new_name:
                    raise invalid({"new_name": "نام جدید وارد نشده است"})
                if os.path.exists(dst):
                    raise ApiError(409, "conflict", "پوشه‌ای با این نام از قبل وجود دارد")
                parent = os.path.dirname(rel)
                new_rel = f"{parent}/{new_name}" if parent else new_name
                os.rename(src, dst)
                await self._db_move(rel, new_rel)
            except (ValueError, OSError) as e:
                raise ApiError(400, "bad_request", f"خطا در تغییر نام پوشه: {e}")
            return reply({"rel": new_rel})

        @api_route(bp, "/api/admin/images/rename", "api_rename", ["POST"])
        async def api_rename():
            data = body()
            rel = str(data.get("rel", ""))
            new_name = os.path.basename(str(data.get("new_name", "")).strip())
            if not new_name:
                raise invalid({"new_name": "نام جدید وارد نشده است"})
            try:
                src = _abs_path(rel)
                dst = os.path.join(os.path.dirname(src), new_name)
                if not os.path.exists(src):
                    raise ApiError(404, "not_found", "فایل یافت نشد")
                if src == dst:
                    return reply({"rel": _safe_rel(rel)})
                if os.path.exists(dst):
                    raise ApiError(409, "conflict", "فایلی با این نام از قبل وجود دارد")
                old_rel = _safe_rel(rel)
                new_rel = _safe_rel(os.path.join(os.path.dirname(old_rel), new_name))
                os.rename(src, dst)
                await self._db_rename(old_rel, new_rel)
            except (ValueError, OSError) as e:
                raise ApiError(400, "bad_request", f"خطا در تغییر نام: {e}")
            return reply({"rel": new_rel})

        @api_route(bp, "/api/admin/images/delete", "api_delete", ["POST"])
        async def api_delete():
            rels = [r for r in (body().get("rels") or []) if r]
            n, errors = 0, []
            for rel in rels:
                try:
                    p = _abs_path(rel)
                    if os.path.isdir(p):
                        shutil.rmtree(p)
                        await self._db_delete(_safe_rel(rel))
                    elif os.path.isfile(p):
                        os.remove(p)
                        await self._db_delete(_safe_rel(rel))
                    n += 1
                except (ValueError, OSError) as e:
                    errors.append(f"خطا در حذف {rel}: {e}")
            self._invalidate_cache()
            return reply({"deleted": n, "errors": errors})

        @api_route(bp, "/api/admin/images/move", "api_move", ["POST"])
        async def api_move():
            """Move one or more files/folders to another folder."""
            data = body()
            rels = [r for r in (data.get("rels") or []) if r]
            try:
                dest = _safe_rel(str(data.get("dest", "")))
                dest_abs = _abs_path(dest) if dest else UPLOAD_ROOT
                os.makedirs(dest_abs, exist_ok=True)
            except ValueError:
                raise invalid({"dest": "پوشه مقصد نامعتبر است"})
            n, errors = 0, []
            for rel in rels:
                try:
                    src = _abs_path(rel)
                    if not os.path.exists(src):
                        continue
                    dst = os.path.join(dest_abs, os.path.basename(_safe_rel(rel)))
                    if os.path.abspath(src) == os.path.abspath(dst):
                        continue
                    if os.path.exists(dst):
                        errors.append(f"فایلی با نام «{os.path.basename(dst)}» در مقصد وجود دارد")
                        continue
                    old_rel = _safe_rel(rel)
                    new_rel = _safe_rel(os.path.join(dest, os.path.basename(old_rel)) if dest else os.path.basename(old_rel))
                    shutil.move(src, dst)
                    await self._db_move(old_rel, new_rel)   # file itself + everything inside if it's a folder
                    n += 1
                except (ValueError, OSError) as e:
                    errors.append(f"خطا در انتقال {rel}: {e}")
            self._invalidate_cache()
            return reply({"moved": n, "errors": errors})

        # ---------- text editor ----------
        @api_route(bp, "/api/admin/images/text", "api_text", ["GET", "PUT"])
        async def api_text():
            if request.method == "PUT":
                data = body()
                rel = str(data.get("rel", ""))
                try:
                    path = _abs_path(rel)
                    if not os.path.isfile(path):
                        raise ApiError(404, "not_found", "فایل یافت نشد")
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(str(data.get("content", "")))
                    await self._db_upsert(path)   # refresh size in DB
                except (ValueError, OSError) as e:
                    raise ApiError(400, "bad_request", f"خطا در ذخیره: {e}")
                return reply({"rel": rel})
            rel = request.args.get("rel", "")
            try:
                with open(_abs_path(rel), "r", encoding="utf-8", errors="replace") as fh:
                    return reply({"rel": rel, "content": fh.read()})
            except (ValueError, OSError):
                raise ApiError(404, "not_found", "فایل یافت نشد")

        # ---------- public file serving: /assets/uploads/<path> ----------
        @bp.route(f"/{PUBLIC_PREFIX}/<path:filename>")
        async def serve_file(filename):
            resp = send_from_directory(UPLOAD_ROOT, filename)
            # files can be replaced (delete + re-upload with the same name), so
            # no ``immutable``; one day is safe for CDN/browser caching
            resp.headers["Cache-Control"] = "public, max-age=86400"
            resp.headers["X-Content-Type-Options"] = "nosniff"
            if filename.lower().endswith(".svg"):
                # an SVG opened directly must not be able to run scripts
                resp.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
            return resp

        # ---------- media picker backend ----------
        @api_route(bp, "/api/admin/media/browse", "media_browse")
        async def media_browse():
            """Folder/file listing for the admin media picker. The disk is the
            source of truth (the ``images`` table is not read)."""
            folder = request.args.get("folder", "")
            q = (request.args.get("q") or "").strip().lower()
            ext = (request.args.get("ext") or "").strip().lstrip(".").lower()
            try:
                page = max(1, int(request.args.get("page", 1)))
            except ValueError:
                page = 1
            try:
                per_page = min(200, max(1, int(request.args.get("per_page", 60))))
            except ValueError:
                per_page = 60
            try:
                base = _abs_path(folder) if folder else UPLOAD_ROOT
            except ValueError:
                raise ApiError(400, "bad_request", "invalid_path")
            if not os.path.isdir(base):
                raise ApiError(404, "not_found", "پوشه یافت نشد")
            rel_base = _safe_rel(folder)
            folders, files = [], []
            with os.scandir(base) as it:
                for e in sorted(it, key=lambda x: x.name.lower()):
                    if e.is_dir():
                        folders.append({"name": e.name, "rel": f"{rel_base}/{e.name}" if rel_base else e.name})
                    elif e.is_file():
                        fext = os.path.splitext(e.name)[1].lstrip(".").lower()
                        if (q and q not in e.name.lower()) or (ext and fext != ext):
                            continue
                        st = e.stat()
                        files.append((st.st_mtime, e.name, fext, st.st_size))
            files.sort(key=lambda t: t[0], reverse=True)
            total = len(files)
            out = []
            from app.core import content as C
            for mtime, name, fext, size in files[(page - 1) * per_page: page * per_page]:
                rel = f"{rel_base}/{name}" if rel_base else name
                is_image = fext in ("png", "jpg", "jpeg", "gif", "webp", "bmp", "svg")
                url = f"/{PUBLIC_PREFIX}/{rel}"
                meta = C.media_meta(url) if is_image else {"width": None, "height": None}
                out.append({
                    "name": name, "rel": rel, "url": url, "size": size, "ext": fext,
                    "width": meta["width"], "height": meta["height"], "is_image": is_image,
                    "mtime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(mtime)),
                })
            return reply({"folders": folders, "files": out}, meta={"page": page, "per_page": per_page, "total": total})

    def register(self):
        bp = Blueprint("plugin_images", __name__)
        self._routes(bp)
        self.app.register_blueprint(bp)

    # ---------------- helpers ----------------
    async def _db_upsert(self, path: str):
        """Insert/update the DB record for a file on disk (table: images).
        Images get width/height; non-images only need name/size/path.
        File content is always stored as base64 in base64_data."""
        try:
            rel = os.path.relpath(path, UPLOAD_ROOT).replace("\\", "/")
        except ValueError:
            return
        self._invalidate_cache(os.path.dirname(rel))
        st = os.stat(path)
        name = os.path.basename(rel)
        folder = os.path.dirname(rel)
        fmt = os.path.splitext(name)[1].lstrip(".").lower()
        is_image = fmt in ("png", "jpg", "jpeg", "gif", "webp", "bmp", "svg")
        w = h = None
        if is_image:
            w, h = self._image_size(path)
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
        else:
            b64 = None
        await self.db.execute(
            "INSERT INTO images (rel_path, file_name, folder, format, size_bytes, "
            "width, height, is_image, url, base64_data) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE file_name=VALUES(file_name), folder=VALUES(folder), "
            "format=VALUES(format), size_bytes=VALUES(size_bytes), width=VALUES(width), "
            "height=VALUES(height), is_image=VALUES(is_image), url=VALUES(url), "
            "base64_data=VALUES(base64_data)",
            (rel, name, folder, fmt, st.st_size, w, h, int(is_image),
             f"{PUBLIC_PREFIX}/{rel}", b64),
        )

    async def _db_rename(self, old_rel: str, new_rel: str):
        await self.db.execute(
            "UPDATE images SET rel_path=%s, file_name=%s, folder=%s, url=%s WHERE rel_path=%s",
            (new_rel, os.path.basename(new_rel), os.path.dirname(new_rel),
             f"{PUBLIC_PREFIX}/{new_rel}", old_rel),
        )
        self._invalidate_cache()

    async def _db_delete(self, rel: str):
        await self.db.execute("DELETE FROM images WHERE rel_path=%s OR rel_path LIKE %s",
                              (rel, rel + "/%"))
        self._invalidate_cache()

    async def _db_move(self, old_rel: str, new_rel: str):
        """Update DB paths after moving/renaming a file/folder."""
        await self._db_rename(old_rel, new_rel)
        # if a folder was renamed/moved, update all children paths
        await self.db.execute(
            "UPDATE images SET rel_path=CONCAT(%s, SUBSTRING(rel_path, %s)), "
            "folder=%s WHERE rel_path LIKE %s",
            (new_rel + "/", len(old_rel) + 1, os.path.dirname(new_rel),
             old_rel + "/%"),
        )
        # rebuild url column for all affected rows (self + children)
        await self.db.execute(
            "UPDATE images SET url=CONCAT(%s, '/', rel_path) "
            "WHERE rel_path=%s OR rel_path LIKE %s",
            (PUBLIC_PREFIX, new_rel, new_rel + "/%"),
        )

    async def list_folders(self):
        """All folders under uploads root — used by move/upload destination pickers."""
        result = [""]
        for dirpath, dirnames, _ in os.walk(UPLOAD_ROOT):
            for d in dirnames:
                rel = os.path.relpath(os.path.join(dirpath, d), UPLOAD_ROOT).replace("\\", "/")
                result.append(rel)
        return sorted(result)

    @staticmethod
    def _image_size(path):
        try:
            from PIL import Image
            with Image.open(path) as img:
                return img.width, img.height
        except Exception as e:
            print(e)
            pass
        try:
            with open(path, "rb") as fh:
                raw = fh.read(64)
            import struct
            if raw[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", raw[16:24])
                return w, h
            if raw[:4] == b"GIF8":
                w, h = struct.unpack("<HH", raw[6:10])
                return w, h
        except Exception:
            pass
        return None, None
    
