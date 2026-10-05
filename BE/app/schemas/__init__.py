"""Sprint-1 API contracts. Types only; endpoints come in later milestones."""

from app.schemas.common import Page, PageParams
from app.schemas.errors import ERROR_HTTP_STATUS, ErrorBody, ErrorCode, ErrorResponse

__all__ = [
    "ERROR_HTTP_STATUS",
    "ErrorBody",
    "ErrorCode",
    "ErrorResponse",
    "Page",
    "PageParams",
]
