import asyncio

from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from canterlot.exceptions import InvalidOAuthCredentialError
from canterlot.models.enums import AuthProviderName
from canterlot.utils import get_logger

from .interfaces import OAuthIdentity, OAuthProvider

logger = get_logger(__name__)


class GoogleAuthProvider(OAuthProvider):
    def __init__(self, client_id: str):
        self.__client_id = client_id

    @property
    def name(self) -> AuthProviderName:
        return AuthProviderName.GOOGLE

    async def verify(self, credential: str) -> OAuthIdentity:
        log = logger.bind(provider=self.name)
        log.info("Verifying Google ID token against Google's public certificates")

        try:
            claims = await asyncio.to_thread(
                google_id_token.verify_oauth2_token,
                credential,
                google_requests.Request(),
                self.__client_id,
            )
        except (ValueError, GoogleAuthError) as exc:
            log.warn("Google ID token failed cryptographic verification", error=str(exc))
            raise InvalidOAuthCredentialError("The provided Google credential could not be verified.") from exc

        log.info("Google ID token successfully verified")
        return OAuthIdentity(
            external_id=claims["sub"],
            email=claims["email"],
            name=claims.get("name"),
        )
