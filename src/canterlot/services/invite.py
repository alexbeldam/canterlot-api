from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from beanie import PydanticObjectId

from canterlot.dto.invite import InvitePreviewResponse
from canterlot.exceptions import (
    ClubNotFoundError,
    DirectInviteIdentityMismatchError,
    InvalidInviteTokenError,
    InviteLinkDeactivatedError,
    UnauthorizedClubMemberError,
)
from canterlot.models.club import ClubNameStr
from canterlot.models.invite import InviteModel
from canterlot.models.user import UsernameStr
from canterlot.repositories import ClubRepository, InviteRepository, UserRepository
from canterlot.types import InviteType, MemberRole, NormalizedEmailStr
from canterlot.utils import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class InviteValidationResult:
    club_id: PydanticObjectId
    club_name: ClubNameStr
    invited_by: UsernameStr | None
    is_direct: bool


class InviteService:
    def __init__(
        self,
        invite_repo: InviteRepository,
        club_repo: ClubRepository,
        user_repo: UserRepository,
    ):
        self.__invite_repo = invite_repo
        self.__club_repo = club_repo
        self.__user_repo = user_repo

    async def get_preview_metadata(
        self, invite_id: str, invited_by: UsernameStr | None = None
    ) -> InvitePreviewResponse:
        log = logger.bind(invite_id=invite_id)
        log.info("Fetching stateful token preview metadata")

        invite = await self.__invite_repo.find_by_id(invite_id)
        if not invite:
            log.warn("Preview aborted: metadata fetch failed because token does not exist")
            raise InvalidInviteTokenError("Invalid or unrecognized invitation link.")

        log = log.bind(club_id=str(invite.club_id), invite_type=str(invite.type))

        if not invite.is_active:
            log.warn("Preview aborted: invitation token is soft-deactivated")
            raise InviteLinkDeactivatedError("This invitation link has been deactivated or rotated by an admin.")

        if invite.expires_at and invite.expires_at < datetime.now(UTC):
            log.warn("Preview aborted: token validity window has closed")
            raise InviteLinkDeactivatedError("This invitation link has expired.")

        club = await self.__club_repo.find_by_id(invite.club_id)
        if not club or not club.id:
            log.warn("Preview aborted: relational parent club record is missing from database")
            raise ClubNotFoundError("The club associated with this invitation does not exist.")

        inviter_username = await self.__resolve_inviter_username(invite, invited_by)

        log.info("Preview metadata successfully built and dispatched")
        return InvitePreviewResponse(
            club_slug=club.slug,
            club_name=club.name,
            join_policy=club.join_policy,
            invite_type=invite.type,
            invited_by_username=inviter_username,
        )

    async def validate_incoming_invite(
        self,
        invite_id: str,
        user_email: NormalizedEmailStr | None = None,
        invited_by: UsernameStr | None = None,
    ) -> InviteValidationResult:
        log = logger.bind(invite_id=invite_id, target_email=user_email)
        log.info("Executing strict entry point validation for incoming token")

        invite = await self.__invite_repo.find_by_id(invite_id)
        if not invite:
            log.warn("Validation failed: token does not exist")
            raise InvalidInviteTokenError("Invalid or unrecognized invitation link.")
        if not invite.is_active:
            log.warn("Validation failed: token is deactivated")
            raise InviteLinkDeactivatedError("This invitation link is invalid or deactivated.")

        log = log.bind(club_id=str(invite.club_id), invite_type=str(invite.type))
        self.__assert_not_expired(invite, log)

        club_name = await self.__club_repo.find_club_name_by_id(invite.club_id)
        if not club_name:
            log.warn("Validation failed: destination club no longer exists")
            raise ClubNotFoundError("Target club does not exist.")

        is_direct = invite.type == InviteType.DIRECT
        self.__assert_direct_identity_matches(invite, is_direct, user_email, log)
        inviter_username = await self.__resolve_inviter_username(invite, invited_by)

        log.info("Entry ticket criteria passed, staging domain context results metadata")
        return InviteValidationResult(
            club_id=invite.club_id,
            club_name=club_name,
            invited_by=inviter_username,
            is_direct=is_direct,
        )

    def __assert_not_expired(self, invite: InviteModel, log) -> None:
        if invite.expires_at and invite.expires_at < datetime.now(UTC):
            log.warn("Validation failed: ticket lifetime exceeded")
            raise InviteLinkDeactivatedError("This invitation link has expired.")

    def __assert_direct_identity_matches(
        self,
        invite: InviteModel,
        is_direct: bool,
        user_email: NormalizedEmailStr | None,
        log,
    ) -> None:
        if is_direct and (not user_email or invite.target_email != user_email):
            log.warn(
                "Security Alert: Identity mismatch during direct admission attempt",
                expected_email=invite.target_email,
            )
            raise DirectInviteIdentityMismatchError("This invite belongs to another user.")

    async def __resolve_inviter_username(
        self,
        invite: InviteModel,
        invited_by: UsernameStr | None,
    ) -> UsernameStr | None:
        if invite.created_by:
            return await self.__user_repo.find_username_by_id(invite.created_by)
        if invited_by and await self.__user_repo.exists_by_username(invited_by.lower()):
            return invited_by
        return None

    async def rotate_public_link(self, club_id: PydanticObjectId, user_id: PydanticObjectId) -> str:
        log = logger.bind(club_id=str(club_id), authorized_by=str(user_id))
        log.info("Executing public linkage rotation routine sequence")

        await self.__verify_privileged_role(club_id=club_id, user_id=user_id)
        await self.__invite_repo.deactivate_all_public_by_club_id(club_id)

        new_invite = InviteModel(club_id=club_id)
        saved = await self.__invite_repo.save(new_invite)

        log.info("New public shortUUID access link deployed successfully", new_invite_id=str(saved.id))

        return saved.id

    async def get_public_link(self, club_id: PydanticObjectId) -> str:
        log = logger.bind(club_id=str(club_id))
        log.info("Fetching current active public link reference")

        invite = await self.__invite_repo.find_one_active_public_by_club_id(club_id)
        if not invite:
            log.warn("Public link lookup failed: no active token mapped for this club")
            raise InviteLinkDeactivatedError("This club has no active public link.")

        return invite.id

    async def create_direct_invite(
        self,
        club_id: PydanticObjectId,
        issuer_id: PydanticObjectId,
        target_email: NormalizedEmailStr,
    ) -> str:
        log = logger.bind(club_id=str(club_id), issuer_id=str(issuer_id), destination_email=target_email)
        log.info("Issuing secure identity-bound direct invite key")

        await self.__verify_privileged_role(club_id=club_id, user_id=issuer_id)
        await self.__invite_repo.deactivate_all_direct_by_club_id_and_target_email(club_id, target_email)

        now = datetime.now(UTC)
        expires_at = now + timedelta(weeks=1)

        invite = InviteModel(
            club_id=club_id,
            created_by=issuer_id,
            target_email=target_email,
            type=InviteType.DIRECT,
            created_at=now,
            expires_at=expires_at,
        )

        saved = await self.__invite_repo.save(invite)

        log.info("Direct secure single-use token registered and live", direct_invite_id=saved.id)
        return saved.id

    async def register_invite_usage(self, invite_id: str) -> None:
        log = logger.bind(invite_id=invite_id)
        log.info("Registering invite metrics consumption transaction")

        invite = await self.__invite_repo.find_by_id(invite_id)
        if not invite:
            log.debug("Aborting usage registration: tracking record missing from database index")
            return

        await self.__invite_repo.increment_uses_count_by_id(invite.id)

        if invite.type == InviteType.DIRECT:
            await self.__invite_repo.deactivate_by_id(invite.id)
            log.info("Direct single-use token burned successfully")
        else:
            log.info("Generic token usage count metric incremented")

    async def __verify_privileged_role(self, club_id: PydanticObjectId, user_id: PydanticObjectId):
        role = await self.__club_repo.find_member_role_by_club_id_and_user_id(club_id, user_id)

        if not role or role not in [MemberRole.OWNER, MemberRole.ADMIN]:
            logger.warn(
                "Access Denied: administrative scope escalation attempt intercepted",
                club_id=str(club_id),
                user_id=str(user_id),
                resolved_role=str(role) if role else None,
            )
            raise UnauthorizedClubMemberError("Administrative privileges required.")
