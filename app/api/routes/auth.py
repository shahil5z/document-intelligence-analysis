from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies.auth import CurrentUser
from app.api.dependencies.rate_limit import enforce_rate_limit, limit_by_ip
from app.api.dependencies.services import AuthServiceDep
from app.api.dependencies.settings import AppSettings
from app.api.responses import error_responses
from app.core.security import create_upload_token
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UploadTokenResponse
from app.schemas.user import UserRead
from app.services.auth_service import normalize_email

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    description="Creates a regular user account. Self-registration never grants the admin role.",
    responses=error_responses(409, 422, 429),
    dependencies=[Depends(limit_by_ip("register"))],
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
def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


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
    responses=error_responses(401, 403),
)
def upload_token(user: CurrentUser, settings: AppSettings) -> UploadTokenResponse:
    token, expires_in = create_upload_token(user_id=user.id, role=user.role, settings=settings)
    return UploadTokenResponse(upload_token=token, expires_in=expires_in)
