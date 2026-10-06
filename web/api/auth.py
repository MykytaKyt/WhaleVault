"""One password from .env, signed session cookie for N days. No users, no database table."""
import asyncio
import hashlib
import hmac
import secrets
import time
from pathlib import Path

from fastapi import HTTPException, Request

COOKIE = "nb_session"


class Auth:
    def __init__(self, password: str, secret_file: Path, days: int):
        self.password = password
        self.days = days
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        if not secret_file.exists():
            secret_file.write_bytes(secrets.token_bytes(32))
            secret_file.chmod(0o600)
        # Changing the password invalidates every existing session
        self.key = hashlib.sha256(secret_file.read_bytes() + password.encode()).digest()

    def _sign(self, payload: str) -> str:
        return hmac.new(self.key, payload.encode(), hashlib.sha256).hexdigest()

    def issue(self) -> str:
        exp = str(int(time.time()) + self.days * 86400)
        return f"{exp}.{self._sign(exp)}"

    def valid(self, token: str | None) -> bool:
        if not token or "." not in token:
            return False
        exp, sig = token.split(".", 1)
        return exp.isdigit() and int(exp) > time.time() and hmac.compare_digest(sig, self._sign(exp))

    async def check_password(self, password: str) -> bool:
        ok = bool(self.password) and hmac.compare_digest(password.encode(), self.password.encode())
        if not ok:
            await asyncio.sleep(1)  # slows down guessing
        return ok

    def require(self, request: Request) -> None:
        if not self.valid(request.cookies.get(COOKIE)):
            raise HTTPException(status_code=401, detail="login required")
