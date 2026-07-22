from canterlot.services.user import UserService
from canterlot.utils.security import UnsubscribeScope, decode_unsubscribe_token


class ProcessUnsubscribeUseCase:
    def __init__(self, user_service: UserService):
        self.__user_service = user_service

    async def execute(self, token: str) -> UnsubscribeScope:
        # ---------------------------------------------------------
        # 1. Decode & Cryptographically Verify Unsubscribe Token
        # ---------------------------------------------------------
        token_data = decode_unsubscribe_token(token)

        # ---------------------------------------------------------
        # 2. Persist Opt-Out & Invalidate Email Preferences Cache
        # ---------------------------------------------------------
        return await self.__user_service.process_unsubscribe(token_data)
