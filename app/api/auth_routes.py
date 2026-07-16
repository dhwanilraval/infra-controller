"""Auth endpoints — login (local mode), token info, Entra ID config for frontends."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import CurrentUser, create_local_token, get_current_user
from app.config import settings

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AuthConfigResponse(BaseModel):
    auth_mode: str
    entra_tenant_id: str | None = None
    entra_client_id: str | None = None
    authority: str | None = None
    scopes: list[str] | None = None


@router.get("/config", response_model=AuthConfigResponse)
async def get_auth_config():
    """Public endpoint — returns auth config for frontend clients."""
    if settings.auth_mode == "entra_id":
        return AuthConfigResponse(
            auth_mode="entra_id",
            entra_tenant_id=settings.entra_tenant_id,
            entra_client_id=settings.entra_client_id,
            authority=f"https://login.microsoftonline.com/{settings.entra_tenant_id}",
            scopes=[f"api://{settings.entra_client_id}/.default"],
        )
    return AuthConfigResponse(auth_mode=settings.auth_mode)


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    """Local auth only — issues a JWT. Disabled when using Entra ID."""
    if settings.auth_mode != "local":
        raise HTTPException(400, "Login endpoint is only available in local auth mode")

    if req.username == "admin" and req.password == settings.secret_key:
        token = create_local_token(
            sub="admin", name="Admin", email="admin@local", roles=["admin"]
        )
        return TokenResponse(access_token=token)

    raise HTTPException(401, "Invalid credentials")


@router.get("/me")
async def get_me(user: CurrentUser = Depends(get_current_user)):
    return {
        "sub": user.sub,
        "name": user.name,
        "email": user.email,
        "roles": [r.value for r in user.roles],
    }
