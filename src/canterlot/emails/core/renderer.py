from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from pydantic import BaseModel

from canterlot.emails.core.definitions import EmailTemplate
from canterlot.types import NormalizedEmailStr

if TYPE_CHECKING:
    from canterlot.emails.interfaces import EmailMessage

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_REPLY_TO = "sunset@canterlot.com.br"


@dataclass(frozen=True)
class RenderedEmailTemplate:
    template: EmailTemplate
    subject: str
    html: str
    sender: str
    reply_to: NormalizedEmailStr
    headers: dict[str, str] | None

    def to_message(self, to: list[NormalizedEmailStr] | NormalizedEmailStr) -> EmailMessage:
        from canterlot.emails.interfaces import EmailMessage

        recipients = [to] if isinstance(to, str) else to

        return EmailMessage(
            sender=self.sender,
            to=recipients,
            subject=self.subject,
            html=self.html,
            reply_to=self.reply_to,
            headers=self.headers,
        )


_ENV = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(enabled_extensions=("html.j2", "xml.j2"), default_for_string=True),
    undefined=StrictUndefined,
)


def _format_string(template: str, context: dict[str, Any], *, field_name: str, template_enum: EmailTemplate) -> str:
    try:
        return template.format(**context)
    except KeyError as exc:
        missing = str(exc).strip("'")
        raise ValueError(f"Missing '{missing}' for {field_name} in email template '{template_enum.name}'.") from exc


def _build_headers(template_enum: EmailTemplate, context: dict[str, Any]) -> dict[str, str] | None:
    if not template_enum.brand.includes_preferences:
        return None

    unsubscribe_url = context.get("unsubscribe_url")
    if not isinstance(unsubscribe_url, str) or not unsubscribe_url:
        return None

    return {
        "List-Unsubscribe": f"<mailto:{_REPLY_TO}?subject=unsubscribe>, <{unsubscribe_url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def render_email_template(template: EmailTemplate, context: dict[str, Any] | BaseModel) -> RenderedEmailTemplate:
    validated_context = template.context_schema(**context) if isinstance(context, dict) else context

    context_dict = validated_context.model_dump(mode="json")

    subject = _format_string(template.subject_template, context_dict, field_name="subject", template_enum=template)

    render_context = dict(context_dict)
    render_context["subject"] = subject
    render_context["preheader"] = _format_string(
        "{subject}", render_context, field_name="preheader", template_enum=template
    )
    render_context["heading"] = _format_string(
        "{subject}", render_context, field_name="heading", template_enum=template
    )

    jinja_template = _ENV.get_template(template.template_path)
    html = jinja_template.render(render_context)

    return RenderedEmailTemplate(
        template=template,
        subject=subject,
        html=html,
        sender=template.brand.sender,
        reply_to=_REPLY_TO,
        headers=_build_headers(template, render_context),
    )
