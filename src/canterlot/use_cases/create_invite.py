from typing import cast

from beanie import PydanticObjectId

from canterlot.dto.invite import CreateInviteRequest, InviteTokenResponse
from canterlot.emails.core.definitions import EmailTaskPayload, Templates
from canterlot.emails.core.schemas import InviteExternalContext, InviteInternalContext
from canterlot.models import ClubModel, UserModel
from canterlot.services.dispatch import EmailDispatchService
from canterlot.services.invite import InviteService
from canterlot.services.user import UserService
from canterlot.types import InviteType, NormalizedEmailStr, UsernameStr


class CreateInviteUseCase:
    def __init__(
        self,
        invite_service: InviteService,
        user_service: UserService,
        email_dispatch: EmailDispatchService,
    ):
        self.__invite_service = invite_service
        self.__user_service = user_service
        self.__email_dispatch = email_dispatch

    async def execute(
        self,
        club: ClubModel,
        issuer: UserModel,
        payload: CreateInviteRequest,
    ) -> InviteTokenResponse:
        club_id = PydanticObjectId(club.id)
        issuer_id = PydanticObjectId(issuer.id)

        # ---------------------------------------------------------
        # 1. Public Link Rotation (No Email Dispatched)
        # ---------------------------------------------------------
        if payload.type is InviteType.PUBLIC:
            token = await self.__invite_service.rotate_public_link(
                club_id=club_id,
                user_id=issuer_id,
            )
            return InviteTokenResponse(invite_token=token)

        # ---------------------------------------------------------
        # 2. External Invite (Recipient has no account yet)
        # ---------------------------------------------------------
        if payload.email:
            target_email = cast(NormalizedEmailStr, payload.email)
            invite = await self.__invite_service.create_external_invite(
                club_id=club_id,
                issuer_id=issuer_id,
                target_email=target_email,
            )

            external_context = InviteExternalContext.from_domain(
                inviter=issuer,
                club=club,
                invite=invite,
            )

            external_task = EmailTaskPayload(
                template=Templates.CELESTIA_INVITE_EXTERNAL,
                to=target_email,
                context=external_context,
            )

            await self.__email_dispatch.dispatch(task=external_task)
            return InviteTokenResponse(invite_token=invite)

        # ---------------------------------------------------------
        # 3. Internal Invite (Recipient exists in system)
        # ---------------------------------------------------------
        target_user = await self.__user_service.get_by_username(cast(UsernameStr, payload.username))

        invite = await self.__invite_service.create_internal_invite(
            club_id=club_id,
            issuer_id=issuer_id,
            target_user_id=PydanticObjectId(target_user.id),
        )

        internal_context = InviteInternalContext.from_domain(
            recipient=target_user,
            inviter=issuer,
            club=club,
            invite=invite,
        )

        internal_task = EmailTaskPayload(
            template=Templates.CELESTIA_INVITE_INTERNAL,
            to=target_user.email,
            context=internal_context,
        )

        await self.__email_dispatch.dispatch(task=internal_task, prefs=target_user.email_preferences)

        return InviteTokenResponse(invite_token=invite)
