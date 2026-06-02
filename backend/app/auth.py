"""JWT bearer-token authentication.

A single shared secret is used for HS256 signing. In production this
would be rotated and loaded from a secrets manager; here a hard-coded
dev secret keeps the local dev loop frictionless.
"""

from datetime import datetime, timedelta, timezone
from typing_extensions import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

# Dev-only secret. Override via environment variable in any real deployment.
SECRET_KEY = "dentalai-dev-secret-change-in-prod"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 h for convenience during local dev

bearer_scheme = HTTPBearer()


def create_access_token(subject: str = "dev-user") -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_auth(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
) -> dict:
    """FastAPI dependency — validates the Bearer token and returns the payload."""
    return _decode_token(credentials.credentials)
