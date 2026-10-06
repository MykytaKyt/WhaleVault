"""One password, stored as an argon2 hash; a signed session cookie for N days.

The password comes from WEB_PASSWORD in .env. Its hash lives in data/web_password.json; a password changed
from the web settings is stored there too and then wins over .env (delete the file to go back to .env).
Five wrong attempts lock the login for a minute.
"""
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException, Request

COOKIE = "nb_session"
MAX_FAILURES = 5
LOCK_SECONDS = 60

_ph = PasswordHasher()


class Auth:
    def __init__(self, env_password: str, data_dir: Path, days: int):
        self.days = days
        self.store = data_dir / "web_password.json"
        data_dir.mkdir(parents=True, exist_ok=True)
        secret_file = data_dir / "web_secret"
        if not secret_file.exists():
            secret_file.write_bytes(secrets.token_bytes(32))
            secret_file.chmod(0o600)
        self.secret = secret_file.read_bytes()
        self.failures: list[float] = []
        self._load(env_password)

    # ---- password storage ----

    def _load(self, env_password: str) -> None:
        stored = json.loads(self.store.read_text()) if self.store.exists() else {}
        self.hash = stored.get("hash", "")
        if stored.get("source") != "web" and env_password and not self._verify(env_password):
            self._save(env_password, "env")  # first start, or WEB_PASSWORD changed in .env

    def _save(self, password: str, source: str) -> None:
        self.hash = _ph.hash(password)
        self.store.write_text(json.dumps({"hash": self.hash, "source": source}))
        self.store.chmod(0o600)

    def _verify(self, password: str) -> bool:
        if not self.hash:
            return False
        try:
            return _ph.verify(self.hash, password)
        except (VerificationError, InvalidHashError):
            return False

    @property
    def configured(self) -> bool:
        return bool(self.hash)

    def change_password(self, current: str, new: str) -> bool:
        if not self._verify(current):
            return False
        self._save(new, "web")
        return True

    # ---- login throttling ----

    def locked_for(self) -> int:
        now = time.time()
        self.failures = [t for t in self.failures if now - t < LOCK_SECONDS]
        if len(self.failures) >= MAX_FAILURES:
            return int(LOCK_SECONDS - (now - self.failures[0])) + 1
        return 0

    def check_password(self, password: str) -> bool:
        if self._verify(password):
            self.failures.clear()
            return True
        self.failures.append(time.time())
        return False

    # ---- sessions ----

    @property
    def key(self) -> bytes:
        # The current hash is part of the key: changing the password logs every session out
        return hashlib.sha256(self.secret + self.hash.encode()).digest()

    def _sign(self, payload: str) -> str:
        return hmac.new(self.key, payload.encode(), hashlib.sha256).hexdigest()

    def issue(self) -> str:
        exp = str(int(time.time()) + self.days * 86400)
        return f"{exp}.{self._sign(exp)}"

    def valid(self, token: str | None) -> bool:
        if not token or "." not in token or not self.hash:
            return False
        exp, sig = token.split(".", 1)
        return exp.isdigit() and int(exp) > time.time() and hmac.compare_digest(sig, self._sign(exp))

    def require(self, request: Request) -> None:
        if not self.valid(request.cookies.get(COOKIE)):
            raise HTTPException(status_code=401, detail="Нужно войти")
