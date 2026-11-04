"""inquiries plugin — contact form / quote requests (spec 6.10).

Public: ``POST /api/public/inquiries`` (JSON). The server repeats every rule
of the frontend form (never trust the client), applies a honeypot, a rate
limit per IP and issues a sequential, atomic reference code
``<PREFIX>-<year>-<0001>``.

Admin: ``/admin/inquiries`` (search/filter/paginate, details, status, internal
note, CSV export, delete). Inquiry data is never exposed by the public API.
"""
from __future__ import annotations

import asyncio
import csv
import io
import os
import random
import re
import smtplib
import threading
from email.message import EmailMessage

from flask import Blueprint, Response, current_app, request

from app.core import captcha
from app.core import content as C
from app.core import migrate
from app.core.base_plugin import BasePlugin
from app.core.admin_api import api_route, body, invalid, page_route, reply
from app.core.public import (
    ApiError, RateLimiter, client_ip, json_body, public_blueprint, validation_failed,
)

STATUSES = [("new", "جدید"), ("in_progress", "در حال بررسی"), ("answered", "پاسخ داده شد"),
            ("closed", "بسته"), ("spam", "اسپم")]
STATUS_LABEL = dict(STATUSES)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9+\-()\s۰-۹٠-٩.]+$")
LIMITER = RateLimiter()
PER_PAGE = 20


def _rate_rules():
    def num(name, default):
        try:
            return int(os.getenv(name, default) or default)
        except ValueError:
            return int(default)
    return [(num("INQUIRY_RATE_PER_HOUR", 5), 3600), (num("INQUIRY_RATE_PER_DAY", 20), 86400)]


def validate_payload(data: dict) -> tuple[dict, dict]:
    """Return ``(clean, fields_errors)`` using the frontend zod rules."""
    errors, clean = {}, {}

    def text(name, lo, hi, required=True):
        raw = data.get(name)
        v = C.strip_tags(raw).strip() if isinstance(raw, str) else ""
        if raw is not None and not isinstance(raw, str):
            errors[name] = {"code": "invalid_value"}
            return ""
        if not v:
            if required:
                errors[name] = {"code": "required"}
            return ""
        if lo and len(v) < lo:
            errors[name] = {"code": "too_short", "min": lo}
        elif hi and len(v) > hi:
            errors[name] = {"code": "too_long", "max": hi}
        return v

    clean["full_name"] = text("full_name", 3, 160)
    clean["email"] = text("email", 0, 200)
    if clean["email"] and "email" not in errors and not EMAIL_RE.match(clean["email"]):
        errors["email"] = {"code": "invalid_email"}
    clean["phone"] = text("phone", 8, 60)
    if clean["phone"] and "phone" not in errors and not PHONE_RE.match(clean["phone"]):
        errors["phone"] = {"code": "invalid_value"}
    clean["company"] = text("company", 0, 160, required=False)
    clean["subject"] = text("subject", 4, 240)
    clean["product_code"] = text("product_code", 0, 80, required=False)
    clean["message"] = text("message", 15, 5000)
    locale = data.get("locale")
    if locale in (None, ""):
        clean["locale"] = "fa"
    elif locale in ("fa", "en"):
        clean["locale"] = locale
    else:
        errors["locale"] = {"code": "invalid_value"}
        clean["locale"] = "fa"
    return clean, errors


class Plugin(BasePlugin):
    name = "inquiries"
    auto_enable = True
    admin_entry = {"title": "استعلام‌ها", "icon": "✉️", "url": "/admin/inquiries", "order": 19}
    output_type = "json"

    def declare_schema(self, schema):
        schema.register_table("inquiries", {
            "id": "INT AUTO_INCREMENT PRIMARY KEY",
            "reference_code": "VARCHAR(40) NOT NULL",
            "full_name": "VARCHAR(160) NOT NULL",
            "email": "VARCHAR(200) NOT NULL",
            "phone": "VARCHAR(60) NOT NULL",
            "company": "VARCHAR(160) NULL",
            "subject": "VARCHAR(240) NOT NULL",
            "product_code": "VARCHAR(80) NULL",
            "product_id": "INT NULL",
            "message": "TEXT NOT NULL",
            "locale": "VARCHAR(8) NOT NULL DEFAULT 'fa'",
            "status": "VARCHAR(20) NOT NULL DEFAULT 'new'",
            "ip": "VARCHAR(64) NULL",
            "user_agent": "VARCHAR(400) NULL",
            "created_at": "DATETIME NULL",
            "handled_by": "VARCHAR(64) NULL",
            "internal_note": "TEXT NULL",
            "answered_at": "DATETIME NULL",
        })
        schema.register_table("inquiry_counters", {
            "year": "INT PRIMARY KEY",
            "last": "INT NOT NULL DEFAULT 0",
        })

    def maybe_run_migration(self):
        def go(cur):
            migrate.ensure_index(cur, "inquiries", "uniq_inq_ref", "reference_code", unique=True)
            migrate.ensure_index(cur, "inquiries", "idx_inq_status", "status, created_at")
            migrate.ensure_index(cur, "inquiries", "idx_inq_ip", "ip, created_at")
        migrate.run(self.db, go)

    # dashboard tile with the number of new inquiries (sync; short query)
    def get_admin_entry(self):
        entry = super().get_admin_entry()
        if not entry:
            return None
        try:
            conn = self.db._conn()
            try:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM inquiries WHERE status='new'")
                n = cur.fetchone()[0]
            finally:
                conn.close()
            if n:
                entry["badge"] = n
        except Exception:
            pass
        return entry

    # ------------------------------------------------------------------ settings
    async def _reference_prefix(self, db) -> str:
        row = await db.fetch("SELECT value FROM site_settings WHERE skey='inquiry_reference_prefix'", one=True)
        v = (row or {}).get("value") or "INQ"
        return re.sub(r"[^A-Za-z0-9]", "", v).upper()[:10] or "INQ"

    async def _notify_emails(self, db) -> list:
        row = await db.fetch("SELECT value FROM site_settings WHERE skey='inquiry_notify_emails'", one=True)
        return [e for e in C.parse_list((row or {}).get("value")) if isinstance(e, str) and EMAIL_RE.match(e)]

    def smtp_configured(self) -> bool:
        return bool(os.getenv("SMTP_HOST"))

    # ------------------------------------------------------------------ routes
    def register(self):
        db = self.db
        pub = public_blueprint("public_inquiries")

        @pub.route("/inquiries", methods=["POST"])
        async def create_inquiry():
            ip = client_ip()
            wait = LIMITER.check(f"inq:{ip}", _rate_rules())
            if wait:
                raise ApiError(429, "rate_limited", "Too many requests", headers={"Retry-After": str(wait)})
            data = json_body()
            hour_limit, day_limit = (r[0] for r in _rate_rules())
            counts = await db.fetch(
                "SELECT SUM(created_at >= UTC_TIMESTAMP() - INTERVAL 1 HOUR) AS h, COUNT(*) AS d FROM inquiries "
                "WHERE ip=%s AND created_at >= UTC_TIMESTAMP() - INTERVAL 1 DAY", (ip,), one=True)
            if counts and ((hour_limit and int(counts["h"] or 0) >= hour_limit) or (day_limit and counts["d"] >= day_limit)):
                raise ApiError(429, "rate_limited", "Too many requests", headers={"Retry-After": "3600"})
            prefix = await self._reference_prefix(db)
            if (data.get("website") or "") not in ("", None):
                # honeypot: pretend success, store nothing, do not alert the bot
                fake = f"{prefix}-{C.utcnow().year}-{random.randint(1, 9999):04d}"
                return Response(
                    '{"ok":true,"reference_code":"%s"}' % fake, status=201,
                    headers={"Content-Type": "application/json; charset=utf-8"},
                )
            clean, errors = validate_payload(data)
            token = data.get("captcha_token")
            if captcha.provider():                      # CAPTCHA configured => the token is mandatory
                if not isinstance(token, str) or not token.strip():
                    errors["captcha_token"] = {"code": "required"}
                elif len(token) > captcha.MAX_TOKEN_LEN:
                    errors["captcha_token"] = {"code": "invalid_value"}
            if errors:
                raise validation_failed(errors)
            if captcha.provider():                      # verified last: tokens are single-use
                try:
                    human = await asyncio.to_thread(captcha.verify, token.strip(), ip)
                except captcha.CaptchaUnavailable:
                    raise ApiError(503, "unavailable", "CAPTCHA verification unavailable")
                if not human:
                    raise validation_failed({"captcha_token": {"code": "invalid_value"}})
            ua = (request.headers.get("User-Agent") or "")[:400]
            year = C.utcnow().year

            def go(tx):
                pid = None
                if clean["product_code"]:
                    p = tx.one("SELECT id FROM products WHERE LOWER(model_code)=LOWER(%s) LIMIT 1", (clean["product_code"],))
                    pid = p["id"] if p else None
                # row lock on the yearly counter row serialises concurrent requests;
                # the increment commits (or rolls back) together with the inquiry
                tx.run("INSERT IGNORE INTO inquiry_counters (year, last) VALUES (%s, 0)", (year,))
                tx.run("UPDATE inquiry_counters SET last = LAST_INSERT_ID(last + 1) WHERE year=%s", (year,))
                n = tx.one("SELECT LAST_INSERT_ID() AS n")["n"]
                ref = f"{prefix}-{year}-{n:04d}"
                tx.run(
                    "INSERT INTO inquiries (reference_code, full_name, email, phone, company, subject, product_code, product_id, "
                    "message, locale, status, ip, user_agent, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'new',%s,%s,UTC_TIMESTAMP())",
                    (ref, clean["full_name"], clean["email"], clean["phone"], clean["company"] or None, clean["subject"],
                     clean["product_code"] or None, pid, clean["message"], clean["locale"], ip, ua),
                )
                return ref

            ref = await db.transaction(go)
            self._email_async(clean, ref)
            return Response(
                '{"ok":true,"reference_code":"%s"}' % ref, status=201,
                headers={"Content-Type": "application/json; charset=utf-8"},
            )

        self.app.register_blueprint(pub)
        self._register_admin()

    # ------------------------------------------------------------------ email
    def _email_async(self, clean: dict, ref: str):
        """Fire-and-forget notification; never affects the API response."""
        if not self.smtp_configured():
            return
        app = self.app

        def send():
            try:
                import asyncio

                to = asyncio.run(self._notify_emails(self.db))
                if not to:
                    return
                msg = EmailMessage()
                msg["Subject"] = f"[{ref}] استعلام جدید: {clean['subject'][:80]}"
                msg["From"] = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or "noreply@localhost"
                msg["To"] = ", ".join(to)
                msg.set_content(
                    f"شماره رهگیری: {ref}\nنام: {clean['full_name']}\nایمیل: {clean['email']}\nتلفن: {clean['phone']}\n"
                    f"شرکت: {clean['company']}\nکد محصول: {clean['product_code']}\n\n{clean['message']}\n"
                )
                host, port = os.getenv("SMTP_HOST"), int(os.getenv("SMTP_PORT", "587") or 587)
                tls = (os.getenv("SMTP_TLS", "1") or "1").lower() in ("1", "true", "yes", "on", "starttls")
                with smtplib.SMTP(host, port, timeout=10) as s:
                    if tls:
                        s.starttls()
                    if os.getenv("SMTP_USER"):
                        s.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD", ""))
                    s.send_message(msg)
            except Exception as e:  # logged without secrets
                app.logger.warning(f"[inquiries] email notification failed: {type(e).__name__}")

        threading.Thread(target=send, daemon=True).start()

    # ------------------------------------------------------------------ admin
    def _filters(self):
        q = (request.args.get("q") or "").strip()
        status = (request.args.get("status") or "").strip()
        product_code = (request.args.get("product_code") or "").strip()
        date_from = (request.args.get("date_from") or "").strip()
        date_to = (request.args.get("date_to") or "").strip()
        where, params = [], []
        if q:
            like = "%" + C.escape_like(q) + "%"
            where.append("(full_name LIKE %s OR email LIKE %s OR subject LIKE %s OR reference_code LIKE %s OR phone LIKE %s OR company LIKE %s)")
            params += [like] * 6
        if status in STATUS_LABEL:
            where.append("status=%s")
            params.append(status)
        if product_code:
            where.append("product_code LIKE %s")
            params.append("%" + C.escape_like(product_code) + "%")
        for val, op in ((date_from, ">="), (date_to, "<")):
            if re.match(r"^\d{4}-\d{2}-\d{2}$", val):
                if op == "<":
                    where.append("created_at < DATE_ADD(%s, INTERVAL 1 DAY)")
                else:
                    where.append("created_at >= %s")
                params.append(val)
        return (("WHERE " + " AND ".join(where)) if where else ""), params, dict(
            q=q, status=status, product_code=product_code, date_from=date_from, date_to=date_to)

    def _register_admin(self):
        db = self.db
        bp = Blueprint("plugin_inquiries", __name__)

        page_route(bp, "/admin/inquiries", "admin_list", "inquiries", "استعلام‌ها", "pages-inquiries")
        page_route(bp, "/admin/inquiries/<int:iid>", "admin_detail", "inquiry", "جزئیات استعلام", "pages-inquiries")

        @api_route(bp, "/api/admin/inquiries", "api_list")
        async def api_list():
            where, params, flt = self._filters()
            try:
                page = max(1, int(request.args.get("page", 1)))
            except ValueError:
                page = 1
            total = (await db.fetch(f"SELECT COUNT(*) AS c FROM inquiries {where}", tuple(params), one=True))["c"]
            rows = await db.fetch(
                f"SELECT id, reference_code, created_at, status, full_name, email, phone, company, subject, product_code "
                f"FROM inquiries {where} ORDER BY id DESC LIMIT %s OFFSET %s",
                (*params, PER_PAGE, (page - 1) * PER_PAGE))
            new_count = (await db.fetch("SELECT COUNT(*) AS c FROM inquiries WHERE status='new'", one=True))["c"]
            return reply(rows, meta={
                "total": total, "page": page, "per_page": PER_PAGE, "total_pages": max(1, -(-total // PER_PAGE)) if total else 0,
                "new_count": new_count, "smtp": self.smtp_configured(),
                "statuses": [{"value": v, "label": l} for v, l in STATUSES],
            })

        @api_route(bp, "/api/admin/inquiries/export.csv", "api_export")
        async def api_export():
            where, params, _ = self._filters()
            rows = await db.fetch(f"SELECT * FROM inquiries {where} ORDER BY id DESC LIMIT 20000", tuple(params))
            buf = io.StringIO()
            buf.write("﻿")  # BOM so Excel reads UTF-8
            w = csv.writer(buf)
            cols = ["reference_code", "created_at", "status", "full_name", "email", "phone", "company", "subject",
                    "product_code", "message", "locale", "internal_note"]
            w.writerow(cols)

            def safe(v):
                s = "" if v is None else str(v)
                return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s  # CSV formula injection

            for r in rows:
                w.writerow([safe(r.get(c)) for c in cols])
            return Response(
                buf.getvalue(), mimetype="text/csv; charset=utf-8",
                headers={"Content-Disposition": 'attachment; filename="inquiries.csv"'},
            )

        @api_route(bp, "/api/admin/inquiries/<int:iid>", "api_detail", ["GET", "PUT"])
        async def api_detail(iid):
            row = await db.fetch("SELECT * FROM inquiries WHERE id=%s", (iid,), one=True)
            if not row:
                raise ApiError(404, "not_found", "استعلام یافت نشد")
            if request.method == "PUT":
                data = body()
                status = data.get("status") or row["status"]
                if status not in STATUS_LABEL:
                    raise invalid({"status": "وضعیت نامعتبر است"})
                note = C.strip_tags(str(data.get("internal_note") or ""))[:5000] if "internal_note" in data else row.get("internal_note")
                from app.core.auth import AuthManager

                user = AuthManager.current_user()
                await db.transaction(lambda tx: tx.run(
                    "UPDATE inquiries SET status=%s, internal_note=%s, handled_by=%s, "
                    "answered_at=CASE WHEN %s='answered' AND answered_at IS NULL THEN UTC_TIMESTAMP() ELSE answered_at END WHERE id=%s",
                    (status, note or None, (user or {}).get("username"), status, iid)))
                row = await db.fetch("SELECT * FROM inquiries WHERE id=%s", (iid,), one=True)
            return reply({"inquiry": row, "statuses": [{"value": v, "label": l} for v, l in STATUSES]})

        @api_route(bp, "/api/admin/inquiries/<int:iid>", "api_delete", ["DELETE"])
        async def api_delete(iid):
            if not await db.fetch("SELECT id FROM inquiries WHERE id=%s", (iid,), one=True):
                raise ApiError(404, "not_found", "استعلام یافت نشد")
            await db.transaction(lambda tx: tx.run("DELETE FROM inquiries WHERE id=%s", (iid,)))
            return reply({"deleted": iid})

        self.app.register_blueprint(bp)
