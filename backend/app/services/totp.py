"""Time-based one-time codes (RFC 6238), the codes shown by Google Authenticator, Microsoft Authenticator,
Authy, 1Password and similar apps: HMAC-SHA1, 6 digits, a new code every 30 seconds.

`verify` accepts the current code and the one before / after (clocks drift by a few seconds) and returns the
time step it matched, so the caller can refuse the same code twice (a code that was seen cannot be replayed)."""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30
DIGITS = 6
ISSUER = "BuildSuite"


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret):
    return base64.b32decode(secret + "=" * (-len(secret) % 8))


def code_at(secret, step):
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** DIGITS).zfill(DIGITS)


def current_step(at=None):
    return int((at if at is not None else time.time()) // STEP)


def now_code(secret, at=None):
    return code_at(secret, current_step(at))


def verify(secret, code, last_step=None, at=None):
    """Return the matched time step, or None. A step at or before `last_step` was already used."""
    code = (code or "").strip().replace(" ", "")
    if not secret or len(code) != DIGITS or not code.isdigit():
        return None
    now = current_step(at)
    for step in (now - 1, now, now + 1):
        if hmac.compare_digest(code_at(secret, step), code):
            if last_step is not None and step <= last_step:
                return None
            return step
    return None


def otpauth_uri(secret, account):
    """The link inside the QR code an authenticator app scans."""
    label = quote(f"{ISSUER}:{account}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}&algorithm=SHA1&digits={DIGITS}&period={STEP}"
