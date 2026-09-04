import asyncio
import logging
import sys

import structlog

from canterlot.config import get_settings
from canterlot.config.enums import Environment
from canterlot.utils import get_logger

from .seeder import run_seed

logger = get_logger(__name__)


def main() -> int:
    if get_settings().environment == Environment.PROD:
        logger.warning("Refusing to seed: environment is PROD.")
        return 1

    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.INFO))

    try:
        asyncio.run(run_seed())
    except Exception:
        logger.error("Seeding failed", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
