"""Authentication module — supports Entra ID (Azure AD), local JWT, or no auth."""

import logging
from enum import Enum
from functools import lru_cache

import httpx
from fastapi import Depends, HTTPException, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)


class Role(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class CurrentUser(BaseModel):
    sub: str
    name: str
    email: str
    roles: list[Role]

    def has_role(self, role: Role) -> bool:
        return Role.ADMIN in self.roles or role in self.roles


# ── Entra ID JWKS (Azure AD public keys) ──

_jwks_cache: dict | None = None


async def _get_entra_jwks() -> dict:
    global _jwks_cache
    if _jwks_cache:
        return _jwks_cache
    url = (
        f"https://login.microsoftonline.com/{settings.entra_tenant_id}"
        f"/discovery/v2.0/keys"
    )
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        return _jwks_cache


def _find_signing_key(jwks: dict, kid: str) -> dict:
    for key in jwks.get("keys", []):
        if key["kid"] == kid:
            return key
    raise HTTPException(401, "Token signing key not found")


def _map_entra_roles(token_payload: dict) -> list[Role]:
    """Map Entra ID groups/roles claim to app roles."""
    roles = []
    groups = token_payload.get("groups", [])
    app_roles = token_payload.get("roles", [])

    if settings.entra_role_admin in groups or "admin" in app_roles:
        roles.append(Role.ADMIN)
    if settings.entra_role_operator in groups or "operator" in app_roles:
        roles.append(Role.OPERATOR)
    if settings.entra_role_viewer in groups or "viewer" in app_roles:
        roles.append(Role.VIEWER)

    if not roles:
        roles.append(Role.VIEWER)

    return roles


# ── Token Validation ──


async def _validate_entra_token(token: str) -> CurrentUser:
    """Validate a token issued by Entra ID / Azure AD."""
    try:
        unverified = jwt.get_unverified_header(token)
    except JWTError:
        raise HTTPException(401, "Invalid token header")

    jwks = await _get_entra_jwks()
    signing_key = _find_signing_key(jwks, unverified["kid"])

    try:
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=settings.entra_audience or settings.entra_client_id,
            issuer=f"https://login.microsoftonline.com/{settings.entra_tenant_id}/v2.0",
            options={"verify_at_hash": False},
        )
    except JWTError as e:
        raise HTTPException(401, f"Token validation failed: {e}")

    return CurrentUser(
        sub=payload.get("sub", payload.get("oid", "")),
        name=payload.get("name", ""),
        email=payload.get("preferred_username", payload.get("email", "")),
        roles=_map_entra_roles(payload),
    )


def _validate_local_token(token: str) -> CurrentUser:
    """Validate a locally-issued JWT (for local auth mode)."""
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.jwt_algorithm]
        )
    except JWTError as e:
        raise HTTPException(401, f"Token validation failed: {e}")

    return CurrentUser(
        sub=payload.get("sub", ""),
        name=payload.get("name", ""),
        email=payload.get("email", ""),
        roles=[Role(r) for r in payload.get("roles", ["viewer"])],
    )


# ── FastAPI Dependencies ──


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    if settings.auth_mode == "none":
        return CurrentUser(
            sub="anonymous",
            name="Anonymous",
            email="",
            roles=[Role.ADMIN],
        )

    if not creds:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = creds.credentials

    if settings.auth_mode == "entra_id":
        return await _validate_entra_token(token)
    elif settings.auth_mode == "local":
        return _validate_local_token(token)
    else:
        raise HTTPException(500, f"Unknown auth mode: {settings.auth_mode}")


async def get_ws_user(ws: WebSocket) -> CurrentUser:
    """Extract user from WebSocket query param: ?token=xxx"""
    if settings.auth_mode == "none":
        return CurrentUser(
            sub="anonymous", name="Anonymous", email="", roles=[Role.ADMIN]
        )

    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=4001, reason="Missing token query parameter")
        raise HTTPException(401, "Missing token")

    if settings.auth_mode == "entra_id":
        return await _validate_entra_token(token)
    elif settings.auth_mode == "local":
        return _validate_local_token(token)
    raise HTTPException(500, f"Unknown auth mode: {settings.auth_mode}")


def require_role(role: Role):
    """Dependency that enforces a minimum role."""
    async def _check(user: CurrentUser = Depends(get_current_user)):
        if not user.has_role(role):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Requires '{role.value}' role. Your roles: {[r.value for r in user.roles]}",
            )
        return user
    return _check


# ── Convenience dependencies ──

require_admin = require_role(Role.ADMIN)
require_operator = require_role(Role.OPERATOR)
require_viewer = require_role(Role.VIEWER)


# ── Local auth: issue tokens (only for auth_mode=local) ──


def create_local_token(sub: str, name: str, email: str, roles: list[str]) -> str:
    from datetime import datetime, timedelta, timezone
    payload = {
        "sub": sub,
        "name": name,
        "email": email,
        "roles": roles,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expiry_minutes),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
