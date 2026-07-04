from canterlot.exceptions.base import ErrorCode
from canterlot.models.error import ErrorDetail, ErrorResponseModel


def describe_error_detail():
    def it_stamps_a_timestamp_by_default():
        detail = ErrorDetail(error_code=ErrorCode.BOOK_NOT_FOUND, message="Book not found.")
        assert detail.timestamp is not None
        assert detail.context is None


def describe_error_response_model():
    def it_wraps_an_error_detail():
        response = ErrorResponseModel(error=ErrorDetail(error_code=ErrorCode.BOOK_NOT_FOUND, message="Book not found."))
        assert response.error.error_code == ErrorCode.BOOK_NOT_FOUND
