from datetime import UTC, datetime
from typing import Any, ClassVar, cast, get_args, get_origin

from beanie import BackLink, Document, Link, PydanticObjectId
from faker import Faker
from polyfactory import Use
from polyfactory.factories.beanie_odm_factory import BeanieDocumentFactory
from polyfactory.factories.pydantic_factory import ModelFactory
from polyfactory.field_meta import FieldMeta
from pydantic import BaseModel

from canterlot.emails import EmailTemplate
from canterlot.emails.core.schemas import BaseEmailContext
from canterlot.types import BookProviderIdentifier, BookProviderName


def get_random_email_template(faker: Faker) -> EmailTemplate[Any]:
    """Helper to pick a registered EmailTemplate instance."""
    templates = EmailTemplate.all()
    if not templates:
        raise RuntimeError("No EmailTemplate instances registered in EmailTemplate._registry")
    return faker.random_element(templates)


def _get_custom_providers(cls) -> dict[Any, Any]:
    return {
        BookProviderIdentifier: lambda: BookProviderIdentifier(
            provider=cls.__faker__.random_element(list(BookProviderName)),
            book_id=cls.__faker__.bothify("????####"),
        ),
        EmailTemplate: lambda: get_random_email_template(cls.__faker__),
        datetime: lambda: cls.__faker__.date_time_between(
            start_date="-2y",
            end_date="+1y",
            tzinfo=UTC,
        ),
    }


def _link_target(annotation: Any) -> type[Any] | None:
    if get_origin(annotation) is not Link:
        return None
    target: type[Any] = get_args(annotation)[0]
    return target


def _is_link_list(annotation: Any) -> bool:
    return get_origin(annotation) is list and _link_target(get_args(annotation)[0]) is not None


def _is_optional_link(annotation: Any) -> bool:
    return any(_link_target(arg) is not None for arg in get_args(annotation))


class BaseModelFactory[T: BaseModel](ModelFactory[T]):
    """Base factory for standard Pydantic schemas, DTOs, and request/response models."""

    __model__: type[T]
    __is_base_factory__ = True

    @classmethod
    def get_provider_map(cls) -> dict[Any, Any]:
        providers = super().get_provider_map()
        providers.update(_get_custom_providers(cls))
        return providers


class BaseDocumentFactory[T: Document](BeanieDocumentFactory[T]):
    """Base factory for Beanie MongoDB Documents."""

    __model__: type[T]
    __is_base_factory__ = True

    id: Any = Use(PydanticObjectId)

    @classmethod
    def get_provider_map(cls) -> dict[Any, Any]:
        providers = super().get_provider_map()
        providers.update(_get_custom_providers(cls))
        return providers

    @classmethod
    def get_field_value(cls, field_meta: FieldMeta, *args: Any, **kwargs: Any) -> Any:
        annotation = field_meta.annotation
        link_target = _link_target(annotation)
        if link_target is not None:
            return link_target.link_from_id(PydanticObjectId())
        if get_origin(annotation) is BackLink or _is_link_list(annotation):
            return []
        if _is_optional_link(annotation):
            return None
        return super().get_field_value(field_meta, *args, **kwargs)


class BaseContextFactory[T: BaseEmailContext](BaseModelFactory[T]):
    __model__: type[T]
    __is_base_factory__ = True
    _by_model: ClassVar[dict[type[BaseEmailContext], type["BaseContextFactory[Any]"]]] = {}
    _by_template_name: ClassVar[dict[str, type["BaseContextFactory[Any]"]]] = {}

    unsubscribe_url: Any = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)

        if cls.__dict__.get("__is_base_factory__", False):
            return

        model_cls = getattr(cls, "__model__", None)
        if model_cls and issubclass(model_cls, BaseEmailContext):
            cls._by_model[model_cls] = cls

    @classmethod
    def get_for_model[C: BaseEmailContext](cls, model: type[C]) -> type["BaseContextFactory[C]"]:
        if model not in cls._by_model:
            raise KeyError(f"No context factory registered for model: {model.__name__}")
        return cls._by_model[model]

    @classmethod
    def get_for_template(cls, template: EmailTemplate[Any] | str) -> type["BaseContextFactory[Any]"]:
        if isinstance(template, str):
            template_obj = EmailTemplate._registry.get(template)
            if not template_obj:
                raise KeyError(f"Unknown EmailTemplate name: {template}")
            template = template_obj

        return cls.get_for_model(template.context_schema)

    @classmethod
    def build_for_template(cls, template: EmailTemplate[Any] | str, **kwargs: Any) -> BaseModel:
        factory_cls = cls.get_for_template(template)
        return cast(BaseModel, factory_cls.build(**kwargs))
