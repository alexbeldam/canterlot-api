import asyncio
import logging
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from beanie import PydanticObjectId
from beanie.operators import In, Or, RegEx
from pydantic import HttpUrl

from canterlot.config import get_settings
from canterlot.config.database import DatabaseManager
from canterlot.config.enums import Environment
from canterlot.dto.auth import UserRegisterRequest
from canterlot.dto.club import ClubCreateRequest, ClubSettingsUpdateRequest
from canterlot.models import BookModel, ClubModel, InviteModel, JoinPolicy, MemberRole, UserModel
from canterlot.models.book import BookProviderIdentifier
from canterlot.models.club import CatalogEntryModel
from canterlot.models.user import LinkedProviderSchema
from canterlot.repositories.beanie import (
    BeanieBookRepository,
    BeanieClubRepository,
    BeanieInviteRepository,
    BeanieUserRepository,
)
from canterlot.services import AuthService, ClubService, InviteService
from canterlot.types import AuthProviderName, BookProviderName

# This goes through the same ClubService/InviteService calls the real routers use, so a freshly
# seeded club ends up in exactly the state a club created through the API would be in (e.g. it
# already has an active public invite, because create_club always rotates one on the way out).

SEED_PASSWORD = "Password123!"
SEED_EMAIL_DOMAIN = "seed.canterlot.dev"
LINKED_GOOGLE_USERNAME = "rarity"
LINKED_GOOGLE_PICTURE_URL = HttpUrl("https://seed.canterlot.dev/avatars/rarity.jpg")
DIRECT_INVITE_EMAIL = f"new.reader@{SEED_EMAIL_DOMAIN}"

SEED_USERS: list[tuple[str, str]] = [
    ("twilightsparkle", "Twilight Sparkle"),
    ("applejack", "Applejack"),
    ("rarity", "Rarity"),
    ("rainbowdash", "Rainbow Dash"),
    ("pinkiepie", "Pinkie Pie"),
]


@dataclass(frozen=True, slots=True)
class SeedBook:
    title: str
    authors: list[str]
    year: int
    isbn_10: str | None = None
    isbn_13: str | None = None


# Deliberately out of alphabetical AND chronological order, so sorting by title/year/suggested_at
# each produce a visibly different page ordering. The first two carry an ISBN so /books/{identifier}
# and friends can also be exercised by ISBN, not just by external_id.
CLUB_A_BOOKS: list[SeedBook] = [
    SeedBook("The Wandering Star", ["Luna Nightshade"], 2018, isbn_10="0306406152"),
    SeedBook("A History of Everfree Forest", ["Zecora Hex"], 2009, isbn_13="9783161484100"),
    SeedBook("Ponyville Under Siege", ["Applejack"], 2015),
    SeedBook("Zephyr Winds", ["Rainbow Dash"], 2021),
    SeedBook("Moonlit Manuscripts", ["Twilight Sparkle"], 1998),
    SeedBook("Diamonds of Canterlot", ["Rarity"], 2012),
    SeedBook("Cakes and Kingdoms", ["Pinkie Pie"], 2019),
    SeedBook("The Last Alicorn", ["Starswirl the Bearded"], 1972),
    SeedBook("Elements of Harmony", ["Twilight Sparkle"], 2010),
    SeedBook("Griffonstone Chronicles", ["Gilda Griff"], 2016),
    SeedBook("Sonic Rainboom Theory", ["Rainbow Dash"], 2020),
    SeedBook("The Bookworm's Guide", ["Bookworm99"], 2005),
    SeedBook("Whispers of the Crystal Empire", ["Sunburst Mage"], 2014),
    SeedBook("Yakyakistan Travels", ["Prince Rutherford"], 2017),
    SeedBook("Silver Shoes, Golden Dreams", ["Applejack"], 2011),
    SeedBook("Under Canterlot Skies", ["Princess Celestia"], 1995),
    SeedBook("Feathers and Fables", ["Fluttershy Meadow"], 2013),
    SeedBook("The Mareionette Theatre", ["Coco Pommel"], 2008),
    SeedBook("Storm Over Cloudsdale", ["Rainbow Dash"], 2022),
    SeedBook("Roots of the Everfree", ["Zecora Hex"], 2001),
    SeedBook("Kingdom of Two Sisters", ["Princess Luna"], 1987),
    SeedBook("Journal of the Six", ["Twilight Sparkle"], 2010),
    SeedBook("Xylophone Serenade", ["Octavia Melody"], 2006),
    SeedBook("Vault of the Pearl", ["Rarity"], 2023),
    SeedBook("Echoes of the Old Republic", ["Starswirl the Bearded"], 1960),
]

CLUB_B_BOOKS: list[SeedBook] = [
    SeedBook("Gems in the Rough", ["Rarity"], 2017),
    SeedBook("The Orchard Ledger", ["Applejack"], 2004),
    SeedBook("Skybound", ["Rainbow Dash"], 2019),
]

CLUB_A_NAME = "Catalog Club"
CLUB_B_NAME = "Restricted Club"
CLUB_C_NAME = "Closed Club"
CLUB_D_NAME = "Dissolvable Club"
SEED_CLUB_NAMES = [CLUB_A_NAME, CLUB_B_NAME, CLUB_C_NAME, CLUB_D_NAME]


@dataclass(frozen=True, slots=True)
class ClubSeedResult:
    slug: str
    name: str
    public_invite_id: str


@dataclass(frozen=True, slots=True)
class SeedSummary:
    club_a: ClubSeedResult
    club_b: ClubSeedResult
    club_c: ClubSeedResult
    club_d: ClubSeedResult
    direct_invite_id: str


def _book_external_ids(books: list[SeedBook], prefix: str) -> list[BookProviderIdentifier]:
    return [BookProviderIdentifier(BookProviderName.GOOGLE, f"{prefix}-{i:02d}") for i in range(len(books))]


async def _clear_previous_seed() -> None:
    # Matched by the seed email domain and by club membership, not by the current username/club-name
    # constants above -- so renaming a seed user or club (as happens whenever this file is tweaked)
    # still cleans up what an *earlier* version of this script left behind, instead of orphaning it.
    domain_pattern = rf"@{re.escape(SEED_EMAIL_DOMAIN)}$"
    stale_user_ids = [user.id for user in await UserModel.find(RegEx(UserModel.email, domain_pattern)).to_list()]

    club_filters = [In(ClubModel.name, SEED_CLUB_NAMES)]
    if stale_user_ids:
        club_filters.append(In(ClubModel.members.user_id, stale_user_ids))  # type: ignore[attr-defined]
        club_filters.append(In(ClubModel.pending_approvals.user_id, stale_user_ids))  # type: ignore[attr-defined]
    stale_club_ids = [club.id for club in await ClubModel.find(Or(*club_filters)).to_list()]

    if stale_club_ids:
        await InviteModel.find(In(InviteModel.club_id, stale_club_ids)).delete()
        await ClubModel.find(In(ClubModel.id, stale_club_ids)).delete()

    if stale_user_ids:
        await UserModel.find(In(UserModel.id, stale_user_ids)).delete()

    book_ids = _book_external_ids(CLUB_A_BOOKS, "seed-a") + _book_external_ids(CLUB_B_BOOKS, "seed-b")
    await BookModel.find(In(BookModel.external_id, book_ids)).delete()


async def _seed_users(auth_service: AuthService, user_repo: BeanieUserRepository) -> dict[str, PydanticObjectId]:
    settings = get_settings()
    user_ids: dict[str, PydanticObjectId] = {}

    for username, name in SEED_USERS:
        result = await auth_service.register_user(
            UserRegisterRequest(
                name=name,
                username=username,
                email=f"{username}@{SEED_EMAIL_DOMAIN}",
                password=SEED_PASSWORD,
                terms_version=settings.current_terms_version,
                privacy_version=settings.current_privacy_version,
            )
        )
        user_ids[username] = result.user_id

        if username == LINKED_GOOGLE_USERNAME:
            # No endpoint links a provider without a real OAuth credential to verify, so this one
            # falls back to the repository directly, same as the other documented seed exceptions.
            await user_repo.add_linked_provider(
                result.user_id,
                LinkedProviderSchema(
                    provider=AuthProviderName.GOOGLE,
                    external_id=f"seed-google-{username}",
                    picture_url=LINKED_GOOGLE_PICTURE_URL,
                ),
            )

    return user_ids


# CatalogService.suggest_book_to_club is the only path that creates a BookModel, but it does so by
# scraping live external link providers for missing formats -- unsuitable for deterministic, offline
# seed data. No other service method creates a book, so this goes straight to the repository.
async def _insert_books(book_repo: BeanieBookRepository, books: list[SeedBook], prefix: str) -> list[PydanticObjectId]:
    external_ids = _book_external_ids(books, prefix)
    book_ids = []

    for external_id, spec in zip(external_ids, books, strict=True):
        book = BookModel(
            external_id=external_id,
            title=spec.title,
            authors=spec.authors,
            year=spec.year,
            isbn_10=spec.isbn_10,
            isbn_13=spec.isbn_13,
        )
        saved = await book_repo.save(book)
        book_ids.append(PydanticObjectId(saved.id))

    return book_ids


# Same exception as _insert_books: CatalogService.suggest_book_to_club always stamps suggested_at as
# datetime.now(), but the shuffled ordering above (see CLUB_A_BOOKS's comment) needs staggered
# historical timestamps to make sort_by=suggested_at pagination demonstrable, so this writes directly
# through the repository instead.
async def _populate_catalog(
    club_repo: BeanieClubRepository,
    club_id: PydanticObjectId,
    book_ids: list[PydanticObjectId],
    suggesters: list[PydanticObjectId],
) -> None:
    now = datetime.now(UTC)

    for i, book_id in enumerate(book_ids):
        entry = CatalogEntryModel(
            book_id=book_id,
            suggested_by=suggesters[i % len(suggesters)],
            suggested_at=now - timedelta(days=i),
        )
        await club_repo.add_to_catalog(club_id, entry)


async def _create_club(
    club_service: ClubService,
    invite_service: InviteService,
    name: str,
    description: str,
    join_policy: JoinPolicy,
    owner_id: PydanticObjectId,
) -> tuple[PydanticObjectId, str, str]:
    club = await club_service.create_new_club(
        creator_id=owner_id,
        data=ClubCreateRequest(name=name, description=description, join_policy=join_policy, preferred_languages=["en"]),
    )
    club_id = PydanticObjectId(club.id)

    public_invite_id = await invite_service.rotate_public_link(club_id=club_id, user_id=owner_id)

    return club_id, club.slug, public_invite_id


async def _build_club_a(
    club_service: ClubService,
    invite_service: InviteService,
    book_repo: BeanieBookRepository,
    club_repo: BeanieClubRepository,
    user_ids: dict[str, PydanticObjectId],
) -> ClubSeedResult:
    club_id, slug, public_invite_id = await _create_club(
        club_service,
        invite_service,
        CLUB_A_NAME,
        "A big, deliberately shuffled catalog for exercising pagination and every sort field.",
        JoinPolicy.PUBLIC,
        user_ids["twilightsparkle"],
    )

    for username in ("applejack", "rarity", "rainbowdash", "pinkiepie"):
        await club_service.admit_user(club_id, user_ids[username], is_direct=False)

    book_ids = await _insert_books(book_repo, CLUB_A_BOOKS, "seed-a")
    await _populate_catalog(club_repo, club_id, book_ids, list(user_ids.values()))

    return ClubSeedResult(slug=slug, name=CLUB_A_NAME, public_invite_id=public_invite_id)


async def _build_club_b(
    club_service: ClubService,
    invite_service: InviteService,
    book_repo: BeanieBookRepository,
    club_repo: BeanieClubRepository,
    user_ids: dict[str, PydanticObjectId],
) -> tuple[ClubSeedResult, str]:
    club_id, slug, public_invite_id = await _create_club(
        club_service,
        invite_service,
        CLUB_B_NAME,
        "A restricted-join club with an OWNER, an ADMIN, a plain MEMBER, and a pending join request.",
        JoinPolicy.RESTRICTED,
        user_ids["rarity"],
    )

    await club_service.admit_user(club_id, user_ids["applejack"], is_direct=True)
    await club_service.change_member_role(club_id, user_ids["rarity"], user_ids["applejack"], MemberRole.ADMIN)
    await club_service.admit_user(club_id, user_ids["rainbowdash"], is_direct=True)
    await club_service.admit_user(club_id, user_ids["twilightsparkle"], is_direct=False)
    # pinkiepie is intentionally left out of the roster so the public invite above stays usable
    # for testing PATCH /invites/{invite_id} end to end (PENDING_APPROVAL outcome, since this
    # club is RESTRICTED).

    # Leaves rarity as protected former-OWNER (ADMIN) with an active 24h reclaim window, for CLUB-10.
    await club_service.transfer_ownership(club_id, user_ids["rarity"], "applejack")

    book_ids = await _insert_books(book_repo, CLUB_B_BOOKS, "seed-b")
    suggesters = [user_ids["rarity"], user_ids["applejack"], user_ids["rainbowdash"]]
    await _populate_catalog(club_repo, club_id, book_ids, suggesters)

    direct_invite_id = await invite_service.create_direct_invite(
        club_id=club_id,
        issuer_id=user_ids["rarity"],
        target_email=DIRECT_INVITE_EMAIL,
    )

    return ClubSeedResult(slug=slug, name=CLUB_B_NAME, public_invite_id=public_invite_id), direct_invite_id


async def _build_club_c(
    club_service: ClubService,
    invite_service: InviteService,
    user_ids: dict[str, PydanticObjectId],
) -> ClubSeedResult:
    club_id, slug, public_invite_id = await _create_club(
        club_service,
        invite_service,
        CLUB_C_NAME,
        "A public club with its suggestion queue closed, and an empty catalog.",
        JoinPolicy.PUBLIC,
        user_ids["pinkiepie"],
    )

    for username in ("twilightsparkle", "rarity"):
        await club_service.admit_user(club_id, user_ids[username], is_direct=False)

    await club_service.update_settings(
        club_id, user_ids["pinkiepie"], ClubSettingsUpdateRequest(allow_suggestions=False)
    )

    return ClubSeedResult(slug=slug, name=CLUB_C_NAME, public_invite_id=public_invite_id)


async def _build_club_d(
    club_service: ClubService,
    invite_service: InviteService,
    user_ids: dict[str, PydanticObjectId],
) -> ClubSeedResult:
    _club_id, slug, public_invite_id = await _create_club(
        club_service,
        invite_service,
        CLUB_D_NAME,
        "A minimal club that exists solely to demonstrate DELETE /clubs/{slug} (CLUB-14 dissolution).",
        JoinPolicy.PUBLIC,
        user_ids["rainbowdash"],
    )

    return ClubSeedResult(slug=slug, name=CLUB_D_NAME, public_invite_id=public_invite_id)


def _print_summary(summary: SeedSummary) -> None:
    print()
    print("=== Seed complete ===")
    print()
    print("Login with any seeded user (same password for all):")
    for username, name in SEED_USERS:
        print(f"  {username:<16} ({name})")
    print(f"  password: {SEED_PASSWORD}")
    print(f"  {LINKED_GOOGLE_USERNAME} also has a fake linked Google provider (GET/DELETE /users/me/auth-providers)")
    print()
    print(f'  curl -X POST /v1/auth/login -d "username=rarity&password={SEED_PASSWORD}"')
    print()

    for club in (summary.club_a, summary.club_b, summary.club_c, summary.club_d):
        print(f"{club.name} -- slug: {club.slug}")
        print(f"  public invite: {club.public_invite_id}")
    print()

    print("Club roster highlights:")
    print(f"  {CLUB_A_NAME}: twilightsparkle OWNER; applejack/rarity/rainbowdash/pinkiepie MEMBER")
    print(
        f"  {CLUB_B_NAME}: applejack OWNER; rarity ADMIN (protected former owner); "
        "rainbowdash MEMBER; twilightsparkle PENDING"
    )
    print(f"  {CLUB_C_NAME}: pinkiepie OWNER; twilightsparkle/rarity MEMBER; suggestions closed")
    print(f"  {CLUB_D_NAME}: rainbowdash OWNER; no other members")
    print()

    print("Try it out, e.g.:")
    print(f"  GET /v1/clubs/{summary.club_a.slug}/catalog/?sort_by=title&sort_direction=ASC")
    print(f"  GET /v1/clubs/{summary.club_a.slug}/catalog/?sort_by=year&sort_direction=DESC")
    print(f"  GET /v1/clubs/{summary.club_a.slug}/catalog/?sort_by=suggested_at&page=2")
    print(f"  PATCH /v1/clubs/{summary.club_b.slug}/pending-approvals/twilightsparkle (as applejack -> approve)")
    print(f"  DELETE /v1/clubs/{summary.club_b.slug}/ownership-transfers/current (as rarity, within 24h)")
    print(f"  PATCH /v1/invites/{summary.club_b.public_invite_id} (as pinkiepie -> 202 PENDING_APPROVAL)")
    print(
        f'  POST /v1/auth/register -d \'{{"invite_id": "{summary.direct_invite_id}", ...}}\' '
        f"(email={DIRECT_INVITE_EMAIL} -> JOINED)"
    )
    print(f"  POST /v1/clubs/{summary.club_c.slug}/catalog/ (as pinkiepie -> 403 ClubSuggestionsClosedError)")
    print(f"  PUT /v1/clubs/{summary.club_b.slug}/members/rainbowdash/role (as applejack -> promote to ADMIN)")
    print(f"  DELETE /v1/clubs/{summary.club_a.slug}/members/me (as pinkiepie -> leaves voluntarily)")
    print(f"  DELETE /v1/clubs/{summary.club_d.slug} (as rainbowdash -> dissolves the club entirely)")


async def seed() -> None:
    async with DatabaseManager():
        await _clear_previous_seed()

        book_repo = BeanieBookRepository()
        club_repo = BeanieClubRepository()
        user_repo = BeanieUserRepository()
        invite_repo = BeanieInviteRepository()
        auth_service = AuthService(user_repo, {})
        club_service = ClubService(club_repo, user_repo)
        invite_service = InviteService(invite_repo, club_repo, user_repo)

        user_ids = await _seed_users(auth_service, user_repo)

        club_a = await _build_club_a(club_service, invite_service, book_repo, club_repo, user_ids)
        club_b, direct_invite_id = await _build_club_b(club_service, invite_service, book_repo, club_repo, user_ids)
        club_c = await _build_club_c(club_service, invite_service, user_ids)
        club_d = await _build_club_d(club_service, invite_service, user_ids)

        _print_summary(
            SeedSummary(club_a=club_a, club_b=club_b, club_c=club_c, club_d=club_d, direct_invite_id=direct_invite_id)
        )


def main() -> int:
    if get_settings().environment == Environment.PROD:
        print("Refusing to seed: environment is PROD.", file=sys.stderr)
        return 1

    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.ERROR))

    asyncio.run(seed())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
