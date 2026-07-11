from canterlot.config import get_settings
from canterlot.models.enums import AuthProviderName
from canterlot.utils import get_logger

from .google import GoogleAuthProvider
from .interfaces import OAuthProvider

logger = get_logger(__name__)


def get_all_oauth_providers() -> dict[AuthProviderName, OAuthProvider]:
    client_id = get_settings().google_oauth_client_id
    if not client_id:
        logger.warn("Google OAuth client id not configured; Google sign-in will be unavailable")
        return {}

    logger.info("Google OAuth provider configured and enabled")
    return {AuthProviderName.GOOGLE: GoogleAuthProvider(client_id)}
