from enum import StrEnum


class Environment(StrEnum):
    DEV = "dev"
    PROD = "prod"
    LOCAL = "local"
    TEST = "test"
