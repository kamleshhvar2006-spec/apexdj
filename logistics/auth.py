"""Admin authentication without any external service.

* Password: stored as "scrypt:<saltHex>:<hashHex>" (same format as the Node.js Catalyst version, so hashes are interchangeable).
* Session: a token "<payload>.<signature>" signed with HMAC-SHA256 using SESSION_SECRET, valid for one hour.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

SESSION_SECONDS = 3600
SCRYPT = dict(n=16384, r=8, p=1, maxmem=64 * 1024 * 1024)


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def session_secret():
    secret = os.environ.get('SESSION_SECRET', '')
    return secret if len(secret) >= 32 else None


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode('utf-8'), salt=salt, dklen=64, **SCRYPT)
    return f'scrypt:{salt.hex()}:{digest.hex()}'


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, hash_hex = str(stored or '').split(':')
        expected = bytes.fromhex(hash_hex)
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    if scheme != 'scrypt' or not expected or not salt:
        return False
    actual = hashlib.scrypt(password.encode('utf-8'), salt=salt, dklen=len(expected), **SCRYPT)
    return hmac.compare_digest(actual, expected)


def same_text(a: str, b: str) -> bool:
    return hmac.compare_digest(hashlib.sha256(a.encode()).digest(), hashlib.sha256(b.encode()).digest())


def _signature(secret: str, body: str) -> bytes:
    return hmac.new(secret.encode('utf-8'), body.encode('ascii'), hashlib.sha256).digest()


def sign_token(payload: dict) -> str:
    body = _b64u(json.dumps(payload, separators=(',', ':')).encode('utf-8'))
    return f'{body}.{_b64u(_signature(session_secret(), body))}'


def verify_token(token: str):
    secret = session_secret()
    parts = str(token or '').split('.')
    if not secret or len(parts) != 2 or not all(parts):
        return None
    body, sig = parts
    try:
        given = _b64u_decode(sig)
    except ValueError:
        return None
    if not hmac.compare_digest(given, _signature(secret, body)):
        return None
    try:
        payload = json.loads(_b64u_decode(body))
    except ValueError:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get('exp'), (int, float)):
        return None
    return payload if payload['exp'] > time.time() else None


# Best-effort brute-force guard: kept in this process's memory, so it is per gunicorn worker.
# For a hard limit, add Catalyst API Gateway throttling on the login route.
_failures = {}
_lock = threading.Lock()
WINDOW_SECONDS = 15 * 60
MAX_FAILURES = 8


def locked_out(ip: str) -> bool:
    with _lock:
        rec = _failures.get(ip)
        return bool(rec) and rec[0] >= MAX_FAILURES and time.time() - rec[1] < WINDOW_SECONDS


def note_failure(ip: str) -> None:
    now = time.time()
    with _lock:
        rec = _failures.get(ip)
        if not rec or now - rec[1] >= WINDOW_SECONDS:
            _failures[ip] = [1, now]
        else:
            rec[0] += 1
        if len(_failures) > 1000:
            _failures.clear()


def reset_failures() -> None:
    with _lock:
        _failures.clear()
