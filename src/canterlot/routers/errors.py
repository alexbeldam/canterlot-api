import logging

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from canterlot.exceptions import BusinessError
from canterlot.models import ErrorCode, ErrorDetail, ErrorResponseModel
from canterlot.utils import get_logger

logger = get_logger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(BusinessError)
    async def business_error_handler(_req: Request, exc: BusinessError) -> JSONResponse:
        payload = ErrorResponseModel(error=ErrorDetail(error_code=exc.error_code, message=exc.response_message))
        return JSONResponse(status_code=exc.status_code, content=jsonable_encoder(payload), headers=exc.headers)

    @app.exception_handler(Exception)
    async def global_unexpected_error_handler(_req: Request, exc: Exception) -> JSONResponse:
        logging.critical("Unhandled Exception caught in global gate: %s", str(exc), exc_info=True)

        payload = ErrorResponseModel(
            error=ErrorDetail(error_code=ErrorCode.INTERNAL_SERVER_ERROR, message="An unexpected error occurred.")
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=jsonable_encoder(payload),
        )
