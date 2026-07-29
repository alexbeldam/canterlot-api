from datetime import UTC, datetime
from typing import Any

from beanie import PydanticObjectId
from polyfactory import Use
from polyfactory.factories import DataclassFactory
from polyfactory.factories.pydantic_factory import ModelFactory

from canterlot.emails import ClubPreferenceEmailTemplate, EmailTaskPayload, EmailTemplate, GlobalEmailTemplate
from canterlot.emails.core import schemas
from canterlot.services.dispatch import BatchEmailDispatchItem
from canterlot.types import AuthProviderName, MemberRole
from canterlot.utils import generate_secure_code

from .base import BaseContextFactory, get_random_email_template


class RecipientContextFactory(BaseContextFactory[schemas.RecipientContext]):
    __model__ = schemas.RecipientContext

    recipient_name = Use(lambda: RecipientContextFactory.__faker__.first_name())


class BaseVerificationContextFactory(RecipientContextFactory):
    __model__ = schemas.BaseVerificationContext

    code = Use(lambda: generate_secure_code().get_secret_value())


class ClubActionContextFactory(RecipientContextFactory):
    __model__ = schemas.ClubActionContext

    club_name = Use(lambda: ClubActionContextFactory.__faker__.company())
    unsubscribe_url = Use(lambda: ClubActionContextFactory.__faker__.url())


class ClubActorActionContextFactory(ClubActionContextFactory):
    __model__ = schemas.ClubActorActionContext

    actor_name = Use(lambda: ClubActionContextFactory.__faker__.first_name())


class AuthProviderContextFactory(RecipientContextFactory):
    __model__ = schemas.AuthProviderContext

    provider_name = Use(lambda: AuthProviderContextFactory.__faker__.random_element(list(AuthProviderName)))


class InviteExternalContextFactory(BaseContextFactory):
    __model__ = schemas.InviteExternalContext

    inviter_name = Use(lambda: InviteExternalContextFactory.__faker__.first_name())
    club_name = Use(lambda: InviteExternalContextFactory.__faker__.company())


class InviteInternalContextFactory(ClubActionContextFactory):
    __model__ = schemas.InviteInternalContext

    inviter_name = Use(lambda: InviteInternalContextFactory.__faker__.first_name())


class EmailVerificationContextFactory(BaseVerificationContextFactory):
    __model__ = schemas.EmailVerificationContext


class SpikeBaseFactory(RecipientContextFactory):
    __model__ = schemas.SpikeBaseContext

    club_name = Use(lambda: SpikeBaseFactory.__faker__.company())


class SpikeActionContextFactory(SpikeBaseFactory):
    __model__ = schemas.SpikeActionContext


class SpikeBookContextFactory(SpikeActionContextFactory):
    __model__ = schemas.SpikeBookContext

    book_title = Use(lambda: SpikeBookContextFactory.__faker__.sentence(nb_words=3))


class SpikeRoleContextFactory(SpikeActionContextFactory):
    __model__ = schemas.SpikeRoleContext

    role_name = Use(lambda: SpikeRoleContextFactory.__faker__.random_element(list(MemberRole)))


class PasswordChangedContextFactory(RecipientContextFactory):
    __model__ = schemas.PasswordChangedContext


class PasswordResetValidationContextFactory(BaseVerificationContextFactory):
    __model__ = schemas.PasswordResetValidationContext


class LunaProviderActionContextFactory(AuthProviderContextFactory):
    __model__ = schemas.LunaProviderActionContext


class EmailTaskPayloadFactory(ModelFactory[EmailTaskPayload]):
    __model__ = EmailTaskPayload

    created_at = Use(lambda: datetime.now(UTC))

    @classmethod
    def build(cls, **overrides: Any) -> EmailTaskPayload:
        template: EmailTemplate[Any] = overrides.get("template") or get_random_email_template(cls.__faker__)
        overrides["template"] = template

        if "context" not in overrides:
            overrides["context"] = BaseContextFactory.build_for_template(template)
        if "club_id" not in overrides:
            if isinstance(template, GlobalEmailTemplate):
                overrides["club_id"] = None
            elif isinstance(template, ClubPreferenceEmailTemplate):
                overrides["club_id"] = PydanticObjectId()

        return super().build(**overrides)


class BatchEmailDispatchItemFactory(DataclassFactory[BatchEmailDispatchItem]):
    __model__ = BatchEmailDispatchItem
