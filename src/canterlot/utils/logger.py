import logging
import sys

import structlog
from structlog.typing import Processor

from canterlot.config.enums import Environment

_UVICORN_ACCESS_ARGS_MIN_LEN = 3
_UVICORN_ACCESS_PATH_ARG_INDEX = 2

_NOISY_ACCESS_PATHS = {
    "/",
    "/v1",
    "/health",
    "/docs",
    "/redoc",
    "/favicon.ico",
    "/openapi.json",
}
_NOISY_ACCESS_PATH_PREFIXES = ("/static",)


class UvicornAccessPathFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access":
            return True

        if not isinstance(record.args, tuple) or len(record.args) < _UVICORN_ACCESS_ARGS_MIN_LEN:
            return True

        raw_path = record.args[_UVICORN_ACCESS_PATH_ARG_INDEX]
        if not isinstance(raw_path, str):
            return True

        path = raw_path.split("?", 1)[0]
        if path in _NOISY_ACCESS_PATHS:
            return False

        return not any(path == prefix or path.startswith(f"{prefix}/") for prefix in _NOISY_ACCESS_PATH_PREFIXES)


def setup_logging(environment: Environment) -> None:
    is_local = environment in (Environment.LOCAL, Environment.TEST)
    base_log_level = logging.DEBUG if is_local else logging.INFO

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.format_exc_info,
    ]

    formatter_processor = structlog.dev.ConsoleRenderer() if is_local else structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    console_handler = logging.StreamHandler(sys.stdout)

    console_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=formatter_processor,
            foreign_pre_chain=shared_processors,
        )
    )
    console_handler.addFilter(UvicornAccessPathFilter())

    target_loggers = ["", "uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"]
    for logger_name in target_loggers:
        logger_instance = logging.getLogger(logger_name)
        logger_instance.handlers = [console_handler]
        logger_instance.setLevel(base_log_level)
        logger_instance.propagate = False

    for library in ["pymongo", "beanie", "httpx", "httpcore"]:
        logging.getLogger(library).setLevel(logging.WARNING)


def get_logger(module_name: str):
    return structlog.get_logger(module_name)
