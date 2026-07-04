from canterlot.exceptions.base import BusinessError, ErrorCode


def _error_body(error_code: ErrorCode, message: str) -> dict:
    return {"error": {"error_code": error_code.value, "message": message}}


def _readable_message(exc: type[BusinessError]) -> str:
    return exc.client_message or exc.error_code.value.replace("_", " ").capitalize() + "."


def error_example(*exceptions: type[BusinessError]) -> dict:
    """Build an OpenAPI `content` example so docs show a real error_code instead of the schema's default."""
    if len(exceptions) == 1:
        exc = exceptions[0]
        return {"application/json": {"example": _error_body(exc.error_code, _readable_message(exc))}}

    return {
        "application/json": {
            "examples": {
                exc.__name__: {"value": _error_body(exc.error_code, _readable_message(exc))} for exc in exceptions
            }
        }
    }


INTERNAL_SERVER_ERROR_EXAMPLE = {
    "application/json": {"example": _error_body(ErrorCode.INTERNAL_SERVER_ERROR, "An unexpected error occurred.")}
}
