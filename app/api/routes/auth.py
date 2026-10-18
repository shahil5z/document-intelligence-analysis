from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies.auth import CurrentUser
from app.api.dependencies.rate_limit import (
    GLOBAL_IDENTIFIER,
    enforce_rate_limit,
    limit_by_ip,
    limit_by_user,
)
from app.api.dependencies.services import AuthServiceDep, DemoServiceDep
from app.api.dependencies.settings import AppSettings
from app.api.responses import error_responses
from app.core.config import Settings
from app.core.security import create_upload_token
from app.db.models import User
from app.schemas.auth import (
    DemoSessionResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UploadTokenResponse,
)
from app.schemas.user import DemoStatus, UserRead
from app.services.auth_service import normalize_email

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Creates a regular user account. Self-registration never grants the admin role.",
    responses=error_responses(409, 422, 429),
    dependencies=[Depends(limit_by_ip("register", "register_daily"))],
)
def register(body: RegisterRequest, auth: AuthServiceDep) -> UserRead:
    user = auth.register(email=body.email, password=body.password)
    return UserRead.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in with a JSON body",
    description="Exchange email and password for a short-lived JWT access token.",
    responses=error_responses(401, 403, 422, 429),
    dependencies=[Depends(limit_by_ip("login"))],
)
def login(request: Request, body: LoginRequest, auth: AuthServiceDep) -> TokenResponse:
    enforce_rate_limit(request, "login_per_email", normalize_email(body.email))
    issued = auth.login(email=body.email, password=body.password)
    return TokenResponse(access_token=issued.access_token, expires_in=issued.expires_in)


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Log in with an OAuth2 password form",
    description=(
        "OAuth2 password-flow endpoint (form fields `username` = email, `password`). "
        "Used by the Swagger UI *Authorize* dialog; behaves exactly like `/auth/login`."
    ),
    responses=error_responses(401, 403, 422, 429),
    dependencies=[Depends(limit_by_ip("login"))],
)
def token(
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    auth: AuthServiceDep,
) -> TokenResponse:
    enforce_rate_limit(request, "login_per_email", normalize_email(form.username))
    issued = auth.login(email=form.username, password=form.password)
    return TokenResponse(access_token=issued.access_token, expires_in=issued.expires_in)


@router.get(
    "/me",
    response_model=UserRead,
    summary="Current user",
    responses=error_responses(401, 403),
)
def me(user: CurrentUser, settings: AppSettings) -> UserRead:
    return user_read(user, settings)


def demo_status(user: User, settings: Settings) -> DemoStatus | None:
    if not user.is_demo:
        return None
    return DemoStatus(
        questions_used=user.demo_questions_used,
        questions_limit=settings.demo_max_questions,
        questions_remaining=max(0, settings.demo_max_questions - user.demo_questions_used),
        uploads_used=user.demo_uploads_used,
        uploads_limit=settings.demo_max_uploads,
        max_upload_bytes=min(settings.demo_max_upload_bytes, settings.max_upload_size_bytes),
        allowed_extensions=list(settings.demo_allowed_extensions),
        expires_at=user.demo_expires_at,
    )


def user_read(user: User, settings: Settings) -> UserRead:
    read = UserRead.model_validate(user)
    read.demo = demo_status(user, settings)
    return read


@router.post(
    "/demo",
    response_model=DemoSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a demo session",
    description=(
        "Creates an ephemeral, isolated demo account and returns its access token. Demo "
        "accounts cannot log in with a password, may upload one PDF (`DEMO_MAX_UPLOADS`, "
        "`DEMO_MAX_UPLOAD_BYTES`) and ask `DEMO_MAX_QUESTIONS` questions; beyond that the "
        "API answers 403 `demo_limit_reached`. They are deleted with their files after "
        "`DEMO_TTL_HOURS`. Rate-limited per client IP (`RATE_LIMIT_DEMO`) and globally "
        "(`RATE_LIMIT_DEMO_GLOBAL`)."
    ),
    responses=error_responses(403, 429, 503),
    dependencies=[Depends(limit_by_ip("demo"))],
)
def start_demo(
    request: Request, demo: DemoServiceDep, settings: AppSettings
) -> DemoSessionResponse:
    enforce_rate_limit(request, "demo_global", GLOBAL_IDENTIFIER)
    session = demo.create()
    status_ = demo_status(session.user, settings)
    if status_ is None:  # pragma: no cover - create() always makes a demo user
        raise RuntimeError("demo user expected")
    return DemoSessionResponse(
        access_token=session.access_token, expires_in=session.expires_in, demo=status_
    )


@router.post(
    "/demo/convert",
    response_model=UserRead,
    summary="Turn the current demo session into a free account",
    description=(
        "Sets an email and password on the demo account and removes its demo limits and "
        "expiry; uploaded documents are kept. Log in with the new credentials afterwards."
    ),
    responses=error_responses(401, 403, 409, 422, 429),
    dependencies=[Depends(limit_by_ip("register", "register_daily"))],
)
def convert_demo(
    body: RegisterRequest, user: CurrentUser, demo: DemoServiceDep, settings: AppSettings
) -> UserRead:
    return user_read(demo.convert(user, email=body.email, password=body.password), settings)


@router.post(
    "/upload-token",
    response_model=UploadTokenResponse,
    summary="Issue a short-lived upload-only token",
    description=(
        "Returns a bearer token (default lifetime 5 minutes, `UPLOAD_TOKEN_EXPIRE_SECONDS`) "
        "that is accepted only by `POST /documents`. A browser frontend whose session lives "
        "in a server-side proxy uses it to upload files directly to the API, so large "
        "uploads do not pass through the proxy. Requires a normal access token; an upload "
        "token cannot mint another one."
    ),
    responses=error_responses(401, 403, 429),
    dependencies=[Depends(limit_by_user("upload_token"))],
)
def upload_token(user: CurrentUser, settings: AppSettings) -> UploadTokenResponse:
    token, expires_in = create_upload_token(user_id=user.id, role=user.role, settings=settings)
    return UploadTokenResponse(upload_token=token, expires_in=expires_in)
