from fastapi import APIRouter, HTTPException, Request, Response, status

from app.core.schemas import AuthSessionResponse, LoginRequest
from app.services.browser_security import (
    SESSION_COOKIE,
    issue_session,
    origin_is_allowed,
    password_matches,
    verify_session,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/session", response_model=AuthSessionResponse)
async def session_status(request: Request) -> AuthSessionResponse:
    settings = request.app.state.settings
    if not settings.public_mode:
        return AuthSessionResponse(required=False, authenticated=True)
    authenticated = verify_session(
        settings, request.cookies.get(SESSION_COOKIE)
    ) is not None
    return AuthSessionResponse(required=True, authenticated=authenticated)


@router.post("/login", response_model=AuthSessionResponse)
async def login(body: LoginRequest, request: Request, response: Response) -> AuthSessionResponse:
    settings = request.app.state.settings
    if not origin_is_allowed(
        request.headers.get("origin"), request.headers.get("host"), settings
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin is not allowed")
    if not settings.public_mode:
        return AuthSessionResponse(required=False, authenticated=True)

    remote = request.client.host if request.client else "unknown"
    allowed = await request.app.state.rate_limiter.allow(
        f"login:{remote}", settings.login_attempts_per_minute
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts; try again shortly",
            headers={"Retry-After": "60"},
        )
    if not password_matches(settings, body.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")

    token, _session_id, _expires_at = issue_session(settings)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=settings.browser_session_ttl_seconds,
        httponly=True,
        secure=settings.public_mode,
        samesite="strict",
        path="/",
    )
    return AuthSessionResponse(required=True, authenticated=True)


@router.post("/logout", response_model=AuthSessionResponse)
async def logout(request: Request, response: Response) -> AuthSessionResponse:
    settings = request.app.state.settings
    if not origin_is_allowed(
        request.headers.get("origin"), request.headers.get("host"), settings
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin is not allowed")
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=settings.public_mode,
        samesite="strict",
    )
    return AuthSessionResponse(required=settings.public_mode, authenticated=not settings.public_mode)
