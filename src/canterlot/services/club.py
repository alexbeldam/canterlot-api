from beanie import PydanticObjectId

from canterlot.exceptions import ClubNotFoundError
from canterlot.models import (
    ClubCreateRequest,
    ClubModel,
    ClubOnboarding,
    ClubOnboardingStatus,
    JoinPolicy,
    MemberSchema,
    UserRole,
)
from canterlot.repositories import ClubRepository
from canterlot.utils import get_logger

logger = get_logger(__name__)


class ClubService:
    def __init__(self, club_repo: ClubRepository):
        self.__club_repo = club_repo

    async def create_new_club(self, creator_id: PydanticObjectId, data: ClubCreateRequest) -> ClubModel:
        log = logger.bind(creator_id=str(creator_id), club_name=data.name, join_policy=str(data.join_policy))
        log.info("Initiating new book club workspace creation")

        owner = MemberSchema(user_id=creator_id, role=UserRole.OWNER)

        club = ClubModel(
            name=data.name,
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
            raise ClubNotFoundError(f"Club with ID '{club_id}' not found")

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
            new_member = MemberSchema(user_id=user_id, role=UserRole.USER)
            await self.__club_repo.add_member(club_id, new_member)
            log.info("User successfully admitted into the club roster", status=status)
        else:
            status = ClubOnboardingStatus.PENDING_APPROVAL
            await self.__club_repo.add_to_pending_approvals(club_id, user_id)
            log.info("User profile successfully pushed into the club pending approval queue", status=status)

        return ClubOnboarding(club_name=club.name, status=status)
