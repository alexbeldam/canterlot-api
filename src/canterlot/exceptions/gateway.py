from fastapi import status

from .base import BusinessError, ErrorCode


class GatewayConfigurationError(BusinessError):
    error_code = ErrorCode.GATEWAY_CONFIGURATION_ERROR
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    client_message = "Try again later."
