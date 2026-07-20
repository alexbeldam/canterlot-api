from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, ClassVar, TypeVar

from beanie import PydanticObjectId
from pydantic import BaseModel, Field, GetCoreSchemaHandler
from pydantic_core import core_schema

from canterlot.emails.core import schemas
from canterlot.types import NormalizedEmailStr

TContext = TypeVar("TContext", bound=BaseModel)


class EmailPriority(StrEnum):
    HIGH = "high"
    DEFAULT = "default"
    LOW = "low"


class EmailCategory(StrEnum):
    TRANSACTIONAL = "transactional"
    ENGAGEMENT = "engagement"
    PROMOTIONAL = "promotional"


class SubBrand(StrEnum):
    CELESTIA = "celestia"
    SPIKE = "spike"
    LUNA = "luna"

    @property
    def includes_preferences(self) -> bool:
        return self == SubBrand.SPIKE

    @property
    def sender(self) -> str:
        return f"{self.value.title()} · Canterlot <{self.value}@noreply.canterlot.com.br>"


class EmailTemplate[TContext: BaseModel]:
    _registry: ClassVar[dict[str, "EmailTemplate[Any]"]] = {}

    def __init__(
        self,
        name: str,
        brand: SubBrand,
        slug: str,
        subject_template: str,
        context_schema: type[TContext],
        priority: EmailPriority = EmailPriority.DEFAULT,
        category: EmailCategory = EmailCategory.TRANSACTIONAL,
    ):
        self.name = name
        self.brand = brand
        self.slug = slug
        self.subject_template = subject_template
        self.context_schema = context_schema
        self.priority = priority
        self.category = category

        EmailTemplate._registry[name] = self

    @property
    def template_path(self) -> str:
        return f"{self.brand}/{self.slug}.html.j2"

    @classmethod
    def __get_pydantic_core_schema__(cls, _source_type: Any, _handler: GetCoreSchemaHandler) -> core_schema.CoreSchema:
        def validate_template_name(v: str) -> Any:
            if v not in cls._registry:
                raise ValueError(f"Unknown email template: {v}")
            return cls._registry[v]

        return core_schema.json_or_python_schema(
            json_schema=core_schema.chain_schema(
                [
                    core_schema.str_schema(),
                    core_schema.no_info_before_validator_function(
                        validate_template_name,
                        core_schema.any_schema(),
                    ),
                ]
            ),
            python_schema=core_schema.is_instance_schema(cls),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda instance: instance.name,
                return_schema=core_schema.str_schema(),
            ),
        )


class Templates:
    # --- CELESTIA TEMPLATES (Auth & Core Administration) ---
    CELESTIA_VERIFY_EMAIL = EmailTemplate(
        name="CELESTIA_VERIFY_EMAIL",
        brand=SubBrand.CELESTIA,
        slug="verify-email",
        subject_template="Confirm your email on Canterlot",
        context_schema=schemas.VerificationContext,
        priority=EmailPriority.HIGH,
        category=EmailCategory.TRANSACTIONAL,
    )
    CELESTIA_VERIFY_EMAIL_CHANGED = EmailTemplate(
        name="CELESTIA_VERIFY_EMAIL_CHANGED",
        brand=SubBrand.CELESTIA,
        slug="verify-email-changed",
        subject_template="Confirm your new email on Canterlot",
        context_schema=schemas.VerificationContext,
        priority=EmailPriority.HIGH,
        category=EmailCategory.TRANSACTIONAL,
    )
    CELESTIA_INVITE_EXTERNAL = EmailTemplate(
        name="CELESTIA_INVITE_EXTERNAL",
        brand=SubBrand.CELESTIA,
        slug="invite-external",
        subject_template="{inviter_name} invited you to the {club_name}",
        context_schema=schemas.InviteExternalContext,
        priority=EmailPriority.DEFAULT,
        category=EmailCategory.TRANSACTIONAL,
    )
    CELESTIA_INVITE_INTERNAL = EmailTemplate(
        name="CELESTIA_INVITE_INTERNAL",
        brand=SubBrand.CELESTIA,
        slug="invite-internal",
        subject_template="{inviter_name} invited you to the {club_name}",
        context_schema=schemas.InviteInternalContext,
        priority=EmailPriority.DEFAULT,
        category=EmailCategory.TRANSACTIONAL,
    )
    CELESTIA_APPROVED = EmailTemplate(
        name="CELESTIA_APPROVED",
        brand=SubBrand.CELESTIA,
        slug="approved",
        subject_template="You were approved to the {club_name}!",
        context_schema=schemas.ClubActionContext,
        priority=EmailPriority.DEFAULT,
        category=EmailCategory.ENGAGEMENT,
    )
    CELESTIA_OWNERSHIP_RECEIVED = EmailTemplate(
        name="CELESTIA_OWNERSHIP_RECEIVED",
        brand=SubBrand.CELESTIA,
        slug="ownership-received",
        subject_template="You are now owner of the {club_name}",
        context_schema=schemas.ClubActorActionContext,
        priority=EmailPriority.DEFAULT,
        category=EmailCategory.TRANSACTIONAL,
    )

    # --- SPIKE TEMPLATES (The Engagement Engine) ---
    SPIKE_BOOK_DECIDED = EmailTemplate(
        name="SPIKE_BOOK_DECIDED",
        brand=SubBrand.SPIKE,
        slug="book-decided",
        subject_template="{club_name}: time to start reading {book_title}",
        context_schema=schemas.SpikeBookContext,
        priority=EmailPriority.LOW,
        category=EmailCategory.ENGAGEMENT,
    )
    SPIKE_VOTING_OPEN = EmailTemplate(
        name="SPIKE_VOTING_OPEN",
        brand=SubBrand.SPIKE,
        slug="voting-open",
        subject_template="{club_name}: vote on the next book",
        context_schema=schemas.SpikeActionContext,
        priority=EmailPriority.LOW,
        category=EmailCategory.ENGAGEMENT,
    )
    SPIKE_REMINDER_T1 = EmailTemplate(
        name="SPIKE_REMINDER_T1",
        brand=SubBrand.SPIKE,
        slug="reminder-t1",
        subject_template="{club_name}: 1 day left for {book_title} deadline",
        context_schema=schemas.SpikeBookContext,
        priority=EmailPriority.LOW,
        category=EmailCategory.ENGAGEMENT,
    )
    SPIKE_REMINDER_T0 = EmailTemplate(
        name="SPIKE_REMINDER_T0",
        brand=SubBrand.SPIKE,
        slug="reminder-t0",
        subject_template="{club_name}: {book_title} deadline is today",
        context_schema=schemas.SpikeBookContext,
        priority=EmailPriority.LOW,
        category=EmailCategory.ENGAGEMENT,
    )
    SPIKE_ROLE_CHANGED = EmailTemplate(
        name="SPIKE_ROLE_CHANGED",
        brand=SubBrand.SPIKE,
        slug="role-changed",
        subject_template="Your role in {club_name} changed to {role_name}",
        context_schema=schemas.SpikeRoleContext,
        priority=EmailPriority.DEFAULT,
        category=EmailCategory.ENGAGEMENT,
    )
    SPIKE_REMOVED = EmailTemplate(
        name="SPIKE_REMOVED",
        brand=SubBrand.SPIKE,
        slug="removed",
        subject_template="You were removed from the {club_name}",
        context_schema=schemas.SpikeBaseContext,
        priority=EmailPriority.DEFAULT,
        category=EmailCategory.TRANSACTIONAL,
    )
    SPIKE_CLUB_DISSOLVED = EmailTemplate(
        name="SPIKE_CLUB_DISSOLVED",
        brand=SubBrand.SPIKE,
        slug="club-dissolved",
        subject_template="The {club_name} was disbanded",
        context_schema=schemas.SpikeActionContext,
        priority=EmailPriority.DEFAULT,
        category=EmailCategory.ENGAGEMENT,
    )

    # --- LUNA TEMPLATES (Security & Core Identity) ---
    LUNA_PASSWORD_RESET = EmailTemplate(
        name="LUNA_PASSWORD_RESET",
        brand=SubBrand.LUNA,
        slug="password-reset",
        subject_template="Reset your password on Canterlot",
        context_schema=schemas.VerificationContext,
        priority=EmailPriority.HIGH,
        category=EmailCategory.TRANSACTIONAL,
    )
    LUNA_LOCKED_OUT = EmailTemplate(
        name="LUNA_LOCKED_OUT",
        brand=SubBrand.LUNA,
        slug="locked-out",
        subject_template="You have no login methods left",
        context_schema=schemas.LunaProviderActionContext,
        priority=EmailPriority.HIGH,
        category=EmailCategory.TRANSACTIONAL,
    )
    LUNA_PASSWORD_CHANGED = EmailTemplate(
        name="LUNA_PASSWORD_CHANGED",
        brand=SubBrand.LUNA,
        slug="password-changed",
        subject_template="Your password was changed",
        context_schema=schemas.RecipientContext,
        priority=EmailPriority.HIGH,
        category=EmailCategory.TRANSACTIONAL,
    )
    LUNA_PROVIDER_LINKED = EmailTemplate(
        name="LUNA_PROVIDER_LINKED",
        brand=SubBrand.LUNA,
        slug="provider-linked",
        subject_template="You linked {provider_name} to your account",
        context_schema=schemas.LunaProviderActionContext,
        priority=EmailPriority.HIGH,
        category=EmailCategory.TRANSACTIONAL,
    )
    LUNA_PROVIDER_DISCONNECTED = EmailTemplate(
        name="LUNA_PROVIDER_DISCONNECTED",
        brand=SubBrand.LUNA,
        slug="provider-disconnected",
        subject_template="You unlinked {provider_name} from your account",
        context_schema=schemas.LunaProviderContext,
        priority=EmailPriority.HIGH,
        category=EmailCategory.TRANSACTIONAL,
    )
    LUNA_EMAIL_CHANGED = EmailTemplate(
        name="LUNA_EMAIL_CHANGED",
        brand=SubBrand.LUNA,
        slug="email-changed",
        subject_template="Your account email was changed",
        context_schema=schemas.RecipientContext,
        priority=EmailPriority.HIGH,
        category=EmailCategory.TRANSACTIONAL,
    )
    LUNA_OWNERSHIP_TRANSFERRED = EmailTemplate(
        name="LUNA_OWNERSHIP_TRANSFERRED",
        brand=SubBrand.LUNA,
        slug="ownership-transferred",
        subject_template="You transferred ownership of {club_name}",
        context_schema=schemas.ClubActorActionContext,
        priority=EmailPriority.DEFAULT,
        category=EmailCategory.TRANSACTIONAL,
    )
    LUNA_OWNERSHIP_RECLAIMED = EmailTemplate(
        name="LUNA_OWNERSHIP_RECLAIMED",
        brand=SubBrand.LUNA,
        slug="ownership-reclaimed",
        subject_template="Your transfer of {club_name} was reverted",
        context_schema=schemas.LunaOwnershipReclaimedContext,
        priority=EmailPriority.DEFAULT,
        category=EmailCategory.TRANSACTIONAL,
    )


class EmailTaskPayload[TContext: BaseModel](BaseModel):
    template: EmailTemplate[TContext]
    to: NormalizedEmailStr
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    context: TContext
    club_id: PydanticObjectId | None = None
