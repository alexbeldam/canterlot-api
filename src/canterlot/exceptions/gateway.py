from fastapi import status

from .base import BusinessError, ErrorCode


class GatewayConfigurationError(BusinessError):
    error_code = ErrorCode.GATEWAY_CONFIGURATION_ERROR
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    client_message = "Try again later."
