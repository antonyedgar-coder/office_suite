from django import template

from core.user_display import user_display_name
from documents.periods import period_detail_display, period_fy_display
from documents.task_bridge import user_can_change_task_linked_document

register = template.Library()


@register.filter
def document_fy(doc):
    if not doc:
        return "—"
    return period_fy_display(
        doc.period_key,
        financial_year=doc.financial_year,
        period_label=doc.period_label,
    )


@register.filter
def document_period(doc):
    if not doc:
        return "—"
    kind = ""
    if getattr(doc, "document_type_id", None) and getattr(doc, "document_type", None):
        kind = doc.document_type.period_kind
    return period_detail_display(kind, doc.period_key, period_label=doc.period_label)


@register.filter
def document_can_edit(doc, user):
    if not doc or not user or not getattr(user, "is_authenticated", False):
        return False
    return user_can_change_task_linked_document(user, doc)


@register.filter
def document_uploader(doc):
    if not doc or not getattr(doc, "uploaded_by_id", None):
        return ""
    user = getattr(doc, "uploaded_by", None)
    if user:
        return user_display_name(user)
    return ""
