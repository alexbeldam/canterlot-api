import asyncio
from asyncio import Lock
from dataclasses import dataclass
from typing import Any

import jwt
from curl_cffi.requests import AsyncSession
from fastapi import status

from canterlot.utils import get_logger

RISC_CONFIGURATION_URL = "https://accounts.google.com/.well-known/risc-configuration"

logger = get_logger(__name__)


class RiscVerificationError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class _RiscConfig:
    issuer: str
    jwk_client: jwt.PyJWKClient


class GoogleRiscVerifier:
    def __init__(self, client_id: str, session: AsyncSession):
        self.__client_id = client_id
        self.__session = session
        self.__config: _RiscConfig | None = None
        self.__config_lock = Lock()

    async def __get_config(self) -> _RiscConfig:
        if self.__config is not None:
            return self.__config

        async with self.__config_lock:
            if self.__config is not None:
                return self.__config

            log = logger.bind(url=RISC_CONFIGURATION_URL)
            log.info("Fetching Google's RISC discovery configuration")

            response = await self.__session.get(RISC_CONFIGURATION_URL)
            if response.status_code != status.HTTP_200_OK:
                log.warning("Failed to fetch Google's RISC configuration", http_status_code=response.status_code)
                raise RiscVerificationError("Could not fetch Google's RISC configuration.")

            document = response.json()
            self.__config = _RiscConfig(
                issuer=document["issuer"],
                jwk_client=jwt.PyJWKClient(document["jwks_uri"], cache_keys=True),
            )
            return self.__config

    async def verify(self, set_token: str) -> dict[str, Any]:
        log = logger.bind(provider="GOOGLE")
        log.info("Verifying Google RISC security event token")

        config = await self.__get_config()

        try:
            signing_key = await asyncio.to_thread(config.jwk_client.get_signing_key_from_jwt, set_token)
            claims = jwt.decode(
                set_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.__client_id,
                issuer=config.issuer,
                # Google's guidance is not to enforce `exp`.
                options={"verify_exp": False},
            )
        except jwt.PyJWTError as exc:
            log.warning("Google RISC token failed verification", error=str(exc))
            raise RiscVerificationError("The provided security event token could not be verified.") from exc

        log.info("Google RISC token successfully verified")
        return claims
