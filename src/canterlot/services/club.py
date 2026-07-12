from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from beanie import PydanticObjectId

from canterlot.dto.club import ClubCreateRequest, ClubOnboarding
from canterlot.exceptions import (
    CannotTransferOwnershipToSelfError,
    ClubMemberNotFoundError,
    ClubNotFoundError,
    OwnershipReclaimWindowExpiredError,
    OwnershipTransferConflictError,
    OwnershipTransferCooldownError,
    PendingRequestNotFoundError,
    UnauthorizedClubMemberError,
)
from canterlot.models import (
    ClubModel,
    ClubOnboardingStatus,
    JoinPolicy,
    MemberRole,
    MemberSchema,
)
from canterlot.models.club import ClubSlugStr
from canterlot.models.user import UsernameStr
from canterlot.repositories import ClubRepository, UserRepository
from canterlot.utils import get_logger, make_slug
from canterlot.utils.format import LanguageStr

logger = get_logger(__name__)

_OWNERSHIP_TRANSFER_COOLDOWN = timedelta(days=30)
_OWNERSHIP_RECLAIM_WINDOW = timedelta(hours=24)


def _find_member(members: list[MemberSchema], user_id: PydanticObjectId) -> MemberSchema | None:
    return next((m for m in members if m.user_id == user_id), None)


def _find_owner(members: list[MemberSchema]) -> MemberSchema | None:
    return next((m for m in members if m.role == MemberRole.OWNER), None)


@dataclass
class ClubView:
    club: ClubModel
    member_usernames: dict[PydanticObjectId, UsernameStr]
    viewer_role: MemberRole
    # None unless the viewer is an OWNER/ADMIN — pending approvals are never resolved for anyone else.
    pending_usernames: dict[PydanticObjectId, UsernameStr] | None


class ClubService:
    def __init__(self, club_repo: ClubRepository, user_repo: UserRepository):
        self.__club_repo = club_repo
        self.__user_repo = user_repo

    async def create_new_club(self, creator_id: PydanticObjectId, data: ClubCreateRequest) -> ClubModel:
        log = logger.bind(creator_id=str(creator_id), club_name=data.name, join_policy=str(data.join_policy))
        log.info("Initiating new book club workspace creation")

        owner = MemberSchema(user_id=creator_id, role=MemberRole.OWNER)
        slug = await make_slug(data.name, self.__club_repo.exists_by_club_slug)

        club = ClubModel(
            name=data.name,
            slug=slug,
            description=data.description,
            join_policy=data.join_policy,
            preferred_languages=data.preferred_languages,
            members=[owner],
        )

        saved_club = await self.__club_repo.save(club)

        log.info("Book club workspace successfully created and persisted", club_id=str(saved_club.id))
        return saved_club

    async def admit_user(
        self,
        club_id: PydanticObjectId,
        user_id: PydanticObjectId,
        is_direct: bool = False,
    ) -> ClubOnboarding:
        log = logger.bind(club_id=str(club_id), user_id=str(user_id), is_direct_invite=is_direct)
        log.info("Processing user admission routine for club")

        club = await self.__club_repo.find_by_id(club_id)
        if not club:
            log.warn("Admission aborted: requested club node does not exist")
            raise ClubNotFoundError("This club no longer exists.")

        log = log.bind(club_name=club.name, club_join_policy=str(club.join_policy))
        status = None

        if await self.__club_repo.exists_by_club_id_and_member_user_id(club_id, user_id):
            log.info(
                "Admission short-circuited: user already holds a seat in this roster",
                status=ClubOnboardingStatus.ALREADY_MEMBER,
            )
            status = ClubOnboardingStatus.ALREADY_MEMBER
        elif is_direct or club.join_policy == JoinPolicy.PUBLIC:
            status = ClubOnboardingStatus.JOINED
            new_member = MemberSchema(user_id=user_id, role=MemberRole.MEMBER)
            await self.__club_repo.add_member(club_id, new_member)
            log.info("User successfully admitted into the club roster", status=status)
        else:
            status = ClubOnboardingStatus.PENDING_APPROVAL
            await self.__club_repo.add_to_pending_approvals(club_id, user_id)
            log.info("User profile successfully pushed into the club pending approval queue", status=status)

        return ClubOnboarding(club_name=club.name, status=status)

    async def get_preferred_languages(self, club_id: PydanticObjectId, user_id: PydanticObjectId) -> list[LanguageStr]:
        if not await self.__club_repo.exists_by_club_id_and_member_user_id(club_id, user_id):
            logger.bind(club_id=str(club_id), user_id=str(user_id)).warn(
                "Preferred languages lookup rejected: caller is not a club member"
            )
            raise UnauthorizedClubMemberError("Only members of this club can search for books to suggest.")

        return await self.__club_repo.get_preferred_languages_by_id(club_id)

    async def get_club_by_slug(self, slug: ClubSlugStr) -> ClubModel:
        club = await self.__club_repo.find_by_slug(slug)
        if not club:
            logger.bind(club_slug=slug).warn("Club lookup failed: no club with this slug exists")
            raise ClubNotFoundError(f"Club with slug '{slug}' not found")

        return club

    async def get_member_role(self, club_id: PydanticObjectId, user_id: PydanticObjectId) -> MemberRole | None:
        return await self.__club_repo.find_member_role_by_club_id_and_user_id(club_id, user_id)

    async def resolve_member_usernames(self, members: list[MemberSchema]) -> dict[PydanticObjectId, UsernameStr]:
        return await self.__user_repo.find_usernames_by_ids([member.user_id for member in members])

    async def get_club_view(self, slug: ClubSlugStr, viewer_id: PydanticObjectId) -> ClubView:
        club = await self.get_club_by_slug(slug)
        club_id = PydanticObjectId(club.id)

        viewer_role = await self.get_member_role(club_id, viewer_id)
        if viewer_role is None:
            logger.bind(club_id=str(club_id), viewer_id=str(viewer_id)).warn(
                "Club view rejected: caller is not a member of this club"
            )
            raise UnauthorizedClubMemberError("Only members of this club can view it.")

        member_usernames = await self.resolve_member_usernames(club.members)

        pending_usernames = None
        if viewer_role in (MemberRole.OWNER, MemberRole.ADMIN):
            pending_usernames = await self.__user_repo.find_usernames_by_ids(
                [pending.user_id for pending in club.pending_approvals]
            )

        return ClubView(
            club=club,
            member_usernames=member_usernames,
            viewer_role=viewer_role,
            pending_usernames=pending_usernames,
        )

    async def review_pending_request(
        self,
        club_id: PydanticObjectId,
        reviewer_id: PydanticObjectId,
        target_user_id: PydanticObjectId,
        approve: bool,
    ) -> None:
        log = logger.bind(
            club_id=str(club_id),
            reviewer_id=str(reviewer_id),
            target_user_id=str(target_user_id),
            approve=approve,
        )
        log.info("Reviewing pending club join request")

        reviewer_role = await self.get_member_role(club_id, reviewer_id)
        if reviewer_role not in (MemberRole.OWNER, MemberRole.ADMIN):
            log.warn("Review rejected: caller lacks OWNER/ADMIN privileges")
            raise UnauthorizedClubMemberError("Only an OWNER or ADMIN can review pending join requests.")

        if not await self.__club_repo.exists_by_club_id_and_pending_user_id(club_id, target_user_id):
            log.warn("Review rejected: target user has no pending request in this club")
            raise PendingRequestNotFoundError("This user has no pending join request for this club.")

        if approve:
            await self.__club_repo.add_member(club_id, MemberSchema(user_id=target_user_id, role=MemberRole.MEMBER))

        await self.__club_repo.remove_from_pending_approvals(club_id, target_user_id)
        log.info("Pending join request reviewed successfully", outcome="approved" if approve else "rejected")

    async def transfer_ownership(
        self,
        club_id: PydanticObjectId,
        current_owner_id: PydanticObjectId,
        target_user_id: PydanticObjectId,
    ) -> None:
        log = logger.bind(
            club_id=str(club_id),
            current_owner_id=str(current_owner_id),
            target_user_id=str(target_user_id),
        )
        log.info("Initiating club ownership transfer")

        club = await self.__club_repo.find_by_id(club_id)
        if not club:
            log.warn("Transfer rejected: club no longer exists")
            raise ClubNotFoundError("This club no longer exists.")

        now = datetime.now(UTC)
        self.__ensure_transfer_is_allowed(club, current_owner_id, target_user_id, now, log)

        transferred = await self.__club_repo.transfer_ownership(club_id, current_owner_id, target_user_id, now)
        if not transferred:
            log.warn("Transfer rejected: club membership changed before the transfer could complete")
            raise OwnershipTransferConflictError(
                "This club's membership changed before the transfer could complete; please retry."
            )

        log.info("Club ownership transferred successfully")

    def __ensure_transfer_is_allowed(
        self,
        club: ClubModel,
        current_owner_id: PydanticObjectId,
        target_user_id: PydanticObjectId,
        now: datetime,
        log,
    ) -> None:
        if target_user_id == current_owner_id:
            log.warn("Transfer rejected: cannot transfer ownership to yourself")
            raise CannotTransferOwnershipToSelfError("You cannot transfer ownership to yourself.")

        caller = _find_member(club.members, current_owner_id)
        if caller is None or caller.role != MemberRole.OWNER:
            log.warn("Transfer rejected: caller is not the club OWNER")
            raise UnauthorizedClubMemberError("Only the club OWNER can transfer ownership.")

        if _find_member(club.members, target_user_id) is None:
            log.warn("Transfer rejected: target user is not a member of this club")
            raise ClubMemberNotFoundError("This user is not a member of this club.")

        if target_user_id == club.protected_former_owner_id:
            return

        last_transfer = club.ownership_transferred_at
        if last_transfer is not None and now - last_transfer < _OWNERSHIP_TRANSFER_COOLDOWN:
            log.warn("Transfer rejected: new-owner cooldown is still active")
            raise OwnershipTransferCooldownError(
                "You must wait 30 days after receiving ownership before transferring it again."
            )

    async def reclaim_ownership(self, club_id: PydanticObjectId, caller_id: PydanticObjectId) -> None:
        log = logger.bind(club_id=str(club_id), caller_id=str(caller_id))
        log.info("Initiating ownership transfer reclaim")

        club = await self.__club_repo.find_by_id(club_id)
        if not club:
            log.warn("Reclaim rejected: club no longer exists")
            raise ClubNotFoundError("This club no longer exists.")

        if club.protected_former_owner_id != caller_id:
            log.warn("Reclaim rejected: caller is not the recorded former owner")
            raise UnauthorizedClubMemberError("You are not the recorded former owner of this club.")

        transferred_at = club.ownership_transferred_at
        current_owner = _find_owner(club.members)
        if transferred_at is None or current_owner is None:
            log.warn("Reclaim rejected: club ownership state is inconsistent")
            raise OwnershipTransferConflictError("This club's ownership state is inconsistent; please retry.")

        now = datetime.now(UTC)
        if now - transferred_at > _OWNERSHIP_RECLAIM_WINDOW:
            log.warn("Reclaim rejected: the 24-hour reclaim window has elapsed")
            raise OwnershipReclaimWindowExpiredError(
                "The 24-hour reclaim window has passed; ask the current owner to transfer it back."
            )

        reclaimed = await self.__club_repo.reclaim_ownership(club_id, caller_id, current_owner.user_id)
        if not reclaimed:
            log.warn("Reclaim rejected: club membership changed before the reclaim could complete")
            raise OwnershipTransferConflictError(
                "This club's membership changed before the reclaim could complete; please retry."
            )

        log.info("Ownership transfer reclaimed successfully")
