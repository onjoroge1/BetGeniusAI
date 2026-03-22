"""
Admin JWT Authentication

Lightweight JWT-based auth for the admin user.  Supports both:
1. Legacy API key (Bearer <BETGENIUS_API_KEY>)
2. JWT tokens (Bearer <jwt_token>)

Environment variables:
    JWT_SECRET_KEY  – HMAC secret for signing tokens (required for JWT)
    ADMIN_EMAIL     – Admin email for login (default: admin@snapbet.bet)
    ADMIN_PASSWORD_HASH – bcrypt hash of admin password
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import jwt, JWTError

logger = logging.getLogger(__name__)

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 24

# Load from env
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@snapbet.bet")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH", "")


def create_access_token(
    subject: str = "admin",
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a signed JWT access token.

    Args:
        subject: Token subject (default: "admin")
        expires_delta: Custom expiry (default: 24 hours)

    Returns:
        Encoded JWT string.

    Raises:
        ValueError: If JWT_SECRET_KEY is not configured.
    """
    if not JWT_SECRET_KEY:
        raise ValueError(
            "JWT_SECRET_KEY environment variable is not set. "
            "Set it to a random 32+ character string to enable JWT auth."
        )

    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(hours=JWT_EXPIRE_HOURS))

    payload = {
        "sub": subject,
        "iat": now,
        "exp": expire,
        "iss": "betgenius-api",
    }

    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> Optional[dict]:
    """
    Verify and decode a JWT token.

    Returns:
        Decoded payload dict if valid, None otherwise.
    """
    if not JWT_SECRET_KEY:
        return None

    try:
        payload = jwt.decode(
            token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM]
        )
        # Check required fields
        if payload.get("sub") and payload.get("exp"):
            return payload
        return None
    except JWTError as e:
        logger.debug(f"JWT verification failed: {e}")
        return None


def verify_admin_password(password: str) -> bool:
    """
    Verify the admin password against the stored bcrypt hash.

    Falls back to a simple comparison if bcrypt is not available
    or no hash is configured (dev mode only).
    """
    if not ADMIN_PASSWORD_HASH:
        logger.warning("ADMIN_PASSWORD_HASH not set — login disabled")
        return False

    # If hash looks like a bcrypt hash, use bcrypt
    if ADMIN_PASSWORD_HASH.startswith("$2"):
        try:
            import bcrypt
            return bcrypt.checkpw(
                password.encode("utf-8"),
                ADMIN_PASSWORD_HASH.encode("utf-8"),
            )
        except ImportError:
            logger.error("bcrypt not installed — cannot verify password hash")
            return False
        except Exception as e:
            logger.error(f"Password verification error: {e}")
            return False

    # Fallback: plain-text comparison (dev/testing only)
    logger.warning("ADMIN_PASSWORD_HASH is not bcrypt — using plain comparison (dev mode)")
    return password == ADMIN_PASSWORD_HASH


def is_jwt_configured() -> bool:
    """Check if JWT auth is fully configured."""
    return bool(JWT_SECRET_KEY and ADMIN_PASSWORD_HASH)
