from django.urls import reverse


def breadcrumbs(*items: tuple[str, str | None]) -> list[dict[str, str]]:
    """Build breadcrumb items: (label,) or (label, url_name). Last item has no url."""
    result: list[dict[str, str]] = []
    for item in items:
        if len(item) == 1:
            result.append({"label": item[0]})
        else:
            label, url_name = item[0], item[1]
            if url_name:
                result.append({"label": label, "url": reverse(url_name)})
            else:
                result.append({"label": label})
    return result
