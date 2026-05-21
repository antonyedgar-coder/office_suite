"""Display labels for clients in notifications and messages."""

from __future__ import annotations


def format_client_name_pan(client) -> str:
    """e.g. 'Acme Pvt Ltd — PAN ABCDE1234F' or name only if no PAN."""
    name = (getattr(client, "client_name", None) or "").strip() or "—"
    pan = (getattr(client, "pan", None) or "").strip().upper()
    if pan:
        return f"{name} — PAN {pan}"
    return name


def format_task_client_suffix(task) -> str:
    return format_client_name_pan(task.client)
