from django import template

from tasks.models import Task
from tasks.user_labels import user_person_name as resolve_user_person_name

register = template.Library()


@register.filter
def person_name(user):
    return resolve_user_person_name(user)


@register.filter
def task_status_label(code):
    return Task.status_label(code) if code else ""
