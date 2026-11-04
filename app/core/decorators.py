import functools

from flask import redirect, url_for, flash, current_app

from .auth import AuthManager


def _localized_url(endpoint, **values):
    """Build a URL that respects the active language prefix. If the
    i18n plugin is loaded and active, it adds the /<code> prefix for
    non-default languages so the user lands in the same language
    after a redirect."""
    i18n = current_app.core.plugins.plugins.get("i18n") \
        if hasattr(current_app, "core") else None
    if i18n is not None:
        try:
            return i18n.url_for_lang(endpoint, **values)
        except Exception:
            pass
    return url_for(endpoint, **values)


def login_required(view):
    @functools.wraps(view)
    async def wrapper(*args, **kwargs):
        if not AuthManager.current_user():
            flash("لطفاً وارد شوید", "warning")
            return redirect(_localized_url("core.login"))
        return await view(*args, **kwargs)

    return wrapper


def admin_required(view):
    @functools.wraps(view)
    async def wrapper(*args, **kwargs):
        if not AuthManager.current_user():
            return redirect(_localized_url("core.login"))
        if not AuthManager.is_admin():
            flash("دسترسی غیرمجاز", "danger")
            return redirect(_localized_url("core.index"))
        return await view(*args, **kwargs)

    return wrapper
