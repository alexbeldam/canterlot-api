from fastapi import status

from .base import BusinessError, ErrorCode


class RateLimitExceededError(BusinessError):
    error_code = ErrorCode.RATE_LIMIT_EXCEEDED
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    client_message = "Too many requests. Please try again later."

    def __init__(self, retry_after_seconds: int):
        super().__init__()
        self.headers = {"Retry-After": str(retry_after_seconds)}
