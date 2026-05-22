from django import template

from core.created_by import creator_display

register = template.Library()


@register.filter
def creator_name(user):
    """Display name for created_by user, or em dash when unknown."""
    return creator_display(user)
