from canterlot.config import get_settings
from canterlot.models.enums import AuthProviderName

from .google import GoogleAuthProvider
from .interfaces import OAuthProvider


def get_all_oauth_providers() -> dict[AuthProviderName, OAuthProvider]:
    client_id = get_settings().google_oauth_client_id
    if not client_id:
        return {}

    return {AuthProviderName.GOOGLE: GoogleAuthProvider(client_id)}
