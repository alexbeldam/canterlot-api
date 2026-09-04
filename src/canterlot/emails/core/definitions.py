from datetime import UTC, datetime
from typing import Any, ClassVar, Never, Self, TypeVar, overload

from beanie import PydanticObjectId
from pydantic import BaseModel, Field, GetCoreSchemaHandler, ValidationInfo, field_validator, model_validator
from pydantic_core import core_schema

from canterlot.emails.core import schemas
from canterlot.types import NormalizedEmailStr

from .enums import EmailCategory, EmailPriority, SubBrand

TContext = TypeVar("TContext", bound=BaseModel)


class EmailTemplate[TContext: schemas.BaseEmailContext]:
    """Base email template contract."""

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
        heading_template: str | None = None,
    ):
        self.name = name
        self.brand = brand
        self.slug = slug
        self.subject_template = subject_template
        self.context_schema = context_schema
        self.priority = priority
        self.category = category
        self.heading_template = heading_template

        EmailTemplate._registry[name] = self

    @property
    def template_path(self) -> str:
        return f"{self.brand}/{self.slug}.html.j2"

    @classmethod
    def __get_pydantic_core_schema__(cls, _source_type: Any, _handler: GetCoreSchemaHandler) -> core_schema.CoreSchema:
        def validate_template_name(v: Any) -> Any:
            if isinstance(v, cls):
                return v
            if isinstance(v, str):
                if v not in cls._registry:
                    raise ValueError(f"Unknown email template: {v}")
                return cls._registry[v]
            raise ValueError(f"Invalid input type for EmailTemplate: {type(v)}")

        return core_schema.json_or_python_schema(
            json_schema=core_schema.no_info_before_validator_function(
                validate_template_name,
                core_schema.any_schema(),
            ),
            python_schema=core_schema.no_info_before_validator_function(
                validate_template_name,
                core_schema.any_schema(),
            ),
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda instance: instance.name,
                return_schema=core_schema.str_schema(),
            ),
        )

    @classmethod
    def all(cls) -> list["EmailTemplate[Any]"]:
        return list(cls._registry.values())


class ClubPreferenceEmailTemplate[TContext: schemas.BaseEmailContext](EmailTemplate[TContext]):
    """Club engagement templates that honor recipient per-club opt-out preferences. MUST take a club_id."""

    def __init__(
        self,
        name: str,
        brand: SubBrand,
        slug: str,
        subject_template: str,
        context_schema: type[TContext],
        priority: EmailPriority = EmailPriority.DEFAULT,
        category: EmailCategory = EmailCategory.ENGAGEMENT,
        heading_template: str | None = None,
    ):
        super().__init__(
            name=name,
            brand=brand,
            slug=slug,
            subject_template=subject_template,
            context_schema=context_schema,
            priority=priority,
            category=category,
            heading_template=heading_template,
        )


class GlobalEmailTemplate[TContext: schemas.BaseEmailContext](ClubPreferenceEmailTemplate[TContext]):
    """Global or transactional emails where per-club opt-outs do not apply. MUST NOT have a club_id."""

    def __init__(
        self,
        name: str,
        brand: SubBrand,
        slug: str,
        subject_template: str,
        context_schema: type[TContext],
        priority: EmailPriority = EmailPriority.DEFAULT,
        category: EmailCategory = EmailCategory.TRANSACTIONAL,
        heading_template: str | None = None,
    ):
        super().__init__(
            name=name,
            brand=brand,
            slug=slug,
            subject_template=subject_template,
            context_schema=context_schema,
            priority=priority,
            category=category,
            heading_template=heading_template,
        )


class Templates:
    # --- CELESTIA TEMPLATES (Auth & Core Administration) ---
    CELESTIA_OAUTH_WELCOME = GlobalEmailTemplate(
        name="CELESTIA_OAUTH_WELCOME",
        brand=SubBrand.CELESTIA,
        slug="oauth-welcome",
        subject_template="Welcome to Canterlot!",
        context_schema=schemas.AuthProviderContext,
        priority=EmailPriority.HIGH,
        category=EmailCategory.TRANSACTIONAL,
    )
    CELESTIA_VERIFY_EMAIL = GlobalEmailTemplate(
        name="CELESTIA_VERIFY_EMAIL",
        brand=SubBrand.CELESTIA,
        slug="verify-email",
        subject_template="{code} is your Canterlot verification code",
        heading_template="Confirm your email on Canterlot",
        context_schema=schemas.EmailVerificationContext,
        priority=EmailPriority.HIGH,
        category=EmailCategory.TRANSACTIONAL,
    )
    CELESTIA_VERIFY_EMAIL_CHANGED = GlobalEmailTemplate(
        name="CELESTIA_VERIFY_EMAIL_CHANGED",
        brand=SubBrand.CELESTIA,
        slug="verify-email-changed",
        subject_template="{code} is your code to confirm your new email",
        heading_template="Confirm your new email on Canterlot",
        context_schema=schemas.EmailVerificationContext,
        priority=EmailPriority.HIGH,
        category=EmailCategory.TRANSACTIONAL,
    )
    CELESTIA_INVITE_EXTERNAL = GlobalEmailTemplate(
        name="CELESTIA_INVITE_EXTERNAL",
        brand=SubBrand.CELESTIA,
        slug="invite-external",
        subject_template="{inviter_name} invited you to the {club_name}",
        context_schema=schemas.InviteExternalContext,
        priority=EmailPriority.DEFAULT,
        category=EmailCategory.TRANSACTIONAL,
    )
    CELESTIA_INVITE_INTERNAL = GlobalEmailTemplate(
        name="CELESTIA_INVITE_INTERNAL",
        brand=SubBrand.CELESTIA,
        slug="invite-internal",
        subject_template="{inviter_name} invited you to the {club_name}",
        context_schema=schemas.InviteInternalContext,
        priority=EmailPriority.DEFAULT,
        category=EmailCategory.TRANSACTIONAL,
    )
    CELESTIA_APPROVED = ClubPreferenceEmailTemplate(
        name="CELESTIA_APPROVED",
        brand=SubBrand.CELESTIA,
        slug="approved",
        subject_template="You were approved to the {club_name}!",
        context_schema=schemas.ClubActionContext,
        priority=EmailPriority.DEFAULT,
        category=EmailCategory.ENGAGEMENT,
    )
    CELESTIA_OWNERSHIP_RECEIVED = GlobalEmailTemplate(
        name="CELESTIA_OWNERSHIP_RECEIVED",
        brand=SubBrand.CELESTIA,
        slug="ownership-received",
        subject_template="You are now owner of the {club_name}",
        context_schema=schemas.ClubActorActionContext,
        priority=EmailPriority.DEFAULT,
        category=EmailCategory.TRANSACTIONAL,
    )

    # --- SPIKE TEMPLATES (The Engagement Engine) ---
    SPIKE_BOOK_DECIDED = ClubPreferenceEmailTemplate(
        name="SPIKE_BOOK_DECIDED",
        brand=SubBrand.SPIKE,
        slug="book-decided",
        subject_template="{club_name}: time to start reading {book_title}",
        context_schema=schemas.SpikeBookContext,
        priority=EmailPriority.LOW,
        category=EmailCategory.ENGAGEMENT,
    )
    SPIKE_VOTING_OPEN = ClubPreferenceEmailTemplate(
        name="SPIKE_VOTING_OPEN",
        brand=SubBrand.SPIKE,
        slug="voting-open",
        subject_template="{club_name}: vote on the next book",
        context_schema=schemas.SpikeActionContext,
        priority=EmailPriority.LOW,
        category=EmailCategory.ENGAGEMENT,
    )
    SPIKE_REMINDER_T1 = ClubPreferenceEmailTemplate(
        name="SPIKE_REMINDER_T1",
        brand=SubBrand.SPIKE,
        slug="reminder-t1",
        subject_template="{club_name}: 1 day left for {book_title} deadline",
        context_schema=schemas.SpikeBookContext,
        priority=EmailPriority.LOW,
        category=EmailCategory.ENGAGEMENT,
    )
    SPIKE_REMINDER_T0 = ClubPreferenceEmailTemplate(
        name="SPIKE_REMINDER_T0",
        brand=SubBrand.SPIKE,
        slug="reminder-t0",
        subject_template="{club_name}: {book_title} deadline is today",
        context_schema=schemas.SpikeBookContext,
        priority=EmailPriority.LOW,
        category=EmailCategory.ENGAGEMENT,
    )
    SPIKE_ROLE_CHANGED = ClubPreferenceEmailTemplate(
        name="SPIKE_ROLE_CHANGED",
        brand=SubBrand.SPIKE,
        slug="role-changed",
        subject_template="Your role in {club_name} changed to {role_name}",
        context_schema=schemas.SpikeRoleContext,
        priority=EmailPriority.DEFAULT,
        category=EmailCategory.ENGAGEMENT,
    )
    SPIKE_REMOVED = GlobalEmailTemplate(
        name="SPIKE_REMOVED",
        brand=SubBrand.SPIKE,
        slug="removed",
        subject_template="You were removed from the {club_name}",
        context_schema=schemas.SpikeBaseContext,
        priority=EmailPriority.DEFAULT,
        category=EmailCategory.TRANSACTIONAL,
    )
    SPIKE_CLUB_DISSOLVED = ClubPreferenceEmailTemplate(
        name="SPIKE_CLUB_DISSOLVED",
        brand=SubBrand.SPIKE,
        slug="club-dissolved",
        subject_template="The {club_name} was disbanded",
        context_schema=schemas.SpikeActionContext,
        priority=EmailPriority.DEFAULT,
        category=EmailCategory.ENGAGEMENT,
    )

    # --- LUNA TEMPLATES (Security & Core Identity) ---
    LUNA_PASSWORD_RESET = GlobalEmailTemplate(
        name="LUNA_PASSWORD_RESET",
        brand=SubBrand.LUNA,
        slug="password-reset",
        subject_template="{action_capitalized} your password on Canterlot",
        context_schema=schemas.PasswordResetValidationContext,
        priority=EmailPriority.HIGH,
        category=EmailCategory.TRANSACTIONAL,
    )
    LUNA_LOCKED_OUT = GlobalEmailTemplate(
        name="LUNA_LOCKED_OUT",
        brand=SubBrand.LUNA,
        slug="locked-out",
        subject_template="You have no login methods left",
        context_schema=schemas.LunaProviderActionContext,
        priority=EmailPriority.HIGH,
        category=EmailCategory.TRANSACTIONAL,
    )
    LUNA_PASSWORD_CHANGED = GlobalEmailTemplate(
        name="LUNA_PASSWORD_CHANGED",
        brand=SubBrand.LUNA,
        slug="password-changed",
        subject_template="Your password was changed",
        context_schema=schemas.PasswordChangedContext,
        priority=EmailPriority.HIGH,
        category=EmailCategory.TRANSACTIONAL,
    )
    LUNA_PROVIDER_LINKED = GlobalEmailTemplate(
        name="LUNA_PROVIDER_LINKED",
        brand=SubBrand.LUNA,
        slug="provider-linked",
        subject_template="You linked {provider_name} to your account",
        context_schema=schemas.LunaProviderActionContext,
        priority=EmailPriority.HIGH,
        category=EmailCategory.TRANSACTIONAL,
    )
    LUNA_PROVIDER_DISCONNECTED = GlobalEmailTemplate(
        name="LUNA_PROVIDER_DISCONNECTED",
        brand=SubBrand.LUNA,
        slug="provider-disconnected",
        subject_template="You unlinked {provider_name} from your account",
        context_schema=schemas.AuthProviderContext,
        priority=EmailPriority.HIGH,
        category=EmailCategory.TRANSACTIONAL,
    )
    LUNA_EMAIL_CHANGED = GlobalEmailTemplate(
        name="LUNA_EMAIL_CHANGED",
        brand=SubBrand.LUNA,
        slug="email-changed",
        subject_template="Your account email was changed",
        context_schema=schemas.RecipientContext,
        priority=EmailPriority.HIGH,
        category=EmailCategory.TRANSACTIONAL,
    )
    LUNA_OWNERSHIP_TRANSFERRED = GlobalEmailTemplate(
        name="LUNA_OWNERSHIP_TRANSFERRED",
        brand=SubBrand.LUNA,
        slug="ownership-transferred",
        subject_template="You transferred ownership of {club_name}",
        context_schema=schemas.ClubActorActionContext,
        priority=EmailPriority.DEFAULT,
        category=EmailCategory.TRANSACTIONAL,
    )
    LUNA_OWNERSHIP_RECLAIMED = GlobalEmailTemplate(
        name="LUNA_OWNERSHIP_RECLAIMED",
        brand=SubBrand.LUNA,
        slug="ownership-reclaimed",
        subject_template="Your transfer of {club_name} was reverted",
        context_schema=schemas.ClubActorActionContext,
        priority=EmailPriority.DEFAULT,
        category=EmailCategory.TRANSACTIONAL,
    )


class EmailTaskPayload[TContext: schemas.BaseEmailContext](BaseModel):
    """Encapsulates an email dispatch payload with strict type-level constraints.

    The model enforces compile-time and runtime validation on context and club scoping:
    - `GlobalEmailTemplate`: Platform-wide or transactional tasks. Forbids `club_id`.
    - `ClubPreferenceEmailTemplate`: Club-scoped engagement tasks. Requires `club_id`.
    - `context`: Must match the schema required by `template`.
    """

    template: EmailTemplate[TContext]
    to: NormalizedEmailStr
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    context: TContext
    club_id: PydanticObjectId | None = None

    @field_validator("context", mode="before")
    @classmethod
    def hydrate_dict_context_using_templates_context_schema(cls, value: Any, info: ValidationInfo) -> Any:
        template = info.data.get("template")
        if template is not None and isinstance(value, dict):
            return template.context_schema.model_validate(value)
        return value

    @overload
    def __init__(
        self,
        *,
        template: GlobalEmailTemplate[TContext],
        to: NormalizedEmailStr,
        context: TContext,
        created_at: datetime = ...,
        club_id: Never = ...,
    ) -> None: ...

    @overload
    def __init__(
        self,
        *,
        template: ClubPreferenceEmailTemplate[TContext],
        to: NormalizedEmailStr,
        context: TContext,
        club_id: PydanticObjectId,
        created_at: datetime = ...,
    ) -> None: ...

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)

    @model_validator(mode="after")
    def validate_club_id_usage(self) -> Self:
        if isinstance(self.template, GlobalEmailTemplate) and self.club_id is not None:
            raise ValueError(
                f"Cannot attach club_id to global template '{self.template.name}'. "
                "Global/transactional emails cannot be opted out of per club."
            )
        if (
            isinstance(self.template, ClubPreferenceEmailTemplate)
            and not isinstance(self.template, GlobalEmailTemplate)
            and self.club_id is None
        ):
            raise ValueError(f"Club preference template '{self.template.name}' requires a club_id.")
        return self
