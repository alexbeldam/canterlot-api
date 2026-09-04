from datetime import UTC, datetime, timedelta

from beanie import Document, PydanticObjectId
from faker import Faker
from pydantic import HttpUrl

from canterlot.config import get_settings
from canterlot.config.database import DatabaseManager
from canterlot.emails import EmailCategory
from canterlot.models import BEANIE_DOCUMENT_MODELS, BookModel, ClubModel, UserModel
from canterlot.models.book import ReadBook
from canterlot.models.club import CatalogEntryModel, PendingApprovalSchema
from canterlot.models.user import EmailPreferencesSchema, LinkedProviderSchema
from canterlot.types import AuthProviderName, AvatarSchema, InviteType, JoinPolicy, MemberRole, MemberSchema
from canterlot.utils import get_logger, hash_password
from canterlot.utils.slugs import make_slug
from tools.factories import BookFactory, ClubFactory, InviteFactory, UserFactory

logger = get_logger(__name__)

SEED_FAKER_SEED = 101010
SEED_PASSWORD = "Password123!"


def _get_id(doc: Document) -> PydanticObjectId:
    return PydanticObjectId(doc.id)


async def _slug_exists(slug: str) -> bool:
    return await ClubModel.find(ClubModel.slug == slug).exists()


async def _wipe_database(db: DatabaseManager) -> None:
    log = logger.bind(phase="wipe")
    log.info("Dropping all collections")

    for model in BEANIE_DOCUMENT_MODELS:
        await model.get_pymongo_collection().drop()

    await db.reinitialize_beanie()
    log.info("Collections dropped and indexes reinitialized")


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


async def _seed_users(read_candidates: list[BookModel], now: datetime) -> dict[str, UserModel]:
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
        books_read=[ReadBook(id=_get_id(book)) for book in read_candidates[:3]],
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

    public_catalog = [
        CatalogEntryModel(
            book_id=_get_id(book),
            suggested_by=standard_id if i % 2 == 0 else stale_id,
            suggested_at=now - timedelta(days=i),
        )
        for i, book in enumerate(batch_books[:10])
    ]

    public_hub = await ClubFactory.create_async(
        name="Public Hub",
        slug=await make_slug("Public Hub", _slug_exists),
        join_policy=JoinPolicy.PUBLIC,
        allow_suggestions=True,
        members=[MemberSchema(user_id=standard_id, role=MemberRole.OWNER)],
        catalog=public_catalog,
    )

    restricted_hierarchy = await ClubFactory.create_async(
        name="Restricted Hierarchy",
        slug=await make_slug("Restricted Hierarchy", _slug_exists),
        join_policy=JoinPolicy.RESTRICTED,
        allow_suggestions=True,
        members=[
            MemberSchema(user_id=standard_id, role=MemberRole.OWNER),
            MemberSchema(user_id=unverified_id, role=MemberRole.ADMIN),
            MemberSchema(user_id=oauth_id, role=MemberRole.MEMBER),
        ],
        banned_users=[stale_id],
        pending_approvals=[PendingApprovalSchema(user_id=hybrid_id)],
    )

    protected_transition = await ClubFactory.create_async(
        name="Protected Transition",
        slug=await make_slug("Protected Transition", _slug_exists),
        allow_suggestions=True,
        members=[
            MemberSchema(user_id=oauth_id, role=MemberRole.OWNER),
            MemberSchema(user_id=standard_id, role=MemberRole.ADMIN),
        ],
        ownership_transferred_at=now - timedelta(days=2),
        protected_former_owner_id=standard_id,
    )

    locked_queue = await ClubFactory.create_async(
        name="Locked Queue",
        slug=await make_slug("Locked Queue", _slug_exists),
        allow_suggestions=False,
        members=[MemberSchema(user_id=standard_id, role=MemberRole.OWNER)],
    )

    clubs = [public_hub, restricted_hierarchy, protected_transition, locked_queue]
    log.info("Clubs seeded", count=len(clubs))
    return clubs


async def _seed_invites(clubs: list[ClubModel], users: dict[str, UserModel], now: datetime) -> None:
    log = logger.bind(phase="invites")
    log.info("Seeding invites")

    for club in clubs:
        await InviteFactory.create_async(club_id=_get_id(club), type=InviteType.PUBLIC)

    restricted_hierarchy = clubs[1]
    await InviteFactory.create_async(
        club_id=_get_id(restricted_hierarchy),
        type=InviteType.DIRECT,
        created_by=_get_id(users["standard"]),
        target_user_id=_get_id(users["unverified"]),
        target_email=None,
        expires_at=now + timedelta(days=7),
    )

    log.info("Invites seeded", public_count=len(clubs), direct_count=1)


async def run_seed() -> None:
    Faker.seed(SEED_FAKER_SEED)
    now = datetime.now(UTC)

    async with DatabaseManager() as db:
        await _wipe_database(db)

        _flawless_book, _sparse_book, batch_books = await _seed_books()
        users = await _seed_users(batch_books, now)
        clubs = await _seed_clubs(users, batch_books, now)

        hybrid = users["hybrid"]
        hybrid.email_preferences.clubs_opt_out[_get_id(clubs[0])] = now
        await hybrid.save()

        await _seed_invites(clubs, users, now)

    logger.info(
        "Seed complete",
        users=[user.username for user in users.values()],
        clubs=[club.slug for club in clubs],
        password=SEED_PASSWORD,
    )
