from django import template

register = template.Library()


@register.inclusion_tag("includes/breadcrumbs.html")
def show_breadcrumbs(items):
    return {"items": items}
