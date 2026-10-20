import os
import time

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.appdb import get_user

_hasher = PasswordHasher()
_DUMMY_HASH = _hasher.hash("not-a-real-password")
bearer = HTTPBearer(auto_error=False)


class AuthError(Exception):
    pass


class AuthConfigError(AuthError):
    pass


def hash_password(password):
    return _hasher.hash(password)


def verify_password(password, password_hash):
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def authenticate(user, password):
    if user is None:
        verify_password(password, _DUMMY_HASH)
        return False
    return verify_password(password, user.password_hash) and user.is_active


def _secret():
    secret = os.getenv("JWT_SECRET", "")
    if len(secret) < 32:
        raise AuthConfigError("JWT_SECRET must be set to at least 32 characters.")
    return secret


def create_token(username, role):
    now = int(time.time())
    minutes = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))
    payload = {"sub": username, "role": role, "iat": now, "exp": now + minutes * 60}
    return jwt.encode(payload, _secret(), algorithm="HS256")


def decode_token(token):
    try:
        return jwt.decode(token, _secret(), algorithms=["HS256"], options={"require": ["exp", "sub"]})
    except jwt.PyJWTError as e:
        raise AuthError("Invalid or expired token.") from e


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)):
    headers = {"WWW-Authenticate": "Bearer"}
    if creds is None:
        raise HTTPException(status_code=401, detail="Not authenticated.", headers=headers)
    try:
        claims = decode_token(creds.credentials)
    except AuthConfigError:
        raise
    except AuthError:
        raise HTTPException(status_code=401, detail="Invalid or expired token.", headers=headers)
    user = get_user(claims["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid or expired token.", headers=headers)
    return user