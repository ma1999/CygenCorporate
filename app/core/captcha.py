"""Optional CAPTCHA for the public contact form (Cloudflare Turnstile / hCaptcha).

Enabled only when ``CAPTCHA_PROVIDER`` (``turnstile`` | ``hcaptcha``) and
``CAPTCHA_SECRET`` are set; then ``POST /api/public/inquiries`` requires a
``captcha_token``. ``CAPTCHA_SITE_KEY`` is public (returned by ``GET /site`` so
the frontend can render the widget). ``CAPTCHA_VERIFY_URL`` overrides the
provider endpoint (tests / self-hosted mirrors). The secret is never logged.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

VERIFY_URLS = {
    "turnstile": "https://challenges.cloudflare.com/turnstile/v0/siteverify",
    "hcaptcha": "https://hcaptcha.com/siteverify",
}
MAX_TOKEN_LEN = 4096


class CaptchaUnavailable(Exception):
    """The verification service could not be reached / answered with an error."""


def provider() -> str | None:
    p = (os.getenv("CAPTCHA_PROVIDER") or "").strip().lower()
    return p if p in VERIFY_URLS and (os.getenv("CAPTCHA_SECRET") or "").strip() else None


def site_key() -> str | None:
    return (os.getenv("CAPTCHA_SITE_KEY") or "").strip() or None


def public_config() -> dict:
    """What the frontend needs to render the widget (never the secret)."""
    p = provider()
    return {"provider": p, "site_key": site_key() if p else None}


def verify(token: str, ip: str = "") -> bool:
    """Blocking call (run it in a thread). True = human, False = rejected."""
    p = provider()
    if not p:
        return True
    url = (os.getenv("CAPTCHA_VERIFY_URL") or "").strip() or VERIFY_URLS[p]
    body = urllib.parse.urlencode(
        {"secret": os.getenv("CAPTCHA_SECRET", ""), "response": token, "remoteip": ip or ""}
    ).encode()
    req = urllib.request.Request(
        url, data=body, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500:
            return False
        raise CaptchaUnavailable(f"HTTP {e.code}") from e
    except Exception as e:
        raise CaptchaUnavailable(type(e).__name__) from e
    return bool(isinstance(data, dict) and data.get("success") is True)
