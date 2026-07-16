from dataclasses import dataclass
from typing import Protocol

from canterlot.models.enums import AuthProviderName
from canterlot.utils.format import NormalizedEmailStr


@dataclass(frozen=True)
class OAuthIdentity:
    external_id: str
    email: NormalizedEmailStr
    name: str | None = None
    picture: str | None = None


class OAuthProvider(Protocol):
    @property
    def name(self) -> AuthProviderName: ...

    @property
    def supports_avatar(self) -> bool: ...

    async def verify(self, credential: str, redirect_uri: str | None = None) -> OAuthIdentity: ...
