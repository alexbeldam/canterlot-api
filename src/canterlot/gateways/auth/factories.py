from curl_cffi.requests import AsyncSession

from canterlot.config import get_settings
from canterlot.types import AuthProviderName
from canterlot.utils import get_logger

from .clients import GoogleAuthProvider, GravatarAuthProvider
from .interfaces import OAuthProvider

logger = get_logger(__name__)


def get_all_oauth_providers(session: AsyncSession) -> dict[AuthProviderName, OAuthProvider]:
    settings = get_settings()
    providers: dict[AuthProviderName, OAuthProvider] = {}

    if settings.google_oauth_client_id:
        logger.debug("Google OAuth provider configured and enabled")
        providers[AuthProviderName.GOOGLE] = GoogleAuthProvider(settings.google_oauth_client_id)
    else:
        logger.warn("Google OAuth client id not configured; Google sign-in will be unavailable")

    if settings.gravatar_oauth_client_id and settings.gravatar_oauth_client_secret:
        logger.debug("Gravatar OAuth provider configured and enabled")
        providers[AuthProviderName.GRAVATAR] = GravatarAuthProvider(
            settings.gravatar_oauth_client_id,
            settings.gravatar_oauth_client_secret,
            session,
        )
    else:
        logger.warn("Gravatar OAuth client id/secret not configured; Gravatar linking will be unavailable")

    return providers
