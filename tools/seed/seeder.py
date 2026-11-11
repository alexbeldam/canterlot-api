from datetime import UTC, datetime, timedelta

from beanie import Document, PydanticObjectId
from faker import Faker
from pydantic import HttpUrl

from canterlot.config import get_settings
from canterlot.emails import EmailCategory
from canterlot.hoodie import DatabaseManager, link_id
from canterlot.models import BookModel, CatalogEntryModel, ClubModel, UserModel
from canterlot.models.user import EmailPreferencesSchema, LinkedProviderSchema
from canterlot.types import (
    AuthProviderName,
    AvatarSchema,
    InviteType,
    JoinPolicy,
    MembershipStatus,
    RoundResolutionMethod,
    RoundSelectionMode,
    RoundStatus,
)
from canterlot.utils import get_logger, hash_password
from canterlot.utils.slugs import make_slug
from tools.factories import (
    BookFactory,
    CatalogEntryFactory,
    ClubFactory,
    ClubMembershipFactory,
    InviteFactory,
    ReadBookFactory,
    RoundCompletionFactory,
    RoundFactory,
    UserFactory,
)

logger = get_logger(__name__)

SEED_FAKER_SEED = 101010
SEED_PASSWORD = "Password123!"


def _get_id(doc: Document) -> PydanticObjectId:
    return PydanticObjectId(doc.id)


async def _slug_exists(slug: str) -> bool:
    return await ClubModel.find(ClubModel.slug == slug).exists()


async def _seed_books() -> tuple[BookModel, BookModel, list[BookModel]]:
    log = logger.bind(phase="books")
    log.info("Seeding books")

    flawless = await BookFactory.create_async(title="The Wandering Star")
    sparse = await BookFactory.create_async(
        title="A Book With No Cover",
        isbn_10=None,
        isbn_13=None,
        year=None,
        cover_url=None,
        urls={},
    )
    batch = await BookFactory.create_batch_async(size=25)

    log.info("Books seeded", flawless_id=str(flawless.id), sparse_id=str(sparse.id), batch_size=len(batch))
    return flawless, sparse, batch


async def _seed_users(now: datetime) -> dict[str, UserModel]:
    log = logger.bind(phase="users")
    log.info("Seeding users")

    auth_settings = get_settings().auth
    password_hash = hash_password(SEED_PASSWORD)
    legal_acceptance = {
        "accepted_terms_version": auth_settings.current_terms_version,
        "accepted_privacy_version": auth_settings.current_privacy_version,
    }

    standard = await UserFactory.create_async(
        name="Twilight Sparkle",
        username="twilight_sparkle",
        email="twilight.sparkle@seed.canterlot.dev",
        hashed_password=password_hash,
        **legal_acceptance,
    )

    unverified = await UserFactory.create_async(
        name="Applejack",
        username="applejack",
        email="applejack@seed.canterlot.dev",
        hashed_password=password_hash,
        email_preferences=EmailPreferencesSchema(verified_at=None),
        **legal_acceptance,
    )

    google_picture_url = HttpUrl(UserFactory.__faker__.image_url(width=300, height=300))
    oauth = await UserFactory.create_async(
        name="Rarity",
        username="rarity",
        email="rarity@seed.canterlot.dev",
        hashed_password=None,
        linked_providers=[
            LinkedProviderSchema(
                provider=AuthProviderName.GOOGLE,
                external_id="seed-google-rarity",
                picture_url=google_picture_url,
            )
        ],
        avatar=AvatarSchema(source=AuthProviderName.GOOGLE, value=google_picture_url),
        **legal_acceptance,
    )

    stale = await UserFactory.create_async(
        name="Rainbow Dash",
        username="rainbow_dash",
        email="rainbow.dash@seed.canterlot.dev",
        hashed_password=password_hash,
        accepted_terms_version=0,
        accepted_privacy_version=0,
    )

    hybrid = await UserFactory.create_async(
        name="Fluttershy",
        username="fluttershy",
        email="fluttershy@seed.canterlot.dev",
        hashed_password=password_hash,
        linked_providers=[
            LinkedProviderSchema(
                provider=AuthProviderName.GRAVATAR,
                external_id="seed-gravatar-fluttershy",
            )
        ],
        email_preferences=EmailPreferencesSchema(
            verified_at=now,
            categories_opt_out={EmailCategory.PROMOTIONAL: now},
            categories_system_suppressed={EmailCategory.TRANSACTIONAL: now},
        ),
        **legal_acceptance,
    )

    log.info("Users seeded", count=5)

    return {
        "standard": standard,
        "unverified": unverified,
        "oauth": oauth,
        "stale": stale,
        "hybrid": hybrid,
    }


async def _seed_clubs(users: dict[str, UserModel], batch_books: list[BookModel], now: datetime) -> list[ClubModel]:
    log = logger.bind(phase="clubs")
    log.info("Seeding clubs")

    standard_id = _get_id(users["standard"])
    stale_id = _get_id(users["stale"])
    unverified_id = _get_id(users["unverified"])
    oauth_id = _get_id(users["oauth"])
    hybrid_id = _get_id(users["hybrid"])

    public_hub = await ClubFactory.create_async(
        name="Public Hub",
        slug=await make_slug("Public Hub", _slug_exists),
        join_policy=JoinPolicy.PUBLIC,
        allow_suggestions=True,
    )
    for i, book in enumerate(batch_books[:10]):
        await CatalogEntryFactory.create_async(
            club=public_hub.to_link(),
            book=book.to_link(),
            suggested_by=UserModel.link_from_id(standard_id) if i % 2 == 0 else UserModel.link_from_id(stale_id),
            suggested_at=now - timedelta(days=i),
        )
    await ClubMembershipFactory.create_async(
        club=public_hub.to_link(),
        user=UserModel.link_from_id(standard_id),
        status=MembershipStatus.OWNER,
        joined_at=now,
    )
    await ClubMembershipFactory.create_async(
        club=public_hub.to_link(),
        user=UserModel.link_from_id(unverified_id),
        status=MembershipStatus.MEMBER,
        joined_at=now,
    )

    restricted_hierarchy = await ClubFactory.create_async(
        name="Restricted Hierarchy",
        slug=await make_slug("Restricted Hierarchy", _slug_exists),
        join_policy=JoinPolicy.RESTRICTED,
        allow_suggestions=True,
    )
    restricted_hierarchy_id = _get_id(restricted_hierarchy)
    for i, book in enumerate(batch_books[10:14]):
        await CatalogEntryFactory.create_async(
            club=ClubModel.link_from_id(restricted_hierarchy_id),
            book=book.to_link(),
            suggested_by=UserModel.link_from_id(unverified_id) if i % 2 == 0 else UserModel.link_from_id(oauth_id),
            suggested_at=now - timedelta(days=i * 3),
        )
    await ClubMembershipFactory.create_async(
        club=ClubModel.link_from_id(restricted_hierarchy_id),
        user=UserModel.link_from_id(standard_id),
        status=MembershipStatus.OWNER,
        joined_at=now,
    )
    await ClubMembershipFactory.create_async(
        club=ClubModel.link_from_id(restricted_hierarchy_id),
        user=UserModel.link_from_id(unverified_id),
        status=MembershipStatus.ADMIN,
        joined_at=now,
    )
    await ClubMembershipFactory.create_async(
        club=ClubModel.link_from_id(restricted_hierarchy_id),
        user=UserModel.link_from_id(oauth_id),
        status=MembershipStatus.MEMBER,
        joined_at=now,
    )
    await ClubMembershipFactory.create_async(
        club=ClubModel.link_from_id(restricted_hierarchy_id),
        user=UserModel.link_from_id(stale_id),
        status=MembershipStatus.BANNED,
    )
    await ClubMembershipFactory.create_async(
        club=ClubModel.link_from_id(restricted_hierarchy_id),
        user=UserModel.link_from_id(hybrid_id),
        status=MembershipStatus.PENDING,
        requested_at=now,
    )

    protected_transition = await ClubFactory.create_async(
        name="Protected Transition",
        slug=await make_slug("Protected Transition", _slug_exists),
        allow_suggestions=True,
        ownership_transferred_at=now - timedelta(days=2),
        protected_former_owner_id=standard_id,
    )
    protected_transition_id = _get_id(protected_transition)
    for i, book in enumerate(batch_books[14:18]):
        await CatalogEntryFactory.create_async(
            club=ClubModel.link_from_id(protected_transition_id),
            book=book.to_link(),
            suggested_by=UserModel.link_from_id(oauth_id) if i % 2 == 0 else UserModel.link_from_id(standard_id),
            suggested_at=now - timedelta(days=i * 2),
        )
    await ClubMembershipFactory.create_async(
        club=ClubModel.link_from_id(protected_transition_id),
        user=UserModel.link_from_id(oauth_id),
        status=MembershipStatus.OWNER,
        joined_at=now,
    )
    await ClubMembershipFactory.create_async(
        club=ClubModel.link_from_id(protected_transition_id),
        user=UserModel.link_from_id(standard_id),
        status=MembershipStatus.ADMIN,
        joined_at=now,
    )

    locked_queue = await ClubFactory.create_async(
        name="Locked Queue",
        slug=await make_slug("Locked Queue", _slug_exists),
        allow_suggestions=False,
    )
    await ClubMembershipFactory.create_async(
        club=locked_queue.to_link(),
        user=UserModel.link_from_id(standard_id),
        status=MembershipStatus.OWNER,
        joined_at=now,
    )

    clubs = [public_hub, restricted_hierarchy, protected_transition, locked_queue]
    log.info("Clubs seeded", count=len(clubs))
    return clubs


async def _seed_read_books(
    flawless_book: BookModel,
    sparse_book: BookModel,  # noqa: ARG001 - deliberately given zero ratings, kept for documentation
    batch_books: list[BookModel],
    users: dict[str, UserModel],
) -> None:
    log = logger.bind(phase="read_books")
    log.info("Seeding read books")

    standard_id = _get_id(users["standard"])
    unverified_id = _get_id(users["unverified"])
    oauth_id = _get_id(users["oauth"])
    flawless_id = _get_id(flawless_book)

    for user_id, rating in ((standard_id, 5.0), (unverified_id, 4.0), (oauth_id, 3.0)):
        await ReadBookFactory.create_async(
            user=UserModel.link_from_id(user_id),
            book=BookModel.link_from_id(flawless_id),
            rating=rating,
        )

    await ReadBookFactory.create_async(
        user=UserModel.link_from_id(standard_id),
        book=batch_books[0].to_link(),
        rating=None,
    )

    log.info("Read books seeded")


async def _catalog_book_ids(club: ClubModel) -> list[PydanticObjectId]:
    entries = await CatalogEntryModel.find({"club.$id": _get_id(club)}).sort("-suggested_at").to_list()
    return [link_id(entry.book) for entry in entries]


async def _seed_rounds(clubs: list[ClubModel], users: dict[str, UserModel], now: datetime) -> None:
    log = logger.bind(phase="rounds")
    log.info("Seeding reading rounds")

    public_hub, restricted_hierarchy, protected_transition, _locked_queue = clubs
    standard_id = _get_id(users["standard"])
    public_hub_latest_book_id = (await _catalog_book_ids(public_hub))[0]
    restricted_hierarchy_book_ids = await _catalog_book_ids(restricted_hierarchy)
    protected_transition_book_ids = await _catalog_book_ids(protected_transition)

    public_hub_round = await RoundFactory.create_async(
        club=public_hub.to_link(),
        started_by=UserModel.link_from_id(standard_id),
        selection_mode=RoundSelectionMode.RANDOM,
        status=RoundStatus.DECIDED,
        book=BookModel.link_from_id(public_hub_latest_book_id),
        candidate_pool=[],
        decided_at=now - timedelta(days=1),
    )
    await RoundCompletionFactory.create_async(
        club=public_hub.to_link(),
        round=public_hub_round.to_link(),
        book=BookModel.link_from_id(public_hub_latest_book_id),
        user=UserModel.link_from_id(standard_id),
    )

    await RoundFactory.create_async(
        club=restricted_hierarchy.to_link(),
        started_by=users["unverified"].to_link(),
        selection_mode=RoundSelectionMode.CURATED,
        status=RoundStatus.SETUP,
        book=None,
        candidate_pool=[BookModel.link_from_id(book_id) for book_id in restricted_hierarchy_book_ids],
    )

    await RoundFactory.create_async(
        club=protected_transition.to_link(),
        started_by=users["oauth"].to_link(),
        selection_mode=RoundSelectionMode.CURATED,
        status=RoundStatus.VOTING,
        resolution_method=RoundResolutionMethod.VOTE,
        book=None,
        candidate_pool=[BookModel.link_from_id(book_id) for book_id in protected_transition_book_ids],
    )

    log.info("Reading rounds seeded", count=3)


async def _seed_invites(clubs: list[ClubModel], users: dict[str, UserModel], now: datetime) -> None:
    log = logger.bind(phase="invites")
    log.info("Seeding invites")

    for club in clubs:
        await InviteFactory.create_async(club=ClubModel.link_from_id(_get_id(club)), type=InviteType.PUBLIC)

    restricted_hierarchy = clubs[1]
    await InviteFactory.create_async(
        club=restricted_hierarchy.to_link(),
        type=InviteType.DIRECT,
        created_by=users["standard"].to_link(),
        target_user=users["unverified"].to_link(),
        target_email=None,
        expires_at=now + timedelta(days=7),
    )

    log.info("Invites seeded", public_count=len(clubs), direct_count=1)


async def run_seed() -> None:
    Faker.seed(SEED_FAKER_SEED)
    now = datetime.now(UTC)

    settings = get_settings()
    async with DatabaseManager(
        settings.db.mongodb_url.get_secret_value(),
        settings.db.mongodb_db_name,
        polling=settings.hoodie,
    ) as db:
        await db.reset()

        flawless_book, sparse_book, batch_books = await _seed_books()
        users = await _seed_users(now)
        clubs = await _seed_clubs(users, batch_books, now)

        hybrid = users["hybrid"]
        hybrid.email_preferences.clubs_opt_out[_get_id(clubs[0])] = now
        await hybrid.save()

        await _seed_read_books(flawless_book, sparse_book, batch_books, users)
        await _seed_rounds(clubs, users, now)
        await _seed_invites(clubs, users, now)

    logger.info(
        "Seed complete",
        users=[user.username for user in users.values()],
        clubs=[club.slug for club in clubs],
        password=SEED_PASSWORD,
    )
