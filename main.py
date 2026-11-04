"""Base CMS - Plugin-based Flask backend (async).

Features:
- Auto-restart on crash (supervisor loop)
- Daily log files in logs/YYYY-MM-DD.log with timestamps
"""
import asyncio
import logging
import os
import sys
import time
from datetime import datetime
import types

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)


def setup_logging() -> logging.Logger:
    """File logger: logs/<YYYY-MM-DD>.log — one file per day."""
    today = datetime.now().strftime("%Y-%m-%d")
    logfile = os.path.join(LOG_DIR, f"{today}.log")

    logger = logging.getLogger("cms")
    logger.setLevel(logging.INFO)

    fh = logging.FileHandler(logfile, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(sh)

    logging.captureWarnings(True)

    def handle_exception(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = handle_exception
    return logger


logger = setup_logging()

def safe_length(value):
    # بررسی می‌کنیم که آیا جینجا اشتباهاً یک متد داخلی پایتون را فرستاده یا خیر
    if isinstance(value, types.BuiltinMethodType):
        try:
            # اگر متد بود، آن را اجرا می‌کنیم (مثل اجرای dict.keys()) و طولش را برمی‌گردانیم
            return len(value())
        except TypeError:
            pass
    # در حالت عادی، همان کار استاندارد را انجام می‌دهد
    return len(value)




def run_server_once() -> int:
    """Run the server in normal (blocking) mode; return exit code on crash."""
    from app import create_app

    try:
        app = create_app()

        app.jinja_env.filters['length'] = safe_length


        app.logger.handlers = logger.handlers  # route flask logs to our files

        logger.info("Server starting on http://127.0.0.1:5000")
        # normal blocking run (no threads/asyncio server)
        app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=True)
        return 0
    except Exception:
        logger.critical("Server crashed", exc_info=True)
        return 1


def reset_password(username: str) -> int:
    """CLI: python main.py resetpass <username> — prompts for new password."""
    import getpass

    from app import create_app
    from app.core.auth import hash_password

    app = create_app()
    db = app.core.db
    import asyncio

    async def do():
        row = await db.query("SELECT id FROM users WHERE username=%s", (username,), one=True)
        if not row:
            print(f"User '{username}' not found.")
            return 1
        pw = getpass.getpass("New password: ")
        pw2 = getpass.getpass("Confirm password: ")
        if pw != pw2 or not pw:
            print("Passwords do not match (or empty).")
            return 1
        await db.execute(
            "UPDATE users SET password_hash=%s WHERE username=%s",
            (hash_password(pw), username),
        )
        print(f"Password for '{username}' reset successfully.")
        return 0

    return asyncio.run(do())


def import_ui_strings(argv) -> int:
    """CLI: python main.py import_ui_strings --lang fa --file fa.json
    [--prefix web.] [--mode missing|overwrite]

    Imports a nested frontend locale JSON into ``i18n_translations`` as flat
    dotted keys (``{"nav":{"home":"x"}}`` -> ``web.nav.home``)."""
    import argparse
    import json

    ap = argparse.ArgumentParser(prog="main.py import_ui_strings")
    ap.add_argument("--lang", required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--prefix", default="web.")
    ap.add_argument("--mode", choices=["missing", "overwrite"], default="missing")
    args = ap.parse_args(argv)

    from app import create_app

    app = create_app()
    i18n = app.core.plugins.plugins.get("i18n")
    if not i18n:
        print("i18n plugin is not loaded.")
        return 1
    with open(args.file, encoding="utf-8-sig") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        print("JSON root must be an object.")
        return 1

    async def go():
        row = await app.core.db.fetch(
            "SELECT code FROM i18n_languages WHERE code=%s", (args.lang,), one=True
        )
        if not row:
            print(f"Language '{args.lang}' does not exist (create it in /admin/i18n first).")
            return None
        return await i18n.import_strings(args.lang, data, prefix=args.prefix, mode=args.mode)

    import asyncio

    res = asyncio.run(go())
    if res is None:
        return 1
    print(f"[{args.lang}] added={res['added']} updated={res['updated']} skipped={res['skipped']} ignored={res['ignored']}")
    return 0


if __name__ == "__main__":
    # CLI commands: python main.py resetpass <username>
    if len(sys.argv) >= 3 and sys.argv[1] == "resetpass":
        sys.exit(reset_password(sys.argv[2]))
    if len(sys.argv) >= 2 and sys.argv[1] == "import_ui_strings":
        sys.exit(import_ui_strings(sys.argv[2:]))

    run_server_once()
