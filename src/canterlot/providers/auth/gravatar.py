from curl_cffi.requests import AsyncSession
from fastapi import status

from canterlot.exceptions import InvalidOAuthCredentialError
from canterlot.models.enums import AuthProviderName
from canterlot.utils import get_logger

from .interfaces import OAuthIdentity, OAuthProvider

TOKEN_URL = "https://public-api.wordpress.com/oauth2/token"
ME_URL = "https://public-api.wordpress.com/rest/v1.1/me"

logger = get_logger(__name__)


class GravatarAuthProvider(OAuthProvider):
    def __init__(self, client_id: str, client_secret: str, session: AsyncSession):
        self.__client_id = client_id
        self.__client_secret = client_secret
        self.__session = session

    @property
    def name(self) -> AuthProviderName:
        return AuthProviderName.GRAVATAR

    @property
    def supports_avatar(self) -> bool:
        return True

    async def verify(self, credential: str, redirect_uri: str | None = None) -> OAuthIdentity:
        log = logger.bind(provider=self.name)

        if not redirect_uri:
            log.warn("Gravatar verification rejected: no redirect_uri supplied for the authorization-code exchange")
            raise InvalidOAuthCredentialError("A redirect_uri is required to complete Gravatar authorization.")

        log.info("Exchanging Gravatar authorization code for an access token")
        token_response = await self.__session.post(
            TOKEN_URL,
            data={
                "client_id": self.__client_id,
                "client_secret": self.__client_secret,
                "code": credential,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        access_token = None
        if token_response.status_code == status.HTTP_200_OK:
            access_token = token_response.json().get("access_token")
        if not access_token:
            log.warn("Gravatar authorization code exchange failed", http_status_code=token_response.status_code)
            raise InvalidOAuthCredentialError("The provided Gravatar authorization code could not be verified.")

        log.info("Fetching the linked Gravatar account's profile")
        me_response = await self.__session.get(ME_URL, headers={"Authorization": f"Bearer {access_token}"})
        if me_response.status_code != status.HTTP_200_OK:
            log.warn("Gravatar profile fetch failed", http_status_code=me_response.status_code)
            raise InvalidOAuthCredentialError("Could not fetch the linked Gravatar account's profile.")

        profile = me_response.json()
        if not profile.get("verified"):
            log.warn("Gravatar reported this account's email as unverified", email=profile.get("email"))
            raise InvalidOAuthCredentialError("Gravatar has not verified this account's email address.")

        log.info("Gravatar identity successfully verified")
        return OAuthIdentity(
            external_id=str(profile["ID"]),
            email=profile["email"],
            name=profile.get("display_name"),
            picture=profile.get("avatar_URL"),
        )
