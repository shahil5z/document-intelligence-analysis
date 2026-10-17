"""Per-request context (request id, user id, document id) carried via a ContextVar.

A single mutable ``RequestContext`` object is created per request by the request-id
middleware. Because FastAPI runs sync dependencies and routes in a threadpool with a
*copy* of the context, the object (not the ContextVar value) is mutated so that values
set inside a dependency (e.g. the authenticated user id) are visible to later log calls.
"""

import re
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


@dataclass
class RequestContext:
    request_id: str
    user_id: str | None = None
    document_id: str | None = None


_current: ContextVar[RequestContext | None] = ContextVar("request_context", default=None)


def new_request_id() -> str:
    return str(uuid.uuid4())


def sanitize_request_id(candidate: str | None) -> str:
    """Accept a client-supplied id only if it matches a conservative pattern, else generate one."""
    if candidate and _SAFE_REQUEST_ID.fullmatch(candidate):
        return candidate
    return new_request_id()


def bind_context(context: RequestContext) -> Token[RequestContext | None]:
    return _current.set(context)


def reset_context(token: Token[RequestContext | None]) -> None:
    _current.reset(token)


def get_context() -> RequestContext | None:
    return _current.get()


def get_request_id() -> str | None:
    context = _current.get()
    return context.request_id if context else None


def set_user_id(user_id: str) -> None:
    context = _current.get()
    if context is not None:
        context.user_id = user_id


def set_document_id(document_id: str) -> None:
    context = _current.get()
    if context is not None:
        context.document_id = document_id
